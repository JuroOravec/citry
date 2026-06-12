# Design: the `on_render` hook, error bubbling, and render-path error tracing

**Status (2026-06-12): built, all steps of the plan (section 12).** The
summary entry lives in the [`citry_migration.md`](citry_migration.md)
implementation log. This document specifies one work package with four
coupled parts:

1. **`Component.on_render()`** - a per-component render hook, including a
   generator form that can post-process the component's fully-rendered output.
2. **Error bubbling** - a child component's render error travels up the
   component tree, and any ancestor's `on_render` generator may catch it and
   substitute new content. Today an error anywhere re-raises immediately.
3. **Render-path error tracing** - errors that escape carry the component path
   ("MyPage > Card > Avatar") and an underlined snippet of the template at the
   failing node, so the user can see where in the tree and where in the
   template the error happened.
4. **The `ErrorFallback` built-in component** - a React-style error boundary
   built on parts 1-2 (section 7). It ships in this package as the proof that
   the hook design actually carries its flagship consumer.

They are one package because 1 is useless for its flagship consumer (error
boundaries) without 2, 2 decides where 3's path frames get attached, and 4
exercises all three end to end.

For the render pipeline this hooks into see [`rendering.md`](rendering.md) and
[`deferred_rendering.md`](deferred_rendering.md). For the migration context see
[`citry_migration.md`](citry_migration.md) (the `on_render` and error-tracing
"To migrate" rows). For operating rules see [`/CLAUDE.md`](../../CLAUDE.md).

---

## 1. Prior art

django-components (all paths under `packages/py/citry/_djc_reference/`):

- The three hooks `on_render_before` / `on_render` / `on_render_after` and
  their docstrings: `component.py:1802-2066`.
- The generator protocol (`OnRenderGenerator`): `component_render.py:55-127`.
- The driving machinery: `make_renderer_generator` (`component_render.py:733`),
  `_call_generator` (`component_render.py:1364`), the versioned queue items
  (`QueueItemId`, `component_render.py:836`), error bubbling via `ErrorPart`
  and `handle_error` (`component_render.py:1163-1186`, `1289-1306`).
- Error tracing: `util/exception.py` (`set_component_error_message`,
  `with_component_error_message`, `add_slot_to_error_message`),
  `render_with_error_trace` (`component_render.py:219`), and the `full_path`
  threading through the queue.
- Template position in errors: `node.py:771`
  (`_format_error_with_template_position`, the underlined-snippet formatter).
  DJC only applies it to tag-signature `TypeError`s, and only over the start
  tag with made-up indices, because Django's parser does not keep the whole
  template; the NOTE at `node.py:143-147` wishes for per-node source +
  start/end metadata, which citry's nodes have.
- The flagship consumer: `components/error_fallback.py` (a React-style error
  boundary built entirely on the generator form).

citry (all paths under `packages/py/citry/citry/`):

- The drive loop `render_impl` with its `_RenderTask` / `_FinalizeTask` stack,
  `_render_one`, and `_finalize`: `component_render.py:80-247`.
- The extension hook `on_component_rendered`, which already threads
  `(render, error)` tuples: `extension.py:686-705`.
- `CitryRender` / `DeferredComponent` parts: `citry_render.py`.
- `Slot` metadata (`component_name`, `slot_name`): `slots.py:114-154`; the
  slot invocation site: `nodes/__init__.py` (`SlotNode.render`).
- `Component.parent` / `root` links set across component boundaries.
- Earlier decisions that constrain this one:
  [`deferred_rendering.md`](deferred_rendering.md) section 8 (error
  interception listed as an open decision; current skeleton re-raises) and
  [`dynamic_component.md`](dynamic_component.md) section 8, alternative B
  (dynamic components deliberately do NOT need `on_render`, so error
  boundaries are the driving use case, not delegation).

There is no existing `on_render` surface in citry; `_render_one` has no
component-level hook between building the context and walking the body.

---

## 2. The decision in one paragraph

