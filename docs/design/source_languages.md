# Design: source languages (template / js / css) and their tooling

**Status (2026-07-01): design agreed, not yet built.** This document is the
umbrella design for a question that spans three tracks already filed as issues:
how a component declares the *language* its `template` / `js` / `css` is written
in, how that source is compiled ([#10](https://github.com/citry-dev/citry/issues/10),
the asset compiler), and how editors give it syntax highlighting
([#24](https://github.com/citry-dev/citry/issues/24)) and semantic intelligence
([#23](https://github.com/citry-dev/citry/issues/23), the language server). It
records the decisions, the reasoning behind them, and the prior art we surveyed,
so the three implementing tracks start from a shared model rather than
rediscovering it.

"Source language" here means the dialect a component's template/style/script is
authored in (HTML, Markdown or Pug for the template; JS or TS for the script;
CSS, SCSS or Sass for the style). It is **not** the host binding language
(Python, JS, PHP, Go); that is a separate axis covered in
[`../codebase.md`](../codebase.md).

Related: the asset-loading pipeline this sits on
([`asset_loading.md`](asset_loading.md)), the dependency system that consumes the
compiled output ([`dependencies.md`](dependencies.md)), and the extensions
roadmap that classifies the surrounding tooling
([`extensions_roadmap.md`](extensions_roadmap.md)).

---

## 1. The problem, and the three concerns not to conflate

A component carries up to three source bodies, each either inline or in a file:

```python
class Card(Component):
    template = "<div>{{ title }}</div>"   # or template_file = "card.html"
    js = "$onComponent(({els}) => {...})"  # or js_file = "card.ts"
    css = ".card { color: red }"           # or css_file = "card.scss"
```

Most components write the defaults: HTML template, JS script, CSS style. But we
want to support other dialects too: a Markdown or Pug template, a TypeScript
script, an SCSS or Sass stylesheet, and eventually user-defined dialects.

Supporting that pulls in three genuinely different concerns, and the whole design
gets muddled if they are treated as one:

1. **Declaration** - how the author says "this block is SCSS / Pug / TS." A file
   can self-declare by its suffix (`card.scss`); an inline string cannot, so it
   needs an explicit signal.
2. **Compilation** - turning the declared source into what the browser (or the
   citry template parser) consumes: SCSS to CSS, TS to JS, Markdown to HTML. This
   is the asset compiler ([#10](https://github.com/citry-dev/citry/issues/10)).
3. **Editor experience** - two sub-concerns that are often confused with each
   other: **syntax highlighting** (coloring the string) and **semantic
   intelligence** (completion, go-to-definition, type checking, diagnostics).
   These need very different machinery.

The rest of this doc takes them in that order. The short version of the
conclusions: declaration is a `*_lang` string attribute; compilation is a
pluggable registry; and the editor experience is a dedicated language server
whose *rich* support covers a smaller, curated set of languages than the compiler
can compile.

---

## 2. Declaration: `*_lang` string attributes (not type annotations)

**Decision.** A component declares a non-default source language with a plain
class attribute:

```python
class Card(Component):
    template_lang = "markdown"   # default None
    css_lang = "scss"            # default None
    js_lang = "ts"               # default None
    template = "# Title\n\n{{ subtitle }}"
    css = "$brand: red; .card { color: $brand }"
```

**Defaults are `None`, which means "infer", and that is deliberately different
from an explicit value.** Resolution:

- `*_lang` is `None` (the default): infer the language. For a file body, from its
  suffix (`css_file = "card.scss"` is SCSS). For an inline body, the base dialect
  (`html` / `js` / `css`), since a string literal has no suffix.
- `*_lang` is set explicitly: that value wins, and it **overrides a file's
  suffix**. `css_file = "card.txt"` with `css_lang = "scss"` compiles as SCSS.

So a component that writes the common case declares nothing, and `None` (infer)
stays distinguishable from an explicit `"html"` (force html even when the file
says otherwise). That distinction is why the default is `None` rather than the
base dialect name.

The value is a bare language name that matches an entry in the compiler registry
(section 3). The set of legal values is therefore whatever is registered:
citry's built-ins plus anything the user added. It is finite at any moment but
open, exactly like Svelte's and Vue's `lang` attribute.

### 2.1 The alternative we rejected: typed string aliases

django-components ships `types.py` with PEP 593 annotated aliases and lets
authors write the language into the type position:

```python
# django-components
from django_components import types
class Card(Component):
    template: types.django_html = "<div>...</div>"
    css: types.css = "..."
```

We considered porting this (it was a to-migrate item in the migration review) and
rejected it as the declaration mechanism. What we found:

- **django-components never reads these annotations at runtime.** A grep of the
  reference finds zero `get_type_hints` / `__metadata__` access; the aliases are
  defined in `types.py` and used nowhere else. They are purely an editor hint.
  So they do not, and cannot as written, drive a compiler.
- **They require an import** (`from ... import types`) and put build-relevant
  configuration in the type position, which is a surprising place for it.
- **The decisive point is pluggability.** A user-registered compiler is just a
  name string. With `*_lang`, plugging it in is symmetric and needs no ceremony:
  register the compiler under `"mypug"`, then write `template_lang = "mypug"`.
  With annotations, the same custom language forces the user to *also* define and
  import a matching alias type (`mypug = Annotated[str, "mypug"]`) purely to
  annotate with it. That extra step scales badly across an open compiler set.
  Svelte proves the pattern: custom languages are strings in an alias dictionary,
  never type-level constructs.
- **The two editor ecosystems do not even agree on the marker.** The VS Code
  extension that reads the annotation (`python-inline-source`, and the citry
  maintainer's fork `jurooravec.python-inline-source-2`) reads the PEP 593
  metadata; PyCharm ignores annotations entirely and uses a `# language=HTML`
  *comment* before the string. So the annotation is not a portable highlighting
  key either; it works only for one extension in one editor.

Naming footnote: had we kept an HTML alias its citry name would have been `html`
(the component context already implies citry), not `django_html`. Moot given the
decision.

### 2.2 Why `*_lang` on the merits (not because it was written down first)

- **No import**, and it keeps build configuration out of the type position.
- **It is the Vue/Svelte `lang=` pattern**, which authors of those frameworks
  already know.
- **It composes with a pluggable registry with zero ceremony** (section 2.1).
- The value is plain data the runtime reads directly, and an editor tool can read
  a class-attribute assignment from the AST just as easily as an annotation.

The one thing type annotations buy that `*_lang` does not is highlighting *today*
via the unmodified `python-inline-source` extension. We are deliberately not
taking that (section 4.4): it is a dead end that cannot grow into the real editor
experience, and shipping an annotation surface we would later regret is worse
than having no interim highlighting.

---

## 3. Compilation: a pluggable, finite-but-extensible compiler registry

This is issue [#10](https://github.com/citry-dev/citry/issues/10); the full
prototype notes live there. The parts that matter for this doc:

### 3.1 The registry

A component's source is matched to a compiler. django-components' prototype keyed
the registry by file type:

```python
compilers = [
    ("js", re.compile(r"\.(?:js|ts|jsx|tsx|mjs)$"), ts_compiler),
]
```

For citry the same registry is keyed two ways, because inline source has no file
suffix:

- **File source** matches by suffix / pattern (`.scss` to the sass compiler),
  the way Eleventy, Parcel and every bundler match by extension.
- **Inline source** matches by the `*_lang` name (section 2), the way Svelte's
  `lang="scss"` selects a preprocessor.

Both resolve to the same registered compiler, so `css_file = "card.scss"` and
`css_lang = "scss"` + inline `css` run through one code path.

### 3.2 Built-in versus user-registered (the extensibility model)

The registry is **built-ins plus user-registered**, so the legal language set is
finite at any moment but open. citry ships compilers for the common dialects
(as they get built: templates html / markdown / pug; scripts js / ts / jsx /
tsx; styles css / scss / sass / less), and a project adds its own through a
registration API (shape still open, section 8: `Citry(compilers=[...])`, a
settings entry, or an extension hook).

This is squarely the industry model. We confirmed it across the ecosystem:

- **Svelte / svelte-preprocess** is the closest analogue. `lang` / `src` / `type`
  selects a preprocessor, and the set is explicitly extensible: you register a
  custom preprocessor and extend the alias dictionary
  (`['cst', 'customLanguage']` routes `lang="cst"` to it). A preprocessor is a
  plain function receiving `{ content, attributes, filename }` and returning
  `{ code }`.
- **Vue** ships a built-in preprocessor set but is extensible via configuration
  (`preprocessLang`, `preprocessCustomRequire` in `SFCStyleCompileOptions`) and,
  in practice, via the bundler loader layer (vue-loader / Vite plugins).
- **Eleventy** exposes `addExtension(ext, { compile })`, registering any file
  extension with a `compile(inputContent, inputPath)` function that returns a
  render function, plus `addDependencies` for incremental-build cache keys. It is
  the "register a custom template language" API in its purest form.
- **Parcel** transformer plugins "transform a single asset to compile it ... many
  transformers are wrappers around other tools such as compilers and
  preprocessors," matched by file type.
- **Astro's** integration API is "inspired by Rollup and Vite" plugin shapes.
- **esbuild / Vite / Rollup / webpack** plugins all claim inputs by a filter
  (regex on path / namespace) and transform. This is the same registry shape.

Takeaway for citry: the registry (name-or-pattern to compiler function, built-ins
plus user entries) is a well-trodden design; citry's contribution is only the
inline-`*_lang` keying alongside file-suffix keying.

### 3.3 When compilation runs: an open question, not a settled split

The django-components prototype ran js/css compilation at **build time** (a
`collectcomponent` command that subclassed Django's `collectstatic`, wrote hashed
files to `STATIC_ROOT`, and recorded per-component meta files) and template
dialects (Markdown/Pug) at **render time** (right after the template renders,
before any HTML post-process hook). That split was shaped by the Django ecosystem
it lived in, and citry should **not** adopt it uncritically. This area needs its
own design pass. The open threads:

- **Why not pre-compile templates too?** A Markdown template `- Hello {{ name }}`
  could compile once to `<ul><li>Hello {{ name }}</li></ul>` (treating `{{ }}` as
  opaque text to preserve), and only the resulting citry-HTML is rendered per
  request. So template-dialect compilation and per-render `{{ }}` rendering are
  separable, and the dialect step could be a first-load step like js/css rather
  than a per-render one. What Markdown/Pug do with `{{ }}` and `<c-*>` (pass
  through verbatim, escape, or interpret) is itself a design question.
- **What is the lifecycle "freeze" point?** A bulk compiler that processes all
  files together needs a moment where citry can say "these are all the components,
  this is the complete js/css set." The only natural such moment is after
  autodiscovery has imported the component modules, which already runs Python to
  find, load, and resolve component paths and contents. So a citry "build" is not
  a separate world the way `collectstatic` is; it is just a point in a `Citry`
  instance's lifecycle.
- **Lazy-at-first-render may be simpler than a bulk build.** If the compiler runs
  per component the first time it is needed and the class caches the compiled
  js/css/template, there is no freeze point to arrange at all.
- **Then the "static directory" is a cache, not an export.** If compiled output is
  written to disk only to avoid recompiling (keyed by a content hash), that is an
  optimization (a `.citry_cache/` directory), not a `collectcomponent` /
  `collectstatic`-style export. Those export commands exist to hand assets to
  *further* processing (a CDN, whitenoise, another build step), a different intent.
- **Per-file or in bulk? The industry does per-file for the transform, and bulk
  only for bundling.** Vite compiles each module on demand in dev (esbuild,
  per-file, so startup does not grow with app size) and does a whole-graph pass
  only for the production bundle, because code-splitting and tree-shaking need the
  complete module graph to find shared chunks. Eleventy compiles per-file. The
  django-components prototype batched precisely because it wanted cross-component
  code-splitting (esbuild `--splitting`) and one type-check pass. So batching
  exists *for bundling*. If citry does not bundle across components (the likely
  conclusion above), a local per-file transform, run lazily and cached, is the
  natural and simpler fit.

**Provisional takeaway:** a django-style `collectcomponent` static export is
likely **not** a citry feature. citry's compilation is more likely lazy (or a
lifecycle step after autodiscovery) plus a content-hash cache, with "export these
built assets for a CDN" treated as a separate, optional concern if it is wanted at
all. Settle this before building #10.

One thing survives regardless of *when* compilation runs: a template dialect
(Markdown/Pug) turns into citry-HTML that the citry parser then interprets, which
is what makes the editor story for template dialects subtle (section 6.3).

---

## 4. Editor experience: highlighting is not intelligence

The single most important distinction in this whole design:

- **Syntax highlighting** colors a region according to a language. It is
  delivered by a grammar (a TextMate injection grammar, or a tree-sitter
  injection). It is comparatively cheap and needs no understanding of the code.
- **Semantic intelligence** (completion, hover, go-to-definition, find-references,
  type checking, diagnostics) requires a *language service* that actually parses
  and resolves the code. It is expensive and specific to each language.

Type annotations, comment markers, and grammars can buy the first. Only a
language service buys the second. Conflating them is what makes "just add type
aliases" look more capable than it is.

### 4.1 How django-components and the Python editors do highlighting

Two unrelated mechanisms, one per editor family:

- **VS Code**: the `python-inline-source` extension (by samwillis; the citry
  maintainer runs a fork, `jurooravec.python-inline-source-2`) parses the Python
  AST, reads the `Annotated[str, "html"]` metadata, and applies a grammar to the
  string contents.
- **PyCharm / JetBrains**: native "language injections" read a `# language=HTML`
  comment placed before the string (optionally with `prefix` / `suffix`). It does
  not read type annotations at all.

Both are highlighting only. Neither gives citry-aware completion or variable
resolution, and they disagree on the marker, so neither is a portable foundation.

### 4.2 The three ways a block gets *semantic* support (and why the compiler is none of them)

This is what we set out to answer: in frameworks that allow preprocessing, do the
language servers give semantic features for every preprocessor language, or only
first-class ones, and do custom preprocessors plug into the language server too?

The answer is that **build-time preprocessing and editor-time intelligence are
two decoupled systems.** A block gets semantic support in exactly one of three
ways, and registering a build compiler is none of them:

1. **A bundled language service (a first-class, closed set).** Vue's tooling
   (Volar) gives full style features for **CSS, Less and SCSS only**, because
   those ride `vscode-css-languageservice`. **Stylus, PostCSS and indented Sass
   get highlighting only**, no semantic service, even though the build can
   compile them. The `<script>` block rides the TypeScript service. That fixed
   set is the whole of the "free" semantic support.
2. **A hand-written language-server plugin, per language.** To get *template*
   intelligence on Pug, someone wrote `@vue/language-plugin-pug` (formerly
   `@volar/vue-language-plugin-pug`), which compiles Pug into the Vue template
   AST so Volar's existing template engine applies. This is a **different piece
   of code from the build-time Pug preprocessor**, and it is not automatic:
   installing the package is not enough, you must register it in `tsconfig.json`
   under `vueCompilerOptions.plugins`. There is even an open issue asking for
   "transparent installation" precisely because it is a manual, explicit,
   per-language wiring step.
3. **Sourcemaps (partial).** Svelte's model: `svelte-preprocess` emits sourcemaps,
   and the language server computes features on the *compiled* output and maps
   positions back to source. This gives limited diagnostics mapping, not true
   source-language completion, and the docs call out the asynchronous
   position-mapping limits.

Volar.js generalizes mechanism 2 into a framework: a "language plugin" supplies
`createVirtualCode` / `updateVirtualCode` that map your source into embedded
standard languages, and the framework wires the LSP requests through. It makes
custom-language semantic support *possible*, but you still author the mapping per
language; it is never free.

The structural conclusion, and the design principle citry adopts: **the set of
languages you can compile is deliberately larger and more open than the set you
give rich editing.** Vue can build many bundler preprocessors but gives semantic
support to css/less/scss plus a hand-written pug plugin; Svelte can preprocess
many languages but gives editing to ts/scss/less plus sourcemap mapping. citry
should adopt this split consciously rather than imply that `*_lang`
extensibility buys editor intelligence.

### 4.3 Why the real editor experience needs a citry language server

citry's templates are not plain HTML: they carry `<c-*>` tags, `{{ ... }}`
(Python expressions), `{# ... #}`, and `c-*` attributes whose values are either
Python expressions or nested templates. The experience we want (the Vue/React
feel: hovering a template variable, jumping to where it is provided, red squiggles
on a typo, completion of a component's declared inputs) is variable resolution and
type flow across those constructs. A grammar cannot do it; only a language service
that understands citry's AST can. Two more citry-specific behaviors have the same
requirement: the `css_data()` return values that become CSS custom properties
should be recognized inside the style block, and the `$onComponent()` magic in the
script block should be understood by the js tooling.

The parser already tracks what such a service needs: each scope-introducing node
(`<c-for>`, `<c-fill>`) records its `used_variables` and `introduced_variables` as
tokens with source positions ([#23](https://github.com/citry-dev/citry/issues/23)
has the harvested notes). So the language server is buildable, but it is a large,
dedicated effort, not a side effect of anything else.

### 4.4 Decision: no interim highlighting; the language server is the editor investment

We are **not** shipping the typed aliases and **not** teaching the
`python-inline-source` fork to recognize citry components as a stopgap. When
citry invests in the editor, it invests in the full language server / VS Code
extension directly. The consequence, accepted deliberately: **until that ships,
inline template/js/css strings get no citry-provided editor support.** The
rationale is that a highlight-only stopgap is a dead end that cannot grow into
semantic support, and every stopgap marker (an annotation surface, a comment
convention) is something to maintain and later regret. Better to arrive once, at
the right layer.

### 4.5 How the pieces fit in an editor, and the incremental build path

This decides how the editor effort can be staged, so it is worth stating. There
are three layers, and one extension can own all of them:

1. **Syntactic highlighting: a TextMate grammar.** A static, declarative grammar
   (regular expressions) that tokenizes a file with no understanding of it. Fast,
   always on, no delay. **Injection grammars** are the embedded-language tool:
   they splice one language's grammar into marked regions of another, which is how
   a citry-HTML grammar would color `{{ }}` as Python, `<style>` as CSS, and so
   on. The grammar is contributed by the extension (in its `package.json`), not by
   a separate process.
2. **Semantic highlighting: semantic tokens from a language server.** The editor
   asks the server (over LSP) for tokens it can only know by resolving symbols in
   context, and paints them *on top of* the grammar colors. Delayed (the server
   has to analyze) and refines, rather than replaces, the grammar layer.
3. **Language intelligence: the language server.** A separate process (any
   runtime, e.g. `node server.js`) that speaks LSP and answers completion, hover,
   go-to-definition, find-references, and diagnostics. For embedded languages it
   keeps its own virtual-document model (the Volar.js approach) and maps or
   delegates regions itself; the editor does not split *semantic* regions on its
   own.

A caveat on the grammar layer, because it bears on citry directly: a TextMate
grammar is regex plus a stack of `begin`/`end` contexts, so it has state (it
knows it is inside a tag, a string, a comment) but it does not backtrack and
cannot truly *count*. It never matches an opening `<div>` to its `</div>` (it
colors tag structure by context, which is all coloring needs; validating nesting
is semantic). And a naive `{{` ... `}}` rule ends at the *first* `}}`, so an
expression whose value contains braces, like `{{ {'a': {}} }}` or `{{ "}}" }}`,
mis-detects the boundary. A grammar can be pushed a long way with recursive
brace-tracking and string-consuming sub-rules, but it stays an approximation with
edge cases. The fully correct boundary needs a real parser, which is the semantic
layer: the language server runs citry's parser and emits semantic tokens that
override the grammar, and/or citry ships a **tree-sitter** grammar (a real
incremental parser with injection support, used by Zed, Neovim, and others)
instead of or alongside TextMate. Since citry already has a parser, a tree-sitter
grammar is the natural way to get correct highlighting boundaries without waiting
for the full language server.

So the mental model is right in shape, with two refinements: highlighting is
normally the *same* extension contributing a grammar (not necessarily a separate
extension), and "which region is which language" is answered twice by different
layers, statically by injection grammars for color and dynamically by the
language server for semantics.

**Yes, one citry extension can deliver both highlighting and intelligence**, and
that is the norm (Vue's official extension bundles the grammar and the
language-server client together). And **yes, it can be built incrementally**,
which is the standard path:

1. **Skeleton / wiring.** The extension plus a language contribution (file
   association, comment and bracket config). No coloring, no intelligence yet.
2. **Syntax highlighting.** Add the TextMate grammar and injection grammars for
   citry-HTML (`<c-*>`, `{{ }}`, `{# #}`, embedded `<script>` / `<style>`). Static,
   no server, ships on its own and is already a real improvement.
3. **Language intelligence (much later).** Add the language server for completion,
   go-to-definition on template variables, diagnostics, `css_data` custom
   properties, `$onComponent`. The large lift, additive to the previous layers.

Each layer stands on its own, so the editor work sequences skeleton to
highlighting to intelligence without rework.

---

## 5. What "first-class" means for a Python component framework

Translating the three mechanisms of section 4.2 into citry's world:

- **Bundled service, delegated:** citry's language server can delegate the default
  `css` block to `vscode-css-languageservice` (so css / scss / less come along
  for free, exactly as in Vue) and the default `js` block to the JS/TS service,
  then layer citry's additions on top (`css_data()` custom properties,
  `$onComponent`).
- **citry's own service:** the default `html` template is citry's *own* embedded
  language (the `<c-*>` / `{{ }}` / `{# #}` engine). Nobody else provides this;
  it is the whole reason to build the language server and the core of its value.
- **Per-language mapping, hand-written:** an alternative *template* dialect
  (`template_lang = "markdown"` or `"pug"`) needs a dedicated mapping that
  compiles the source to the citry-HTML template AST and maps positions back,
  the `@vue/language-plugin-pug` pattern. Each such dialect is a deliberate
  investment.
- **Highlight-only / sourcemap fallback:** a custom or unrecognized `*_lang` gets,
  at most, highlighting (if a grammar for that source language is installed) or
  sourcemap-mapped diagnostics (if its compiler emits sourcemaps). No citry
  semantics unless someone writes the mapping. This should be documented as
  honestly as Vue documents "Stylus / PostCSS get highlighting only."

---

## 6. citry's architecture (the design that falls out)

### 6.1 Two sets, different sizes, on purpose

- **The compile set (`*_lang` registry):** open and pluggable. Anyone registers a
  compiler; no editor promise attached.
- **The rich-editing set (language server):** curated and closed, grown only by
  deliberate per-language work: the default citry-HTML template (citry's own
  service), the default css (delegated + `css_data`), the default js (delegated +
  `$onComponent`), and whatever alternative template dialects citry chooses to
  hand-map.

Writing this down prevents the most likely design mistake: assuming that because a
project can register a Pug compiler, its Pug templates will also get citry
template intelligence in the editor. They will not, unless a Pug language mapping
is also written and wired.

### 6.2 One declaration, several readers

The `*_lang` attribute (plus the file suffix) is the single declaration, read by:

- the **compiler registry** at build time (js/css) or render time (template md/pug);
- the **language server** to decide which service or mapping to apply to a block;
- any **grammar-only highlighter** as a fallback marker.

One source of truth, several consumers. Contrast with the rejected design, where
the type annotation would be a highlighting marker that the compiler could not
read and that could drift out of sync with any real `*_lang` the compiler needed.

### 6.3 The subtlety with template dialects

Because a Markdown or Pug template compiles to citry-HTML which the citry parser
then interprets (section 3.3), the `{{ }}` / `<c-*>` semantics live in the
*compiled* output, not in the Markdown or Pug source the author edits. Providing
template-variable resolution on a Markdown source therefore requires the language
server to run the Markdown-to-HTML compile and map positions back, exactly the
Volar pug-plugin situation. This is why alternative template dialects are a
per-language language-server investment, not a free consequence of the compiler.

### 6.4 Dialect support is a plugin system, and built-ins are plugins too

The language server (and the compiler registry) treat each dialect's support as a
**plugin**, and citry's own built-in dialects are implemented as plugins on that
same interface, with no privileged path. This is the Volar.js model (every
language, the first-class ones included, is a language plugin) and Svelte's and
Vue's (built-in and third-party preprocessors and language plugins share one
interface). Designing it this way from the start means:

- a citry-HTML template plugin, a delegated-css plugin, and a delegated-js plugin
  are just the plugins that ship in the box;
- a user or an ecosystem package can add a plugin for a custom dialect (the
  source-to-citry-AST mapping for editing, and the compiler for building) and get
  the same treatment as a built-in;
- there is no separate, lesser "custom language" code path to maintain.

The default expectation still holds (a dialect is build-only until someone writes
an editing plugin for it), but the *mechanism* is uniform: everything is a plugin.
This lines up with the compiler registry in section 3, which is already a plugin
registry. The principle across both: the compiler and the editor treat dialects as
plugins, citry's built-ins included.

---

## 7. Decisions, at a glance

| Question | Decision | Why |
|---|---|---|
| How is an inline source language declared? | `template_lang` / `js_lang` / `css_lang` string attributes (default `None` = infer; an explicit value overrides a file's suffix) | No import; Vue/Svelte `lang=` pattern; composes with a pluggable registry with zero ceremony; `None`-vs-explicit keeps "infer" distinct from "force" |
| Typed string aliases (`Annotated[str, ...]`)? | Not shipped | Never read at runtime in djc; import-heavy; awkward for custom languages; not even a portable highlight key |
| How is a file's source language declared? | File suffix (`.scss`, `.ts`), matched by the same registry | Matches every bundler and Eleventy |
| Is the compiler set fixed? | Built-ins plus user-registered; finite but open | Matches Svelte alias dictionary, Eleventy `addExtension`, bundler plugins |
| When does compilation run, and is there a static export? | Open, needs its own design pass (section 3.3); likely lazy-at-first-render plus a content-hash cache, and a djc-style `collectcomponent` export is likely *not* a citry feature | The prototype's build/export model was Django-shaped |
| Interim syntax highlighting? | None | A highlight-only stopgap cannot grow into semantic support |
| What delivers the real editor experience? | A dedicated citry language server / VS Code extension (built incrementally: skeleton, then highlighting grammar, then semantic intelligence) | Only a language service can resolve `{{ }}` variables, `c-*`, `css_data`, `$onComponent` |
| Which languages get rich editing? | A curated first-class set (citry-HTML, delegated css/js) plus hand-written per-language plugins; custom languages get highlight/sourcemap only | Matches how Volar/Svelte scope semantic support |
| How is dialect support structured? | A plugin system; citry's built-in dialects (compiler and editor) are plugins on the same interface | Volar.js / Svelte / Vue model; no privileged built-in path |

---

## 8. Open questions

- **Compilation lifecycle and static export (the big one, section 3.3).** Whether
  compilation is lazy-at-first-render plus a content-hash cache or a lifecycle
  step after autodiscovery; whether template dialects pre-compile like js/css;
  what a dialect does with `{{ }}` / `<c-*>` (pass through, escape, interpret);
  where a render-time dialect runs relative to `on_template_loaded` /
  `on_template_compiled`; and whether any CDN-oriented export exists at all.
  Settle before building #10.
- **Registry API shape.** How a project registers a custom compiler:
  `Citry(compilers=[...])`, a settings entry, or an extension hook; and the exact
  keying (a lang name, a file pattern, or both per entry). Interaction with the
  asset post-process hooks (`on_js_postprocess` / `on_css_postprocess`) noted in
  [`extensions_roadmap.md`](extensions_roadmap.md) section 4.
- **Which alternative languages get first-class editing first.** Delegating css to
  `vscode-css-languageservice` brings scss/less almost for free; a Pug or Markdown
  *template* editing plugin is real work. Sequence accordingly.
- **Editor scope and base.** VS Code first, and whether to build the language
  server on Volar.js (it targets exactly this embedded-language problem) or
  lighter; the TextMate grammar for citry-HTML; multi-editor support via the
  language server later.

---

## 9. Prior art references

Framework preprocessing and language declaration:

- Svelte preprocessing and custom preprocessors:
  [svelte-preprocess docs](https://github.com/sveltejs/svelte-preprocess/blob/main/docs/preprocessing.md),
  [language-tools preprocessors](https://github.com/sveltejs/language-tools/blob/master/docs/preprocessors/in-general.md).
- Vue SFC blocks and preprocessors:
  [SFC spec](https://vuejs.org/api/sfc-spec),
  [vue-loader pre-processors](https://vue-loader.vuejs.org/guide/pre-processors.html).
- Eleventy custom template languages:
  [11ty custom languages](https://www.11ty.dev/docs/languages/custom/).
- Parcel transformer plugins:
  [Parcel transformer](https://parceljs.org/plugin-system/transformer/).
- Astro integrations (Rollup/Vite-inspired):
  [Astro integrations](https://docs.astro.build/en/guides/integrations/).
- Per-file transform versus whole-graph bundle (why batching is only for
  code-splitting): [Why Vite](https://vite.dev/guide/why),
  [Vite production build](https://vite.dev/guide/build).

Editor tooling architecture:

- The three editor layers (grammar, semantic tokens, language server):
  [VS Code syntax highlighting (TextMate grammars)](https://code.visualstudio.com/api/language-extensions/syntax-highlight-guide),
  [VS Code semantic highlighting (semantic tokens)](https://code.visualstudio.com/api/language-extensions/semantic-highlight-guide).
- TextMate grammar model and its limits (state via `begin`/`end`, no
  backtracking, approximate nesting):
  [TextMate language grammars](https://manual.macromates.com/en/language_grammars),
  [lessons learned](https://www.apeth.com/nonblog/stories/textmatebundle.html).
  Parser-based alternative with injections:
  [tree-sitter](https://tree-sitter.github.io/tree-sitter/).
- Volar.js embedded-language framework:
  [embedded languages](https://volarjs.dev/core-concepts/embedded-languages/),
  [languages reference](https://volarjs.dev/reference/languages/).
- Vue language tooling and the Pug language plugin (register in
  `vueCompilerOptions.plugins`):
  [language-tools](https://github.com/vuejs/language-tools),
  [pug language plugin](https://www.npmjs.com/package/@vue/language-plugin-pug),
  [Vue Compiler Options](https://github.com/vuejs/language-tools/wiki/Vue-Compiler-Options),
  [transparent-installation issue](https://github.com/vuejs/language-tools/issues/2036).
- Which Vue style languages are first-class (css/less/scss via
  vscode-css-languageservice):
  [Volar on Open VSX](https://open-vsx.org/extension/Vue/volar/1.8.7).
- Python-side highlighting markers: `python-inline-source` (reads
  `Annotated[str, ...]`; the citry maintainer's fork is
  `jurooravec.python-inline-source-2`) and
  [PyCharm language injections](https://www.jetbrains.com/help/pycharm/using-language-injections.html)
  (reads `# language=` comments).
