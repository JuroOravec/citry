# Design: deferred rendering (infinite depth, top-down passes, component-id markers)

**Status (2026-06-09): Phase A and Phase B built.** This document specifies how
citry renders a component tree without recursion limits, in a top-down order, and
how it tags each component's root element(s) with a component-id marker. It is the
citry port of the two django-components features: infinite render depth and the
multi-pass render that powers per-instance JS/CSS attribute passing. Phase A (the
deferred queue) lives in
[`component_render.py`](../../packages/py/citry/citry/component_render.py)
(`render_impl` drive loop, `_render_one`, the `_RenderTask`/`_FinalizeTask`
queue) and [`citry_render.py`](../../packages/py/citry/citry/citry_render.py)
(`DeferredComponent`). Phase B (the `data-cid-<ID>` markers) lives in
[`serialize.py`](../../packages/py/citry/citry/serialize.py). Tests in
[`test_deferred_render.py`](../../packages/py/citry/tests/test_deferred_render.py)
and [`test_markers.py`](../../packages/py/citry/tests/test_markers.py). The only
part still deferred is the CSS-scoping attribute (`all_attributes`, section 6.2.1),
which lands with the dependency extension.

It extends [`rendering.md`](rendering.md), which defines the three-phase
pipeline (`CitryElement` -> `CitryRender` -> serialize) and the `CitryContext`.
That doc's section 10 phasing stops before this work. For the const-folding
interaction see [`constness.md`](constness.md); for the extension lifecycle that
owns the dependency flow see [`extensions.md`](extensions.md). Operating rules
are in [`/CLAUDE.md`](../../CLAUDE.md).

Upstream reference: the django-components implementation studied for this design
is [`_djc_reference/component_render.py`](../../packages/py/citry/_djc_reference/component_render.py)
(the `component_post_render` queue) and
[`_djc_reference/dependencies.py`](../../packages/py/citry/_djc_reference/dependencies.py)
(`set_component_attrs_for_js_and_css`, `insert_component_dependencies_comment`).

---

## 1. The two problems, kept separate

These are easy to conflate, but they are independent and only one of them is
foundational:

1. **Render depth.** Rendering a component recursively renders its nested
   components, which renders theirs, and so on. Each level consumes Python
   stack, so a naive recursive renderer caps out at roughly 60 component levels.
   citry has this limit today: [`ComponentNode.render`](../../packages/py/citry/citry/nodes/__init__.py)
   ends with `return render_impl(element, parent=component)`, a direct recursive
   call.

2. **Marker stacking order.** To tag a component's root element(s) with a marker
   attribute, and to let a parent's marker reach a child that *is* the parent's
   root (the `<div data-cid-parent data-cid-child>` case), the markers must stack
   in a definite order. citry serializes **top-down, parsing each frame once**,
   with child-component frames emitted as `<template c-render-id>` placeholders so
   the marking scan (`mark_html`) can report which children sit at the root
   and must inherit the parent's root attributes (section 6). This order concerns
   the markers (problem-2 feature) only; depth (problem 1) does not require any
   particular order.

Because of this split, the work phases cleanly: deferred queue rendering first
(solves depth), markers second (built on top, decided at serialization, and only
consumed by the JS/CSS dependency runtime). The render queue commits to no
ordering: it just builds the resolved `CitryRender` tree. The top-down order is a
property of the *serialization step*, which runs after the queue has finished
(section 6.2).

## 2. What django-components needed that citry does not

DJC operates over strings. To carry "which components rendered" across a string
boundary it embeds `<!-- _RENDERED ... -->` comments and regex-scans the final
document ([`dependencies.py` `insert_component_dependencies_comment`](../../packages/py/citry/_djc_reference/dependencies.py),
`COMPONENT_COMMENT_REGEX`). To assemble a deep tree without recursion it emits
`<template djc-render-id="...">` placeholder strings and re-parses them out of
each component's HTML in a flat queue ([`component_post_render`](../../packages/py/citry/_djc_reference/component_render.py)).

