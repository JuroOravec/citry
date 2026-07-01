# Codebase & Development

This document outlines the architectural and organizational decisions made for the citry monorepo.

## Monorepo Structure

### Overview

This repository follows a **monorepo pattern** where:

1. **Rust as source of truth** - Core logic lives in Rust [`crates/`](../crates/)
2. **Language bindings** - Rust functionality is exposed to multiple languages - Python, PHP, JS, Go...

   Each language has one package to define language-specific API. E.g. [`packages/py/citry_core`](../packages/py/citry_core/) exposed Rust code to Python.

3. **Packages** - The actual packages for developers are defined as separate packages, e.g. [`packages/py/citry`](../packages/py/citry/).

4. **Third party git modules** - In some cases, like for Ruff, we have to include them as git module.
   These are stored inside [`third_party/`](../third_party/).

### Directory Structure

```
citry/
├── crates/              # Rust workspace crates (core + internal crates)
│   ├── citry_core_py/   # Main Rust crate exposed to Python
│   ├── citry_html_transform/
│   ├── python_safe_eval/
│   └── citry_template_parser/
├── packages/            # Shipping products per language
│   └── py/              # Python packages
│       └── citry/       # Main Python package
│       └── citry_core/  # Expose citry_core_py to Python
├── tests/               # Integration tests
├── pyproject.toml       # Root tooling configuration (NOT releasable)
└── Cargo.toml           # Rust workspace configuration
```

### Rationale

The architecture is designed to support multiple language bindings:

- **Python**: Via PyO3/maturin
- **JS/TS**: Via wasm-bindgen
- **Go**: Via stable C ABI/FFI
- **PHP**: Via stable C ABI/FFI

As such, the Rust crates are ideal for:

- Text transformation - e.g. template parser, or HTML/code modification
- Shared component logic with string interfaces - Instead of re-implementing it for each language, we define it one in Rust.

<!-- TODO - THE REST IS NOT VERIFIED!!! -->
<!-- TODO - THE REST IS NOT VERIFIED!!! -->
<!-- TODO - THE REST IS NOT VERIFIED!!! -->

## Getting Started / Development Setup

### Prerequisites

