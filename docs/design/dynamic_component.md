# Design: dynamic components and dynamic HTML elements (`<c-component>`, `<c-element>`)

**Status (2026-06-11): implemented (design went through three review
rounds).** The built-ins live in `citry/components/dynamic.py`, the compiler
changes in `compiler.rs` (`C_COMPONENT_TAG` / `C_ELEMENT_TAG` arms), tests in
`tests/tag_compiler_dynamic.rs` (Rust) and `tests/test_component_dynamic.py`
(Python). This document specifies two sibling built-in tags that choose
their render target at render time:

- **`<c-component is="...">`** renders a *component* (a registered name or a
  class). This is the citry migration of django-components'
  `DynamicComponent`.
- **`<c-element is="...">`** renders a *plain HTML element* whose tag name is
  decided at render time. This is new relative to DJC: Django's text-based
  templates could write `<{{ tag_name }}>` directly, and citry's V3 syntax,
  being structural, cannot.

The two are deliberately separate (an earlier draft folded both into
`<c-component>` with resolution fallback; section 8, alternative D records
why that lost): each tag has exactly one target kind, so there is no
resolution order, no component-shadows-element ambiguity, and no settings
needed to police the boundary.

This is a migration item: it resolves the two ❓ rows in
[`citry_migration.md`](citry_migration.md) for `DynamicComponent` and the
`dynamic_component_name` setting. It is also "feature B" in
[`benchmarking.md`](benchmarking.md) section 6.3, where the large benchmark
scenario's Form component picks its content tag (div/table/ul) at render
time. For the transparent-built-in pattern both tags reuse see
[`provide.md`](provide.md); for how an element embedded in an expression
renders see [`rendering.md`](rendering.md); for slot pass-through see
[`slots.md`](slots.md); for the Const interactions see
[`constness.md`](constness.md). Operating rules: [`/CLAUDE.md`](../../CLAUDE.md).

---

## 1. Prior art (what was searched)

### In this repo

The headline: **the parse and compile layers already implement most of
`<c-component>`; the Python built-in does not exist, so the tag currently
fails at render time.** `<c-component c-is="x" />` parses, compiles to
`ComponentNode(name="component")`, and then `registry.get("component")`
raises `NotRegistered` because nothing is registered under that name.
`<c-element>` exists nowhere yet.

- **README.md:72** (the north star): `<c-component>` is one of the 12
  built-in tags, "Dynamic component", example `<c-component c-is="comp_name" />`.
  `<c-element>` is an addition to that list; the README gains its row when
  this ships (section 3).
- **`crates/citry_template_parser/src/constants.rs`**: `C_COMPONENT_TAG`
  (`:31`); parse-time attribute rules at `:184` (any attributes allowed, one
  of `is` / `c-is` / `c-bind` required); slot rules at `:195` (any slots
  allowed, none required). The comment at `:65` classifies it with
  `c-provide`/`c-js`/`c-css`: "practically just custom components", i.e. no
  grammar involvement. `<c-element>` follows the same pattern with its own
  rules entries. `HTML_VOID_ELEMENTS` lives at `:11`.
- **`crates/citry_template_parser/src/compiler.rs:265`**: a static-`is`
  rewrite already exists. `<c-component is="Xyz" ...>` is mutated at compile
  time into `<c-Xyz ...>` (the `is` attribute dropped), so the static case
  costs nothing at render. Anything else (dynamic `c-is`, or `is` via
  `c-bind`) compiles to a regular `ComponentNode` named `"component"`.
  Under this design's components-only semantics the rewrite is correct
  as-is; it gains one conflict check and a `<c-element>` mirror
  (section 5.2). **No test anywhere in the crate covers `c-component`**
  (checked all of `tests/` and inline `#[cfg(test)]`; zero matches outside
  `src/`).
- **`crates/citry_template_parser/src/parser.rs:2044`**: fill validation
  treats `c-component` as a component, so `<c-fill>` is allowed in its
  body; `<c-element>` needs the same listing.
- **`citry/nodes/__init__.py:649`** `ComponentNode`: resolves the class by
  name at render time via the registry (`component.citry.get(self.name)`,
  `:716`), turns attributes into kwargs with Const marking for literals
  (`:757`), and collects the body into slots (`:762`). This is the pipeline
  both built-ins plug into unchanged.
- **`citry/component_registry.py:39`** `BUILTIN_COMPONENT_NAMES` is
  `{"provide", "js", "css"}`. **Neither `"component"` nor `"element"` is
  reserved**: a user class can claim either name today and silently shadow
  the future built-ins. This design closes that gap. A related fact that
  shaped section 5.1: the metaclass registers *every* `Component` subclass
  with its `Citry` instance at class definition, so any design that mints
  classes at render time would pollute the registry (or need a
  registration opt-out).
