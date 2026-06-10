# Design: provide / inject and the `<c-provide>` component

**Status (2026-06-10): built.** All phases are implemented: the
`CitryContext.provides` plumbing, the hand-over at component and slot
boundaries, `Component.provide()`/`inject()`, the `<c-provide>` built-in with
the `transparent` flag, lazy per-instance built-in registration, and the
reserved-name guard. Tests in
[`tests/test_provide.py`](../../packages/py/citry/tests/test_provide.py).

This document specifies how a component passes data to components rendered
deep below it, without threading the data through every kwarg in between:
the provide/inject feature (React's `ContextProvider`, Vue's
`provide()`/`inject()`). It covers how the data travels, the
`Component.provide()` / `Component.inject()` APIs, the `<c-provide>` built-in
component, and how the data reaches slot content.

It extends [`rendering.md`](rendering.md) (the three-phase pipeline and
`CitryContext`), [`deferred_rendering.md`](deferred_rendering.md) (children
render after their parents, which forces the snapshot rule in section 4.2
here), and [`slots.md`](slots.md) (whose section 6 defers provide/inject to
this design). Operating rules are in [`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: the django-components implementation studied for this
design is [`_djc_reference/provide.py`](../../packages/py/citry/_djc_reference/provide.py)
(`ProvideNode`, `set_provided_context_var`, `get_injected_context_var`),
[`_djc_reference/perfutil/provide.py`](../../packages/py/citry/_djc_reference/perfutil/provide.py)
(the cache and reference-counting machinery), and
[`_djc_reference/context.py`](../../packages/py/citry/_djc_reference/context.py)
(the `_DJC_INJECT__` key pass-through). The behavioral contract is pinned by
the captured DJC suite
[`_djc_tests/test_templatetags_provide.py`](../../packages/py/citry/tests/_djc_tests/test_templatetags_provide.py),
including the slot tests from django-components PRs #778 and #786.

---

## 1. Prior art

What already exists, verified on 2026-06-10:

- **The parser deliberately does not reserve `<c-provide>`.**
  [`constants.rs`](../../crates/citry_template_parser/src/constants.rs) notes
  (lines 19, 182, 196) that `c-provide`, `c-js`, and `c-css` do not influence
  the grammar and "can be implemented as regular user-side components". A
  `<c-provide>` tag therefore compiles to an ordinary
  `ComponentNode(name="provide")` today. **No grammar, AST, compiler,
  `LangImpl`, or PyO3 change is needed**; the whole feature is Python in
  `packages/py/citry/`.
- **The README pins the syntax** (line 74): the provider-name attribute is
  **`key`**, and every other attribute is the provided data:
  `<c-provide key="theme" mode="dark">...</c-provide>`.
- **[`citry_migration.md`](citry_migration.md)** plans `<c-provide>` as a
  built-in component in `citry/components/provide.py` (sections "Built-in
  components" and "Step 4").
- **The runtime pieces are in place**: `CitryContext`
  (variables/extra/component), the render queue where a child's inputs are
  read while the parent renders but the child itself renders later
  (`ComponentNode.render` -> `DeferredComponent` -> `_render_one`), the slot
  subsystem (`Slot`, `SlotContext`, `SlotNode`, fill collection), and
  `Component.parent`/`root` links. Nothing provide-related existed before
  this work;
  [`components/__init__.py`](../../packages/py/citry/citry/components/__init__.py)
  was empty.

---

## 2. The model in one paragraph

A component makes data available with `self.provide("user_data", user=user)`
(or a template wraps content in `<c-provide key="user_data" c-user="user">`),
and anything rendered inside that point can read it with
`self.inject("user_data")`. Content written elsewhere (`CitryElement`) that ends up
rendering inside the provider (as `CitryRender`) can inject too (section 3). The data travels on
`CitryContext.provides`, a small mapping that each render hands to the next:
a component hands it to its children, and a `<c-slot>` hands it into the slot
content it renders. The data never enters the template variables; components
opt in with `inject`. When two providers use the same key, the closer one
wins, and its payload replaces the outer one entirely (no field merging).

## 3. Who can inject the data: follow the rendered page, not the template files

Slot content is written in one place and rendered in another. That splits
"what surrounds this content?" into two possible answers, and provide/inject
has to pick one:

- the place the content is **written**: the parent's template, where the
  `<c-fill>` or component body sits;
- the place the content is **rendered**: the `<c-slot>` site inside the
  receiving component.

For template *variables*, citry picks "written": a fill renders with the
variables of the template that wrote it ([`slots.md`](slots.md) section 2).
For provide/inject, citry picks **rendered**. This example (the shape of the
DJC tests from PRs #778/#786) shows why:

```html
<!-- Provider's template: provides around its slot -->
<c-provide key="theme" mode="dark">
  <c-slot />
</c-provide>

<!-- Page's template: passes content into Provider -->
<c-provider>
  <c-themed-button />
</c-provider>
```

The button is written in Page's template, where no `theme` is provided. But
it ends up rendering inside Provider's `<c-provide>` block, and "the button
asks for the theme it is rendered under" is the entire point of the pattern.
So `inject` must see what is provided around the place the content lands,
not only around the place it was written.

Choosing "rendered" loses nothing from the "written" side. By the time
content reaches a slot, providers have only ever been *added* around it,
never removed: the content was picked up at the component call
(`<c-provider>` above), the receiving component inherits everything provided
around that call, and on the way to its `<c-slot>` it can only provide more.
So rendering slot content with the provides of the slot site keeps everything
that was provided where the content was written, plus whatever the receiving
component added. And when both provide the same key, the rule from section 2
already answers it: the closer provider wins.

One more option that cannot work: walking up `Component.parent`. Those links
follow where content was *written* (a component inside slot content gets the
component that wrote it as its parent, see [`slots.md`](slots.md)), so
Provider above would never be on the button's parent chain.

## 4. How the data travels

### 4.1 `CitryContext.provides`

`CitryContext` gets a `provides` field next to `variables`/`extra`: a mapping
from key to frozen payload. It is treated as read-only. A component that
provides builds a **new** mapping with its additions instead of changing the
one it received, so everyone already holding the old mapping is unaffected,
and handing the mapping around is just sharing a reference (no copies).
Every place that builds a derived context passes it along:
`ForNode.iter_bodies`, `_make_body_slot`, and `_render_one`.

### 4.2 From parent to child component

A child component renders *after* its parent has finished, through the
render queue, when the parent's context is already gone. So, exactly like
kwargs ([`deferred_rendering.md`](deferred_rendering.md) section 4.2), the
provides are read while the parent is still rendering: `ComponentNode.render`
stores the current `context.provides` on the `DeferredComponent` (a shared
reference, nothing is copied). When the queue renders the child, the child
instance keeps that mapping (this is what `inject` reads), and the child's
own context starts from it plus whatever the child itself provides in
`template_data`. A root render (`CitryElement.render()`) starts with nothing
provided.

### 4.3 From a `<c-slot>` into the slot content

When `<c-slot>` renders a fill, it passes its current provides into the
call: `slot(data, fallback=..., provides=...)`. `Slot.__call__` exposes them
on `SlotContext.provides` (`None` when the Slot is called directly, outside
any render, e.g. `str(slot)`). A template fill's body then renders with the
slot site's provides laid over the ones captured when the fill was collected;
per section 3 the slot site's entries win on a clash. Called with no slot
site, the body just keeps the captured ones. The slot's fallback body needs
no special handling: it renders against the context current at the slot
site, which already carries the right provides.

### 4.4 Elements rendered in the middle of a render

A `CitryElement` that gets rendered *during* another render inherits the
provides active at that point: `_render_value` passes them to `render_impl`.
This covers `{{ element }}` expressions (via `ExprNode`) and Python-supplied
slot content (a `Slot` wrapping an element, or a slot function returning
one), so `Provide(key="x", ..., slots={"default": Injectee()})` works. Only a
plain user call to `.render()` starts with nothing provided.

## 5. The Python API

### 5.1 `Component.provide(key, /, **data)`

Makes `data` available to this component's descendants. Call it from
`template_data` (or any hook that runs before the render context is built in
`_render_one`). `key` must be a non-empty string identifier (error
otherwise, matching DJC). `key` is positional-only, so a data field literally
named `key` can be provided. The data is frozen right away into a
`NamedTuple` named `Provided`: it cannot be changed afterwards, its fields
are read as attributes (`inject("user_data").user`), and every provided
field is always present. This is DJC's `DepInject` contract under a citry
name.

### 5.2 `Component.inject(key, default=MISSING)`

Returns the payload from the nearest provider above this component in the
rendered page, the given `default` when the key was never provided, or
raises `KeyError` (with the DJC-style explanation plus a difflib "did you
mean" hint over the available keys). Uses a `MISSING` sentinel rather than
DJC's `default=None` convention, so `inject(key, None)` can genuinely
default to `None` (a deliberate, strictly-wider divergence). `inject` sees
only what was provided *above* the component, never the component's own
`provide()` calls, and keeps working after the render finishes for as long
as the component instance is kept (the data sits on a plain attribute).

### 5.3 Scoping rules (the DJC contract)

- Provided data is **not** added to template variables; components opt in
  via `inject`. (`test_provide_does_not_expose_kwargs_to_context`)
- An inner provide under the same key **replaces the outer payload
  entirely**; fields of the outer payload do not merge in.
  (`test_provide_nested_in_provide_same_key`)
- Different keys are independent and compose.
- Siblings after the provider's closing tag do not see the data.
  (`test_provide_does_not_leak`)
- Providing with no data fields yields an empty payload, which is still
  injectable. (`test_provide_empty`)

## 6. The `<c-provide>` built-in component

A regular component in
[`components/provide.py`](../../packages/py/citry/citry/components/provide.py),
essentially:

```python
class Provide(Component):
    transparent = True
    template = "<c-slot />"

    def template_data(self, kwargs, slots=None):
        data = dict(kwargs)
        key = data.pop("key", None)   # missing/invalid key raises
        self.provide(key, **data)
        return {}
```

Everything else comes from existing machinery: static `key="theme"`, dynamic
`c-key="expr"`, `c-bind` spread (with `key` inside the mapping), data
attributes read against the live parent scope, self-closing
`<c-provide ... />` rendering empty, nesting, and per-iteration provides
inside `<c-for>`. The component declares no `Kwargs`/`Slots` classes, so the
parse-time tag rules correctly allow arbitrary data attributes and the
default fill. Its body reaches descendants through the slot hand-over
(section 4.3): the body is the default fill, rendered at the `<c-slot />`
site inside the component's own context, which carries the provided data.

### 6.1 Transparent components (no `data-cid` frame)

`<c-provide>` only wraps content: it owns no markup, no JS, no CSS. A new
class flag, `Component.transparent = False` by default, makes a component's
output count as part of the surrounding component for serialization: its
render is produced with `is_component_root=False`, so the serializer
([`serialize.py`](../../packages/py/citry/citry/serialize.py)) neither treats
it as a child component frame nor stamps a `data-cid-<id>` marker on its
content (the root-marker site also checks `is_component_root`, so a
transparent component serialized directly as the root is unmarked too). The
instance still gets a render id, hooks still fire, and dependency merging is
unchanged.

### 6.2 Per-instance registration and reserved names

A `Component` subclass binds to one `Citry` instance when the class is
defined, but the built-in must exist in every instance. Registering it
eagerly inside `Citry.__init__` cannot work for the default instance: that
instance is constructed while `citry/citry.py` is still importing, before
`component.py` can be imported at all. So built-ins are created **lazily**,
and the machinery lives on `ComponentRegistry`: on the registry's first
component lookup (`get`/`has`/`all`) it calls a factory the owning `Citry`
instance handed it at construction (`Citry._create_builtin_components`,
whose function-local import is justified by this concrete cycle), which
creates the subclasses bound to that instance. `clear()` resets the flag so
a cleared registry re-creates them.

The names `provide`, `js`, and `css` are **reserved**
(`BUILTIN_COMPONENT_NAMES` in `component_registry.py`):
`ComponentRegistry.register` rejects a user registration that would claim
one of them (the README promises all three as built-in tags), raising
`AlreadyRegistered` with a message naming the built-in. Without the guard, a
user class registered before the first lookup would silently take the
built-in's place.

## 7. What does NOT port from django-components

Each piece compensates for DJC machinery citry does not have:

- The entire [`perfutil/provide.py`](../../packages/py/citry/_djc_reference/perfutil/provide.py):
  `provide_cache`, `provide_references`, `component_provides`,
  `active_provides`, `managed_provide_cache`, the GC finalizers and all
  reference counting. DJC stores payloads in module-level globals (so its
  flat `Context` stays inspectable) and then has to track by hand when each
  entry can be deleted; citry keeps plain references on contexts and
  instances and lets Python's garbage collection do the work. The DJC tests'
  `_assert_clear_cache` assertions have no citry analog because there is no
  cache to leak.
- The `_DJC_INJECT__` context-key indirection and
  `make_isolated_context_copy`'s provide pass-through (citry has no context
  modes; the slot hand-over in 4.3 is the principled replacement).
- `ProvideNode`/`BaseNode` tag plumbing (the component IS the tag).
- The `var1:key=...` aggregate-dict kwarg syntax (a DJC expression-language
  feature; citry has `c-bind` and real dict expressions).
- `TemplateSyntaxError` types; citry raises its established
  `RuntimeError`/`KeyError`/`ValueError` styles.

Bonus: the three DJC tests skipped upstream over global-state cleanup
(provide inside forloops, django-components #1413) work in citry and are
ported as active tests.

## 8. Alternatives considered

- **Pass provides down the `Component.parent` chain.** Rejected: those links
  follow where content was written, so the provider in the section 3 example
  is never on the injecting component's chain.
- **Give slot content only the provides captured where it was written (no
  hand-over at the slot).** Rejected: breaks the section 3 example, which is
  the feature's main use, and the `<c-provide>` component could then never
  reach its own body (the body is slot content).
- **Store provides in `CitryContext.extra`.** Rejected: `extra` flows *up*
  (a child's entries are merged into its parent when the child finishes);
  provides flow only *down* and must never travel upward. One bag carrying
  both directions invites exactly the kind of leak the `extra` merge rules
  exist to prevent.
- **`<c-provide>` as a parser built-in / runtime node.** Rejected: the parser
  decision (prior art) is that it does not influence the grammar, and a node
  would need its own scope machinery that the component boundary already
  provides. The component approach also gives the Python-side
  `Component.provide()` API for free.
- **A plain mutable dict payload instead of a NamedTuple.** Rejected: DJC
  chose the NamedTuple so the injected object cannot be changed and always
  has all provided fields; both properties are part of the ported test
  contract (attribute access, `payload.field`).
- **Eager built-in registration in `Citry.__init__`.** Rejected for the
  import cycle described in 6.2.

What would falsify the section 3 choice: a real need for slot content that
must NOT see what is provided around the slot it renders in. Both DJC's
tests and the React/Vue context model treat that visibility as the feature
itself, so this is considered settled.

## 9. Phasing and test plan

1. **Core plumbing**: `CitryContext.provides` plus passing it through every
   derived-context construction site; `DeferredComponent.provides`; the
   `ComponentNode.render` snapshot; `_create_instance`/`__init__`;
   `citry/provide.py` (the `Provided` payload builder, the `MISSING`
   sentinel, key validation); `Component.provide()`/`inject()`.
2. **Slot hand-over**: the `Slot.__call__` provides argument,
   `SlotContext.provides`, the `_make_body_slot` overlay, `SlotNode`
   pass-through, and the `_render_value`/`render_impl` threading for
   elements rendered mid-render.
3. **The built-in**: `components/provide.py`, the `transparent` flag, lazy
   per-instance registration, and the reserved-name guard.
4. **Docs**: this document, the [`slots.md`](slots.md) section 6/12
   cross-references, README examples verified.

Tests (in `tests/test_provide.py`), ported from the DJC suite plus
citry-specific cases: basic provide+inject through the template and through
Python attribute access; payload immutability and full-field presence;
self-closing provide; scoping (sibling after close, no variable leak,
nested same-key replacement, nested different keys); dynamic `c-key`,
`c-bind` spread; missing/empty/non-identifier key errors; `inject` default
(including explicit `None`), missing-key `KeyError` with the did-you-mean
hint, inject-after-render with a kept instance; provide inside `<c-for>`
with per-iteration values; the slot trio (slot-in-provide, inject-in-fill,
inject-in-slot-in-fill); provides reaching Python-channel slot content and
`{{ element }}` expressions; deep nesting through the render queue;
transparent serialization (no `data-cid` for the provide, correct marker
stacking through it, transparent-as-root); the reserved-name guard; and the
README example verbatim.