citry keeps the render output as a struct, `CitryRender.parts` (a heterogeneous
`list[str | CitryRender]`, see [`citry_render.py`](../../packages/py/citry/citry/citry_render.py)).
So citry does not need comment markers or placeholder-string parsing to know
which components rendered or to assemble the tree: ownership is already encoded
structurally, and the dependency bag rides on `CitryContext.extra`. The string
machinery in DJC exists only because its medium was a string.

DJC also needs a `ContextVar` render stack
([`_component_render_stack`](../../packages/py/citry/_djc_reference/component_render.py))
to detect "am I nested inside another render," because `{% component %}` calls
`render()` recursively. citry does not, see section 5.

## 3. What citry already has for the markers

The hardest sub-problem of the marker feature is locating a component's **root
element(s)** so the attribute can be attached. citry compiles plain HTML
elements into static strings, not nodes: `<div class="card" data-x="{{ v }}">`
compiles to `["<div class=\"card\" data-x=\"", ExprNode(...), "\">...", ...]`.
There is no element node to target, so root detection needs HTML structure
awareness.

citry already ships that primitive. The Rust crate
[`citry_html_transform`](../../crates/citry_html_transform) exposes two entry
points (surfaced under
[`citry_core.html_transform`](../../packages/py/citry_core/citry_core/html_transform/__init__.py)):
`mark_html(html, root_attributes, placeholder_attr)`, a single-pass scan that
splices attributes onto the root element(s), reports which placeholders sat at
the root, and splits the output around the placeholders; and
`transform_html(html, root_attributes, all_attributes, watch_on_attribute)`,
a full rewrite that can also inject attributes onto *all* elements. Both
handle multiple roots, the exact capability DJC gets from
`set_html_attributes`. Their tests
([`marker.rs`](../../crates/citry_html_transform/tests/marker.rs),
[`test_html_transformer.py`](../../packages/py/citry_core/tests/test_html_transformer.py))
cover multi-root and nested cases. So the markers can be built by reusing this
crate, with no compiler change.

## 4. Phase A: the deferred render queue (infinite render depth)

Phase A is pure Python in the `citry` package. It touches no grammar, AST,
compiler output, `LangImpl`, or PyO3 surface, so it is outside the plan-mode and
prior-art gate in [`/CLAUDE.md`](../../CLAUDE.md). It delivers unbounded render
depth and the children-first `on_component_rendered` finalization, with no
markers. The serialize-time marker ordering (section 6) is independent of it.

### 4.1 A new render part: `DeferredComponent`

Add a third member to the `RenderPart` union (today `str | CitryRender` in
[`citry_render.py`](../../packages/py/citry/citry/citry_render.py)):

```python
class DeferredComponent:
    __slots__ = ("element", "parent", "inherited_attrs", "resolved")
    # element:         CitryElement, with kwargs ALREADY resolved against the
    #                  live context (see 4.2). Slots/body are carried here too
    #                  once the slot subsystem lands.
    # parent:          Component, for parent/root linkage on the child render.
    # resolved:        CitryRender | None, filled when the queue resolves it.
```

`DeferredComponent` carries no marker state. Markers are applied at serialize
time (section 6.2): a component's own id is read from
`resolved.context.component.id`, and the inherited root attributes are passed as a
parameter of the serialization recursion, never stored on a render-phase struct.

### 4.2 Resolve kwargs eagerly, defer only the render

The one correctness rule: a `ComponentNode`'s kwargs must be resolved in the
first pass, while the surrounding context is live. Kwargs can reference
variables that exist only transiently, most importantly `ForNode` loop bindings,
which are built into a per-iteration child context in
[`ForNode.render`](../../packages/py/citry/citry/nodes/__init__.py). If kwarg
resolution were deferred to a later pass, those bindings would be gone.

