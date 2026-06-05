# CLAUDE.md - Citry

Operating rules for AI agents working on this repository. Architectural
facts live in [`docs/agent/INDEX.md`](docs/agent/INDEX.md);
the reasoning behind these rules is in
[`docs/agent/RATIONALE.md`](docs/agent/RATIONALE.md).

When working inside a specific crate or package, also read its `AGENTS.md`
for local pointers and gotchas (e.g.
[`crates/citry_template_parser/AGENTS.md`](crates/citry_template_parser/AGENTS.md)).

## What this project is

Citry is a universal, cross-language HTML templating engine (Vue/React-like
component syntax). The core logic lives in **Rust crates** under
[`crates/`](crates/) and is exposed to host languages through thin bindings.
**Python is live** (via PyO3/maturin, shipped as the `citry_core` package);
JS, PHP, and Go are planned. Rust is the single source of truth: a behavior
is defined once in a crate and surfaced to every language.

The active frontier is the **V3 template parser** in
[`crates/citry_template_parser/`](crates/citry_template_parser/). V3 is the
HTML-like `<c-*>` tag syntax described in [`README.md`](README.md). See the
agent INDEX for the V1/V2/V3 version model and the current status
snapshot in [`TODO/project_status_june_2026.md`](TODO/project_status_june_2026.md).

This is a monorepo. Per-language packages live under [`packages/`](packages/);
dev/build/release conventions are documented in
[`docs/codebase.md`](docs/codebase.md).

## High-risk areas - require a prior-art check before redesign

If a change touches one of these, survey existing implementations and tests
first, and lead your proposal with what you searched (see Mechanism 1).

- **The Pest grammar**
  ([`crates/citry_template_parser/src/grammar.pest`](crates/citry_template_parser/src/grammar.pest)).
  Rule **atomicity changes cascade** to called rules and have repo-wide
  effects. Read the gotcha below before touching it.
- **The AST structs**
  ([`crates/citry_template_parser/src/ast.rs`](crates/citry_template_parser/src/ast.rs)).
  Types marked `#[pyclass]` are the **Python contract**, mirrored by hand in
  [`packages/py/citry_core/citry_core/_rust.pyi`](packages/py/citry_core/citry_core/_rust.pyi).
- **The compiler output format**
  ([`crates/citry_template_parser/src/compiler.rs`](crates/citry_template_parser/src/compiler.rs)).
  The generated source string is a contract consumed by Python-side runtime
  node classes. Shape changes break the runtime.
- **The `LangImpl` trait and per-language impls**
  ([`src/lang/lang.rs`](crates/citry_template_parser/src/lang/lang.rs) and
  `src/lang/{python,js,php,go,rust}.rs`). Changes must stay consistent across
  all five host languages.
- **The PyO3 glue**
  ([`crates/citry_core_py/src/lib.rs`](crates/citry_core_py/src/lib.rs)).
  Defines exactly what Python sees.
- **Workspace dependencies.** New Rust deps must be pinned in the root
  [`Cargo.toml`](Cargo.toml) `[workspace.dependencies]` and referenced with
  `workspace = true` in crates. See [`docs/codebase.md`](docs/codebase.md).

Routine bug fixes, test additions, and doc edits do not need this gate.

## Mechanism 1 - prior-art header for high-risk designs

When designing a change in one of the areas above, lead with a "Prior art"
section naming the files, functions, and tests you searched and what already
exists. Cite `file:line` for anything load-bearing. Empty prior art is fine,
say so explicitly ("checked X, Y, Z; nothing exists"). Reach across crates,
not just the one you started in.

When a docstring, `.pyi` stub, or README seems to constrain the answer,
**open the actual Rust source and confirm**. In this repo the implementation
is authoritative; stubs and prose can lag behind it.

## Mechanism 2 - plan mode for structural changes

Present a written plan (via `ExitPlanMode`) before editing when the change:

- Adds or alters a grammar rule, or changes any rule's atomicity
- Changes an AST struct shape or any `#[pyclass]` surface
- Changes the compiler output format
- Adds or changes a `LangImpl` method
- Adds or changes a PyO3-exposed function/class