Citry gets a single hook, **`Component.on_render()`**. DJC's
`on_render_before` and `on_render_after` are **not carried over**: the
"before" use case (preparing data) is `template_data()` and the extension
hooks, and the "after" use case is the generator form of `on_render` (code
after the `yield`). Both could be re-added later additively if real demand
appears; starting with one hook keeps the lifecycle surface minimal. Unlike
DJC, where the default `on_render` *is* the renderer (`return
template.render(context)`), citry's `on_render` **wraps** rendering: the
framework owns body building (const folding, compiled-body caching, extension
hooks), and the hook can only observe and replace the output. The generator
form receives the component's **completed `CitryRender`** (children resolved),
never a serialized string, keeping the object pipeline intact.

---

## 3. The `on_render` contract (user-facing)

### 3.1 Plain form

```py
class MyTable(Component):
    template = "<table>...</table>"

    def on_render(self):
        if not self.kwargs.get("rows"):
            return "<p>No data</p>"   # replace the output entirely
        return None                   # render the template as usual
```

- **Return `None`** (the default implementation): the template renders as
  usual.
- **Return replacement content**: the returned value is used as the
  component's entire output instead of the template. Accepted values follow
  the same rules as a `{{ ... }}` expression result (`_render_value` in
  `citry_render.py`): a `str` (autoescaping does NOT apply here, the value is
  the component's own output), a `CitryElement` (rendered, children deferred
  as usual), a `CitryRender` (inlined, dependencies merged), or a `Slot`.
- Because `None` means "no replacement", a component that wants literally
  empty output returns `""`.

The hook takes no arguments. Everything it needs is on `self`: `kwargs`,
`slots`, `id`, `parent` / `root`, `inject()` / `provide()`, `citry`. There is
no context or template object to pass; citry has neither as a user-facing
concept.

### 3.2 Generator form

Including a `yield` turns `on_render` into a generator. The code before the
first `yield` runs just before the template body is rendered; the code after
it runs once the component's whole subtree has finished rendering:

```py
class MyTable(Component):
    template = "<table>...</table>"

    def on_render(self):
        # BEFORE: runs before the template renders (side effects only;
        # data for the template belongs in template_data()).
        result, error = yield

        # AFTER: result is the component's completed CitryRender
        # (children rendered), or None if rendering failed.
        if error is not None:
            return "<p>Something went wrong</p>"   # swallow the error
        return None                                # keep the result
```

The protocol, step by step:

- **`yield` (bare, or `yield None`)** on the first yield means "render my
  template as usual". **`yield <content>`** means "use this content as my
  output instead" (same accepted values as the plain-form return).

  This is a deliberate divergence from DJC, where the user yields
  `lambda: template.render(context)` so the framework can catch rendering
  errors on their behalf. In citry the framework renders and routes errors
  through the queue anyway, so there is nothing for the user to call; the
  lambda dance disappears.

- **The yield receives `(result, error)`** once the yielded (or default)
  content has fully settled, children included. `result` is a `CitryRender`,
  or `None` when rendering failed; `error` is the exception, or `None` on
  success. Exactly one of the two is set.

  The result is the live render object, NOT a string. Inspect its parts or
  hand it around, but do not serialize it here unless you are replacing the
  output with the serialized form: serialization is one-shot
  ([`rendering.md`](rendering.md) section 5.3).

- **Multiple yields are supported.** Each `yield <content>` discards the
  previous output, renders the new content (deferring and resolving any
  components inside it), and resumes the generator with that new
  `(result, error)`. After the first yield, a bare `yield` / `yield None` is
  answered immediately with the current result unchanged (use it to peek
  again without re-rendering).

- **Ending the generator** decides the final output:
  - `return <content>`: the content replaces the output (processed like a
    yielded value, but the generator is done and is not resumed again).
  - `return` / `return None`: keep the current `(result, error)`; if the
    error is still set, it continues to bubble.
  - `raise`: the raised exception becomes the component's error (the original
    result and error are discarded) and bubbles to the parent.

- A generator that returns before its first yield behaves like the plain
  form (its return value is the replacement, or `None` for the default).