So [`ComponentNode._resolve_kwargs`](../../packages/py/citry/citry/nodes/__init__.py)
still runs in pass 1. Only the child's *render* (its `template_data`, its body
walk) is deferred. `ComponentNode.render` stops recursing: instead of calling
`render_impl`, it resolves kwargs, builds the `CitryElement`, and returns a
`DeferredComponent` part.

### 4.3 Split the render entry point

Split today's [`render_impl`](../../packages/py/citry/citry/component_render.py)
into two:

- `_render_one(element, parent) -> CitryRender`: render a single component's body
  into a parts list. Nested components in that body surface as
  `DeferredComponent` parts. No recursion into children, no queue drive.
- `render_impl(element) -> CitryRender`: the user/root entry. Calls
  `_render_one` for the root, then drives the queue (4.4) to completion, and
  returns a `CitryRender` with no `DeferredComponent` parts remaining.

### 4.4 The drive loop

Heap-bound, non-recursive **depth-first with per-component finalize markers**.
This is DJC's `component_post_render` structure
([`_djc_reference/component_render.py`](../../packages/py/citry/_djc_reference/component_render.py)),
with the strings removed: a `DeferredComponent` *is* DJC's `ComponentPart` (no
regex `parse_component_result` needed), and splicing a child's `CitryRender` into
its parent's parts *is* DJC's "append result to parent" step (the struct linkage
does it). Firing the hook on the finalize marker reproduces DJC's `is_last`
finalization (section 7).

A `position` (the `_DeferredComponentPosition` type) is a
`(containing_list, index, parent_context)` triple: the list and index say where
the `DeferredComponent` sits, so we can put its result there, and
`parent_context` is the `CitryContext` of the component that owns it (where its
dependencies are copied, section 4.5). For the root, `position` is `None`. The
stack holds two kinds of work item:

```
def scan(render):  # the DeferredComponents directly owned by `render`'s component
    walk render.parts; for nested CitryRenders that SHARE render.context.component
    (control-flow: IfNode/ForNode/TemplateNode) descend in; STOP at component
    boundaries (a nested render whose context.component differs); yield each
    DeferredComponent as Render(deferred, position=(its list, its index, render.context)).

def locate(containing_list, index, target):  # index is only a hint
    check containing_list[index] first; if it is not `target`, scan the whole
    list for it (the list may have been edited)
    # each step swaps one item for one item, so other items keep their positions

stack = []
root_render = _render_one(element, parent=None)
push Finalize(root_render, position=None)
push reversed(scan(root_render))         # source order: first child popped first
while stack:
    item = stack.pop()
    if item is Render(deferred, position):
        child_render = _render_one(deferred.element, deferred.parent)
        locate + replace the deferred in position.list with child_render
        push Finalize(child_render, position)
        push reversed(scan(child_render))   # grandchildren land above this Finalize
    elif item is Finalize(render, position):
        comp = render.context.component
        final = apply on_component_rendered(comp, render)   # str->wrap, None->render, raise->raise
        if position is None:             # root
            root_result = final
        else:
            locate + replace child_render in position.list with final
            merge final.context deps into position.parent_context     # section 4.5
return root_result
```

Because each `Render` adds its children *above* its own `Finalize`, and we always
take from the top of the stack, a component and everything inside it finish (and
get finalized) before we return to the parent's `Finalize`. So
`on_component_rendered` runs children-first, the moment each component is done,
without waiting for the whole page and without counting children. Adding
`reversed(scan(...))` keeps siblings in source order (first child taken first),
which the dependency de-duplication relies on. The result is the same hook order
as the old approach where one component rendered the next directly
(`on_component_input` -> `on_component_data` -> `on_component_rendered`, children
before parents); the only difference is the depth limit is gone. Checking the
remembered index first and otherwise scanning the list keeps the position correct
even if user code or an extension edited `.parts` in between.

Marker ordering (section 6) is a separate, serialize-time concern; it does not
depend on this drive order. The drive's job is only to produce a fully-resolved,
finalized `CitryRender` tree.

