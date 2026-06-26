# Design: render performance and optimization

**Status (2026-06-22): two optimization passes done (repeat render 19.63 -> ~13.7
ms, 1.85x -> 1.29x a bare Django template); render-walk-in-Rust prototyped and
scoped (section 6).** The first pass fixed render-path hot spots (section 4); a
second trimmed per-component fixed overhead (section 4.7). A Rust prototype
(section 6.7) then sized the architectural lever and tempered two earlier,
over-optimistic conclusions in this doc: the Rust-movable part of the render is
~20-30% (string assembly and traversal), not ~85% (the rest is the
irreducibly-Python component model), and the per-expression sandbox check is
value-dependent, not compile-time-resolvable. Net: there is no cheap path to
parity. The Rust render walk reaches *roughly* Django parity (not a beat) and is
the only route to parallelism, but it is a large project moving the
compiler-output contract; the smaller levers (a security-sensitive runtime
sandbox fast path ~2-3%, remaining Python micro-opts) do not add up to parity.
The decision was framed as binary, commit to the Rust-walk project or accept
~1.3x. A third lever has since shipped: citry renders each component body by
running a Python function generated from it, rather than walking the body's node
list (section 6.10), the Python-side version of the Rust walk. A few percent on
a real page (more on static- and loop-heavy templates), not parity, at near-zero
risk. This
document records what changed and why, the cost model, and that analysis.

This doc is about **consciously making the render faster**. It is the
companion to two neighbours, and the split matters:

- [`benchmarking.md`](benchmarking.md) is about **measuring**: where the
  benchmark code lives, how the harness runs it, what the scenarios contain.
  It answers "how fast are we, relative to Django and django-components".
- This doc is about **optimizing**: where the time goes, what we changed to
  spend less of it, and what is left. It answers "why are we that fast, and
  how do we get faster".
- [`constness.md`](constness.md) is one specific optimization (marking inputs
  constant so template parts that depend only on them are computed once and
  reused). It predates this doc and stands on its own; section 4 here does not
  repeat it.

For operating rules see [`/CLAUDE.md`](../../CLAUDE.md).

---

## 1. How to measure (reproducing the profile)

Two tools, used together. Neither is wired into CI; both run on demand against
the large benchmark scenario
([`packages/py/citry/tests/test_benchmark_citry.py`](../../packages/py/citry/tests/test_benchmark_citry.py)),
which is the biggest real template citry renders.

**1. cProfile, for "where does the time go".** Load the scenario module, warm
it once (so templates are compiled and caches are filled), then profile a
batch of renders and sort by `tottime` (time inside a function itself) and
`cumtime` (time including everything it calls):

```python
import cProfile, pstats, importlib.util, sys
spec = importlib.util.spec_from_file_location("bc", "tests/test_benchmark_citry.py")
m = importlib.util.module_from_spec(spec); sys.modules["bc"] = m; spec.loader.exec_module(m)
data = m.gen_render_data(); m.render(data)            # warm up
pr = cProfile.Profile(); pr.enable()
for _ in range(10): m.render(data)
pr.disable()
pstats.Stats(pr).sort_stats("tottime").print_stats(20)
```

cProfile inflates absolute time (per-call instrumentation overhead), so read
it for **relative** weight and call counts, never as a wall-clock number. Its
two most useful follow-ups are `print_callers(name)` (who calls this hot
function) and watching a call count fall after a change.

**2. In-process A/B timing, for "did this change actually help".** cProfile's
overhead hides small wins, so confirm each change with a plain timer that
renders the warm page many times and keeps the best run (the least
noise-affected). Measure the same change both ways: swap the new code for the
old in-process (a monkeypatch on the hot method is enough) so the only
variable is the code under test, not process startup or GC timing.

The authoritative cross-engine numbers still come from
`benchmarks/compare.py` (fresh subprocess per cell, median of 5); the two
tools above are for finding and sizing a change before it reaches that table.

## 2. The render-path cost model

A repeat (warm) render runs almost entirely in Python: parsing happens once at
compile time in the Rust core, and the compiled template is a tree of Python
node objects that execute on every render. So a warm render's cost is the cost
of walking that tree and turning values into HTML.

The work splits into two kinds, and the split is the whole strategy:

**Optimizable overhead** (Python doing more work than it needs to):

- **Attribute resolution and formatting.** For every element with dynamic
  attributes, citry resolves each attribute, merges the contributions
  (`class`/`style` accumulate), and formats the result. The structured
  `class`/`style` values (the React/Vue-style lists and dicts, see
  [`html_attrs.md`](html_attrs.md)) are normalized here with a chain of type
  checks.
- **HTML escaping.** Every dynamic value and attribute value is escaped before
  it reaches the output. The escaping itself is C-accelerated (markupsafe),
  but each result is wrapped in a `Markup` object (a trusted-HTML string
  subclass), and those wrappers add up.
- **Expression evaluation.** Each `{{ expr }}` and `c-*` attribute runs a
  compiled function through safe_eval. The compilation is cached; the
  per-call wrapper that adds error context is not free.
- **Type dispatch.** The render path is full of `isinstance` checks (to tell a
  rendered subtree from a raw value, a const-marked value from a plain one,
  and so on). Individually tiny, collectively the single most-called built-in.

