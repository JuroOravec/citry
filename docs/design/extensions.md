# Design: the extension (plugin) system

**Status (2026-06-13): built, except the caching/short-circuit phase.** This
document is the design for citry's extension/hook system, adapted from
django-components and reshaped for citry's architecture (Citry-instance scoping,
the `CitryRender` struct pipeline, no Django). The system (`Extension`,
`Extension.Config`, `ExtensionManager`, `CitrySettings`, `ExtensionCommand`,
the `On*Context` types, the lifecycle/registration/render/template/slot/JS/CSS
hooks, the `emit` mechanism for extension-owned custom hooks,
`on_render_context_merge`/`on_serialize`, and `Extension.urls`) is
implemented; see the impl-log entries in
[`citry_migration.md`](citry_migration.md). The caching/short-circuit phase
(a future cache extension) is the main piece still deferred.

For the broader migration context see [`citry_migration.md`](citry_migration.md).
For the render model the render-hooks plug into see [`rendering.md`](rendering.md).
For operating rules see [`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: django-components
[#829](https://github.com/django-components/django-components/issues/829)
(extensions architecture),
[#1144](https://github.com/django-components/django-components/issues/1144)
(media as an extension),
[#1213](https://github.com/django-components/django-components/issues/1213)
(extensions specify HTML attribute rules),
[#1230](https://github.com/django-components/django-components/issues/1230)
(scoped CSS),
[#1444](https://github.com/django-components/django-components/issues/1444)
(head-tag extension). Prior art:
[`extension.py`](../../packages/py/citry/_djc_reference/extension.py) (1555 lines).

---

## 1. Prior art (what was searched)

In `packages/py/citry/_djc_reference/`:

- **`extension.py`** is the whole system: `ComponentExtension` (base + hook
  methods), `ExtensionManager` (module-global singleton calling each hook on every extension),
  `ExtensionComponentConfig` (the `Component.View` nested-class mechanism),
  16 `On*Context` NamedTuples, plus `ComponentCommand` / `URLRoute` plumbing.
- **Scoping is a module global** (`extensions = ExtensionManager()`,
  `extension.py:1533`), initialized from Django `apps.ready()` via `_init_app`
  (`:1261`). The deferral machinery (`store_events`, `_initialized`, `_events`
  flush, `:1087`, `:1327`) exists **only** to survive Django's app-load order.
  The `_init_app` URL-resolver block (`:1269-1306`) is Django-specific.
- **`on_registry_created` / `on_registry_deleted` are fired by
  `component_registry.py` but implemented by no extension** (grep: only the
  base definition and the firing site exist). Confirms they can be dropped
  (section 6.3).
- **The `<name>_class` escape hatch** (`extension.py:1176`) mirrors the legacy
  `media_class` attribute (`component_media.py:575,640`). It exists for
  parity with that old API; with no such legacy in citry it can be dropped
  (section 5.3).
- **The two-job framing of `on_component_input`** (mutate inputs *and*
  short-circuit the render - that is, skip rendering it and return a substitute,
  such as a cached result) lives in its docstring (`extension.py:717-784`),
  with the memory-leak footgun the conflation causes. The maintainer's proposal
  to split it is **django-components#1141 "[v2] Ideas", item R6** ("Elevate
  component caching to first-class lifecycle hooks, instead of overloading
  `on_component_input`"): `on_component_input` regains a single responsibility
  (inspect/mutate inputs); a dedicated `on_component_cache` takes over
  "compute key / decide whether to render" (explicit short-circuit); and
  `on_component_cache_hit` fires on a short-circuited render so *other*
  extensions can observe it (today they cannot). Leak lineage:
  django-components#1607 (leak found) -> #1648 (fix: bind per-render state to the
  component lifetime) -> #1649 (docs warning). Section 7.1 carries R6 into
  citry's extension-owned-hooks model.

Places in citry where hooks will attach: `ComponentMeta.__new__`/`__del__`
([`component.py:83`](../../packages/py/citry/citry/component.py), `:180`);
`Citry.register`/`unregister` ([`citry.py:82`](../../packages/py/citry/citry/citry.py));
`render_impl` ([`component_render.py:75`](../../packages/py/citry/citry/component_render.py));
`_get_compiled_template`/`_compile_template` (`:185`,`:206`);
the `_merge_dependencies` call (`:277`, already TODO-marked "replace this direct
call with an extension hook"); and `CitryContext.extra`, the tree-wide bag
reserved "for extensions."

---

## 2. Central decision: the manager is scoped to the `Citry` instance

DJC's manager is a module global. Citry's
[#1413](https://github.com/django-components/django-components/issues/1413) rule
is that **all engine state lives on the `Citry` instance**. So each `Citry`
**owns an `ExtensionManager`**; extensions are passed at construction:

```python
app = Citry(extensions=[MyExtension, "my_pkg.ext.OtherExtension"])
app.extensions                 # -> the ExtensionManager (not the raw list)
app.settings.extensions        # -> the immutable spec tuple (see 2.1)
```

Every instance (including the default module-level `citry`) also carries the
**built-in extensions**: a fixed set (`extension.py`'s `_builtin_extensions()`) the manager prepends
to the user's spec, with their names reserved. The first built-in is the
`dependencies` extension (see [`asset_loading.md`](asset_loading.md) section 7);
this mirrors the registry's built-in components. Beyond the built-ins, the
default instance has no extensions; a user who wants more constructs their own
`Citry(extensions=[...])` and assigns components to it
(`class C(Component): citry = app`). Same test-isolation model as the registry.

**This deletes DJC's deferral machinery entirely.** There is no `apps.ready()`
race in citry: a component class is bound to its `Citry` (and thus its
extensions) at definition time in the metaclass, so the extensions are always
present when a hook fires. `store_events`, `_initialized`, `_events`,
`_init_app`, and the replay loop are all dropped.

### 2.1 Where extensions live, and immutability

- **`Citry.extensions` is the `ExtensionManager`** (the thing that calls each
  hook on every extension). It is *not* the list of extensions. (An earlier draft
  conflated the two; corrected.)
- **The raw `extensions=` spec lives in the settings** (section 5.2's
  `CitrySettings`), stored as an **immutable tuple**. The `ExtensionManager`
  builds its instances from that tuple, and also holds the instantiated
  extensions as a tuple (not a mutable list).
- **No post-construction mutation.** Extensions are fixed at construction;
  mutating them afterward is undefined behavior. The tuple storage makes the
  intended-immutability explicit and blocks the obvious accidental `.append`.

---

## 3. Hook contexts: frozen dataclasses, minimal surface, `citry` + `component`

### 3.1 Frozen dataclasses

`@dataclass(frozen=True, slots=True)`, threaded across extensions with
`dataclasses.replace()`. Consistent with citry's metaclass (which already
converts inner `Kwargs`/`Slots` to dataclasses) and flagged per migration
principle #5. `frozen` blocks accidental field reassignment; where a hook is
*meant* to mutate inputs (adding a kwarg), it mutates the contained `dict`,
whose contents are not frozen.

### 3.2 Minimal surface: pass `citry` + `component`, derive the rest

Every context that concerns a specific render carries **`citry`** (the primary
handle extensions reach for: registry, settings, caches) and, when a component
instance exists, **`component`**. Fields trivially derivable from those are
**dropped**:

- `component_class` is `type(component)`; `component_id` is `component.id`. Both
  dropped from the per-instance render hooks. (`component.id`, `component.kwargs`,
  etc. are all on the instance.)
- The registry is `citry.registry`, so it is not passed separately (section 6.3).

Class-lifecycle hooks have no instance, so they carry **`citry`** +
**`component_class`** (full name; section 3.3).

`citry` itself is technically derivable (`component.citry`), but it is passed
explicitly because it is the handle extensions use most; making them write
`ctx.component.citry` everywhere is poor ergonomics. This is the one deliberate
redundancy.

### 3.3 `component_class`, not `component_cls`

Use the full word **`component_class`** on the contexts that carry a class.
(DJC marked `component_class` for deprecation in favor of `component_cls`;
citry keeps the readable full name.)

---

## 4. Naming

- **`Extension`** - the base users subclass. (`CitryExtension` was the
  considered alternative; `Extension`/`ExtensionManager`/`ExtensionCommand`/
  `Extension.Config` reads consistently.)
- **`Extension.Config`** - the per-component nested-config base (DJC:
  `ComponentConfig`). Shortened to `Config`: a user writes `class View:` and the
  manager rebuilds it as a subclass of `Extension.Config`.
- **`ExtensionManager`** - owned by `Citry`.
- **`ExtensionCommand`** - the CLI-command base (DJC: `ComponentCommand`). The
  CLI design that builds on it (the command runner, `Citry.commands`
  aggregation, and the `citry` executable) is
  [`extension_commands.md`](extension_commands.md).

---

## 5. The per-component config (`Extension.Config`)

The `Component.View` / `Component.Cache` mechanism: an extension named `"view"`
(`class_name == "View"`) lets a user define a nested `class View:` on a
component; it is rebuilt as a subclass of the extension's `Config` (with the
owner bound), then instantiated per render and attached as `component.view`.

### 5.1 Component back-reference: keep the weakref + optional component

DJC stores a **weakref** to the component (`_component_ref = ref(component)`)
with a `.component` property - to avoid a component->config->component cycle, and
to support extensions that run **outside** the component lifecycle, where there
is no component (`component=None`).

An earlier draft of this doc proposed dropping both (strong ref, no `None`
case). **That was wrong:** citry will port DJC's extensions, including
**Storybook, which runs out-of-lifecycle** - so `component=None` is a real,
required case. The weakref + optional component **stay**.

The only cleanup is ergonomic: a tidier `__init__` and `.component` that
distinguishes the two `None` reasons with clear errors -

```python
def __init__(self, component: Component | None) -> None:
    self._component_ref = ref(component) if component is not None else None

@property
def component(self) -> Component:
    if self._component_ref is None:
        raise RuntimeError(f"{type(self).__name__} runs outside a component lifecycle (no component)")
    component = self._component_ref()
    if component is None:
        raise RuntimeError("Component has been garbage collected")
    return component
```

### 5.2 Three-level config defaults, on a real settings schema

Per the maintainer's call, citry gets a **real settings schema object now**
(not a plain `**settings` dict). Introduce a frozen `CitrySettings` dataclass as
the first concrete schema; it grows field-by-field as the engine does. Initial
fields relevant here:

```python
@dataclass(frozen=True, slots=True)
class CitrySettings:
    extensions: tuple[type[Extension] | Extension | str, ...] = ()
    extensions_defaults: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # ... more fields added as subsystems land
```

`Citry(extensions=[...], extensions_defaults={...})` validates and freezes these
into `Citry.settings` (the `extensions` spec lives here as a tuple, section 2.1).
This replaces the placeholder `self._settings` dict.

The per-component config then merges all three DJC layers:

1. **Factory defaults** - attributes on the extension's `Config` base.
2. **Global defaults** - `settings.extensions_defaults["view"]`.
3. **Component-level** - the user's nested `class View:` on the component.

Precedence: component-level > global defaults > factory, realized by base order:
`type("View", (user_view, GlobalDefaults, Extension.Config), {"component_class": C})`.

### 5.3 Escape hatch dropped

The `<name>_class` attribute override (DJC `extension.py:1176`) is dropped: it
only existed to mirror the legacy `media_class` API. The supported way to change
the base is the obvious one:

```python
class MyComp(Component):
    class View(SomeOtherBase):   # just subclass directly
        ...
```

---

## 6. Hook firing: where, and the registry rethink

### 6.1 Class lifecycle

`ComponentMeta.__new__` fires `on_component_class_created` then runs the
config-class setup (`_init_component_class`), then registers.
`ComponentMeta.__del__` fires `on_component_class_deleted`. Both reachable
because the class knows its `Citry` at definition time.

### 6.2 Render

`render_impl`: after instance creation, run `_init_component_instance` (attach
`component.<name>` configs), then `on_component_input` (mutate) and the
short-circuit hook (section 7.1); after `template_data`, `on_component_data`;
after the body builds into a `CitryRender`, `on_component_rendered`.

### 6.3 Registry hooks dropped; setup moves to `on_extension_created`

A `Citry` has exactly one registry, created in its `__init__`. DJC's
`on_registry_created` / `on_registry_deleted` are **dropped** (no extension
implements them, section 1). Any per-registry setup an extension needs is done
in **`on_extension_created`**, whose context gains **`citry`**, so the extension
reaches `ctx.citry.registry` directly.

`on_component_registered` / `on_component_unregistered` are **kept** (extensions
do use them) but fire from `Citry.register`/`unregister` (keeping
`ComponentRegistry` framework-agnostic), and their contexts carry **`citry`** +
`name` + `component_class` (no separate `registry`; use `citry.registry`).

---

## 7. Render-hook divergences from DJC

### 7.1 `on_component_input` is mutate-only; short-circuit is deferred

DJC's `on_component_input` does two jobs (mutate inputs *and* short-circuit the
render), and the conflation causes the leak class of #1607/#1648/#1649. R6
proposes splitting them. Citry takes the **uncontroversial half now** and
**defers the rest**:

- **Now (skeleton):** `on_component_input(ctx) -> None` is **mutate-only** -
  inspect/mutate `ctx.kwargs` / `ctx.slots`, single responsibility, always runs.
  No short-circuit return.

- **Deferred:** the short-circuit mechanism (how a render is skipped and a
  substitute supplied) is **not** added in the skeleton. An earlier draft of this
  doc proposed a core `on_component_render` hook plus making
  `on_component_rendered` fire on short-circuit "to dissolve the leak at the
  root." That is **withdrawn as premature.** In DJC the cache-hit branch
  genuinely *cannot* call `on_component_rendered`, because that hook expects
  inputs (`template_data`, etc.) that a cache hit never computes. Whether citry's
  pipeline has the same constraint depends on how the rest of the render skeleton
  shapes up, so the right move is to **build more of the skeleton first, then
  conclude** what short-circuiting and its interaction with `on_component_rendered`
  should be.

When it does land, the likely shape is **not** a core hook but a pair of
**cache-extension-owned custom hooks via `emit()`** (section 9.2):
`on_component_cache` (compute key / decide whether to render) and
`on_component_cache_hit` (observe a cache short-circuit). Keeping them owned by
the cache extension matches citry's "caching is an extension, not core" stance
and avoids baking a short-circuit contract into the engine before we know its
shape.

### 7.2 Short-circuit / post-render return type: `CitryRender | str | None`

Both the short-circuit hook (7.1) and `on_component_rendered` accept
**`CitryRender | str | None`**. A returned `str` is convenience: it is wrapped as
a single-part `CitryRender` (treated as already-serialized HTML). Keeping the
struct form available means deps stay recoverable; the `str` form is the easy
path. (DJC used `str` only, because its render output was a string.)

### 7.3 `on_component_rendered` operates on the `CitryRender`

Receives `render: CitryRender | None` + `error`. Return a `CitryRender`/`str` to
replace output, raise to replace the error, return `None` to keep the original.
Threading semantics preserved from DJC.

### 7.4 `on_template_compiled` fires at the node list, not a Template object

Citry has no Django `Template`. The useful point is **after the body node list is
generated** (so extensions can mutate/replace nodes - e.g. scoped-CSS attribute
injection, #1230). Fire `on_template_compiled(ctx)` with `ctx.nodes` (the
generated body list) at body-build time, before the list is cached (in the
const-body cache, `_const_body`), so the transform is applied once per
cached body, not per render. May mutate in place or return a new list.

`on_template_loaded` still fires once per class with the template **string**
before parse.

### 7.5 JS/CSS data methods

`js_data()` / `css_data()` exist alongside `template_data()` (with typed
`JsData`/`CssData` schemas), and `on_component_data` carries `template_data`
+ `js_data` + `css_data`, plus the render's `CitryContext` (so extensions can
stash tree-wide state in `context.extra`). The dependencies extension
consumes the data as JS/CSS variables ([`dependencies.md`](dependencies.md)
section 5). (DJC's deprecated `context_data` is dropped outright.)

---

## 8. Smarter dispatch: call only extensions that implement a hook

DJC loops every extension for every hook, invoking empty base methods. Citry
builds a **dispatch map** at manager construction: for each hook name, the list
of extensions whose method is actually overridden
(`type(ext).on_x is not Extension.on_x`). Each `manager.on_x(...)` iterates only
that list. Empty-hook extensions cost nothing. This map is also what makes custom
hooks (section 9) tractable, since dispatch is already name-keyed.

---

## 9. An open hook system: custom hooks + the merge step

The most structural change. Two coupled ideas:

### 9.0 Convention: namespace `extra` by owner

`CitryContext.extra` is one bag shared by everything in the render tree, so
its top-level keys are **namespaced by owner** to avoid collisions: an
extension stashes its data under a key named after itself (the dependencies
extension uses `extra["dependencies"]`), and citry-core concepts that more
than one party may contribute to live under `extra["citry"]`
(`citry_context.EXTRA_CITRY_KEY`). The root-marker seam is the first such
core concept; the core wraps it in the internal
`CitryContext._add_root_markers` / `_get_root_markers` rather than exposing
the raw nested key, so the magic strings stay in one place (underscore-
prefixed for now: the built-in dependencies extension is the only writer, so
the contract can firm up before it is offered to third-party extensions).
The rule keeps two extensions (or an extension and the core) from clobbering
each other's `extra` entries.

### 9.1 The dependency-merge step becomes a hook

`_merge_dependencies(parent_ctx, child_ctx)`, the seam fired when a child
`CitryRender` is consumed, is a core hook: **`on_render_context_merge(ctx)`**,
`ctx` carrying the parent and child `CitryContext`s, so each extension merges
*its own* slice of `extra` with its own policy (deps want ordered de-dup, not
last-writer-wins). The core no longer owns the merge semantics.

### 9.2 Extensions can define their own hooks

For a clean layering, **`on_dependencies` is not a core hook** - it belongs to
the `dependencies` extension. So the core lets an extension **declare and
fire its own hooks** that other extensions implement. Mechanism (registration is
duck-typed, leaning on section 8's name-keyed dispatch):

- `manager.emit(name, ctx, result=..., field=...)` dispatches `name` to every
  extension that defines a method `name`, combining their returns per `result`.
- Built-in policies: `none` (side-effecting, return `None`), `first` (return
  the first non-`None` return; short-circuit), `map` (thread `ctx.<field>`,
  each non-`None` return replacing it via `dataclasses.replace`, returning the
  final value).
- The core hooks are just well-known `emit` names with fixed policies; a custom
  hook (like `on_dependencies`) is fired by its owning extension via `emit`, and
  any extension implements it by defining a method of that name.

So the dependency extension owns `on_dependencies` (and fires it at serialize
time), uses `on_render_context_merge` to bubble deps up the tree, and stashes into
`CitryContext.extra` - all without the core knowing about JS/CSS.

The **cache short-circuit** (section 7.1) is the second concrete consumer of
this mechanism: a future `CacheExtension` owns `on_component_cache` and
`on_component_cache_hit` as `emit()` hooks, rather than the engine carrying a
core short-circuit hook. This keeps the leak-prone short-circuit logic out of the
core and lets other extensions observe a cache hit explicitly.

The name-keyed dispatch + `emit` mechanism is built and the core hooks route
through it; the dependencies extension exercises custom-hook ownership
(`on_dependencies`). The cache extension's `emit`-owned hooks remain future
work (section 7.1).

---

## 10. DJC hook + surface tracking table

Status: **Skeleton** (build now) · **Deferred** (defined/planned, no hook wired
yet) · **Dropped** · **Renamed/Reshaped**.

| DJC hook | citry status | Divergence |
|---|---|---|
| `on_extension_created` | Skeleton | ctx gains `citry` (absorbs registry setup, section 6.3) |
| `on_component_class_created` | Skeleton | ctx: `citry, component_class` |
| `on_component_class_deleted` | Skeleton | ctx: `citry, component_class` |
| `on_registry_created` | **Dropped** | one registry per Citry; use `on_extension_created` + `citry.registry` |
| `on_registry_deleted` | **Dropped** | same |
| `on_component_registered` | Skeleton | ctx: `citry, name, component_class` (no `registry`) |
| `on_component_unregistered` | Skeleton | ctx: `citry, name, component_class` |
| `on_component_input` | Skeleton (reshaped) | mutate-only, `-> None` (django-components#1141 R6, 7.1) |
| *(short-circuit)* | **Deferred** | not in skeleton; likely cache-extension-owned `on_component_cache` / `on_component_cache_hit` via `emit()` (7.1, 9.2) |
| `on_component_data` | Wired | ctx: `citry, component, context, template_data, js_data, css_data` (7.5) |
| `on_component_rendered` | Skeleton | operates on `CitryRender`; `-> CitryRender \| str \| None`; short-circuit interaction deferred (7.1) |
| `on_template_loaded` | Skeleton | ctx: `citry, component_class, content` |
| `on_template_compiled` | Skeleton (reshaped) | fires at the node list, not a Template (7.4) |
| `on_css_loaded` | Skeleton | wired by the asset-loading subsystem ([`asset_loading.md`](asset_loading.md) section 6); ctx: `citry, component_class, content` |
| `on_js_loaded` | Skeleton | same as `on_css_loaded` |
| `on_slot_rendered` | Wired | fires at the `<c-slot>` site (docs/design/slots.md section 7) |
| *(new)* `on_attrs_resolved` | Wired | citry-only; fires per HTML element with dynamic attributes, after the attribute dict resolves and before formatting ([`html_attrs.md`](html_attrs.md) section 5.5); ctx: `citry, component, tag_name, attrs`, threaded on `attrs` |
| `on_dependencies` | **Reshaped (built)** | not core; the `dependencies` extension fires it via `emit` at serialize time ([`dependencies.md`](dependencies.md) section 7.2) |
| *(new)* `on_render_context_merge` | Wired | the generalized `_merge_dependencies` step (9.1); core fires it, extensions own their slice of the merge |
| *(new)* `on_serialize` | Wired | fires at the end of `serialize()` with the joined HTML, threaded; the dependencies extension's placement point ([`dependencies.md`](dependencies.md) section 7.2) |

| DJC non-hook surface | citry status | Note |
|---|---|---|
| `ComponentExtension` base | Renamed | `Extension` |
| `ExtensionComponentConfig` | Renamed | `Extension.Config`; weakref + optional component kept (5.1) |
| `ExtensionManager` (global) | Reshaped | per-`Citry`; no deferral; smart dispatch + `emit` |
| `ComponentCommand` | Renamed | `ExtensionCommand` (stub; no runner yet) |
| `commands` list | Skeleton | kept (framework-agnostic CLI) |
| `urls` / `URLRoute` / resolvers | Wired (reshaped) | framework-neutral `Extension.urls` + `Citry.urls` + contrib adapters (section 11) |
| `extensions_defaults` | Skeleton | built now as a field on the `CitrySettings` schema object (5.2) |
| `<name>_class` escape hatch | **Dropped** | legacy `media_class` mirror (5.3) |
| `store_events` / `_init_app` deferral | **Dropped** | no Django app-load race (section 2) |
| `ExtensionMeta` / `ExtensionClass` | **Dropped** | DJC backwards-compat only |
| `args`, `context_data`, `component_class` dup | **Dropped** | no positional args; deprecated fields |

---

## 11. URLs: extension routes (built)

Extensions provide HTTP endpoints through **`Extension.urls`**: a list (or
property) of framework-neutral `URLRoute`s (`citry/util/routing.py`). The
manager combines them into `Citry.urls`, which the web-integration adapters
(`citry.contrib.asgi`/`wsgi`/`fastapi`) mount into the host app; a user
extension's routes are namespaced under `ext/<name>/`, built-ins own their
paths directly. Route handlers reach engine state through `self.citry`, the
back-reference the manager sets on every extension instance. Full design in
[`dependencies.md`](dependencies.md) section 9; the dependencies extension's
script endpoints are the first user.

---

## 12. Open questions

- The whole short-circuit / caching mechanism is **deferred** until more of the
  render skeleton exists (7.1): whether it is cache-extension-owned
  `on_component_cache` / `on_component_cache_hit` hooks, and whether (and how)
  `on_component_rendered` participates on a short-circuit. `on_component_input`
  mutate-only is settled.
- ~~Naming of the merge hook and the `emit` custom-hook API shape~~ settled
  (section 9): the hook is **`on_render_context_merge`** (it merges the
  `extra` bag between two `CitryContext`s), and `emit(name, ctx, result=...)`
  ships with the `none` / `first` / `map` policies, exercised by
  `on_dependencies` and `on_serialize`.
- Where `CitrySettings` is validated, and how settings compose with the existing
  per-class fields (5.2). (Decided: it is a real schema object, not a dict.)
- ~~`js_data` / `css_data` data-method signatures~~ settled (7.5):
  `js_data(kwargs, slots)` / `css_data(kwargs, slots)`, mirroring
  `template_data`, with optional `JsData` / `CssData` schemas.

---

## 13. Suggested phasing

1. **Skeleton - built.** `Extension`, `Extension.Config` (weakref +
   optional component), `ExtensionManager` (per-`Citry`, smart dispatch, `emit`),
   `CitrySettings` schema object,
   `ExtensionCommand`, the `On*Context` dataclasses (lean surface). The
   **Skeleton** rows of section 10 are wired at their hook points; core hooks
   route through `emit`. `extensions_defaults` as the first settings entry.
2. **Dependency extension, emission phase - built.** The first real
   `emit`-owned custom hook (`on_dependencies`), the `on_render_context_merge` and
   `on_serialize` core hooks, `Script`/`Style` types, `CitryContext.extra`
   population, serialize-time placement (#1144). Full design and remaining
   phases (client runtime, fragments, URLs) in
   [`dependencies.md`](dependencies.md).
3. **Caching / short-circuit - not started (deferred decision).** Conclude how
   short-circuiting works and how it interacts with `on_component_rendered`
   (7.1), then build the `CacheExtension` with its `emit()`-owned
   `on_component_cache` / `on_component_cache_hit` hooks.
4. **Slots - done.** `on_slot_rendered` fires at the `<c-slot>` site.
5. **CSS/JS - done.** The asset-loading subsystem
   ([`asset_loading.md`](asset_loading.md)) provides the `js`/`css` sources and
   fires `on_css_loaded`/`on_js_loaded`; the `js_data`/`css_data` data methods
   and their delivery are built (7.5, [`dependencies.md`](dependencies.md)).
6. **URLs - built** (section 11); the Django adapter
   (`citry.contrib.django`) and the django-components template-tag
   integration remain ([`dependencies.md`](dependencies.md) phase 5).