### 4.5 The dependency merge: two sites, not one

There are two distinct merges, and only one moves:

- **Embedded eager renders stay in `_render_body`.** A `{{ element }}` expression
  whose value is a `CitryElement`/`CitryRender` is rendered eagerly by
  `_render_value` (its own complete `render_impl` drive) and surfaces as a
  `CitryRender` from a *different* context. `_render_body`'s existing check
  (`isinstance(part, CitryRender) and part.context is not context`) merges its
  deps, unchanged. A `DeferredComponent` is not a `CitryRender`, so it passes that
  check untouched.
- **Deferred components merge at `Finalize`, in the drive loop.** A child's
  `extra` is only fully populated once its own descendants have finalized (each
  grandchild merges up at *its* `Finalize`). So the merge of a child's deps into
  its parent happens at the child's `Finalize` (section 4.4), *not* when the child
  is first resolved. Merging at resolution time would capture an empty `extra`.

Both reuse [`_merge_dependencies`](../../packages/py/citry/citry/component_render.py)
(the documented hook-conversion seam). Control-flow `CitryRender`s that share the
parent context still need no merge, same rule as today.

## 5. Why citry needs no render-stack ContextVar

DJC's recursion goes through `{% component %}` -> `render()`, so any code path
(including a user calling `.render()` inside `get_template_data`) can re-enter
the renderer, and DJC tracks that with a `ContextVar` to pick the right
dependency strategy.

In citry, `ComponentNode.render` never calls `render_impl`; it only ever
produces a `DeferredComponent`. The only callers of `render_impl` are the user
(via `CitryElement.render`) and nothing else. A user who calls `Inner.render()`
inside `Outer.template_data` gets a self-contained, fully-driven subtree (its own
queue), which then embeds as a part of `Outer`'s render and merges its deps
upward through the same section-4.5 path. Composability and depth-safety fall out
without any ambient stack state.

## 6. Phase B: component-id markers via `mark_html`

**Status (2026-06-09, updated 2026-06-11): built.** The id markers are added on
every `serialize()`,
implemented in [`serialize.py`](../../packages/py/citry/citry/serialize.py) and
covered by [`test_markers.py`](../../packages/py/citry/tests/test_markers.py).
Marking uses `mark_html`, the single-pass root scan (see section 3); the
CSS-scoping half (the `all_attributes` set, section 6.2.1) is still deferred
to the dependency extension and will ride the every-element `transform_html`
pass when it lands. The markers let the future browser runtime scope CSS and
run per-instance JS.

The marker attribute is **`data-cid-<ID>`**, a valueless (boolean) attribute,
where `<ID>` is the component render id (already `c`-prefixed, see
[`constants.py`](../../packages/py/citry/citry/constants.py)). `mark_html`
writes a boolean attribute in its empty-value form, so a marker reads
`data-cid-cAb3d9=""`. The boolean form lets multiple component ids sit on one
element, which is what the parent-root-is-child case (6.1) requires.

### 6.1 The structural fact to reproduce

A component's marker goes on its **root element(s)**, and when a parent's root
*is* a child component, the child's root element carries both ids:

```
Parent template "<c-child/>"   ->  <div data-cid-cChild data-cid-cParent>...</div>
Parent template "<div><c-child/></div>"  ->  <div data-cid-cParent><span data-cid-cChild>...
```

Root elements compile to static strings, not nodes (section 3), so this needs
HTML-structure awareness, which is exactly what the `citry_html_transform`
crate provides.

### 6.2 The model: top-down marking, then bottom-up assembly, at serialize time