The plan must include: prior art, the chosen design, one or two alternatives
considered and why rejected, and what would falsify the chosen design. This
applies even when the user has not explicitly asked for plan mode.

## Mechanism 3 - when you fix a bug, sweep for the whole class

A bug is rarely unique. Once you understand the root cause, reduce it to a
greppable signature (the leaky idiom, the missing guard, the unchecked
iteration order) and search all of [`crates/`](crates/) for siblings, then
fix them in the same pass or note explicitly what you left out of scope.

Concrete examples from this codebase (session 9.1.x): a non-deterministic
`HashSet`-into-codegen bug in the compiler, and the Pest implicit-whitespace
cascade. Both were single symptoms of a broader pattern worth sweeping for.

## Mechanism 4 - cross-language / cross-binding consistency audit

The parser, AST, and compiler form a **contract that spans five host
languages plus the Python bindings**. When a change touches that contract,
the work is not done until you have enumerated and classified everything that
must move with it. Produce the list explicitly in the plan:

- The five `src/lang/*.rs` implementations (Python is fully implemented;
  JS/PHP/Go/Rust are structural stubs, so note which need real work vs a stub
  update)
- The PyO3 registration in [`citry_core_py/src/lib.rs`](crates/citry_core_py/src/lib.rs)
- The `_rust.pyi` type stub
- The Python wrapper module under
  [`packages/py/citry_core/citry_core/`](packages/py/citry_core/citry_core/)
- The Rust tests and the Python tests

Partial migrations of a cross-binding contract produce silent drift that no
single grep will catch. Walk the callers, not just the keyword.

## Where new agent knowledge goes

When you discover something worth recording, pick **one** location. All of
these are source-controlled and visible in `git status`, which is the point.

| Kind of knowledge | Goes in |
|---|---|
| Operating rule (applies to any task) | `/CLAUDE.md` (this file) |
| Cross-crate architectural fact, contract, or anti-pattern | [`/docs/agent/INDEX.md`](docs/agent/INDEX.md) |
| Deep architecture of a single crate | `/<crate>/docs/agent/INDEX.md` (create lazily) |
| Crate-local pointer ("the grammar lives in X") | `/<crate>/AGENTS.md` |
| Crate-local gotcha specific to one crate | `/<crate>/AGENTS.md` - "Gotchas" section |
| Monorepo dev/build/release convention | [`/docs/codebase.md`](docs/codebase.md) |
| Why a rule exists / post-mortem context | [`/docs/agent/RATIONALE.md`](docs/agent/RATIONALE.md) |
| Per-user, repo-specific preference | `/.claude/settings.local.json` or `/CLAUDE.local.md` (both gitignored) |

**Pick one location, not two.** If a fact already lives in
[`docs/codebase.md`](docs/codebase.md) or the status report, the
agent entry is a one-line pointer, not a copy.

**Do not** write durable project knowledge into the machine-local, gitignored
agent memory store (`~/.claude/projects/<project>/memory/`). That store is for
genuine per-user/machine-local preferences only. Architectural facts go in the
source-controlled docs above so the whole team (and future sessions) see them.

When **looking for** knowledge, in order: this file, then
[`docs/agent/INDEX.md`](docs/agent/INDEX.md), then the
relevant crate's `AGENTS.md`, then its `docs/agent/INDEX.md`, then
[`docs/codebase.md`](docs/codebase.md) for dev workflow.

## Repository-specific gotchas

- **Pest implicit-whitespace cascade.** The grammar defines a special
  `WHITESPACE = _{ ... }` rule, which makes Pest auto-skip whitespace between
  elements in *non-atomic* rules. The `template` rule is compound-atomic
  (`${ ... }`) specifically to stop whitespace being silently dropped between
  template elements, and that atomicity **cascades** to the rules it calls
  (`html_comment`, `html_raw`). Changing a rule's atomicity has effects beyond
  that rule. Details in
  [`crates/citry_template_parser/docs/agent/INDEX.md`](crates/citry_template_parser/docs/agent/INDEX.md).
- **Compiler output must be deterministic.** The generated code is a contract
  and may be cache-keyed. Never iterate a `HashSet` into emitted output; dedupe
  while preserving first-seen (source) order.
