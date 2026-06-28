# Design: template globals

**Status (2026-06-28): built.** Both layers are implemented: instance-wide
globals (`Citry(template_globals=...)` plus the live `citry.template_globals`
dict) and the per-render override (`element.render(template_globals=...)`).
Tests in
[`tests/test_template_globals.py`](../../packages/py/citry/tests/test_template_globals.py).

A template global is a variable that every component's template can read
without the component returning it from its own `template_data()`. You set
globals once (a site name, the current user, a feature flag) and reference them
in any template as `{{ site_name }}`, instead of re-exposing the same value from
every component.

This document covers what globals are, the two layers and their precedence, the
Python API, and how each layer reaches every component at render time. It builds
on [`rendering.md`](rendering.md) (the three-phase pipeline and `CitryContext`)
and [`deferred_rendering.md`](deferred_rendering.md) (how children render).

## 1. Prior art

- **django-components had `context_processors_data`** and citry dropped it (see
  the `util/context.py` row in
  [`citry_migration.md`](citry_migration.md)). It auto-injected Django
  context-processor output (`request`, `user`, ...) into every component
  template, but only when a request was present, which made it empty in tests
  and other non-request renders. Template globals are the citry replacement,
  bound to the engine instead of a request.
- **`provide` / `inject`** ([`provide.md`](provide.md)) is a different feature:
  it passes data *down* to descendants who opt in by calling `inject()`, and the
  data deliberately does **not** enter template variables. Globals do the
  opposite: they land directly in every component's template variables, no
  opt-in call.
- **The `on_component_data` extension hook** ([`extensions.md`](extensions.md))
  can mutate a component's template data on every render, so before this feature
  the only way to inject a shared variable was to write and register an
  extension that re-set the key on every component. Template globals make that
  unnecessary for the common case.
- **The settings spec-to-live pattern.** `Citry.cache` and `Citry.id_generator`
  are built once in `__init__` from an immutable settings spec into a live
  attribute. Instance globals follow the same shape: a frozen settings seed, a
  live mutable copy on the instance.

## 2. The model in one paragraph

citry's template variables do not cross a component boundary: each component
gets a fresh set from its own `template_data()`
([`citry_context.py`](../../packages/py/citry/citry/citry_context.py)). That
isolation is deliberate (it is the Vue/React model), and it is exactly why a
shared value otherwise has to be returned from every `template_data()`. Template
globals add a controlled, instance-wide channel on top of that isolation: at the
one point where a component's template variables are assembled, the globals are
merged in, for **every** component. Nothing about the boundary changes; the
globals are simply re-applied at each component.

## 3. The two layers and precedence

There are two sources of globals:

1. **Instance globals** - `citry.template_globals`, shared by every render on
   that engine. Set them at startup for values that do not change per render.
2. **Per-render globals** - the `template_globals=` argument to one `.render()`
   call, for values that belong to a single render (the current user, a request
   id). They never touch the instance.

At each component, the effective template variables are the merge, lowest
precedence first:

```
citry.template_globals  <  render(template_globals=...)  <  component's own template_data
```

A component's own `template_data` always wins, so globals act as defaults and a
component can override one locally. The merge is a plain dict union built fresh
per component:

```python
# component_render.py, _render_one
tpl_data = {**instance_globals, **(render_globals or {}), **tpl_data}
```

## 4. The Python API

```python
from citry import Citry, Component

# Instance globals at construction:
app = Citry(template_globals={"site_name": "Acme"})

# ...or change them on the live instance (a plain dict). The default `citry`
# instance is created at import, before your code runs, so this is how you
# configure it after the fact:
app.template_globals["year"] = 2026
app.template_globals.update({"theme": "dark"})
del app.template_globals["year"]

class Footer(Component):
    citry = app
    template = """
    <footer>{{ site_name }} {{ year }}</footer>
    """

# Per-render globals, layered on top of the instance globals for this render:
Footer().render(template_globals={"year": 2027})
```

`str(Footer())` and `str(component_element)` run render-then-serialize with
defaults and so take no per-render globals; pass them through an explicit
`.render(template_globals=...)` when you need them.

## 5. How each layer reaches every component

Both layers are applied at one site: `_render_one` in
[`component_render.py`](../../packages/py/citry/citry/component_render.py),
right after a component's own `template_data()` is validated and just before its
`CitryContext` is built. Because template variables do not cross a component
boundary, this site runs once per component, which is exactly where the globals
have to be re-applied.

### 5.1 Instance globals: a frozen seed and a live copy

`CitrySettings.template_globals` holds the construction-time seed and stays
immutable with the rest of the frozen settings. `Citry.__init__` copies it into
a separate live dict, `self.template_globals`:

```python
self.template_globals: dict[str, Any] = dict(self.settings.template_globals)
```

