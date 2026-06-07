# Design: rendering flow and the `CitryRender` object

**Status (2026-06-06): design agreed; skeleton not yet built.** This document
captures the rendering-phase model that came out of an exploration session: the
three-phase pipeline, the `CitryRender` output struct, the `CitryContext`
render-scoped state, and the JS/CSS dependency flow that drives the whole shape.
The current code skeleton still returns a plain `str` from `render_impl`; this
doc is the target to build toward.

For the broader migration context see
[`citry_migration.md`](citry_migration.md). For the const-folding feature that
sits on top of this flow see [`constness.md`](constness.md). For operating rules
see [`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: django-components
[#1650](https://github.com/django-components/django-components/issues/1650)
(cache the render object, not the string),
[#1144](https://github.com/django-components/django-components/issues/1144)
(media becomes an extension),
[#1340](https://github.com/django-components/django-components/issues/1340)
(fragment tag),
[#1337](https://github.com/django-components/django-components/issues/1337)
(lazy/streaming),
[#1326](https://github.com/django-components/django-components/issues/1326)
(avoid double-parsing). The JS/CSS placement logic to study is DJC's
[`dependencies.py`](../../packages/py/citry/_djc_reference/dependencies.py).

---

## 1. The three-phase pipeline

Rendering is split into three structs across three phases, each with its own
job:

```
Component(**kwargs)         -> CitryElement     compose: "what to render" (upstream)
CitryElement.render()       -> CitryRender      render: rendered parts + collected metadata
CitryRender.serialize()     -> str (HTML)       serialize: join + place deps per strategy
```

- **`CitryElement`** ([`citry_element.py`](../../packages/py/citry/citry/citry_element.py))
  is purely a composition descriptor: the component class plus its kwargs/slots.
  It is the React `ReactElement` analog. It does not render anything.
- **`CitryRender`** is the rendering-phase output. It is a distinct struct from
  `CitryElement` (this separation is the central decision of this doc, see
  section 3). It carries the rendered HTML parts and the metadata collected
  during the render (most importantly the JS/CSS dependencies).
- **Serialization** turns a `CitryRender` into a final HTML string: it joins the
  parts and places the collected dependencies into their destinations
  (`<head>`/`<body>`).

`CitryRender` is what #1650 calls the "render object." We use `CitryRender` for
naming consistency with `CitryElement` and `CitryContext` (section 9).

### 1.1 Convenience coercions

The explicit chain is `Component(...).render().serialize()`. For good UX, the
intermediate steps fall through with sensible defaults so a caller can stop at
any phase:

- `str(citry_render)` runs `citry_render.serialize()` with defaults.
- `str(citry_element)` runs `citry_element.render().serialize()` with defaults,
  so `str(Component(title="x"))` yields HTML directly.
- `bytes(...)` serializes and encodes (details in open questions).

`serialize()` (alias candidate: `.html()`) is the configurable entry point:
strategy and document-vs-fragment mode are passed here, at the very last step,
not on `render()` (section 7).

---

## 2. Why the render output is a struct, not a string

The motivating problem is JS/CSS dependency collection. A component may declare
assets (`Component.js`/`css`, or `Component.Media.js`/`css`). The engine must
collect those assets from every component that actually rendered and then place
them in specific locations (CSS in `<head>`, etc.). Two scenarios show why a
string output cannot carry this:

- **One large template rendered at once.** In DJC, a rendered component might be
  embedded into a Django template, which is effectively just a string. To carry
  "which components rendered" across that string boundary, DJC embedded marker
  comments into the HTML and post-processed them. That marker hack exists only
  because the medium was a string. Citry does not have that constraint: the
  render output can hold the rendered HTML *and* a metadata bag (deps, plus
  whatever extensions attach) as first-class fields.

- **Pre-rendering a subtree and inserting it into a larger whole.** Again DJC
  used the string as the medium for "what assets come with this fragment." In
  citry, `CitryElement.render()` returns a live `CitryRender`. You can hand that
  object to another component (as a kwarg, inside `{{ ... }}`, or in an HTML
  attribute). When the consuming tree renders it, the code detects "this is a
  `CitryRender`", extracts its collected deps, merges them into the consuming
  tree's collection, and inlines its HTML. The user only collapses to a string
  when they actually want final HTML, and that coercion is what triggers the
  join plus head/body placement.

So the struct is what lets a rendered subtree stay composable. The string is the
terminal form, produced once, at the edge.

---

## 3. `CitryRender`: the render-phase output

`CitryRender` holds:

- **The rendered output** as a parts list. Parts are heterogeneous: a part is
  either a `str` (static or already-serialized text) or a nested `CitryRender`
  (an embedded subtree not yet joined). Deferring the join keeps embedding cheap
  and keeps deps recoverable until the final serialize. This mirrors the
  heterogeneous body list in [`constness.md`](constness.md) section 5
  (`str | child | dynamic node`).
- **The `CitryContext` used during the render** (section 4). For the first
  iteration `CitryRender` keeps the whole context object rather than pre-selected
  fields; the metadata (deps) lives there. We can refine to specific fields once
  we know exactly what serialization needs.

### 3.1 Detecting and merging an embedded `CitryRender`

The detection happens at the leaf nodes that can surface an arbitrary value:

- `ExprNode.render(ctx)` evaluates a `{{ ... }}` expression. If the result is a
  `CitryRender`, it merges that render's collected deps into `ctx` and inlines
  its HTML parts.
- The dynamic attribute nodes (`ExprHtmlAttr`, `TemplateHtmlAttr`) do the same
  for values that land in attributes.
- `ComponentNode.render(ctx)` renders a child component inline, which produces a
  child `CitryRender`, then merges its deps into `ctx`.

**Discovery: inline child rendering and external pre-rendered embedding are the
same operation.** Whether a child component is rendered inline during the parent
render, or was rendered earlier and passed in via `{{ }}`/kwargs/attr, the
consuming step is identical: take a `CitryRender`, merge its deps upward, inline
its HTML. One code path covers both.

---

## 4. `CitryContext`: render-scoped state and the two scopes

A custom `CitryContext` struct is passed down through `_render_body` as the body
tree is walked. It is named `CitryContext` to keep it clearly distinct from
Django's `Context`.

There are **two different scopes flowing through a render, and they must not be
conflated**:

1. **The variable context (per component).** The template variables produced by
   `template_data(kwargs, slots)` for the component currently rendering. This
   does not flow across a component boundary: a child component gets fresh
   variables from its own `template_data`, computed from its own props/slots, not
   inherited from the parent. (This is the existing impl-note rule "DO NOT PASS
   CONTEXT BETWEEN NODES. ONLY PROPS AND SLOTS" in
   [`citry_migration.md`](citry_migration.md).)
2. **The tree-wide collection (extensions).** An `extra` container (a dict, or
   typed per-extension containers) where extensions stash data during the
   render. The dependency extension stores collected JS/CSS here. This concern
   spans the whole render tree: deps bubble all the way to the render root.

`CitryContext` carries both: the current component's variables and the `extra`
bag. The trick is that the variable part is per-component while the `extra` part
must merge across component boundaries.

### 4.1 `ComponentNode` is the context boundary

Each component render creates its own `CitryContext`. The outer context is
created when `RootComp(...).render()` is called. As the body is walked and a
`<c-my-comp ...>` is reached, it becomes a `CitryElement` whose `.render()` is
called, which mints the inner component's own `CitryContext`. The tree-wide data
(`extra`/deps) is then merged from the inner context into the outer when the
inner `CitryRender` is consumed (the same merge as section 3.1).

**Why per-component contexts plus merge, rather than one shared context reused
down the tree:** the choice depends on what `CitryContext` needs to hold. If it
held only tree-wide shared data, a single shared object passed down would be
enough. But we anticipate per-component data (for example a `self` template
variable pointing at the current component instance, and the per-component
variable context above), and per-component data must not leak across boundaries.
So the safer default is a context per component with an explicit merge of the
tree-wide parts. If it turns out only tree-wide data is ever stored, this can
collapse to a shared context later.

---

## 5. Serialization

`CitryRender.serialize(...)` joins the parts (recursively, since parts may be
nested `CitryRender`s) and then places the collected dependencies into their
destinations. Configuration lives here, at the last step:

### 5.1 Strategy and mode (document vs fragment)

Citry's serialization accepts strategy options similar to DJC's, scoped to this
final step (not to `render()`):

- **Document mode** places collected deps into `<head>`/`<body>`.
- **Fragment mode** (#1340, #897): no document shell exists (for example an
  HTMX-style partial swap), so deps cannot go in `<head>`. They are delivered
  another way (for example inline at the component location, or via injected JS).
  The first version may implement document mode only, with fragment mode added
  later. The point is that the mode is a serialize-time argument.

### 5.2 Injection strategy: a deferred fork

Two ways to place deps:

- **(i) String surgery after join.** Build the HTML string, then find `<head>`
  and splice (DJC's [`dependencies.py`](../../packages/py/citry/_djc_reference/dependencies.py)
  approach). Proven and simple, but it re-introduces string-as-medium at the
  very end.
- **(ii) Structured placement before join.** The `CitryRender` tree knows where
  the head/body are, so deps are placed into the structure and only then joined.
  This is the better fit for a struct-based system, but it has hard cases (a
  fragment with no `<head>`, or a `<head>` owned by an outer non-citry host).

Direction: (ii) is preferred, but the decision is deferred until we are actually
writing the stringification and can see which is cleaner in code.

### 5.3 One-shot serialization (a contract to document)

Once `serialize()` has placed deps into `<head>`, the resulting string can no
longer be merged into another tree (its deps are baked in, the same failure DJC
had with strings). The contract: keep a value as a `CitryRender` for as long as
you compose; coerce to a string only at the final boundary.

---

## 6. The dependency (JS/CSS) flow, end to end

This is the concrete driving use case that shaped `CitryRender`:

1. A component declares assets (`Component.js`/`css` or `Component.Media`).
2. During that component's render, the dependency extension stashes its assets
   into `CitryContext.extra` (the tree-wide collection).
3. As children's `CitryRender`s are consumed (section 3.1), their collected deps
   merge upward into the consuming context.
4. At `serialize()`, the fully-collected deps are placed into `<head>`/`<body>`
   per the chosen mode (section 5).

Because deps travel as data on the struct (not as markers in HTML), no string
post-processing is needed to know what rendered. The media subsystem itself
becomes an extension (#1144) that hooks the lifecycle to do steps 2 and 4; the
extension system is a prerequisite for building it (see the ordering in
[`citry_migration.md`](citry_migration.md)).

---

## 7. Interactions and non-goals

- **Const-folding stays consistent** ([`constness.md`](constness.md) section 6).
  A folded component boundary cannot collapse to frozen text: each render it must
  still mint a fresh render id and re-merge its deps into the parent. So a folded
  placeholder is a recipe that produces a child `CitryRender` each render, not a
  baked string. The two designs agree.
- **Expression caching (#1473) is a separate, value-keyed layer.** It must not be
  entangled with `CitryRender` or `CitryContext`; see
  [`constness.md`](constness.md) section 10.
- **Class-level body caching (#1326) is unaffected.** The parsed+compiled
  body-generating function is cached per component class; `CitryRender` is
  per-render. The two caches are orthogonal.
- **#1650 alignment.** `CitryRender` is the render object #1650 says to cache.
  Caching the object (rather than the final string) is what lets each
  consumption re-mint ids and re-merge deps.
- **Streaming (#1337) is held off.** The core conflict: efficient streaming
  cannot move JS/CSS into `<head>` (or any already-streamed location) after the
  fact. If pursued later, streaming would likely be constrained to placing deps
  at the component's own location in the output rather than hoisting them. Not a
  priority now, but `CitryRender`'s parts list (which can later hold lazy parts)
  should not foreclose it.

---

## 8. Naming

- **`CitryRender`** for the render-phase output struct. Alternatives considered:
  `RenderObject` (the term #1650 uses; kept as the conceptual alias), `VNode`
  (rejected: implies virtual-DOM diffing/reconciliation, which citry does not
  do), `CNode` (rejected: collides with the runtime `ComponentNode` and the
  `*Node` family the compiler emits).
- **`CitryContext`** for the render-scoped state, to distinguish it from Django's
  `Context`.
- The `Citry`-prefixed family (`CitryElement`, `CitryRender`, `CitryContext`) is
  self-documenting and avoids collisions with React (`ReactElement`), Django
  (`Context`), and the runtime node classes.

---

## 9. Open questions

- Exactly which fields `CitryRender` keeps versus holding the whole
  `CitryContext` (section 3). Start broad, narrow once serialization needs are
  known.
- Whether `CitryContext` stays per-component-plus-merge or collapses to a shared
  context, decided once the full set of stored data is known (section 4.1).
- Injection strategy (i) vs (ii), decided at stringification (section 5.2).
- Fragment-mode dependency delivery (section 5.1).
- `bytes()` serialization details and whether `serialize()` or `.html()` is the
  canonical name.

---

## 10. Suggested phasing

Status as of 2026-06-07: phases 1-3 and the control-flow nodes are built (see
the implementation log in [`citry_migration.md`](citry_migration.md)). Phases
4-5 and slots are not started.

1. **Done.** `CitryRender` + `CitryContext` skeleton: `render()` returns a
   `CitryRender` holding a parts list plus the context; `serialize()` joins the
   parts; `str()`/`bytes()` coercions; `str(CitryElement)` convenience. No deps
   yet.
2. **Done.** Value nodes render against `CitryContext`: `ExprNode` and
   `TemplateNode`, with embedded-`CitryRender`/`CitryElement` detection and the
   merge seam (section 3.1). Note: a dynamic attribute on a *plain HTML element*
   is compiled to an inline `ExprNode` (between literal quote strings), not an
   attribute node; the attribute nodes are component inputs and were done with
   phase 3.
3. **Done.** `ComponentNode` as the context boundary: attribute nodes resolve to
   the child's kwargs, registry lookup via `CitryContext.component`, child render
   through the boundary, deps merge (section 4.1). Component body (default-slot
   text or `<c-fill>`) raises `NotImplementedError` pending the slots phase.
4. **Not started.** Extension hook points, then the dependency extension
   populating `extra`, then serialize-time placement in document mode (section
   6). The merge call site in `_render_body` (`_merge_dependencies`) is the
   marked seam to convert into a hook.
5. **Not started.** Fragment mode and the injection-strategy refinement
   (section 5).

Adjacent work: the **control-flow nodes** (`IfNode`, `ForNode`) are built (they
were self-contained and done independently of phases 4-5). The **slot
subsystem** (`SlotNode`, `FillNode`, default vs named slots) needs its own
design doc before implementation (many edge cases).
