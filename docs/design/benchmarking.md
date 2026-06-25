# Design: rendering benchmarks (citry vs django-components vs Django)

**Status (2026-06-22): phases 1-3 built; first optimization pass done.** Phase
3 (the large scenario) is complete: all 35 components ported to citry, the full
`ProjectPage` renders, and `benchmarks/compare.py --size lg` publishes numbers
(citry ~2x faster startup/import, ~1.7x faster first render and ~3.1x faster
repeat render than django-components; see the results log in section 11).
Getting there fixed several real citry bugs the large, deeply-nested template
surfaced: feature A's Const-marker class/style regex, `c-bind="None"` tolerance
on plain elements and component/dynamic tags, and a `c-for`+`c-bind` parser
bug. A follow-up optimization pass then cut citry's repeat render from 1.85x a
bare Django template to 1.37x; what changed and what is left lives in
[`performance.md`](performance.md). Phases 4 (asv) and 5 (engines beyond the
Django family) are not started. This document
specifies how citry measures its template-rendering performance against
django-components (DJC) and vanilla Django templates: where the benchmark code
lives, how the harness runs it, what the two benchmark scenarios contain, and
which citry features are still missing to port them fully. Engines beyond the
Django family (Jinja2, MiniJinja, and others) are catalogued as future
additions in section 2.1.

This document is about *measuring*. For the *optimizing* that the measurements
drive (where the render time goes, what was changed to spend less of it, and
the paths that are candidates for moving into Rust) see
[`performance.md`](performance.md).

For the migration context (what citry keeps and drops from DJC) see
[`citry_migration.md`](citry_migration.md). For the Const optimization that
the `citry-const` variant exercises see [`constness.md`](constness.md).
For the JS/CSS dependency rendering that gates the large scenario see
[`asset_loading.md`](asset_loading.md) section 7.4. For operating rules see
[`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: django-components
[PR #999](https://github.com/django-components/django-components/pull/999)
(the benchmark suite and the "benchmarked code doubles as a pytest test"
convention this design reuses).

---

## 1. Prior art (what was searched)

In `~/repos/django-components` (the upstream repo, source of the scenarios):

- **`benchmarks/benchmark_templating.py`** (442 lines) is the whole asv
  benchmark suite. Two parametrized groups ("Components vs Django",
  "isolated vs django modes"), each measured across sizes (`sm`/`lg`),
  test types (`first` render, `subsequent` render, `startup`), and metrics
  (`timeraw_` wall time, `peakmem_` peak memory), plus one import-time test.
- **`benchmarks/utils.py:15`**: the `@benchmark(...)` decorator that maps
  friendly names, groups, and params onto asv's function-attribute
  conventions. `utils.py:71` `create_virtual_module` execs a source string as
  an importable module (needed for `peakmem_` tests, which run in-process).
- **`tests/test_benchmark_{django,djc}{,_small}.py`**: the benchmarked code
  itself, four fully self-contained scripts (inline `settings.configure`, all
  components, all data, a `gen_render_data()` and `render(data)` entrypoint
  at the top). Each ends with a pytest snapshot test, so the benchmark code
  is verified by the normal test suite.
- **The slicing trick** (`benchmark_templating.py:52-79`): the runner never
  imports the test files. It reads them as source strings, cuts at the
  `# ----------- TESTS START ------------ #` marker (dropping the pytest
  part), optionally cuts at `# ----------- IMPORTS END ------------ #` (for
  the import-time test), and regex-overrides the `CONTEXT_MODE` constant.
  `timeraw_` benchmarks return that string to be executed in a fresh process;
  `peakmem_` benchmarks exec it as a virtual module in-process.
- **`asv.conf.json`**: `virtualenv` environments, per-commit install via
  `pip install ./project`, results committed to the repo, HTML dashboard
  published with the docs site.
- **CI**: `pr-benchmark-generate.yml` + `pr-benchmark-comment.yml` run
  `asv continuous` between master and the PR head and post the comparison as
  a PR comment. `DJC_BENCHMARK_QUICK=1` trims the suite to the single test
  flagged `include_in_quick_benchmark` (`benchmark_templating.py:224`),
  because the full suite takes ~10 minutes. Release tags run the full suite
  and publish the dashboard.
- **Interpretation rules** (`benchmarks/README.md`): results are relative
  only, never absolute. Their "Django" variant still imports
  django-components and uses `{% html_attrs %}`, so it measures "the relative
  cost of using components", not pure vanilla Django. Citry inherits both
  caveats.

In this repo:

- **`packages/py/citry/tests/benchmark_const.py`**: the existing script-style
  benchmark (Const optimization). Establishes local conventions this design
  follows: plain script not collected by pytest, warmup render, output
  equality assert before timing, and the release-build warning (a debug
  `citry_core` build makes serialization ~12x slower and invalidates every
  number).
- **`packages/py/citry_core/tests/benchmark.py`** and **`benchmark_eval.py`**:
  micro-benchmarks of the Rust HTML transformer and of `safe_eval` dispatch.
  Different layer (citry_core primitives, not component rendering); they stay
  as they are.
- **`old_djccore_benchmark_eval.py`** (repo root): the djc-core ancestor of
  `benchmark_eval.py`, kept for reference.
- **The vendoring pattern**: `packages/py/citry/_djc_reference/` and
  `packages/py/citry/tests/_djc_tests/` already hold DJC material copied into
  this repo for porting work. Vendoring the DJC benchmark files continues an
  established pattern.
