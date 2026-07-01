# Design: citry package and django-components migration

This document tracks the extraction of the framework-agnostic component
engine from `django-components` into the `citry` Python package. It is the
persistent reference for this multi-session effort.

For operating rules see `/CLAUDE.md`. For current project state see
`/TODO/project_status_june_2026.md`.

---

## Package hierarchy

```
citry_core  (PyPI: citry-core)
  Rust bindings: parser, compiler, safe_eval, html_transform.
  No component logic. No Django.

citry       (PyPI: citry)
  Framework-agnostic component engine: nodes, slots, registry,
  rendering, extensions. Depends on citry_core. No Django.

django-components  (PyPI)
  Django integration: template tags, finders, loaders, management
  commands, settings. Depends on citry. Thin wrapper.
```

`citry` replaces `djc-core` in the dependency chain. Users who only want
Django components keep using `django-components` (which pulls in `citry`
automatically). Users who want the engine without Django depend on `citry`
directly.

---

## Guiding principles

1. **Iterative, not waterfall.** The migration works by establishing the
   core Component class and rendering pipeline first, then extending
   iteratively. The exact citry API will evolve as we work through the
   django-components code, so detailed specifications for later phases
   are intentionally deferred.

2. **Rendering core first, node implementations after.** The node
   implementations (ExprNode, IfNode, etc.) depend on knowing what
   the render output looks like. That answer is not "just a string" -
   features like `Const()` marking, expression caching, and
   `CitryElement` (see DJC issues) mean the render pipeline shapes
   what nodes produce. So: establish the rendering pipeline, then
   implement nodes to fit it.

3. **Every file reviewed individually.** Even "Django-specific" files
   may contain logic that belongs partly in citry. For example,
   `app_settings.py` contains field definitions that will split between
   citry settings and Django-specific settings. The classification
   below is a starting guide, not a final verdict.

4. **Consider planned features during design.** The DJC issue tracker
   contains features that affect the citry architecture. These are
   catalogued below and must be considered when designing each
   subsystem.