- **HTML rendering rules.** Void elements stay compact (`<br/>`), non-void
  self-closing expand (`<div></div>`), and `key=""` normalizes to a boolean
  attribute (`True`).
- **Rust nightly toolchain** (edition 2024), pinned in
  [`rust-toolchain.toml`](rust-toolchain.toml).
- **maturin module mapping.** The Python extension is built with
  `module-name = "citry_core._rust"`; see
  [`packages/py/citry_core/pyproject.toml`](packages/py/citry_core/pyproject.toml)
  for why.
- **The `template_parser` PyO3 module is currently commented out** in
  [`citry_core_py/src/lib.rs`](crates/citry_core_py/src/lib.rs); the V3 wiring
  to Python is pending (see the INDEX "Open project plans").

## Code conventions

- **Rust:** `cargo fmt` and `cargo clippy` must pass. Edition 2024, nightly.
- **Python:** `ruff` (line length 119, `select = ["ALL"]` with a curated
  ignore list) and `mypy` (strict for `citry_core.*`). Config in the root
  [`pyproject.toml`](pyproject.toml).
- **Imports at the top, not inline.** Put imports in the standard place at
  the top of the file. Only move an import inline (lazy) when there is a
  concrete circular dependency or a measured issue. Do not defensively
  lazy-import "just in case."
- **Run checks repo-wide before declaring done.** Scoping a linter or test run
  to the files you touched is fine for iteration, but a final pass must run the
  way CI does (`cargo test`, `cargo clippy`, `cargo fmt --check`, `uv run ruff
  check .`, `uv run mypy`, `uv run pytest`). A scoped pass hides failures in
  files you changed indirectly.
- **Don't preserve incorrect behavior to keep tests passing.** When a fix makes
  the more correct choice, update the failing tests to match the new contract,
  and call the update out explicitly. A failing test under a deliberate change
  is usually evidence the test encoded the old bug. If you cannot articulate
  why the new behavior is more correct, reconsider the change. (Session 9.1.x:
  the whitespace fix made HTML-comment values symmetric and made `<c-raw>`
  attribute rejection explicit; the comment and raw tests were updated to the
  corrected contract, not worked around.)
- **Authoring parser/compiler tests: observe, then lock.** These tests assert
  exact ASTs or exact generated strings. Author them by running the
  parser/compiler on representative inputs, observing the real output, then
  locking it into the assertion. Do not hand-compute token offsets or codegen
  strings from memory. A throwaway exploration harness (deleted afterward) is
  the established way to capture the output.

## House style

- **No em dashes** (the U+2014 character) in agent docs, code comments, or
  docstrings. Use a hyphen, a comma, parentheses, or two sentences. A
  PostToolUse hook ([`.claude/hooks/check-em-dashes.py`](.claude/hooks/check-em-dashes.py))
  warns when one slips through.
- Prefer a robust solution over a one-line shortcut. When choosing between
  proper architecture and a quick patch, recommend the proper one outright.
- Honest analysis. Do not validate user suggestions uncritically.
- Sentence case for markdown headings.

## Writing rule - don't document what isn't there

If a field, function, or approach was removed, do not mention it in agent docs
or code comments to "warn" people off it. Doing so re-adds the deprecated token
to the searchable codebase and gives agents a pattern to latch onto. Frame
guardrails positively ("the rule is X") rather than negatively ("the old Y is
gone, don't reintroduce it"). The reflex fires at write-time: when you catch
yourself writing "renamed from", "replaces", "no longer", or "instead of" in a
doc or comment, reframe in terms of what is there now.
(`RATIONALE.md` post-mortems are the narrow exception, and even there prefer
abstract framing of the failure mode.)

## Pointers

- Operating rules -> this file
- Cross-crate architecture -> [`docs/agent/INDEX.md`](docs/agent/INDEX.md)
- Why the rules exist -> [`docs/agent/RATIONALE.md`](docs/agent/RATIONALE.md)
- Monorepo dev / build / release -> [`docs/codebase.md`](docs/codebase.md)
- Current status snapshot -> [`TODO/project_status_june_2026.md`](TODO/project_status_june_2026.md)
- Changelog -> [`CHANGELOG.md`](CHANGELOG.md)
