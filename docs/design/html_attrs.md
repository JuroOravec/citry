# Design: HTML attribute rendering (c-bind, class/style values, booleans)

**Status (2026-06-11): design agreed; implementation started alongside this
doc.** This document
specifies how dynamic attribute values render on plain HTML elements: the
structured value forms for `class` and `style` (Vue/React style), boolean
and `None` handling, `c-bind` spreading, and what happens when the same
attribute is given multiple times. It also specifies the compiler and parser
changes needed to make any of that possible, because today the compiler
flattens element attributes into plain string interpolation before the
runtime ever sees them.

This is "feature A" of the benchmarking plan
([`benchmarking.md`](benchmarking.md) section 6.3), but it is a standalone
user-facing feature: it is what makes the README's "Dynamic attributes" and
"Attribute spreading" sections actually work, and it is the citry equivalent
of django-components' `{% html_attrs %}`.

For the render model the new node plugs into see
[`rendering.md`](rendering.md); for the constant-folding pass that must keep
working see [`constness.md`](constness.md). For operating rules see
[`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: django-components
[#1281](https://github.com/django-components/django-components/issues/1281)
(repeated `class` kwargs in `{% html_attrs %}`; settles the v1 direction of
"one kwarg, structured values"), django-components
[PR #1066](https://github.com/django-components/django-components/pull/1066)
(the discussion that kept DJC close to Django syntax), and Vue's
[`mergeProps`](https://vuejs.org/api/render-function#mergeprops) (the
semantics both DJC and this design follow).

---

## 1. Prior art (what was searched)

### 1.1 django-components: the feature exists, fully implemented

`src/django_components/attributes.py` (440 lines) is the complete reference
implementation, itself derived from django-web-components (credited at
`attributes.py:1-3`):

- **`HtmlAttrsNode`** (`:20-90`): the `{% html_attrs attrs defaults **kwargs %}`
  template tag. Merges `defaults` under `attrs`, then merges `kwargs` on top
  via `merge_attributes`, then renders with `format_attributes`.
- **`format_attributes`** (`:93-121`): dict -> HTML attribute string.
  `None`/`False` values skip the attribute, `True` renders the bare key,
  everything else renders `key="value"` with `conditional_escape` +
  `format_html`. Returns a SafeString.
- **`merge_attributes`** (`:131-232`): merges dicts left to right. `class`
  and `style` values are collected across all dicts and normalized at the
  end; any other repeated key is joined with a space (`:219-222`), a
  behavior DJC plans to retire (see 1.2).
- **`normalize_class`** (`:235-295`): string used as-is; dict keeps truthy
  keys; list items each convert to a `{class_name: bool}` dict and update
  cumulatively, so a later falsy entry removes an earlier class. The code
  documents this as a deliberate divergence from Vue (`:274-279`): Vue keeps
  `["a", {"a": False}]` as `"a"`, DJC drops it.
- **`normalize_style`** (`:319-401`): string used as-is at the top level;
  dict entries render `prop: value;`; in merges, a `None` value means "skip,
  let an earlier value stand" while a literal `False` means "remove this
  property entirely" (`:334-336`). List items convert to dicts and update,
  last value per property wins.
- **`parse_string_style`** (`:412-439`): inline CSS string -> dict. Strips
  `/* */` comments, splits on `;` but not inside parentheses (so
  `url(data:...;base64)` survives), splits each declaration on the first `:`.
- **Type shapes** (`:15-17`):
  `ClassValue = Sequence[ClassValue] | str | dict[str, bool]`,
  `StyleValue = Sequence[StyleValue] | str | StyleDict` with
  `StyleDict = dict[str, str | int | Literal[False] | None]`.
- **Tests**: `tests/test_attributes.py` (601 lines) covers escaping,
  SafeString passthrough, `True`/`False`/`None` attribute values, class and
  style merging incl. `None`/`False` cases, the tag's positional/kwarg/spread
  forms, and `parse_string_style` edge cases (comments, missing delimiters,
  incomplete declarations). The edge-case inventory ports almost wholesale.

`format_attributes` and `merge_attributes` are public API, exported from
`django_components/__init__.py:178,185`.

### 1.2 The DJC v1 direction (issue #1281)

`{% html_attrs %}` accepts the same kwarg repeated (`class=x class="y"`) and
merges the values; a bug where repeats were dropped led to issue #1281. The
maintainer's resolution comment sets the v1 direction: repeated kwargs get
deprecated, and the recommended form becomes a **single `class` kwarg with a
list value** (`class=[btn_class, "no-underline"]`), since literal lists made
the repeated-kwarg syntax redundant. Citry starts where DJC v1 lands: there
is no repeated-kwarg syntax to support, structured values are the only form.
The same comment links tailwind-merge as the kind of class-conflict
resolution this feature deliberately does NOT attempt (see section 10).

### 1.3 Citry today: the README promises more than the engine does

The README (the north-star spec) promises, in "Dynamic attributes" and
"Attribute spreading" (`README.md:137-214`):

- `c-disabled="is_loading"` with a `True` value renders bare `disabled`;
- `c-bind="{...}"` spreads a dict onto the element, `True` entries become
  boolean attributes;
- `c-bind` can repeat and interlace with regular and dynamic attributes,
  duplicates resolve last-one-wins.

What the engine does today (verified by rendering, June 2026):

- `c-bind="{'class': 'from-bind', 'id': 'x'}"` on a plain element renders
  literally as `bind="{&#39;class&#39;: ...}"`. No spread.
- `c-disabled="flag"` renders `disabled="True"` or `disabled="False"`.
- `c-class="['a', {'b': True}]"` renders the `str()` of the Python list,
  escaped.
- `class="x"` together with `c-class="y"` on one tag is a **parse error**
  (`parser.rs:1902`: same attribute in static and dynamic form is rejected,
  except through `c-bind`), which also rejects the README's own interlacing
  example.

The cause is structural, in the compiler
(`crates/citry_template_parser/src/compiler.rs:432-520`,
`compile_html_node`): a plain element's attributes are flattened at compile
time into static string chunks with a bare `ExprNode` per dynamic value,
e.g. `'<div class="'`, `ExprNode(...)`, `'"'`. By render time there is no
attribute structure left, so no spread, no boolean handling, and no
normalization can happen. Component tags are different: `compile_component_node`
(`compiler.rs:771`) keeps attributes structured as
`StaticHtmlAttr` / `ExprHtmlAttr` / `TemplateHtmlAttr` tuples, and the
runtime resolves them into kwargs, with `c-bind` correctly spreading
(`citry/nodes/__init__.py:593-625`). This design gives plain HTML elements
the same structured treatment.

Also relevant in `packages/py/citry/citry/`:

- `util/html.py`: `escape` (markupsafe, escapes all five of `& < > ' "` so
  one escaping is safe in body and attribute position) and `SafeString`
  with `__html__` passthrough. The new code uses these, nothing new needed.
