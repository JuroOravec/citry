# Agent knowledge - Citry

One-paragraph architectural facts, contracts, and anti-patterns for this
codebase, optimized for LLM context windows. Read this **before designing
anything in the high-risk areas** listed in [`/CLAUDE.md`](../../CLAUDE.md).
For why this directory exists, see [`RATIONALE.md`](RATIONALE.md).

This file covers **cross-crate** concerns. For deep package-internal
architecture, follow the topic router to that crate's own
`docs/agent/INDEX.md`, or its `AGENTS.md` when no deeper doc exists
yet.

When you discover a non-obvious fact while working, propose a new entry: here
if it is cross-cutting, in the crate's own INDEX if it is crate-internal. Keep
each entry to one paragraph and link to longer docs rather than copying them.

---

## Topic router

| Topic | Read |
|---|---|
| Template parser: grammar, AST, parser, compiler, lang impls | [`crates/citry_template_parser/docs/agent/INDEX.md`](../../crates/citry_template_parser/docs/agent/INDEX.md) |
| Template parser: quick pointers + gotchas | [`crates/citry_template_parser/AGENTS.md`](../../crates/citry_template_parser/AGENTS.md) |
| PyO3 glue: what Python sees, module registration | [`crates/citry_core_py/AGENTS.md`](../../crates/citry_core_py/AGENTS.md) |
| Sandboxed Python expression transform | [`crates/python_safe_eval/AGENTS.md`](../../crates/python_safe_eval/AGENTS.md) |
| HTML attribute transformer | [`crates/citry_html_transform/AGENTS.md`](../../crates/citry_html_transform/AGENTS.md) |
| Python package surface (`citry_core` on PyPI) | [`packages/py/citry_core/AGENTS.md`](../../packages/py/citry_core/AGENTS.md) |
| Monorepo dev / build / release conventions | [`docs/codebase.md`](../codebase.md) |
| Current status snapshot (dated) | [`docs/../TODO/project_status_june_2026.md`](../../TODO/project_status_june_2026.md) |

---

## Quick facts (cross-cutting)

### Template syntax versions (V1 / V2 / V3)

These are **template syntax versions**, not project versions. V1 is
Django-compatible (only `{% component %}` tags use extended syntax). V2 uses
extended syntax across the whole template but keeps Django `{% %}` delimiters.
**V3 drops Django syntax entirely** and uses HTML-like `<c-*>` tags, `c-*`
attributes, `{{ expr }}`, and `{# comment #}`. V3 is what Citry builds; the
root [`README.md`](../../README.md) describes the V3 surface. The migration
path (from upstream django-components) is `djc_v1 -> v2 -> v3 -> citry_v1`,
tracked in django-components issues #1499, #1004, and #1141. The `v2_*.md`
files in the template parser crate are working notes for the next iteration,
not a spec; treat them as brainstorming, with the README as the north star.

### Rust-first binding architecture

Core logic lives in [`crates/`](../../crates/) and is the single source of
truth. Host languages get thin bindings: Python is live (PyO3/maturin), and
JS (wasm-bindgen), PHP (FFI), and Go (cgo) are planned. The same crate is
released per language. Dev setup, the monorepo layout, dependency-pinning
rules, release tags, and CI workflow naming are documented in
[`docs/codebase.md`](../codebase.md); do not duplicate them here.

### The grammar -> AST -> compiler -> codegen pipeline

A template string is parsed by a Pest grammar into an AST, the AST is compiled
into host-language source code, and (for Python) that source builds a tree of
runtime node objects. The three stages are a single contract: a change to the
grammar can change the AST, which can change the compiler output, which the
runtime node classes consume. Depth lives in the template parser's own INDEX:
[`crates/citry_template_parser/docs/agent/INDEX.md`](../../crates/citry_template_parser/docs/agent/INDEX.md).

### PyO3 binding contract