**Irreducible component machinery** (work a bare Django template does not do
at all, which is the reason citry is a component engine):

- **The marking pass.** At serialize time citry walks the render tree and
  inserts a `data-cid-<id>` attribute on each component's root element, so CSS
  and JS can scope to an instance. Django emits flat HTML with none of this.
- **Dependency collection.** Each component reports the JS/CSS it needs; those
  reports are gathered and turned into `<script>`/`<style>` tags or a manifest
  (see [`dependencies.md`](dependencies.md)).
- **Per-component construction and slots.** Each instance is constructed,
  given an id, linked to its parent, and has its slots/fills resolved across a
  context boundary.

The optimizable overhead is where Python-level fixes pay off (section 4). The
irreducible machinery is the floor: it can be made cheaper but not removed
without dropping the feature, and getting *below* a bare template means moving
some of it into Rust (section 6).

## 3. The ceiling, and what actually sets it

After the passes in section 4, citry's repeat render is about 1.29x a bare
Django template and about 3.4x faster than django-components (the fair
comparison, since both pay the component cost).

It is tempting to call the rest "the structural cost of Python components," and
an earlier version of this doc did. Measurement (section 6.5) shows that is
wrong. The genuinely unavoidable Python work, the data callbacks
(`template_data`) and expression evaluation, is only ~10% of the render. The
other ~85% is **render-walk machinery** (tree traversal, type dispatch,
attribute formatting, string assembly, per-component construction and hooks):
mechanical work that merely happens to run in a tree of Python objects. So the
gap to Django is largely reducible, and matching or beating a bare template is
reachable, but not by trimming Python further. It means running the walk itself
in Rust, which moves the compiler-output contract (the compiler emits Python
node classes today, see [`rendering.md`](rendering.md)). Section 6 scopes that
move and the prototype that de-risks it.

## 4. Optimizations done (2026-06-22 pass)

Each change below was verified to leave the rendered HTML byte-identical (the
output is the contract; only the work behind it changed) and sized with the
A/B timer. They are listed biggest win first. The cross-engine table is in
[`benchmarking.md`](benchmarking.md) section 11; the per-change deltas here are
from the in-process A/B timer on this machine and are directional.

### 4.1 Dependency collection: O(n*depth) to O(n)

The largest win (~3.2 ms). Each component reports a dependency record, and
those records bubble up to every ancestor as nested renders merge into their
parents. The merge copied the child's whole record list into the parent, so a
record at depth *d* was re-copied at each level above it. On the 325-instance
page this built **469,583 record copies**, and the final de-duplication ran
over **154,120 entries** to recover the 71 distinct records.

The fix holds each render context's records as an **insertion-ordered set** (a
`dict` used for its keys) instead of a list. The merge becomes a set union, so
it de-duplicates on insert and is idempotent: a record that has already
bubbled through is not copied again. The accumulation can no longer multiply,
and emission reads the 71 distinct records directly.

An earlier fix (a prior session) had de-duplicated the records *before* the
expensive per-record script lookup, which removed the wasted lookups but left
the list itself blowing up. This change removes the blow-up at its source.
Code: [`citry/extensions/dependencies/__init__.py`](../../packages/py/citry/citry/extensions/dependencies/__init__.py)
(`on_component_data`, `on_render_context_merge`).

### 4.2 Element attributes format in one pass

The element renderer formatted attributes one at a time: it called
`format_attrs({key: value})` once per attribute, and each call escaped, joined
a single piece, allocated a `SafeString`, and was concatenated with a leading
space. For an element with three attributes that is three of everything.

It now formats the whole resolved attribute dict in a single `format_attrs`
call for the common case (no attribute value is a nested-template render),
falling back to the per-attribute path only when a nested template is present
(those keep their parts so components inside them stay deferred). One escape
pass, one join, one allocation per element. Code:
[`citry/nodes/__init__.py`](../../packages/py/citry/citry/nodes/__init__.py)
(`ElementAttrsNode._format`).

### 4.3 Escape to a plain string, not a Markup, in format_attrs

`format_attrs` escapes each attribute key and value into an f-string and wraps
the whole joined result as one `SafeString` at the end. The individual
`escape()` calls therefore allocated a `Markup` per key and per value only to
have it immediately turned back into a plain string by the f-string: pure
allocation.

A new helper, `escape_to_str`
([`citry/util/html.py`](../../packages/py/citry/citry/util/html.py)), runs the
same escaping but returns a plain `str`. It uses markupsafe's own inner
escaper (the routine `escape` calls before wrapping the result), with a
fallback to the public `escape` if a future markupsafe removes the name, so
the escaping stays exactly markupsafe's. Use it only where the escaped text is
concatenated into a larger string that is marked safe as a whole, so the
unmarked piece is never re-escaped; for a value that becomes output on its
own, `escape` is still correct. `Markup` allocations across the render dropped
about 78%.

### 4.4 Cheaper component ids