- The static-attr path already normalizes `key=""` to the bare boolean form
  at compile time (`compiler.rs:456-460`), and `StaticHtmlAttr.resolve`
  returns `True` for value-less attributes (`nodes/__init__.py:405`). The
  runtime semantics below extend that same convention to dynamic values.
- The Const pass marks `StaticHtmlAttr` and variable-free `ExprHtmlAttr`
  values as literal on component nodes (`nodes/__init__.py:601-625`,
  consumed in `constness.py`); the new element-attrs node must participate
  the same way.

---

## 2. Scope and the decisions that shaped it

The feature was requested as "Vue/React-style class/style values", but the
audit above shows the real unit of work is the **dynamic-attribute rendering
subsystem for plain HTML elements**: value forms, booleans, `c-bind` spread,
and duplicate resolution all need the same structural change (a runtime node
that sees the whole attribute set), so they ship together. Decisions:

1. **One merge rule: last-one-wins for every attribute except `class` and
   `style`, which merge.** Sources are collected left to right (static
   attrs, `c-*` attrs, `c-bind` entries, in source order). For `class` and
   `style` all collected values combine via the normalization below; for
   everything else the last value replaces earlier ones. This matches Vue's
   `mergeProps` and DJC's `merge_attributes`, and it is what makes the
   "caller's attrs + component's own classes" pattern (`c-bind="attrs"
   c-class="..."`) work without manual dict surgery.