`OnRenderGenerator` is published as a type alias for annotating the hook:

```py
OnRenderGenerator: TypeAlias = Generator[
    "RenderReplacement | None",                        # what you yield
    "tuple[CitryRender | None, Exception | None]",     # what you receive
    "RenderReplacement | None",                        # what you may return
]
```

with `RenderReplacement` the accepted replacement values (section 3.1).

### 3.3 What the hook is for (and not for)

For: error boundaries, post-processing the rendered output, wrapping or
replacing output conditionally, instrumentation around a single component's
render. Not for: passing data to the template (that is `template_data()`),
tree-wide concerns (those are extensions; `on_component_rendered` already
exists and fires for every component), and dynamic delegation (settled
differently in [`dynamic_component.md`](dynamic_component.md)).

---

## 4. How it threads through the pipeline

All changes live in `component_render.py`; the stack-driven drive loop is
already the right shape.

### 4.1 In `_render_one`

`on_render` is invoked after the context is built (step 5) and before the
body is built and walked (step 6-7):

- Plain form returning `None`: proceed exactly as today.
- Plain form returning content: skip body build and walk; the parts are the
  processed replacement. (Skipping the build is a small perf win and is safe:
  the compiled-body cache is per class and will be built whenever a render
  actually needs it.)
- Generator: prime it (`send(None)`) to run the before-phase. The first
  yielded value selects the parts as above (None = default body walk, content
  = replacement). The live generator travels with the component's
  `_FinalizeTask`. An unrenderable yielded value (the `TypeError` from the
  coercion) is delivered straight back into the generator as
  `(None, error)`, at priming time and at settle time alike, so every yield
  uniformly receives the settled result or failure of what it yielded.
- `is_generator` (a trivial check, ported from djc `util/misc.py`) tells the
  forms apart.

`_render_one` returns the `CitryRender` plus the live generator (if any);
`render_impl` stores the generator on the component's `_FinalizeTask`. The
generator is drive-loop state: it does not live on `CitryRender` or
`CitryContext`.

### 4.2 In the drive loop: finalize with a live generator

A `_FinalizeTask` pop becomes:

1. **If the task carries a live generator**, resume it with
   `(render, error)`:
   - It **yields new content**: process the replacement (coerce, swap it in
     at the component's recorded position), push a new `_FinalizeTask` for
     the same component (generator still attached) and the replacement's
     deferred-scan tasks above it, and stop here. The generator will be
     resumed again when the new content settles. This is the multiple-yields
     loop.
   - It **yields `None`**: resume again immediately with the unchanged
     `(render, error)` (section 3.2).
   - It **finishes (`StopIteration`)**: if `StopIteration.value` is content,
     process it as a replacement, push a `_FinalizeTask` WITHOUT the
     generator, and stop here. If the value is `None`, keep the current
     `(render, error)` and fall through to step 2.
   - It **raises**: the new exception replaces `(render, error)` as
     `(None, error)`; fall through to step 2 (extensions get to see it, then
     it bubbles).
2. **Run the extension hook** `extensions.on_component_rendered(component,
   render, error)` (today's `_finalize`). The manager already threads
   `(render, error)` and lets an extension replace either. Ordering matches
   DJC: the component's own generator settles fully before extensions see
   the result.
3. **Settle**: if an error is still set, bubble it (section 5). Otherwise
   swap the final render in at the recorded position and merge its collected
   dependencies into the parent context (today's behavior).

Note the dependency-merge timing: the merge into the parent happens only at
step 3, for the render that is actually kept. Output discarded by a yield or
a replacement never merges its dependencies upward; replacing a component's
output replaces its dependency contribution too. (Dependencies collected from
children that finalized into this component's own context before the
replacement are an accepted edge; see open question 3.)

Replacement renders inherit `is_component_root` from the render they stand in
for, the same rule `_finalize` applies today, so serialization framing and
the `transparent` opt-out keep working.

### 4.3 Why citry needs no version bookkeeping

DJC tracks `(component_id, version)` pairs and an `ignored_components` set
because its queue items are interleaved string fragments: when a component's
output is replaced, stale fragments of the old version are still sitting in
the queue and must be skipped when encountered. In citry the output is an
object (`CitryRender`); replacing it discards the old object wholesale, and
the stale pending work is removed by the same stack unwinding that delivers
the error (section 5.1). No versions, no ignore set.

---

## 5. Error bubbling

### 5.1 The mechanism: stack unwinding

The drive-loop stack has a useful invariant, by construction of how tasks are
pushed: **everything above a component's `_FinalizeTask` is exactly that
component's pending subtree work**. (When a `_RenderTask` runs, the child's
`_FinalizeTask` is pushed first and the child's own deferred tasks above it;
nothing else gets between them.)

So when a task raises (a `_RenderTask`, i.e. `_render_one` of a child, or a
finalize step):

1. Pop and discard stack entries until the nearest `_FinalizeTask`. The
   discarded entries are precisely the pending work of the enclosing
   component's now-dead output (the failed component's remaining siblings
   included; their already-finished renders die with the parent's parts).
2. Run that finalize with `(None, error)`: the ancestor's generator (if any)
   is resumed with the error and may swallow it by yielding or returning new
   content; then extensions' `on_component_rendered` may do the same.
3. If the error survives, repeat: unwind to the next `_FinalizeTask`.
4. If the root's finalize does not handle it, raise from `render_impl`, with
   the component path attached (section 6).

This reproduces DJC's `ErrorPart` / `handle_error` semantics (a child's error
invalidates the parent's current output; any ancestor may recover by
substituting content) with no extra data structures.

Errors raised synchronously inside a component's body walk (an expression, an
attribute, a slot fill invoked by `SlotNode`) surface from `_render_one` of
that component, which is a `_RenderTask` in the loop (or the initial root
call), so they enter the same path.