Each component instance gets a short random id for its `data-cid` marker. This
used nanoid, which makes a `urandom` syscall and recomputes its
rejection-sampling math on every call, about 342 times per render. These ids
scope DOM and CSS to an instance; they are not secrets. `gen_id` then switched to
`random.choices` over the same alphabet, which is uniform, has the same id
space (so the same collision odds), and is about 4x faster with no syscall.
(A later pass replaced `random.choices` with a counter off a random base, faster
again and the current scheme; see section 8 and
[`util/id.py`](../../packages/py/citry/citry/util/id.py).)

### 4.5 Port side: hoisting render-invariant constructions

Not an engine change, but the idiomatic thing a citry user would do: a value
that is the same on every render of a component does not belong in
`template_data`. In the benchmark port the breadcrumb home icon (a fixed
`Icon`) is now built once at module load. A sweep of the port found it was the
only pure-literal *component* construction; the other invariants are the
literal attribute dicts, which the Const variant already marks (see
[`benchmarking.md`](benchmarking.md) section 6.4). Rendering a component
instance does not mutate it, so a single shared instance is safe to reuse.

### 4.6 Tried and reverted: fusing the attribute merge

`ElementAttrsNode._resolve` builds a one-key dict per attribute and then
merges them. Fusing the merge into the resolve loop to skip those dicts was
implemented, measured as perf-neutral, and reverted. The reason is in the
profile: `_resolve`'s time is in its callees (resolving each attribute through
safe_eval), not in building the small dicts, so removing the dicts changed
nothing and only added public surface. Recorded here so it is not re-attempted
blind.

### 4.7 Per-component fixed-overhead trims (second pass)

A second pass chased the per-component fixed cost (the work a bare Django
template does not do, paid once per component, ~342 times on the large page).
Together these took the repeat render from ~14.5 ms to ~13.7 ms.

- **Lazy extension-hook contexts.** Each per-component hook dispatcher
  (`on_component_rendered`, `on_slot_rendered`) built its context dataclass and
  fired the event even when no installed extension implements the hook. With
  only the dependencies extension installed, those fire for nobody. They now
  check `has_hook` first and return early, skipping the build
  ([`citry/extension.py`](../../packages/py/citry/citry/extension.py)).
- **Cached strategy validation.** `serialize_render` validated its
  `deps_strategy`/`deps_position` against `get_args(<Literal>)` on every call;
  the allowed values are computed once into module constants
  ([`citry/serialize.py`](../../packages/py/citry/citry/serialize.py)).
- **Memoized class-level dependency resolution.** `_resolve_records` rebuilt
  each *class's* `Dependencies` entries and JS/CSS for every *instance* (the
  serialize was ~57% this one function). The class-level part is now resolved
  once per class within the call and reused across its instances
  ([`citry/extensions/dependencies/emission.py`](../../packages/py/citry/citry/extensions/dependencies/emission.py)),
  cutting ~0.24 ms.
- **Tried and reverted: a cross-render version of that cache.** Persisting the
  class resolution across renders (keyed per Citry, invalidated on file reset)
  measured neutral against the within-call memo: once duplicates are collapsed
  within a render, the remaining first-sight resolution is cheap (most classes
  have no dependencies, so it is trivially empty), so caching it across renders
  saved nothing and added a weak-keyed store plus invalidation. Reverted.

## 5. Further Python-level opportunities (explored 2026-06-22)

The leads from the first pass were chased down. The finding is that the
Python-level wins are now **at or below the full-render noise floor** (about
+/- 0.2 ms on a 13.5 ms render): the big structural costs are gone, and what is
left is spread thinly across many already-tight call sites. One small cleanup
landed; the rest were measured and either rejected or judged not worth the
churn. This is the evidence that section 6 (moving work to Rust), not more
Python micro-tuning, is the next real lever.

What was investigated:

- **safe_eval per-call wrapper (landed, sub-noise).** The `error_context`
  decorator wraps every intercepted operation of every expression (variable,
  attribute, subscript, call; ~27,700 calls per render). It used to extract the
  source string and token positions from the arguments on every call, but those
  are only used to build a message when the operation raises. Moving that
  extraction into the `except` branch leaves the success path bare. Measured at
  ~7 ns per call, ~0.19 ms per render: real and strictly less work, but below
  what the full-render timer can resolve. Kept as a cleanup
  ([`citry_core/.../safe_eval/error.py`](../../packages/py/citry_core/citry_core/safe_eval/error.py)),
  not because the render got visibly faster.
- **Type-dispatch in the value-to-output path (tried, reverted).** Adding a
  "plain string, just escape it" fast path to `citry_render._render_value`
  looked obvious but was reverted: instrumenting it showed **none** of its calls
  on the real page are a plain `str`. The function exists for *composed* values
  (a `Slot`, an unrendered `CitryElement`, an already-rendered `CitryRender`);
  plain interpolated text is escaped on a different, already-direct path. The
  fast path was dead code. A good reminder to count the branch before adding it.
- **`isinstance` overall (no change).** It is the most-called built-in, but its
  weight is spread across paths that are already tight: `_render_body` checks
  `str` first and moves on; the render-tree `walk` does two checks per part that
  are inherent to telling a deferred child from a nested render; `const_value` /
  `is_const` are a single check each and exist to support the `Const` feature.
  No single reordering moved the full-render timer.