- **`citry/components/provide.py`**: the established built-in pattern: a
  per-`Citry`-instance subclass created by `make_builtin_components`
  (`citry/citry.py:189`), `transparent = True`, behavior in `template_data`.
- **`citry/citry_render.py:175`** `_render_value`: a `CitryElement` found in
  an expression result renders in place, inheriting the provide/inject
  entries active at the site. This is the documented delegation seat
  `<c-component>` uses (`{{ target }}`, section 5.1). The same function's
  escape rules (`:195`: values are autoescaped; `markupsafe` `__html__`
  passes through) are what let `<c-element>` emit its open/close tags as
  pre-built `Markup` values.
- **`citry/component.py:241`** `transparent`: a transparent component's
  output joins the surrounding serialization frame and gets no
  `data-cid-<id>` marker of its own; hooks and dependency merging are
  unaffected.
- **`citry/attrs.py`**: `normalize_class` / `normalize_style` /
  `merge_attrs` / `format_attrs`, the shared attribute machinery that
  `ElementAttrsNode` uses for statically written elements and that
  `<c-element>` calls directly (section 5.1). `ElementAttrsNode.render`
  fires the `on_attrs_resolved` extension hook (`nodes/__init__.py:582`);
  `<c-element>` must fire the same hook for parity.
- **`citry/tag_rules.py`**: a component that declares no `Kwargs`/`Slots`
  contributes no parse rules, so both built-ins stay permissive at parse
  time; the Rust `TAG_ATTR_RULES` entries provide the required-attribute
  rules.
- **The serializer's HTML rendering rules** (CLAUDE.md gotchas): void
  elements stay compact (`<br/>`), non-void self-closing expand
  (`<div></div>`).
- **`citry_core.template_parser`** is wired (e.g. `tag_rules.py` imports
  `TagRules` from it), so exposing `HTML_VOID_ELEMENTS` to Python
  (section 5.3) follows an existing path.

### In `_djc_reference/` (django-components)

- **`components/dynamic.py`** (170 lines), the whole feature:
  - `is` accepts a registered name (str) or a `Component` class; also a
    component *instance*, but only because Django templates auto-call
    callables when resolving variables (`dynamic.py:142-149`), a quirk citry's
    `safe_eval` does not have.
  - Optional `registry` kwarg; without it, all registries are searched via
    the global `ALL_REGISTRIES` (`:151-164`).
  - All other args/kwargs/slots pass through to the target
    (`raw_kwargs.copy()` minus `is`/`registry`, `:111-132`).
  - Delegation happens in `on_render`, so the Django `Context` is already
    framed as if the target were a child (`:102-105`).
  - `_is_dynamic_component = True` marker (`:100`), read by upstream
    `slots.py:675` during slot rendering: the wrapper adds a component level
    that DJC's fill resolution must see through.
  - Registered as `"dynamic"`; the `COMPONENTS.dynamic_component_name`
    setting renames it on conflict (`:75-97`).
- **`tests/test_component_dynamic.py`** (upstream), the behavior contract:
  name as literal, name as variable, name via spread, class as value,
  invalid name raises `NotRegistered`, missing `is` raises `TypeError`,
  default slot, named slots, fills for slots the target lacks are silently
  unused, unexpected kwargs raise from the target's own signature, the
  rename setting, and the name-conflict error.

### Upstream concept: Vue

Vue's single `<component :is="...">` resolves a string **component-first**:
`resolveDynamicComponent` looks the name up among registered components
and, when nothing matches, returns the string itself, which the renderer
emits as a native (or custom) element, with only a dev-mode warning. The
collision (a component registered under an element's name shadows the
element) is resolved by Vue silently in the component's favor; the only
escape is the global `compilerOptions.isCustomElement` config. The
collision would bite citry harder than Vue: Vue components are registered
explicitly (often locally), while citry auto-registers every component
class under its lowercased name, so `class Table(Component)` shadows
`table` by default. Splitting into two tags removes the collision class
entirely instead of arbitrating it.

---

## 2. Scope and the decisions that shaped it

Decisions made with the maintainer:

1. **Two tags, one target kind each.** `<c-component>` resolves components
   only (exact DJC `DynamicComponent` scope); `<c-element>` renders plain
   HTML elements only. The earlier single-tag-with-fallback draft, and the
   settings it needed, are retired (section 8, alternative D).