A subtlety carried over from DJC: when an ancestor swallows a descendant's
error, the intermediate components between them never produced a successful
render. Their generators (if any) are resumed once with `(None, error)`
during the unwind, so an intermediate component still gets its chance to
handle the error closest to where it happened; inner handlers win over outer
ones, exactly like nested `try` blocks.

One divergence from DJC: the failing component's *own*
`on_component_rendered` does not fire (DJC delivers `(None, error)` to it
first). The component never finished rendering, and in the kwargs-validation
case its instance never existed, so there is no finalize to run; the nearest
enclosing component is the first to see the error. The error's path frames
still name the failing component.

### 5.2 What this changes for existing behavior

Today `_finalize` raises immediately when the extension hook leaves an error
set. Under bubbling, the raise moves to the root; everything in between is a
chance to recover. For a tree with no `on_render` generators and no
error-handling extensions, the observable behavior is unchanged: the error
reaches the root and raises, now with a component path attached.

---

## 6. Render-path error tracing

Port of djc `util/exception.py`, adapted to citry's instance links.

### 6.1 The user-visible behavior

Any exception escaping a render carries the path from the root to the
component where it happened, prepended to the message:

```
RuntimeError: An error occurred while rendering components
MyPage > Card(slot:body) > Avatar:
<original message>
```

### 6.2 Mechanism

- `set_component_error_message(err, path)` and the
  `with_component_error_message(path)` / `add_slot_to_error_message(...)`
  context managers port to `citry/util/exception.py` essentially as-is: path
  frames accumulate on the exception object itself (`err._components`), and
  the message prefix is rewritten idempotently. Carrying the path on the
  exception means it survives bubbling, re-raising, and user `try/except`
  passthroughs without threading state through the loop.
- **Component frames come from the instance chain**, not from threaded
  `full_path` lists (djc needed those because its queue had no component
  objects in hand). At the point an error is caught (a failed `_RenderTask`
  or finalize), the chain `component.parent -> ... -> root` yields the path;
  class names are used (`type(component).__name__`), matching how citry
  names components elsewhere.
