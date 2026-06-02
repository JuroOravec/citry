# AGENTS.md - packages/py/citry_core

The Python package (`citry_core` on PyPI). A mixed Rust/Python package: maturin
builds the Rust `_rust` extension from `crates/citry_core_py`, and the
hand-written Python modules here wrap it in a language-native API.

For repo-level rules see [`/CLAUDE.md`](../../../CLAUDE.md). For cross-crate
facts see [`/docs/agent/INDEX.md`](../../../docs/agent/INDEX.md).

## Where to look

- `citry_core/_rust.pyi` - **hand-written type stub** mirroring everything the
  Rust `_rust` module exposes. This is the IDE / type-check contract; keep it in
  sync with `crates/citry_core_py/src/lib.rs`.
- `citry_core/html_transform/` - wraps the `html_transform` submodule.
- `citry_core/safe_eval/` - sandboxed expression eval (`eval.py`, `sandbox.py`,
  `error.py`); wraps the `safe_eval` submodule.
- `citry_core/template_parser/` - V3 parser/compiler wrapper. **Work in
  progress**: it currently targets the older V1/V2 API and depends on the
  `_rust.template_parser` module that is commented out in the Rust glue. It will
  be rewritten for the V3 API when the parser is wired through.
- `pyproject.toml` - `[tool.maturin]` config. `module-name = "citry_core._rust"`
  and `manifest-path` point maturin at `crates/citry_core_py`. The long comment
  there explains why the module name mapping is necessary.
- `tests/` - `test_html_transformer.py` and `test_safe_eval.py` run in CI. The
  `_test_template_parser__*.py` files are disabled (leading underscore) pending
  the V3 wiring.

## Gotchas

- **The package name (`citry_core`) and the Rust extension name (`_rust`)
  differ from the Rust crate name (`citry_core_py`).** The maturin
  `module-name` setting bridges them; do not "fix" the mismatch by renaming.
- **`_rust.pyi` is the contract** consumers and the type checker see. When the
  Rust surface changes, update the stub in the same change.

## Verifying changes

```bash
# from this directory: build the extension, then run tests from the repo root
uv run maturin develop
cd ../../.. && uv run pytest && uv run mypy packages/py/citry_core
```
