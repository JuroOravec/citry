# Design: CI/CD for the citry monorepo

This document plans the continuous-integration and release (CI/CD) setup for
the citry monorepo: how the `citry_core` (Rust/maturin) and `citry`
(pure-Python) packages get tested, built, and published to PyPI, and how that
work folds in the uv-workspace conversion
([#8](https://github.com/JuroOravec/citry/issues/8)). It is the persistent
reference for that multi-PR effort, in the same spirit as
[`citry_migration.md`](citry_migration.md).

For operating rules see [`/CLAUDE.md`](../../CLAUDE.md). For the documented
dev/build/release conventions (some marked unverified) see
[`docs/codebase.md`](../codebase.md).

**Status (2026-06-30): PRs 1-3 implemented.** PR 1 (uv workspace + the
lint/format/type-check gates), PR 2 (the `citry` publish workflow, the
`citry-core@`/`citry@` tag rename with a tag==version guard, the built-wheel
smoke test, macOS on `rust--tests`), and PR 3 (Trusted Publishing / OIDC on both
publish workflows plus a GitHub Release per tag) are all in. Two deviations from
the original plan: the quality-gate mechanism was switched from pre-commit to an
explicit `python scripts/check.py` command with auto-discovered validators in
[`scripts/validators/`](../../scripts/validators/) (see
[`docs/codebase.md`](../codebase.md) "Checks and validators"); and GitHub Release
notes are auto-generated rather than sliced from the CHANGELOG, because the
CHANGELOG is date-headed, not version-headed. Before the first real release the
maintainer configures PyPI pending publishers (repo + workflow file + environment
`pypi`) for `citry-core` and `citry`. Deferred: stripping debug symbols from
published wheels (the release profile keeps `debug = true` for profiling).
Passages below that mention pre-commit hooks or `repo--tests.yml` describe the
original plan, not what shipped.

---

## 1. Why this is mostly hardening, not greenfield

citry already ships four GitHub Actions workflows, clearly ported from
`djc-core`. The `citry_core` wheel-build and publish pipeline in particular is
mature. So this design is mostly about closing gaps and adding the second
package, not building from scratch.

| Workflow | What it does | State |
|---|---|---|
| [`py--citry-core--publish.yml`](../../.github/workflows/py--citry-core--publish.yml) | maturin wheels across linux (x86_64/x86/aarch64/armv7/s390x/ppc64le), musllinux, windows (x64/x86), macOS (intel + arm) + sdist + build-provenance attestation + PyPI upload | mature |
| [`rust--tests.yml`](../../.github/workflows/rust--tests.yml) | `cargo test -p` per first-party crate, {ubuntu, windows}, nightly | works |
| [`py--tests.yml`](../../.github/workflows/py--tests.yml) | Python 3.10-3.14 x {ubuntu, windows}, `maturin develop` + `pytest` | works, partial |
| [`repo--tests.yml`](../../.github/workflows/repo--tests.yml) | `pre-commit run --all-files` (the 4 custom invariant scripts) | works |

---

## 2. Decisions taken (this session)

1. **Phased, foundation first.** Three PRs: (1) uv workspace (#8) plus the
   quality gates, (2) the `citry` release pipeline plus publish hardening,
   (3) Trusted Publishing. The uv workspace lands and bakes on its own before
   the release path changes.
2. **Both packages are in scope now, including `citry` publishing.** `citry`
   is pre-1.0 (0.1.0), but the release pipeline goes in now so the next
   version bump can ship.
3. **Trusted Publishing (OIDC) for PyPI uploads**, replacing the stored API
   token, for both packages. An API token stays as the documented fallback if
   a project cannot be configured for OIDC.
4. **Independent versioning per package.** `citry_core` and `citry` version on
   their own cadence (already the de-facto state: 1.3.0 vs 0.1.0). The release
   tag namespace supports this.
5. **Release tags drop the language prefix.** Tags and GitHub releases are
   `citry-core@x.y.z` and `citry@x.y.z` (not `py@citry-core@...`). A tag with
   no language prefix means the Python package. When a second host language is
   published, we revisit how to disambiguate then; until then the prefix would
   be noise. Workflow *file* names keep the documented
   `<language>--<package>--<type>.yml` convention (for example
   `py--citry-core--publish.yml`) because they are a separate scheme and a
   rename is more disruptive; the file-name-vs-tag divergence is deliberate and
   easy to revisit (section 8).

---

## 3. Prior art (what was searched)

This touches dependency declarations and the cross-file invariant scripts, so
per [`/CLAUDE.md`](../../CLAUDE.md) Mechanism 1 here is what was surveyed.

### 3.1 citry's own workflows and config (read in full)

- The four workflows above. Key facts confirmed from source: the publish
  pipeline uses `PyO3/maturin-action@v1` with `--release --out dist
  --find-interpreter` (a wheel per interpreter, not a single stable-ABI wheel),
  `sccache: true`, and explicit per-version `setup-python` on Windows/macOS
  (otherwise those runners skip older-version wheels, citing djc-core issue
  #22). Upload is via `maturin upload` with `MATURIN_PYPI_TOKEN` (an API
  token); `id-token: write` is granted but used only by
  `actions/attest-build-provenance@v3`. The release job `needs` only the build
  jobs, so a publish is **not** gated on tests
  ([`py--citry-core--publish.yml:226-253`](../../.github/workflows/py--citry-core--publish.yml)).
- [`py--tests.yml`](../../.github/workflows/py--tests.yml) builds `citry_core`
  with `maturin develop` and runs `uv run pytest` from the repo root, but never
  installs the `citry` package, so `citry`'s tests do not run in CI.
- [`packages/py/citry_core/pyproject.toml`](../../packages/py/citry_core/pyproject.toml):
  `version = 1.3.0`, `requires-python = ">=3.10, <4.0"`, maturin
  `features = ["pyo3/extension-module"]`, `module-name = "citry_core._rust"`.
- [`crates/citry_core_py/Cargo.toml`](../../crates/citry_core_py/Cargo.toml):
  `pyo3 = { workspace = true }` with no `abi3` feature anywhere, which is why
  the per-interpreter wheel matrix (3.10-3.14) exists by design.
- [`packages/py/citry/pyproject.toml`](../../packages/py/citry/pyproject.toml):
  `version = 0.1.0`, setuptools backend, `dependencies = ["citry-core>=1.3.0",
  ...]`, a `citry` console script, and `package-data` shipping `py.typed` and
  `extensions/dependencies/client/*.js`.
- [`pyproject.toml`](../../pyproject.toml) (root): `Private :: Do Not Upload`,
  `dev`/`ci` extras that mirror `citry`'s test deps with version skew (root
  pins `pytest>=8.0` / `maturin>=1.8`; the packages pin `pytest>=8.3.5` /
  `maturin>=1.10.2`). No `[tool.uv.workspace]` or `[tool.uv.sources]`.
- The four invariant scripts in
  [`scripts/precommit/`](../../scripts/precommit/): crate-is-a-workspace-member,
  rust-toolchain consistency (only checks `rust--tests.yml`), the
  `_rust.pyi`/PyO3 surface sync, and the dependabot-covers-every-py-package
  check (expects one `directory: /packages/py/<name>` entry per package).
- [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) holds **only**
  those four scripts. No `ruff`, `ruff format`, `mypy`, `cargo fmt`, or `cargo
  clippy` hook. Grep over `.github/workflows` confirms none of those run as CI
  steps either; the clippy/rustfmt mentions are `components:` install lines, not
  invocations.

### 3.2 The two upstream models (read in full)

- **`djc-core`** (Rust + maturin, the model `citry_core` was ported from):
  `.github/workflows/publish.yml` and `tests.yml`. Same maturin matrix,
  `--find-interpreter`, no abi3, API-token upload, no GitHub Release, version
  from `pyproject [project].version`. Its tests workflow installs clippy/rustfmt
  but runs only `cargo test` + `pytest`, so it does not lint either. Confirms
  citry inherited both the strengths (the wheel matrix) and the gaps (no lint,
  no test-gate-on-publish).
- **`django-components`** (pure Python, the model for the `citry` package):
  `release-pypi.yml` builds with `python -m build` and publishes via
  `pypa/gh-action-pypi-publish@release/v1`, but still with an API token (no
  OIDC). Its `tests.yml` runs a separate single-version `lint` job
  (`ruff check` + `ruff format --check` + `mypy`) and a `coverage` job with
  `--cov-fail-under`. The separate-lint-job shape is the model for section 5.2.

### 3.3 Where CI/CD is and is not documented

The migration doc [`citry_migration.md`](citry_migration.md) has **no** CI/CD
content; its "feature/file index" is a per-file feature audit. The real source
of release conventions is [`docs/codebase.md`](../codebase.md), which documents
the manual release steps and the workflow-naming convention, but carries a
`THE REST IS NOT VERIFIED` marker over that prose, so it is intent to
cross-check against the live workflows, not ground truth.

---

## 4. Constraints the design must respect

- **Dependency chain `citry_core` <- `citry` <- django-components.** A release
  that bumps both citry packages must publish `citry_core` first and let it
  reach PyPI before `citry`'s `citry-core>=X` can resolve.
- **Per-interpreter wheels.** No abi3, so `citry_core` needs a wheel per
  CPython minor (3.10-3.14) per platform. This is deliberate; keep it.
- **maturin-action, not cibuildwheel.** It is the idiomatic builder for maturin
  projects and already works. Keep it.
- **Nightly Rust toolchain** (edition 2024), pinned in
  [`rust-toolchain.toml`](../../rust-toolchain.toml).
- **The vendored ruff submodule crates are Cargo workspace members.** Any
  `cargo test`/`cargo clippy` must scope `-p` to the four first-party crates
  (`citry_core_py`, `citry_html_transform`, `citry_template_parser`,
  `python_safe_eval`), or it runs ruff's own suite. Checkout needs
  `submodules: recursive`.
- **`citry` ships non-Python assets** (`py.typed`, the client JS). Its wheel
  and sdist must both contain them.
- **Independent versions and the new tag scheme** (section 2, decisions 4-5).

---

## 5. The design

### 5.1 Issue #8: uv workspace (the foundation)

This lands first because it makes two gaps disappear for free: `citry`'s tests
start running in CI, and the mirrored-dep skew goes away.

```toml
# root pyproject.toml
[tool.uv.workspace]
members = ["packages/py/*"]

[tool.uv.sources]
citry      = { workspace = true }
citry-core = { workspace = true }
```

- Convert the root `dev`/`ci` extras to PEP 735 `[dependency-groups]` (uv
  installs the `dev` group by default on `uv sync`). Keep only genuinely
  repo-wide tooling there (ruff, mypy, maturin, pre-commit) and **delete** the
  mirrored test deps (`pytest`, `pydantic`, `fastapi`, `httpx`) so each
  package's own group is the single declaration.
- **The maturin member rebuild story.** uv keys its rebuild detection on
  package metadata, not Rust sources, so editing `crates/**` would not trigger
  a rebuild on the next `uv sync`. Mitigate with `[tool.uv] cache-keys` on
  `citry_core` globbing the Rust sources (which live outside the package dir,
  under `crates/`), and keep `maturin develop` as the documented inner-loop
  command for Rust work. Confirm the profile the PEP 517 editable build uses
  (debug is fine for tests; the benchmark path still needs `--release`, the
  known debug-skews-benchmarks gotcha).
- `uv lock`, commit the expanded `uv.lock`.

CI then collapses to one install command that also installs and tests `citry`:

```yaml
- run: uv sync --locked --all-packages --group ci   # builds citry_core (maturin PEP 517) + installs citry editable
- run: uv run --no-sync pytest                       # now collects BOTH packages' tests
```

Keep `Swatinem/rust-cache` (it caches the Rust compile; `cache-keys` is mostly
local-dev ergonomics).

### 5.2 CI hardening

- **Add the missing quality gates** (the biggest hole today). Two layers, the
  way django-components does it:
  - Fast local feedback: add the official `ruff` and `ruff format` pre-commit
    hooks. They then also run through
    [`repo--tests.yml`](../../.github/workflows/repo--tests.yml).
  - The authoritative gate: a single-version `lint` job (lint results do not
    vary by OS or Python version) running `ruff check .`, `ruff format --check
    .`, `mypy`, `cargo fmt --check`, and `cargo clippy` (scoped `-p` per crate,
    same exclusion trick as the test job).
- **Add macOS** to the test matrices (a 3.10 + 3.14 smoke pair keeps cost down,
  as django-components does for Windows), so the macOS wheels the publish
  workflow builds are at least import-exercised somewhere.
- **Gate publishing on green tests.** Make the test workflows
  `workflow_call`-able and have the release job `needs` them, plus a
  wheel-install smoke step (install the built artifact, import it, run a
  trivial parse). This catches packaging breakage that `maturin develop` never
  exercises: the `citry_core._rust` module merge, and `citry`'s client-JS
  package-data.

### 5.3 CD: citry_core hardening, citry publishing, Trusted Publishing

**A tag==version guard** on both publish workflows (independent versioning
makes a mismatch easy, and `--skip-existing` would hide it):

```bash
# citry_core workflow (strip the "citry-core@" tag prefix)
TAG_VERSION="${GITHUB_REF_NAME#citry-core@}"
PKG_VERSION=$(grep -m1 '^version' packages/py/citry_core/pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
[ "$TAG_VERSION" = "$PKG_VERSION" ] || { echo "tag $TAG_VERSION != pyproject $PKG_VERSION"; exit 1; }
```

**Trusted Publishing (OIDC)** replaces the API token. The wheel-build matrix
jobs are unchanged; only the release job's upload changes. Download all wheel
artifacts into `dist/`, attest, then publish with no stored secret:

```yaml
release:
  needs: [linux, musllinux, windows, macos, sdist]   # plus the test job, per 5.2
  environment: pypi
  permissions:
    id-token: write        # OIDC for trusted publishing AND attestation
    attestations: write
    contents: read
  steps:
    - uses: actions/download-artifact@v7
      with: { path: dist, merge-multiple: true }
    - uses: actions/attest-build-provenance@v3
      with: { subject-path: "dist/*" }
    - uses: pypa/gh-action-pypi-publish@release/v1   # no password: OIDC
```

**The new `citry` publish workflow** (pure Python, so much simpler than the
maturin one): a new `py--citry--publish.yml` triggered on `citry@*`, building
with uv and publishing via the same OIDC block:

```yaml
on:
  push:
    tags: ["citry@*"]
  workflow_dispatch:
# build job: setup-uv, tag==version guard (strip "citry@"), `uv build --package
# citry --out-dir dist`, smoke-test the wheel (pip install, `citry --help`,
# import), upload artifact. release job: the OIDC block above.
```

The `citry-core@*` and `citry@*` tag patterns are disjoint (`citry-core@1.0.0`
does not start with `citry@`), so the two workflows never both fire on one tag.
A pure-Python `citry` build does not need the ruff submodule, so its checkout
can skip `submodules: recursive`. Verify the client JS lands in the sdist as
well as the wheel (setuptools `package-data` covers wheels reliably; the sdist
may need a `MANIFEST.in`).

**Release ordering** for a coordinated bump stays manual for now: push
`citry-core@…`, wait for it to reach PyPI, then push `citry@…`. A future
orchestrator workflow could automate the wait; out of scope here.

### 5.4 Cross-binding ripples (do not forget these)

The uv-workspace conversion is not only pyproject edits. It moves parts of the
cross-file contract that the invariant scripts protect, so they move together:

- [`scripts/validators/dependabot.py`](../../scripts/validators/dependabot.py)
  expects one `directory: /packages/py/<name>` dependabot entry per package. If
  the workspace collapses the per-package pip entries in
  [`.github/dependabot.yml`](../../.github/dependabot.yml), the script and the
  config update in the same PR.
- [`scripts/validators/toolchain.py`](../../scripts/validators/toolchain.py)
  validates only `rust--tests.yml`. `py--tests.yml` (and the new lint workflow)
  also pin `toolchain: nightly` uncovered; extend the check while we are here.
- [`docs/codebase.md`](../codebase.md): update the dev-setup to `uv sync
  --all-packages`, the release section to the new `citry-core@…` / `citry@…`
  tag scheme, and remove the mirror comments.

---

## 6. Pre-implementation checks

Quick checks to run before editing, so the fallbacks in the plan are real:

- A proof-of-concept spike: does `uv sync --all-packages` build the
  `citry_core` maturin member cleanly under the nightly toolchain across the
  3.10-3.14 matrix? The whole "citry tests for free" premise rests on this. If
  it is flaky, keep an explicit `maturin develop` step.
- Does the `PYPI_API_TOKEN` secret exist (so the Trusted Publishing fallback is
  real)?
- Does setuptools include the client JS in the **sdist**, or is a `MANIFEST.in`
  needed?

---

## 7. Phasing (three PRs)

- **PR 1, foundation:** uv workspace (#5.1), drop mirrored deps, fix the `uv
  run` footgun, `citry` tests now run in CI, add the lint/type-check job and
  the ruff pre-commit hooks, add macOS. Plus the dependabot/script ripples in
  5.4 that the workspace forces. Highest value; unblocks the rest. Run the
  spike (section 6) first.
- **PR 2, citry CD:** the new `py--citry--publish.yml`, the tag==version guard
  on both publish workflows, the rename to `citry-core@…` tags (update the
  existing trigger and `docs/codebase.md`), gate publishing on green tests, and
  the built-artifact smoke tests.
- **PR 3, modernize publishing:** Trusted Publishing (OIDC) on both workflows,
  a GitHub Release with notes sliced from `CHANGELOG.md`, and optionally
  stripping debug symbols from published wheels (the release profile sets
  `debug = true`). Requires the one-time PyPI-side pending-publisher setup per
  project.

---

## 8. Risks and open questions

- **The maturin member under `uv sync` is the load-bearing unknown** (section
  6). It could send PR 1 back to an explicit `maturin develop` step.
- **Trusted Publishing is operational, not just YAML.** It needs PyPI-side
  pending-publisher config per project (the `citry` project is not on PyPI
  yet). If the maintainer cannot configure it, that package keeps an API token.
- **Workflow file names vs tag names diverge** (files keep `py--…`, tags drop
  the prefix). Deliberate and reversible; revisit if the inconsistency grates,
  or when a second language's workflows arrive and force the question anyway.
- **The publish workflow's release profile** (`lto = true`, `codegen-units =
  1`, `debug = true`) makes wheel builds slow and large. Stripping is a PR 3
  nice-to-have, not a blocker.
- A future `packages/js/citry-client` TypeScript build (flagged in the
  migration doc) will eventually add npm publishing to this picture. Out of
  scope now, but it is the reason the tag scheme leaves room for a language
  prefix later.