- **Slot frames** (`Card(slot:body)`) are added where a slot invocation is
  synchronous: `SlotNode.render` wraps the fill / fallback call in
  `add_slot_to_error_message(component_name, slot_name)`; `Slot` already
  carries both names. A component written inside fill content and deferred
  renders later, outside that wrapper; its path comes from its parent chain
  (the component that wrote the fill, since fills close over the writer's
  scope), without the slot frame. That is a small, documented divergence from
  DJC, where the threaded path retains slot frames for deferred descendants
  too; revisit if real error reports prove confusing (open question 4).
- `render_impl` attaches the root frame, so even a root-level failure names
  the component.

### 6.3 Template position in errors

The third layer of tracing: the error message also shows *where in the
template* the failure sits, as an underlined source snippet with real line
numbers.

The formatter already exists. DJC's `_format_error_with_template_position`
was ported into `citry_core` as
`citry_core/safe_eval/error.py::_format_error_with_context` (same algorithm:
two context lines around the span, line numbers, `^^^` underline, an
`_error_processed` marker). `safe_eval` applies it at expression-eval time
with the **expression string** as the source, which is why its snippet says
"line 1" regardless of where the expression sits in the template. The
template layer reuses the same formatter with the **template** as the
source; it becomes a public export of `citry_core.safe_eval`
(`format_error_with_context`) so citry does not copy the 100 lines or import
a private name.

The design:

- **One wrap site, `_render_body`**: each `item.render(context)` is wrapped;
  on error, the node's `source` (the full template string) and `position`
  (start/end indices), which every compiler-emitted node carries, feed the
  formatter. This single site covers control-flow bodies (they recurse
  through `_render_body`), slot fill and fallback bodies (`_make_body_slot`
  renders through `_render_body`), and attribute-resolution errors (they
  surface through the enclosing node's render, so they get the tag's span).
- **Innermost node wins**: the helper
  (`set_template_position_error_message(err, source, position,
  component_name)` in `citry/util/exception.py`) sets its own marker
  attribute on the error and is a no-op when it is already set, so the
  enclosing `IfNode` does not overwrite the failing `ExprNode`'s snippet.
  The marker is distinct from safe_eval's `_error_processed`, so an
  expression error keeps safe_eval's precise sub-expression caret *and*
  gains the template snippet with real line numbers.
- **A header line names the template's owner** ("In template of 'Page':"),
  taken from `context.component` at the wrap site. This is correct for fill
  content too: fill bodies render with the writer's context, and their nodes
  come from the writer's template. Without the header, the expression
  snippet and the template snippet would be two unlabeled code blocks.
- **Stacking by construction**: each decoration treats the current message
  as its head, so the final message reads path line (section 6.2, prepended
  last), original error + safe_eval's expression snippet (when the failure
  was in an expression), then the template snippet:

  ```
  ValueError: An error occurred while rendering components Page > Card > Card(slot:body):
  Error in call: ValueError: boom

       1 | broken()
           ^^^^^^^^

  In template of 'Page':

       3 |     <span>{{ broken() }}</span>
                     ^^^^^^^^^^^^^^^
  ```

- **Guards**: nodes injected by extensions may lack `source`/`position`
  (`getattr` checks); `template_data()` errors get no snippet (they are user
  Python with a real traceback), which is correct.

Two deliberate scope cuts: a child component's failure does not get the
parent's `<c-child>` tag position (the child renders from the drive loop,
away from the parent's node; its own body errors carry its own template's
positions, and the component path covers the chain) - an "included at line
N" breadcrumb carried on `DeferredComponent` is a possible later refinement.
And the snippet granularity for attribute errors is the enclosing tag's
span, not the single attribute; per-attribute spans (the attr nodes carry
their own `position`) are likewise a refinement.

This is strictly broader than DJC's version, which fires only for
tag-signature `TypeError`s over the start tag (see the prior-art note in
section 1).

---

## 7. The `ErrorFallback` built-in component

