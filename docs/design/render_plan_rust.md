# Design: the Rust render plan (moving the render walk to Rust)

## What this is and why

Citry's warm (repeat) render runs almost entirely in Python: it walks a tree of
node objects and turns values into HTML. After two optimization passes the large
page renders in about 13.7 ms, roughly 1.3x a bare Django template, and
[`performance.md`](performance.md) section 6 found that further Python-level
tuning is at or below the render noise floor. The one remaining structural lever
is to run the node walk in Rust.

This document defines the **render plan**: a compiled, host-agnostic form that a
Rust executor walks instead of the Python node tree, calling back into the host
language only for the work that cannot leave it. It also records a working,
in-repo **prototype** that implements the core of the design and measures it.

There are three reasons to want this, only one of which is raw speed:

1. **Parity.** The Rust walk does the string assembly, attribute formatting,
   escaping, and joining; the expression evaluation stays in Python. The
   realistic single-thread ceiling is roughly Django parity, not a beat, because
   the expression-eval floor stays in Python (see section 6.7 of
   [`performance.md`](performance.md)).
2. **Portability.** The plan carries no host-language source and no host object
   references, so the same Rust executor serves Python, JS, PHP, and Go behind a
   thin per-language callback layer. Moving the walk to Rust and easing the port
   to other host languages are the same piece of work.
3. **Parallelism (add-on).** A plan with no shared mutable state and a
   document-ordered dependency merge does not foreclose a future `rayon` walk
   over independent sub-trees, which the Python GIL makes impossible today.

The contract below is designed for the whole walk. The prototype implements the
smallest slice that validates it.

## Findings so far

The prototype was built up in steps, each one byte-identical to the Python engine
on its test bodies: (1) static text plus `{{ expr }}` interpolation, (2) simple
element attribute regions, (3) control flow (`<c-if>`/`<c-for>`) with recursion,
(4) driving a whole component tree across `<c-child>` boundaries, (5) slots and
fills. The measured per-call speedups (Rust walk vs the equivalent Python walk,
plan held on both sides so only the walk is timed):

| what is walked | speedup | note |
|---|---|---|
| interpolation-heavy body | ~1.3x | bounded by the Python expression-eval floor |
| attribute-heavy body | **~1.8x** | the strongest result, and the axis June never tested |
| control flow (if / for / nested) | ~1.3x | recursion and loop-variable scoping stay faithful |
| component tree, small components | **~1.03x** | construction-bound: almost no win |
| component tree, rich bodies | ~1.16x | the win returns in proportion to body work |
| slot tree (fills, looped components) | ~1.0x | correct, but the fill body stays Python |

Three things were learned:

1. **The body walk is a real lever; attributes most of all.** Doing string
   assembly, escaping, and attribute formatting in Rust beats Python by 1.3x to
   1.8x. Attribute formatting (~1.8x) pushes back on section 6.4's "marginal,
   defer" reading, at least for simple (non-`class`/`style`) attributes.
2. **The inter-component drive is NOT a lever.** Moving the across-components walk
   to Rust buys almost nothing for a page of many small components (~1.03x),
   because each component's cost is Python construction plus `template_data`,
   which both sides pay equally. The body walk Rust speeds up is a sliver. This is
   the concrete, measured form of section 6.5's "~70-80% is irreducibly-Python
   component machinery".
3. **Const-folding is output-preserving.** Folding only pre-computes; it never
   changes the output. So an unfolded plan walked over the unfolded body yields
   byte-identical HTML to the real folding engine, which is what makes the
   prototype simple (no fold-alignment problem).

Strategic read: the render plan's value is the **within-body string work**
(attributes especially), **portability** (a host-agnostic walk other languages
reuse), and **a clean contract**, not the inter-component drive. The result also
tempers the parallelism case: if a page's cost is mostly per-component
construction in Python, even a parallel Rust walk re-acquires the GIL for it.

## Recommendation (go or no-go)

Measured against the plan's framing (parity, portability, parallelism, with
"parallelism + parity is enough" as the bar):