2. **Both are transparent built-in components**, registered as
   `"component"` and `"element"`, exactly like `<c-provide>`. No new node
   class, no grammar change, no AST change. The Rust constants already
   classify `c-component` this way (`constants.rs:65`); `c-element` joins
   it. The name `element` was chosen over `tag` because reserving it is
   less likely to collide with user component classes (`Tag` is a common
   chip/label component name; `Element` is not a plausible component name).
3. **`<c-element>` accepts any tag name**, exactly like statically written
   HTML (where `<my-widget>`, and indeed a misspelled `<tabel>`, are legal
   and unvalidated). Custom web components therefore need no configuration.
   No known-element list exists anywhere in the design; the typo risk on
   an element name is the same risk static templates already carry, and a
   misspelled *component* name still errors loudly because `<c-component>`
   never falls back.
4. **`<c-element>` is one generic component, not a class per tag name.**
   The open and close tags are computed values in a fixed template
   (section 5.1), so there is no per-tag class synthesis, no cache to
   bound, and no render-time class minting (which would also have collided
   with the metaclass's auto-registration). An earlier draft synthesized a
   class per tag; section 8, alternative E records why that lost.
5. **The compiler's static-`is` rewrite stays as-is** (it is correct under
   components-only semantics), gains conflict checks, and gets a
   `<c-element>` mirror that compiles a static tag choice into a literal
   element (section 5.2).