Part of this work package (it is the reason DJC built the generator form, and
implementing it validates the whole design end to end). It lands as a
built-in component in `citry/components/error_fallback.py`, with
`"error-fallback"` added to `BUILTIN_COMPONENT_NAMES` and created lazily via
the registry's builtins factory, the same arrangement as `<c-provide>` and
`<c-component>`. Usage: `<c-error-fallback>` wrapping the guarded content
(the default slot), with the fallback given either as the `fallback` kwarg or
as a `fallback` fill that receives the error as slot data. Giving both is an
error, matching DJC. Sketch:

```py
class ErrorFallback(Component):
    class Kwargs:
        fallback: str | None = None

    template = "<c-slot />"   # default slot: the guarded content

    def on_render(self):
        result, error = yield          # render the guarded content
        if error is None:
            return None                # success: keep it
        fallback_slot = self.slots.get("fallback")
        if fallback_slot is not None:
            return fallback_slot({"error": error})   # slot gets the error as data
        return self.kwargs.fallback or ""
```

Note how the slot-based fallback needs no template re-render (DJC re-rendered
the whole template with `error` pushed into the Context): the fill is a
`Slot`, calling it with data returns a render part, and that part is a valid
replacement. The replacement may itself contain components; the
multiple-yield processing handles that. If the fallback errors too, the error
bubbles past this component, which is the right behavior for nested
boundaries.

DJC registered the component as `"error_fallback"`; the citry reserved name
is `"error-fallback"` (the registry's kebab-case convention, like the other
built-ins).

---

## 8. Interactions

- **Const folding and body caching** are untouched: `on_render` runs per
  render, downstream of the per-class compiled body and the const body cache.
  A replacement bypasses the cached body for that render only.
- **Extensions ordering** matches DJC: a component's generator fully settles,
  then extensions' `on_component_rendered` runs, then the result is committed.
  Extensions never observe intermediate yields (DJC's
  `on_component_intermediate` is already classified Superseded in
  [`citry_migration.md`](citry_migration.md)).
- **`transparent` components** may use `on_render` like any other; the hook
  is orthogonal to serialization framing.
- **Slots**: `on_slot_rendered` fires inside the body walk as today,
  unaffected. A `Slot` returned as replacement content goes through
  `_render_value`, which already invokes it.
- **Streaming** ([`rendering.md`](rendering.md) section 7): the generator
  form is per-component post-processing, not output streaming; nothing here
  forecloses lazy parts. If streaming lands, a component whose `on_render`
  has a post-yield phase simply cannot stream past its own boundary (it needs
  its completed subtree), which is inherent to "post-process my output".
- **`<c-component>` / `<c-element>`** stay as designed; alternative B of
  [`dynamic_component.md`](dynamic_component.md) (delegating via `on_render`)
  remains rejected, now on cost rather than absence grounds.

---

## 9. Alternatives considered

**A. DJC's shape: `on_render(context, template)` as the renderer, yielding
lambdas.** Rejected: citry has no user-facing context or template object to
pass, and handing the user the render step would bypass const folding, the
compiled-body cache, and `on_template_compiled`. The lambda-yield exists only
because in DJC the user owns the (synchronous, fallible) render call.

**B. Keep all three hooks (`on_render_before` / `on_render` /
`on_render_after`).** Rejected for now (user decision, 2026-06-12): "before"
duplicates `template_data()` plus extension hooks, "after" duplicates the
generator's post-yield phase. Both are re-addable additively; removing a
shipped hook would not be.

**C. Error boundaries as an extension instead of a component hook.**
Rejected: an extension's `on_component_rendered` is tree-wide and cannot
express "this subtree, with this fallback" without per-instance
configuration, which is exactly what a component already is. The extension
hook stays as the tree-wide observer it is.

**D. Versioned queue items (DJC's `QueueItemId.version` +
`ignored_components`) instead of stack unwinding.** Rejected: versions exist
to skip stale string fragments in an interleaved queue; citry's object parts
plus the LIFO subtree invariant make discarding O(subtree) and explicit
(section 4.3).

## 10. What would falsify this design

- A real need for extensions to observe or veto intermediate yields would
  break the "generator settles, then extensions" ordering and force a
  per-yield hook.