2. **This amends the README.** The README's interlacing example
   (`README.md:201-214`) currently shows `class` resolving last-one-wins
   like every other attribute. Under this design that example's output
   changes (`class="default from-bind override"` instead of
   `class="override"`). The amendment is deliberate: a class that silently
   swallows earlier classes is exactly the bug pattern DJC's `html_attrs`
   exists to prevent, and per-attribute opt-outs (some marker for "replace,
   don't merge") are not worth the syntax. The README update is part of this
   work (phase 4), including reworking that example to show last-one-wins on
   a non-class attribute and merge on `class`.
3. **DJC's normalization semantics are adopted as-is**, including its
   documented divergence from Vue (a later falsy dict entry removes an
   earlier class). Same author, deliberate choice, and parity makes the DJC
   test suite portable.
4. **The parser stops rejecting same-name static + dynamic attributes**
   (`parser.rs:1902`). With defined duplicate semantics the rejection loses
   its purpose, and the README interlacing example must parse. The
   control-flow attribute exclusivity check right below it
   (`parser.rs:1935`) stays.
5. **Component tags are out of scope.** Attributes on `<c-Comp>` are kwargs,
   not HTML attributes; `c-bind` already spreads there and dict-update
   (last-one-wins) semantics stay. If component attrs fallthrough (Vue's
   `$attrs`) lands later, it reuses the merge model from this design at the
   point where forwarded attrs meet the root element's own.
6. **The helpers are public API.** `template_data()` authors building attr
   dicts by hand need the same normalization DJC exports
   (`merge_attributes` / `format_attributes`); citry exports its equivalents
   from the `citry` package.

Alternatives considered:

- **Pure Python-side fix, no compiler change** (normalize inside the
  existing `ExprNode`): falsified immediately by the codegen, since the
  `' disabled="'` prefix and closing quote are static chunks around the
  node; a `False` value cannot un-emit them, and `c-bind` has no node to
  hook at all. Section 1.3 is the evidence.
- **Keep last-one-wins universally, merge only inside explicit list
  values** (`c-class="[attrs.get('class'), btn_class]"`): consistent with
  the current README, but it forces every component that accepts caller
  attrs to manually pluck `class`/`style` out of the spread dict, which is
  the boilerplate Vue and DJC both eliminated. Rejected for ergonomics; the
  explicit list form still works under decision 1.

What would falsify this design: a plain element whose attribute set cannot
be known at compile time beyond `c-bind` (none exists in V3, attributes are
syntactically enumerated); or a measurable render-time regression on
static-heavy templates, which the static fast path (section 5.2) exists to
prevent.

---

## 3. The value model

A dynamic attribute value (from a `c-*` expression or a `c-bind` entry)
resolves to a Python object. What it means depends on the attribute:

### 3.1 Any attribute: booleans and None

| Value | Rendered as |
|---|---|
| `True` | bare attribute: `disabled` |
| `False` or `None` | attribute omitted entirely |
| string / number / other | `key="value"`, value escaped via `escape()` (SafeString / `__html__` objects pass through unescaped) |

A value-less or empty dynamic attribute (`<div c-foo>`, `<div c-foo="">`) is
a **parse error**: there is nothing to evaluate, and it is almost certainly
a mistake (the user meant the static boolean `foo`, or forgot the value).
The error message says exactly that. The control-flow shorthand attributes
that take no value by design (`c-else`, `c-empty`) are exempt. Value-less
*static* attributes keep meaning `True` (`<div hidden>`), as in HTML.

### 3.2 `class` values

`ClassValue = str | dict[class_name, bool] | sequence of ClassValue` (lists
nest arbitrarily and flatten):

| Input | Output |
|---|---|
| `"btn btn-lg"` | `class="btn btn-lg"` (used as-is, stripped) |
| `{"btn": True, "hidden": False}` | `class="btn"` |
| `["btn", {"active": is_active}, other_classes]` | items convert to `{name: bool}` dicts (strings split on whitespace, all `True`) and update left to right; truthy keys join in first-seen order |
| `["a", "b", {"b": False}]` | `class="a"` (later falsy removes; the documented DJC divergence from Vue) |

### 3.3 `style` values

`StyleValue = str | dict[css_prop, css_value] | sequence of StyleValue`:

| Input | Output |
|---|---|
| `"color: red; width: 100px"` | used as-is when it is the only value; parsed via the string-style parser when merging |
| `{"color": "red", "background-color": "blue"}` | `style="color: red; background-color: blue;"` |
| dict value `None` | skip this entry; an earlier value for the property survives |
| dict value `False` | remove the property entirely, even if set earlier |
| list | items convert to dicts (strings parsed) and update; last value per property wins; `None`/`False` rules apply at the end |

The string-style parser strips `/* */` comments and splits declarations on
`;` only outside parentheses, so `background: url(data:image/png;base64,...)`
parses correctly (DJC `parse_string_style` semantics, ported with its
tests).

Property names are used as written: kebab-case, as CSS spells them. Vue's
camelCase acceptance (`fontSize`) is deliberately not adopted (DJC parity,
one less transform). Property values may be `int` (rendered bare,
`width: 100`, DJC parity); no unit is auto-appended.

### 3.4 Escaping: a literal `c-` attribute name

Because `c-` is reserved for the framework, an attribute name that starts with
`c-` is normally handled as a directive. To emit a *literal* `c-`-prefixed
attribute, add one extra `c-` segment: the compiler always strips **exactly
one** leading `c-`, and if what remains still starts with `c-`, it is a literal
name rather than a directive (its value is still evaluated as usual).

| Written | Rendered |
|---|---|
| `c-foo="'bar'"` | `foo="bar"` (a directive: one `c-` stripped, value evaluated) |
| `c-c-foo="'bar'"` | `c-foo="bar"` (literal `c-foo`) |
| `c-c-c-foo="'bar'"` | `c-c-foo="bar"` (literal `c-c-foo`) |
| `c-c-bind="'lit'"` | `c-bind="lit"` (literal `c-bind`, not a spread) |

The common use is a framework "bridge" attribute: `c-:class="expr"` strips one
`c-` and emits `:class="..."`, which Vue or Alpine then reads. Keys inside a
`c-bind` mapping are always literal and never get this treatment.

---

## 4. The merge model

For one element, attributes are collected **left to right in source order**:

1. a static attribute contributes its literal value (`True` when value-less),
2. a `c-*` attribute contributes its evaluated expression value under the
   prefix-stripped key,
3. a `c-bind` attribute contributes each entry of its evaluated value, which
   must be a `Mapping` (a non-mapping raises at render time, consistent with
   the README's "c-bind spreads are checked at render").

Resolution per key:

- `class`, `style`: every contribution is kept, in order, and the list
  normalizes per section 3 at the end. Order is contribution order, so later
  entries override (style) or can disable (class dict) earlier ones.
- every other key: last contribution wins.

Attribute output order is **first-seen order of each key**, so adding a
later override does not move the attribute in the output (and output stays
deterministic, per the repo-wide determinism rule).

Worked example (the README interlacing example under the new semantics):

```html
<div
  class="default"
  c-bind="{ 'class': 'from-bind', 'id': 'first' }"
  c-class="'override'"
  c-bind="{ 'id': 'second' }"
></div>

<!-- Renders: -->
<div class="default from-bind override" id="second"></div>
```

`class` merged all three contributions; `id` kept the last one.

---

## 5. Runtime and compiler design

### 5.1 `citry/attrs.py`: the value and merge helpers

A new self-contained module, the citry counterpart of DJC's
`attributes.py`:

```python
normalize_class(value) -> str
normalize_style(value) -> str
parse_string_style(css_text) -> dict
merge_attrs(*dicts) -> dict      # left-to-right, class/style merging
format_attrs(attrs) -> SafeString  # dict -> 'key="value" ...', True/False/None rules
```

`format_attrs` accepts the structured class/style forms itself (it runs
`normalize_class` / `normalize_style` on those two keys before formatting),
so a hand-built dict and `merge_attrs` output render the same way and a
caller never needs to pre-normalize.

`merge_attrs` and `format_attrs` are exported from the `citry` package for
use in `template_data()` (decision 6); the normalizers come along for free.
Escaping goes through `util/html.py` only. Naming follows the repo's
existing "attrs" shorthand (`c-bind` docs, `tag_rules.py`); DJC's longer
names are not kept since citry has no deprecation history to honor.

This module has no dependency on the node or compiler layers, so it lands
first and is fully testable by porting DJC's `test_attributes.py` cases.

### 5.2 `ElementAttrsNode`: the structured runtime node

A new runtime node rendering the **entire attribute region** of one start
tag (everything between the tag name and `>`):

```python
ElementAttrsNode(source, (start, end), (attr_nodes...), (used_vars...))
```

- Reuses the existing attribute node classes
  (`StaticHtmlAttr` / `ExprHtmlAttr` / `TemplateHtmlAttr`) exactly as
  `ComponentNode` does, including `c-bind` detection by key.
- `render()` collects contributions per section 4, finalizes class/style
  via `attrs.py`, applies the boolean/None rules, escapes, and returns one
  string part: `' key="value" disabled'` (with the leading space, or `""`
  when every attribute resolved away).
- The compiler emits it **only when the tag has at least one dynamic
  attribute** (`c-*` expression, nested template, or `c-bind`). Purely
  static tags keep today's flattened-string fast path byte for byte, so
  static-heavy templates pay nothing and existing compiled-output tests for
  static HTML stay green. (A purely static tag with a repeated key also
  keeps today's literal passthrough; browsers take the first occurrence,
  and changing that is not worth losing the fast path.)
- Const pass: `StaticHtmlAttr` and variable-free `ExprHtmlAttr` members are
  literal, same marking as `ComponentNode` applies (`nodes/__init__.py:601`);
  an `ElementAttrsNode` whose members are all literal renders to a constant
  string and folds like any other literal part (constness.md). This keeps
  `<div c-class="['a', 'b']">` (no variables) free after the first render.

### 5.3 Compiler change (high-risk area: compiler output format)

In `compile_html_node` (`compiler.rs:432`): when any attribute is
`Expression` or `Template` kind (including `c-bind`), emit
`<tag` + `ElementAttrsNode(...)` + `>` instead of the per-attribute
flattening; otherwise emit the current static chunks. The attr-tuple
codegen already exists for components (`compile_component_node`,
`compiler.rs:771`) and is reused.

Cross-binding consistency audit (CLAUDE.md Mechanism 4):

| Surface | Work |
|---|---|
| `src/lang/python.rs` | new node-name constant + emission, real implementation |
| `src/lang/{js,php,go,rust}.rs` | structural stub update (name registration only) |
| `grammar.pest`, `ast.rs` | **no change** (the AST already carries structured attrs; this is purely compiler output) |
| PyO3 glue (`citry_core_py`), `_rust.pyi` | **no change** (compiler output is a string; no new exposed types) |
| Rust compiler tests | new expected outputs, authored observe-then-lock |
| Python: exec namespace in `component_render.py` | register `ElementAttrsNode` alongside `ExprNode` etc. |
| Python: `nodes/__init__.py` | the new node class |
| Python tests | behavior tests (section 7) + compiled-output expectations |

### 5.4 Parser change

Remove the same-name static/dynamic rejection at `parser.rs:1902` (the
duplicate now has defined semantics). Keep the control-flow attribute group
check (`parser.rs:1935`). Update the parser tests that lock the old error.

### 5.5 Extension hook: `on_attrs_resolved`

For post-processing like tailwind-merge-style class dedup, the extension
system already has everything needed: hooks fire per render site
(`on_slot_rendered` is the precedent, `extension.py:352`) and the
`result="map"` threading mode lets each extension's return value replace a
context field (`extension.py:516`).

The hook fires **after resolution, before formatting**: it sees the final
merged dict (`class`/`style` already normalized to strings, booleans still
`True`, omitted attributes already gone) and can rewrite any value. The two
alternative timings lose: a before-resolution hook would expose the
internal per-source contribution list as public API for little gain (a
post-processor wants the outcome, not the inputs), and an after-formatting
hook would hand extensions an HTML string they must re-parse.

```python
@dataclass(frozen=True, slots=True)
class OnAttrsResolvedContext:
    citry: Citry
    component: Component   # whose template holds the element
    tag_name: str
    attrs: dict[str, Any]  # resolved; threaded with result="map"

def on_attrs_resolved(self, ctx) -> dict[str, Any] | None: ...
```

`ElementAttrsNode.render()` funnels through one resolve-then-format
function and emits there with `result="map"` on `attrs`. This ships with
phase 2, including the [`extensions.md`](extensions.md) hook-inventory row.
Because this is a per-element per-render hot path, the emit must short-cut
to a no-op when no installed extension implements the hook.

---

## 6. DJC surface tracking

| DJC surface | citry status | Note |
|---|---|---|
| `normalize_class` / `normalize_style` / `parse_string_style` | Ported | same semantics incl. the Vue divergence |
| `merge_attributes` | Ported as `merge_attrs` | minus the "join other repeated keys with space" rule (`attributes.py:219-222`); citry is last-one-wins, which is where DJC v1 is heading per #1281 |
| `format_attributes` | Ported as `format_attrs` | same True/False/None rules, markupsafe instead of Django escaping |
| `{% html_attrs %}` tag | Not ported as a tag | the tag's job is done by attribute syntax itself: `attrs`/`defaults` positionals become `c-bind` spreads (defaults first, attrs after), kwargs become `c-*` attributes |
| `defaults:` / `attrs:` aggregate kwargs | Dropped | a Django-syntax workaround; citry templates have real dict literals |
| repeated `class=` kwargs | Dropped | deprecated upstream by #1281; list values are the form |
| `bytes`-free, dict-order-preserving merge | Kept | first-seen key order in output |

---

## 7. Acceptance examples

These lock the user-visible contract (authored observe-then-lock once
built); the README examples are the first three:

| Template (data) | Output |
|---|---|
| `<button c-disabled="is_loading">` (`is_loading=True`) | `<button disabled>` |
| `<button c-disabled="is_loading">` (`is_loading=False`) | `<button>` |
| `<div c-bind="{'class': 'btn', 'disabled': True, 'data-id': item.id}">` (`item.id=123`) | `<div class="btn" disabled data-id="123">` |
| the interlacing example (section 4) | `<div class="default from-bind override" id="second">` |
| `<form c-id="my_var" id="form">` (`my_var="dyn"`) | `<form id="form">` (source order decides; static vs dynamic makes no difference) |
| `<div c-class="['btn', {'active': ok}]">` (`ok=False`) | `<div class="btn">` |
| `<div c-style="{'color': 'red', 'width': False}">` | `<div style="color: red;">` |
| `<div class="a" c-style="s" c-bind="extra">` (`s={'color': None}`, `extra={'style': 'color: blue'}`) | `<div class="a" style="color: blue;">` |
| `<div c-title="'a \" b'">` | `<div title="a &#34; b">` (escaped) |

Plus the ported DJC `test_attributes.py` matrix for the helpers themselves.

---

## 8. Implementation phases

**Phase 1 - the helpers (pure Python, no contract changes).**
`citry/attrs.py` with `normalize_class`, `normalize_style`,
`parse_string_style`, `merge_attrs`, `format_attrs`; exported from `citry`;
DJC's helper tests ported. Immediately usable from `template_data()`, even
before the template syntax catches up.

**Phase 2 - `ElementAttrsNode` + compiler emission.** The high-risk step
(compiler output format): the `compile_html_node` branch, the lang impl
constants (Python real, four stubs), the runtime node, the exec-namespace
registration, the `on_attrs_resolved` hook (context class, base method,
emit in the funnel, extensions.md inventory row), Rust and Python
compiled-output tests (observe-then-lock), and the behavior tests of
section 7 minus the interlacing example.

**Phase 3 - parser alignment.** Lift `parser.rs:1902`, update its tests,
add the interlacing acceptance example.

**Phase 4 - docs and changelog.** README "Dynamic attributes" gains the
class/style value forms; the "Attribute spreading" example reworks per
decision 2; changelog entry (user-visible behavior: "c-bind now spreads on
plain elements; class/style accept structured values; True/False/None
attribute semantics").

Phases 1 and 2 unblock the benchmark small-scenario port
(benchmarking.md phase 1); phase 3 is independent of it.

---

## 9. Interactions

- **Benchmarking** ([`benchmarking.md`](benchmarking.md)): the Button port
  uses `c-bind="attrs" c-class="[btn_class, 'no-underline']"`, exercising
  phases 1-2. The large scenario's 47 `{% html_attrs %}` uses all map to
  this feature.
- **Const folding** ([`constness.md`](constness.md)): literal-only
  `ElementAttrsNode`s fold; mixed ones fold their static members into the
  surrounding parts as today. No new pass needed.
- **HTML serialization rules** (CLAUDE.md gotchas): the `key=""` -> boolean
  normalization and void-element handling are unchanged; the new node emits
  the same conventions (bare key for `True`).
- **`data-cid` injection** (`citry_html_transform`): operates on the
  serialized HTML string downstream; unaffected.
- **Future component attrs fallthrough** (Vue `$attrs`): would reuse
  `merge_attrs` at the point where forwarded attrs meet the root element;
  decision 5 keeps it out of scope here.
- **Nested-template attribute values** (`c-foo="<span>...</span>"`):
  `TemplateHtmlAttr` resolves to rendered HTML; under the new node it is
  escaped into the attribute value like any other string (SafeString rules
  apply). Behavior today is the same, just via flattened codegen.

---

## 10. Open questions

Resolved with the maintainer (2026-06-11) and folded into the body above:
camelCase style properties are not accepted (section 3.3); `int` style
values stay, no auto-unit (section 3.3); `format_attrs` normalizes
structured class/style forms itself (section 5.1); class-conflict
resolution beyond positional merge stays out of core, served by the
`on_attrs_resolved` hook, which ships with phase 2 (section 5.5).

Nothing currently open.
