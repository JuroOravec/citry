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
   Until the citry equivalent of `@djc_test` exists, tests use plain
   pytest. Track test files that need updating once test isolation
   infrastructure is in place (see "Test files to revisit" in the
   implementation log below).

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
| [#1473](https://github.com/django-components/django-components/issues/1473) | Expression caching | Variable tracking (already in AST) enables memoizing expression results across renders when inputs are unchanged. |
| [#1337](https://github.com/django-components/django-components/issues/1337) | Lazy/streaming rendering | Rendering may be deferred; components produce futures or generators instead of synchronous strings. |
| [#1326](https://github.com/django-components/django-components/issues/1326) | Avoid double-parsing component body | Template parsing should be cached at the class level, not re-parsed per render. |

The render-output model (the three-phase `CitryElement` -> `CitryRender` ->
HTML pipeline, the `CitryContext` render-scoped state, and the JS/CSS dependency
flow that drives the struct shape) is captured separately in
[`rendering.md`](rendering.md). It is designed but not yet built: the current
skeleton still returns a `str` from `render_impl`.

The `Const()` (#1083), expression-caching (#1473), and render-body-caching
design (and its many edge cases) is captured separately in
[`constness.md`](constness.md). The const *flow* skeleton is built (a
transparent `wrapt.ObjectProxy`-based `Const` marker, detection, and a
`Citry`-scoped body cache keyed by const signature); the fold pass and phase-2
taint are parked.

### Component class

| Issue | Feature | Architecture impact |
|---|---|---|
| [#1195](https://github.com/django-components/django-components/issues/1195) | Phase out registered names, use class names directly | `Component()` takes a class, not a string name. Registry becomes optional. |
| [#1413](https://github.com/django-components/django-components/issues/1413) | Global `Components` instance for all state | A `Components()` instance scopes settings, registries, caches. Avoids module-level globals. Easier test isolation. |
| [#1240](https://github.com/django-components/django-components/issues/1240) | Template-only / class-less components | Components can be defined from a template file alone (no Python class). |
| [#1144](https://github.com/django-components/django-components/issues/1144) | `Component.Media` becomes an extension | CSS/JS management moves from the Component class to the extension system. |
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
| [#473](https://github.com/django-components/django-components/issues/473) | Define public API | citry gets a clean public API from scratch. |

---

## Node implementation groups

Nodes are the Python runtime classes the V3 compiler output instantiates.
**Implementation order: rendering core first, then nodes to fit it.**

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

| Tag | Purpose |
|---|---|
| `<c-provide>` | Dependency injection |
| `<c-js>` | JS dependency rendering |
| `<c-css>` | CSS dependency rendering |

---

## django-components file classification

**Every file is reviewed individually during migration.** The categories
below are a starting guide. Files marked "stays in django-components"
may still contain logic that splits between citry and Django.

### Component logic (migrate to citry, review case by case)

| File | Lines | Django coupling | Notes |
|---|---|---|---|
| `component.py` | 3657 | Heavy | Component class, metaclass, lifecycle. Core of citry. |
| `component_render.py` | 1444 | Heavy | Render pipeline, component tree. Core of citry. |
| `slots.py` | 1698 | Medium | Slot/fill system. Core of citry. |
| `extension.py` | 1557 | Light | Plugin/hook system. Core of citry. |
| `component_registry.py` | 718 | Light | Registry, weakrefs. Evolving (#1195). |
| `component_media.py` | 1290 | Medium | CSS/JS management. Will become extension (#1144). |
| `provide.py` | 175 | Light | Provide/inject. |
| `attributes.py` | 441 | None | HTML attribute merging. |
| `expression.py` | 135 | Medium | Template expression eval. |
| `context.py` | 50 | Medium | Context key management. |
| `constants.py` | 3 | None | Constants. |
| `types.py` | 7 | None | Type aliases. |
| `cache.py` | 50 | None | Component instance cache. |

### Primarily Django (stays, but review for splits)

| File | Lines | Notes |
|---|---|---|
| `app_settings.py` | 959 | Settings fields will split: some move to citry settings, some stay Django-specific. |
| `apps.py` | 121 | Django AppConfig. |
| `autodiscovery.py` | 111 | Django app discovery. |
| `finders.py` | 166 | Django static finders. |
| `library.py` | 69 | Django template Library. |
| `template_loader.py` | 32 | Django template loader. |
| `node.py` | 891 | Django template Node/BaseNode. Some concepts (tag parsing, parameter handling) may extract. |
| `tag_formatter.py` | 306 | `{% component %}` formatting. |
| `cache_tag.py` | 214 | Django `{% cache %}` integration. |
| `dependencies.py` | 1927 | JS/CSS rendering. Some dependency-tracking logic may extract. |
| `urls.py` | 18 | Django URLs. |
| `templatetags/` | - | Django template tags. |
| `commands/` | - | Django management commands. |
| `management/` | - | Django management. |
| `compat/` | - | Django compatibility. |

### Utilities (case by case during migration)

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

| Extension | Likely destination |
|---|---|
| `extensions/defaults.py` | Partial |
| `extensions/dependencies.py` | Django |
| `extensions/cache.py` | Partial |
| `extensions/view.py` | Django |
| `extensions/autodiscovery.py` | Django |
| `extensions/debug_highlight.py` | Django |

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

---

## citry package structure

```
packages/py/citry/
  pyproject.toml           # depends on citry-core, no Django
  citry/
    __init__.py            # Public API
    component.py           # Component class
    component_render.py    # Render pipeline
    registry.py            # Component registry
    extension.py           # Extension/hook system
    slots.py               # Slot/fill system
    provide.py             # Provide/inject
    media.py               # CSS/JS asset management (extension)
    context.py             # Rendering context protocol
    attributes.py          # HTML attribute helpers
    expression.py          # Expression evaluation
    cache.py               # Component instance cache
    types.py
    constants.py
    nodes/
      __init__.py
      expr.py              # ExprNode
      template.py          # TemplateNode
      attrs.py             # StaticHtmlAttr, ExprHtmlAttr, TemplateHtmlAttr
      control_flow.py      # IfNode, ForNode
      component.py         # ComponentNode
      slot.py              # SlotNode, FillNode
    components/
      __init__.py
      provide.py           # <c-provide>
      js.py                # <c-js>
      css.py               # <c-css>
    util/
      misc.py
      cache.py
      exception.py
      logger.py
      nanoid.py
      weakref.py
      css.py
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

### Test files to revisit

These test files use plain pytest and should be updated to use citry's
test isolation infrastructure (the equivalent of django-components'
`@djc_test`) once it exists.

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
- **`get_template_data(kwargs, slots, context)` signature.** Simplified
  from DJC's `get_template_data(self, args, kwargs, slots, context)`.
  No `args` parameter.
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

    def template_data(self, kwargs, slots=None, context=None):
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
- **`template_data(self, kwargs, slots, context)` stays explicit.**
  Even though `self.kwargs` could exist, passing kwargs and slots as
  method arguments keeps the signature clear and mirrors React/Vue's
  functional component pattern. Users see immediately what inputs are
  available without learning the full Component instance API. The
  `context` parameter will likely become internal.
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
skeleton; many DJC features (extensions/hooks, context snapshotting, deferred
rendering, JS/CSS media, provide/inject) are not yet ported.

**Design decisions:**
- **Class-level body generator (DJC #1326).** Parsing + compiling + `exec` of a
  template happens once per component class; the resulting `generate_template`
  function is cached on the class (`_template_body_generator`, via
  `_get_body_generator`). That expensive step is invariant for a template, so it
  runs once; calling the cached function yields a fresh node list each render.
  The cache lives in the class's own `__dict__`, so a subclass overriding
  `template` builds its own generator.
- **Generation decoupled from rendering.** `_compile_body_generator` (parse +
  compile + exec) is separate from `_render_body` (walk the node list, emit the
  string). This seam is where the parked const-folding cache will slot in.
- **No per-element body cache.** An earlier iteration cached the node list on
  the element; it was removed. Reusing an already-optimized body across renders
  is the job of the const-folding cache, not the element. The full const-folding
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

**What:** The plumbing for the const-folding feature: a `Const(value)` marker,
detection of const-marked context variables, a const signature, and a
`Citry`-scoped body cache keyed by `(component class, signature)`.

**Why:** Const-folding (DJC #1083) lets the engine reuse an optimized body for
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
- **No folding yet.** The cached body is the unoptimized node list, equivalent
  across signatures, so the cache provides the lookup structure but no speedup
  yet. Folding (replacing all-const nodes with their results) slots into the
  `_compile_body_generator` / `_render_body` seam later.
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

    def template_data(self, kwargs, slots=None, context=None):
        return {"cols": kwargs["cols"]}   # passes the marker through

# Same const signature -> same cache entry; a different value -> a new entry.
Card(cols=Const(3)).render()
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