- If the LIFO subtree invariant stops holding (e.g. a future scheduler
  reorders the stack for parallelism), stack unwinding no longer identifies
  the failed subtree and an explicit ownership map (DJC-style) returns.
- If dependency-merge policy turns out to require contributions from
  discarded output (e.g. a CSS dependency that must load even when the
  component errored and was replaced), the "replaced output replaces deps"
  rule in 4.2 is wrong and merging must move earlier, with explicit
  rollback.
- If error reports from deferred-in-fill components prove confusing without
  slot frames (section 6.2), the path needs breadcrumbs carried on
  `DeferredComponent` instead of being derived from the parent chain.

---

## 11. Open questions

1. **Public type names.** Settled: `RenderReplacement` and
   `OnRenderGenerator` live in `citry_render.py` and are exported from
   `citry`.
2. **Does `on_render` fire for components with no template?** Settled: yes.
   The hook fires before the template is even looked up; without a
   replacement, a template-less component renders empty as before.
3. **Stale `extra` from discarded children** (section 4.2): a child that
   finalized before a sibling's error killed the parent's output has already
   merged into the parent's context. Accepted for now (nothing populates
   `extra` yet); the dependency extension's merge-hook design
   ([`extensions.md`](extensions.md) section 9.1) is where a real policy
   lands.
4. **Slot frames for deferred descendants** (section 6.2): accepted
   divergence, revisit on evidence.

---

## 12. Implementation and test plan

Order of work (each step keeps the suite green):

1. **`citry/util/exception.py`**: port the three error-message helpers; unit
   tests for path accumulation, idempotent prefix rewriting, argless
   exceptions (the Pydantic-style `args`-less case djc handles).
2. **Tracing without bubbling**: attach component paths at `render_impl` and
   `_render_one` boundaries and slot frames in `SlotNode.render`; errors
   still raise immediately. Tests: path through nested components, through a
   fill (slot frame present), through `<c-if>` / `<c-for>` bodies, root-only
   failure.
3. **Template position in errors** (section 6.3): the public
   `format_error_with_context` export from `citry_core.safe_eval`, the
   `set_template_position_error_message` helper, and the `_render_body`
   wrap. Tests: real line numbers in multi-line templates, errors inside
   `<c-if>`/`<c-for>` underlining the right line, innermost-only (one
   snippet, not one per enclosing node), the required-slot error getting the
   `<c-slot>` span, expression + template snippets stacking, fill-content
   errors naming the writer's template, an extension-injected node without
   `position` not crashing.
4. **Error bubbling**: stack unwinding in `render_impl`, `_finalize` folded
   into the settle step (extension hook participates; root raises). Tests:
   extension swallows a descendant error; unhandled error reaches root with
   full path; sibling work after a failed child is discarded (observable via
   `on_component_rendered` call counts).
5. **`on_render` plain form** in `_render_one` + the replacement coercion.
   Tests: None default, `str` / `CitryElement` / `CitryRender` / `Slot`
   replacements, replacement containing deferred children, `transparent`
   interplay, `is_component_root` inheritance.
6. **Generator form**: priming, finalize resume, multiple yields,
   `StopIteration` value, raise-from-generator, generator-returns-before-
   first-yield. Tests mirror DJC's semantics table (return new / raise /
   return None, on both success and error), plus deep-nesting interaction
   with the 600-level test.
7. **`ErrorFallback` built-in** (section 7): the component, the
   `"error-fallback"` reserved name, and the builtins-factory wiring. Tests:
   no-error passthrough, fallback kwarg, fallback slot with `error` data,
   kwarg+slot conflict, nested boundaries (inner wins; failing fallback
   bubbles to the outer), error path of an escaped error names the guarded
   child, deps of the discarded subtree do not leak (once the dependency
   extension exists; until then a placeholder via `extra`).
8. **Docs**: `citry_migration.md` rows flip to Done with divergences noted
   (no before/after hooks, no lambda yields, object results); the
   implementation log entry; `deferred_rendering.md` section 8's open
   decision gets resolved with a pointer here.

`is_generator` ports to `citry/util/misc.py` with step 4.