AST types marked `#[pyclass]` in
[`citry_template_parser/src/ast.rs`](../../crates/citry_template_parser/src/ast.rs)
are the Python-visible surface. They are registered in
[`citry_core_py/src/lib.rs`](../../crates/citry_core_py/src/lib.rs), mirrored by
hand in
[`packages/py/citry_core/citry_core/_rust.pyi`](../../packages/py/citry_core/citry_core/_rust.pyi),
and wrapped by Python modules under
[`packages/py/citry_core/citry_core/`](../../packages/py/citry_core/citry_core/).
These four must stay in sync (see CLAUDE.md Mechanism 4). The
`template_parser` module is registered in `lib.rs` (`parse_template`,
`compile_template`, and the AST classes), alongside `safe_eval` and
`html_transform`.

---

## Anti-patterns observed in this codebase

### Pest implicit-whitespace cascade

Defining a `WHITESPACE` rule makes Pest skip whitespace implicitly between
elements in non-atomic rules. A non-atomic `template` rule therefore silently
dropped whitespace between template elements (for example the space after a
closing tag). The fix made `template` compound-atomic (`${ ... }`). Because
atomicity cascades to called rules, this also changed `html_comment` and
`html_raw` behavior. Lesson: a grammar rule's atomicity is not a local choice.
Full write-up in the template parser INDEX.

### Non-deterministic output from HashSet iteration

The compiler aggregated a node's used-variable names through a `HashSet` and
iterated it into the emitted code, so the output tuple order varied between
runs. Generated code is a contract (and may be cache-keyed), so it must be
reproducible. Dedupe while preserving first-seen (source) order instead of
iterating a hash set.

### Preserving incorrect behavior to keep tests green

When a fix makes the more correct choice, update the tests that encoded the old
behavior, rather than special-casing the code to keep the suite green. The
session 9.1.x whitespace fix made HTML-comment values symmetric and made
`<c-raw>` attribute rejection explicit; the comment and raw tests were updated
to the corrected contract. Always call such test updates out explicitly.

---

## Conventions (repo-wide)

Rust crates are named `citry_*` (the exception, `python_safe_eval`, predates
the rename and is an internal helper). Crate layout, dependency pinning,
release tag format (`py@citry-core@x.y.z`), and CI workflow naming
(`<lang>--<package>--<type>.yml`) are all documented in
[`docs/codebase.md`](../codebase.md).

---

## Open project plans

### Wire the V3 parser through to Python

The V3 parser and compiler are implemented and tested in Rust but not yet
exposed to Python. The sequence: commit the template parser crate; uncomment
and update the `template_parser` PyO3 module in
[`citry_core_py/src/lib.rs`](../../crates/citry_core_py/src/lib.rs) to expose
the V3 types and functions; rewrite the Python `template_parser/` wrapper and
the `_rust.pyi` stub for the V3 API; enable and rewrite the disabled
`_test_template_parser__*.py` tests. After that, implement the Python-side
runtime node classes the compiler output references. The detailed, dated
snapshot of where this stands is
[`docs/../TODO/project_status_june_2026.md`](../../TODO/project_status_june_2026.md).

### Rust render walk (built, measured ~parity, archived in git)

Moving the render body-walk to Rust was prototyped and then built out into a full
production engine (`BodyEngine` / `FoldedPlan`). It was byte-identical but only
reached ~parity (about 1.06x on a markup-heavy page, parity on the
construction-bound benchmark), not a beat, so it was removed from the live code
rather than kept. The full implementation, its design doc (`render_plan_rust.md`),
and the measurements are preserved in commit `b7b2f4e` (taken back out at
`60e1980`); `git revert 60e1980`, or a cherry-pick from `b7b2f4e`, brings it
forward. The motivation that could still justify it is portability (a host-agnostic
walk that JS/PHP/Go reuse), not speed. Full write-up:
[`performance.md`](../design/performance.md) section 6.9.

The same body-walk lever was also tried on the Python side (generating a function
from each component body instead of walking it). It reached the same ~parity
result for the same construction-bound reason, plus a large one-time first-render
cost, and was likewise reverted; the implementation is preserved in commit
`ec5faaf` and written up in
[`performance.md`](../design/performance.md) section 6.10.

---

For the reasoning behind these rules and the incidents that shaped them, see
[`RATIONALE.md`](RATIONALE.md).