- **Speed / parity: no-go as a speed play.** The realistic single-thread ceiling
  is roughly Django parity, which `performance.md` section 6.7 predicted and this
  prototype confirms with a sharper finding: a real page's render cost is
  dominated by per-component Python machinery (constructing the instance and
  running `template_data`) that both the Python and Rust walks pay equally. The
  one genuine Rust lever is within-body string work (attributes ~1.8x, the rest
  ~1.3x), but attribute formatting is only ~7% of the render (section 6.4), so the
  page-level win is small. The dependency choreography is a regression. A full
  Rust render port does not buy a meaningful speedup.
- **Parallelism: no-go for now.** Same finding: if the dominant cost is
  per-component Python construction, even a `rayon` walk re-acquires the GIL for
  it, so the parallel ceiling is low on a typical many-small-component page.
- **Portability: conditional go, but deferred.** The render-plan contract is
  host-agnostic and works end to end (byte-identical, including the component tree
  and slots). If and when porting citry to JS/PHP/Go becomes a concrete priority,
  the render plan is the right vehicle and this prototype is the reference. But it
  is a large project whose payoff is portability, not speed, so it should wait for
  that goal to be real.

**The pivot.** The decisive finding redirects the effort: the render is
construction-bound, and construction is Python, so the higher-value work is
reducing the per-component Python construction cost, not moving the walk to Rust.

**Net:** keep the prototype and contract as the reference for a future
portability-driven port; do not pursue the full Rust render port as a speed or
parallelism play now. The one tactical Rust option worth keeping in mind is
attribute formatting (~1.8x on attribute-heavy content), and only if a profile
ever shows attributes dominating a real page.

## Where the plan is produced

The compiler already has the right seam. `compile_template_body`
([`compiler.rs`](../../crates/citry_template_parser/src/compiler.rs)) walks the
parsed template and returns a language-agnostic `Vec<LangSpecArgument>` (the
codegen intermediate form in
[`lang.rs`](../../crates/citry_template_parser/src/lang/lang.rs)). Only *after*
that does `LangImpl::compile`
([`python.rs`](../../crates/citry_template_parser/src/lang/python.rs)) turn the
intermediate form into the `def generate_template(): body = [...]` Python source
string that today builds the runtime node objects.

The render plan is a **new serializer of that same intermediate form**, emitted
as a sibling output that coexists with the string codegen. It reuses everything
`compile_template_body` already resolved (control-flow grouping, string
coalescing, used-variable de-duplication), which the raw parse tree has not.
It is exposed to Python as `compile_render_plan`, a sibling of `compile_template`
in [`citry_core_py`](../../crates/citry_core_py/src/render_plan.rs).

A load-bearing consequence: the plan body and the Python `generate_template()`
body list are produced from the *same coalesced intermediate form*, so they line
up one-to-one by position. Plan entry `i` describes the same body item as Python
node `i`. The executor uses that to reach a live Python node when it must call
back (evaluate an expression, render a not-yet-modelled node).

## The plan (what the Rust executor walks)

The plan is immutable and compiled once per `(class_id, ConstSignature)`, shared
across every render with that signature. It is **identity-free**: no render id,
component id, or scoped CSS hash appears anywhere (those are spliced in at
serialize time, see [`serialize.py`](../../packages/py/citry/citry/serialize.py)),
so one plan is safe to share. It is the *output* of the Python const fold (the
cache value): `Text` entries are already-baked constant text, and live nodes
remain.

The full node set the contract targets (the prototype models a subset, see
below):

```rust
enum PlanNode {
    Text(StrId),                                       // baked literal; no crossing
    Expr   { expr: ExprId, used_vars, span },          // {{ }} -> Python eval -> classify/route
    ElementAttrs { attrs: Vec<AttrFrag>, fold_attrs, span },
    If  { branches: Vec<Branch>, span },               // branch chosen at render time
    For { each: ExprId, targets, body: BodyId, empty, span },
    Component { name, attrs, body: BodyId, contains_fills, span },
    Slot { name: NameSrc, required, data, fallback_body: BodyId },
    Fill { name: NameSrc, data_var, fallback_var, body: BodyId },
    ForeignNode { handle: ForeignNodeId, span },       // extension-injected: opaque Python render()
}
```