- **`docs/codebase.md`** "Running tests" and the root `pyproject.toml`:
  Python dev deps are mirrored between each package's
  `[dependency-groups].dev` and the root extras; any new benchmark deps must
  follow the same mirroring (until the uv workspace conversion,
  [#8](https://github.com/JuroOravec/citry/issues/8)).

---

## 2. Goal and scope

Two distinct uses, one set of benchmark files:

1. **Cross-engine comparison**: how does rendering the same UI compare across
   citry, django-components, and vanilla Django templates? This is a
   marketing-grade and sanity-grade number ("is the Rust-parser architecture
   paying off?") measured at one point in time.
2. **Longitudinal tracking**: how does citry's own rendering performance move
   commit to commit? This is what asv is for, and it only makes sense for
   citry's history (Django and DJC are pinned baselines that do not change).

Micro-benchmarks of citry_core primitives stay out of scope (they already
exist, section 1). Engines beyond the Django family are in scope as future
additions, below.

### 2.1 Future comparison targets beyond the Django family

The engine axis is open-ended by design: each engine is one self-contained
scenario file (section 5.2), so adding an engine never touches the others.
The Django family ships first because the scenarios come from DJC and stay
byte-comparable there. Candidates for follow-up engines, from a June 2026
scan of the Python HTML-rendering landscape (a maintained index to re-run
the scan later:
[awesome-python-html](https://github.com/hasansezertasan/awesome-python-html)):

| Candidate | What it is | Comparability |
|---|---|---|
| [Jinja2](https://jinja.palletsprojects.com/) | The de-facto Python template engine; compiles templates to Python bytecode (reportedly 10-20x faster than Django templates) | High. Macros approximate components, `{% call %}` blocks approximate slots. The baseline every reader knows. |
| [MiniJinja](https://github.com/mitsuhiko/minijinja) | Jinja2-compatible engine written in Rust, official Python bindings via PyO3/maturin | High, and the most interesting control group: the same Rust-core-plus-PyO3 architecture as citry, so it separates "Rust core" from "citry's design" in the numbers. |
| [JinjaX](https://jinjax.scaletti.dev/) | Component syntax (`<Component attr=...>`) on top of Jinja2 | High. The closest syntax peer in the Jinja world. |
| [django-cotton](https://django-cotton.com/) | HTML-like `<c-*>` component tags for Django templates | High. The closest syntax peer in the Django world (same `<c-` prefix), and a natural fourth row in the Django-family table. |
| [Mako](https://www.makotemplates.org/) | Compiled template engine, speed comparable to Jinja2 | Medium. Classical engine, no component model; `<%def>` blocks approximate components. |
| [Chameleon](https://chameleon.readthedocs.io/) | ZPT/XML-attribute templates, compiles to Python | Medium. Attribute-driven syntax is structurally close to `c-*` attributes, but no component model. |
| [htpy](https://htpy.dev/) / [Dominate](https://github.com/Knio/dominate) | HTML built by Python function calls / context managers | Medium. There is no template to parse or compile, so the `startup` and `first` columns measure something different; the `subsequent` column is the honest comparison. |
| [FastHTML](https://fastht.ml/) | Web framework over fastcore FT components (HTML-as-Python) | Medium. Same caveat as htpy, plus framework overhead; benchmark its component render path, not its server. |
| [Ludic](https://github.com/getludic/ludic) | Type-safe HTML components with htmx integration | Medium. Same HTML-in-Python caveat. |
| [Reflex](https://reflex.dev/) | Full-stack framework; Python compiles to a React/Next.js frontend | Low. There is no server-side HTML render to time, so this harness's metrics do not map; comparing it needs a different metric (e.g. time-to-first-byte of a served page). Listed for completeness, not planned. |

Suggested order when the time comes: Jinja2 first, MiniJinja second (the
architectural control group), then JinjaX / django-cotton (component-syntax
peers). Each addition is phase 5 work (section 8) and follows the same
scenario-file contract, including its own snapshot test.

---

## 3. Decisions that shaped the design

Decisions made with the maintainer:

1. **The benchmarks live in citry, not in django-components.** Three reasons:
   - Installability is one-directional. `django` and `django-components` are
     on PyPI; adding them to citry is a dev-dependency line. The `citry`
     package is unpublished (0.1.0) and sits on a locally-built `citry_core`
     via maturin, so installing it into the DJC repo would need path hacks
     plus a Rust toolchain in DJC's CI.
   - The longitudinal axis that matters is citry's commit history
     (section 2), and asv tracks the repo it lives in.
   - The vendoring direction already exists here (`_djc_reference/`,
     `tests/_djc_tests/`).
2. **Two-stage harness.** Stage one is a plain comparison script (the
   `benchmark_const.py` style) that runs all engine variants at HEAD and
   prints a table; stage two adopts asv for per-commit tracking and
   dashboards. The benchmark *files* follow the DJC marker convention from
   day one so stage two reuses them unchanged (section 5).
3. **Small scenario first; large scenario gated.** The small scenario needs
   one small citry feature (class/style attribute values, section 6.3
   feature A); the large scenario additionally needs dynamic tag names and
   JS/CSS dependency rendering (features B and C), so its citry port waits
   for those rather than shipping a lopsided comparison.
4. **Citry runs as two variants**: plain inputs, and `Const`-marked inputs
   where the optimization applies (section 6.4). The plain row is the
   cross-engine comparison; the Const row shows opt-in headroom.
5. **Missing citry features get implemented, not worked around.** Where the
   scenarios exercise something citry lacks (class/style value forms,
   dynamic tag names), the feature is built as a real, user-facing citry
   feature with its own design, and the benchmark port uses it. The one
   exception is Django forms, which are hand-written in the citry port
   (section 6.2).

---

## 4. The two scenarios

Both come from DJC and are kept byte-comparable on the DJC/Django side
(vendored nearly verbatim), with a citry reimplementation added as a third
variant.

- **Small** (`sm`): a single Button component (~340 lines). One component,
  kwargs with defaults, a computed CSS class, an if/else branch, attribute
  spreading, one default slot. Renders a button from
  `gen_render_data()` kwargs plus a `"content"` slot fill.
- **Large** (`lg`): a realistic project-management page (~6,000 lines):
  35 registered components (layout, navbar, sidebar, dialog, tabs, tables,
  forms, breadcrumbs, bookmarks...), a JSON data blob, custom filters,
  Alpine.js attributes throughout, provide/inject, 13 components with inline
  JS, and JS/CSS dependency rendering in the base layout.

Each scenario file exposes the same two entrypoints the harness calls:
`gen_render_data() -> data` and `render(data) -> str`.

Measured dimensions (mirroring DJC so numbers are methodologically
comparable):

| Dimension | Values |
|---|---|
| Engine | `django`, `django-components`, `citry`, `citry-const` (section 6.4) |
| Size | `sm`, `lg` |
| Test type | `startup` (class + template definition), `first` render, `subsequent` render |
| Metric | wall time (fresh process), peak memory, import time |

The DJC-only `isolated` vs `django` context-mode axis stays in the vendored
DJC files (it is one regex override) but is not part of the cross-engine
table; citry has no equivalent mode split. The `citry-const` row is the
mirror image: a citry-only axis with no DJC/Django equivalent.

---

## 5. File layout and harness

### 5.1 Layout

```
benchmarks/                         # repo root, mirrors DJC's layout
    README.md                       # how to run, how to read results
    compare.py                      # stage-one runner (section 5.3)
    utils.py                        # marker slicing + (later) asv helpers
packages/py/citry/tests/
    test_benchmark_citry_small.py   # citry port of the small scenario
    test_benchmark_citry.py         # citry port of the large scenario (phase 3)
    test_benchmark_djc_small.py     # vendored from DJC
    test_benchmark_djc.py           # vendored from DJC (phase 3)
    test_benchmark_django_small.py  # vendored from DJC
    test_benchmark_django.py        # vendored from DJC (phase 3)
```

The benchmarked files sit in `tests/` so pytest verifies them (section 5.2),
exactly as in DJC. The runner lives at the repo root because it spans
engines and (in stage two) hosts the asv suite. Future engines (section 2.1)
each add one `test_benchmark_<engine>{,_small}.py` file to the same
directory.

### 5.2 The scenario file contract

Each `test_benchmark_*.py` is self-contained and follows the DJC marker
convention:

- All imports first, ending with `# ----------- IMPORTS END ------------ #`
  (enables the import-time benchmark).
- Engine setup (for Django/DJC: inline `settings.configure`; for citry:
  `Citry()` instantiation), component definitions, data, and the two
  entrypoints `gen_render_data()` / `render(data)`.
- `# ----------- TESTS START ------------ #` followed by a pytest snapshot
  test that calls both entrypoints. Everything below the marker is invisible
  to the harness.

The harness reads the file as a source string and slices at the markers; it
never imports the module. This keeps the benchmark process free of pytest
and of the citry test venv's import state, and it is what lets the same file
serve asv's `timeraw_` (run string in fresh process) and `peakmem_` (exec
string as virtual module) modes later.

The vendored DJC files keep their `CONTEXT_MODE` trick: a module-level
constant near the top of the file that the runner overrides by regex to switch
the `isolated`/`django` context axis. The citry Const variant does not use
that trick; it is a separate scenario file (section 6.4), because per-component
`Const` placement cannot be expressed as a single flipped flag.

The vendored DJC/Django files require `django` and `django-components` at
test time. When those are absent (the default dev install), `tests/conftest.py`
skips collecting the files entirely. The skip lives in conftest rather than
as an importorskip inside the files so the vendored import section stays
byte-identical to upstream; the import-time benchmark slices and times that
section, and a test-infra import inside it would pollute the measurement.

### 5.3 Stage one: the comparison script

`benchmarks/compare.py`, in the style of `benchmark_const.py`:

- For each (engine, size, test type) cell: build the script by slicing the
  scenario file, append the setup lines (`gen_render_data()`, plus one warmup
  `render()` for the `subsequent` type), and time `render(render_data)` in a
  **fresh subprocess** (so startup state never leaks between cells, matching
  asv's `timeraw_` semantics). The `citry-const` engine reads its own scenario
  file (`test_benchmark_citry_const.py`); it exists only for the large size,
  so the small `citry-const` cell is skipped.
- Print one table per size: engine rows (including `citry-const`),
  test-type columns, with ratios against the Django baseline.
- Refuse to run (or warn loudly) when `citry_core` is a debug build, the
  same trap `benchmark_const.py` documents. How to detect the build profile
  cheaply is an open question (section 9); worst case the README warning is
  the guard.
- Not collected by pytest; run as
  `.venv/bin/python benchmarks/compare.py [--size sm|lg] [--quick]`.

### 5.4 Stage two: asv

Adopt asv once the files exist and stage one has produced first numbers:

- `asv.conf.json` at the repo root, results in `.asv/results/` (or committed,
  matching DJC, once there is a docs site to publish to).
- The suite file ports DJC's `benchmark_templating.py` structure: same
  decorator, same slicing helpers, with `renderer` gaining the `citry` and
  `citry-const` values.
- **The build step is the citry-specific work**: asv installs the project per
  commit, and citry needs a maturin release build of `citry_core` per
  benchmarked commit. This means a custom `build_command` (maturin build
  `--release`, then install the wheel plus the `citry` package) and a Rust
  toolchain wherever benchmarks run. Per-commit Rust builds are slow; the
  DJC-style quick subset (one flagged benchmark) is what makes PR runs
  viable.

Stage two is deliberately last: it adds tracking and dashboards, not new
information about citry vs DJC.

### 5.5 Dependencies

`django` and `django-components` go into a `benchmark` dependency group of
`packages/py/citry/pyproject.toml`, mirrored in the root `pyproject.toml`
extras with the usual cross-comments (the mirrored-deps gotcha in
`/CLAUDE.md`). They are not runtime deps and not part of the default dev
install. Future engines add their packages to the same group.

No snapshot plugin: upstream's syrupy snapshot asserts are replaced with
the observed output locked directly into the assert (the "observe, then
lock" rule in `/CLAUDE.md`), so the scenario tests use plain asserts like
the rest of the suite. DJC's random per-render `data-djc-id-*` marker is
regex-stripped inside the DJC file's assert only (upstream's `djc_test`
fixture played that role); citry's `data-cid-*` markers are deterministic
under the suite's conftest fixture and are asserted as-is.

---

## 6. Can citry express the scenarios? (feature audit)

Audited against the current `packages/py/citry/` runtime, June 2026. The
audit surfaced three citry features that the scenarios exercise and citry
does not have yet. Per decision 5 (section 3) they get built as real,
user-facing features, each with its own design; section 6.3 holds the
sketch-level specs and section 8 maps them onto phases.

### 6.1 Small scenario

| DJC construct in the Button file | citry equivalent | Status |
|---|---|---|
| `get_context_data(...)` with kwarg defaults | `Kwargs` class + `template_data()` | Ported as-is |
| `{% if %}` / `{% else %}` | `<c-if>` / `<c-else>` | Ported as-is |
| `{% html_attrs attrs class=x class="y" %}` | `c-bind` spread + class/style value forms | Needs feature A (section 6.3) |
| `{% if disabled %} disabled {% endif %}` (bare attribute) | `disabled: True` in the `c-bind` dict renders as a boolean attribute | Ported as-is |
| `{% slot "content" default / %}` | `<c-slot name="content">` filled via `slots={"content": ...}` | Ported as-is |
| `Button.render(kwargs=..., slots=...)` | `str(Button(**kwargs, slots=...))` | Ported as-is |

DJC's `{% html_attrs %}` *appends* duplicate `class` values where `c-bind`
is last-one-wins, so the honest port needs class values that merge. That is
exactly feature A; the citry port uses it rather than hand-merging strings
in `template_data()`, so the benchmark exercises the engine, not a
component author's workaround.

### 6.2 Large scenario

Three constructs needed citry features (A, B, C in section 6.3), all now
built; one item is a deliberate hand-port:

**Django forms.** The scenario defines real Django forms
(`ProjectAddUserForm` with `ChoiceField`s, `test_benchmark_djc.py:5127`) and
renders their fields. Django form widgets render through Django's own
template engine, which would smuggle Django's renderer into the "citry"
measurement. The citry port hand-writes the equivalent field HTML; Django
stays a data-generation dependency only (like `HttpRequest` and `csrf`
already are). The vendored DJC/Django variants keep the real forms.

Everything else maps mechanically:

| DJC construct (large scenario) | citry equivalent |
|---|---|
| `{% component "Name" %}` (35 registered components) | `<c-Name>` via the registry |
| `{% for %}` / `{% empty %}` / `{% elif %}` | `<c-for>` / `<c-empty>` / `<c-elif>` |
| `{% fill %}` incl. conditional and in-loop fills | `<c-fill>` (already tested in `test_slot_fills.py`) |
| `{% provide %}` | `<c-provide>` |
| `{% html_attrs %}` (47 uses) | `c-bind` + feature A |
| `<{{ form_content_tag }}>` dynamic tag (`:3775`) | feature B |
| `{% component_js_dependencies %}` / `{% component_css_dependencies %}` (`:2763`) | feature C |
| Filters: `json`, `alpine`, `js`, `get_item`, `escape`, `title`, `linebreaksbr`, `default_if_none` | plain function calls in expressions; helpers passed via template data (V3 has no filter syntax by design) |
| `{% define expr as var %}` (used once, `:1932`) | inline the expression at the use site |
| `{% static 'js/htmx.js' %}` (used once, `:2757`) | a `static()` helper passed via template data |
| Alpine attributes (`@click`, `:class`, `x-data`) | the names parse as-is (the grammar allows any non-delimiter chars). One catch: a static attribute's value is literal in citry (html_attrs.md), so an Alpine value that embeds `{{ var }}` (e.g. `@click="{{ model }} = ..."`) must use the dynamic `c-` form to interpolate, or it renders the braces verbatim |
| `mark_safe` | markupsafe / `mark_html()` |
| `naturaltime` (django.contrib.humanize) | small local reimplementation, so the citry file does not import Django at module level and the import-time benchmark stays honest |

### 6.3 New citry features this work drives

These are user-facing citry features that happen to be surfaced by the
benchmark port; each needs its own design before building, and they outlive
the benchmarks.

**Feature A - class/style attribute values (Vue/React style).** `class` and
`style` values, wherever they appear (static attribute, `c-class`/`c-style`
dynamic attribute, or an entry inside a `c-bind` dict), accept structured
forms that the engine normalizes at render time:

- `class`: a plain string, a list of strings, a dict of
  `{class_name: enabled_bool}` (falsy values drop the class), or a list
  mixing any of those (nested lists flatten).
- `style`: a plain string, a dict of `{css_property: css_value}`, or a list
  of those.
- Unlike all other attributes, where duplicates are last-one-wins (README
  "Attribute spreading"), multiple `class`/`style` sources on one element
  **merge**. This is a deliberate special case, matching Vue's class/style
  bindings.

Designed in [`html_attrs.md`](html_attrs.md). The audit there found the
scope is larger than value normalization: the compiler currently flattens
plain-element attributes into string chunks, so the feature also covers
`c-bind` spreading and boolean attribute semantics, and it includes a
compiler-output change (a structured element-attrs node). No grammar or
AST change. Needed by both scenario sizes.

**Feature B - dynamic HTML tag names.** The large scenario picks a tag at
render time (`<{{ form_content_tag }}>` resolving to div/table/ul,
`test_benchmark_djc.py:3775`). V3 tag names are static in the grammar. The
design adds a `<c-element is="...">` built-in (sibling of `<c-component>`,
which stays components-only) that renders a plain HTML element named at
render time; the Form case becomes `<c-element c-is="form_content_tag">`.
Designed in [`dynamic_component.md`](dynamic_component.md), built in
`39824bb`. Needed by the large scenario only.

**Feature C - JS/CSS dependency rendering.** Designed in
[`dependencies.md`](dependencies.md) and built in `9947f05`: the
`DependenciesExtension` (a built-in, on by default) collects each rendered
component's JS/CSS and injects the deduped result, and the `<c-js>`/`<c-css>`
built-in tags mark where it lands (default: CSS before `</head>`, JS before
`</body>`). `str(ProjectPage(**data))` therefore does the collection-and-inject
automatically, matching DJC's `{% component_js_dependencies %}` +
`ProjectPage.render(kwargs=data)`. Both engines also inject a client-side
dependency-manager core script; the port keeps both in the measured output
so the comparison stays fair.

### 6.4 The two citry variants: plain and Const

The large citry scenario runs as two engine rows:

- **`citry`**: plain inputs, matching what a naive user writes in every
  engine. This is the cross-engine comparable row.
- **`citry-const`**: a separate scenario file
  ([`test_benchmark_citry_const.py`](../../packages/py/citry/tests/test_benchmark_citry_const.py))
  in which each component's `template_data()` marks `Const` exactly the values
  that are the same on every render (literal attribute dicts, the module-level
  theme, slices of the icon table) and nothing derived from the per-render
  data ([`constness.md`](constness.md)). This row shows the headroom an
  opted-in user gets; it has no DJC/Django equivalent, so within the table it
  reads as "citry vs itself".

Mechanism: the const variant is its own file, not a flag on the plain file.
Marking constness is a per-value judgement (is *this* return value the same on
every render?), so it has to be written into each `template_data`, which a
runner-flipped switch cannot do. The earlier flag approach wrapped the whole
input tree in `Const`, which both over-promised (the project data is the
per-render input, not a constant) and did nothing: a `Const` container yields
non-`Const` elements when iterated and a `Const` dict yields non-`Const`
values when indexed, so a blanket mark never reaches the loop bodies that do
the rendering work. The honest result is that even a correct, hand-placed
`Const` pass folds almost nothing on this page, because a real project page is
mostly loops over dynamic data (see the section 11 log). The small scenario
has no const variant at all: its single Button computes everything it renders
from its inputs, so it has no render-invariant literal to mark.
`benchmark_const.py` remains the micro-level Const benchmark; this is the
scenario-level view of the same optimization.

### 6.5 Fairness notes

- **Each port uses its own engine's native patterns, not a literal
  translation.** The scenario (the UI, the data, the component breakdown) is
  fixed, but how each engine expresses it is idiomatic to that engine: Django
  uses its dict dot-access resolver and `|filters`, citry computes in
  `template_data` and uses Python subscripts / attribute access, a future
  Jinja2 port would use its own attribute-then-item resolution and macros.
  Forcing one engine's idiom onto another distorts the comparison. Concretely,
  citry resolves `{{ x.key }}` as Python attribute access (not a dict lookup),
  so the port reads nested data with subscripts or, more often, pulls the
  values out in `template_data` and passes flat variables to the template,
  which is the idiomatic citry shape. (An early draft wrapped the data in a
  dot-access dict subclass to mirror Django; measured at ~3.4x a plain
  subscript per access in the render path, it was dropped as both slower and
  non-native.)
- **Component inputs use each engine's real props mechanism.** DJC binds
  kwargs to its `get_context_data` signature every render (applying defaults,
  rejecting unknowns); the citry port declares a typed `Kwargs` dataclass per
  component, which does the equivalent binding. An early draft read a plain
  kwargs dict with `.get(...)` defaults, which skipped that work and quietly
  handed citry a small unfair edge; using `Kwargs` is both fairer and the
  idiomatic citry shape. A second self-inflicted edge was removed at the same
  time: an extension that injected ~21 helper functions into every
  component's scope each render (mimicking Django's global filters) cost
  ~19 us/render on the large page for one helper that was actually used, so
  the helpers are now plain functions called from `template_data`.
- **Release builds only.** All citry numbers require
  `uv run maturin develop --release` in `packages/py/citry_core` first; a
  debug build invalidates everything (the `benchmark_const.py` precedent).
- **Per-render ID attributes.** Citry output carries `data-cid-*` markers
  that DJC/Django output does not. They are part of citry's real cost, so
  the benchmarks never strip them; output is timed and snapshotted as
  rendered.
- **Outputs are not byte-identical across engines** (markers, attribute
  ordering, whitespace), so there is no cross-engine equality assert. Each
  scenario file carries its own snapshot test instead, same as DJC.

---

## 7. What gets vendored, and how it stays honest

The four DJC files are copied nearly verbatim (they were designed as
self-contained single files precisely so they could be lifted), with only:

- a header comment naming the upstream commit they were copied from,
- the pytest section adapted to citry's test conventions (locked-string
  asserts instead of syrupy snapshots; see section 5.5),
- no behavior edits. If an edit is ever needed, it goes in as a clearly
  marked, commented divergence.

The vendored files are excluded from ruff (root `pyproject.toml` excludes);
linting them would force edits that defeat the byte-close-to-upstream rule.

Pinning: the `benchmark` dependency group pins `django` and
`django-components` to exact versions, and the benchmark README records which
versions the published numbers refer to. Bumping the pins is a deliberate
act that re-baselines the comparison.

---

## 8. Implementation phases

**Phase 1 - small scenario, three engines. Done (2026-06-12).**

1. Design and implement feature A (class/style attribute values,
   section 6.3), with its own design note and tests. Standalone value even
   if benchmarks stalled here.
2. Add the `benchmark` dependency group (package + root mirror).
3. Vendor `test_benchmark_django_small.py` and `test_benchmark_djc_small.py`
   into `packages/py/citry/tests/`, adapt their pytest sections.
4. Write `test_benchmark_citry_small.py` per the section 6.1 mapping, using
   feature A, plus its snapshot test. (The small scenario has no Const
   variant; section 6.4.)
5. Verify all variants render correctly via pytest.

**Phase 2 - the comparison runner. Done (2026-06-12).**

6. `benchmarks/utils.py` (marker slicing) and `benchmarks/compare.py`
   (subprocess timing, table output, baseline ratios, the `citry-const`
   row), per section 5.3.
7. `benchmarks/README.md`: how to run, release-build requirement,
   relative-results-only interpretation rules (adapted from DJC's).
8. First published numbers (small scenario) land in the README.

**Phase 3 - large scenario. Done (2026-06-22).** All 35 components ported,
the full `ProjectPage` renders, lg numbers published (section 11).

9. ~~Design and implement feature B~~ (done, `39824bb`); feature C done
   (`9947f05`).
10. Vendor `test_benchmark_django.py` and `test_benchmark_djc.py`. Done.
11. Port `test_benchmark_citry.py` per the section 6.2 mapping (forms
    hand-written, helpers local, typed `Kwargs`, features A/B/C exercised),
    plus its Const variant as a separate file (section 6.4). Done; surfaced
    and fixed four citry bugs along the way (section 11).
12. `compare.py` runs `--size lg`; the lg table is published in the benchmarks
    README and the section 11 results log.

**Phase 4 - asv adoption (optional, after phases 1-3 prove out).**

13. `asv.conf.json` + suite file with the custom maturin `build_command`
    (section 5.4).
14. CI: a PR quick-compare job and a full run on release tags, modeled on
    DJC's `pr-benchmark-generate.yml` / `pr-benchmark-comment.yml`.

**Phase 5 - additional engines (section 2.1).**

15. One scenario file per engine, starting with Jinja2 and MiniJinja, then
    the component-syntax peers (JinjaX, django-cotton). Each lands with its
    own snapshot test and a README note on its comparability caveats.

Phases 1-2 gave the first citry-vs-DJC-vs-Django numbers. Phase 3's gates
(features B and C) are now built, so the large port is mechanical from here
(vendor, port, lock outputs).

---

## 9. Open questions

- **Detecting a debug `citry_core` build** from the runner, so `compare.py`
  can refuse to produce garbage numbers instead of relying on a README
  warning. (Possible angle: a build-profile flag exposed from the Rust crate;
  needs its own small design if pursued.)
- **Where published numbers live** once a docs site exists (DJC publishes the
  asv dashboard with its docs). Until then, the benchmarks README holds a
  dated results table.
- **How far does `Const` reach in the large scenario** (resolved): the
  `citry-const` file now marks `Const` on each component's render-invariant
  literals, the most a careful user could do by hand. It still folds almost
  nothing (the fold cache grows by one entry over the auto-marked baseline)
  and does not move the render time, because the page is loop-dominated and
  `Const` does not survive iteration or indexing into the per-render data
  (section 11 log, section 6.4). Closing that gap is a `constness.md` design
  question (propagating the marker through iteration/indexing), not a
  benchmark one.

---

## 10. Interactions

- **Class/style attribute values (feature A)** and **dynamic tag names
  (feature B)**: standalone user-facing features that this work surfaces;
  their designs land separately and they outlive the benchmarks. Feature B
  is a high-risk-area change (grammar/parser/compiler contract).
- **Dependency extension (feature C)** (asset_loading.md section 7.4,
  extensions.md phasing): phase 3's gate. The large scenario becomes its
  first integration-scale consumer and benchmark.
- **Const optimization** (constness.md): exercised at scenario level by the
  `citry-const` variant (section 6.4); `benchmark_const.py` remains the
  micro-level benchmark of the same machinery.
- **V3 parser work** (`crates/citry_template_parser/`): the large scenario is
  the biggest real-world template the parser will have seen; expect it to
  surface grammar and runtime edge cases (Alpine attribute names, deeply
  nested fills). That is a feature, not a risk: the pytest section catches
  breakage in the normal suite.
- **citry_core micro-benchmarks** (`packages/py/citry_core/tests/`):
  unaffected; different layer.

---

## 11. Results log

Dated snapshots of published numbers; `benchmarks/README.md` always carries
the latest table with the full how-to-reproduce context. Results are
relative values only (section 1, "Interpretation rules"): compare rows
within one run, never numbers across machines, runs, or build profiles.

### 2026-06-12 - small scenario, first numbers

Apple M4, Python 3.13.12, median of 5 fresh-process rounds per cell.
django 6.0.6, django-components 0.151.0, citry 0.1.0 (citry_core 1.3.0,
release build). Ratios vs the `django` row.

| engine | startup | import | first | subsequent |
|---|---|---|---|---|
| django | 75.35 ms (1.00x) | 71.45 ms (1.00x) | 1.11 ms (1.00x) | 39.5 us (1.00x) |
| django-components | 72.47 ms (0.96x) | 72.05 ms (1.01x) | 1.44 ms (1.29x) | 206.6 us (5.23x) |
| citry | 25.96 ms (0.34x) | 26.08 ms (0.37x) | 866.6 us (0.78x) | 58.9 us (1.49x) |
| citry-const | 26.05 ms (0.35x) | 25.80 ms (0.36x) | 849.7 us (0.76x) | 64.4 us (1.63x) |

Reading:

- citry imports and starts up about 3x faster than the Django stack, and
  beats even vanilla Django on first render.
- On repeat renders citry is about 3.5x faster than django-components,
  though ~1.5x slower than a bare Django template; the gap is the component
  machinery itself (per-render component construction, slot resolution, id
  marking).
- `citry-const` shows no benefit on this scenario: the Button template is a
  single element, so almost nothing is left to fold, while computing the
  fold-cache key still costs a little per render. Expected, not a bug; the
  optimization targets templates with large constant regions, so the large
  scenario (phase 3) is its fair test.

### 2026-06-22 - phase 3 (large scenario) port: progress and findings

The large `lg` scenario is being ported bottom-up. Done and verified so far:
the two DJC baselines (`test_benchmark_django.py`, `test_benchmark_djc.py`)
vendored and rendering via a structural smoke test; the citry foundation
(data blob, types, constants, theme, helpers, the DJC filters reimplemented
as plain functions injected into every component via a small
`on_component_data` extension, and `gen_render_data`); and the leaf
components Button, Icon, HeroIcon, each verified rendering in isolation. The
citry scenario file's smoke tests are skipped until the whole `ProjectPage`
tree is in (its `render()` references components not yet ported).

The port is proving the translation patterns end to end (registration by
`name`, class/style merge, dynamic-element branches, slots, nested
components, loops, dynamic kwargs all work), and it surfaced two citry issues
in line with this doc's prediction that the 6,000-line template would shake
out parser/runtime edge cases:

- **`c-bind` of `None` (fixed).** An optional attribute dict that resolves to
  `None` now contributes nothing instead of raising, matching Vue's
  `v-bind="null"` and DJC's `{% html_attrs %}`. Without it, nearly every one
  of the 47 `html_attrs` ports would need an `or {}` guard. A non-`None`,
  non-mapping value still raises.
- **`c-for` + `c-bind` on the same element referencing the loop variable
  (fixed).** `<path c-for="p in items" c-bind="p" />` wrongly failed to parse
  ("variable ... already taken"). Root cause: a bodied node drops its
  introduced loop variable from `used_variables`
  (`ast::from_start_and_end_tags`), but the self-closing and void-element
  paths in the parser did not, so the same-element `c-bind` use of the loop
  variable looked both used and introduced and tripped the shadowing check.
  The three node-construction sites now share one
  `remove_introduced_variables` helper. The loop variable is in scope for its
  own element's attributes (matching Vue's `v-for`), so the port uses the
  direct form with no wrapper.

(The `on_component_data` helper-injection extension mentioned above was later
removed; see the 2026-06-22 completion entry for why.)

### 2026-06-22 - phase 3 (large scenario) complete, first lg numbers

All 35 components are ported and the full `ProjectPage` renders (~205 KB,
~325 component instances). `benchmarks/compare.py --size lg`, Apple M4,
Python 3.13.12, median of 5 fresh-process rounds; django 6.0.6,
django-components 0.151.0, citry 0.1.0 (citry_core 1.3.0, release). Ratios vs
`django`:

| engine | startup | import | first | subsequent |
|---|---|---|---|---|
| django | 77.19 ms (1.00x) | 70.10 ms (1.00x) | 17.42 ms (1.00x) | 10.64 ms (1.00x) |
| django-components | 75.69 ms (0.98x) | 69.76 ms (1.00x) | 65.18 ms (3.74x) | 45.45 ms (4.27x) |
| citry | 38.17 ms (0.49x) | 29.28 ms (0.42x) | 41.92 ms (2.41x) | 19.63 ms (1.85x) |
| citry-const | 37.49 ms (0.49x) | 29.13 ms (0.42x) | 43.80 ms (2.51x) | 19.74 ms (1.86x) |

citry is ~2x faster than the Django stack on startup/import, and against
django-components (the fair component-vs-component comparison) ~1.5x faster on
first render and ~2.4x faster on repeat renders. Both component engines trail
a bare Django template, which does none of the per-render component work;
"relative cost of components" is the meaningful axis and citry wins it.
`citry-const` is within noise of plain citry (see the Const finding below).

Findings from completing the port, beyond the two parser/attr fixes in the
progress entry above:

- **Helper injection was a DJC-ism, removed.** An extension injected ~21
  filter/builtin helpers into every component's scope each render to mimic
  Django's global filters; only one was used in a template. The helpers are
  now plain functions called from `template_data` (the idiomatic citry shape).
- **AttrDict was a DJC-ism, removed.** An early draft wrapped the data in a
  dot-access dict subclass to keep DJC's `{{ x.key }}`; measured ~3.4x a plain
  subscript per access, so the port computes values in `template_data` and
  uses subscripts instead. Both are recorded under section 6.5.
- **Typed `Kwargs` per component.** Components declare a `Kwargs` dataclass
  (matching DJC's `get_context_data` signature), so citry does the same
  props-binding work DJC does each render rather than reading a plain dict.
- **`c-bind="None"` tolerance extended to component/dynamic tags.** The plain
  element fix did not cover `<c-Foo c-bind="opt">` / `<c-element>`;
  `ComponentNode._resolve_kwargs` now treats `None` as no kwargs too.
- **O(n*depth) dependency-emission bug (fixed).** First lg run had citry ~37x
  slower than Django. Root cause: a component's `DependencyRecord` is copied
  into each ancestor as nested renders merge, so a 325-instance page resolved
  ~154,000 records, and `_resolve_records` did a cached-script lookup (with a
  `json.loads`) per duplicate. Collapsing duplicate records first (they
  resolve to identical scripts) cut repeat renders ~32x, to the numbers above.
  This is the large benchmark's main payoff: a real scaling bug invisible at
  small scale.
- **Const variant reworked from a blanket flag to per-component literals.**
  The first cut wrapped the whole input tree in `Const` via a single
  runner-flipped flag. That was wrong twice over: it falsely promised the
  per-render project data was constant, and it folded nothing, because a
  `Const` container yields non-`Const` elements when iterated and a `Const`
  dict yields non-`Const` values when indexed, so the marker never reached the
  loop bodies. The variant is now a separate file
  (`test_benchmark_citry_const.py`) where each `template_data()` marks `Const`
  only its render-invariant literals (literal attribute dicts, the theme, icon
  paths). This is the correct usage, and it still grows the fold cache by one
  entry (50 to 51) and leaves render time unchanged: those literals are
  consumed by child components that mix them with dynamic data, so they do not
  fold either. The honest conclusion is that `Const` does not help a
  loop-over-data page; it is built for templates with large static blocks.
  Propagating the marker through iteration/indexing is a `constness.md`
  question, separate from the benchmark.

### 2026-06-22 - render-path optimization pass

Profiling the large `subsequent` render (cProfile on a warm render, plus
in-process A/B timing per change) drove a round of render-path fixes. citry's
repeat render dropped from 19.63 ms to 14.52 ms (1.85x a bare Django template
down to 1.37x; about 3.1x faster than django-components). Apple M4, Python
3.13.12, median of 5 fresh-process rounds; same versions as above. Ratios vs
`django`:

| engine | startup | import | first | subsequent |
|---|---|---|---|---|
| django | 77.25 ms (1.00x) | 69.75 ms (1.00x) | 17.77 ms (1.00x) | 10.60 ms (1.00x) |
| django-components | 77.16 ms (1.00x) | 70.90 ms (1.02x) | 64.11 ms (3.61x) | 45.73 ms (4.31x) |
| citry | 38.51 ms (0.50x) | 29.02 ms (0.42x) | 37.57 ms (2.11x) | 14.52 ms (1.37x) |
| citry-const | 37.85 ms (0.49x) | 29.52 ms (0.42x) | 38.22 ms (2.15x) | 14.61 ms (1.38x) |

The biggest win was a dependency-collection scaling fix (records bubbled up by
copying into every ancestor, ~470,000 copies on this page, now an
insertion-ordered set that dedupes on merge); the rest were render-path trims
(one-pass attribute formatting, escaping to `str` instead of allocating a
`Markup` per piece, and a cheaper per-component id). The full record of what
changed, why, and the cost model behind it is in
[`performance.md`](performance.md) section 4; that doc also tracks the
remaining Python-level work and the paths that are candidates for moving into
Rust to close the rest of the gap to a bare Django template.