The render output stays a `CitryRender` tree (no strings) until `serialize()` is
called. Marking each component's frame exactly once needs a parent processed
before its children (a child's markers depend on the parent's scan report), while
joining the final string needs a child finished before its parent. So
[`serialize.py`](../../packages/py/citry/citry/serialize.py) does it in two
passes, neither of which calls itself (the same reason the render side uses a
queue, so depth is not capped by Python's recursion limit):

**Pass 1 (top-down), for each component frame, given the markers it inherited
from its parent:**

1. Build the frame string by joining the component's parts. A nested part that is
   a child component (detected structurally by `part.context.component is not
   comp`, the same predicate the deferred-scan uses, section 4.4) is emitted as a
   placeholder `<template c-render-id="<child id>"></template>`, and the child is
   recorded. A nested control-flow render (`part.context.component is comp`, or a
   component-less render) is joined in directly.
2. Run `mark_html(frame, root_attributes=[...], placeholder_attr="c-render-id")`,
   where `root_attributes` is the component's `data-cid-<id>` marker plus the
   markers inherited from the parent. These go on the component's root
   element(s) only. (The CSS-scoping attribute, which goes on *every* element
   of the frame, is deferred to the dependency extension and uses the
   every-element `transform_html` pass; see 6.2.1.)

   In one scan, the call splices the markers onto the root tags and splits the
   frame around the child placeholders, reporting per placeholder the
   attributes spliced into it (non-empty only when that placeholder was itself
   at the root). Each such child inherits those markers, processed next.

**Pass 2 (bottom-up):** walk the components in reverse of pass-1 order (so a
child is finished before its parent) and join each frame's segments with its
children's finished HTML in the placeholder slots.

The placeholder is a temporary token used only while serializing, never stored on
a render object. The component's own id is read from `r.context.component`, so no
marker state lives on the render objects. Each frame is scanned once (a child is
still just a placeholder when its parent is marked), so the pass is `O(total
size)`, and per-component CSS scoping stays correct because a parent's
scoping attribute never reaches a child's interior elements. The stacked result is
`<div data-cid-<child>="" data-cid-<parent>="">` (child marker first, then
inherited).

This is DJC's `component_post_render` marking algorithm
([`_djc_reference/component_render.py`](../../packages/py/citry/_djc_reference/component_render.py),
[`dependencies.py` `set_component_attrs_for_js_and_css`](../../packages/py/citry/_djc_reference/dependencies.py)),
minus the `<!-- _RENDERED -->` dependency comments: citry collects deps
structurally in `extra`, so only the attribute-marking half of DJC's string pass
is reproduced, and the tree assembly itself stays struct-based.

#### 6.2.1 The two attribute kinds

Two distinct CSS-related attributes attach to different element sets, and the
top-down pass is what keeps them correctly scoped:

- **CSS-scoping attribute** (`all_attributes`): goes on **every** element of a
  component's own frame, so the component's CSS rules select only its own
  elements. This is the case that *requires* the top-down pass: a frame is
  transformed while its children are still placeholders, so a parent's
  scoping attribute never leaks onto a child's interior elements.
- **CSS-variables binding** (`root_attributes`): the per-instance attribute that
  binds CSS custom properties (computed from the component's css data) onto the
  component's **root** element(s), alongside the `data-cid-<id>` id marker.

In the captured reference, `set_component_attrs_for_js_and_css` puts the id marker
and the CSS-variables binding into `root_attributes` and passes `all_attributes=[]`
([`dependencies.py`](../../packages/py/citry/_djc_reference/dependencies.py)); the
scoping-attribute (`all_attributes`) case is the one citry adds. The root-only
attributes ride the per-frame `mark_html` scan; a frame that also needs the
scoping attribute uses the every-element `transform_html` pass instead.

### 6.3 Why not bottom-up

A bottom-up alternative (serialize children first, inline them, then
`transform_html` the parent's full frame) needs no placeholder or watch-map and
stacks the `data-cid` markers automatically. It is rejected because:

- **CSS scoping is a core feature.** Per-component CSS scoping uses `all_attributes`
  to tag a component's own elements; inlining the children first and then
  transforming would also tag the children's inner elements with the parent's
  scope, which is wrong. Correct scoping needs each frame transformed while its
  children are still placeholders, which is the top-down model.
- **Re-parse cost.** Bottom-up re-parses each ancestor's inlined children, making
  it `O(depth x size)`; the top-down pass is `O(total size)`.

## 7. Interactions

- **Slots.** `ComponentNode` with body content still raises today.
  `DeferredComponent` carries the element's slots/body so deferred rendering is
  slot-ready; slot resolution is specified in [`slots.md`](slots.md), whose
  section 8 also extends `_scan_deferred` to descend into cross-owner renders
  (fill bodies can defer grandchildren).
- **Const-folding.** A folded component boundary must still mint a fresh render
  id and re-merge its deps each render
  ([`constness.md`](constness.md) section 6, [`rendering.md`](rendering.md)
  section 7). A folded placeholder therefore produces a `DeferredComponent` each
  render, not a baked string. The two designs agree.
- **`on_component_rendered` timing.** This hook fires **the moment a component's
  nested subtree is fully resolved** (children before parent), matching DJC, so a
  post-processing hook sees fully-resolved children. Today it fires inside
  [`render_impl`](../../packages/py/citry/citry/component_render.py) (step 8)
  before any child is rendered; under deferral it moves out of `_render_one` onto
  the `Finalize` work item (section 4.4). Because each component's `Render` adds
  its children above its own `Finalize` on the stack, the `Finalize` is reached
  only after everything inside the component has been rendered, which is exactly
  DJC's `is_last` finalization in [`next_renderer_result`](../../packages/py/citry/_djc_reference/component_render.py).
  A replacement returned by the hook (`CitryRender`/`str`) is put back at the
  component's recorded position. Error interception (a child's error bubbling into an ancestor's
  `Finalize`, as DJC allows) is a follow-up; the current skeleton re-raises, which
  is retained for now.

## 8. Open decisions

- **Error interception across the post-order hook pass** (section 7):
  decided and built. An ancestor (extensions' `on_component_rendered` today;
  the `on_render` generator when it lands) may catch a descendant's error
  and substitute content; errors travel by unwinding the task stack to the
  nearest enclosing `Finalize`. Design in [`on_render.md`](on_render.md)
  sections 4-5.
- **Exact attribute spellings** for the CSS-scoping attribute (`all_attributes`)
  and the CSS-variables binding (`root_attributes`), section 6.2.1. The element
  sets they attach to are settled (all elements vs root); only the concrete
  attribute names are decided with the dependency extension.

## 9. Suggested phasing

1. **Phase A (built).** `DeferredComponent`, the `_render_one`/`render_impl`
   split, the `_RenderTask`/`_FinalizeTask` drive loop, the finalize-time dep
   merge, and the children-first `on_component_rendered` (section 7). Pure Python.
   Delivers infinite depth. Tests cover deep nesting (600 levels, well past the
   old recursion limit), loop-variable kwargs resolved correctly under deferral,
   deps bubbling to root `extra`, children-first and sibling-source-order
   finalize, the serialize-time unresolved-deferred guard, and nested
   `on_component_rendered` replace/raise.
2. **Phase B (built).** `data-cid-<ID>` markers, added on every `serialize()` via
   the two-pass (top-down marking, bottom-up assembly) pass in
   [`serialize.py`](../../packages/py/citry/citry/serialize.py): `<template
   c-render-id>` placeholders, the per-placeholder scan report, and inherited
   root attributes.
   Reuses the existing `citry_html_transform` crate, no compiler change.
   [`test_markers.py`](../../packages/py/citry/tests/test_markers.py) covers single
   root, multiple roots, nested-not-at-root, two- and three-level
   parent-root-is-child stacking, text-only (no marker), and fresh-id-per-render.
3. **Phase C** (with the dependency extension): the CSS-scoping `all_attributes`
   set (section 6.2.1), confined per-component by the same pass. Until then
   `all_attributes` is empty.