- **Attribute-merge and kwargs allocation (not pursued).** The same per-key
  allocation pattern as section 4.6 (which was measured neutral and reverted):
  `_resolve`'s and `_resolve_kwargs`'s time is in resolving each value through
  safe_eval, not in building the small dicts, so removing the dicts is expected
  to be neutral for the same reason. Left alone unless a profile says otherwise.

## 6. Candidates for moving to Rust (analysed 2026-06-22)

**Finding: the obvious string-processing paths are already in Rust, and the
per-call boundary cost rules out the remaining fine-grained moves (one would
make escaping 2x slower). The single borderline candidate is attribute
formatting, about 7% of the render, and even it is marginal. The real lever is
architectural (running the render loop itself in Rust), not a piecewise port.**

The selection rule a path must clear to be worth moving:

- **It is genuinely hot.** High call count and real `tottime` share in the
  warm-render profile, not just "feels low-level".
- **Its work is CPU on plain data, not Python-object choreography.** Moving a
  loop that mostly calls back into Python objects (user `template_data`, Python
  expressions, component instances) buys little and costs a boundary crossing
  each call. Good candidates take simple inputs (strings, the compiled node
  data) and return simple outputs.
- **Its interface is stable and narrow.** The Rust/Python boundary is a
  contract (see the high-risk areas in [`/CLAUDE.md`](../../CLAUDE.md)); a path
  still changing shape is not ready to freeze across the binding.
- **The win survives the boundary cost** (the one that does most of the work
  below).

### 6.1 What is already across the boundary

Four Rust crates back `citry_core`: `citry_template_parser` (parse and
compile), `citry_html_transform` (the marking scan), `python_safe_eval`
(expression transformation), and `citry_core_py` (the PyO3 glue). The Python
runtime imports from Rust: `template_parser.compile_template` / `parse_template`,
`html_transform.mark_html`, and `safe_eval.safe_eval`. So Rust already owns the
mechanical string work: turning a template into a node tree, scanning a
component's rendered HTML to splice in its `data-cid` markers, and turning an
expression string into safe code. What is left in Python is the **runtime**:
walking the compiled node tree and turning values into HTML.

### 6.2 The decisive constraint: the per-call boundary cost

A minimal PyO3 round-trip, measured here by calling `mark_html` on a 7-character
string, is about **177 ns** on this machine. That is the floor every crossing
pays before any useful work, so a path called N times per render starts at
177ns x N just in crossings. This is what rejects the fine-grained candidates,
and it refutes this section's own earlier guess that escaping was a starting
point:

