# Design: slots and fills

**Status (2026-06-10): built.** All phases are implemented: the section 11
parser fixes, the `Slot` value (section 3), fill collection and the Python
`slots=` channel (sections 4 and 9), the queue + serializer handling of fill
content (section 8), slot resolution at `<c-slot>` (section 5), and the
`on_slot_rendered` hook (section 7). The README's slot examples work end to
end. This document specifies the
slot subsystem: the `Slot` value, how `<c-fill>` content travels from a parent
template into a child component, how `<c-slot>` resolves it, the Python-side
`slots=` input, and how all of it interacts with the deferred render queue. It
is the design doc that [`rendering.md`](rendering.md) section 10 and the
`ComponentNode` docstring defer to.

It extends [`rendering.md`](rendering.md) (the three-phase
`CitryElement` -> `CitryRender` -> serialize pipeline and `CitryContext`) and
[`deferred_rendering.md`](deferred_rendering.md) (the render queue that this
design must cooperate with, section 8 here). Operating rules are in
[`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: the django-components implementation studied for this
design is [`_djc_reference/slots.py`](../../packages/py/citry/_djc_reference/slots.py)
(the `Slot` class, `SlotNode.render`, `resolve_fills`,
`normalize_slot_fills`), with the component-side wiring in
[`_djc_reference/component_render.py`](../../packages/py/citry/_djc_reference/component_render.py).
The behavioral contract is pinned by the captured DJC test suites
[`_djc_tests/test_templatetags_slot_fill.py`](../../packages/py/citry/tests/_djc_tests/test_templatetags_slot_fill.py)
and [`_djc_tests/test_slots.py`](../../packages/py/citry/tests/_djc_tests/test_slots.py).
Related upstream issue: django-components
[#1259](https://github.com/django-components/django-components/issues/1259)
(deprecate slot context input and outer_context), which this design completes.

---

## 1. Prior art

What already exists, verified on 2026-06-10 by running `parse_template` /
`compile_template` on representative inputs (not just by reading stubs):

- **Parse-time fill validation is largely done, in Rust.** The parser rejects:
  a `<c-fill>` outside a component or inside plain HTML
  ([`parser.rs` `validate_fill_placement`](../../crates/citry_template_parser/src/parser.rs)),
  node siblings mixed with fills (`validate_fill_exclusivity`), duplicate
  static fill names, duplicate `c-name` expressions, duplicate `c-bind`
  tuples, dynamic-fill overflow against a tag's `allowed_slots`, and unmet
  `required_slots` counts (`validate_fill_names`). Control-flow tags are
  *transparent* for fill validation
  ([`constants.rs` `CONTROL_FLOW_TAGS`](../../crates/citry_template_parser/src/constants.rs)):
  fills inside `<c-if>`/`<c-for>` are a supported, first-class shape.
- **Dynamic fill identity is already modeled.** `FillIdentity` distinguishes a
  static `name`, a dynamic `c-name`, and a `c-bind` spread, resolved by a
  right-to-left walk of the identity attributes; each collected fill carries
  `inside_for_loop` / `inside_control_flow` flags
  ([`parser.rs` `FillNodeInfo`, `_extract_fill_identity`](../../crates/citry_template_parser/src/parser.rs)).
- **The compiler output shape is locked.** `FillNode(source, pos, attrs, body,
  used_vars, introduced_vars)` and `SlotNode(...)` with the same signature;
  the fill's `data`/fallback attribute values are *variable names* and appear
  in `introduced_vars`, excluded from `used_vars`. A component with fills
  compiles with `contains_fills=True` and a body of FillNodes; a default body
  compiles with `contains_fills=False`, and the body's variables count as the
  *parent* component's `used_vars`. The compiler already encodes that fill and
  default bodies evaluate in the parent scope
  ([`compiler.rs` `compile_component_node`](../../crates/citry_template_parser/src/compiler.rs)).
- **`template.slots`** collects `StaticNamedSlot { name, required:
  Some(bool) | None }`; `required` is `None` when `c-required`/`c-bind` makes
  it dynamic ([`parser.rs` `extract_slot_from_node`](../../crates/citry_template_parser/src/parser.rs)).
- **Runtime stubs are in place.** `SlotNode`/`FillNode` are constructible but
  raise on render; `ComponentNode.render` raises on any body
  ([`nodes/__init__.py`](../../packages/py/citry/citry/nodes/__init__.py)).
  `DeferredComponent` and `CitryElement` carry a `slots` field on purpose
  ([`deferred_rendering.md`](deferred_rendering.md) section 7).
- **Per-tag slot rules are exposed to Python.** `parse_template(...,
  user_rules={tag: TagRules})` accepts `allowed_slots`/`required_slots`
  ([`_rust.pyi`](../../packages/py/citry_core/citry_core/_rust.pyi)); the
  parse-time validation above runs against them. Wiring component `Slots`
  declarations into these rules is out of scope here (section 12) but the
  capability shapes the design.

What does *not* exist: any runtime slot behavior, a `Slot` value type, the
Python `slots=` input channel, and three parser rules that contradict the
README (section 11).

---

## 2. The model in one paragraph

A fill is a `Slot`: a callable that closes over the variable scope where the
fill was written. When a parent's template reaches `<c-child>`, the parent
*collects* the fills eagerly (so loop variables and conditions are read while
the parent context is live) but does not render their bodies. The child
renders later (through the deferred queue), and when its template reaches
`<c-slot name="x">`, it looks up `x` among the slots it received and *invokes*
the Slot, passing slot data and a lazy handle to its own fallback content. A
fill body therefore renders in the parent's scope, at the child's pace, zero
or more times. There is no context mode, no outer-context snapshot, and no
fill-discovery render pass: the single closure rule replaces all three pieces
of django-components machinery.

---

## 3. The `Slot` value

Lives in a new `citry/slots.py` module (the location
[`citry_migration.md`](citry_migration.md) already reserves).

### 3.1 `Slot`

The one normalized form for every way slot content can be supplied: a
`<c-fill>` body, the implicit default-slot body, a plain string, a Python
function, or a pre-made `Slot`. Ported from DJC's `Slot`
([`slots.py:173`](../../packages/py/citry/_djc_reference/slots.py)) with these
citry adaptations:

- **Calling a Slot returns a `RenderPart`, not a string.** A template-defined
  fill renders to a `CitryRender`, so nested components inside the fill stay
  structural and JS/CSS dependencies keep bubbling through `extra`. A
  Python-supplied function may return `str | SafeString | CitryElement |
  CitryRender`; the result goes through `_render_value`
  ([`citry_render.py`](../../packages/py/citry/citry/citry_render.py)), which
  already coerces all of these.
- **Callable standalone and repeatedly.** `my_slot({"name": "John"})` works
  with no component or render context (DJC
  `test_slot_call_outside_render_context`), and the same Slot may be invoked
  many times in one render with different data (a `<c-slot>` inside a
  `<c-for>` calls it once per iteration). For a template fill this means a
  fresh walk of the fill's body node list per call, which is safe: rendering
  the same node list repeatedly is exactly what `ForNode` already does.
- **Signature:** `Slot(contents, ...)` where `contents` is the original input;
  `slot(data=None, fallback=None) -> RenderPart`. Constructing
  `Slot(Slot(...))` raises (ambiguous metadata), as in DJC.
- **Escaping:** a string input is escaped at construction with
  [`util/html.escape`](../../packages/py/citry/citry/util/html.py)
  (markupsafe, honors `__html__`), so `Slot("<b>")` renders escaped and
  `Slot(SafeString(...))` does not; a function result is escaped by
  `_render_value` unless it is a `SafeString`/`CitryRender`/`CitryElement`.
  This matches DJC's `conditional_escape` semantics
  (`test_render_slot_unsafe_content__*`).
- **Metadata, slim:** `contents`, `component_name` (owner), `slot_name`,
  `source_position` (the FillNode token span, for diagnostics), and an
  `extra: dict` bag. The `extra` bag is kept because DJC's CSS-scoping
  extension passes per-slot metadata through it, and citry's equivalent will
  want the same seam. DJC's `nodelist` field (a Django type) and
  `do_not_call_in_templates` (Django auto-call protection) have no citry
  analog and are not carried.

### 3.2 `SlotContext`

The single argument a slot function receives: `SlotContext(data, fallback)`.
Frozen dataclass, generic over the data type. The DJC field `context` (the
Django template `Context`) is **not** carried: a fill already closes over its
scope, and exposing the child's render context to the fill is exactly what
django-components #1259 deprecates and what the repo rule "only props and
slots" ([`citry_migration.md`](citry_migration.md) impl notes) forbids.

### 3.3 The fallback is a `Slot`

There is no separate fallback type: the lazy handle to the slot's own body,
passed to every fill invocation as `SlotContext.fallback`, is itself a `Slot`
(`Slot | None`). It wraps the `<c-slot>` body closing over the child's context
at the slot site (so a fallback inside a loop sees that iteration's
variables), and like any Slot it may be invoked multiple times (DJC
`test_multiple_calls`). DJC's own internals support this unification: on the
unfilled path DJC already wraps the slot body as a `Slot` via
`_nodelist_to_slot` and invokes it through the same call path as a real fill
([`slots.py:846`](../../packages/py/citry/_djc_reference/slots.py)); its
standalone fallback type exists only as the handle passed into fills, and
citry folds that role into `Slot` too. Consumption paths:

- Inside a template, `{{ fallback }}` evaluates to the Slot; `_render_value`'s
  ordinary Slot detection (3.5) invokes it and inlines the result with its
  dependencies intact. No extra detection branch is needed.
- In Python, `str(fallback)` serializes it via `Slot.__str__` (invoke with
  empty data, then serialize). `__str__` is defined on `Slot` itself, so every
  slot gets the same convenience; it is dependency-losing, the same one-shot
  caveat as `CitryRender.serialize`.
- Because it is a Slot, the fallback can be forwarded like any slot content,
  for example passed into a nested component's slots.

A fallback Slot ignores `ctx.data` passed to it (its body has no data-variable
binding), the same way string-derived Slots do.

### 3.4 Input normalization

`normalize_slot_fills(fills, component_name)` ports nearly verbatim from
[`slots.py:1496`](../../packages/py/citry/_djc_reference/slots.py): every
value in a `slots={...}` mapping becomes a `Slot`; `None` values are dropped
(same as no slot). Citry extends the accepted input forms with
`CitryElement` and `CitryRender` (compose-first: `slots={"header":
Card(title=...)}` just works, because the Slot's call path hands the value to
`_render_value`).

### 3.5 Slots inside expressions

New citry feature, replacing DJC's `body=` kwarg on `{% fill %}` (which was a
workaround for not being able to write `{{ my_slot }}` inside a fill body in
Django; DJC docs at
[`slots.py:1093`](../../packages/py/citry/_djc_reference/slots.py)).
`_render_value` gains one more detection: a value that is a `Slot` is invoked
with empty data (`SlotContext(data={}, fallback=None)`) and its result
inlined. So:

```html
<c-Table>
  <c-fill name="pagination">{{ my_slot }}</c-fill>
</c-Table>
```

renders the Slot a component passed down via `template_data`. Calling it with
data also works with no extra machinery, because a Slot is callable inside
the sandboxed expression: `{{ my_slot({'page': 3}) }}` returns a
`CitryRender`, which `_render_value` already inlines.

The full `_render_value` detection order becomes: `None` -> `""`, `Slot` ->
invoke, `CitryElement` -> render, `CitryRender` -> inline, else escape. The
fallback handle needs no entry of its own: it is a Slot (3.3).

---

## 4. Fill collection at the component boundary

`ComponentNode.render` (which runs in pass 1, while the parent's context is
live; see [`deferred_rendering.md`](deferred_rendering.md) section 4.2)
gains a second job next to kwarg resolution: build the child's
`dict[str, Slot]`.

### 4.1 Two body modes, split by `contains_fills`

- **`contains_fills=False`, body non-empty:** the whole body is the implicit
  default slot. If the body is only whitespace strings, no slot is created
  (DJC ignores whitespace-only implicit content). Otherwise it becomes one
  `Slot` registered under `"default"`, closing over the current context.
- **`contains_fills=True`:** the body is a fill group. Collect fills by
  walking the body **executing control flow against the live context**: an
  `IfNode` evaluates its branch conditions and recurses into the matching
  branch only; a `ForNode` evaluates its iterable and recurses once per
  iteration, with that iteration's loop bindings overlaid into the context
  that the collected fills close over. This is the runtime mirror of the
  parser's `extract_fill_nodes`, and it is what the compiler's
  `contains_fills` comment calls "pre-rendering the body to collect the fill
  nodes". Only fill *membership* is evaluated here; fill *bodies* stay
  unrendered.

Dynamic fills are therefore in scope from the start: `<c-for each="s in
slots"><c-fill c-name="s">...</c-fill></c-for>` collects one Slot per
iteration, each closing over its own iteration context (so a fill body using
`s` sees the right value).

### 4.2 Per-fill resolution

For each collected `FillNode`, resolve against the context current at its
collection point:

- **Name:** static `name`, or evaluate `c-name`; a `c-bind` spread resolves a
  mapping whose recognized keys are `name`, `data`, `fallback`. Precedence is
  rightmost-wins across the identity attributes, matching the parser's
  right-to-left identity walk (`_extract_fill_identity`).
- **`data` / `fallback`:** variable *names* (strings) under which the fill
  body will see the slot data and the fallback handle. Both optional. Each
  must be a valid identifier; `data == fallback` is an error (DJC
  `test_slot_data_raises_on_slot_data_and_slot_fallback_same_var`).
- **Body:** wrapped as a `Slot` whose content function, when invoked with a
  `SlotContext`, renders the body against the *captured* context overlaid
  with `{data_var: ctx.data, fallback_var: ctx.fallback}` (overlay wins on a
  name collision, same as `ForNode` loop bindings). The overlay context
  shares the captured context's `extra` bag, so dependencies collected while
  a fill renders flow to the fill's lexical owner (see section 8).

### 4.3 Runtime validation at collection

- **Duplicate resolved names error.** The parser catches static duplicates;
  two dynamic fills resolving to the same name at runtime must error here
  (DJC `test_non_unique_fill_names_is_error_via_vars`).
- **Non-whitespace text or `{{ expr }}` between fills errors**, mirroring
  DJC's "fills cannot occur alongside other text". After the parser fix in
  section 11.3 this is mostly unreachable, but the runtime keeps the check
  because `c-name` fills make some shapes undecidable statically.
- **Whitespace strings between fills are dropped.** They exist for template
  formatting only; they are neither captured into any slot nor rendered.
- `{# template comments #}` never reach the runtime (stripped at parse), so
  comments between fills are naturally permitted (DJC
  `test_comments_permitted_inside_implicit_fill_content`).

The resulting `dict[str, Slot]` rides on the `CitryElement` into the
`DeferredComponent`, exactly the slot-ready seam
[`deferred_rendering.md`](deferred_rendering.md) section 7 reserved.

### 4.4 Dispatch: nodes collect their own fills

The fill-group walk dispatches polymorphically. `Node.collect_fills(context,
sink)` is the second method of the node contract, next to `render`: the base
implementation rejects the node (nothing but fills, control flow, and
whitespace may sit in a fill group), and the nodes that ARE allowed override
it. `IfNode` contributes its matching branch, `ForNode` contributes once per
iteration (each fill closing over that iteration's bindings), and `FillNode`
resolves its own attributes and registers its body as a `Slot`. The `FillSink`
carries the receiving component's name (for slot metadata and error messages)
and enforces name uniqueness; `collect_fills_from_body` walks one body level,
handling the whitespace-only-text rule. `ComponentNode` only creates the sink
and starts the walk.

Two properties this buys:

- **Open dispatch.** A node kind the collector has never heard of (most
  plausibly one an extension injects via `on_template_compiled`) participates
  by overriding `collect_fills`; nothing enumerates node types.
- **No drift.** `IfNode.active_branch_body` and `ForNode.iter_bodies` are the
  single implementations of branch picking and loop evaluation, called by both
  `render` and `collect_fills`, so collection cannot disagree with rendering
  about which fills a template produces.

Collection still never calls `render`: deciding which fills exist evaluates
only conditions and iterables, and fill bodies stay unrendered inside their
Slots. The alternatives to this dispatch design, including the one that does
collect by rendering, are weighed in section 13.

---

## 5. Slot resolution at `<c-slot>`

`SlotNode.render(context)` is the small essential core of DJC's 300-line
`SlotNode.render`
([`slots.py:651`](../../packages/py/citry/_djc_reference/slots.py)), with the
Django scaffolding removed:

1. **Resolve the slot's own attributes** against the current (child)
   context: `name` (static, `c-name`, or via `c-bind`; missing name means
   `"default"` after the section 11.2 parser fix), `required` (static flag or
   dynamic `c-required`/`c-bind`), and every remaining attribute as **slot
   data** (static attrs as strings, `c-*` attrs evaluated, `c-bind` spread;
   last write wins, left to right). Data resolves per render of the slot
   site, so a slot inside `<c-for>` passes per-iteration data.
2. **Look up** the name in the rendering component's slots
   (`context.component.raw_slots`).
3. **On hit:** wrap the slot's own body and the current context as a fallback
   `Slot` (3.3) and invoke the fill's Slot with
   `SlotContext(data=resolved_data, fallback=fallback)`. The returned
   part is this node's render result; if it is a `CitryRender` from a
   different context, `_render_body`'s existing merge seam copies its
   dependencies (unchanged behavior).
4. **On miss:** render the slot's own body (the fallback) against the current
   context, exactly as if the `<c-slot>` tags were not there. If `required`
   resolved truthy, raise instead, including DJC's `difflib`-based "did you
   mean" hint over the available fill names
   ([`slots.py:865`](../../packages/py/citry/_djc_reference/slots.py)).
5. **Fire `on_slot_rendered`** (section 7.1) and apply a replacement result
   if an extension returns one.

Behavioral points carried from DJC's test contract:

- **Validation matches DJC.** Only a *rendered* slot can error: a required
  slot inside an untaken `<c-if>` branch does not complain, and surplus fills
  for slots that never render are silently ignored
  (`test_passthrough_slots_unknown_fills_ignored`). The reason DJC states
  ([`slots.py:630-650`](../../packages/py/citry/_djc_reference/slots.py))
  holds identically in citry: slot names can be dynamic, so the full slot set
  is unknowable before rendering.
- **The same slot name may appear at several `<c-slot>` sites** in one
  template; each site invokes the same fill, each with its own data and
  fallback (DJC `TestDuplicateSlot`).
- **The default slot is the one named `"default"`**, by name only. There is
  no `default` *flag* on `<c-slot>` (divergence from DJC, see section 11.2);
  with the flag gone, DJC's "filled twice, explicitly and implicitly" check
  collapses into the ordinary duplicate-name error, and the
  "multiple default slots with different names" error disappears
  structurally.
- **Errors carry the slot path.** Wrap render errors with component/slot
  names (the `add_slot_to_error_message` idea); citry derives the component
  path from the `parent` chain.

Passthrough slots and nested slots need no code: a `<c-slot>` written inside
a `<c-fill>` body renders when the fill is invoked, with the fill's captured
context, whose `context.component` is the *outer* component, so it looks up
the outer component's fills (DJC `TestPassthroughSlots`); a `<c-slot>` inside
another slot's fallback renders against the child context at that point and
resolves normally (DJC `TestNestedSlots`). Both fall out of the closure rule.

---

## 6. What this deletes from django-components

For the record (and for the migration doc), the DJC machinery that does NOT
port, because each piece compensates for the flat Django `Context` that citry
does not have: the `context_behavior` setting (django/isolated) and
`_resolve_slot_context`; the `outer_context` snapshot and the
`context.dicts` parent-index walk; the `FILL_GEN_CONTEXT_KEY`
render-to-discover pass and its `_is_extracting_fill` guards; the manual
forloop/`{% with %}` variable capture in `FillNode._extract_fill`; the
django-mode infinite-loop guard; the `{% extends %}`/`block_context`
compatibility; `SlotIsFilled` / `component_vars.is_filled` (deprecated
upstream, superseded by `Component.slots`); the `SlotContent`/`SlotRef`
aliases; and the `body=` fill kwarg (superseded by section 3.5). The
provide/inject pass-through is deferred to the `<c-provide>` design, where it
will ride on `CitryContext` and survive slot boundaries automatically via
the closure.

---

## 7. Extension surface

### 7.1 `on_slot_rendered`

New hook on `Extension`, following the existing frozen-dataclass context
pattern in [`extension.py`](../../packages/py/citry/citry/extension.py):

```python
OnSlotRenderedContext(
    citry, component,          # the component whose template holds the <c-slot>
    slot,                      # the Slot instance that was rendered (or the fallback pseudo-slot)
    slot_name, slot_node,      # resolved name + the runtime SlotNode
    slot_is_required,          # resolved bool
    result,                    # RenderPart
)
```

Return semantics match `on_component_rendered`: `None` keeps the result, a
returned `RenderPart` replaces it, raising propagates. There is no
`slot_is_default` field (DJC has one because of its `default` flag; in citry
`slot_name == "default"` carries the same information).

This is the seam the future CSS-scoping/dependency extension needs (DJC's
scoping rewrites slot output here), which is why it ships with the MVP even
with no built-in consumer.

---

## 8. Interaction with the deferred render queue

**Status: built**, with one addition over the original design: serialization
needed the same cross-owner treatment as the scan, solved with an
`is_component_root` flag on `CitryRender` (set only by the render pipeline on
a component's whole output, preserved through `on_component_rendered`
replacement). The serializer frames a nested render as a child component iff
it is another component's root render; everything else (control flow, nested
templates, slot-fill content) joins into the surrounding frame. The component
identity on the context cannot make this distinction, because fill content
carries the context of the component that wrote it while rendering inside
another component's frame.

This is the one place slots, deferral, and the dependency flow intersect, and
it contains a latent bug that must be fixed as part of this work.

**The problem.** A fill body renders lazily at the slot site, i.e. *during
the child's* `_render_one`, but it renders against the parent's captured
context. If the fill body contains `<c-grandchild>`, the body walk produces a
`DeferredComponent` inside a `CitryRender` whose `context.component` is the
**parent**. `_scan_deferred` currently descends only into nested renders
whose `context.component is owner`
([`component_render.py`](../../packages/py/citry/citry/component_render.py)),
so when the child render is scanned, the fill-body render fails the predicate
and the grandchild is never queued. It then trips the serialize-time
unresolved-deferred guard.

**The fix.** `_scan_deferred` descends into **every** nested `CitryRender`,
regardless of owner. This is safe and cheap:

- An *embedded pre-rendered* subtree (a `CitryRender` passed in via `{{ }}`
  or a kwarg) is guaranteed deferred-free, because `render_impl` runs its
  queue to completion before returning. Descending finds nothing.
- A *slot-fill* render is the only cross-owner render that can contain
  deferreds, and descending finds exactly those.

For a deferred found inside a fill-body render, the task's `parent_context`
(the dependency merge target at finalize) is the **fill render's own
context**, not the scanning child's. That is the lexical owner: the fill body
was written in the parent's template, so its grandchild's JS/CSS belong to
the parent's collection. Ordering stays correct with no new rules: the
grandchild's finalize task sits above the child's finalize, which sits above
the parent's, so deps merged into the parent's shared `extra` always land
before the parent itself finalizes.

**Eagerness boundary restated:** kwargs and fill *membership* resolve in pass
1 (live context); fill *bodies* render at slot invocation (inside the child's
`_render_one`); child components inside fill bodies render through the queue
like any other deferred. Nothing about the queue's two task kinds changes.

A second-order case to test explicitly: a fill body whose grandchild's own
template has slots filled by *its* surrounding fill content (three-level
passthrough), which exercises scan-through-two cross-owner layers.

---

## 9. The Python composition API

### 9.1 `slots=` is a reserved kwarg

Decision: slots are passed under a dedicated `slots` keyword:

```python
MyComp(title="x", slots={"header": "Hi", "footer": lambda ctx: ...})
```

`ComponentMeta.__call__` extracts `slots` from the call kwargs, normalizes it
(section 3.4), and constructs `CitryElement(cls, kwargs, slots)`; the
remaining kwargs stay kwargs. This resolves the open TODOs in
[`component.py`](../../packages/py/citry/citry/component.py) (metaclass
`__call__`) and [`citry_element.py`](../../packages/py/citry/citry/citry_element.py).
Consequence: `slots` is a reserved input name; a component cannot take a
regular kwarg named `slots`. This is the same class of reservation as `cls`
(already handled positionally-only) and is acceptable for a component system
whose core vocabulary includes slots.

### 9.2 Keep `Component.Slots`, `Component.slots`, `Component.raw_slots`

Three options were considered for the component-side surface:

1. *Drop `Component.Slots`; type slots inside `Component.Kwargs`.* Rejected:
   slots are not kwargs. They are lazily-invoked callables with scoped data,
   they must be excluded from the const signature (`Slot` closures are
   unhashable and never constant), they normalize through a different
   boundary (`normalize_slot_fills` vs `to_dict`), and in-template fills
   arrive with no kwarg channel at all, so a kwarg-only model would have
   `ComponentNode` synthesizing a fake `slots` kwarg anyway.
2. *Drop `Component.slots`/`raw_slots`; read `raw_kwargs.get("slots")`.*
   Rejected for the same reasons, plus it breaks the established
   `template_data(kwargs, slots)` signature that both citry and DJC users
   already program against, and it makes the typed-`Slots` validation
   impossible.
3. **Extract `slots` out of the call kwargs and keep the separate, typed
   surface.** Chosen. `Component.Slots` (auto-dataclass, slots typed as
   `SlotInput[...]`), instance `slots` (the `Slots` dataclass instance, or a
   plain dict of `Slot`s), and `raw_slots` (always the plain dict view) all
   stay as they are today, now actually populated. Normalization to `Slot`
   instances happens in `Component.__init__` before the typed view is built,
   so both `slots` and `raw_slots` hold normalized `Slot` values
   (DJC `test_slots_normalized_as_slot_instances`).

What would falsify choice 3: if the typed `Slots` class turns out to add no
validation value over `Kwargs` once template-only components (#1240) land,
options 1/2 could be revisited; the extraction in 9.1 is compatible with all
three, so only the component-side surface would move.

### 9.3 Public typing surface

Port the type aliases: `SlotResult` (`str | SafeString` extended with
`CitryRender`), `SlotFunc[TSlotData]` (protocol over
`(SlotContext) -> SlotResult | CitryElement | CitryRender`), and
`SlotInput[TSlotData]` (`SlotResult | SlotFunc | Slot | CitryElement |
CitryRender`). The deprecated DJC aliases are not carried.

### 9.4 What is exported where

The package root (`citry/__init__.py`, its `__all__`) is the public API, and
only those names are promised not to break between releases; submodules
(`citry.slots`, `citry.nodes`, ...) may be imported from, but their contents
are internal and free to change. For the slot subsystem that means:

- **Root (stable):** `Slot`, `SlotContext`, and the typing aliases
  (`SlotInput`, `SlotResult`, `SlotFunc`), which component authors use to
  pass slots and type their `Slots` classes. The runtime node classes are
  also root exports: constructing nodes and editing a template body in the
  `on_template_compiled` extension hook is a recognized user journey.
- **Internal (in their modules):** `normalize_slot_fills` (the framework
  already normalizes at every boundary it owns; for single values the user
  API is the `Slot(...)` constructor; the dict-level rules are boundary
  contract the framework may evolve), and `FillSink` /
  `collect_fills_from_body` (collection machinery behind
  `Node.collect_fills`).

---

## 10. Prop templates vs slots

Citry has a second channel for passing markup that DJC lacks: a nested
template in a `c-*` attribute (`c-footer="<div>...</div>"`, a
`TemplateHtmlAttr` resolving to a `CitryRender` kwarg). Both are legitimate;
the doc-level guidance, so users (and these docs) answer "which one":

| | Prop template (`c-foo="<div/>"`) | Slot (`<c-fill>`) |
|---|---|---|
| Renders | Eagerly, in the parent, at kwarg resolution | Lazily, at each `<c-slot>` site |
| Scope | Parent's scope only | Parent's scope + opt-in slot `data` from the child |
| Times rendered | Exactly once | 0..N (loops, branches, repeated slot sites) |
| Fallback access | No | Yes (`fallback`) |
| Receiver sees | An ordinary kwarg (a value) | A declared slot |

Rule of thumb: the receiving component decides. If it declares a slot, fill
it; pass a prop template only for plain "markup as a value" inputs that the
receiver treats as data. A prop template cannot react to slot data, which is
the capability boundary between the two.

---

## 11. Parser changes (spec fixes; built 2026-06-10)

Three places where the implemented parser, the README (the north star), and
django-components disagree were found by running the parser; the decisions
below were confirmed with the maintainer (session 2026-06-10). Each touches
`constants.rs`/`parser.rs` validation rules, so per
[`/CLAUDE.md`](../../CLAUDE.md) Mechanism 2 the implementation goes through
plan mode; the Mechanism 4 audit for all three is small because no AST shape,
compiler output shape, `LangImpl` method, or PyO3 surface changes: the edits
are `TAG_ATTR_RULES_DATA` / validation functions, Rust tests
(`tag_parser_fills.rs`), and the compiler's doc comments.

### 11.1 The fill's fallback attribute is `fallback`

`<c-fill name="x" fallback="fb">` per the README. The attribute rule set for
`c-fill` becomes `name`/`c-name` (one-of), `data`, `fallback`, `c-bind`, with
the `fallback` value treated as an introduced variable exactly as `data` is
today. This also keeps the word `default` available to mean only "the default
slot". (Verified 2026-06-10: the parser rejects `fallback` and accepts
DJC's deprecated spelling; the README and current DJC both use `fallback`.)

### 11.2 `<c-slot />` with no name means the default slot

Per the README. `name` leaves the required-attribute set of `c-slot` (becomes
fully optional); `extract_slot_from_node` and the runtime treat a missing
name as `"default"`. There is deliberately no `default` flag on `<c-slot>`
(DJC's flag decouples "the default slot" from the name `default`; citry
couples them, which deletes the flag's double-fill and conflicting-defaults
error cases, section 5). Note for the implementation: today an attribute
literally named `default` on `<c-slot>` would parse as slot *data*; that
stays true, and the README convention is name-based only. `<c-fill>` keeps
its name requirement: the implicit-content shortcut already covers the
unnamed case.

### 11.3 Non-whitespace text and `{{ expr }}` cannot sit beside fills

Verified gap: `validate_fill_exclusivity` compares only node pairs, so
`<c-MyComp>text<c-fill .../></c-MyComp>` and `{{ x }}<c-fill .../>` parse
today, while node siblings are rejected and DJC errors on text. The fix
extends the sibling validation to reject non-whitespace `Text`/`Expr`
elements at a level that contains a `<c-fill>`; the recursive helper
`_contains_only_fills_and_control_flow` already applies exactly this rule one
level down, so the top level is the anomaly. Whitespace-only text remains
allowed and is formatting-only: never captured into a slot, never rendered
(section 4.3). Mechanism 3 note for the implementation pass: check whether
other sibling validations have the same nodes-only blind spot for
`Text`/`Expr` elements.

### 11.4a Duplicate-fill detection covers only fills outside control flow

Found while building fill collection: the parser rejected the same fill name
in mutually exclusive branches (`<c-if>`/`<c-else>`), where at most one fill
materializes at runtime. The duplicate-identity checks (static `name`,
`c-name` expression, `c-bind` tuple) now apply only to fills outside control
flow, the same scoping the overflow check already used; duplicates that DO
materialize together are caught at runtime during fill collection (section
4.3). A future improvement could analyze branches to catch guaranteed
duplicates (two same-name fills in one branch) statically.

### 11.4 Adjacent cleanup (observed, same area)

A `SlotNode` using one variable in both an attribute and its body compiles
with that variable duplicated in `used_vars` (observed: `("user", "user")`).
The repo rule is dedupe-preserving-first-seen-order; fix while in
`compile_simple_node`, and sweep the other node kinds for the same miss.

---

## 12. Out of scope (follow-ups this design enables)

- **Parse-time fill validation against component slot declarations.** Feed
  each registered component's slots (from `Component.Slots` or its template's
  `template.slots`) into `parse_template(user_rules=...)` when parsing
  *parent* templates, so `<c-fill name="typo">` fails at template compile
  with the already-implemented Rust checks. A flagship DX feature DJC's
  architecture cannot reach; needs the registry/parse plumbing, not slot
  runtime work.
- **Provide/inject across slots**, with the `<c-provide>` design.
- **Slot metadata consumers** (CSS scoping via `Slot.extra` +
  `on_slot_rendered`), with the dependency extension.
- **Const-folding around slots.** Slots are never part of the const
  signature; whether a fold may cross a slot site is a question for the
  parked constness design ([`constness.md`](constness.md)), not this one.

---

## 13. Alternatives considered

- **Render fill bodies eagerly at collection (pass 1).** Rejected: breaks
  scoped slots (slot data is only known at the slot site), breaks slots
  rendered in loops (one body, N data values), and renders content for slots
  that may never render. Laziness is load-bearing, not an optimization.
- **A fill-discovery render pass (DJC's `FILL_GEN_CONTEXT_KEY` model).**
  Rejected: citry's compiler already hands over `FillNode`s and
  `contains_fills`; re-rendering to discover structure would reintroduce the
  string-medium workaround this engine exists to remove.
- **Plain callables instead of a `Slot` class.** Rejected: loses the
  normalization point for strings/elements/renders, the metadata + `extra`
  seam extensions need, and the standalone-callable contract with escaping
  applied consistently.
- **A standalone fallback type (DJC's `SlotFallback`).** Rejected in favor of
  the fallback being a `Slot` (3.3): one less type, the `{{ fallback }}` path
  reuses the ordinary Slot detection, `str()` coercion comes from
  `Slot.__str__` which every slot benefits from, and the fallback becomes
  forwardable as ordinary slot content. DJC's unfilled path already wraps the
  fallback body as a `Slot` internally, so the separate type carried no extra
  capability. What would falsify this: a need for fallback-specific behavior
  that must not apply to ordinary slots; none is known, and `Slot.extra` can
  carry a marker if one appears.
- **DJC's `default` flag on `<c-slot>`.** Rejected in favor of the README's
  name-based model; see 11.2 for what it deletes. What would falsify this: a
  real need for a component whose default slot must carry a semantic name
  *and* be implicitly fillable; such a component can rename its slot or
  accept explicit fills, so the cost is considered acceptable.
- **Scanning only same-owner renders, with slot renders specially tagged**
  (instead of section 8's descend-everywhere). Rejected: a tag on
  `CitryRender` adds state to carry and keep correct, while
  descend-everywhere is already safe by the completed-queue invariant and
  costs one extra walk over deferred-free subtrees.
- **Fill-collection dispatch.** Three designs were weighed for how the
  fill-group walk (4.4) decides what each body item contributes:

  1. *A closed `isinstance` walk* (one collector function switching on
     `FillNode`/`IfNode`/`ForNode`). Simplest, and the first form built; its
     weakness is that the dispatch is closed: a node kind the collector does
     not enumerate (one injected by an extension, or a future control-flow
     tag) is rejected as foreign content even when it could legitimately hold
     fills.
  2. *Collect by rendering the body*, with `FillNode.render` registering
     itself into a collection channel carried on the context (the
     object-shaped form of django-components' `FILL_GEN_CONTEXT_KEY`
     mechanism). Its genuine strengths: dispatch is open through ordinary
     render polymorphism; branch and loop semantics are identical to
     rendering *by construction*; the per-iteration context falls out of the
     rendering walk with no extra plumbing; and `FillNode` gets a real
     `render`. Rejected for four costs: (i) the collection channel is ambient
     state on the context that every node render must tolerate, exactly the
     mode-flag machinery (`_is_extracting_fill` and friends) this design
     deletes from django-components; (ii) an invalid template runs side
     effects before the violation is detected: a stray `{{ expr }}` evaluates,
     and a stray component resolves its kwargs and mints a
     `DeferredComponent` that must then be kept away from the render queue;
     (iii) error provenance degrades, because the violation is found in the
     *produced parts*, where a text part no longer knows its source position;
     (iv) the walk builds a throwaway parts tree (wrapper renders per branch
     and iteration) only to discard it.
  3. *Polymorphic `collect_fills(context, sink)`* (chosen): a second method on
     the node contract, so dispatch is open like design 2, but collection
     never calls `render`, so designs 2's four costs do not apply. The drift
     risk that design 2 eliminates by construction is handled by sharing the
     branch/iteration logic (`active_branch_body`/`iter_bodies`) between
     `render` and `collect_fills`.

  What would falsify choice 3: a node whose fill contribution cannot be
  expressed without rendering (none is known; even `<c-for>` only needs its
  iterable evaluated), or extension nodes needing collection behavior that
  the `sink` interface cannot carry, which would argue for the richer ambient
  channel of design 2.

What would falsify the central closure design: a requirement that a fill see
variables of the *child* component (the receiving side) without opting in
through slot data. Both django-components #1259 and this design treat that as
an anti-feature; if a hard use case appears, slot data (`<c-slot c-x="...">`)
is the sanctioned channel before any context sharing would be reconsidered.

---

## 14. Phasing and test plan

Single MVP phase (dynamic fills included; they are load-bearing in the parser
contract and cannot be cut cleanly), preceded by the parser fixes:

1. **Done.** Parser fixes (11.1-11.4), with `tag_parser_fills.rs` /
   `tag_compiler.rs` and compiler-comment updates. Observe-then-lock was used
   for the new assertions.
2. **Done.** `citry/slots.py`: `Slot` (including `__str__`), `SlotContext`,
   `normalize_slot_fills`, typing aliases; `_render_value` detections (3.5).
   Tests in `tests/test_slots.py`.
3. **Done.** Collection: `ComponentNode.render` body handling (section 4),
   dispatched through the polymorphic `Node.collect_fills` + `FillSink`
   (section 4.4), `CitryElement.slots` populated from both channels (template
   fills and the `slots=` kwarg, 9.1), `Component.__init__` normalization
   (9.2). `IfNode`/`ForNode` gained `active_branch_body`/`iter_bodies` so
   collection and rendering share the branch/iteration logic. Includes the
   11.4a parser relaxation. Tests in `tests/test_slot_fills.py`; until phase
   4, slots are consumed via `template_data(kwargs, slots)` + `{{ slot_var }}`.
4. **Done.** Resolution: `SlotNode.render` (section 5) with the
   `on_slot_rendered` hook (section 7); the fill and the fallback render
   through one path (both are Slots, invoked with ``(data, fallback)``).
   `FillNode.render` stays unreachable in normal flow (fills are consumed at
   collection; reaching `FillNode.render` means a parser/runtime bug and
   keeps raising). Tests in `tests/test_slot_node.py`, including the README
   examples verbatim.
5. **Done** (with phase 3; collection makes fills invocable, so components
   inside slot content need it immediately). Queue fix: `_scan_deferred`
   descend-everywhere + lexical-owner merge target, plus the
   `is_component_root` serializer fix (section 8).
6. **Hook**: `on_slot_rendered` (section 7).

Tests, ported from the DJC suites plus citry-specific cases: fill-or-fallback
(bodied + self-closing slots); implicit default content (incl.
whitespace-only ignored, content with no default slot silently unused);
explicit `name="default"`; duplicate slot sites sharing one fill; scoped data
(static attrs, `c-*` attrs, `c-bind` spread, per-iteration data in loops);
`data`/`fallback` opt-ins, both, same-var error; lazy fallback coerced twice;
required (+ fuzzy hint, + dynamic `c-required`, + untaken-branch no-error);
dynamic fills (`c-name` in `<c-for>`, runtime duplicate error); passthrough
slots and the three-level nested-slot override matrix; Python `slots=` with
str/SafeString/fn/Slot/CitryElement/CitryRender (escaping per 3.1);
`{{ my_slot }}` and `{{ my_slot({...}) }}`; grandchild-in-fill through the
queue (incl. the three-level passthrough case from section 8) with deps
asserted at the root; `on_slot_rendered` replace/raise; `str(Slot(...))`
standalone invocation.