6. **Dropped DJC surface**: the `registry` kwarg and the all-registries
   search (citry's registry is 1:1 with a `Citry` instance), the
   component-instance form (a Django-template auto-call artifact), and the
   `dynamic_component_name` rename setting (the names are reserved, so the
   conflict it solved cannot happen). Flagged per migration guiding
   principle 5 in the tracking table (section 6).

---

## 3. The template surface

```html
<!-- Component target, static name: resolved at compile time, zero
     render-time cost (rewritten to <c-MyTable>) -->
<c-component is="MyTable" c-rows="rows" />

<!-- Component target, dynamic: any expression yielding a registered name
     or a Component class -->
<c-component c-is="table_comp" c-rows="rows">
  <c-fill name="pagination"><c-pagination /></c-fill>
</c-component>

<!-- Element target, static: compiled to a literal <section> -->
<c-element is="section" class="hero">...</c-element>

<!-- Element target, dynamic: the benchmark Form case -->
<c-element c-is="form_content_tag" class="form-content" @click="onClick">
  ...body becomes the element's children...
</c-element>

<!-- Custom web components need no configuration -->
<c-element is="my-widget" data-x="1">...</c-element>

<!-- Spread form: `is` may arrive via c-bind on either tag -->
<c-component c-bind="{'is': 'MyTable', 'rows': rows}" />
```

Rules:

- On both tags, one of `is` / `c-is` / `c-bind` is required (the existing
  `constants.rs:184` rule for `c-component`; `c-element` gets the same).
- `is` together with `c-is` is a compile error on both tags (section 5.2).
- Every other attribute passes through to the target: as kwargs for
  `<c-component>`, as HTML attributes for `<c-element>`.
- The body passes through: fills become the component target's slots. For
  `<c-element>` only the default slot exists (the body, or an explicit
  `<c-fill name="default">`); named fills are rejected at parse time via
  the slot rules (section 5.2).
- README.md's built-in tag table gains the `<c-element>` row (the 13th tag).

There is no Python-side entry point: in Python you already hold the class
or the element, so `MyTable(rows=...)` or passing `CitryElement` values
around covers what DJC's `DynamicComponent.render(kwargs={"is": ...})` did.

---

## 4. Resolution semantics

### 4.1 `<c-component is="...">`

| `is` value | Resolution |
|---|---|
| `type[Component]` | Used directly. The class-first form, aligned with djc #1195 (phase out registered names). |
| `str`, registered | That component class. Case-insensitive, kebab aliases included, same as any `<c-name>` tag. |
| `str`, not registered | `NotRegistered`, with the registry's did-you-mean help. The message points to `<c-element>` when the name looks like an element ("to render a plain HTML element, use <c-element>"). |
| missing / falsy | `TypeError`: `<c-component>` requires an 'is' value (mirrors DJC `dynamic.py:117-118`). |
| anything else | `TypeError` naming the offending type. |

A `CitryElement` as the `is` value is rejected with a pointed error ("embed
the element with `{{ ... }}` instead, or pass its class"): merging extra
kwargs and slots into an already-composed element has no single obvious
meaning, and the expression path already covers the use case.

### 4.2 `<c-element is="...">`

The value must be a string and is used as the element's tag name, verbatim
(so SVG camelCase names like `clipPath` render as written). Any name is
accepted (decision 3); there is no registry consultation, so a component
registered as `table` is irrelevant here, and conversely
`<c-component is="table">` errors unless such a component exists. The only
validation: the string must be a syntactically valid tag name (the same
charset rule the registry applies, `component_registry.py:72`), so values
containing whitespace, `>`, quotes, etc. raise immediately rather than
producing broken markup. This validation is also what makes emitting the
tag name into output safe (section 5.1). Void elements reject a body.

Polymorphic targets (one variable naming *either* a component or an
element, which Vue's single tag supports) are deliberately not supported;
the author branches with `<c-if>`, or wraps the decision in their own
component. Section 8 (alternative D) records the reasoning and the
additive path back if real demand appears.

---

## 5. Implementation

### 5.1 The two built-ins (`citry/components/dynamic.py`)

`make_dynamic_components(citry_instance)` creates both classes, registered
as `"component"` and `"element"` by `make_builtin_components`, with both
names added to `BUILTIN_COMPONENT_NAMES`.

**`<c-component>`**, following `provide.py`:

```python
class DynamicComponent(Component):
    citry = citry_instance
    transparent = True
    template = "{{ target }}"

    def template_data(self, kwargs, slots=None):
        data = dict(self.raw_kwargs)
        comp_cls = self._resolve(const_value(data.pop("is", None)))   # section 4.1
        return {"target": CitryElement(comp_cls, data, self.raw_slots)}
```

Why this delegation shape works: `{{ target }}` evaluates to a
`CitryElement`, and `_render_value` (`citry_render.py:212-217`) renders an
element found in expression output in place, with the provide/inject
entries active at the site. The target sees the fills directly as its own
`raw_slots`, which is also why DJC's `_is_dynamic_component` special case
in `slots.py:675` has no citry equivalent: DJC's fills had to *see through*
the wrapper's context frame, while citry hands the slot objects to the
target explicitly.

**`<c-element>`** is not a delegator at all: it is itself the element
renderer, one generic class for every tag name. The tag name and the
attribute region are computed values in a fixed template; only the body
flows through the normal slot mechanism:

```python
class DynamicElement(Component):
    citry = citry_instance
    transparent = True
    template = "{{ open }}<c-slot />{{ close }}"

    def template_data(self, kwargs, slots=None):
        attrs = dict(self.raw_kwargs)
        tag = const_value(attrs.pop("is", None))
        self._validate_tag_name(tag)              # section 4.2; also the escape guarantee
        self._reject_named_fills(self.raw_slots)  # parse rules catch static ones;
                                                  # this catches c-bind/dynamic names
        if is_void(tag):                          # HTML_VOID_ELEMENTS, section 5.3
            if self.raw_slots:
                raise ...                         # void elements cannot have children
            return {"open": Markup(f"<{tag}{format_attrs(resolved)}/>"), "close": ""}
        return {
            "open": Markup(f"<{tag}{format_attrs(resolved)}>"),
            "close": Markup(f"</{tag}>"),
        }
```

where `resolved` is the attribute dict after the same treatment a
statically written element gets: `normalize_class` / `normalize_style` on
those two keys, then the `on_attrs_resolved` extension hook, then
`format_attrs` (which escapes values). These are the exact helpers
`ElementAttrsNode` uses (`attrs.py`, `nodes/__init__.py:582`); extract a
small shared function if the hook-firing code would otherwise be
duplicated. Escaping discipline is localized to these few lines: attribute
values are escaped by `format_attrs`, and the tag name is safe to
interpolate because `_validate_tag_name` rejected anything outside the
tag-name charset.

Notes on this shape:

- **No per-tag classes, no cache.** An earlier draft synthesized and
  cached a component class per distinct tag name to reuse
  `ElementAttrsNode` via a per-tag template. That bought ~15 lines of
  reuse at the cost of a size-bounded cache (tag names can be data-driven,
  e.g. `c-is="item.tag"` fed from a CMS, so distinct values are
  unbounded), and it collided with the metaclass auto-registering every
  class. One generic class deletes the whole problem space (section 8,
  alternative E).
- **The body is the default slot**: `<c-slot />` renders it in place
  between the computed tags; absent body renders nothing. Fills with
  dynamic names or smuggled via `c-bind` are re-checked at render; static
  named fills never get this far (parse rules, section 5.2).
- **Nested-template attribute values are rejected on the dynamic path.** A
  `c-foo="<b>{{ x }}</b>"` value resolves to a `CitryRender` whose parts may
  hold not-yet-rendered children, which cannot be flattened into the `open`
  string here. The static-`is` form supports them fully (it compiles to a
  real element with an `ElementAttrsNode`); the dynamic form raises a
  `TypeError` pointing at that alternative.
- **Serialization parity**: `Markup` parts pass through `_render_value`
  unescaped by design (`citry_render.py:195-196`), and `data-cid` marker
  stamping happens at serialize time over the joined frame output, so a
  dynamically emitted element at a parent component's root receives the
  parent's marker exactly like a statically written one. `transparent =
  True` on both built-ins keeps the frames identical to hand-written
  markup.
- **Attribute semantics parity is a stated contract**: `<c-element
  class="a" c-bind="{'class': 'b'}">` must render the same as the
  statically written `<div class="a" c-bind="{'class': 'b'}">`. One known
  nuance: on a component tag, `ComponentNode._resolve_kwargs` collapses
  duplicate attribute spellings last-one-wins *before* `template_data`
  sees them, while a static element hands all sources to
  `ElementAttrsNode`. Today both end at last-one-wins (README "Attribute
  spreading"), so the results agree; if class/style *merging* semantics
  ever land (benchmarking.md feature A), `<c-element>` must adopt them in
  the same change, which is why the shared-helper seat matters. The
  parity tests in section 9 lock this.

`transparent = True` keeps the output identical to writing the target
directly: no extra `data-cid` marker for the wrappers, and a component
target (a real component render) gets its own, exactly as if its tag had
been written in place.

### 5.2 The compiler changes (`compiler.rs:265` and constants)

All changes live in the `C_COMPONENT_TAG` match arm, a new sibling
`C_ELEMENT_TAG` arm, and the rules tables (no AST, grammar, or `LangImpl`
changes):

1. **The static-`is` rewrite on `<c-component>` stays exactly as it is.**
   Under components-only semantics, rewriting `<c-component is="Xyz">` to
   `<c-Xyz>` is always correct: an unregistered name fails at render with
   `NotRegistered` either way. (The earlier fallback design needed
   list-driven skip logic here; this design deletes that need.)
2. **A mirror static rewrite for `<c-element>`**: `<c-element is="div" ...>`
   with no fills in its body mutates into the plain `<div ...>` HTML node
   (the `is` attribute dropped), compiling exactly as if the element had
   been written statically: zero render cost for the benchmark Form case
   with a static choice. When the body contains fills, the runtime path is
   kept: a `<c-fill name="default">` is legal (it is the default slot) and
   unwrapping it at compile time is not worth the complexity.
3. **Reject `is` together with `c-is`** on both tags with a compile error.
   Today the `c-component` rewrite consumes `is` and leaves `c-is` behind,
   which then reaches the target as a literal `is` kwarg; without the
   rewrite, both spellings collapse onto the same kwarg key in
   `ComponentNode._resolve_kwargs` (`nodes/__init__.py:759`) and the last
   one silently wins. The parse rules cannot express this exclusion
   (allowed-attrs is `None` for these tags, and mutual exclusion rides on
   allowed groups), so the compiler arm is the right seat.
4. **Rules tables** (`constants.rs`): `C_ELEMENT_TAG = "c-element"`;
   `TAG_ATTR_RULES_DATA` gains `(C_ELEMENT_TAG, (None, &[&["is", "c-is", "c-bind"]]))`,
   mirroring `c-component`; `TAG_SLOT_RULES_DATA` gains
   `(C_ELEMENT_TAG, (Some(&["default"]), &[]))` so **named fills on
   `<c-element>` are parse errors** (dynamic fill names defer to runtime
   as usual, where the built-in re-checks). `parser.rs:2044`'s component
   check and the `:65` built-ins comment list `c-element` alongside
   `c-component`. The dynamic `<c-element>` path compiles to
   `ComponentNode(name="element")`.

One accepted gap, documented rather than fixed: parse-time `Kwargs`
validation (tag_rules) runs while the tag is still `<c-component>` with
permissive rules, so a statically-targeted component's declared kwargs are
not checked at parse time the way `<c-my-table>` would be. The target's own
`Kwargs` construction still validates at render. Fixing this would need the
parser to know the registry at validation time, ordering it does not have;
revisit only if it bites in practice.

### 5.3 `HTML_VOID_ELEMENTS` exposed to Python

The only Rust-to-Python data this design needs: the existing
`HTML_VOID_ELEMENTS` list (`constants.rs:11`), exported through the
`citry_core` PyO3 `template_parser` module as a `frozenset[str]` and
mirrored in `_rust.pyi`, so `<c-element>` can emit compact void tags and
give the clean "void elements cannot have children" error. One list,
Rust-owned, same single-source rule as everything else. (The earlier
fallback design needed a full `HTML_ELEMENT_NAMES` list plus settings
plumbed into the compile call; all of that is gone.)

### 5.4 Cross-binding consistency audit (CLAUDE.md mechanism 4)

What moves with this change, classified:

| Surface | Change |
|---|---|
| Grammar (`grammar.pest`) | None. |
| AST (`ast.rs`, `#[pyclass]` types) | None. |
| Parse rules (`constants.rs`) | New `c-element` entries in `TAG_ATTR_RULES_DATA` and `TAG_SLOT_RULES_DATA`; `C_ELEMENT_TAG` constant. |
| Compiler output format | None structurally; the two match arms change *which* existing output a template gets (rewritten component node, plain HTML element node, or `ComponentNode("component"/"element")`). |
| `LangImpl` + the five `lang/*.rs` | None: `ComponentNode` and HTML-element emission are shared code. |
| PyO3 glue (`citry_core_py/src/lib.rs`) | Export `HTML_VOID_ELEMENTS`. |
| `_rust.pyi` | Stub for it. |
| Python wrapper (`citry_core/template_parser/`) | Re-export. |
| `citry` package | New `components/dynamic.py` (both built-ins); `BUILTIN_COMPONENT_NAMES` gains `"component"` and `"element"`; `make_builtin_components` creates both; possibly a small shared attrs-resolution helper extracted from `ElementAttrsNode` (section 5.1). |
| README.md | `<c-element>` row in the built-in tags table. |
| Rust tests | New: both rewrites, the conflict errors, the `c-element` slot rule, the dynamic paths. These are the first `c-component` tests in the crate. |
| Python tests | New `test_component_dynamic.py` (section 9). |

---

## 6. DJC surface tracking

| DJC surface (`components/dynamic.py` + settings) | citry status | Note |
|---|---|---|
| `is` = registered name (str) | Ported | `<c-component>`; registry lookup, case-insensitive + kebab aliases |
| `is` = `Component` class | Ported | The djc-#1195-friendly form |
| `is` = component instance | Dropped | Only existed because Django templates auto-call callables; `safe_eval` does not |
| `registry` kwarg | Dropped | Registry is 1:1 with the `Citry` instance |
| `ALL_REGISTRIES` fallback search | Superseded | Same: instance-scoped state (djc #1413) |
| kwargs pass-through (minus `is`) | Ported | `raw_kwargs`, so the target's own validation speaks |
| args pass-through | Dropped | citry components are kwargs-only |
| slots pass-through | Ported | `raw_slots` handed to the target directly (default slot only for `<c-element>`) |
| Fills the target does not render | Ported (same behavior) | Unused `Slot`s, unless the target's `Slots` class rejects them; `<c-element>` rejects named fills at parse time instead (nothing could consume them) |
| Unexpected kwargs raise from target | Ported (same behavior) | Target's `Kwargs` construction raises |
| Delegation seat: `on_render` | Superseded | `template_data` + `{{ target }}` via `_render_value` for `<c-component>`; `<c-element>` renders directly, no delegation at all; citry has no `on_render` hook yet, and does not need one here |
| `_is_dynamic_component` + `slots.py:675` special case | Superseded | Explicit slot hand-off, no see-through needed |
| `deps_strategy` / `outer_context` / `registered_name` forwarding | Skip (Django) / superseded | No outer context crosses component boundaries in citry |
| Registered as `"dynamic"` | Changed | citry registers `"component"` (the README tag), reserved as a built-in name |
| `dynamic_component_name` rename setting | Dropped | The names are reserved, so the conflict it solved cannot arise |
| (new, no DJC equivalent) `<c-element>` dynamic HTML elements | Added | Replaces Django's `<{{ tag }}>` text-template trick; any tag name, like static HTML; custom web components included |

---

## 7. Behavior notes

- **Hooks fire for two components** when `<c-component>` delegates: the
  transparent wrapper and the target are both real renders, same as DJC.
  `<c-element>` is a single render. Extensions that count or wrap
  components see exactly these; `transparent` only affects serialization
  framing. `<c-element>` fires `on_attrs_resolved` like a static element
  (section 5.1).
- **Const and folding.** A literal `is` and other literal attributes
  arrive `Const`-marked via `ComponentNode._resolve_kwargs`, so each
  built-in's const-body cache keys include the target; two sites with
  different static targets never share an entry, and only
  template-authored (finite) values are ever cached. Dynamic `c-is` values
  are not const, so nothing about the target is ever wrongly cached. The
  compile-time rewrites mean both static cases bypass the built-ins
  entirely.
- **Reserved names.** `"component"` and `"element"` join
  `BUILTIN_COMPONENT_NAMES`, so a user class named `Element` (or
  `Component.name = "element"`) now fails registration with the existing
  loud `AlreadyRegistered` message (`component_registry.py:152-158`),
  which names the fix. `element` was picked over `tag` precisely because
  this collision is implausible for real component class names
  (decision 2).
- **Error identity.** Resolution errors name the built-in tag and the `is`
  value; errors from inside a component target are the target's own (the
  wrapper adds no frame to blame). When render-path error tracing lands
  (the to-migrate row in `citry_migration.md`), the wrappers should appear
  in the component path like any parent.
- **`provide`/`inject`** flow through unchanged: the built-ins are normal
  components for context purposes, and `_render_value` hands the active
  provides to a delegated component target.

---

## 8. Alternatives considered, and what would falsify this design

**Alternative A: a dedicated `DynamicNode` in the compiler.** Rejected: it
adds a node class to the AST contract, all five `lang/*.rs` implementations,
the PyO3 registration, the `.pyi` stub, and the Python runtime, for behavior
a registered component expresses today; `constants.rs:65` explicitly
classifies these tags as built-in-able. Revisit only if the built-ins'
render cost shows up in benchmarks (both static paths bypass them entirely,
so this would have to come from heavy dynamic-target usage).

**Alternative B: delegate via an `on_render` hook, as DJC does.** Rejected
for now: the `on_render` hook family is still a to-migrate row with an
unsettled shape (`citry_migration.md`, `component.py` review), and blocking
the benchmark's large scenario on it buys nothing; `template_data` +
`{{ target }}` is a documented, tested path.

**Alternative C: Vue's single polymorphic tag** (one `is` that resolves
components first and falls back to elements). Rejected: with citry's
auto-registration, component names shadow element names routinely
(`Table`, `Form`, `Button`, `Input`...), so the fallback needs an
arbitration story, and the fallback's element half needs typo protection
(a known-element list) because a misspelled component name would otherwise
silently ship as a bogus element. Splitting the tags removes both problems
at the root. The cost is polymorphic `is` (one variable naming either kind);
that is rare, expressible with a `<c-if>` or a user-side wrapper component,
and re-addable later *additively* (e.g. an opt-in fallback) if real demand
appears, whereas merging first and splitting later would break users.

**Alternative D: one tag with a `tag=`/`c-tag=` attribute and settings
escape hatches** (an earlier draft of this document). Superseded by the
two-tag split: it needed a Rust-owned `HTML_ELEMENT_NAMES` list (HTML +
SVG + MathML), two `CitrySettings` fields (`extra_html_elements`,
`allow_any_html_element`), those settings plumbed into the compile call,
and list-driven skip logic in the static-`is` rewrite. The split deletes
all of it: `<c-component>` errors on unknown names with no fallback to
protect, and `<c-element>` trusts any name exactly as static HTML already
does, which also covers custom web components with zero configuration.

**Alternative E: synthesize and cache a component class per tag name**
(an earlier draft of section 5.1, where `<c-element>` delegated to a
generated `class TagElement` with the tag baked into its template, to
reuse `ElementAttrsNode` wholesale). Superseded by the single generic
class: tag names can be data-driven, so distinct values are unbounded and
the class cache needed an LRU; render-time class creation collides with
the metaclass auto-registering every `Component` subclass (registry
pollution or a registration opt-out); and each synthesized class fired
class-lifecycle extension hooks as noise. The generic class costs ~15
lines that call the same shared attrs helpers, and deletes the cache, the
bound, and the registration question entirely.

Falsifiers checked during implementation:

- `_render_value`'s in-place `render_impl` call does add Python stack
  frames per *chained* dynamic wrapper (a `<c-component>` whose target's
  template is again a `<c-component>`, recursively). **Measured: chains of
  100 render fine; chains of 200 hit the recursion limit.** Regular nesting
  is unaffected (the deferred queue handles normal children), and realistic
  wrapper chains are a handful deep, so this ships as a documented
  limitation with a depth-50 test locking the working range. If real
  templates ever approach the limit, the fix is returning a
  `DeferredComponent` from the wrapper instead, which needs a small
  `_render_value` extension.
- If `<c-element>`'s hand-assembled attribute region diverges from
  `ElementAttrsNode` output on any input (escaping, boolean attributes,
  class/style normalization, the `on_attrs_resolved` hook), the parity
  contract in section 5.1 is broken; the section 9 parity tests exist to
  catch exactly this, and the fix is sharing more code, not patching the
  copy.
- The large benchmark scenario's Form port is the acceptance test: if its
  div/table/ul switch cannot be expressed cleanly (it should be one
  `<c-element c-is="form_content_tag">`), the design missed.
- If real templates turn out to need polymorphic targets often, alternative
  C's additive path (an opt-in fallback on `<c-component>`) gets designed;
  the split makes that a pure extension, not a rework.

---

## 9. Testing plan

Rust (`crates/citry_template_parser/tests/`, new `tag_compiler_component.rs`
or extending the parser suites; authored observe-then-lock per CLAUDE.md):

- `<c-component is="MyComp">` rewrites to the named component node;
  attributes and body carried over; `is` dropped. (Locks the existing,
  currently untested rewrite.)
- `<c-element is="div">` rewrites to the plain `<div>` HTML node; `is`
  dropped; body and attributes carried over; not rewritten when the body
  contains fills.
- `is` + `c-is` is a compile error on both tags.
- Missing all of `is`/`c-is`/`c-bind` is a parse error on both tags
  (extends the existing `constants.rs:184` rule, currently untested).
- Named `<c-fill>` inside `<c-element>` is a parse error; default fill and
  plain body are allowed; named fills inside `<c-component>` are allowed
  (locks `parser.rs:2044`).
- Dynamic paths compile to `ComponentNode("component")` /
  `ComponentNode("element")`.

Python (`packages/py/citry/tests/test_component_dynamic.py`), porting the
DJC behavior contract plus the `<c-element>` half:

- `<c-component>`: static name, dynamic name from a variable, name via
  `c-bind` spread, class via `c-is`, kwargs/slots pass-through, default
  slot, named slots, fills the target lacks staying unused, unexpected
  kwargs raising from the target, unknown name raising `NotRegistered`
  with did-you-mean (and the `<c-element>` hint for element-looking
  names), missing `is` raising `TypeError`, `CitryElement` as `is`
  rejected.
- `<c-element>`: static and dynamic tag names, custom-element names
  (`my-widget`), SVG camelCase (`clipPath`) rendered verbatim, body as
  children (implicit and via explicit default fill), void elements compact
  and rejecting bodies, invalid tag-name strings (whitespace, `>`, quotes)
  raising, named fills via dynamic `c-name`/`c-bind` raising at render.
- **Attribute parity**: for a matrix of attribute shapes (static, `c-*`
  expression, `c-bind` spread, boolean attributes, `class`/`style` values,
  values needing escaping), `<c-element is="div" ...>` output is
  byte-identical to the statically written `<div ...>` equivalent, and
  `on_attrs_resolved` fires with the same payload.
- No shadowing: with a registered `Table` component, `<c-component
  is="table">` renders the component and `<c-element is="table">` renders
  the element; neither consults the other's namespace.
- Registry: `"component"` and `"element"` reserved against user
  registration (raises `AlreadyRegistered`); built-ins created lazily per
  `Citry` instance.
- Const: same template with two different static targets renders both
  correctly (no cache crosstalk); `data-cid` markers match the
  statically-written equivalent (transparent built-ins invisible).
- Provide/inject through both built-ins.
- A deep chained-dynamic test for the recursion falsifier (section 8).

---

## 10. Interactions

- **Benchmarks** ([`benchmarking.md`](benchmarking.md) feature B): unblocks
  the citry port of the large scenario's Form component together with
  feature C (dependency rendering); the Form case becomes
  `<c-element c-is="form_content_tag">`. The static rewrites keep both
  common cases benchmark-clean.
- **Class/style value forms** (benchmarking.md feature A): if class/style
  *merging* semantics land, `<c-element>` must adopt them in the same
  change (the parity contract in section 5.1); the shared attrs helpers
  are the single seat for both.
- **`citry_migration.md`**: resolves the `DynamicComponent` ❓ row (migrate,
  as specified here) and the `dynamic_component_name` ❓ row (drop); the
  built-in components table gains both tags.
- **README.md** (the north star): gains the `<c-element>` row;
  `<c-component>`'s existing row stands as written.
- **Registry / djc #1195**: the class-valued `c-is` form works without any
  registry name, so `<c-component>` gets *more* idiomatic as registered
  names phase out, not less.
- **Dependency extension** (`<c-js>`/`<c-css>`): none beyond all being
  built-ins from the same factory; the wrappers merge the target's
  dependencies like any parent.
- **Error tracing** (to-migrate): the built-ins should appear in component
  paths; nothing here blocks it.

---

## 11. Open questions

- **Parse-time kwargs validation for static `<c-component is>` targets**
  (the accepted gap in section 5.2): revisit only if template authors get
  bitten in practice.
- **Whether the attrs-resolution helper should be formally extracted** (one
  function used by both `ElementAttrsNode` and `<c-element>`, section 5.1)
  or the built-in calls the existing pieces directly. Decide by code size
  at implementation time; the parity tests hold either way.