- **HTML escaping is already C and must not move.** `escape_to_str` is about
  **87 ns end to end** (markupsafe's C escaper). A Rust escape would pay ~177 ns
  just to cross, before escaping one character: roughly **2x slower**. Escaping
  is called tens of thousands of times per render, so this is decisive.

### 6.3 Candidate verdicts

- **Already C or Rust (no win, some would regress):** HTML escaping and `Markup`
  construction (markupsafe C), the `mark_html` scan, and parsing/compilation.
  Re-porting these to Rust gains nothing and, for escaping, loses.
- **Python-object choreography (cannot move piecewise):** the render-tree walk
  (`_render_one` / `_render_body` / `walk`), expression **evaluation** (the
  compiled functions run Python against Python context data), and
  kwargs/slot/provide resolution. Each step calls back into Python objects, so
  a Rust version would cross the boundary per node, and the 177 ns floor turns
  that into a loss. These move only if the objects they walk move too (6.5).
- **Borderline, the only real piecewise candidate:** attribute formatting (6.4).

### 6.4 The one borderline candidate: attribute formatting

`format_attrs` plus the `class`/`style` normalizers are about **6.9%** of the
warm render (cProfile), at ~591 `format_attrs` calls per render. It is the most
string-like of the Python hot paths, so it is the natural thing to weigh. It
still does not clearly pay:

- Part of its cost is escaping, already C: no Rust win there.
- The `class`/`style` values are structured Python (lists and dicts of class
  names, dicts of style properties). Passing them to Rust means converting
  nested Python into Rust on every call, which costs more than the 177 ns base
  crossing.
- ~591 crossings per render is already a ~0.1 ms floor, before that conversion.

So of a roughly 1 ms prize, perhaps 0.3 to 0.5 ms would survive, in exchange for
a new function frozen into the cross-language contract. The clean shape (format
an element's *already-normalized*, strings-only attributes in Rust) needs the
normalization done in Python first, and the normalization is the Python-heavy
part, so little is left to move. Verdict: defer unless a future profile makes it
clearly worth a new contract surface.

### 6.5 Where the render time actually goes (and why "structural" was wrong)

Measuring the ~13.7 ms render by callback (not by cProfile bucket) corrects an
earlier claim in this doc. The unavoidable Python work is small:

- **Expression evaluation** (the compiled safe_eval functions running): ~0.8 ms
  (~6%), over ~2,580 evaluations. Python, on Python data, so it stays.
- **`template_data`** (and `js_data`/`css_data`), the user data methods: ~0.5 ms
  (~4%). User Python, so it stays.
- **Serialize / marking**: ~0.7 ms (~5%). `mark_html` is already Rust; the rest
  is Python orchestration, and its deps half was trimmed this pass (4.7).

That is only ~15%. The other **~85% (~11 ms) is render-walk machinery**: walking
the compiled node tree, the per-node type dispatch, resolving and formatting
attributes, assembling and joining strings, and the per-component work
(construction, context setup, id, slots, the extension-hook dispatch). None of
that is an unavoidable Python callback; it is mechanical work that merely runs
in a tree of Python objects. So the gap to Django is **not** "the structural
cost of Python components" (an earlier conclusion here, now retracted) - it is
walk machinery, and some of it is Rust-able. But "~85% Rust-able" overstated it:
the prototype (6.7) found that much of that 85% is woven through the
irreducibly-Python component model (the user component classes, `template_data`,
the per-component hooks) and cannot leave Python, so the genuinely movable part
is the string assembly and traversal, ~20-30%, not 85%. The lever is real but
smaller than this section first claimed.

### 6.6 The render walk in Rust: the architecture

Running the *walk* in Rust removes the interleaving that defeated the
fine-grained moves: the traversal and string assembly stay on the Rust side, and
the boundary is crossed only for the ~15% that is genuinely Python.

Today the compiler emits Python node classes (see [`rendering.md`](rendering.md))
that the Python runtime walks. The change is to emit a **render plan the Rust
core executes**: Rust walks the plan, assembles static text, formats attributes,
escapes, and joins, and calls back into Python only for `template_data` (once
per component) and expression evaluation (once per expression). Crossings drop
from tens of thousands of fine-grained string ops to a few hundred coarse
callbacks (~342 components + ~2,580 expressions ~= 0.5 ms of crossing for the
whole page at the 177 ns floor).

The hard part is not the string work; it is the **component machinery** the walk
drives: per-component construction, the context boundary, slots/fills,
provide/inject, and the extension-hook dispatch (the deps collection's
`on_component_data` fires per component). These are Python objects and a Python
extension system. For each, the Rust walk can either keep it Python (a crossing
per component, which the math above affords) or move it too (much larger); the
first is the pragmatic start. This moves the compiler-output format, a high-risk
contract ([`/CLAUDE.md`](../../CLAUDE.md)), and a chunk of the runtime, so it is
a project, not a patch, and needs a prototype before commitment.

### 6.7 The prototype, and what it found

Built (`crates/citry_core_py/src/prototype.rs`, a throwaway `RenderPlan` class,
since removed): a Rust walk of a body expressed as static segments interleaved
with `{{ expr }}` interpolations, calling back into Python for each compiled
expression, measured against the equivalent Python walk. Both call the same
compiled expressions, so the comparison isolates the walk itself; the plan
(segments and expressions) is held on each side and only the context crosses per
render, as a compiled template would be.

It answered the one question it could (interpolation; attributes and the
component machinery were left for a later prototype) and the answer reshapes the
verdict:

- **The per-expression crossing is affordable.** Even paying a Rust-to-Python
  crossing per expression, the Rust walk beat the Python walk on every body. The
  crossing was the headline risk, and it is cleared.
- **But the win is bounded and sub-threshold.** Output byte-identical; the Rust
  walk saved **10% on an expression-heavy body, up to 25% on a static-heavy one**
  (1.10x to 1.33x). The reason: the expression evaluations are the bulk of the
  dynamic work (~80% of the expression-heavy body, 3.7 of 4.6 us over 9 evals),
  and they are Python on Python data, so they stay. Rust cut the walk machinery
  itself ~1.8x net of the crossings, but the eval floor caps the overall win.
- **So the "30% net -> go" threshold was not met** on the part that could be
  tested, and the part that could not (the component machinery: construction,
  context, slots, the per-component hooks) is the *irreducibly-Python* component
  model, not movable string work. The realistic Rust-walk ceiling is the string
  assembly and traversal, ~20-30% of the render, which would reach roughly
  Django parity, not beat it, in exchange for moving the compiler-output
  contract and a chunk of the runtime.

**Verdict: not yet.** The architectural move is a large, high-risk project for a
bounded (~parity) gain, and the prototype showed the dominant cost is the
expression eval, which the Rust walk does not remove.

That eval is worth attacking, but **not** the way an earlier draft of this
section claimed. The claim was that a literal key's sandbox check is invariant
to the runtime value, so the compiler could resolve it once and emit direct
access. That is wrong, and reading `safe_eval/sandbox.py` shows why:
`is_safe_attribute(obj, attr)` calls `_is_internal_attribute`, which blocks
*every* attribute on a `CodeType`/`TracebackType`/`FrameType` (and special
attributes on functions, generators, and so on) purely from `obj`'s runtime
type. `is_safe_attribute(frame, "name")` is False while `is_safe_attribute(dict,
"name")` is True, for the same key. A compile-time fast path would emit direct
access not knowing `obj` is not a frame, which is a sandbox hole. The check is
genuinely value-dependent.

What is real: the check is ~62% of a subscript eval (272 of 436 ns), and for the
built-in container/scalar types none of `_is_internal_attribute`'s dangerous
branches can match, so its result there reduces to `not attr.startswith("_")`.
So a **runtime** fast path - a guard like `if type(obj) in
_SAFE_CONTAINER_TYPES: return not attr.startswith("_")` (exact types only;
subclasses and custom objects fall through to the full check) - is provably
equivalent and skips the isinstance chain. But it is a security-sensitive change
to the sandbox, covers only exact common types, and is worth ~2-3% of the render
(the eval is ~6% of the page and this trims part of it), not the ~1 ms an
earlier draft implied.

So no lever short of the Rust-walk project reaches parity: that project gets to
~parity (and is the only route to parallelism, 6.8); the runtime sandbox fast
path is ~2-3% and security-sensitive; the remaining Python micro-opts are low
single digits. The honest decision is binary: commit to the Rust-walk
architecture, or accept ~1.3x as where a Python component engine lands. (That
decision was taken and settled - the engine was built out, measured, and
archived; see 6.9.)

### 6.8 Parallelism is the same lever, not a separate one

Can node sub-trees render in parallel? Not in current Python: the GIL serializes
CPU-bound threads, so threads buy nothing, and the render holds shared mutable
state (the deps collection, the parent/child context linkage) that would need
real locking even under free-threaded Python (experimental, with C-extension
caveats). `multiprocessing` and subinterpreters cannot share the render tree. So
parallelism is reachable only *through* the Rust walk (no GIL, `rayon` over
independent sub-trees) - it is the same project, which is a further reason to
prioritize the prototype above over more piecewise Python tuning.

### 6.9 Postscript: the full engine was built, measured, and archived (2026-06-25)

The binary decision in 6.7 was taken: the prototype was built out into a full
production body engine and measured, to settle "roughly parity, not a beat" with a
real implementation rather than the isolated-walk estimate.

What was built: a Rust `BodyEngine` (with a `FoldedPlan` that lowers a const-precomputed
body once and caches it) that walks the body in Rust - static text, simple
attribute regions, and scalar `{{ expr }}` interpolation - emitting the real
`list[RenderPart]` and delegating every other node (components, slots, control
flow, non-scalar values) back to Python. It crosses to Python only for expression
eval and the in-walk hooks, and was gated behind a default-off flag.

What it measured (byte-identical everywhere - 823 rendering tests plus the 203 KB
benchmark):

- **~parity on a real, construction-bound page** (the large benchmark: 12.5 ->
  12.7 ms, 0.98-1.0x). The first cut, walking the Python body item-by-item, was
  ~3-6% *slower* (the per-item `get_item`/`isinstance` crossings cost more than the
  string work saved); pre-lowering the body into the Rust-side `FoldedPlan` removed
  that and brought it to parity.
- **~1.06x on a markup-heavy page** (40 components x 24 attributes + 12
  interpolations: 1.13 -> 1.06 ms), the regime where string work dominates -
  exactly where the prototype's isolated 1.8x came from, attenuated by the
  unavoidable per-component crossings.

So the production measurement confirmed the prediction: the body walk reaches
parity on a real page and wins only modestly where string work dominates. Not a
beat; the page stays construction-bound (section 8), and the expression-eval floor
stays in Python.

**It was removed from the live code but preserved in git history**, so a future
portability or multi-language port (the real reason to want a host-agnostic Rust
walk - see the section 6 opening) can pick it up:

- The full implementation, its design doc (`render_plan_rust.md`, with the complete
  contract, callback ABI, and measurements), and the prototype harness live in
  commit **`b7b2f4e`** ("refactor: Rust renderer proof of concept (rejected)").
- It was taken back out of the tree in **`60e1980`** ("revert: remove the Rust
  render engine from the live code").
- To bring it forward again: `git revert 60e1980`, or cherry-pick from `b7b2f4e`.

### 6.10 Rendering a body by running a generated function, not walking the nodes

Section 6 framed the choice as binary, walk the node tree in Python or move that
walk to Rust, and missed a third option that a cross-engine comparison
surfaced. Jinja2 renders a warm page about **2x faster than citry and ~1.8x
faster than a bare Django template** (`benchmarking.md` section 11). The reason
is not that Jinja2 compiles and citry does not (both compile): citry compiled a
template into **a list of node objects, and walked that list every render**,
calling `node.render()` on each node, which is the same tree-walking interpreter
Django is. Jinja2 instead compiles a template into **a Python function** where
static text is a literal append, `{% if %}` is a Python `if`, and `{{ x }}` is
an inline "evaluate, then append". Running that function *is* the render; there
is no list to walk and no per-node call, because the CPython interpreter is the
only interpreter involved. Doing the same in Python, generating a function from
the body instead of walking it, removes that walk without moving anything to
Rust.

citry now does this for every render
([`body_compile.py`](../../packages/py/citry/citry/body_compile.py)). For each
component body it generates, once, a Python function that produces the body's
output directly: static text becomes a literal append, `<c-if>`/`<c-for>`
become Python `if`/`for`, and `{{ expr }}` becomes an inline evaluate-and-append.
The work-heavy nodes (element attributes, components, slots, fills, nested
templates) are left to their own `render` method, because their cost is the
resolve/escape/evaluate work itself, which moving it inline cannot remove.

Two things this must not change, and does not (proven byte-identical by a
battery of constructs rendered both ways,
[`test_compile_body.py`](../../packages/py/citry/tests/test_compile_body.py),
plus the 203 KB benchmark page, modulo random ids):

- **Constant parts stay precomputed.** The input is the body *after* `precompute_const_parts`
  has computed the parts that depend only on constant inputs, so those are
  already plain strings before this runs. `precompute_const_parts` is untouched, and the
  generated function is cached per `(component class, set of Const values)`, the
  same key the body uses.
- **Component nesting stays unbounded.** A `<c-child>` is handed to
  `ComponentNode.render`, which returns a `DeferredComponent` (it does not render
  the child). The function returns the same `list[RenderPart]` walking the body
  would, so `render_impl`'s queue drives nesting, never Python recursion.

It is wired where the body is built and cached: the cache holds the body (the
node list, which the const tests inspect) and the function generated from it,
keyed together. The Rust compiler-output contract is untouched; this is an
additive Python step.

**Measured (this machine, A/B per section 1):**

- **~3.1%** on the large benchmark page (12.97 -> 12.57 ms). The page is
  attribute-heavy and construction-bound (section 8), so the part that becomes
  inline code is a minority of the time. Every body is generated to a function:
  the top-level component bodies at their build site, and the sub-bodies (slot
  fallbacks, fills, default content, nested templates) on the nodes that own
  them (see below). An earlier cut that generated only the top-level bodies was
  ~2.6%.
- **1.15x to 1.24x** on the body work in isolation, by shape: static-heavy
  layout HTML 1.22x, a 50-row loop 1.24x, an expression-heavy body 1.15x, and an
  **attribute-heavy body 1.01x** (no gain, because the eval/merge/escape work is
  intrinsic, which is why attributes are left to their own render). So it pays
  on static- and loop-heavy templates (real apps' layout shells) and does
  nothing for attribute-dense ones.

This lands in the same place as the archived Rust walk (section 6.9: 1.0-1.06x
on a real page) and for the same reason, the leaf work dominates, but in Python
at a fraction of the risk. It does **not** reach Jinja2: that gap is the
component machinery (construction, section 8) and the per-expression sandbox
(section 6.7), neither of which this touches, plus features Jinja2 lacks on
purpose (the unbounded nesting above, the sandbox).

**Sub-bodies are generated on the node that owns them.** A component's top body
is generated at its build site, but a few nodes render a body of their own (a
`<c-slot>` fallback, a `<c-fill>`, a component's default content, a nested
template). Each generates a function for that body the same way and caches it on
itself (`render_function_for` in `body_compile.py`). The node is the right place
to cache it: `id(body)` is not safe (the Const cache can drop a body and the next
one may land at the same identity), but a node lives exactly as long as the body
it owns. Nested templates get a second small win here: they no longer rebuild
their node list on every render. The two cases with no body of their own to
generate are unaffected: element attributes (their resolve/escape cost is
intrinsic) and `<c-child>` (rendered later from the queue, its own body generated
at its own build site).

## 7. Working rules for optimization

- **Output is the contract; prove it byte-identical.** A render optimization
  that changes the HTML is a bug, not a speedup. Diff the rendered page (modulo
  the random per-render ids) before and after, and lean on the suite's exact
  attribute/element assertions.
- **Measure, then keep.** Size every change with the A/B timer in section 1. A
  change that is within noise does not go in, however clean it looks (4.6).
- **Read the profile before guessing.** A "this looks slow" hunch is worth one
  cProfile run to confirm; the biggest win in section 4 (the dependency
  blow-up) was invisible in `tottime` and only showed up as a call count.
- **Fix the cause, not the symptom.** The dependency fix removed the
  accumulation; it did not add a bigger cache or a faster de-duplication over
  the already-exploded list.

## 8. Per-component construction cost (and the Python trims)

Section 6.5 found that a page of many small components is **construction-bound**:
most of the per-component cost is Python work (creating the instance and running
`template_data`) that no Rust walk can speed up. So the question this section
answers is: what does that construction actually do, and can it be made cheaper *in
Python*?

### 8.1 What was trimmed (low-risk wins, landed)

Four low-risk reductions landed. Measured together (cProfile of one component's
construction, then a component-render harness):

- **Component-id generator** -> a per-process random base plus a counter,
  format-preserving (`gen_id` in [`util/id.py`](../../packages/py/citry/citry/util/id.py)).
  This replaces the `random.choices` scheme that section 4.4 describes.
- **`has_hook` short-circuit** on `on_component_input` / `on_component_data`
  ([`extension.py`](../../packages/py/citry/citry/extension.py)).
- **Skip slot normalization** for the no-slots case
  ([`component.py`](../../packages/py/citry/citry/component.py)).
- **Lazy `_provides_own`** ([`component.py`](../../packages/py/citry/citry/component.py)).

Result: construction (the `_create_instance` + `template_data` path) got about
**34% cheaper** (the six PRNG draws of `random.choices` are gone, and the
`on_component_input` context dataclass is no longer built when nothing subscribes),
which showed up as about a **19% faster** render on a page of many tiny components
(less on richer pages where the body walk dominates). Output stays byte-identical;
ids keep the `c[0-9A-Za-z]{6}` format and stay non-deterministic.

### 8.2 What construction costs (the baseline)

Profiling one simple component's construction (`_create_instance` + `template_data`
+ context; the wall-clock is ~3.5 us per component) breaks the cost, *before the
trims above*, into four areas:

1. **Component-id generation, ~20% of construction.** The old `gen_id` was
   `"".join(random.choices(_ID_ALPHABET, k=6))`. `random.choices` is not one cheap
   call: it does `floor(random() * 62)` per character, so one id is six
   Mersenne-Twister draws plus six `math.floor` calls plus a list and a join - the
   single largest contributor in the profile. (Now: a counter off a random base;
   see 8.1.)
2. **Extension per-component touchpoints, ~15%.** Every component runs
   `_init_component_instance`, which per extension allocates a config object (with a
   `weakref`) and `setattr`s it onto the component, and then `on_component_input`,
   which **built a frozen context dataclass for every component even when no
   extension subscribed**. The three hot hooks already guarded with `has_hook`;
   `on_component_input` / `on_component_data` did not (now they do; see 8.1).
3. **`Component.__init__` core, the rest of the spine.** A defensive copy of the
   kwargs dict, slot normalization that ran even with no slots, the typed
   `Kwargs`/`Slots` dataclass instantiation, and two empty-dict allocations for
   `provides`.
4. **Normalization helpers.** `to_dict` runs ~3 times per component, and
   `_normalize_data` normalizes the `template_data`/`js_data`/`css_data` outputs.

The recurring pattern: the work is unconditional but only needed for a subset of
components. Most components are leaf markup with no slots, no provides, no
extension-config access, and a `template_data` that just reads the plain kwargs
dict, so almost all of it is paid for nothing.

### 8.3 The reductions, ranked

**1. Component id: a counter or a hybrid (the standout, landed).** The id only
scopes a component's CSS/JS (the `data-cid-<id>` marker) and is a DOM lookup key; it
is never a dict key, never persisted, and not a secret, and it only has to be unique
within one serialized page. So the random id was over-provisioned. Measured (200k
iterations):

| scheme | per id | vs old |
|---|---|---|
| old (`random.choices`, 6 draws) | 0.299 us | 1.0x |
| per-render **counter** (`c1`, `c2`, ...) | 0.056 us | **5.3x** |
| **hybrid**: one random base per render + counter | 0.061 us | **4.9x** |
| single `getrandbits(36)` + 6-char assembly | 0.399 us | 0.75x (slower) |

The last row is a useful negative: one `getrandbits` plus a Python assembly loop is
*slower* than `random.choices`, because the per-character shift-and-index in Python
costs more than `random.choices`' C internals. Only a counter avoids the per-char
work. The **hybrid** (random base + counter) was chosen: ~5x faster, keeps
cross-render uniqueness (different bases pick different starting points), and keeps
the `c[0-9A-Za-z]{6}` format. See [`util/id.py`](../../packages/py/citry/citry/util/id.py).

**2. Guard `on_component_input`/`on_component_data` with `has_hook` (landed).**
Return early when nothing subscribes, exactly as the three hot hooks already do, so
the per-component context dataclass is never built. In the default Citry nothing
implements `on_component_input`, so it is a pure win; these are fire-and-forget
hooks, so there is no observable change.

**3. Skip slot normalization when there are no slots (landed).** The render path
sets `element.slots = slots or {}` (a falsy empty dict), so a `slots is not None`
guard did not short-circuit and `normalize_slot_fills({})` ran a call frame to build
an empty dict. A truthiness check returns `{}` directly for the common no-slots
component.

**4. Trim the `Component.__init__` allocations.** Lazy `_provides_own` landed
(initialize to `None`, let `provide()` create it on first use). Two medium-risk
follow-ups remain: a **lazy typed `Kwargs`/`Slots` view** (build from the raw dict
on first access, saving the dataclass instantiation for the common case where
`template_data` reads the plain dict; medium risk because a required-field `Kwargs`
would then raise at first access rather than at construction), and **avoiding the
defensive kwargs copy** when no input-mutating extension is active (gate on
`has_hook("on_component_input")`; medium risk because a wrong gate would leak one
render's mutation into the next).

**5. `_init_component_instance` plan cache (medium, not done).** Cache, per
component class, the resolved `(name, config_cls)` tuple so the per-component path is
just `setattr(component, name, config_cls(component))`. Making the config object
itself lazy would remove the `weakref` + object + `setattr` for components that never
read their extension config, but it is the riskiest (timing of when
`component.<ext.name>` exists), so it should follow the cheaper wins.

### 8.4 Honest assessment

Stacking the low-risk wins trims construction by perhaps 20-30%, about 1 us off a
~3.5 us construction. At the render level that is a few percent for a page of many
small components, and less for a page of rich components where the body walk and
attributes dominate. The medium-risk changes roughly double that ceiling but carry
correctness questions worth a careful pass each.

So: real, low-risk, worth doing as an incremental Python pass, with the id generator
the clear first move - but it does not change the strategic picture any more than the
Rust port did (section 6). A Python component engine that creates an instance, runs
the user data methods, and walks a node tree per component lands around 1.3x a bare
Django template; construction is a meaningful slice of that, but trimming it yields
single-digit percentages, not a different order. The constructs are sound; the wins
are in making the conditional work conditional and deferring the speculative work,
not in replacing the model.