`ExprId` and `ForeignNodeId` index a per-plan table of host callables; they are
never inlined source. `Component`, `Slot`, and `Fill` never fold to text (every
render mints a fresh child with a fresh render id and re-merged dependencies),
but their bodies may be pre-folded. `fold_attrs` on `ElementAttrs` is false when
an extension subscribes to `on_attrs_resolved` (subscribing disables the
attribute-region fold), so the plan shape depends on the installed-extension set
and must be invalidated when it changes.

## Identity: stable handles instead of Python `is`

The render walk and the serializer both lean on two Python object-identity
checks. A Rust walk replaces them with stable handles:

- `part.context is not context` (the trigger to merge a foreign render's
  dependencies) becomes a **context handle**: a small integer minted when a
  `CitryContext` is created. Foreign means the handles differ.
- `part.context.component is not comp` (the serialize frame boundary) becomes the
  existing **`component.id`** string (`gen_render_id`, for example `c1A2b3c`),
  which is already what serialization emits as `data-cid-<id>`.
- `is_component_root` stays an **explicit boolean** on the render value. It
  cannot be derived from the handles, because slot-fill content deliberately
  carries the *writer's* context and component, so a foreign component does not
  imply a child frame.
- The const-cache class key uses **`class_id`** (`ClassName_<md5[:6]>`), a
  deterministic string, so Rust never needs a Python type object.

A handle table on the per-render executor maps a handle back to the live Python
object for the callbacks that need it.

## The callback ABI (what stays in the host)

Everything that depends on live host objects stays in the host and is reached
through a narrow, enumerated set of callbacks. Each hot one is gated by a
subscriber flag baked into the plan, so a page with no extensions makes zero hook
crossings.

| callback | when / frequency | crosses |
|---|---|---|
| `eval_expr` | per `{{ }}` / attr expr / `c-if` cond / `c-for` clause (hottest) | the compiled evaluator `callable(vars) -> Any`; `vars` is the real mutable dict (walrus assigns to it) |
| `render_value` | after each non-`str` eval result | mirrors `_render_value`: None -> empty, Slot -> invoke, element -> render, else escape |
| `template_data` | once per component | returns the component's variable scope |
| `component_input` / `component_data` / `component_rendered` | once per component (rendered may repeat on a generator requeue) | the component handle; `data` writes the component's own dependency record |
| `render_context_merge` | the two merge sites (cross-context body part; child commit) | two collector handles; the merge is order-preserving and idempotent |
| `invoke_slot` / `on_slot_rendered` | per `<c-slot>` site | the slot handle; provides nearest-wins applied host-side |
| `on_attrs_resolved` | per dynamic-attr element, only when subscribed | the resolved attribute dict (may be rewritten) |
| `on_serialize` | once at the serialize root | the joined HTML (may be rewritten) |
| `collect_fills` | per `Component` with `contains_fills` | runs live `c-if`/`c-for` to decide which fills exist |
| `drive_on_render` | per component with a live `on_render` generator | resumes the Python coroutine; the deepest coupling |

What stays in Python, in full: expression evaluation and the sandbox checks;
`template_data`/`js_data`/`css_data`; the `on_render` generators; slot and fill
closures and user-supplied slot callables; provide/inject; every extension hook
and the dependency-collection merge policy; the const fold (the `wrapt` proxy has
no Rust analogue, so folding stays a build-time Python step that *produces* the
plan); `markupsafe` escaping of values is matched in Rust for the scalar path but
the `__html__` trust protocol is honored.

## Dependencies: a merge that does not foreclose parallelism