- **Rust**: Install via [rustup](https://rustup.rs/) v1.93 or higher (nightly toolchain required for edition 2024)
- **Python**: 3.10 or higher
- **UV**: Fast Python package installer (recommended)

### Installing and Managing Rust

This codebase uses **Rust edition 2024**, which requires the **nightly** toolchain. The required Rust version is pinned in [`rust-toolchain.toml`](../rust-toolchain.toml).

**Check your Rust version:**

```bash
# Check current Rust version
rustc --version
cargo --version

# Verify the toolchain for this project
cd citry
rustup show
```

**Install or update Rust:**

```bash
# Install rustup (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install the nightly toolchain (required for edition 2024)
rustup toolchain install nightly

# Update to the latest nightly
rustup update nightly

# The rust-toolchain.toml file will automatically select the correct toolchain
# when you run cargo commands in this directory
```

**Verify the correct toolchain is active:**

```bash
# From the repository root
cd citry
cargo --version  # Should show nightly version
rustc --version  # Should show nightly version
```

If you need to manually override the toolchain for this directory:

```bash
rustup override set nightly
```

### Installing UV

Install [UV](https://astral.sh/uv) using one of these methods:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip (if you have Python already)
pip install uv
```

### Setting Up the Development Environment

1. **Clone the repository**:

   ```bash
   git clone <repository-url>
   cd citry
   git submodule update --init --recursive  # Initialize Ruff submodule
   ```

2. **Verify Rust toolchain** (required before building):

   ```bash
   # Check that nightly is installed and active
   rustc --version  # Should show nightly version
   cargo --version  # Should show nightly version

   # If not using nightly, install it:
   rustup toolchain install nightly
   rustup override set nightly
   ```

   The [`rust-toolchain.toml`](../rust-toolchain.toml) file automatically selects the nightly toolchain when you run cargo commands in this directory. This is required because the codebase uses Rust edition 2024.

3. **Install the workspace** (from the repository root):

   ```bash
   cd citry
   uv sync --all-packages
   ```

   This is the one-step bootstrap. From the root [`pyproject.toml`](../pyproject.toml) and the locked workspace it: builds the `citry_core` Rust extension through the maturin backend, installs the pure-Python `citry` package in editable mode, and installs every package's dev dependencies (pytest, ruff, mypy, maturin, and each package's own test deps). Because the lockfile now knows every package, a later `uv sync` or `uv run` is safe and will not remove the editable installs.

4. **Rebuilding the Rust extension during development**:

   `uv sync` rebuilds `citry_core` when the Rust sources change (the `cache-keys` in its [`pyproject.toml`](../packages/py/citry_core/pyproject.toml) cover `crates/**`). For a tighter inner loop while working on Rust, build it directly:

   ```bash
   cd packages/py/citry_core
   uv run maturin develop
   ```

   Note: both `maturin develop` and the `uv sync` build produce a **debug** (unoptimized) extension. That is fine for tests, but it makes the Rust-backed paths ~10x or more slower, so pass `--release` (for example `uv run maturin develop --release`) before running any benchmark.

5. **Run tests**:

   ```bash
   # From the root directory
   uv run pytest

   # Or run Rust tests first (scoped to our crates, see "Running tests" below)
   cargo test -p citry_core_py -p citry_html_transform -p citry_template_parser -p python_safe_eval
   ```

## Common Development Tasks

**Note**: Codebase-wide tools (like `uv sync`, `uv run pytest`, `uv run ruff`) should be run from the **repository root directory**, as they read the root [`pyproject.toml`](../pyproject.toml) for configuration.

### Building the package

```bash
# From the package directory
cd packages/py/citry_core
uv run maturin develop
```

### Running tests

Rust tests are scoped to the crates under `crates/`, one `-p` flag per crate.
The vendored ruff submodule's crates are auto-included in the cargo workspace
(path dependencies inside the workspace directory), so a bare `cargo test`
would also run ruff's own test suite. CI scopes the run the same way
(see `rust--tests.yml`).

```bash
# From the root directory
# Python tests
uv run pytest

# Rust tests (our crates only)
cargo test -p citry_core_py -p citry_html_transform -p citry_template_parser -p python_safe_eval

# Both (Rust first, then Python)
cargo test -p citry_core_py -p citry_html_transform -p citry_template_parser -p python_safe_eval && uv run pytest
```

### Formatting and linting code

```bash
# From the root directory
# Python (ruff - replaces black, isort, flake8)
uv run ruff format .          # Format code
uv run ruff check .           # Lint code
uv run ruff check --fix .     # Auto-fix linting issues

# Rust (rustfmt)
cargo fmt
```

### Type checking

```bash
# From the root directory
uv run mypy packages/py/citry_core
```

### Linting (Rust)

```bash
# From the root directory
cargo clippy
```

### Checks and validators

Quality is enforced by one explicit command, not a commit-time hook: `python scripts/check.py` runs the whole gate and is the same thing CI runs. Nothing runs automatically on `git commit`, so the tools never change your files behind your back; you run the gate when you choose and fix what it reports.

#### Running the checks

```bash
# The full gate: cargo fmt/clippy/test, ruff check/format, mypy, pytest, and the
# custom validators. Runs every phase, then reports all results in one pass.
python scripts/check.py

# Machine-readable: one JSON object with per-phase status (and the tail of any
# failing phase's output). Handy for tools and AI agents.
python scripts/check.py --reporter agent

# Run only the custom validators (fast; no compiling or tests).
python scripts/validate.py
```

`check.py` only checks; it never edits files. It assumes the workspace is set up (`uv sync --all-packages`) and that `cargo`, `uv`, and the Rust toolchain are on PATH.

#### Custom validators

The repo-specific invariants (every Python package has a Dependabot entry, the Rust bindings match the Python stub, the toolchain pins agree, every crate is a workspace member) live as small modules in `scripts/validators/`. They are **auto-discovered**: `scripts/validate.py` runs every `<name>.py` in that directory, so adding a check is just dropping in a new file (names starting with `_` are skipped).

Each validator exports a `check()` function that returns a list of problem descriptions; an empty list means the invariant holds:

```python
"""One line on what this invariant protects."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def check() -> list[str]:
    problems: list[str] = []
    # ... read files under REPO_ROOT; append a message for each violation ...
    return problems
```

The runner prints `PASS`/`FAIL` per validator and exits non-zero if any returns problems (or raises). There is no registration, argparse, or logging boilerplate to write: keep the module to the check logic and let `validate.py` (and `check.py`) handle running and reporting. If a validator needs an extra Python dependency, add it to the root `[dependency-groups].dev`.

#### CI integration

The gate runs in CI via the [`repo--check.yml`](../.github/workflows/repo--check.yml) workflow, which builds the workspace and runs `python scripts/check.py` on every change (no path filters). The per-language matrix workflows ([`rust--tests.yml`](../.github/workflows/rust--tests.yml), [`py--tests.yml`](../.github/workflows/py--tests.yml)) add cross-version and cross-OS test breadth on top of that single-environment gate.

### Adding a codebase-wide tooling package

To add a new tooling dependency (like a linter, formatter, or test utility) that should be available across the entire codebase:

1. Edit the root [`pyproject.toml`](../pyproject.toml) file
2. Add the package to the root `dev` dependency-group. Use this only for
   repo-wide tooling; a dependency used by a single package belongs in that
   package's own `[dependency-groups]` instead:

   ```toml
   [dependency-groups]
   dev = ["maturin>=1.10.2", "ruff>=0.8.0", "mypy>=1.0.0", "your-new-tool>=1.0.0"]
   ```

3. Install the new dependency:

   ```bash
   # From the root directory
   uv sync --all-packages
   ```

4. Use the tool:

   ```bash
   # From the root directory
   uv run your-new-tool
   ```

### Runtime optional-dependency extras (`citry[...]`)

Runtime extras on the `citry` package (the `pip install citry[...]` surface, as
opposed to the root `dev`/`ci` tooling extras above) are namespaced
`citry[<category>-<name>]` so the extras namespace stays collision-free and has
room to grow. Two categories exist so far:

- `watcher-<backend>`: a file-watcher backend for hot reload, e.g.
  `citry[watcher-watchfiles]`, `citry[watcher-watchdog]`. See
  [`docs/design/hot_reload.md`](design/hot_reload.md).
- `ext-<name>`: an optional or bundled extension and its dependencies, e.g. a
  future `citry[ext-storybook]`.

Rules:

1. **Always include the category prefix.** Do not add a bare `citry[watcher]` or
   `citry[storybook]`: an unprefixed token reads ambiguously (is `watcher` a
   backend name or a category?) and risks colliding with a future package or
   extension of the same name.
2. **Import the optional dependency lazily**, inside the module that needs it, so
   plain `import citry` never requires it (the contrib adapters and
   [`docs_site/cli.py`](../docs_site/cli.py) are the precedent).
3. **Mirror the pin into the root extras only if a test or the shared venv needs
   it.** Per the mirrored-dependency gotcha in [`/CLAUDE.md`](../CLAUDE.md),
   test and tooling deps are declared in both the package and the root
   `pyproject.toml` because CI and the shared venv install from the root. A
   runtime-only extra that no test imports (for example a watcher backend that
   the test suite exercises only through its protocol, never importing the
   backend) lives on the package alone. Either way, grep the name across all
   `pyproject.toml` files and CI workflows before pinning. (The mirroring goes
   away with the uv workspace conversion,
   [#8](https://github.com/citry-dev/citry/issues/8).)

### Adding a git submodule

To add a new third-party dependency as a git submodule:

1. **Determine the location**: Submodules are organized by language in [`third_party/`](../third_party/):

   - Rust - `third_party/rust/`
   - Python - `third_party/py/`
   - ect..

2. **Add the submodule**:

   ```bash
   # From the root directory
   # Example: Adding a Rust crate
   git submodule add https://github.com/example/upstream-repo.git third_party/rust/upstream-repo

   # Or for a specific tag/branch
   git submodule add -b v1.0.0 https://github.com/example/upstream-repo.git third_party/rust/upstream-repo
   ```

3. **Update documentation**: Add an entry to [`third_party/README.md`](../third_party/README.md) documenting:

   - What the dependency is for
   - Where it's used
   - License information
   - Update policy

4. **Update references**: If the submodule is used in code (e.g., `Cargo.toml` for Rust), update path references to point to the new location.

5. **Commit the changes**:

   ```bash
   git add .gitmodules third_party/rust/upstream-repo third_party/README.md
   git commit -m "Add upstream-repo as submodule"
   ```

**Initializing submodules** (for new clones):

```bash
# Initialize all submodules
git submodule update --init --recursive

# Or initialize a specific submodule
git submodule update --init third_party/rust/upstream-repo
```

**Updating a submodule**:

```bash
# Navigate to the submodule
cd third_party/rust/upstream-repo

# Fetch latest changes
git fetch origin --tags

# Checkout a specific tag/commit
git checkout v1.2.0

# Return to root and commit the update
cd ../../..
git add .gitmodules third_party/rust/upstream-repo
git commit -m "Update upstream-repo submodule to v1.2.0"
```

To keep track of the current version, update the comment in the `.gitmodules` file.

**Verifying builds after updating a submodule**:

After updating an upstream submodule, **always verify that everything still builds**. Upstream packages may introduce new dependencies that need to be added to the workspace `Cargo.toml`.

For example, when I upgraded `ruff` from v0.14.0 to v0.14.10, they added `datatest-stable` as a Rust dependency. So it had to be added to our root `Cargo.toml`:

### Adding Rust Dependencies

When adding a new Rust dependency to any crate in the workspace, follow these guidelines to ensure version consistency across the entire workspace:

1. **Add the dependency to the root `Cargo.toml`**: All dependency versions should be specified and pinned in the root [`Cargo.toml`](../Cargo.toml) under the `[workspace.dependencies]` section.

   ```toml
   [workspace.dependencies]
   your_new_dependency = { version = "1.2.3" }
   ```

2. **Use `workspace = true` in individual crates**: Individual crates should reference the workspace dependency using `workspace = true`, not specify versions directly:

   ```toml
   # In crates/your-crate/Cargo.toml
   [dependencies]
   your_new_dependency = { workspace = true }
   ```

   This ensures the entire workspace uses the same version of the dependency, preventing version conflicts and reducing binary size.

3. **Document upstream dependencies**: If the dependency was introduced because it's required by an upstream third-party package (like `ruff`), add a comment in the root `Cargo.toml` to document this:

   ```toml
   # Used by ruff_python_parser
   datatest-stable = { version = "0.3.3" }
   ```

   This helps track which dependencies are direct requirements vs. transitive requirements from upstream packages.

**Example**: Adding a new dependency to `python_safe_eval`:

1. Add to root `Cargo.toml`:

   ```toml
   [workspace.dependencies]
   # Used by python_safe_eval
   serde_json = { version = "1.0.113" }
   ```

2. Add to `crates/python_safe_eval/Cargo.toml`:

   ```toml
   [dependencies]
   serde_json = { workspace = true }
   ```

3. Run `cargo build` to verify it works.

### Adding a new package

When adding a new package to the monorepo (either a new Rust crate or a new Python package), you need to ensure that Dependabot is configured to watch its dependencies.

#### Rust packages

**No additional Dependabot configuration needed** for Rust crates. All Rust dependencies are centralized in the root [`Cargo.toml`](../Cargo.toml) under `[workspace.dependencies]`, so Dependabot automatically monitors all Rust dependencies when configured for the root directory.

The existing Dependabot entry for `package-ecosystem: "cargo"` at the root directory will cover all Rust crates in the workspace.

#### Python packages

**You must add a Dependabot entry** for each new Python package that has its own `pyproject.toml` with dependencies.

1. **Create the new Python package** in `packages/py/your-package/` with its own `pyproject.toml`

2. **Add a Dependabot entry** in [`.github/dependabot.yml`](../.github/dependabot.yml):

   ```yaml
   # Python - your-package
   - package-ecosystem: "pip"
     directory: "/packages/py/your-package"
     schedule:
       interval: "weekly"
   ```

3. **Verify the configuration** by checking that Dependabot can detect the package's dependencies.

**Note**: The root `pyproject.toml` already has a Dependabot entry for tooling dependencies (ruff, pytest, mypy, etc.). Each Python package with its own dependencies needs its own entry.

**Example**: If you add a new Python package `packages/py/citry/`, you would add:

```yaml
- package-ecosystem: "pip"
  directory: "/packages/py/citry"
  schedule:
    interval: "weekly"
```

### Working with Multiple Python Versions

UV can manage multiple Python versions automatically:

```bash
# Install a specific Python version
uv python install 3.11

# Use a specific version for this project
uv python pin 3.11

# Sync with that version
uv sync --all-packages
```

### CI Dependencies

CI installs the whole workspace from the lockfile, so it builds citry_core and installs every package's dev group reproducibly:

```bash
uv sync --locked --all-packages
```

## Rust-First Architecture

### Core Principle

**Rust is the source of truth** for all core functionality. Language bindings are thin wrappers that expose Rust functionality to other languages.

### Rust Workspace

The top-level `Cargo.toml` defines a workspace that includes:

- Core crates (`citry_core_py`, `citry_html_transform`, `python_safe_eval`, `citry_template_parser`)
- Shared dependencies and toolchain configuration
- Unified linting, formatting, and testing

### One binary, hand-owned Python API

All the Rust crates are exposed to Python through a single binding crate,
`citry_core_py`, compiled to one extension module, `citry_core._rust`. A
Rust-to-Python binary is large (on the order of ~100 MB), so bundling every
crate into one module ships one binary instead of one per crate.

The Python-facing API is written by hand rather than left as maturin's
auto-generated re-exports. The maturin-built binary is only a Python *module*
(`citry_core._rust`); the `citry_core` *package* wraps it with a thin Python
layer that unwraps union-returning Rust calls, adds Python-side error context,
and keeps a stable public surface (mirrored in the `_rust.pyi` stubs). That
layer is why the package can hold Python code beyond the raw bindings.

### Future Language Bindings

The architecture is designed to support multiple language bindings:

- **Python**: Via PyO3/maturin (current)
- **JavaScript/TypeScript**: Via wasm-bindgen (planned)
- **Go**: Via stable C ABI/FFI (planned)
- **PHP**: Via stable C ABI/FFI (planned)

## Python Packaging

### Package Structure

The Python package lives in `packages/py/citry_core/`.

**Key Files:**

- `packages/py/citry_core/pyproject.toml` - Package metadata and build configuration
- `packages/py/citry_core/__init__.py` - Public Python API
- Rust extension module built via maturin

### Build Configuration

The `pyproject.toml` in `packages/py/citry_core/`:

- Uses `maturin` as the build backend
- References the Rust crate at `../../../crates/citry_core_py/Cargo.toml`
- Includes Python source files via `[tool.maturin]` include paths

### Package vs Bindings

Currently, we have a single Python distribution (`citry_core`) that includes both:

- The Rust extension module (bindings)
- Python-side SDK code (helpers, types, error handling)

**Future consideration**: Split into two distributions:

- `citry_core` (thin): Only bindings + minimal shims
- `citry` (fat SDK): Full Python SDK that depends on `citry_core`

This would reduce verbosity in the package directory and allow independent versioning if needed.

## Dependency Management

### UV for Tooling

The root `pyproject.toml` uses **UV** for dependency management instead of traditional `requirements.txt` files.

**Why UV?**

- 10-100x faster than pip
- Better dependency resolution
- Built-in virtual environment management
- Lock files for reproducible builds

**Structure:** the root is a uv workspace; `packages/py/*` are members, and repo-wide tooling lives in a dependency-group:

```toml
[tool.uv.workspace]
members = ["packages/py/*"]

[dependency-groups]
dev = ["maturin>=1.10.2", "ruff>=0.8.0", "mypy>=1.0.0"]
```

**Usage:**

```bash
# Install the whole workspace (builds citry_core, installs citry editable,
# and pulls every package's dev group)
uv sync --all-packages

# Run tools
uv run pytest
uv run maturin develop
```

### Root pyproject.toml Protection

The root `pyproject.toml` is **explicitly marked as non-releasable**:

- No `[build-system]` section (prevents building)
- `"Private :: Do Not Upload"` classifier
- Version `0.0.0` with descriptive name

This prevents accidental releases while still allowing tooling configuration.

## Tooling Configuration

### Codebase-Wide Tools

The root `pyproject.toml` contains tool configurations that apply to the entire codebase:

- **Black**: Code formatting (119 char line length)
- **isort**: Import sorting (black-compatible)
- **flake8**: Linting (E302, W503 ignored)
- **mypy**: Type checking
- **pytest**: Test configuration

**Important**: These tools are **not** excluded from the `packages/` directory. They apply codebase-wide, including to all Python packages.

### Tool Exclusions

Tools exclude standard build artifacts and caches:

- `.venv`, `.tox`, `build`, `dist`
- `__pycache__`, `.mypy_cache`
- But **NOT** `packages/` - tools should run on package code

## Versioning Strategy

### Current Approach

- **Lockstep versioning**: All packages share the same version
- Version is defined in each package's `pyproject.toml`
- Rust crates may have independent versions (via `Cargo.toml`)

### Future Considerations

If we split into multiple Python distributions:

- Core package (`citry_core`) could have independent versioning
- SDK package (`citry`) would depend on compatible `citry_core` versions
- Or maintain lockstep versions for simplicity

## Changelog Management

### Single Root-Level Changelog

This monorepo uses a **single root-level `CHANGELOG.md`** that includes releases of all public-facing packages.

**Rationale:**

- **Simplicity**: Maintaining multiple changelog files across packages is cumbersome
- **User-friendly**: Users can see all relevant changes in one place
- **Scalability**: Works well even as the monorepo grows with multiple major projects and language bindings

**Structure:**

The root [`CHANGELOG.md`](../CHANGELOG.md) contains:

- All releases for public-facing packages (e.g., `citry_core` Python package)
- Version-specific release notes organized by version
- Feature additions, bug fixes, and breaking changes for all packages
- Migration guides when needed

**What's NOT included:**

- Internal package changes (e.g., Rust crates that aren't published)
- Monorepo infrastructure changes (these are documented in this `codebase.md`)

**Format:**

The changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format with sections for:

- `Added` - New features
- `Changed` - Changes in existing functionality
- `Deprecated` - Soon-to-be removed features
- `Removed` - Removed features
- `Fixed` - Bug fixes
- `Security` - Security fixes

**When adding entries:**

- Group changes by package when multiple packages are updated in the same release
- Use clear, user-facing language (not internal implementation details)
- Include migration notes for breaking changes
- Link to relevant issues/PRs when helpful

## Versioning, tags and releases

### Package-specific tags

This monorepo uses **package-specific git tags** to distinguish versions of different packages.

**Tag format:**

Tags follow the format: `<package-name>@<version>`. A tag with no language prefix means the Python package.

**Examples:**

- `citry-core@1.3.0` - the citry-core Python package
- `citry@0.2.0` - the citry Python package

**Note:** When a second host language (JS/PHP/Go) is published, we will revisit how to disambiguate its tags from the Python ones (likely a `<language>@` prefix on the non-default languages); until then the prefix would be noise. The version after `@` must match the package's `pyproject.toml` version: the publish workflow checks this and fails the release on a mismatch.

**Rationale:**

- **Clarity**: Each tag clearly identifies which package it refers to
- **Independent versioning**: Supports packages versioning independently
- **Filtering**: Easy to list tags for a specific package: `git tag -l "citry-core@*"`
- **Scalability**: Works well as the monorepo grows with multiple major projects and language bindings

### Current Release Process

Currently, releases are managed manually:

1. **Update version** in the package's `pyproject.toml` (or equivalent for other languages)
2. **Update CHANGELOG.md** with release notes
3. **Create the git tag** matching that version: `git tag -a citry-core@1.3.0 -m "Release citry-core@1.3.0"` (use `citry@0.2.0` for the citry package)
4. **Push the tag**: `git push origin citry-core@1.3.0`

Pushing the tag triggers the package's publish workflow, which verifies the tag matches the pyproject version, builds the distributions, smoke-tests them, and uploads to PyPI. **Release ordering**: citry depends on `citry-core`, so when bumping both, publish `citry-core` first and let it reach PyPI before tagging `citry`.

`citry` and `citry-core` are versioned and released **independently on purpose**, so each can ship on its own cadence. That is why the ordering above is a deliberate manual step rather than an automated cross-package release orchestrator: an orchestrator would couple the two releases, which is exactly what we want to avoid.

### Chronological Ordering

Git tags are ordered by the commit date they point to, not the date they were created. When packages version independently:

- Tags may appear out of chronological order in the tag list
- To list tags chronologically for a specific package: `git tag -l "citry-core@*" --sort=-version:refname`
- This is expected behavior and acceptable for independent versioning

### Future Tooling

As the monorepo grows, we may adopt automated tooling for versioning and releases:

**Potential Tools:**

- **Changesets**: Popular for npm/pnpm monorepos, supports independent versioning with `package-name@version` tags (can be configured for custom tag formats)
- **Lerna**: JavaScript-focused monorepo tool with flexible versioning strategies
- **Cocogitto**: Rust-focused tool that automates versioning based on conventional commits
- **Semantic Release**: Automated versioning based on commit messages
- **Release Please**: Google's tool that works with multiple languages and package managers

**Benefits of automation:**

- Automatic version bumping based on commit messages
- Automatic changelog generation
- Automatic tag creation
- Dependency version updates
- Coordinated releases across packages

**When to adopt:**

Consider adopting automated tooling when:

- Manual release process becomes error-prone or time-consuming
- Multiple packages are released frequently
- Coordinating releases across packages becomes complex
- Team size grows and release process needs standardization

### Workflow management

**Workflow file naming convention:**

Since GitHub Actions workflows cannot be nested in subdirectories (all workflow files must be in `.github/workflows/` at the root), we use a consistent naming convention to organize workflows by language and package:

**Format:** `<language>--<package-name>--<workflow-type>.yml`

**Examples:**

- `py--citry-core--publish.yml` - Publish Python citry-core package
- `py--citry-core--test.yml` - Test Python citry-core package (future)
- `js--citry-core--publish.yml` - Publish JavaScript citry-core package (future)
- `go--citry-core--publish.yml` - Publish Go citry-core package (future)

**Rationale:**

- **Double dashes (`--`)** clearly separate language → package → workflow type
- **Language prefix** (`py--`, `js--`, `go--`) namespaces the workflow file by language; release *tags* drop the prefix (a bare tag means Python), so the file naming is a separate scheme that still leaves room for other languages
- **Scalable** as the monorepo grows with multiple packages and languages
- **Easy to filter**: `ls .github/workflows/py--*` shows all Python workflows

**Package-Specific Workflow Triggers:**

Each publish workflow is configured to trigger only on tags for its specific package:

```yaml
on:
  push:
    tags:
      - "citry-core@*" # Only triggers for citry-core@1.3.0, etc.
```

This ensures:

- Workflows only run when their specific package is released
- No unnecessary workflow runs for unrelated package tags
- Clear separation of concerns per package

**Workflow Organization:**

- **Test workflows** use descriptive names: `repo--check.yml`, `rust--tests.yml`, `py--tests.yml`
- **Package-specific workflows** use the `language--package--type.yml` convention (e.g., `py--citry-core--publish.yml`)
- All workflows are in `.github/workflows/` (no subdirectories supported by GitHub)

## CI/CD Strategy

### Test Workflows

The repository uses **three separate test workflows** to optimize CI performance and only run tests when relevant code changes:

#### 1. `repo--check.yml` - The full gate

**Purpose**: Runs the whole check suite (`python scripts/check.py`) on all changes: formatting, lints, types, the custom validators, and a single-environment test pass.

**Triggers**: Runs on all pushes and pull requests (no path filters).

**What it runs**:

- `python scripts/check.py`: cargo fmt/clippy/test, ruff check/format, mypy, pytest, and the custom validators, every phase followed by a combined report
- The single source of truth for "does everything pass"

**Configuration**:

- Python 3.13 on ubuntu-latest, with the Rust nightly toolchain
- `uv sync --locked --all-packages` to build the workspace, then `python scripts/check.py`

#### 2. `rust--tests.yml` - Rust Tests

**Purpose**: Tests all Rust crates in the workspace.

**Triggers**: Runs when changes are made to:

- `crates/**` - Rust crate code
- `.github/**` - Workflow changes that might affect test execution
- `third_party/**` - Third-party dependencies (e.g., Ruff submodule)
- `.gitmodules` - Submodule configuration changes

**What it tests**:

- All Rust crates via `cargo test -p <package>` for each crate
- Tests only our crates (excludes Ruff submodule crates)

**Configuration**:

- Rust nightly toolchain (matching `rust-toolchain.toml`)
- Tests on ubuntu-latest and windows-latest
- Uses Rust dependency caching for faster builds

**Why path filters**: Avoids running Rust tests when only Python code, documentation, or unrelated files change.

#### 3. `py--tests.yml` - Python Tests

**Purpose**: Tests all Python packages.

**Triggers**: Runs when changes are made to:

- `packages/py/**` - Python package code
- `crates/**` - Rust code (Python packages depend on Rust via PyO3 bindings)
- `third_party/**` - Third-party dependencies used by both Rust and Python
- `.github/**` - Workflow changes
- `.gitmodules` - Submodule configuration changes

**What it tests**:

- Installs the whole workspace with `uv sync --locked --all-packages`, which builds the `citry_core` extension through maturin and installs `citry` editable, so both packages' suites run (`citry` did not run in CI before the uv workspace)
- Runs Python tests via `uv run --no-sync pytest`

**Configuration**:

- Python versions: 3.10, 3.11, 3.12, 3.13, 3.14
- OS: ubuntu-latest and windows-latest, plus a macOS smoke pair (oldest and newest Python)
- Requires Rust toolchain (`uv sync` builds the citry_core extension via maturin)
- Uses Rust dependency caching

**Why path filters**: Avoids running Python tests when only documentation, scripts, or unrelated files change. Includes `crates/**` because Python packages depend on Rust code via PyO3 bindings.

### Testing

- **Rust tests**: Run via `rust--tests.yml` workflow using `cargo test`
- **Python tests**: Run via `py--tests.yml` workflow, which installs the uv workspace (`uv sync --locked --all-packages`) and runs `uv run --no-sync pytest`
- **The full gate**: Run via `repo--check.yml`, which runs `python scripts/check.py` (lint, types, validators, single-env tests)
- **Dependencies**: Installed from the uv workspace lockfile; `--locked` keeps CI reproducible
- **Matrix testing**: Python tests run across Python versions (3.10-3.14) and OSes

### Publishing

Each Python package has its own tag-triggered publish workflow (`py--citry-core--publish.yml`, `py--citry--publish.yml`). Pushing a `<package>@<version>` tag builds the distributions, smoke-tests them, publishes to PyPI, and creates a matching GitHub Release.

**PyPI auth is Trusted Publishing (OIDC), not a stored API token.** The release jobs carry `id-token: write` and target a GitHub environment named `pypi`; PyPI verifies the workflow's OIDC identity, so there is no secret to keep. Before a package's first publish, configure a PyPI **publisher** (a *pending publisher* if the project does not exist yet) with:

- PyPI project name (`citry-core` / `citry`)
- Owner and repository (`citry-dev/citry`)
- Workflow filename (`py--citry-core--publish.yml` / `py--citry--publish.yml`)
- Environment name (`pypi`)

The first publish from a configured pending publisher creates the project. The GitHub `pypi` environment is also where you can add a manual-approval gate on releases.

- Rust crates are not published to crates.io; they are an internal implementation detail surfaced through the Python packages.
- The root `pyproject.toml` is never published (no build-system; `Private :: Do Not Upload`).

## Future Architecture

### Planned Expansions

1. **JavaScript/TypeScript Bindings**

   - WASM build via wasm-bindgen
   - Package in `packages/js/citry/`
   - Native Node.js addon as alternative

2. **Go Bindings**

   - Stable C ABI from `crates/ffi/`
   - Go wrapper in `packages/go/citry/`
   - Generated header file in `include/citry.h`

3. **PHP Bindings**
   - Same C ABI as Go
   - PHP extension in `packages/php/citry/`

### FFI Crate

A future `crates/ffi/` crate will provide:

- Stable C ABI boundary
- Language-agnostic interface
- Used by Go, PHP, and potentially other languages
- Generated headers committed to repo

## Design Principles

1. **Rust First**: Core logic always in Rust
2. **Thin Bindings**: Language bindings are minimal wrappers
3. **Idiomatic APIs**: Packages provide language-native interfaces
4. **Single Source of Truth**: One implementation, multiple interfaces
5. **Tooling at Root**: Shared configuration, not duplicated
6. **Explicit Non-Releasable**: Root config clearly marked as tooling-only

## Migration Notes

### From Single Package to Monorepo

The codebase was migrated from a single-package structure to a monorepo:

- **Before**: Root `pyproject.toml` for both tooling and package
- **After**:
  - Root `pyproject.toml` for tooling only
  - `packages/py/citry_core/pyproject.toml` for package

### Path Updates

When moving the package `pyproject.toml`:

- `manifest-path` updated to `"../../../crates/citry_core_py/Cargo.toml"`
- `readme` updated to `"../../../README.md"`
- Maturin include paths remain relative to package directory