5. Drop features that are marked for deprecation in v1, v2, v3.
   When the djc source contains a comment, TODO, or NOTE about how
   something should be done differently (e.g. "dataclasses would be
   faster than NamedTuple"), **flag it to the user before implementing
   either approach**. Do not silently carry over the old approach, and
   do not silently pick the new one either. The djc comment is a signal
   that there is a design decision to make, and the user should make it.

6. **Tests alongside features.** Every feature gets tests when built.
   Tests use plain pytest; the isolation unit is a fresh `Citry()`
   instance per test (it owns its own registry, caches, and settings),
   not a `@djc_test`-style decorator. Some early test files still lean on
   the shared default `citry` instance (see "Test files to revisit" in
   the implementation log below).

7. **Type-check new code.** Run `uv run mypy packages/py/citry/citry/`
   after changes. New code must pass mypy with `--ignore-missing-imports`.

8. **Document as you go.** Each implemented feature is logged with
   rationale, usage examples, and design decisions in the implementation
   log at the end of this document. This serves as raw material for
   user-facing docs, tutorials, and colleague-facing summaries of
   what has been built.

---

## Planned features that affect citry architecture

These are open DJC issues that change how the citry API should be
designed. Grouped by which part of the architecture they impact.

### Rendering pipeline

| Issue | Feature | Architecture impact |
|---|---|---|
| [#1650](https://github.com/django-components/django-components/issues/1650) | `Component()` returns a `CitryElement`, not a string | Three-phase pipeline: `Component()` composes a `CitryElement`; `.render()` produces a `CitryRender` (rendered parts + collected metadata); `.serialize()` produces the HTML string. The render output is a struct so JS/CSS deps travel as data, not as marker strings. Cache stores objects. Full design in [`rendering.md`](rendering.md). |
| [#1083](https://github.com/django-components/django-components/issues/1083) | `Const()` marker for 50% perf gain | Nodes detect constant inputs and replace themselves with static text. Rendering context must track constness. |
| [#1473](https://github.com/django-components/django-components/issues/1473) | Expression caching | Variable tracking (already in AST) enables memoizing expression results across renders when inputs are unchanged. Tracked in citry [#18](https://github.com/citry-dev/citry/issues/18). |
| [#1337](https://github.com/django-components/django-components/issues/1337) | Lazy/streaming rendering | Rendering may be deferred; components produce futures or generators instead of synchronous strings. Tracked in citry [#19](https://github.com/citry-dev/citry/issues/19). |
| [#1326](https://github.com/django-components/django-components/issues/1326) | Avoid double-parsing component body | Template parsing should be cached at the class level, not re-parsed per render. |

The render-output model (the three-phase `CitryElement` -> `CitryRender` ->
HTML pipeline, the `CitryContext` render-scoped state, and the JS/CSS dependency
flow that drives the struct shape) is captured separately in
[`rendering.md`](rendering.md). It is built: `.render()` returns a
`CitryRender`, rendering is deferred (depth-unbounded, stack-driven), and
`serialize()` stamps the per-component `data-cid-<id>` markers. Placing
collected JS/CSS dependencies into `<head>`/`<body>` at serialize time is
built (the five dependency-rendering phases in
[`dependencies.md`](dependencies.md); see the implementation log below).

The `Const()` (#1083), expression-caching (#1473), and render-body-caching
design (and its many edge cases) is captured separately in
[`constness.md`](constness.md). Both the const *flow* (the
`wrapt.ObjectProxy`-based `Const` marker, detection, and the `Citry`-scoped
body cache keyed by const signature) and the *precompute pass* are built: precomputing
pre-computes const expressions and attributes, drops untaken `<c-if>`
branches, and unrolls small const `<c-for>` loops. Phase-2 taint tracking is
parked (citry [#20](https://github.com/citry-dev/citry/issues/20)), as is
across-render expression caching (citry [#18](https://github.com/citry-dev/citry/issues/18)).

### Component class

| Issue | Feature | Architecture impact |
|---|---|---|
| [#1195](https://github.com/django-components/django-components/issues/1195) | Phase out registered names, use class names directly | `Component()` takes a class, not a string name. Registry becomes optional. |
| [#1413](https://github.com/django-components/django-components/issues/1413) | Global `Components` instance for all state | A `Components()` instance scopes settings, registries, caches. Avoids module-level globals. Easier test isolation. |
| [#1240](https://github.com/django-components/django-components/issues/1240) | Template-only / class-less components | Components can be defined from a template file alone (no Python class). The `CitryTemplate` struct ([`asset_loading.md`](asset_loading.md) section 4) is the synthesis seat: a template-only component starts from a `CitryTemplate` with no user class. Tracked in citry [#17](https://github.com/citry-dev/citry/issues/17). |
| [#1144](https://github.com/django-components/django-components/issues/1144) | `Component.Media` becomes an extension | Realized from the start: secondary assets are the `Dependencies` class, owned by the built-in `dependencies` extension ([`asset_loading.md`](asset_loading.md) section 7). |
| [#1259](https://github.com/django-components/django-components/issues/1259) | Deprecate slot context input and outer_context | Simplifies slot resolution API. |

### Extension system

| Issue | Feature | Architecture impact |
|---|---|---|
| [#829](https://github.com/django-components/django-components/issues/829) | Extensions/plugins architecture | citry must have a hook system that extensions can register into. Django-specific behavior (template tags, finders) is an extension. |
| [#1213](https://github.com/django-components/django-components/issues/1213) | Extensions specify HTML attribute rules | Extension hooks for attribute validation at parse time. |
| [#1230](https://github.com/django-components/django-components/issues/1230) | Scoped CSS | CSS scoping as an extension, needs render-time attribute injection. |
| [#1444](https://github.com/django-components/django-components/issues/1444) | Head tag extension | Extensions can inject content into `<head>`. |

### Other

| Issue | Feature | Architecture impact |
|---|---|---|
| [#1340](https://github.com/django-components/django-components/issues/1340) | Fragment tag | Template partials within a component template. |
| [#897](https://github.com/django-components/django-components/issues/897) | Partials support | Related to fragments. |
| [#1471](https://github.com/django-components/django-components/issues/1471) | Language server / linter | Variable tracking in AST already supports this. |
| [#1118](https://github.com/django-components/django-components/issues/1118) | MCP for component metadata | CLI/tooling integration. |
| (no issue yet) | Component URLs + `Component.Events` | Components served over HTTP (djc's `Component.View` / `get_component_url`), redesigned: handlers named by the *event* they handle (`Events.submit()`, `Events.delete()`, ...) instead of by HTTP method. DJC's `View` forced every action onto an HTTP-method name, which broke down when one component backed several mutations (one had to go under `post()`, another under `patch()`). Each handler declares what it accepts (query args, request body, file upload, eventually websocket events). Builds on `Extension.urls`, the fragment strategy, and the mount contract from [`dependencies.md`](dependencies.md) section 9.5. Needs its own design doc. |
| [#473](https://github.com/django-components/django-components/issues/473) | Define public API | citry gets a clean public API from scratch. |

---

## Node implementation groups

Nodes are the Python runtime classes the V3 compiler output instantiates.
**Implementation order: rendering core first, then nodes to fit it.**

**Status: all three groups are implemented** (in `citry/nodes/__init__.py`),
plus one node the original plan did not list: `ElementAttrsNode`, which
merges static, dynamic, and `c-bind` attributes on a plain HTML element
with Vue-like `class`/`style` merging.

### Group 1: Value nodes

| Node | Renders |
|---|---|
| `ExprNode` | Evaluates a Python expression |
| `TemplateNode` | Evaluates a nested template (recursive) |
| `StaticHtmlAttr` | Returns `key="value"` or bare `key` |
| `ExprHtmlAttr` | Evaluates expression, returns `key="result"` |
| `TemplateHtmlAttr` | Evaluates nested template, returns `key="result"` |

### Group 2: Control flow nodes

| Node | Renders |
|---|---|
| `IfNode` | First truthy branch body |
| `ForNode` | Body per iteration item; empty branch if no items |

### Group 3: Component nodes (requires extracted engine)

| Node | Renders |
|---|---|
| `ComponentNode` | Full component lifecycle |
| `SlotNode` | Insertion point (fill or fallback) |
| `FillNode` | Content for a slot |

### Built-in components

| Tag | Purpose | Status |
|---|---|---|
| `<c-provide>` | Dependency injection | Implemented (`citry/components/provide.py`, a `transparent` component) |
| `<c-js>` | JS dependency rendering | Implemented (`citry/components/js_css.py`); renders a `Placeholder` part the dependencies extension fills at serialize ([`dependencies.md`](dependencies.md) section 7.3) |
| `<c-css>` | CSS dependency rendering | Implemented (`citry/components/js_css.py`); same mechanism |
| `<c-component>` | Dynamic component (components only) | Implemented (`citry/components/dynamic.py`); design in [`dynamic_component.md`](dynamic_component.md) |
| `<c-element>` | Dynamic HTML element (any tag name) | Implemented (`citry/components/dynamic.py`); sibling of `<c-component>`, same doc |

---

## django-components file classification

**Every file is reviewed individually during migration.** The categories
below are a starting guide. Files marked "stays in django-components"
may still contain logic that splits between citry and Django.

The review is done (June 2026): every group links to its per-feature
verdict tables. The "likely destination" guesses in the tables below are
the original estimates, kept as-is; where they disagree with a verdict
table, the verdict table is authoritative.

### Component logic (migrate to citry, review case by case)

Reviewed file by file; see [Feature review by file](#feature-review-by-file-component-logic)
below for the per-feature verdicts.

| File | Lines | Django coupling | Notes |
|---|---|---|---|
| `component.py` | 3620 | Heavy | Component class, metaclass, lifecycle. Core of citry. |
| `component_render.py` | 1444 | Heavy | Render pipeline, component tree. Core of citry. |
| `slots.py` | 1688 | Medium | Slot/fill system. Core of citry. |
| `extension.py` | 1555 | Light | Plugin/hook system. Core of citry. |
| `component_registry.py` | 705 | Light | Registry, weakrefs. Evolving (#1195). |
| `component_media.py` | 1290 | Medium | CSS/JS management. Will become extension (#1144). |
| `dependencies.py` | 1927 | Heavy | JS/CSS dependency rendering. Blueprint for the citry dependency extension; definitely ports. |
| `provide.py` | 174 | Light | Provide/inject. |
| `attributes.py` | 441 | None | HTML attribute merging. |
| `expression.py` | 135 | Medium | Template expression eval. |
| `context.py` | 50 | Medium | Context key management. |
| `constants.py` | 3 | None | Constants. |
| `types.py` | 7 | None | Type aliases. |
| `cache.py` | 50 | None | Component instance cache. |

### Primarily Django (stays, but review for splits)

Reviewed file by file; see [Feature review by file](#feature-review-by-file-primarily-django)
below for the per-feature verdicts.

| File | Lines | Notes |
|---|---|---|
| `app_settings.py` | 953 | Settings fields will split: some move to citry settings, some stay Django-specific. |
| `template.py` | 486 | Django Template integration, template caching, origin mapping. (Missed in the original classification.) |
| `apps.py` | 121 | Django AppConfig. |
| `autodiscovery.py` | 111 | Django app discovery. |
| `finders.py` | 166 | Django static finders. |
| `library.py` | 69 | Django template Library. |
| `template_loader.py` | 32 | Django template loader. |
| `node.py` | 891 | Django template Node/BaseNode. Some concepts (tag parsing, parameter handling) may extract. |
| `tag_formatter.py` | 306 | `{% component %}` formatting. |
| `cache_tag.py` | 214 | Django `{% cache %}` integration. |
| `urls.py` | 18 | Django URLs. |
| `templatetags/` | - | Django template tags. |
| `commands/` | - | Django management commands. |
| `management/` | - | Django management. |
| `compat/` | - | Django compatibility. |

### Utilities (case by case during migration)

Reviewed file by file; see [Feature review by file](#feature-review-by-file-utilities)
below for the per-feature verdicts.

| File | Likely destination |
|---|---|
| `util/misc.py` | Mostly citry |
| `util/cache.py` | citry |
| `util/exception.py` | citry |
| `util/logger.py` | citry |
| `util/nanoid.py` | citry |
| `util/weakref.py` | citry |
| `util/css.py` | citry |
| `util/routing.py` | citry |
| `util/types.py` | Partial |
| `util/context.py` | Partial |
| `util/template_tag.py` | Django |
| `util/template_parser.py` | Django |
| `util/django_monkeypatch.py` | Django |
| `util/testing.py` | Partial |
| `util/command.py` | Django |
| `util/loader.py` | Django |

### Extensions (case by case)

Reviewed file by file; see [Feature review by file](#feature-review-by-file-extensions)
below for the per-feature verdicts.

| Extension | Likely destination |
|---|---|
| `extensions/defaults.py` | Partial |
| `extensions/dependencies.py` | Django |
| `extensions/cache.py` | Partial |
| `extensions/view.py` | Django |
| `extensions/autodiscovery.py` | Django |
| `extensions/debug_highlight.py` | Django |

---

## Feature review by file (component logic)

A per-feature audit of the djc "component logic" files against what citry
has built (reviewed June 2026). The other groups are reviewed in the
sections that follow:
[primarily Django](#feature-review-by-file-primarily-django),
[utilities](#feature-review-by-file-utilities), and
[extensions](#feature-review-by-file-extensions). With that, every file in
`_djc_reference/` is classified.

Status legend:

- ✅ **Done** - exists in citry (possibly with deliberate design divergences;
  the notes say which).
- 🚧 **To migrate** - belongs in citry, not built yet.
- ❓ **Ambiguous** - needs a design decision before migrating; do not port
  as-is.
- ♻️ **Superseded** - the need is met by a different citry design; nothing
  left to port.
- ❌ **Drop** - deprecated in djc (TODO_V1/V2) or deliberately not carried
  over (per guiding principle 5, deliberate drops are flagged here, not
  silently skipped).
- ⏭️ **Skip (Django)** - Django-specific; stays in django-components.

### `component.py` (3620 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `template` / `template_file` declaration | ✅ Done | `citry/media.py` asset loading; file paths resolve relative to the component's `.py` file, then `Citry(dirs=...)` |
| `template_name` alias + `ComponentTemplateNameDescriptor` | ❌ Drop | Deprecated alias of `template_file` |
| `get_template_name()` / `get_template()` / `get_context_data()` | ❌ Drop | All marked TODO_V1 in djc; superseded by `template`/`template_file` + `template_data()` |
| `Args` (positional inputs) | ❌ Drop | citry components are kwargs-only (`Component(**kwargs)`) |
| `Kwargs` / `Slots` / `TemplateData` typed classes | ✅ Done | Auto-dataclass (djc used NamedTuple); also feed parse-time validation via `tag_rules.py` |
| `get_template_data()` | ✅ Done | As `template_data(kwargs, slots)`; no `args`/`context` params |
| `js` / `js_file`, `css` / `css_file` declarations | ✅ Done | Loading half only (`media.py`); emission is the dependency extension |
| `JsData` / `CssData` + `get_js_data()` / `get_css_data()` (JS/CSS variables) | ✅ Done | `js_data(kwargs, slots)` / `css_data(kwargs, slots)` + auto-dataclass schemas, delivered to the browser as hashed variables scripts and `data-ccss`-scoped stylesheets ([`dependencies.md`](dependencies.md) section 5) |
| `Media` nested class, `media` property | ✅ Done | `CitryMedia` via `get_media()`; user's class not mutated, callables lazy, `bytes` entries dropped |
| `media_class` | ❌ Drop | Django forms `Media` output class |
| `on_render_before` / `on_render` (incl. generator form) / `on_render_after` | ✅ Done (diverged) | A single `on_render()` hook; before/after dropped (template_data and the generator's post-yield phase cover them). No `Context`/`Template` args, no lambda yields; the generator receives the completed `CitryRender`. Design in [`on_render.md`](on_render.md) |
| `Component.on_dependencies()` | ✅ Done | A classmethod, called per rendered instance at serialize time ([`dependencies.md`](dependencies.md) section 7.2) |
| `Cache` / `Defaults` / `View` / `DebugHighlight` nested configs | ✅ Done (mechanism) | Generic `Extension.Config` exists; the bundled extensions themselves are reviewed with `extensions/` (View/DebugHighlight likely stay Django) |
| `Component.name` | ✅ Done | Registers under that name only |
| `registered_name` | ❌ Drop | Registered names phased out (djc #1195) |
| `Component.id` (render id) | ✅ Done | Plus `data-cid-<id>` serialize markers |
| `ComponentInput` / `Component.input` | ♻️ Superseded | Instance exposes `kwargs`/`raw_kwargs`, `slots`/`raw_slots`; no `args`, no `context` |
| `kwargs` / `raw_kwargs` / `slots` / `raw_slots` accessors | ✅ Done | |
| `context` / `outer_context` | ⏭️ Skip (Django) | Django `Context`; `outer_context` deprecated (djc #1259). citry passes only props + slots between components |
| `deps_strategy` (`document`/`fragment`/...) | ✅ Done (diverged) | `serialize(deps_strategy=..., deps_position=...)`, not context state; `fragment` raises until the client-runtime phase |
| `Component.registry` / `Component.node` | ♻️ Superseded / ❌ Drop | Registry reached via `component.citry.registry`. `ComponentNode` is an internal node type in citry, not part of the public component surface, so a `Component.node` back-reference is deliberately not carried over |
| `is_filled` / `ComponentVars` (`{{ component_vars.* }}`) | ♻️ Superseded | djc injected template globals; in citry slots are explicit `template_data` inputs, so "is filled" is `slots.get(...)` |
| `request`, `context_processors_data`, `as_view()`, `render_to_response()`, `response_class` | ⏭️ Skip (Django) | The view extension stays in django-components |
| `parent` / `root` | ✅ Done | Set across the component boundary during render |
| `ancestors` generator | ✅ Done | Property walking the `parent` links, nearest first up to and including the root (djc's docstring says the root is excluded, but its code includes it; citry matches the code). The chain follows who wrote the component, same as `parent` |
| `inject()` | ✅ Done | `MISSING` sentinel so `inject(key, None)` genuinely defaults to `None`; did-you-mean hint |
| `provide()` | ✅ Done | citry addition: djc only had the `{% provide %}` tag |
| `Component.render()` classmethod (args/kwargs/slots/deps_strategy/request/...) | ♻️ Superseded | `Component(...)` -> `CitryElement` -> `.render()` -> `.serialize(deps_strategy=...)` |
| `all_components()` | ♻️ Superseded | `Citry.components` |
| `get_component_by_class_id()` / `_class_hash` | ✅ Done | `Component.class_id` + `Citry.get_component_by_class_id()` ([`dependencies.md`](dependencies.md) section 4.1) |
| `ComponentMeta` registration at class definition | ✅ Done | |
| `ComponentMeta.__del__` -> class-deleted hook | ✅ Done | Fires `on_component_class_deleted` |
| `on_component_garbage_collected` (provide cache cleanup) | ♻️ Superseded | Provides travel on `CitryContext.provides`; no global cache to clean |
| `ComponentNode` (`{% component %}` tag, spread args, `only` isolation flag) | ✅ Done / ♻️ Superseded | citry `ComponentNode` resolves attrs -> kwargs, `c-bind` spread; isolation flags are moot (no outer context is ever passed) |

</details>

### `component_render.py` (1444 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `_render_impl` orchestration | ♻️ Superseded | citry `render_impl` + `_render_one` |
| Depth-unbounded post-render queue (`component_post_render`, string parts, `<!-- _RENDERED -->` markers) | ✅ Done (diverged) | Object parts + explicit `_RenderTask`/`_FinalizeTask` stack; no marker comments or placeholder parsing |
| Child-first `on_component_rendered` ordering | ✅ Done | |
| Render error tracing with component path (`render_with_error_trace`, `ErrorPart`, "MyComp > slot > Child" paths) | ✅ Done (diverged) | Paths derive from the instance `parent` chain (no `full_path` threading); errors bubble by unwinding the task stack, no `ErrorPart` queue items. Plus template-position snippets djc could not show ([`on_render.md`](on_render.md) sections 5-6) |
| `on_render` generator driving (`make_renderer_generator`, `GeneratorResult`, `_call_generator`) | ✅ Done (diverged) | The `settle` step in `render_impl`: no lambda yields (the framework owns rendering), no version bookkeeping (object parts are swapped and re-queued), generator settles before extensions ([`on_render.md`](on_render.md) section 4) |
| `on_component_intermediate` per-part callbacks | ♻️ Superseded | `_FinalizeTask` |
| `on_component_tree_rendered` + final dependency pass (`render_dependencies`) | ✅ Done (diverged) | The `on_serialize` core hook + the dependencies extension's emission ([`dependencies.md`](dependencies.md) section 7); operates on collected records, not regex over HTML |
| `ComponentTreeContext` / `ComponentContext` structs | ♻️ Superseded | `CitryContext` |
| Deps strategy threading via context key | ♻️ Superseded | Becomes a render/serialize argument (impl notes) |
| `_get_parent_component_context` | ♻️ Superseded | `parent` is on the instance |

</details>

### `slots.py` (1688 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `Slot` class (lazy, repeatable callable + metadata) | ✅ Done | |
| `SlotContext` / `SlotFunc` / `SlotResult` / `SlotInput` | ✅ Done | |
| `normalize_slot_fills` | ✅ Done | Copies incomplete Slots instead of mutating |
| `Slot.contents` / `Slot.nodelist` / `Slot.fill_node` metadata | ✅ Done / ❌ Drop | `Slot.contents` (the raw fill body) and `Slot.source_position` (where the fill was written) exist alongside `component_name`/`slot_name`/`extra`. An originating-node / owning-component back-reference (djc's `nodelist` / `fill_node`) is not carried: no consumer needs it, and it can be added if an extension ever does. |
| `SlotFallback` wrapper | ✅ Done (diverged) | The fallback handle is itself a `Slot` |
| `SlotIsFilled` + `{{ component_vars.is_filled }}` | ♻️ Superseded | Slots are explicit inputs; check via `slots.get(...)` in `template_data` |
| `SlotNode`: name resolution, `required`, slot data kwargs | ✅ Done | Data resolves per render of the site (loops pass per-iteration data) |
| `default` flag on `{% slot %}` | ♻️ Superseded | The default slot is the one named `"default"` |
| Required-slot error with did-you-mean | ✅ Done | And only fires when the slot actually renders (untaken branches never error) |
| `FillNode`: `name` / `data` / `fallback`, `c-bind` spread | ✅ Done | |
| Dynamic fill names | ✅ Done | Per-name parse checks defer to runtime |
| Fills inside control flow (`resolve_fills` walking if/for) | ✅ Done | `collect_fills` polymorphic dispatch; fills close over their iteration's bindings |
| Implicit default slot from component body | ✅ Done | |
| Fill scoping (fills render in the writer's scope) | ✅ Done | |
| Slot escaping (`conditional_escape` on call) | ✅ Done | Via `markupsafe`, honors `__html__` |
| `context_behavior` (`django` vs `isolated`) slot resolution | ❌ Drop | citry passes only props + slots, so there is one behavior; the djc setting was registry-level config |
| `{% extends %}` interplay (`_extends_context_reset`) | ⏭️ Skip (Django) | |

</details>

### `extension.py` (1555 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `ComponentExtension` base + hook surface | ✅ Done | As `Extension`; hooks wired: extension-created, class created/deleted, registered/unregistered, input, data, rendered, slot-rendered, template loaded/compiled, js/css loaded, plus citry-only `on_attrs_resolved` |
| `on_registry_created` / `on_registry_deleted` | ♻️ Superseded | The registry is 1:1 with a `Citry` instance now; separate hooks no longer needed |
| `on_dependencies` hook | ✅ Done | Extension-owned custom hook fired via `emit` at serialize time; the first real consumer of the custom-hook mechanism |
| `ExtensionComponentConfig` (nested per-component config) | ✅ Done | As `ExtensionConfig`; the `<name>_class` escape hatch dropped |
| `ExtensionManager` dispatch | ✅ Done (diverged) | Smart dispatch (only extensions that override a hook) + generic `emit` |
| `store_events` / `_init_app` deferral | ♻️ Superseded | No Django app-load race: components bind to their `Citry` at class definition |
| Extension specs as import strings (`"path.to.Ext"`) | ✅ Done | |
| `extensions_defaults` | ✅ Done | |
| `get_extension(name)` / `get_extension_command(name, cmd)` | ✅ Done | |
| `ComponentCommand` (CLI commands) | ✅ Done (reshaped) | Built as the grown `ExtensionCommand` plus the framework-neutral `build_parser` / `run` in `citry/command.py`, aggregated across extensions via `Citry.commands` and surfaced by the `citry` executable ([`extension_commands.md`](extension_commands.md)) |
| `add_extension_urls` / `remove_extension_urls` (`URLRoute`) | ✅ Done (reshaped) | `Extension.urls` (list or property) combined into `Citry.urls`; user extensions namespaced under `ext/<name>/` ([`dependencies.md`](dependencies.md) section 9.1) |
| `mark_extension_hook_api` doc marker | ♻️ Superseded | Docs tooling concern |

</details>

### `component_registry.py` (705 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `ComponentRegistry` (register/unregister/get/has/all/clear) | ✅ Done (diverged) | Owned by `Citry` (`citry.registry`); name normalization + kebab-case aliases; reserved built-in names with lazy builtin creation |
| `AlreadyRegistered` / `NotRegistered` + duplicate detection | ✅ Done | Re-registering the same class is a no-op |
| Registration extension hooks | ✅ Done | `on_component_registered` / `on_component_unregistered` |
| `RegistrySettings` (`context_behavior`, `tag_formatter`) | ⏭️ Skip (Django) | Tag formatters dropped entirely |
| Django `Library` integration (`_register_to_library`) | ⏭️ Skip (Django) | See impl notes: new DJC renders Django-template pass first, then citry |
| `ALL_REGISTRIES` / `all_registries()` | ♻️ Superseded | `Citry` instance scoping |
| `@register()` decorator | ❌ Drop | `Component.name` or class-name registration |
| Weakref auto-unregister on GC | ❌ Drop | Hard refs + `Citry.clear()` |

</details>

### `component_media.py` (1290 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Inline/file asset pairs with MRO inheritance | ✅ Done (diverged) | Fields stay raw, accessors resolve; presence in `__dict__` replaces the `Unset` sentinel; explicit `None` stops the MRO walk |
| Lazy media descriptors (`ComponentMediaMeta`, `InterceptDescriptor`) | ♻️ Superseded | Existed for a Django settings race citry does not have |
| `ComponentMedia.reset_template` / `reset_files` | ✅ Done | `reset_template` also evicts the compiled body + const cache entries |
| `Media` entry normalization (str/Path/`__html__` objects/callables, lists, globs) | ✅ Done (diverged) | Input not mutated, callables run lazily, `bytes` dropped, globs sorted |
| `Media.extend` merging (True/False/list) | ✅ Done | De-dupes preserving first-seen order |
| Component-relative path resolution | ✅ Done | Component file's dir first, then `Citry(dirs=...)` |
| Django staticfiles resolution tier | ⏭️ Skip (Django) | Could return as a django-components extension hook |
| `media_class` | ❌ Drop | |
| File -> component index for hot reload | ✅ Done | `Citry._file_index` (weakrefs) + `get_components_for_file` |
| Rendering `Media` to script/link tags | ➡️ (elsewhere) | That logic lives in `dependencies.py`, reviewed next |

</details>

### `dependencies.py` (1924 lines)

The blueprint for the citry **dependency extension**, the largest remaining
port. The concepts migrate; the string-smuggling mechanics (HTML comments,
base64 manifests, regex over rendered HTML) are superseded by the object
pipeline (`CitryRender` parts + `CitryContext.extra`).

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `Script` / `Style` / `Dependency` structs (url-or-content, attrs, `to_json`/`from_json`, dedupe by url/content) | ✅ Done | Plus first-class use as `Dependencies` entries ([`dependencies.md`](dependencies.md) section 3); no string re-parsing |
| Caching of processed component JS/CSS + JS/CSS variables (`cache_component_js`, `cache_component_js_vars`, eviction) | ✅ Done | Class scripts with lazy repopulation; variables scripts hashed and cached per distinct data ([`dependencies.md`](dependencies.md) sections 4-5) |
| `render_dependencies()` + six strategies (`document`/`fragment`/`simple`/`prepend`/`append`/`ignore`) | ✅ Done (diverged) | `serialize(deps_strategy=..., deps_position=...)`: four strategies + positions, implementing djc's own TODO; `fragment` raises until the client-runtime phase ([`dependencies.md`](dependencies.md) section 7.1) |
| `_insert_js_css_to_default_locations` (`<head>`/`<body>` insertion) | ✅ Done | Plus a no-`<head>`/`<body>` fallback (prepend CSS, append JS) instead of djc's silent drop |
| `{% component_js_dependencies %}` / `{% component_css_dependencies %}` placeholder tags | ✅ Done | The `<c-js>` / `<c-css>` built-ins, rendering a core `Placeholder` part; first occurrence wins, later ones render nothing |
| Per-component attr injection for JS/CSS scoping (`set_component_attrs_for_js_and_css`) | ✅ Done | `data-cid-<id>` at serialize plus `data-ccss-<hash>` via the root-marker seam (internal `CitryContext._add_root_markers`); the every-element `all_attributes` mode belongs to scoped CSS (#1230), a separate feature |
| `<!-- _RENDERED ... -->` dependency comments + `insert_component_dependencies_comment` | ♻️ Superseded | Dependencies travel as data on the render objects, not marker strings |
| `TagAttrParser` / `_parse_html_tag_attrs` | ♻️ Superseded | No re-parsing of rendered HTML in the object pipeline |
| Client-side runtime (`_core_js`, pre-loader, `Components.onComponent` transform, exec-script manifests) | ✅ Done (rewritten) | Citry's own runtime (`extensions/dependencies/client/citry.js`, `globalThis.Citry.manager`): `$onComponent` callbacks called with `{id, els, data}` per instance via `data-cid` markers; `data-citry` JSON manifests, base64-armored. The fragment pre-loader lands with the fragments phase |
| `cached_script_view` + `urlpatterns` (serving cached JS/CSS over HTTP) | ✅ Done (reshaped) | Framework-neutral endpoints in the extension (`routes.py`: cache + runtime), with lazy repopulation for class scripts; served by the `citry.contrib` adapters ([`dependencies.md`](dependencies.md) section 9) |

</details>

### `provide.py` (174 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `{% provide %}` tag (`ProvideNode`) | ✅ Done | `<c-provide>` built-in component (a `transparent` component) |
| Inject lookup with default + error | ✅ Done (diverged) | `MISSING` sentinel so `inject(key, None)` works; did-you-mean hint added |
| Immutable NamedTuple payload | ✅ Done | `make_provided` |
| Provide key validation | ✅ Done | |
| Global provide cache + reference counting (`provide_cache`, `managed_provide_cache`, perfutil) | ♻️ Superseded | Provides travel on `CitryContext.provides` along the render path; no global cache or GC bookkeeping |
| (citry addition) `Component.provide()` method | ✅ Done | djc had no programmatic provider |

</details>

### `attributes.py` (441 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `{% html_attrs %}` tag (`HtmlAttrsNode`) | ✅ Done | As `ElementAttrsNode` (Vue-like attribute merging on elements) + `on_attrs_resolved` hook |
| `format_attributes` | ✅ Done | As `format_attrs` |
| `merge_attributes` | ✅ Done | As `merge_attrs` |
| `normalize_class` / `normalize_style` / `parse_string_style` | ✅ Done | Same names |
| `attributes_to_string` alias | ❌ Drop | Deprecated in djc (TODO_V1) |
| Escaping (`conditional_escape` / `format_html`) | ✅ Done | Via `markupsafe` |

</details>

### `expression.py` (135 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `TemplateExpression` (nested `{% %}` tags inside tag-attribute strings) | ♻️ Superseded | Template-in-attribute is first-class in V3 (`TemplateHtmlAttr` / `TemplateNode`); expressions are `safe_eval` Python |
| Single-node passthrough of non-string values | ♻️ Superseded | `ExprHtmlAttr` resolves to raw Python values by design |
| `StringifiedNode` | ⏭️ Skip (Django) | Django nodelist mechanics |

</details>

### `context.py` (50 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Internal context keys (`_COMPONENT_CONTEXT_KEY`, ...) | ♻️ Superseded | Typed fields on `CitryContext` |
| `make_isolated_context_copy` | ♻️ Superseded | No outer context crosses a component boundary: props + slots only |
| Forloop context copying | ♻️ Superseded | Loop scope is a child `CitryContext` |
| `_STRATEGY_CONTEXT_KEY` | ♻️ Superseded | Becomes a render/serialize argument (see impl notes) |

</details>

### `constants.py` (3 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `UID_LENGTH` / `COMP_ID_PREFIX` / `COMP_ID_LENGTH` | ✅ Done | Copied verbatim to `citry/constants.py` |

</details>

### `types.py` (7 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `css` / `js` / `django_html` annotated string aliases (IDE syntax highlighting) | ♻️ Superseded | Decided against: the source language is declared with `template_lang` / `js_lang` / `css_lang` string attributes instead (no import, composes with the pluggable asset compiler), and editor support comes from the citry language server, not typed aliases. Full reasoning and prior art in [`source_languages.md`](source_languages.md) |

</details>

### `cache.py` (50 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `template_cache` (LRU of parsed templates) | ❌ Drop | Marked TODO_V1 in djc; superseded by the class-level compiled-template cache + const body cache |
| `component_media_cache` (pluggable cache for inlined/processed JS & CSS) | ✅ Done (mechanism) | The `CitryCache` protocol + `Citry(cache=...)`, in-memory default ([`dependencies.md`](dependencies.md) section 10); the JS/CSS script caching that uses it lands with the emission phase |

</details>

---

## Feature review by file (primarily Django)

Same audit for the "primarily Django" group (reviewed June 2026). Same
status legend as above. The headline: most of these files stay, but
`node.py` carries the template-position-in-errors concept worth porting,
and a handful of unlisted files (reviewed at the end) contain genuinely
portable features (e.g. `ErrorFallback`).
(`dependencies.py` was reclassified into the component-logic group: it is
the blueprint for the citry dependency extension and definitely ports.)

### `app_settings.py` (953 lines)

The file is the Django settings bridge (`COMPONENTS = {...}` ->
`InternalSettings` with lazy loading and per-test reload). The mechanism
stays in django-components; the verdicts below are about each *field*.

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `ComponentsSettings` schema + `InternalSettings` lazy loading, `Dynamic[T]` re-read-per-access wrapper | ♻️ Superseded | `CitrySettings` is a frozen schema bound at `Citry()` construction; no Django settings race, no reload machinery |
| `extensions` / `extensions_defaults` | ✅ Done | Same names on `CitrySettings`, incl. import strings |
| `dirs` | ✅ Done | `Citry(dirs=...)`; djc's `(prefix, dir)` tuple form not carried (prefix only matters for staticfiles) |
| `app_dirs` | ⏭️ Skip (Django) | Per-app `[app]/components` dirs need Django's app registry; django-components can feed the resolved dirs into `Citry(dirs=...)` |
| `autodiscover` | ✅ Done | `Citry(autodiscover=True)` (default) imports the component modules under `Citry(dirs=...)` on first lookup, and `Citry.autodiscover()` runs it on demand. See `autodiscovery.py` below |
| `libraries` | ❌ Drop | An explicit list of component modules to import. It dates to when django-components was a pure-template tool with no component `.py` files to discover; with component classes the `dirs` scan (or a plain `import`) covers it, and it is being dropped upstream too |
| `cache` (named cache backend for component media) | ✅ Done | `Citry(cache=...)` / `CitrySettings.cache` ([`dependencies.md`](dependencies.md) section 10); `citry.contrib.django.DjangoCache` adapts any configured Django cache |
| `context_behavior` (`django` / `isolated`) | ❌ Drop | citry passes only props + slots; there is one behavior |
| `debug_highlight_components` / `debug_highlight_slots` | ⏭️ Skip (Django) | Belongs to the debug-highlight extension (reviewed with `extensions/`) |
| `dynamic_component_name` | ❌ Drop | The `<c-component>` built-in's name is reserved in the registry, so the name conflict this setting solved cannot arise; see [`dynamic_component.md`](dynamic_component.md) section 6 |
| `multiline_tags` | ♻️ Superseded | Existed to patch Django's tag regex; V3 syntax is HTML and multiline by nature |
| `reload_on_file_change` (+ `ReloadMode` hot/restart) | ✅ Done (citry half) | The invalidation seam is in citry (`Citry.get_components_for_file`, `reset_template`/`reset_files`); the host-neutral watcher that drives the seam is designed in [`hot_reload.md`](hot_reload.md) (the hot/restart policy stays host-specific) |
| `reload_on_template_change` | ❌ Drop | Deprecated alias of `reload_on_file_change` |
| `static_files_allowed` / `static_files_forbidden` / `forbidden_static_files` | ⏭️ Skip (Django) | staticfiles concern (`forbidden_static_files` is a deprecated alias) |
| `tag_formatter` | ❌ Drop | Tag formatters dropped entirely |
| `template_cache_size` | ❌ Drop | The LRU template cache it sized is dropped (TODO_V1) |

</details>

### `apps.py` (121 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `AppConfig.ready()` wiring | ⏭️ Skip (Django) | |
| Template monkeypatches (debug-toolbar profiler, `InclusionNode`, template-partials compat) | ⏭️ Skip (Django) | Compat with Django ecosystem packages |
| Multiline-tags regex patch | ♻️ Superseded | See `multiline_tags` row above |
| File-change reload listener (`_setup_component_file_reload`) | ⏭️ Skip (Django) | Django `file_changed` signal handler; calls into the invalidation seam that citry already owns. The host-neutral citry watcher (with a Django `file_changed` piggyback for this case) is designed in [`hot_reload.md`](hot_reload.md) |
| Registering `DynamicComponent` / `ErrorFallback` at app ready | ♻️ Superseded | citry's registry creates built-ins lazily via `builtins_factory`; which built-ins citry ships is the open question (see unlisted files below) |
| `extensions._init_app()` deferred extension init | ♻️ Superseded | Extensions bind at `Citry()` construction |

</details>

### `autodiscovery.py` (110 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `autodiscover()` (import every `.py` under the component dirs) | ✅ Done | citry owns it: `Citry.autodiscover()` and the `autodiscover` setting import the modules under `Citry(dirs=...)`, mapping each file to its import name by anchoring on `sys.path` (the framework-neutral stand-in for djc's `BASE_DIR`). Lives in `citry/autodiscovery.py`. Template-only components (djc #1240) will extend it to synthesize components from template files that have no `.py` |
| `import_libraries()` | ❌ Drop | Implemented the dropped `libraries` setting (see `app_settings.py` above) |
| `LOADED_MODULES` test bookkeeping | ❌ Drop | Tracked imported modules so `@djc_test` could unload them between tests. citry isolates per-test state with separate `Citry()` instances instead, so there is nothing global to unwind; a test that needs to re-import a module manages `sys.modules` itself |

</details>

### `finders.py` (166 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `ComponentsFileSystemFinder` (staticfiles finder over component dirs, allow/forbid filters) | ⏭️ Skip (Django) | Pure staticfiles integration |

</details>

### `library.py` (69 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `register_tag` / `mark_protected_tags` / `TagProtectedError` | ⏭️ Skip (Django) | Django `Library` bookkeeping for tag formatters (which are dropped). The one portable idea, reserving built-in names against user registrations, already exists in citry (`BUILTIN_COMPONENT_NAMES`) |

</details>

### `template_loader.py` (32 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `DjcLoader` (Django template loader over component dirs) | ⏭️ Skip (Django) | citry reads template files directly (`media.py`) |

</details>

### `node.py` (891 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `BaseNode` declarative tag definition (`tag` / `end_tag` / `allowed_flags`, params derived from `render` signature) | ♻️ Superseded | In V3 the Rust grammar parses tags; citry node classes are compiler output, not tag parsers |
| Tag input features (flags, literal lists/dicts, spread `...`, self-closing `/`) | ♻️ Superseded | The V3 grammar covers these natively (boolean attrs, expressions, `c-bind`, self-closing tags) |
| `template_tag()` decorator (user-defined custom tags) | ❌ Drop | citry's user-facing tag is the component (`<c-*>`); there is no user-defined custom-tag or custom-`Node` API, so there is nothing to port |
| `_format_error_with_template_position` (errors point at template line/col, with caret) | ✅ Done (diverged) | Via the shared formatter, now public as `citry_core.safe_eval.format_error_with_context`; citry applies it per failing node with the full template source + node span ([`on_render.md`](on_render.md) section 6.3), broader than djc's tag-signature-TypeError-only use |
| `_modify_typeerror_message` (friendlier missing-kwarg TypeErrors) | ♻️ Superseded | Typed `Kwargs` validation + parse-time tag rules produce the errors up front |
| `NodeMeta` signature validation | ♻️ Superseded | |

</details>

### `tag_formatter.py` (305 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Everything (`TagFormatterABC`, `ComponentFormatter`, `ShorthandComponentFormatter`, `get_tag_formatter`) | ❌ Drop | Tag formatters dropped entirely. The shorthand formatter's goal (call a component by its own name) is native in V3: `<c-table>` |

</details>

### `cache_tag.py` (214 lines)

<details open>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `{% cache %}` compat (`DjcCacheNode`, eager fragment assembly on cache miss) | ⏭️ Skip (Django) | Patches Django's cache tag around djc's two-pass render. **Lesson to keep:** its documented limitations (frozen `data-djc-id`s and stale js/css hashes inside cached strings) are exactly why citry caches must store `CitryElement`/`CitryRender` objects, never serialized HTML (djc #1650; already the citry design) |

</details>

### `urls.py` (18 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Mounting dependency + extension URL patterns | ♻️ Superseded | Citry owns the combined route table (`Citry.urls`); the Django mounting becomes the `citry.contrib.django` adapter ([`dependencies.md`](dependencies.md) sections 9.1-9.2) |

</details>

### `templatetags/component_tags.py`

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Django `Library` registration of all djc tags + `{% cache %}` override | ⏭️ Skip (Django) | The tags themselves are reviewed in their home files |

</details>

### `commands/` + `management/`

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `components` CLI (`list`, `create`, `upgrade`, `ext list`, `ext run`) + Django management bridge | ✅ Done (diverged) | The standalone `citry` CLI ships `list` / `create` / `ext list` / `ext run`, plus `--app module:attribute` engine selection and `--version` (`citry/commands/`, `citry/__main__.py`). `upgrade` is dropped (Django-template legacy); the Django management bridge and an MCP server were deliberately not built ([`extension_commands.md`](extension_commands.md) section 14) |
| `startcomponent` / `upgradecomponent` scaffolding commands | ⏭️ Skip (Django) | Generate Django-flavored files; a citry scaffolder would be new design, not a port |

</details>

### `compat/django.py`

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `load_as_django_command` (`ComponentCommand` -> Django management command) | ⏭️ Skip (Django) | citry deliberately adds no Django management-command bridge; Django projects call the installed `citry` binary directly ([`extension_commands.md`](extension_commands.md) section 14) |
| `routes_to_django` (`URLRoute` -> Django urlpatterns) | ✅ Done | `citry.contrib.django.urlpatterns()`; uses `re_path` where two parameters share a path segment ([`dependencies.md`](dependencies.md) section 9.2) |

</details>

### Files missing from the original classification

These exist in `_djc_reference/` but were not in the classification tables.

#### `template.py` (486 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `cached_template()` + the parsed-template LRU | ❌ Drop | TODO_V1 in djc; citry caches the compiled body generator on the class |
| `prepare_component_template` / `_maybe_bind_template` / `_load_django_template` | ⏭️ Skip (Django) | Django `Template`/`Origin` mechanics |
| `load_component_template` / `_create_template_from_string` | ♻️ Superseded | `media.py` `get_template()` -> `CitryTemplate` |
| `ensure_unique_template` (avoid shared mutable Template) | ♻️ Superseded | The body generator yields a fresh node list per render (djc #1326) |
| Template-file -> component index (`cache_component_template_file`, `get_component_by_template_file`) | ✅ Done | `Citry._file_index` / `get_components_for_file` |
| Origin tracking (`set_component_to_origin`) | ✅ Done (concept) | `CitryTemplate.origin` (file path or `module::Class`) |

</details>

#### `components/` (DynamicComponent, ErrorFallback)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `DynamicComponent` (`{% component "dynamic" is=... %}`) | ✅ Done | As the `<c-component>` built-in (components only), with a new `<c-element>` sibling for render-time HTML element names; full design and DJC surface table in [`dynamic_component.md`](dynamic_component.md). The class-valued `is` form works without any registered name, so it squares with djc #1195 |
| `ErrorFallback` (error boundary, React-style; fallback kwarg or slot with `error` data) | ✅ Done (diverged) | The `<c-error-fallback>` built-in (`citry/components/error_fallback.py`, reserved name); built on the `on_render` generator. Slot-based fallback invokes the fill with the error as data, no template re-render ([`on_render.md`](on_render.md) section 7) |

</details>

#### `testing.py`

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Public re-export of `@djc_test` | ❌ Drop | Re-exported the dropped `@djc_test` (see `util/testing.py` in the utilities section); nothing to re-export |

</details>

#### `perfutil/`

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `perfutil/provide.py` (provide cache + reference counting + GC unlinking) | ♻️ Superseded | Provides travel on `CitryContext.provides`; no global cache to manage |

</details>

---

## Feature review by file (utilities)

Same audit for `util/` (reviewed June 2026). Same status legend. Citry's
`util/` currently holds `misc.py` (ported as needed), `nanoid.py`, and the
new `html.py`; most of the rest of djc's `util/` either serves dropped
Django machinery or migrates together with a bigger feature (error tracing,
the dependency extension, the CLI).

### `util/misc.py` (339 lines)

Ported function by function, on demand. Current state:

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `to_dict` | ✅ Done | Extended beyond djc: also understands Pydantic v1/v2 via the attribute protocol |
| (citry addition) `get_fields` / `FieldSpec` | ✅ Done | Reads dataclass/NamedTuple/Pydantic field specs; feeds `tag_rules.py` |
| `gen_id` / `gen_component_id` | ✅ Done | As `gen_id` / `gen_render_id` in `util/id.py` |
| `get_module_info` | ✅ Done | |
| `is_glob` | ✅ Done | |
| `snake_to_pascal` | ✅ Done | |
| `get_import_path` | ✅ Done | `citry/util/misc.py`; feeds `Component.class_id` |
| `format_url` | ✅ Done | `citry/util/misc.py`: adds query params (True is a flag, False/None dropped) and a fragment to a URL, merging with any existing query. Framework-neutral stdlib helper; a future component-URL builder is its first caller |
| `is_generator` | ✅ Done | `citry/util/misc.py`; returns `TypeIs` so type checkers narrow both branches |
| `hash_comp_cls` | ✅ Done | As the `Component.class_id` metaclass property ([`dependencies.md`](dependencies.md) section 4.1) |
| `format_as_ascii_table` | ✅ Done | Ported into `citry/command.py` for the CLI's `list` / `ext list` tables (no trailing whitespace) |
| `is_str_wrapped_in_quotes`, `get_index` / `get_last_index`, `convert_class_to_namedtuple`, `extract_regex_matches` | ♻️ Superseded | All served Django tag parsing, Context-stack surgery, NamedTuple inputs, or regex-over-HTML; none exist in the citry design |
| `is_identifier`, `is_nonempty_str`, `default`, `flatten` | ♻️ Superseded | One-liners; citry call sites use the plain Python idiom (`key.isidentifier()`, `or`, comprehensions) |
| `any_regex_match` / `no_regex_match` | ⏭️ Skip (Django) | staticfiles allow/forbid filters |

</details>

### `util/cache.py` (115 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `LRUCache` (linked-list LRU) | ♻️ Superseded | Its djc consumer (the parsed-template cache) is dropped; citry's const body cache has its own bounded eviction. Revisit only if the dependency extension's in-process cache wants an LRU |

</details>

### `util/exception.py` (78 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `with_component_error_message` / `add_slot_to_error_message` (prepend the "MyComp > slot > Child" path onto raised errors) | ✅ Done (diverged) | `citry/util/exception.py`, same `_components` attribute for djc interop; the stdout print for args-less exceptions deliberately dropped (no printing from library code). Plus `set_template_position_error_message` for the template snippet |

</details>

### `util/logger.py` (108 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `django_components` logger + `trace` / `trace_component_msg` render tracing | ✅ Done | `citry/util/logger.py`: `logging.getLogger("citry")` plus a TRACE level (5, below DEBUG) and `trace` / `trace_component_msg` / `trace_node_msg` / `is_tracing`. Wired to trace each component, slot, and node as it renders (guarded so TRACE-off costs the hot path only a cached level check; per-node tracing was benchmarked to confirm no measurable penalty when off), plus debug logs for asset loading and autodiscovery |

</details>

### `util/nanoid.py` (28 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `generate(alphabet, size)` | ✅ Done | Copied to `citry/util/nanoid.py` |

</details>

### `util/weakref.py` (23 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `cached_ref` | ♻️ Superseded | citry's file index uses plain weakrefs; no shared-ref caching needed |

</details>

### `util/css.py` (51 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `is_css_func` / `serialize_css_var_value` (serialize CSS variable values) | ✅ Done | `citry/util/css.py`; feeds the generated CSS-variables stylesheets |

</details>

### `util/routing.py` (78 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `URLRoute` / `URLRouteHandler` (framework-neutral route description) | ✅ Done | `citry/util/routing.py`, plus `RouteResponse`, an explicit `methods` field, `{param}` paths, and a small first-wins router the generic adapters share ([`dependencies.md`](dependencies.md) section 9.1) |

</details>

### `util/types.py` (28 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `Empty` (explicit "this component takes no inputs" type) | ❌ Drop | A component that takes no inputs declares an empty `class Kwargs: pass` (or omits the schema). The empty dataclass already yields an empty parse-time rule set ("no attributes allowed"), so a dedicated type earns nothing. |

</details>

### `util/context.py` (169 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `snapshot_context` / `_copy_block_context` | ⏭️ Skip (Django) | Django `Context`/`BlockContext` mechanics |
| `gen_context_processors_data` | ⏭️ Skip (Django) | Django request-coupled processors; citry's instance-wide replacement is `template_globals` (see the implementation log) |

</details>

### `util/template_tag.py` (467 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Tag parsing (`parse_template_tag`, flags, filters, translation, spread) | ♻️ Superseded | The V3 Rust grammar owns all tag parsing |
| Aggregate kwargs (`attrs:class="..."` -> `attrs={"class": ...}`) | ♻️ Superseded | The use case (building an attrs dict at the call site) is covered by `c-bind` + `merge_attrs` and plain expression values |
| `resolve_python_expression` (`{% ... %}` Python-expression escape hatch) | ♻️ Superseded | Expressions are Python natively via `safe_eval` |

</details>

### `util/template_parser.py` (224 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Custom Django-template tokenizer (nested tags inside attribute strings) | ♻️ Superseded | The Rust parser handles nested templates as grammar, not string re-tokenizing |

</details>

### `util/django_monkeypatch.py` (371 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| All Template/IncludeNode/InclusionNode patches | ⏭️ Skip (Django) | Already mined for its one design rule: components receive only props + slots, never a shared Context (see impl notes) |

</details>

### `util/testing.py` (599 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `@djc_test` (per-test isolation of settings, registries, caches, imported modules) | ❌ Drop | citry has no test-isolation decorator: a `Citry()` instance is already the isolation unit (it owns its own registry, caches, and settings), so a test gets clean state by binding its components to a fresh instance. The two leftovers do not need one either: deterministic render ids become the `id_generator` setting, and a test that re-imports a module manages `sys.modules` itself rather than through citry API |
| `GenIdPatcher` (deterministic render ids in tests) | ✅ Done | Two pieces: the public `Citry(id_generator=...)` setting overrides the per-render id per instance (a callable, `"path.to.func"` import string, or a class built once), and the autouse per-test id-counter fixture in `tests/conftest.py` patches the built-in generator so every instance is deterministic across citry's own suite |
| `is_testing` / `CsrfTokenPatcher` / Django settings merging | ⏭️ Skip (Django) | |

</details>

### `util/command.py` (437 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `ComponentCommand` + `CommandArg`/`CommandArgGroup`/`CommandSubcommand` (declarative, framework-neutral argparse CLI) | ✅ Done | The arg dataclasses live in `citry/command.py` with their argparse-aligned names; `ComponentCommand`'s role is filled by the grown `ExtensionCommand` ([`extension_commands.md`](extension_commands.md) section 3) |
| `setup_parser_from_command` (argparse wiring) | ✅ Done | `build_parser` in `citry/command.py`, paired with the `run` dispatch loop lifted out of the Django bridge ([`extension_commands.md`](extension_commands.md) section 3.2) |
| `style_success` / `style_warning` (ANSI colors) | ✅ Done | Internal helpers in `citry/command.py`, gated on a color TTY / `NO_COLOR` so piped output stays plain |

</details>

### `util/loader.py` (254 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `get_component_dirs` (resolve `COMPONENTS.dirs` + per-app dirs from Django settings) | ⏭️ Skip (Django) | citry takes resolved paths via `Citry(dirs=...)`; the host computes them |
| `get_component_files` / `_filepath_to_python_module` / `_search_dirs` (scan dirs, map files to module paths) | ✅ Done | Ported framework-neutral to `citry/autodiscovery.py` as `find_component_modules` / `_path_to_module` / `_iter_py_files`; the file-to-module mapping anchors on `sys.path` instead of Django's `BASE_DIR` |
| `resolve_file` | ♻️ Superseded | `media.py` resolves asset paths against the component file and `Citry.dirs` |

</details>

---

## Feature review by file (extensions)

Same audit for `extensions/` (reviewed June 2026). Same status legend.
These are djc's built-in extensions, i.e. the first consumers of the hook
system. Two surprises against the original classification: `defaults.py`
is superseded outright (dataclass `Kwargs` carry their own defaults), and
`debug_highlight.py`, classified "Django", is actually a portable
extension and a good dogfood test for citry's hook system.

### `extensions/defaults.py` (269 lines)

<details open>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `Component.Defaults` nested class (defaults applied to missing kwargs in `on_component_input`) | ♻️ Superseded | citry `Kwargs` are dataclasses, so defaults live on the field declarations themselves, validated and typed. djc needed a separate class because its `Kwargs` was a NamedTuple over raw dicts |
| `Default(lambda: [...])` factory marker (fresh mutable default per instance) | ♻️ Superseded | `dataclasses.field(default_factory=...)` on the `Kwargs` field. Worth a docs example; decide whether to also re-export a `Default`-style convenience alias for users who find `dataclasses.field` clunky |
| Defaults for components *without* a `Kwargs` class | ❌ Drop | djc applied `Defaults` to raw kwarg dicts too. In citry, untyped components apply defaults in `template_data()`; if that proves noisy, the answer is declaring `Kwargs`, not a parallel defaults mechanism |

</details>

### `extensions/dependencies.py` (29 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Eagerly cache component JS/CSS at class creation (so assets survive a server restart mid-session) | ♻️ Superseded | Replaced by lazy repopulation at the script endpoint, keeping citry's no-I/O-at-import rule ([`dependencies.md`](dependencies.md) section 4.3); variables scripts still need a shared cache in multi-worker setups |

</details>

### `extensions/cache.py` (222 lines)

<details open>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `Component.Cache` config (`enabled`, `ttl`, `cache_name`) + cache key from kwargs hash | 🚧 To migrate | The caching extension. Critically, citry must cache the `CitryElement` / `CitryRender` *objects*, not HTML strings; djc's string caching is what freezes render ids and js/css hashes (the `cache_tag.py` lesson, djc #1650) |
| `include_slots` (hash slot fills into the key; cannot account for context vars used inside fills, djc #1164) | 🚧 To migrate (improved) | citry can do better than djc here: the AST tracks used variables, so a fill's free variables are knowable and can join the cache key instead of being silently ignored |
| Cache miss/hit short-circuit via `on_component_input` return | ❓ Ambiguous | Depends on the deferred short-circuit/caching hook split (django-components#1141 R6, noted as deferred in the extension-system log entry). Decide that hook design first |
| Django `BaseCache` storage | ⏭️ Skip (Django) | The storage goes through whatever the citry cache-backend protocol ends up being |

</details>

### `extensions/view.py` (415 lines)

<details open>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| `ComponentView` (`Component.View` with get/post/..., `as_view()`) | ❌ Drop (API shape) | The HTTP-method-named handler API is not ported; the concept returns redesigned as `Component.Events` (planned-features table above; [`dependencies.md`](dependencies.md) section 9.5) |
| `get_component_url()` / public view auto-registration | 🚧 To migrate (later) | Returns with the `Component.Events` design, on `Extension.urls` + the fragment strategy ([`dependencies.md`](dependencies.md) section 9.5) |

</details>

### `extensions/autodiscovery.py` (26 lines)

<details>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Run `import_libraries()` + `autodiscover()` at extension creation | ⏭️ Skip (Django) | citry runs autodiscovery from the `Citry` instance, not an extension: an extension's only setup hook (`on_extension_created`) fires inside `Citry()` construction, too early to import modules that bind to the instance. The dirs scan runs lazily on first lookup instead (see `autodiscovery.py` above) |

</details>

### `extensions/debug_highlight.py` (142 lines)

<details open>
<summary>Features</summary>

| Feature | Status | Notes |
|---|---|---|
| Visual debug overlay (wrap component/slot output in colored, labeled wrappers via `on_component_rendered` / `on_slot_rendered`) | 🚧 To migrate | Nothing Django about it: both hooks exist in citry and support replacing the output. Port it as a citry extension; it doubles as a real-world test of the hook system. Wrinkle to solve: it wraps *strings*, citry hooks see `CitryRender` parts |
| `debug_highlight_components` / `debug_highlight_slots` settings | 🚧 To migrate | As the extension's own config (per-component `Extension.Config` + `extensions_defaults`), not core `CitrySettings` fields |

</details>

---

## Migration approach

### Step 1: Establish the rendering core

Define the Component class, rendering context protocol, and the render
pipeline in citry. This is iterative: start minimal and extend as each
subsystem is extracted. Key decisions to make at this stage:

- What does `Component()` return? (string vs CitryElement, per #1650)
- How does the rendering context work? (dict-like, with Const() support per #1083)
- How do extensions hook into the lifecycle? (per #829)
- How is the global state scoped? (Components() instance per #1413)

### Step 2: Extract subsystems iteratively

Work through the "component logic" files. For each:
1. Read the DJC source and identify Django-coupled vs framework-agnostic logic.
2. Extract the framework-agnostic parts into citry, replacing Django types
   with citry's own protocols/abstractions.
3. Check the planned features list above for any that affect this subsystem.
4. Write tests.

Order is guided by dependency, but flexible:
- Extension system (lightest coupling, foundational)
- Attributes (no Django)
- Component registry
- Provide/inject
- Slots
- Component class + render pipeline (the big extraction)
- Component media (becomes extension per #1144)

### Step 3: Implement nodes

With the rendering core established, implement nodes to fit it. The
render output format (string vs CitryElement vs hybrid) determines what
each node produces.

### Step 4: Built-in components

`<c-provide>`, `<c-js>`, `<c-css>` as citry components.

### Step 5: Wire django-components to citry

Replace django-components' internal component logic with citry imports.
Django-components becomes a thin wrapper.

**Deferred.** Keeping django-components as a separate legacy project and
pointing its users at citry is simpler than re-absorbing all the Django
integration intricacies. Not planned for now.

---

## citry package structure

The actual layout as built (it diverged from the original sketch: one
`nodes/__init__.py` module instead of per-node files, render-phase structs
got their own `citry_*` modules, and the Django-shaped `context.py` /
`expression.py` / `cache.py` modules turned out not to be needed; see the
feature review below for what superseded them).

```
packages/py/citry/
  pyproject.toml           # depends on citry-core; no Django
  citry/
    __init__.py            # Public API (__all__ is the stability contract)
    citry.py               # Citry instance: registry, settings, caches, file index
    settings.py            # CitrySettings schema
    component.py           # Component class + ComponentMeta
    component_registry.py  # ComponentRegistry (owned by Citry, builtin names)
    autodiscovery.py       # Find + import component modules under Citry(dirs=...)
    component_render.py    # Render pipeline (deferred, stack-driven)
    citry_element.py       # CitryElement (composition phase)
    citry_render.py        # CitryRender (render phase)
    citry_context.py       # CitryContext (render-scoped state)
    citry_template.py      # CitryTemplate (loaded template source + origin)
    serialize.py           # HTML serialization + data-cid markers
    extension.py           # Extension/hook system
    slots.py               # Slot value, SlotContext, fill normalization
    provide.py             # Provide/inject building blocks
    media.py               # Template/JS/CSS asset loading, Media class, file index
    attrs.py               # HTML attribute merging (Vue-like class/style)
    constness.py           # Const marker, const body cache, precompute pass
    tag_rules.py           # Kwargs/Slots -> parser user_rules
    constants.py
    nodes/
      __init__.py          # All runtime nodes + HtmlAttr hierarchy
    components/
      __init__.py
      provide.py           # <c-provide> (js.py / css.py pending)
    util/
      misc.py
      nanoid.py
      html.py              # escape/Markup over markupsafe
  _djc_reference/          # Read-only copy of djc src (migration reference)
  tests/
```

---

## DJC issues to track

Issues that directly impact citry's architecture. Consult these when
designing each subsystem.

- [#1650 - CitryElement](https://github.com/django-components/django-components/issues/1650) - render output format
- [#1083 - Const() / 50% perf](https://github.com/django-components/django-components/issues/1083) - rendering context
- [#1473 - Expression caching](https://github.com/django-components/django-components/issues/1473) - variable tracking
- [#1337 - Lazy/streaming](https://github.com/django-components/django-components/issues/1337) - async rendering
- [#1413 - Global Components instance](https://github.com/django-components/django-components/issues/1413) - state scoping
- [#1195 - Phase out registered names](https://github.com/django-components/django-components/issues/1195) - registry
- [#1240 - Template-only components](https://github.com/django-components/django-components/issues/1240) - component class
- [#1144 - Media as extension](https://github.com/django-components/django-components/issues/1144) - extensions
- [#829 - Extensions architecture](https://github.com/django-components/django-components/issues/829) - extension system
- [#1259 - Deprecate slot context](https://github.com/django-components/django-components/issues/1259) - slots
- [#1340 - Fragment tag](https://github.com/django-components/django-components/issues/1340) - partials
- [#1326 - Avoid double-parsing](https://github.com/django-components/django-components/issues/1326) - template caching
- [#473 - Public API](https://github.com/django-components/django-components/issues/473) - API design

---

## Upstream references

- [django-components #1004: v3 Decoupling from Django](https://github.com/django-components/django-components/issues/1004)
- [django-components #1499: Template versions](https://github.com/django-components/django-components/issues/1499)
- [django-components #1141: v2 Ideas](https://github.com/django-components/django-components/issues/1141)

---

## Implementation log

Each feature is logged when implemented. Includes rationale, usage
examples, and design decisions. This raw material feeds future docs,
tutorials, and colleague-facing summaries.

Entries are chronological; where entries conflict, the later one wins
(early entries describe skeletons that later phases completed). Entries
not yet written for already-shipped features: provide/inject
(`provide.py`, `<c-provide>`, `CitryContext.provides`,
`Component.provide`/`inject`), Vue-like HTML attributes (`attrs.py`,
`ElementAttrsNode`, the `on_attrs_resolved` hook), and the const precompute pass
(`precompute_body`: expression/attr pre-computation, branch dropping, loop
unrolling).

### Test files to revisit

These test files lean on the shared default `citry` instance, which
accumulates state across tests. citry's isolation unit is a fresh
`Citry()` instance per test (it owns its own registry, caches, and
settings), so these should bind their components to a per-test instance
instead. There is no `@djc_test`-style decorator to wait for.

- `packages/py/citry/tests/test_citry.py`
- `packages/py/citry/tests/test_component.py`
- `packages/py/citry/tests/test_component_registry.py`
- `packages/py/citry/tests/test_const.py`
- `packages/py/citry/tests/test_render.py`
- `packages/py/citry/tests/test_nodes.py`
- `packages/py/citry/tests/test_component_node.py`

### Citry global instance (`citry/citry.py`)

**What:** A `Citry` class that scopes all component state. Owns a
component registry, settings, and (eventually) transient rendering state.

**Why:** In django-components, component state is scattered across
module-level globals (caches, registries, weakrefs), making test isolation
hard and cleanup fragile. The `Citry()` instance collects all of this under
one object. Deleting the instance cleans everything. Per DJC issue
[#1413](https://github.com/django-components/django-components/issues/1413).

**Design decisions:**
- **Lazy default instance.** A default `Citry()` is created the first time
  a Component is defined without an explicit `citry` field. Users who never
  call `Citry()` get the same behavior as before.
- **WeakSet for components.** The Citry instance holds a `WeakSet` of
  component classes. If a class is garbage-collected, it automatically
  disappears from the set. No manual cleanup needed.
- **`citry` module-level default instance.** Exported from the `citry`
  package as `from citry import citry`. Created eagerly at import time.
  If `Citry.__init__` ever grows dependencies that import from the package,
  switch to `__getattr__`-based laziness in `__init__.py`.
- **`clear()` method.** Wipes all registered components and (eventually)
  caches. Tests call this for setup/teardown.
- **Settings as kwargs.** `Citry(debug=True, base_dir="/tmp")` stores
  settings as a dict. The settings schema will be defined as citry grows.

**Usage:**

```python
from citry import Citry, Component

# Default instance (most common, no explicit Citry needed):
class MyTable(Component):
    template = "<table>...</table>"

# Custom instance:
app = Citry()
class MyTable(Component):
    citry = app
    template = "<table>...</table>"

# Test isolation:
def test_my_component():
    test_citry = Citry()
    class MyTable(Component):
        citry = test_citry
        template = "..."
    # test_citry.components contains only MyTable
    # default instance is untouched
```

### Component base class (`citry/component.py`)

**What:** The `Component` base class and its `ComponentMeta` metaclass.

**Why:** This is the core user-facing class. Every Citry component
subclasses it. The metaclass handles registration with the Citry instance
and auto-conversion of inner data classes.

**Design decisions:**
- **Metaclass registers at class definition time.** When `class MyComp(Component):`
  is defined, the metaclass immediately reads `citry` (or uses the default)
  and registers the class. This matches DJC's behavior and means the
  registry is always up to date.
- **Inner data classes auto-convert to a dataclass (with slots).** `Kwargs`,
  `Slots`, and `TemplateData` inner classes without an explicit base are
  converted to `dataclass(slots=True)` by the metaclass. This lets users write
  plain annotated classes and get typed, slotted inputs. This diverges from
  DJC, which used NamedTuple.
- **`Args` dropped.** DJC had both `Args` (positional) and `Kwargs`.
  In citry, components are instantiated as `Component({...})`, not
  `Component.render(args=[], kwargs={})`, so positional args are gone.
  Only `Kwargs` remains.
- **`template_data(kwargs, slots)` signature.** Simplified from DJC's
  `get_template_data(self, args, kwargs, slots, context)`. No `args`
  parameter (components take kwargs only), and no `context` parameter
  (render state stays internal; components that need data from above use
  `self.inject()`, see [provide.md](provide.md)).
- **Rendering is a skeleton.** The Component class defines structure and
  registration; rendering (parse, compile, exec, run the node classes) lives in
  the render pipeline (see its entry below) and currently runs with stub nodes.

**Fields:**

| Field | Type | Description |
|---|---|---|
| `citry` | `ClassVar[Citry \| None]` | Citry instance (default: auto-assigned) |
| `template` | `ClassVar[str \| None]` | Inline template string |
| `template_file` | `ClassVar[str \| None]` | Path to template file |
| `Kwargs` | `ClassVar[type \| None]` | Typed keyword arguments (auto-dataclass) |
| `Slots` | `ClassVar[type \| None]` | Typed slot definitions (auto-dataclass) |
| `TemplateData` | `ClassVar[type \| None]` | Typed template data output (auto-dataclass) |

**Usage:**

```python
from citry import Component

class Card(Component):
    template = '''
        <div class="card">
            <h2>{{ title }}</h2>
            <div>{{ body }}</div>
        </div>
    '''

    class Kwargs:
        title: str
        body: str = ""

    def template_data(self, kwargs, slots):
        return {
            "title": kwargs.title,
            "body": kwargs.body,
        }
```

### CitryElement (`citry/citry_element.py`)

**What:** An intermediate representation returned by `Component()`.
Holds the component class, kwargs, and slots. Rendering is deferred
until `.render()` is called.

> **Render-output model (see [`rendering.md`](rendering.md) and the "Render
> output" entry below).** `.render()` returns a `CitryRender` (a distinct
> render-phase struct carrying rendered parts plus an `extra` bag for metadata
> such as JS/CSS dependencies), and `CitryRender.serialize()` produces the HTML
> string. `str(element)` is a convenience that runs the full chain with
> defaults.

**Why:** In DJC, `Component.render()` returns a finished HTML string.
This has problems (DJC #1650): cached strings carry frozen per-instance
IDs and stale JS/CSS variable hashes that break on replay. The fix is
to split composition (creating the CitryElement) from rendering
(producing HTML). Each `.render()` call mints fresh state, so caching
the CitryElement instead of the string is safe.

This is the React `ReactElement` pattern: `<MyComp title="Hi" />`
creates a description of what to render, not the rendered output.

**Design decisions:**
- **`ComponentMeta.__call__` intercepts `MyComp(...)`.** When a user
  writes `Card(title="Hello")`, the metaclass `__call__` returns a
  `CitryElement` instead of a Component instance. This is non-standard
  Python but natural for web component APIs (React, Vue).
- **`_create_instance()` for the rendering pipeline.** Actual Component
  instances are created internally during rendering via
  `type.__call__(cls, ...)`, which bypasses the metaclass `__call__`.
  This mirrors DJC's `_render_impl` creating Component instances with
  render-time state (render_id, resolved context, etc.).
- **`template_data(self, kwargs, slots)` stays explicit.**
  Even though `self.kwargs` could exist, passing kwargs and slots as
  method arguments keeps the signature clear and mirrors React/Vue's
  functional component pattern. Users see immediately what inputs are
  available without learning the full Component instance API. The render
  context is internal; components that need data from above use
  `self.inject()` ([provide.md](provide.md)).
- **`.render()` delegates to the render pipeline.** It calls
  `render_impl(self)` (see the render pipeline entry below) and returns a
  `CitryRender`. The pipeline is a skeleton; the value, attribute, component, and
  control-flow nodes render, while slot nodes are a later phase.
- **`str(element)` renders and serializes.** `str(element)` calls
  `str(self.render())`, i.e. it runs the full pipeline (render then serialize)
  with defaults, so CitryElements can be embedded in f-strings or string
  concatenation and render transparently.

**Usage:**

```python
from citry import Component, CitryElement

class Card(Component):
    template = '<div class="card">{{ title }}</div>'

# Composition phase - returns a CitryElement, not HTML
card = Card(title="Hello")
assert isinstance(card, CitryElement)
assert card.comp_cls is Card
assert card.kwargs == {"title": "Hello"}

# CitryElements compose - pass one as input to another
class Page(Component):
    template = '<main>{{ content }}</main>'

page = Page(content=card)

# Rendering phase: render() -> CitryRender, serialize() -> HTML
# (str(page) runs both with defaults).
html = page.render().serialize()
```

### Component registry (on `Citry` class)

> **Superseded in part:** the registry has since been split into its own
> `ComponentRegistry` class (`citry/component_registry.py`), owned by the
> `Citry` instance as `citry.registry` (with `register`/`unregister`/
> `get`/`has` still delegated from `Citry`). The registry also now reserves
> the built-in component names (`provide`, `js`, `css`) and creates the
> built-ins lazily on first lookup. The naming/validation/duplicate rules
> below still hold.

**What:** The `Citry` class now serves as the component registry. Components
are registered by name at class definition time. Lookup, manual
register/unregister, and validation are all methods on `Citry`.

**Why:** DJC has a standalone `ComponentRegistry` class with a Django
`Library` dependency. In citry, the `Citry` instance already scopes all
component state, so the registry is a natural part of it. No separate
registry class needed. Per DJC #1195 (phase out registered names, use
class names directly).

**Design decisions:**
- **Name derived from class name by default.** `class MyCard(Component)`
  registers as both `"mycard"` (lowercased) and `"my-card"` (kebab-case).
  This follows Vue's convention where both `<MyCard>` and `<my-card>` find
  the same component.
- **`Component.name` override.** Setting `name = "fancy-widget"` registers
  under that name only (no auto-derivation from class name).
- **Case-insensitive lookup.** `citry.get("MyCard")` and `citry.get("mycard")`
  find the same component. This matches the compiler, which lowercases tag
  names.
- **PascalCase-to-kebab-case conversion.** `MyCard` -> `my-card`,
  `HTMLParser` -> `html-parser`. Uses regex: split before each uppercase
  letter following a lowercase letter or digit.
- **Name validation.** Names must start with a letter and contain only
  letters, digits, hyphens, underscores, or dots. Matches the grammar's
  `html_tag_name` rule.
- **Duplicate detection.** Registering a different class under an
  already-taken name raises `AlreadyRegistered`. Re-registering the same
  class is a no-op.
- **Unregister by class or name.** `citry.unregister(Card)` removes all
  names pointing to that class. `citry.unregister("card")` removes one name.
- **Test isolation.** Each `Citry()` instance has its own registry. Tests
  create isolated instances to avoid name collisions.

**DJC registry features NOT carried over (for now):**
- `TagFormatter` / tag registration with Django Library (Django-specific)
- `RegistrySettings` (context_behavior, tag_formatter) (Django-specific)
- `ALL_REGISTRIES` global list (replaced by `Citry` instance scoping)
- `@register("name")` decorator (replaced by `Component.name` or class name)
- Weakref finalizers for auto-unregister on GC (replaced by hard refs + `Citry.clear()`)

**Usage:**

```python
from citry import Citry, Component

c = Citry()

class MyCard(Component):
    citry = c

# Auto-registered under both lowered and kebab forms
assert c.has("mycard")
assert c.has("my-card")
assert c.get("mycard") is MyCard

# Case-insensitive lookup
assert c.get("MyCard") is MyCard

# Explicit name override
class Widget(Component):
    citry = c
    name = "fancy-widget"

assert c.get("fancy-widget") is Widget

# Manual unregister
c.unregister(MyCard)
assert not c.has("mycard")
```

### Input normalization with `to_dict` (`citry/util/misc.py`)

**What:** A `to_dict(data)` helper that converts a `dict`, `NamedTuple`, or
`dataclass` instance to a plain dict. Used to normalize component inputs at the
boundaries of the render pipeline.

**Why:** `kwargs`, `slots`, and the `template_data()` return value may arrive
as a plain dict or as a typed `Kwargs`/`Slots`/`TemplateData` instance (a
dataclass or NamedTuple). The pipeline needs a plain dict (for `**` expansion,
for defensive copying, and as the render context). A naive `dict(value)` raises
on a NamedTuple and produces the wrong shape for a dataclass. Ported from DJC's
`util/misc.to_dict`.

**Design decisions:**
- **Shallow for dataclasses.** Reads each field with `getattr` rather than
  `dataclasses.asdict`, so nested dataclasses are not recursively converted
  (values are kept as-is for rendering). Matches DJC, plus a guard
  (`not isinstance(data, type)`) so a dataclass *class* is not mistaken for a
  dataclass value.
- **`Component.__init__` normalizes and copies.** kwargs/slots run through
  `to_dict` and then a `dict(...)` copy, so a re-render cannot mutate the
  caller's input; the `CitryElement`'s stored inputs stay intact across repeated
  renders.
- **`template_data()` output is normalized, not copied.** It is produced fresh
  by user code each render, so it needs no defensive copy (unlike kwargs/slots,
  which are persistent element state).

### Render pipeline, skeleton (`citry/component_render.py`)

**What:** `render_impl(element)` drives one render: create the Component
instance, call `template_data()`, validate it, build the template body, and
render it to a string. `CitryElement.render()` delegates to it.

**Why:** This is the rendering half of the composition/rendering split. It is a
skeleton; some DJC features (context snapshotting, JS/CSS media) are not yet
ported.

**Design decisions:**
- **Class-level body generator (DJC #1326).** Parsing + compiling + `exec` of a
  template happens once per component class; the resulting `generate_template`
  function is cached on the class (`_template_body_generator`, via
  `_get_compiled_template`). That expensive step is invariant for a template, so it
  runs once; calling the cached function yields a fresh node list each render.
  The cache lives in the class's own `__dict__`, so a subclass overriding
  `template` builds its own generator.
- **Generation decoupled from rendering.** `_compile_template` (parse +
  compile + exec) is separate from `_render_body` (walk the node list, emit the
  string). This seam is where the parked const-precomputing cache will slot in.
- **No per-element body cache.** An earlier iteration cached the node list on
  the element; it was removed. Reusing an already-optimized body across renders
  is the job of the const-precomputing cache, not the element. The full const-precomputing
  and render-body-caching design (including the decision to build `Const` on
  `wrapt.ObjectProxy`) is parked in [`constness.md`](constness.md).
- **`TemplateData` validation.** If a component declares `TemplateData`, the
  `template_data()` output is validated by constructing `TemplateData(**data)`,
  which raises on a missing or unexpected field. Skipped when `template_data()`
  already returned a `TemplateData` instance.
- **Node rendering status.** The value nodes (`ExprNode`, `TemplateNode`), the
  attribute nodes, `ComponentNode`, and the control-flow nodes (`IfNode`,
  `ForNode`) are implemented (see the entries below); the slot nodes (`SlotNode`,
  `FillNode`) still raise `NotImplementedError` on `render` and are a later
  phase. `_render_body` calls each node's `render(context)`; when a node returns
  a `CitryRender` from a different context, it merges that render's dependencies
  into the current context (the seam where the dependency extension will hook).

**Usage:**

```python
from citry import Component

class Hello(Component):
    template = "<p>Hello!</p>"

# render() returns a CitryRender; serialize() (or str()) produces the HTML.
assert Hello().render().serialize() == "<p>Hello!</p>"
assert str(Hello()) == "<p>Hello!</p>"  # convenience: render + serialize
```

### Const flow, skeleton (`citry/constness.py`, render pipeline, `Citry`)

**What:** The plumbing for the const-precomputing feature: a `Const(value)` marker,
detection of const-marked context variables, a const signature, and a
`Citry`-scoped body cache keyed by `(component class, signature)`.

**Why:** Const-precomputing (DJC #1083) lets the engine reuse an optimized body for
inputs the author marks constant. This lands the *flow* (so the render pipeline
is const-aware and loads the body via the signature) without the optimization
itself. The full design and its edge cases are in
[`constness.md`](constness.md).

**Design decisions:**
- **Detection on the `template_data` output, not kwargs.** `Const` flows into
  the component and through `template_data` (pass-through); `render_impl` scans
  the resulting context for const-marked values. This matches the design's
  rejection of keying on raw kwargs.
- **`Citry`-scoped body cache.** Keyed by `(component class, const signature)`
  and cleared by `Citry.clear()`. The signature is the frozenset of
  `(variable name, const value)` pairs; an unhashable value falls back to a
  repr stand-in for now.
- **No precomputing yet.** The cached body is the unoptimized node list, equivalent
  across signatures, so the cache provides the lookup structure but no speedup
  yet. Precomputing (replacing all-const nodes with their results) slots into the
  `_compile_template` / `_render_body` seam later.
- **Markers are never unwrapped during rendering.** The `Const` markers stay
  in the render context so they flow down to descendant components, each of
  which can detect const-ness and key its own cache on it. Unwrapping would
  defeat that propagation.
- **`Const` is a `wrapt.ObjectProxy` subclass.** It is fully transparent, so
  user code and template expressions treat a const value exactly like the
  underlying value (only `repr` is overridden to show `Const(...)` for
  debugging); detection is `isinstance(x, Const)`. This adds `wrapt` as a
  runtime dependency of the `citry` package.

**Usage:**

```python
from citry import Component, Const

class Card(Component):
    template = "<p>{{ cols }}</p>"

    def template_data(self, kwargs, slots):
        return {"cols": kwargs["cols"]}   # passes the marker through

# Same const signature -> same cache entry; a different value -> a new entry.
Card(cols=Const(3)).render()
```

### Render output: `CitryRender` and `CitryContext` (`citry/citry_render.py`, `citry/citry_context.py`)

**What:** The two render-phase structs. `CitryRender` is what `.render()`
returns: an ordered `parts` list (each part a `str` or a nested `CitryRender`)
plus the `CitryContext` used during the render. `serialize()` joins the parts
into an HTML string; `str()`/`bytes()` coerce. `CitryContext` is the
render-scoped state threaded down `_render_body`: the per-component `variables`
(the `template_data` output), the current `component`, and an `extra` bag for
extensions.

**Why:** The render output must be an object, not a string, so a pre-rendered
subtree stays composable and carries metadata (JS/CSS dependencies) as data
rather than as marker strings smuggled through HTML (the DJC workaround). The
full design and reasoning are in [`rendering.md`](rendering.md); this entry
records what is built.

**Design decisions:**
- **Three-phase pipeline.** `Component()` -> `CitryElement` -> `.render()` ->
  `CitryRender` -> `.serialize()` -> HTML. Convenience coercions fall through
  with defaults: `str(CitryRender)` serializes, and `str(CitryElement)` (so
  `str(Component(...))`) renders then serializes.
- **Heterogeneous parts, deferred join.** A part is a `str` or a nested
  `CitryRender`; joining happens only in `serialize()`, which recurses. This
  keeps an embedded subtree composable until the final HTML is produced.
- **Two scopes, kept separate.** `CitryContext.variables` is per-component and
  does not cross a component boundary (a child gets fresh variables from its own
  `template_data`); `CitryContext.extra` is tree-wide scratch for extensions
  (dependencies bubble up). Conflating them is the thing to avoid.
- **`component` stored on the context.** This resolves the open question in
  [`rendering.md`](rendering.md) section 4.1: the current component is on the
  context, giving nodes the registry (to resolve child names) and parent/root
  linkage. Each component render gets its own `CitryContext`.
- **Serialization is the recursive join only, for now.** Placing collected
  dependencies into `<head>`/`<body>`, document-vs-fragment mode, and the
  injection strategy are future work (see [`rendering.md`](rendering.md)
  sections 5-6).

**Usage:**

```python
from citry import Component

class Hello(Component):
    template = "<p>Hello!</p>"

rendered = Hello().render()        # -> CitryRender
assert rendered.serialize() == "<p>Hello!</p>"
assert str(rendered) == "<p>Hello!</p>"
assert str(Hello()) == "<p>Hello!</p>"   # element -> render -> serialize
```

### Value nodes and autoescaping (`citry/nodes/__init__.py`, `citry/util/html.py`)

**What:** The body value nodes. `ExprNode` evaluates a `{{ expr }}` with
`safe_eval` against the context variables and returns an autoescaped string (or
inlines an embedded render). `TemplateNode` renders a nested template (a `c-*`
attribute whose value is itself a template) against the same context. Escaping
lives in `citry/util/html.py`, a thin layer over `markupsafe` exporting
`escape` and `Markup` (aliased `SafeString`).

**Why:** Makes dynamic templates actually render, with correct HTML escaping.

**Design decisions:**
- **`safe_eval`, compiled once (lazily).** Each node compiles its
  expression/template on first render and caches the result; the node is reused
  across renders via the body cache, so it compiles once. This is lazy rather
  than at construction (the compiler's note suggested "at initialization"); lazy
  still compiles once and avoids paying for nodes that never render (for example
  a branch precomputed away once const-precomputing exists).
- **`markupsafe` for escaping.** `escape()` escapes `& < > ' "`, which is safe
  in both body-text and double-quoted attribute positions. This matters because
  the compiler inlines a dynamic attribute on a plain HTML element as an
  `ExprNode` between literal quote strings, so the same node and escaper serve
  both positions. `SafeString` (= `Markup`) passes through unescaped via the
  `__html__` protocol. Adds `markupsafe` as a runtime dependency of `citry`.
  Rationale: HTML escaping is security-sensitive, so reuse the battle-tested
  standard rather than hand-roll it.
- **`_render_value` rules.** `None` renders as `""` (not the literal `"None"`);
  a `CitryElement` handed into an expression is auto-rendered; a `CitryRender`
  is inlined as trusted HTML (and `_render_body` merges its dependencies);
  anything else is escaped. `Const` flows transparently, so `escape` sees the
  underlying value.

**Usage:**

```python
# {{ }} is evaluated and escaped:
#   <p>{{ x }}</p>  with x="<b>"  ->  "<p>&lt;b&gt;</p>"
# A nested template in a c-* attribute renders against the same context:
#   <div c-body="<span>{{ x }}</span>">  with x="hi"  ->  '<div body="<span>hi</span>">'
```

### `ComponentNode` and the component boundary (`citry/nodes/__init__.py`)

**What:** `ComponentNode.render` resolves its attribute nodes into the child's
kwargs, looks the child up in the parent's Citry registry, and renders it
through `render_impl` (a context boundary). The attribute nodes
(`StaticHtmlAttr`, `ExprHtmlAttr`, `TemplateHtmlAttr`) gained `resolve(context)`.

**Why:** Lets a component template compose other components.

**Design decisions:**
- **attrs -> kwargs.** A dynamic attribute key drops its leading `c-`
  (`c-foo` -> `foo`); `c-bind` is a spread (its evaluated mapping merges into
  kwargs rather than producing a `bind` kwarg); a static boolean attribute
  passes `True`. `ExprHtmlAttr`/`TemplateHtmlAttr` resolve to **raw** Python
  values (not escaped or stringified) because they become component inputs;
  escaping happens later, when the child renders the value through an `ExprNode`.
- **Registry lookup via the context's component.** `context.component.citry`
  resolves the child name (case-insensitive). The child is rendered with
  `parent=context.component`, so parent/root linkage and the cross-boundary
  dependency merge both work.
- **`TemplateHtmlAttr` renders in the parent scope.** `c-body="<b>{{ x }}</b>"`
  on a component renders the nested template against the parent's context and
  passes the resulting `CitryRender` as the kwarg, mirroring a Vue/React
  fragment prop.
- **Body deferred.** A component with body content (default-slot text or
  `<c-fill>` nodes) raises `NotImplementedError`; slots are a later phase with
  their own design doc (many edge cases).
- **`ComponentMeta.__call__(cls, /, **kwargs)`.** `cls` is positional-only so a
  component may take a keyword argument named `cls` (for example an HTML class,
  `MyComp(cls="card")`) without colliding with the metaclass's first parameter.

**Usage:**

```python
from citry import Citry, Component

c = Citry()

class Card(Component):
    citry = c
    template = "<span>{{ title }}</span>"

    def template_data(self, kwargs, slots):
        return {"title": kwargs["title"]}

class Page(Component):
    citry = c
    template = '<main><c-card title="Hi" /></main>'

assert str(Page()) == "<main><span>Hi</span></main>"
```

### Node / HtmlAttr hierarchy and render typing (`citry/nodes/__init__.py`)

**What:** Two base classes plus tighter types over the node taxonomy. `Node` is
the base for the seven runtime nodes; `HtmlAttr` is the base for the three
attribute nodes. Type aliases `RenderPart` (`str | CitryRender`,
in `citry/citry_render.py`) and `BodyItem` (`Node | str`) replace the previous
`Any` typing of bodies and parts.

**Why:** Housekeeping (`issubclass(x, Node)` / `issubclass(x, HtmlAttr)` checks)
and real typing of the compiler-output contract (a compiled body is
`list[BodyItem]`; a rendered/parts list is `list[RenderPart]`; component/slot
`attrs` are `tuple[HtmlAttr, ...]`).

**Design decisions:**
- **Bases are NOT abstract.** The compiler builds the whole node tree up front,
  including nodes inside branches that may never render, so a not-yet-implemented
  node must still be instantiable. The base `Node.render` (and `HtmlAttr.resolve`)
  raises `NotImplementedError` instead of being `@abstractmethod`, so a
  not-yet-implemented node (`SlotNode`, `FillNode`) inherits the base and fails
  only when actually rendered, rather than at construction.
- **Attribute nodes are not `Node`s.** They `resolve` to a value (a component
  kwarg), they do not `render` to a part, so `HtmlAttr` is a separate hierarchy.
- **Leaf classes are `@final`; overrides use `@override`.** The node taxonomy is
  fixed: extensions subclass `Node`/`HtmlAttr`, never the leaves. `@override`
  (from `typing_extensions`, since the floor is Python 3.10) marks the six
  overriding `render`/`resolve` methods, which mypy verifies and which lets ruff
  stop flagging base-dictated unused arguments.
- **Runtime dependencies added to `citry`:** `markupsafe` (escaping, see the
  value-nodes entry) and `typing-extensions` (`@override` on 3.10/3.11).
  `wrapt` was already present (for `Const`).

### Control-flow nodes: `IfNode` and `ForNode` (`citry/nodes/__init__.py`, parser, `LangImpl`)

**What:** The two control-flow runtime nodes render. `IfNode` picks the first
branch whose `cond` is truthy (the `c-else` branch always matches); `ForNode`
renders its body once per item of the `each` clause, or its `c-empty` branch
when there are none. Authoring works in both forms: the explicit tags
(`<c-if cond=...>`, `<c-for each=...>`) and the shorthand attributes
(`<div c-if=...>`, `<li c-for=...>`).

**Why:** Makes templates branch and loop. The work spanned the cross-language
contract (parser + `LangImpl` + compiler output + Python runtime), so a key part
was making the two authoring forms produce *identical* variable metadata.

**Design decisions:**
- **The loop runs via a generator expression, not a hand-rolled iterator.** The
  `each` clause is a Python comprehension clause, so `ForNode` evaluates it by
  wrapping the loop targets in a tuple and the clause in a generator:
  `each="x in xs if x > 0"` becomes `((x,) for x in xs if x > 0)`, run through
  `safe_eval`. This reuses Python's own comprehension semantics, so multi-target
  unpacking (`k, v in d.items()`) and `if` filters work for free, and the full
  comprehension grammar the parser already accepts is supported with no extra
  code. The generator-expression evaluator is compiled lazily on first render and
  cached on the node (which is itself reused across renders via the body cache),
  so it compiles once. Wrapping a single target as a 1-tuple (`(x,)`) keeps single
  and multi-target binding uniform.
- **The loop body renders in a child `CitryContext`.** Each iteration overlays
  the loop bindings on the surrounding `variables` in a fresh child context that
  shares the parent's `component` and `extra` bag. So the loop introduces a
  variable scope without crossing a component boundary: the loop variable does
  not leak out, but dependencies still bubble through the shared `extra`. `IfNode`
  reuses the surrounding context unchanged (an `<c-if>` introduces nothing).
- **`cond` is resolved through the attribute node.** Post-enrichment (below) the
  `cond` attribute is an `ExprHtmlAttr`, so `IfNode` just calls
  `cond_attr.resolve(context)` and tests truthiness; a `cond` with no value
  (`<c-if cond>`) stays a boolean `True`. No separate expression machinery in the
  node.
- **The explicit and shorthand forms are unified at parse time.** Variable
  tracking diverged between the forms, and both feed the *same* compiler-emitted
  `IfNode`/`ForNode`, so the fix belongs upstream of codegen. The parser keeps the
  AST faithful (it does not rewrite `<div c-if>` into `<c-if>`; that structural
  expansion stays in the compiler) but enriches the variable metadata in place so
  the forms agree:
  - The explicit `cond`/`each` attributes are not `c-` prefixed, so they parsed as
    `Static` with no tracked variables. They are upgraded to `Expression` with
    their used variables populated.
  - The shorthand `c-for="x in xs"` attribute parsed as a generic expression, so
    its used variables wrongly counted the loop target (`x` *and* `xs`). They are
    recomputed as the clause's free variables (`xs`), and the loop targets (`x`)
    are recorded as the host element's *introduced* variables. The compiler's
    control-flow expansion then inherits the correct introduced variables, so
    `<div c-for>` and `<c-for>` compile to identical `ForNode`s.
- **For-loop variable analysis is language-specific and returns both halves
  together.** A single `LangImpl` method, `parse_forloop_variables`, returns a
  `ForLoopVars { introduced, used }`: the loop targets the clause binds and the
  free variables of its iterable/condition clauses. Bundling them mirrors
  `parse_expression` (which returns its variable categories together) and keeps
  them consistent (a target is never also reported as used). The Python
  implementation analyses the clause wrapped in a generator
  (`(None for <clause>)`): it walks the comprehension targets for `introduced`,
  and reuses the scope-aware expression analyser for `used` (the targets are
  bound, so the reported used variables are exactly the free variables). The
  JS/PHP/Go/Rust implementations are stubs. The parser calls this once per
  for-clause (in `process_control_flow_metadata`, which sets the attribute's
  used-vars and returns the host node's introduced-vars in one pass; the
  introduced set is carried from the start tag to the node via the tag stack), so
  each clause is parsed a single time.
- **Tests updated to the corrected contract.** The Rust parser/compiler tests
  that locked `cond`/`each` as `Static` (and the shorthand `c-for` as counting its
  loop target among used variables) encoded the pre-fix behavior; they were
  updated to assert the unified contract, not worked around.

**Usage:**

```python
# Explicit tags
"<c-if cond=\"n > 2\">big</c-if><c-else>small</c-else>"
"<c-for each=\"k, v in d.items()\">{{ k }}={{ v }} </c-for>"
"<c-for each=\"x in xs if x % 2 == 0\">{{ x }}</c-for><c-empty>none</c-empty>"

# Shorthand attributes (compile to the same IfNode/ForNode)
"<p c-if=\"show\">hi</p>"
"<li c-for=\"item in items\">{{ item }}</li>"
```

### Extension system, skeleton (`citry/extension.py`, `citry/settings.py`, `Citry`, render pipeline)

**What:** Phase 1 of the extension (plugin) system: an `Extension` base with the
lifecycle/registration/render/template hooks, a per-`Citry` `ExtensionManager`
that fans each hook out (smart dispatch + a generic `emit`), the
`Extension.Config` per-component nested-class mechanism, an `ExtensionCommand`
stub, the lean frozen-dataclass `On*Context` types, and a `CitrySettings` schema
object. Full design and the DJC divergences are in
[`extensions.md`](extensions.md); this entry records what is built.

**Why:** Extensions are the foundational, lightest-coupling subsystem (DJC #829),
and Django, the media/JS/CSS subsystem (#1144), scoped CSS (#1230), and caching
all become extensions on top of this surface.

**Design decisions:**
- **Scoped to the `Citry` instance** (#1413). `Citry(extensions=[...])` builds an
  `ExtensionManager`; `citry.extensions` is the manager and the raw spec lives in
  `citry.settings.extensions` as an immutable tuple. This deletes DJC's
  `store_events`/`_init_app` deferral machinery (no Django app-load race: a
  component class is bound to its `Citry`, and thus its extensions, at definition
  time in the metaclass).
- **Smart dispatch.** For each hook name the manager calls only the extensions
  that actually override it (cached `_extensions_with_hook`). `emit(name, ctx, result=...)`
  is the generic dispatcher (`result` is `"none"` / `"map"` / `"first"`); the
  named hook methods route through it. `emit` is also the seam for later
  extension-owned custom hooks (dependencies, caching).
- **Frozen-dataclass contexts, lean surface.** `@dataclass(frozen=True,
  slots=True)`, threaded with `dataclasses.replace`. Contexts carry `citry` plus
  (for render hooks) `component`; `component_class`/`component_id`/`registry` are
  derived, not duplicated. Class-lifecycle contexts carry `citry` +
  `component_class` (full name).
- **`CitrySettings` is a real schema object**, not a loose dict. `Citry` accepts
  only its known fields (`extensions`, `extensions_defaults`); arbitrary kwargs
  are rejected. The old `self._settings` dict is gone (`test_settings_stored`
  updated to the new contract).
- **`Extension.Config`** (shortened from DJC's `ComponentConfig`): the nested
  `class View:` is rebuilt as a subclass of `(user, GlobalDefaults, ext.Config)` so config
  precedence is component-level > `extensions_defaults` > factory. The component
  back-reference is a weakref with an optional `component` (an out-of-lifecycle
  extension such as a future Storybook port has `component=None`). The DJC
  `<name>_class` escape hatch (a `media_class` legacy mirror) is dropped.
- **Hooks wired this phase:** `on_extension_created`,
  `on_component_class_created`/`deleted`, `on_component_registered`/
  `unregistered`, `on_component_input` (mutate-only), `on_component_data`,
  `on_component_rendered` (operates on the `CitryRender`; return replaces, raise
  errors), `on_template_loaded` (per class, before parse),
  `on_template_compiled` (per built body, at the node list, before caching).
  **Deferred:** the short-circuit/caching split (django-components#1141 R6), the
  dependency/`on_render_context_merge`/`on_dependencies` hooks, slots, and CSS/JS hooks.
- **Known skeleton caveat:** `on_component_input` mutations land on
  `raw_kwargs`/`raw_slots` but do not yet propagate to the already-built typed
  `kwargs`/`slots`; that propagation is deferred (see [`extensions.md`](extensions.md) 7.1).

**Usage:**

```python
from citry import Citry, Component, Extension

class Timing(Extension):
    name = "timing"

    def on_component_rendered(self, ctx):
        print(f"{type(ctx.component).__name__} rendered")

app = Citry(extensions=[Timing])

class Card(Component):
    citry = app
    template = "<p>Hello {{ who }}</p>"

    def template_data(self, kwargs, slots):
        return {"who": "world"}

str(Card())   # prints "Card rendered"; returns "<p>Hello world</p>"
```

### Deferred rendering: infinite depth + component-id markers (`citry/component_render.py`, `citry/citry_render.py`, `citry/nodes/__init__.py`, `citry/serialize.py`)

**What:** Two changes that together let a component tree render to any depth and
tag each component's HTML. (1) `ComponentNode` no longer renders a child inline;
it returns a `DeferredComponent` part, and `render_impl` works through a stack of
pending components instead of calling itself. (2) `serialize()` now adds a
`data-cid-<id>=""` marker to each component's root element(s), recording which
component produced which part of the page. (Note: with this change `serialize()`
output carries markers, so the marker-free examples in earlier log entries show
pre-marker output.)

**Why:** Rendering a child inline made one component call the next, capping
nesting at Python's recursion limit (about 60 component levels). Working through a
list makes depth heap-bound. The markers are how a browser runtime will later
scope CSS and run per-instance JS; they are the citry form of django-components'
`data-djc-id` attributes. Full design and reasoning in
[`deferred_rendering.md`](deferred_rendering.md).

**Design decisions:**
- **`DeferredComponent` is the deferral point.** `ComponentNode.render` resolves
  the child's kwargs now (while the parent context, including `<c-for>` loop
  variables, is live) and returns a `DeferredComponent(element, parent)`. Only the
  child's render is deferred, not its inputs.
- **`render_impl` = `_render_one` + a drive loop.** `_render_one` renders one
  component, leaving children as `DeferredComponent` parts. The loop is an explicit
  stack of `_RenderTask` (render a child, put it where the placeholder was) and
  `_FinalizeTask` (run `on_component_rendered`, merge deps up). A component's
  children are added above its own `_FinalizeTask`, so the component and everything
  inside it finish first. This is django-components' `component_post_render`
  structure, on objects instead of strings, so no `<!-- _RENDERED -->` comments or
  `<template>` placeholder parsing are needed.
- **`on_component_rendered` fires children-first**, the moment each subtree is
  done, matching DJC. It moved out of `_render_one` onto `_FinalizeTask`.
- **Deps merge at finalize, into the parent context.** A child's `extra` is only
  complete after its descendants finalize, so the merge happens at the child's
  `_FinalizeTask`, not when it is first resolved.
- **Markers are added at serialize, on by default.** `serialize.py` does a
  two-pass, non-recursive marker pass (top-down marking, then bottom-up assembly)
  so serialize depth is also unbounded. Each component frame is transformed once
  via the existing `citry_html_transform` crate (`transform_html`), with child
  components as `<template c-render-id>` placeholders; the watch-map reports which
  children are at the root and inherit the parent's markers. When a parent's root
  is a child, the child's root carries both, e.g.
  `<div data-cid-c2="" data-cid-c1="">` (child marker first, then inherited).
- **CSS scoping (`all_attributes`) deferred.** Only the id marker is added for now;
  the per-element CSS-scoping attribute lands with the dependency extension.
- **Tests use deterministic render ids.** An autouse fixture in `tests/conftest.py`
  makes ids a per-test counter (`c1`, `c2`, ...), so tests assert the real marker
  output. A `TypeAlias` annotation on `citry_core`'s `transform_html` re-export,
  which made it non-callable under mypy, was changed to a plain re-export in
  passing.

**Usage:**

```python
class Inner(Component):
    citry = app
    template = "<div>x</div>"

class Outer(Component):
    citry = app
    template = "<c-inner />"          # Inner's <div> is Outer's root element

# Inner's root carries both ids (child first, then the inherited parent):
str(Outer())   # '<div data-cid-c2="" data-cid-c1="">x</div>'
```

### The Slot value (`citry/slots.py`)

**What:** The `Slot` class plus its surface: `SlotContext` (the single
argument a slot function receives), `normalize_slot_fills` (the Python-input
boundary), the typing aliases (`SlotResult`, `SlotFunc`, `SlotInput`), and the
`Slot` detection in `_render_value` so `{{ my_slot }}` renders slot content in
place. This is phase 2 of [`slots.md`](slots.md); fill collection at the
component boundary and `<c-slot>` resolution are the next phases.

**Why:** Every form of slot content (a string, a function, a composed
`CitryElement`, a rendered `CitryRender`, and later a `<c-fill>` body)
normalizes to one lazy, repeatable, standalone callable, so the rest of the
engine handles exactly one type. Ported from django-components' `Slot` with
the DJC scope machinery removed.

**Design decisions:**
- **Calling a Slot returns a `RenderPart`, not a string.** The result goes
  through `_render_value`, so a slot wrapping a component element re-renders
  it per call (fresh ids), an already-rendered subtree is inlined with its
  dependencies intact, and plain text is escaped.
- **The fallback handle is a Slot** (`SlotContext.fallback: Slot | None`),
  not a separate type. `{{ fallback }}` rides the same `_render_value`
  detection as any slot value; `str(slot)` (via `Slot.__str__`) renders and
  serializes in one step, with the same one-shot caveat as
  `CitryRender.serialize`.
- **Escaping at the earliest sensible point.** String/scalar contents are
  escaped at construction; a function's return value is escaped per call
  (`escape` honors `__html__`, so `SafeString` stays trusted). Matches
  `{{ expr }}` escaping.
- **`Slot(Slot(...))` raises** (ambiguous metadata, as in DJC);
  `normalize_slot_fills` copies an incomplete Slot (filling in
  `component_name`/`slot_name`, copying `extra`) rather than mutating the
  caller's instance.
- **Import direction:** `slots.py` has no module-load imports from
  `citry_render` (lazy inside methods), so `citry_render` imports `Slot` at
  the top and the hot `_render_value` path needs no per-call import.
- **`SlotFunc.__call__`'s `ctx` parameter is positional-only**, so slot
  functions may name the parameter anything.

**Usage:**

```python
from citry import Slot

slot = Slot(lambda ctx: f"Hello, {ctx.data['name']}!")
slot({"name": "John"})        # 'Hello, John!' - standalone, repeatable

MyPage(slots={"header": "Hi", "footer": slot})   # normalized at the boundary

# Inside a template, a Slot value renders in place:
#   {{ my_slot }}      - invoked with no data
#   {{ my_slot(d) }}   - invoked with data (Slot is callable in expressions)
```

### Fill collection and the `slots=` channel (`nodes/__init__.py`, `component.py`, `component_render.py`, `serialize.py`)

**What:** Slot content now travels from both channels into a component.
`MyComp(title="x", slots={...})` reserves the `slots` kwarg (extracted in
`ComponentMeta.__call__`); `Component.__init__` normalizes the inputs to
`Slot` values before building the typed `Slots` view. In templates,
`ComponentNode.render` turns its body into the child's slots: a body without
fills is the implicit `"default"` slot, and a fill group is collected by
executing control flow against the live context (an `<c-if>` contributes its
matching branch, a `<c-for>` contributes per iteration, each fill closing over
its own iteration's bindings). Until `<c-slot>` resolution lands, components
consume slots via `template_data(kwargs, slots)` and `{{ slot_var }}` /
`{{ slot_var(data) }}` expressions. This is phase 3 of
[`slots.md`](slots.md).

**Why:** The component boundary is where "what fills exist" must be decided
(loop variables and conditions are only live in the parent's render), while
fill *bodies* must stay lazy (slot data arrives at the slot site). Eager
collection + lazy Slots is the split that supports both.

**Design decisions:**
- **Fills close over the writer's scope.** A fill body renders against the
  context where it was written (parent variables, loop bindings), overlaid
  with the fill's `data`/`fallback` variables when the child passes them. The
  overlay shares the captured `extra` bag, so dependencies reach the fill's
  lexical owner.
- **Collection dispatches polymorphically.** `Node.collect_fills(context, sink)` is the second method of the node contract: the base rejects the node
  (nothing but fills, control flow, and whitespace may sit in a fill group),
  `IfNode`/`ForNode` contribute their matching branch / per-iteration fills,
  and `FillNode` resolves its own attributes and registers its body into the
  `FillSink`. Open dispatch means extension-injected node kinds can
  participate without the collector enumerating node types; collection still
  never calls `render`, so an invalid template fails before any side effect
  runs. The alternatives (a closed `isinstance` walk; collecting by rendering
  with a channel on the context) and why they lost are recorded in
  [`slots.md`](slots.md) sections 4.4 and 13.
- **`IfNode.active_branch_body` / `ForNode.iter_bodies`** extract the
  branch/iteration logic so rendering and fill collection cannot drift.
- **Runtime validation mirrors the parser:** duplicate materialized names,
  non-whitespace text/expressions beside fills, invalid `name`/`data`/
  `fallback` values, and `c-bind` spreads limited to `name`/`data`/`fallback`.
  In step, the parser's duplicate-fill checks were narrowed to fills outside
  control flow (the same name in exclusive `c-if`/`c-else` branches is valid;
  see [`slots.md`](slots.md) 11.4a).
- **`CitryRender.is_component_root`** distinguishes a component's whole output
  from interior renders. Serialization frames child components by this flag
  (not by context identity, which slot-fill content breaks: it carries the
  writer's context while rendering inside another component's frame), and
  `_scan_deferred` now descends into every nested render so components inside
  slot content defer correctly, with dependencies merged into the lexical
  owner's context. Side effect: a prop-template (`c-body="<b>...</b>"`) no
  longer stamps the parent's `data-cid` marker on its interior elements; only
  component roots are marked.
- **Unused slot content is silently ignored** (matching django-components:
  surplus fills are not an error, because slot names can be dynamic).

**Usage:**

```python
class Card(Component):
    template = "<div>{{ h }}</div>"

    def template_data(self, kwargs, slots):
        return {"h": slots.get("header", "")}

# Python channel:
Card(slots={"header": "Hi"})

# Template channel (collected by the parent's ComponentNode):
class Page(Component):
    template = '<c-card><c-fill name="header">Hello {{ name }}</c-fill></c-card>'
```

### Asset loading: template, JS, and CSS files (`citry/assets.py`, `citry/citry_template.py`, `citry/extensions/dependencies.py`)

**What:** Components declare primary assets in three inline/file pairs
(`template`/`template_file`, `js`/`js_file`, `css`/`css_file`) plus the nested
`Dependencies` class for secondary assets. Loaded values are read through
classmethods: `Card.get_template()` returns a `CitryTemplate` (source + origin
+ filepath + lazily-filled compiled form), `Card.get_js()`/`get_css()` return
loaded content, `Card.get_dependencies()` returns the merged
`CitryDependencies`. File paths resolve relative to the component's own `.py`
file first, then `Citry(dirs=...)`. Hot-reload seam: a file-to-component
weakref index on `Citry` plus `Card.reset_template()`/`reset_files()`. Full
design in [`asset_loading.md`](asset_loading.md).

**Why:** Ports DJC's `component_media.py` without its Django coupling, and
realizes DJC #1144 (media as an extension) from the start: the secondary-asset
concern lives in a built-in extension, so the later emission phase adds to it
without any user-facing migration. The loaded `js`/`css` are the sources the
`CitryContext.extra` dependency flow will consume.

**Design decisions:**
- **Fields stay raw; classmethods resolve.** DJC's lazy descriptors existed
  for a Django settings race citry does not have. Citry keeps `MyComp.js`
  exactly as declared; the `get_*` classmethods are thin delegates into
  `citry/assets.py`, cached once per class. They are accessors, not override
  points.
- **The pair is one inheritance unit.** Resolution walks the MRO for the first
  class whose own `__dict__` declares either member; explicit `None` stops the
  walk ("no asset"), absence continues to the parent. Presence in `__dict__`
  replaces DJC's `UNSET` sentinel. Both members set non-`None` on one class
  raise at class definition.
- **Paths resolve to absolute and files are read directly** (utf8). No
  staticfiles tier, no Django template loaders, no comp-dir-relative rewriting
  (DJC's own `TODO_v3` direction).
- **`CitryTemplate` is one object for source and compiled form.** It carries
  source (post-`on_template_loaded`), origin (file path, or `module::Class`
  for inline), filepath, and the compiled `generate`/`used_vars`, filled in
  place by the render pipeline on first render. One per-class cache
  (`_citry_template`), one invalidation. Parse/compile errors and the
  template-position snippet header carry the origin.
- **`Dependencies` is a built-in extension.** `DependenciesExtension`
  (`name = "dependencies"`) is prepended to every Citry instance's extensions
  (`_builtin_extensions`; names reserved). The nested class rides the standard
  `Extension.Config` rebuild for runtime access (`component.dependencies`),
  while the merge reads raw declarations captured in
  `on_component_class_created` (the rebuild would otherwise erase
  own-vs-inherited, path anchoring, `extend`, and explicit-`None` semantics).
  Entries (str/Path/glob/callable/`__html__` objects) resolve to absolute
  paths where they exist locally; URLs and unresolved paths pass through;
  globs are sorted (determinism rule). Merge order is **bases first, own
  last** (specialized CSS wins cascade ties; restores Django forms' order,
  which DJC had inverted), de-duplicated first-seen. The merged cache is a
  weak-keyed map on the extension instance, evicted via the `on_files_reset`
  hook, the first consumer of the custom-hook `emit` dispatch. Divergences
  from DJC: the user's nested class is not mutated, callables run lazily at
  resolution, `bytes` entries dropped.
- **Hot reload:** every resolved file registers in `Citry._file_index`
  (weakrefs); `Citry.get_components_for_file` is what a future watcher drives.
  `reset_template()` clears the one template cache and the class's const-body
  cache entries (`Citry._evict_component_cache`); `reset_files()` clears
  JS/CSS and fires `on_files_reset`.

**Usage:**

```python
app = Citry(dirs=["/proj/components"])

class Card(Component):           # /proj/components/card/card.py
    citry = app
    template_file = "card.html"  # found next to card.py
    js_file = "card.js"
    css_file = "card.css"

    class Dependencies:
        js = ["vendor/*.js"]
        css = {"all": "theme.css", "print": "print.css"}

Card.get_template().source       # file content, hooks applied
Card.get_dependencies().js       # merged, absolute paths, bases-first
```

### Slot resolution at `<c-slot>` and the `on_slot_rendered` hook (`nodes/__init__.py`, `extension.py`)

**What:** `SlotNode.render` resolves the slot site: name (static, `c-name`,
or via `c-bind`; missing name means `"default"`), `required` (static flag or
dynamic `c-required`), and every remaining attribute as slot data (`c-`
prefix dropped from evaluated keys, the same rule as component kwargs; data
resolves per render of the site, so a slot in a loop passes per-iteration
data). It then invokes the fill the component received, or its own body as
the fallback, and threads the result through the new `on_slot_rendered`
extension hook. This completes [`slots.md`](slots.md): slots work end to end
through templates alone, and the README's slot examples are tests.

**Why:** This is the consumption half of the slot system; collection (the
earlier entry) produced the Slots, this renders them at their insertion
points.

**Design decisions:**
- **One invocation path.** The fill and the fallback are both Slots, invoked
  with ``(data, fallback)``. On a hit, the slot's own body is wrapped as the
  fallback handle; on a miss, that same wrapper IS the rendered slot (with
  ``fallback=None``). This mirrors django-components' unfilled path (which
  also wraps the body as a Slot) and gives `on_slot_rendered` a `Slot` in
  both cases.
- **Scoping rules hold at the site.** The fill renders against the scope it
  closed over at collection (the writer's); the fallback renders against the
  current context, as if the `<c-slot>` tags were not there. Passthrough
  slots and slots inside slot fallbacks fall out with no extra code.
- **Required is render-time.** Only a *rendered* slot can complain: a
  required slot in an untaken branch never errors (django-components
  parity), and the error carries a `difflib` "did you mean" hint over the
  fills the component received.
- **`on_slot_rendered`** follows the established manager patterns: a frozen
  `OnSlotRenderedContext` (`citry`, `component`, `slot`, `slot_name`,
  `slot_node`, `slot_is_required`, `result`), dispatched with
  `emit(result="map", field="result")`, so a returned render part replaces
  the output and a raise propagates. There is no `slot_is_default` field:
  the default slot is the one named `"default"`.

**Usage:**

```python
class Modal(Component):
    template = """
        <div class="modal">
          <main><c-slot /></main>
          <footer><c-slot name="actions" required /></footer>
        </div>
    """

class Page(Component):
    template = '''
        <c-modal>
          <c-fill name="default"><p>Are you sure?</p></c-fill>
          <c-fill name="actions"><button>OK</button></c-fill>
        </c-modal>
    '''
```

### Parse-time validation of component usage (`citry/tag_rules.py`, `Citry._tag_rules`)

**What:** A component's `Kwargs`/`Slots` declarations become parser
`user_rules`: every template parsed under a `Citry` instance validates its
component tags against the registered components' declarations, so an unknown
kwarg attribute, a missing required kwarg, an unknown `<c-fill>` name, or a
missing required slot fails at template compile time (the parent's first
render), with the Rust parser's existing checks and error messages. Covers
component templates and nested templates (`c-body="..."`).

**Why:** The runtime already rejects these (`Kwargs(**raw)` / `Slots(**raw)`
raise on unknown or missing fields); this moves the same error to where the
template is written. django-components cannot do this: its fills resolve only
at render time. Tracked as the follow-up in [`slots.md`](slots.md)
section 12, extended here to kwargs as well.

**Design decisions:**
- **Opt-in per dimension.** No `Kwargs` class = any attributes accepted; no
  `Slots` class = any fills; neither = no rules entry. The parse-time check
  never tightens beyond the runtime contract.
- **Derivation:** a no-default field is required; each kwarg allows its
  static and dynamic spellings as one mutually exclusive group
  (`["title", "c-title"]`); control-flow shorthand attributes
  (`c-if`/`c-elif`/`c-else`/`c-for`/`c-empty`) are always allowed. The
  parser's own escape hatches stay: `c-bind` bypasses attribute checks, and
  dynamic fill names defer per-name slot checks to runtime, so no template
  that could be valid at runtime is rejected.
- **Declaration styles match the runtime.** Fields are read via
  `util.misc.get_fields`, which understands dataclasses (the metaclass
  product), Pydantic v1/v2 models, and NamedTuples; Pydantic is recognized
  by its attribute protocol (`model_fields` / `__fields__`) without being
  imported, so it stays out of citry's dependencies. An unrecognized style
  means "undeclared" (no rules), never rejection. In step, `to_dict` gained
  the same protocol support, so a Pydantic `template_data()` return or
  input instance normalizes like a dataclass one.
- **Case-insensitive matching.** The parser's `user_rules` lookups now
  lowercase the tag name (a small Rust change), so `<c-MyCard>` validates
  against the rules keyed `c-mycard`/`c-my-card`, consistent with how
  component tags resolve everywhere else. Rule keys must be lowercase.
- **Cached per `Citry` instance** (`_tag_rules()`, internal), invalidated on
  register/unregister/clear. Rules are built at parse time (first render),
  so components declared after the consuming class but before its first
  render are still seen.

**Usage:**

```python
class Card(Component):
    template = '<div>{{ title }}<c-slot name="header" /></div>'

    class Kwargs:
        title: str          # required
        size: int = 10      # optional

    class Slots:
        header: SlotInput   # required
        footer: "SlotInput | None" = None

# Each of these now fails at the parent template's parse:
#   <c-card title="x" bogus="1">...   unknown kwarg
#   <c-card>...                       missing required `title`
#   <c-fill name="bogus">             unknown slot
#   (no header fill)                  missing required slot
```

## Impl notes (things to be done)

- DO NOT PASS CONTEXT BETWEEN NODES. ONLY PROPS AND SLOTS.
  - See `monkeypatch_template_render` in `django_monkeypatch.py`
- `_STRATEGY_CONTEXT_KEY` in context -> No longer applicable! `_STRATEGY_CONTEXT_KEY`
  is now something that's passed to the CitryElement at rendering, and should be
  available throughout the render (or at minimum at render root), so no need to pass it down
  via Context.
  - See `_template_render` in `django_monkeypatch.py`
- Dropped the `@register()` decorator - duplicate (`@register("my_component", registry=my_reg)`)
- Dropped the global default registry `registry` (`from django_components import registry`)
  - Now lives under the default Citry obj - `citry.registry`.
- Dropped ComponentRegistry.settings
- Dropped ComponentRegistry.library - Django-specific
  - NOTE - when updating DJC onto Citry, make it a 2-pass flow -> first render as django template,
    then as citry. Thus, the new DJC will NOT have to handle Django library mgmt and similar.
- Registry.clear - all entries must go through unregister to trigger extension hooks
- un/register in DJC will be tricky. See _register_to_library in `component_registry.py`
- Dropped context_processors_data
- Dropped tag formatters entirely

### Dynamic component and dynamic HTML element (`citry/components/dynamic.py`, compiler, registry)

**What:** The `<c-component is="...">` built-in (render the component named
by `is`: a registered name or a `Component` class) and its new sibling
`<c-element is="...">` (render a plain HTML element whose tag name is decided
at render time). Full design, alternatives, and the DJC surface table live in
[`dynamic_component.md`](dynamic_component.md); this entry is the summary.

**Why:** `<c-component>` migrates DJC's `DynamicComponent`. `<c-element>`
replaces a capability Django got for free from text templates
(`<{{ tag_name }}>`), which V3's structural parsing cannot express; the
immediate driver is the benchmark Form component's div/table/ul switch
([`benchmarking.md`](benchmarking.md) feature B).

**Design decisions:**

- **Two tags, one target kind each** (no Vue-style polymorphic fallback): a
  misspelled component name errors loudly instead of shipping a bogus
  element, and no known-element list or settings are needed anywhere.
  `<c-element>` accepts any tag name, the same trust statically written HTML
  gets, so custom web components need no configuration.
- **Both are transparent built-ins** (the `<c-provide>` pattern), registered
  as `component` / `element`; both names joined `BUILTIN_COMPONENT_NAMES`.
- **Static forms compile away** (`compiler.rs`): `<c-component is="X">`
  rewrites to `<c-X>` (pre-existing, now tested), `<c-element is="div">`
  (no fills) rewrites to the literal element. `is` + `c-is` together is now
  a compile error on both tags.
- **`<c-element>` is one generic class**, not a synthesized class per tag
  name: the open/close tags are computed `Markup` values in a fixed template
  (`{{ open }}<c-slot />{{ close }}`), with attributes resolved through the
  shared `attrs.py` helpers and the `on_attrs_resolved` hook for parity with
  statically written elements (parity locked by tests).
- **`HTML_VOID_ELEMENTS` is now exported** from
  `citry_core.template_parser`, single-sourced from the Rust parser, for the
  void-elements-reject-children check.
- Named fills on `<c-element>` are parse errors (Rust slot rules); the
  dynamic spellings are rejected at render. Nested-template attribute values
  are rejected on the dynamic path (supported on the static path).
- Known limitation, measured: *chained* dynamic wrappers (a dynamic target
  whose template is again a dynamic tag) add stack frames per level; chains
  of 100 work, 200 hit the recursion limit. Realistic chains are a handful
  deep; the documented fix, if ever needed, is returning a
  `DeferredComponent` from the wrapper.

**Usage:**

```html
<c-component c-is="table_comp" c-rows="rows">
  <c-fill name="pagination"><c-pagination /></c-fill>
</c-component>

<c-element c-is="form_content_tag" class="form-content">
  ...children...
</c-element>
```

### First benchmark numbers: citry vs django-components vs Django (`benchmarks/`, `tests/test_benchmark_*_small.py`)

The first cross-engine rendering numbers, from the small benchmark scenario
(the django-components Button benchmark, vendored and ported per
[`benchmarking.md`](benchmarking.md)). Three engine rows render the same UI:
vanilla Django templates, django-components, and the citry port. Each cell is
the median of 5 fresh-process rounds, run by `benchmarks/compare.py`.

Measured 2026-06-12 on an Apple M4, Python 3.13.12; django 6.0.6,
django-components 0.151.0, citry 0.1.0 (citry_core 1.3.0, release build).
Ratios vs the `django` row. Relative values only; never compare across
machines, runs, or build profiles.

| engine | startup | import | first | subsequent |
|---|---|---|---|---|
| django | 75.35 ms (1.00x) | 71.45 ms (1.00x) | 1.11 ms (1.00x) | 39.5 us (1.00x) |
| django-components | 72.47 ms (0.96x) | 72.05 ms (1.01x) | 1.44 ms (1.29x) | 206.6 us (5.23x) |
| citry | 25.96 ms (0.34x) | 26.08 ms (0.37x) | 866.6 us (0.78x) | 58.9 us (1.49x) |

What the numbers say about the migration so far:

- The Django-free core pays off immediately at startup: citry imports and
  starts about 3x faster than the Django stack.
- Repeat renders are about 3.5x faster than django-components, and ~1.5x
  slower than a bare Django template. That remaining gap is the component
  machinery itself (per-render component construction, slot resolution, id
  marking), which a bare template simply does not do.
- The small scenario has no Const variant: a single Button computes everything
  it renders from its inputs, so there is no render-invariant literal to mark.
  The Const optimization gets its fair test in the large scenario (now ported,
  35 components), and even there a correct per-component `Const` pass shows no
  measurable benefit, because a real project page is mostly loops over dynamic
  data; the full picture is in [`benchmarking.md`](benchmarking.md) section 11.

Later snapshots go to the benchmarking design doc's results log
([`benchmarking.md`](benchmarking.md) section 11); `benchmarks/README.md`
always carries the latest table with the how-to-reproduce context.

### The `on_render` hook, error tracing, and `<c-error-fallback>` (`citry/component_render.py`, `citry/util/exception.py`, `citry/components/error_fallback.py`, `citry_core/safe_eval/error.py`)

**What:** One work package, four parts (full design in
[`on_render.md`](on_render.md)): the per-component `Component.on_render()`
hook in plain and generator form; error bubbling up the component tree;
render-path error tracing (component path + underlined template snippet in
error messages); and the `<c-error-fallback>` built-in error boundary built
on top. Public surface: `Component.on_render()`, the `RenderReplacement` and
`OnRenderGenerator` type aliases, `citry_core.safe_eval.format_error_with_context`
(previously private), and the reserved `error-fallback` component name.

**Why:** Migrates djc's `on_render_before`/`on_render`/`on_render_after`
hooks, generator driving, error-path tracing, template-position errors, and
`ErrorFallback` (the to-migrate rows in the `component.py`,
`component_render.py`, `node.py`, `util/` and `components/` tables above).

**Design decisions:**

- **One hook, wrapping rather than being the renderer.** djc's default
  `on_render` *is* `template.render(context)`; citry's framework owns body
  building (const precomputing, caches, hooks), so the hook only observes and
  replaces output. `on_render_before`/`on_render_after` dropped
  (`template_data` and the generator's post-yield phase cover them);
  re-addable additively if ever needed.
- **No lambda yields.** djc users yield `lambda: template.render(context)`
  so the framework can catch errors; citry renders and routes errors through
  the drive loop anyway, so a bare `yield` means "render my template" and
  the yield receives the settled `(CitryRender | None, error)`. The live
  render object, never a string, keeps the object pipeline intact.
- **Multiple yields without version bookkeeping.** djc tracks
  `(component_id, version)` pairs and an ignore set to skip stale string
  fragments; citry swaps the output object at the component's recorded
  position and re-queues its finalize. Stale work cannot exist.
- **Error bubbling is stack unwinding.** The drive-loop stack is pushed
  depth-first, so everything above a component's finalize is exactly its
  pending subtree work; popping to the nearest finalize discards the dead
  output's work and delivers `(None, error)` to the nearest enclosing
  component (its generator first, then extensions'
  `on_component_rendered`). Replaces djc's `ErrorPart` queue items.
  Divergence: the *failing* component's own extension hook does not fire
  (rendering never completed); its own *generator* does receive its own
  body-render failure, which is what lets a boundary guard its own
  synchronously-rendered slot content.
- **Error paths from the instance chain.** Component frames come from
  `parent` links at the failure site, not threaded `full_path` lists; slot
  frames are added at `SlotNode`'s fill/fallback invocation. Same
  `_components` attribute as djc for interop. Deliberate drops: djc's stdout
  print for args-less exceptions; slot frames for deferred-from-fill
  descendants.
- **Template snippets via the shared formatter.** djc's
  `_format_error_with_template_position` already existed in citry_core as
  safe_eval's `_format_error_with_context`; it is now public and applied per
  failing node (every compiler-emitted node carries `source` + `position`),
  with its own once-per-error marker, so an expression error shows
  safe_eval's expression caret *and* the template lines. Strictly broader
  than djc's tag-signature-TypeError-only use.
- **`<c-error-fallback>`** is a regular (non-transparent) built-in whose
  whole behavior is one `on_render` generator: yield, and on error return
  the `fallback` attribute or invoke the `fallback` fill with the error as
  slot data (no template re-render, unlike djc). Fills cannot mix with other
  content, so guarded content moves into the `default` fill when a fallback
  fill is given. A failing fallback bubbles to the next boundary up.

**Usage:**

```html
<c-error-fallback fallback="Oops, something went wrong">
  <c-user-table />
</c-error-fallback>
```

```py
class Guarded(Component):
    template = "..."

    def on_render(self):
        result, error = yield          # result: CitryRender | None
        if error is not None:
            return "<p>fallback</p>"   # swallow the error
        return None                    # keep the rendered output
```

### Dependency rendering, phase 1: core plumbing (`citry/cache.py`, `citry/extensions/dependencies/types.py`, `component.py`, `citry.py`)

**What:** The foundation pieces of the dependency-rendering design
([`dependencies.md`](dependencies.md) section 16 phase 1): the pluggable
cache backend, component class identity, the `Script`/`Style` dependency
objects, and the `js_data()`/`css_data()` data methods. No emission yet;
nothing reaches the rendered page until phase 2.

**Why:** Each piece is an independently testable prerequisite of the
collection/emission phases, and three of them resolve long-standing ❓ rows
in this doc (cache backend protocol, `hash_comp_cls`/class id, and where
processed JS/CSS lives).

**Design decisions:**

- **`CitryCache` protocol** (`citry/cache.py`): four string-valued methods
  (`get`/`set`/`delete`/`has`), so any store adapts in minutes.
  `Citry(cache=...)` accepts a backend object or an import string (resolved
  like extension specs; a class is instantiated with no arguments); `None`
  builds a per-instance `InMemoryCache` (unbounded by default, optional
  `max_entries` with least-recently-used eviction). The spec lives on
  `CitrySettings.cache`, the live backend on `Citry.cache`. `Citry.clear()`
  calls the backend's `clear()` when it has one (the protocol does not
  require it; a shared backend may not want a full wipe).
- **`Component.class_id`** is a property on `ComponentMeta` (so the user's
  class declaration is never rewritten), computed on first read and cached
  in each class's own `__dict__`: the class name plus the first 6 hex chars
  of the md5 of the full import path, djc's `hash_comp_cls` scheme.
  `Citry._classes_by_id` (weak values, filled at registration) backs
  `Citry.get_component_by_class_id()`, the reverse lookup the script
  endpoint will use.
- **`Script`/`Style`** (`citry/extensions/dependencies/types.py`; the
  extension module became a package): url-or-content exclusive, validity
  checked at render (including the no-own-end-tag-in-content rule), equality
  and hashing by url-or-content so `dict.fromkeys` dedupes keeping first
  occurrence, `to_json`/`from_json` as the cache storage format, and the
  IIFE wrap rule for classic inline JS. Divergence from djc (its own
  TODO_V1): they are accepted **directly** as `Dependencies` entries
  (`_resolve_entry` passes them through), instead of djc's render-to-string
  + HTMLParser re-parse round trip, which is not ported.
- **`js_data(kwargs, slots)` / `css_data(kwargs, slots)`** mirror
  `template_data` (kwargs+slots only; no args, no context). Optional
  `JsData`/`CssData` schema classes ride the same metaclass auto-dataclass
  conversion and the same validation (declaring a schema with required
  fields obliges the method to supply them). All three data methods now
  normalize through one `_normalize_data` helper in `component_render.py`,
  and `on_component_data` carries `template_data` + `js_data` + `css_data`
  (closing the TODO in [`extensions.md`](extensions.md) section 7.5).

**Tests:** `tests/test_cache.py`, `tests/test_class_id.py`,
`tests/test_deps_types.py`, `tests/test_js_css_data.py`.

### Dependency rendering, phase 2: collection and document emission (`citry/extensions/dependencies/`, `extension.py`, `serialize.py`, `components/js_css.py`)

**What:** A page rendered through citry now carries its components' JS and
CSS: every rendered component's `Component.js`/`css` and `Dependencies`
entries are collected during the render and placed into the final HTML at
serialize time. The `<c-js>`/`<c-css>` built-in tags mark explicit spots;
without them CSS goes before the first `</head>` and JS before the last
`</body>`. Phase 2 of [`dependencies.md`](dependencies.md).

**Why:** This is the emission half of django-components #1144, rebuilt on
the object pipeline: djc transported "which components rendered" as
`<!-- _RENDERED -->` comments regex-extracted from HTML; citry carries tiny
`DependencyRecord` tuples on `CitryContext.extra` and never re-parses
rendered output.

**Design decisions:**

- **Collection** (`on_component_data`): the extension appends a record
  (class id + render id) to the render's `CitryContext.extra`, but only for
  components that actually carry assets. The hook context gained a
  `context` field for this; the context is now built just before the hook
  fires (provides are snapshotted right after, timing unchanged).
- **Bubbling is extension-owned**: the render pipeline's
  `_merge_dependencies` seam now only fires the new core `on_render_context_merge`
  hook; each extension merges its own slice of `extra` with its own policy.
  The core no longer copies `extra` wholesale (last-writer-wins was the
  wrong default for everything).
- **`on_serialize` core hook**: fires at the end of `serialize()` with the
  joined HTML (threaded), the root context, the strategy arguments, and the
  placeholder map. All placement lives in the extension's implementation
  (`emission.py`); the core knows nothing about JS/CSS.
- **Placeholders**: `<c-js>`/`<c-css>` are transparent built-ins whose
  `on_render` returns a core `Placeholder` part. The serializer renders each
  as a `<template c-render-id="deps:js:N">` tag (the same machinery child
  components ride), reports id -> exact-text to the hook, and the extension
  fills the first occurrence per kind and removes the rest (divergence from
  djc, which duplicated tags into every occurrence).
- **Strategies**: `serialize(deps_strategy=..., deps_position=...)`,
  implementing djc's own TODO that prepend/append are positions, not
  strategies. `document` and `simple` are identical until the client
  runtime lands; `fragment` raises `NotImplementedError`; `ignore` still
  removes the internal placeholders. With no `<head>`/`<body>` and no
  placeholder, CSS is prepended and JS appended rather than silently
  dropped (djc dropped them; flagged divergence).
- **Emission order**: per record, `Dependencies` entries then the
  component's own scripts; page-wide, core kind first, then all extras,
  then all component scripts, deduplicated first-seen via the
  `Script`/`Style` url-or-content equality. `Component.on_dependencies`
  (classmethod, per rendered instance) and the extension-owned
  `on_dependencies` emit hook (the first real custom hook) adjust the
  lists.
- **Entry emission**: resolved local files arrive as `Path` objects from
  the loading half (the type distinguishes a file from a URL-like string
  such as `/static/x.css`) and are inlined, unwrapped, so a vendored lib's
  top-level `var` stays global; `Component.js` is IIFE-wrapped; URL strings
  become `src`/`href` tags; `Script`/`Style` objects pass through;
  pre-rendered tags emit verbatim. The CSS media type from the
  `Dependencies` dict becomes the tag's `media` attribute (omitted for
  `"all"`).

**Usage:**

```py
class Table(Component):
    template_file = "table.html"
    js_file = "table.js"          # inlined once per page, however many tables render
    css_file = "table.css"

    class Dependencies:
        js = ["https://cdn.example.com/chart.js", "helpers.js"]   # URL + local file
        css = {"print": "print.css"}
```

```html
<html>
  <head><c-css /></head>
  <body><c-table /><c-js /></body>
</html>
```

**Tests:** `tests/test_deps_emission.py`; the merge-hook contract in
`tests/test_deferred_render.py` (`TestDepsBubble`).

### Dependency rendering, phase 3: JS/CSS variables and the client runtime (`extensions/dependencies/`, `client/citry.js`, `util/css.py`)

**What:** Per-render data now reaches the browser. `js_data()` results are
delivered to the component's `$onComponent` callback per instance;
`css_data()` results become CSS custom properties scoped to the instance's
elements. The pieces: hashed variables scripts, the `data-ccss-<hash>` root
markers, the `$onComponent` source transform, citry's own client-side
dependency manager, and the page manifest that ties them together. Phase 3
of [`dependencies.md`](dependencies.md).

**Why:** This is djc's JS/CSS-variables mechanism rebuilt on citry's
pipeline: the association between an instance and its data rides the
`data-cid` markers the serializer already stamps (djc had to post-process
HTML to add them), and the per-instance call list rides the collected
records rather than parsed HTML comments.

**Design decisions:**

- **Hashing**: a `js_data()`/`css_data()` result is JSON-serialized (with
  `Const` proxies unwrapped) and hashed (md5, 6 hex chars); the generated
  script/stylesheet is cached under `citry:<class_id>:js|css:<hash>`, so
  identical data, across instances and renders, is generated once and sent
  to the browser once. The hashes ride the `DependencyRecord`.
- **CSS variables** need no JavaScript: a generated stylesheet
  `[data-ccss-<hash>] { --name: value; }` (values via the ported
  `serialize_css_var_value`) plus the marker attribute on the instance's
  root elements. The marker rides the new **root-marker seam**:
  the internal `CitryContext._add_root_markers` / `_get_root_markers`,
  storing under the namespaced `extra["citry"]["root_markers"]`, which serialization splices
  next to `data-cid-<id>`; the future scoped-CSS work (#1230) is the second
  intended user. Generated only when the class has CSS; works under both
  `document` and `simple`.
- **JS variables** are delivered as a script calling
  `Citry.manager.registerComponentData(class_id, hash, data)`, with the
  JSON riding as base64 so no value can break out of the script tag.
  Generated only when the class's JS registers a callback.
- **`$onComponent`** is expanded once per class, when the class script is
  cached: `$onComponent(` becomes
  `Citry.manager.registerComponent("<class_id>", `. The callback receives
  `{id, els, data}` per instance (`els` are the elements carrying the
  instance's `data-cid-<id>` marker).
- **The manifest** is a `data-citry` JSON script tag (schema: `markLoaded`
  URLs, `fetch` descriptors for fragments, `calls` triples), emitted, with
  the runtime, only when some rendered component used `$onComponent`; a
  page without per-instance JS stays as lean as `simple`. Built after the
  `on_dependencies` hook, so URLs added there are marked as loaded too.
- **The runtime** (`client/citry.js`, shipped as package data and inlined
  for now; a `<script src>` once a web integration is mounted) holds the
  loaded-URL sets, the callback/data registries, and an in-order pending
  queue, so the manifest, component scripts, and data scripts may arrive in
  any order; a MutationObserver picks up manifests inserted later (the
  fragments seam). Plain readable JS today; the
  `packages/js/citry-client` TypeScript + minification build is deferred to
  the packaging work.
- **`document` vs `simple` now differ**: `simple` is the no-JS-runtime mode,
  so JS variables and component calls are document-only. Flagged divergence
  from djc, where `simple` emitted manager-calling variables scripts with no
  manager on the page.

**Usage:**

```py
class Table(Component):
    template = "<table>...</table>"
    css = ".table-row { color: var(--row-color); }"
    js = "$onComponent(({ els, data }) => { console.log(els, data.rows); });"

    def js_data(self, kwargs, slots):
        return {"rows": kwargs["rows"]}

    def css_data(self, kwargs, slots):
        return {"row-color": kwargs["color"]}
```

**Tests:** `tests/test_deps_vars.py`.

### Dependency rendering, phase 4: URLs, web integrations, and fragments (`citry/util/routing.py`, `citry/contrib/`, `extensions/dependencies/routes.py`)

**What:** Citry's endpoints are now mountable into any web framework, and
HTML fragments work end to end: a partial rendered with
`serialize(deps_strategy="fragment")` carries a JSON manifest of script URLs
the client-side manager fetches, each once per page however many fragments
need it. Phase 4 of [`dependencies.md`](dependencies.md).

**Why:** Fragments are the reason the whole URL layer exists: a fragment
cannot put tags into `<head>`, so its dependencies must be fetchable. The
layer is split so nothing host-shaped lives in citry: a neutral route table,
neutral handlers, and adapters of a dozen lines each.

**Design decisions:**

- **`URLRoute`** (`citry/util/routing.py`): path + handler-or-children +
  `name` + an explicit `methods` field (deviation from djc, which left
  method checks to each Django view). Paths use `{param}` placeholders; a
  small first-wins router (regexes cached per pattern) backs the generic
  adapters, so define more specific patterns first. Handlers take
  ``(request, **path_params)`` and return a neutral `RouteResponse`.
- **`Extension.urls`** (list or property) feeds `Citry.urls`: built-in
  extensions' routes mount at the prefix root (`cache/...`, `citry.js`),
  user extensions' under `ext/<name>/` so they cannot collide. The manager
  now sets a `citry` back-reference on every extension instance, which is
  how route handlers (and anything else extension-owned) reach engine state.
- **The endpoints** (`routes.py`): `cache/{class_id}.{script_type}` and the
  vars variant serve the cached `Script`/`Style` content with the right
  mime type; class-level scripts repopulate the cache on a miss (the
  phase-1 lazy-repopulation rule, now actually exercised over HTTP);
  `citry.js` serves the client runtime.
- **The mount contract**: an adapter's `mount()` registers the routes and
  records the prefix on the instance (`Citry.set_mounted_prefix`, the
  escape hatch for render-only processes); `Citry.build_url` raises with
  guidance when nothing is mounted. Adapters: a dependency-free ASGI app
  (handles both root-path conventions hosts use when mounting), the WSGI
  twin, and `citry.contrib.fastapi.mount` sugar (one call does both steps;
  works for Starlette too). The FastAPI adapter is what the test suite
  drives end to end with `TestClient` (fastapi/httpx are dev-only deps,
  mirrored in the root pyproject per the monorepo convention).
- **Fragments**: nothing is inlined; the output ends with a pre-loader (load
  the runtime if the page lacks it, then remove yourself) and a manifest
  whose `fetch` lists are `{tag, attrs, content}` descriptors: cache URLs
  for component and variables scripts, plain URLs for URL entries, inline
  content for local-file entries (which have no URL). A fragment whose
  components carry no assets serializes plain, with no pre-loader and no
  mounted-integration requirement; one with assets raises a pointed
  `RuntimeError` when nothing is mounted. Pre-rendered (`__html__`)
  entries are rejected loudly in fragments: an opaque tag string cannot
  become a descriptor.
- **Mounted documents get better**: the runtime is served by URL
  (browser-cacheable) instead of inlined, and the manifest marks the
  inlined component/variables scripts' *cache URLs* as loaded, so a
  fragment inserted into the page later fetches nothing it already has.
  Unmounted documents keep the inlined runtime, so the zero-configuration
  flow is unchanged.

**Usage:**

```py
from fastapi import FastAPI
from citry.contrib.fastapi import mount

app = FastAPI()
mount(app, my_citry)               # serves /citry/cache/..., /citry/citry.js

@app.get("/table-fragment")
def table_fragment(rows: int):
    html = Table(rows=rows).render().serialize(deps_strategy="fragment")
    return HTMLResponse(html)
```

**Tests:** `tests/test_deps_urls.py` (routing, mount contract, endpoint
logic, the WSGI app), `tests/test_deps_fragments.py` (fragment + mounted
document flows), `tests/test_contrib_fastapi.py` (end to end over
`TestClient`, including "every URL a fragment references is servable").

### Dependency rendering, phase 5: more hosts, more caches, served local files (`citry/contrib/`, `routes.py`, `emission.py`)

**What:** The breadth pass over the integration surfaces: Flask and Django
join FastAPI as supported hosts, Redis/diskcache/Django-cache backends join
the in-memory default, and local-file ``Dependencies`` entries can be served
at fingerprinted URLs instead of inlined. Phase 5 of
[`dependencies.md`](dependencies.md); with it, the dependency-rendering
design is fully built (the TS/minification build of the client runtime and
the user-facing docs remain, deliberately).

**Design decisions:**

- **`citry.contrib.flask.mount`** wraps the app's `wsgi_app` callable with a
  prefix dispatcher (the standard WSGI sub-mount convention: prefix into
  `SCRIPT_NAME`, remainder in `PATH_INFO`), so it needs no Flask import and
  works for any framework exposing that attribute.
- **`citry.contrib.django`**: `urlpatterns(citry_instance, prefix=...)`
  converts `Citry.urls` to Django patterns; Django's `path()` syntax cannot
  express two parameters in one segment (the dotted cache routes), so those
  fall back to `re_path` over the same compiled citry pattern. Views check
  `route.methods` and translate `RouteResponse`. `DjangoCache` adapts any
  configured Django cache to the `CitryCache` protocol, so a Django project
  reuses the store it already runs. Citry owns this module (not
  django-components), per the earlier decision that plain citry must work
  with Django regardless of django-components' future.
- **`citry.contrib.caches`**: `RedisCache` and `DiskCache` in one module,
  each wrapping a client object the user constructs (`redis.Redis(...)`,
  `diskcache.Cache(dir)`), so citry imports nothing from the host packages
  and the adapters are testable with fakes. Redis expiries are whole
  seconds, rounded up so a short ttl never means "expire immediately".
  (Deviation from the design sketch, which had one module per backend; one
  import-free module is simpler.)
- **`local_files = "serve"`** (9.4): a setting on the `Dependencies` config,
  per component or global via
  `extensions_defaults={"dependencies": {...}}` (the first real use of the
  extension-config default layers). The file's content is cached under its
  hash and emitted as `asset/<hash>.<ext>` on a new endpoint; the hash IS
  the fingerprint, so a changed file gets a new URL and the old one can be
  cached forever. Falls back to inlining when no integration is mounted
  (inline is always correct), and composes with fragments (served entries
  become URL descriptors the manager de-duplicates).
- `URLRoute` and `RouteResponse` are exported from the package top level:
  extension authors declaring `Extension.urls` need them.

**Tests:** `tests/test_contrib_hosts.py` (Flask mount via a fake WSGI host,
Django patterns/views/cache against real Django, cache adapters against
fakes), `tests/test_deps_fragments.py` (`TestServedLocalFiles`).

### Template globals (`citry/settings.py`, `citry/citry.py`, `citry/component_render.py`, `citry/citry_element.py`)

**What:** Variables exposed to every component's template without being returned
from each `template_data()`. Two layers: instance-wide globals, set at
construction with `Citry(template_globals={...})` or changed on a live instance
through `citry.template_globals` (a plain dict); and a per-render override,
`element.render(template_globals={...})`, for one render only. Both are merged
into every component's template variables on render, lowest precedence first:
instance globals, then the per-render override, then the component's own
`template_data` (which wins), so globals act as defaults. Full design:
[`template_globals.md`](template_globals.md).

**Why:** Citry's template variables deliberately do not cross a component
boundary (each component gets fresh variables from its own `template_data`), so a
value many components need (a site name, the current user, a feature flag)
otherwise has to be returned from every `template_data()`, or injected by a
hand-written extension's `on_component_data`. `template_globals` is the
first-class, instance-wide channel for that. It is citry's replacement for
django-components' `context_processors_data` (which was dropped), without that
feature's coupling to a request object.

**Design decisions:**
- **Seed on settings, live copy on the instance.** `CitrySettings.template_globals`
  holds the construction-time seed (the frozen settings stay immutable); the
  instance keeps a separate live `dict` copied from it. Mutating the live dict
  never touches the seed, and the default `citry` instance, created at import
  before user code runs, can still be configured afterward. This mirrors how
  `cache` and `id_generator` resolve a settings spec to a live attribute.
- **A plain dict, not a wrapper class.** Single dict operations are atomic under
  the GIL, so a wrapper guarding mutations earned nothing over a plain dict for
  the instance-wide store, and `set` / `update` / `del` / `clear` are already the
  vocabulary the feature needs.
- **Merged after schema validation.** The overlay happens after `_normalize_data`
  validates a component's own `template_data` against its declared `TemplateData`,
  so a global key need not appear in that schema and never trips its
  unexpected-field check. The merge is skipped when the instance has no globals,
  so an instance without any pays nothing.
- **Component wins on a clash.** `{**globals, **template_data}`: the most specific
  scope (the component) overrides the ambient default, the way a local value
  shadows an inherited one elsewhere.
- **Per-render override via a context variable.** `render(template_globals=...)`
  is render-wide and must reach nested children, embedded elements, and slot
  content, so it rides a `contextvars.ContextVar` that `render_impl` sets for the
  render and resets on exit, instead of being threaded through every node and
  slot. `_render_one` reads it at the merge site, layering it between the
  instance globals and the component's own data. Each thread or async task keeps
  its own value. Threading it explicitly was rejected: about ten hot-path call
  sites, easy to silently miss one.

**Usage:**

```python
from citry import Citry, Component

app = Citry(template_globals={"site_name": "Acme"})
app.template_globals["year"] = 2026          # add or change on a live instance

class Footer(Component):
    citry = app
    template = """
    <footer>{{ site_name }} {{ year }}</footer>
    """

Footer().render(template_globals={"year": 2027})   # for this render only
```

**Tests:** `tests/test_template_globals.py`. Instance globals: visible without
`template_data`, reaches nested children, per-instance isolation,
post-construction and default-instance configuration, dict mutation, defensive
copy, component-wins precedence, schema bypass. Per-render override: visibility,
combining with and overriding instance globals, losing to component data,
reaching nested children / embedded elements / slot content, no leak to a later
render, no instance mutation.