Today the JS/CSS dependency records live in one insertion-ordered set on
`CitryContext.extra`, written as each component renders and merged child to parent
through the `on_render_context_merge` hook, with first-seen-in-document-order
de-duplication. The contract keeps that as host-owned, but models accumulation as
**per-subtree-local collectors merged in deterministic document order** rather
than one shared bag, with document position carried explicitly so a parallel walk
re-imposes the same first-seen-by-position order regardless of which sub-tree
finishes first. The slot-fill case (a fill writes into the *writer's* collector,
not the slot site's) becomes an explicit collector edge instead of an aliased
Python reference. Run sequentially, this is exactly today's behavior; it just does
not bake in the single-shared-bag assumption.

## Portability

The plan contains no host syntax (expressions are opaque callable handles, not
source strings) and no host object references (identity is integer handles and
plain strings). So the Rust executor (the walk, the deferred-child queue, the
document-ordered collector merge, the error bubble, and serialize marking via the
existing `citry_html_transform` crate) is shared across hosts, and each host
supplies only a thin shim implementing the callback ABI for its own object types.
The compiler already targets the five language enum values; the plan serializer is
one more sibling output, and the only one that is host-agnostic.

## The prototype (in repo, runnable)

The prototype is the smallest slice that validates the contract end to end. It is
new code alongside the real packages, and does not rewire the live runtime.

- [`crates/citry_template_parser/src/render_plan.rs`](../../crates/citry_template_parser/src/render_plan.rs)
  lowers the intermediate form into a flat plan (`PlanNode`).
- [`crates/citry_core_py/src/render_plan.rs`](../../crates/citry_core_py/src/render_plan.rs)
  exposes `compile_render_plan` and a `RenderPlan` class whose `render()` walks
  the plan in Rust.
- [`packages/py/citry/citry/_proto/`](../../packages/py/citry/citry/_proto/) holds
  the harness: it compiles a template both ways (the live node list and the plan),
  runs the Rust walk and the Python `_render_body` over the same body, and checks
  the output is byte-identical before timing each.

**Modelled in Rust:**

- static text;
- `{{ expr }}` interpolation of scalar values (escaped to match `markupsafe`,
  with `None` and the `__html__` trust protocol handled);
- the attribute region of plain elements whose attributes are simple key/value
  pairs (no `class`/`style` merge, no `c-bind` spread, no nested-template value),
  where each value is resolved through its Python attribute object and the merge,
  format, escape, and join happen in Rust;
- control flow (`<c-if>`/`<c-elif>`/`<c-else>` and `<c-for>`/`<c-empty>`): the
  Rust walk recurses into the chosen branch or each loop iteration, with two small
  Python helpers reusing the real `IfNode.active_branch_body` and
  `ForNode.iter_bodies` so branch selection and loop-variable scoping stay
  faithful. Because a branch/loop body is compiled the same way as the root body,
  its sub-plan lines up by position with the node's runtime branch body, which is
  how the executor recurses;
- child components (`<c-child>`): the Rust walk drives the whole component tree.
  At a component tag a Python `prepare` helper builds the child (resolve kwargs,
  construct the instance, run `template_data`, build the context) and returns the
  child's body, context, and its own render plan; the walk then recurses into that
  plan. This relies on const-folding being output-preserving, so the unfolded
  child body walked against its unfolded plan yields the same HTML as the real
  (folding) engine;
- slots and fills (`<c-slot>`/`<c-fill>`): handled correctly, though the fill body
  is rendered by Python. A `<c-slot>` is walked as a foreign node: a Python helper
  calls the real `SlotNode.render` (which does the fill lookup and renders the
  fill body in the writer's scope, the part that genuinely cannot leave Python),
  and the result is resolved to a string with no markers. A component inside a
  fill comes back as a deferred child and is driven through the same Rust walk, so
  a fill that contains a whole component subtree renders. Named/default slots,
  fallbacks, conditional fills, slot data, and slots used in `{{ }}` all work
  byte-identically; they just get no Rust speedup, since the fill-body assembly
  stays Python.

**Left to Python:** `on_render` hooks (the prototype refuses them), nested-template
attribute values, and any `class`/`style`/`c-bind` attribute region. These are
rendered by calling the live Python node, so the executor stays correct on any
body while the modelled fast path avoids the per-node Python round trip.

### How to run it

```
cd packages/py/citry_core && uv run maturin develop --release   # release is mandatory for timing
python -m citry._proto.ab_harness
```

A debug build makes the Rust paths much slower and the numbers meaningless (see
[`benchmarking.md`](benchmarking.md)); always measure on `--release`.

### What it found

Apple M4, CPython 3.13, release build, best-of-N per-call wall-clock, plan held on
both sides so only the walk is timed (one representative run; the two tiny cases,
static-heavy and button, are in the single-microsecond range and swing a few
percent run to run):

| body shape | byte-identical | Python | Rust | speedup |
|---|---|---|---|---|
| expr-heavy | yes | 63.0 us | 48.3 us | 1.30x |
| static-heavy | yes | 7.5 us | 6.8 us | 1.10x |
| mixed | yes | 62.8 us | 46.7 us | 1.34x |
| attr-heavy | yes | 387.7 us | 210.7 us | 1.84x |
| if-heavy | yes | 134.2 us | 102.3 us | 1.31x |
| for-heavy | yes | 122.9 us | 92.7 us | 1.33x |
| nested | yes | 169.0 us | 133.1 us | 1.27x |
| button | yes | 1.2 us | 0.9 us | 1.29x |

Three things stand out:

- The interpolation results (around 1.3x) reproduce the June throwaway
  prototype's range (1.10x to 1.33x, section 6.7 of
  [`performance.md`](performance.md)). The interpolation win is bounded because
  the expression evaluation stays in Python.
- The attribute-heavy body is the strongest result at **~1.8x**, and it is the
  axis the June prototype never measured. Even paying one Python crossing per
  attribute to resolve its value, doing the merge, formatting, escaping, and
  joining in Rust beats the Python attribute path by a wide margin. This is a
  useful push-back on the earlier "attribute formatting is marginal, defer"
  reading (section 6.4): for simple attribute regions it is the best Rust
  candidate found so far. The caveat is that `class`/`style` normalization (the
  Python-heavy part) is exactly what the prototype leaves to Python, so the ~1.8x
  is for the simple-attribute case, not the structured-value case.
- Control flow (`if-heavy`, `for-heavy`, and the `nested` for-loop-with-inner-if)
  lands around 1.3x and is byte-identical, including the `nested` case where the
  loop variable has to reach a conditional inside the loop body. That confirms the
  Rust walk drives the in-body control flow and recursion correctly, with Python
  doing only the branch selection and the loop-iteration evaluation. So the full
  in-body machinery (text, interpolation, attributes, conditionals, loops, and
  nesting) now runs in Rust with the host called only where it must be.

### Driving the whole component tree (and where that stops paying off)

The walk also drives across component boundaries. Here the comparison is the Rust
drive against an equivalent Python drive (both use the same `prepare` helper, so
only the walk differs), with the output checked three ways: Rust drive ==
Python drive == the real engine's resolved tree, flattened. The components are
simple (no slots, no `on_render`, no dependencies), and the body node list is
cached per class as the real engine caches its folded body, so the per-component
cost is construction plus the walk, not a node rebuild.

| component tree | byte-identical | Python | Rust | speedup |
|---|---|---|---|---|
| comp-list (120 small components, looped) | yes | 428 us | 407 us | 1.05x |
| comp-nested (3-level tree, ~160 small components) | yes | 578 us | 563 us | 1.03x |
| comp-rich (60 components, 8 interpolations each) | yes | 472 us | 406 us | 1.16x |

The result is the most decision-relevant of the whole prototype: **moving the
inter-component drive to Rust buys almost nothing for a page of many small
components** (1.03x-1.05x), because each component's cost is dominated by Python
work both sides pay equally: constructing the instance and running
`template_data`. The body walk, the only part Rust speeds up, is a sliver of that.
The win returns only in proportion to per-component body work (`comp-rich`, with
eight interpolations per component, recovers some of the within-body speedup at
1.16x). This is the concrete, measured form of section 6.5's "~70-80% is
irreducibly-Python component machinery": the lever is the body walk, not the
drive, and the large benchmark is a page of many small components.

## Dependency collection and merge in Rust (a separate probe)

The dependencies extension's hot path reduces to one operation: collapse the
collected `DependencyRecord`s (a NamedTuple of four strings) to their distinct
set, keeping first-seen order (`dict.fromkeys` at resolve, `dict.update` at each
merge). A prototype Rust module
([`deps_proto.rs`](../../crates/citry_core_py/src/deps_proto.rs), bench in
[`_proto/deps_bench.py`](../../packages/py/citry/citry/_proto/deps_bench.py))
reimplements that dedup and measures it.

| scenario (distinct x bubble levels) | Python dedup | Rust dedup (records from Python) | Rust native (records in Rust) |
|---|---|---|---|
| realistic, 71 x 40 | ~35 us | ~217 us (**0.16x**) | vs Python build+dedup: ~1.3x |
| deep, 71 x 2000 | ~1.7 ms | ~10.8 ms (**0.15x**) | ~1.4x |
| wide, 1000 x 10 | ~143 us | ~832 us (**0.17x**) | ~1.3x |

The result is decisive: **moving only the dependency dedup/merge to Rust is about
a 6x regression** (the "Rust dedup" column). The records are Python objects;
marshalling the list across the boundary costs far more than Python's in-process,
C-backed `dict.fromkeys` saves. This is the same pattern section 6.3 predicted for
already-C paths. Even in the best case, where the records already live in Rust (a
full render-in-Rust port, the "native" column), the dedup/merge is only about
1.3x faster, and that figure still includes record construction, whose fields come
from Python data. The choreography is also just cheap: a realistic render's
records dedup in tens of microseconds. So the dependency collection and merge is
not a lever, in isolation or as part of a full port.

This also answers a question about the serialize phase: the dependency portion of
serialize (the dedup and resolution) is small and Python-bound (registry lookups,
`Dependency.render()`), so it is not where a Rust serialize would pay off either.

## Honest assessment

Judge this work on portability plus parallelism headroom plus a clean
host-agnostic contract, with the attribute-axis number as the standout speed
result, not on warm-render speed alone. The expression-eval floor keeps the
single-thread ceiling near Django parity, which is exactly why the prior
throwaway prototype read as "sub-threshold." The prototype's value is making the
implementation and the callback boundary concrete, confirming the per-expression
and per-attribute crossings are affordable, and surfacing the attribute axis as a
better candidate than expected.

## What the prototype deliberately does not yet cover

These are the open ends, in rough order of how much they would change the picture:

- **The `on_render` hooks** (the per-component before/after hook, in its hardest
  form a live Python generator with a requeue loop) are refused by the prototype's
  `prepare`. This is the remaining frontier of correctness.
- **Slots that are not Rust-accelerated.** Slots render correctly (see above), but
  the fill body's string assembly stays in Python (the `_make_body_slot` closure
  captures the writer's live context, which cannot move). Routing a fill's
  dependencies to the writer's collector is also still Python.
- **`class`/`style`/`c-bind`** attribute regions stay in Python; whether their
  structured-value normalization is worth moving is unmeasured.
- **The production-grade inter-component machinery.** The basic component drive
  works (Rust walks the tree, byte-identical), but it uses native Rust recursion
  and a simplified `prepare`. It does not reproduce the deferred-child queue (so
  very deep trees would hit the native stack), post-order finalize and
  `on_component_rendered`, dependency collection and the upward merge, or the
  error bubble. These do not change the speed conclusion (they are Python work on
  both sides), but a real port has to carry them.
- **Parallelism** is designed for but not implemented; the document-ordered
  collector merge is written to be associative and order-keyed, but runs
  single-threaded. Note the component result above tempers the parallelism case:
  if a page's cost is mostly per-component construction in Python, even a parallel
  Rust walk re-acquires the GIL for that work.

## Production migration: locked design and status

The prototype validated the walk; turning it into the real body engine means
solving two things the prototype skipped. (1) It returns a flat `String` and
drives children inline; production must emit the `list[RenderPart]` that
`_render_body` produces (preserving `DeferredComponent`, `Placeholder`, and
cross-context `CitryRender` parts, the inline dependency merge, and the
error-position attachment), or it breaks the deferred-render queue and serialize.
(2) It walks the *unfolded* body (re-doing const work every render); production
must walk the const-*folded* body (the `ConstBodyCache` value), so the Rust side
cannot use the prototype's position-aligned plan.

The chosen design walks the folded body directly with a precomputed `kinds`
array, and matches `_render_body` part-for-part:

- **`kinds`** classifies each folded item once (cached without changing the
  `ConstBodyCache` value shape, which tests assert on): `"text"` (a static
  string), `"attrs"` (a *simple* `ElementAttrsNode`: no `class`/`style`/`c-bind`/
  nested-template attribute, and no `on_attrs_resolved` subscriber, mirroring the
  `fold_attrs` gate), `"expr"`, or `"node"`.
- The Rust walk emits one part per item: `"text"` -> the string as a part;
  `"attrs"` -> resolve each attribute (`attr.key` minus a `c-` prefix gives the
  output key) and format in Rust (reuse `format_attrs_into`); `"expr"` ->
  `node.evaluate(variables, sandboxed=context.sandboxed)`, unwrap `Const`, then
  `None` -> empty, a `Slot`/`CitryElement`/`CitryRender` -> delegate to a Python
  helper that runs `_render_value` plus the cross-context merge, anything else ->
  `escape_to_str_into` in Rust; `"node"` -> delegate to `_render_node`.
- **`_render_node`** (`component_render.py`) is the Python delegate callback for
  every kind the walk does not model: it is the extracted per-node step of
  `_render_body` (render, attach error position, merge cross-context deps). It is
  the fallback that keeps the engine correct on any body.
- The Rust function is handed the `_ConstProxy` class (for the unwrap) and the
  `(Slot, CitryElement, CitryRender)` types (for the special-value check), plus
  the `_render_value` and `_render_node` callbacks. Reuse the prototype's
  `escape_html_into` / `escape_to_str_into` / `format_attrs_into` verbatim.
- **Seam:** `_render_one` at the `_render_body(body, context)` call, behind a
  per-Citry capability flag (default off until byte-identical across the suite).

Workstream A (the optional expression sandbox, `Citry(sandbox_expressions=False)`)
is shipped and threads `sandboxed` to every eval site through `CitryContext`.

### Built, and what it measured

The production body engine is implemented (`BodyEngine` + `FoldedPlan` in
`crates/citry_core_py/src/render_plan.rs`, the seam in `component_render.py` behind
the default-off `USE_BODY_ENGINE` flag). It is byte-identical to `_render_body`
across the whole rendering suite (823 tests) and the 203 KB benchmark.

The first cut walked the folded Python body item-by-item and was **~3-6% slower**:
the per-item `get_item` + `isinstance` FFI exceeded the string-work savings. The
fix was to **pre-lower the folded body once** into a `FoldedPlan` (text owned by
Rust, nodes classified once and kept as references), cached per body, so the walk
has no per-item classification crossing. That moved it to:

| workload | engine off -> on | result |
|---|---|---|
| large benchmark (construction-bound) | 12.5 -> 12.7 ms | ~parity (0.98-1.0x) |
| markup-heavy (40 components x 24 attrs + 12 interp) | 1.13 -> 1.06 ms | **1.06x** |

So the engine reaches parity on a real construction-bound page and wins ~6% where
string work dominates (the attribute/interpolation-heavy regime the prototype's
1.8x came from, attenuated by the unavoidable per-component crossings). This is
exactly the document's "roughly parity, not a beat", now confirmed with a
production measurement rather than an isolated-walk one.

The engine stays behind the default-off flag: it is a marginal win (parity to
1.06x) that does not justify flipping on by default, and it is the validated,
byte-identical foundation for a future portability port. Promoting it to an opt-in
`Citry` setting (with a per-instance plan cache replacing the module-level one) is
the remaining step if a markup-heavy workload wants it. Control flow (`If`/`For`)
is still delegated to Python rather than modelled in Rust; modelling it would add a
little more to the markup-heavy win and nothing to the construction-bound case.