The copy decouples the two: mutating the live dict never changes the seed (or
the mapping the caller passed in), and the default instance can be reconfigured
after import. At the merge site each component reads its **own** engine's
globals (`component.citry.template_globals`), so a tree that mixes engines gives
each component the right set.

### 5.2 Per-render globals: a context variable as transport

A per-render override is the same for the whole render and has to reach every
component in it, including nested children, embedded `{{ element }}` values, and
slot content. Threading it as an argument would mean passing it through every
render function, node, and slot. Instead it rides a module-level context
variable (`contextvars.ContextVar`):

- `CitryElement.render(template_globals=...)` hands the dict to `render_impl`.
- `render_impl` sets the context variable for the duration of the render and
  resets it on the way out (in a `finally`, so an error during render still
  clears it). A nested `render_impl` call with no override leaves the outer
  render's value in place, so embedded elements and slot content inherit it
  automatically.
- `_render_one` reads the context variable at the merge site.

The context variable is **transport only**. It does not change what happens to
the value: the override is merged into each component's template variables,
identically to instance globals, one precedence layer higher. A context variable
is the right carrier here because the value is genuinely render-wide and
constant, and because each thread or async task keeps its own value, so
concurrent renders never see each other's per-render globals. (This is unlike
`provide`/`inject` data, which is tree-scoped and therefore captured per child
and threaded explicitly.)

### 5.3 Nested renders

You may start a render inside another render, for example calling
`other.render(...)` from a component's `template_data()` and embedding the
result. This nests correctly, because the context variable is set and reset with
a token (a save/restore stack):

- **Inner passes its own `template_globals`.** The inner override applies only
  to the inner render; when it returns, the outer render's value is restored, so
  the rest of the outer render is unaffected. The restore happens in a `finally`,
  so it holds even if the inner render raises. The inner globals never leak into
  the outer.
- **Inner passes nothing.** The inner render inherits the enclosing render's
  per-render globals, the same way an embedded `{{ element }}` does (the value is
  ambient for the dynamic extent of the render). There is no cross-render leak:
  each top-level render resets the variable when it returns, and a concurrent
  render on another thread or task has its own value.
- **Inner passes `{}`.** An empty dict shadows the inherited per-render globals,
  so the inner render sees only its engine's instance globals. This is the way to
  start a "clean" nested render that ignores the enclosing render's override.

## 6. Interactions and gotchas

- **Typed `TemplateData`.** Globals are merged **after** a component's own
  `template_data()` is validated against its declared `TemplateData` schema, so
  a global key does not have to appear in that schema and never trips its
  unexpected-field check.
- **The "computed once" cache.** Globals are plain values, not wrapped in
  `Const()`, so a template part that reads a global is recomputed each render
  rather than cached. Changing a global between renders shows up in the next
  render. Wrapping a global in `Const()` would promise it never changes; do not,
  if you intend to mutate it.
- **Referencing a render-only global on a render that omits it.** A template
  that reads `{{ user }}` needs `user` to be defined on every render, the same
  as any other variable; citry raises on an undefined variable rather than
  rendering blank. If a template references a global unconditionally, either
  pass it on every relevant render or give the instance a default value for it.
- **Mutating instance globals during concurrent renders.** The instance dict is
  shared. Set it at startup; for values that vary per render or per request, use
  the per-render override, which is isolated to its render.
- **Scope.** Template globals feed the template scope (`template_data`) only,
  not `js_data` or `css_data`. The name says so, and it leaves room for
  `js_globals` / `css_globals` later if a need appears.

## 7. Alternatives considered

- **A `TemplateGlobals` wrapper class instead of a plain dict.** Rejected:
  single dict operations are atomic under the GIL, and per-render values belong
  on the render-time override rather than on a mutated shared instance, so a
  wrapper guarding mutation earned nothing over a dict, whose `set` / `update` /
  `del` / `clear` are already the operations the feature needs.
- **Threading the per-render override explicitly** through the render
  functions, `CitryContext`, the nodes, and the slot call sites. Rejected: it
  touches about ten call sites across the hot render path (every place a node or
  slot spawns a nested render), and it is easy to silently miss one, leaving a
  component that does not see the override. A render-wide value is what a context
  variable models cleanly.
- **A settings-only field with no live store.** Rejected: the settings are
  frozen and the default instance is built at import, so there would be no way
  to configure the default instance afterward, which is the headline use case.

## 8. Test plan

[`tests/test_template_globals.py`](../../packages/py/citry/tests/test_template_globals.py)
covers: a global visible without `template_data`; reaching nested children;
per-instance isolation; configuring an instance (and the default instance) after
construction; dict mutation; the defensive copy of the seed; component-wins
precedence; the schema bypass; a global changed between renders; and, for the
per-render override, visibility, combining with and overriding instance globals,
losing to component data, reaching nested children / embedded elements / slot
content, not leaking to a later render, and not mutating the instance.
