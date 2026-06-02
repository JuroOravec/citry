# AGENTS.md - crates/citry_core_py

The PyO3 glue crate. It is a single `_rust` Python extension module that brings
the other Rust crates together and exposes them to Python as submodules. This
crate defines exactly what Python sees.

For repo-level rules see [`/CLAUDE.md`](../../CLAUDE.md). For cross-crate facts
see [`/docs/agent/INDEX.md`](../../docs/agent/INDEX.md).

## Where to look

- `src/lib.rs` - the `#[pymodule] fn _rust(...)`. Registers each submodule and
  its functions / classes. This is the registration point for everything Python
  can import.
- `src/html_transform.rs` - wraps `citry_html_transform`.
- `src/safe_eval.rs` - wraps `python_safe_eval`.
- `src/template_parser.rs` - wraps `citry_template_parser` (currently not
  registered; see Gotchas).
- `Cargo.toml` - depends on the sibling crates by path; `crate-type =
  ["cdylib"]`.

## Gotchas

- **The `template_parser` module is commented out in `src/lib.rs`.** The V3
  parser is not yet exposed to Python. Wiring it up is the next major step (see
  the cross-crate INDEX "Open project plans"): uncomment and update the module,
  exposing the V3 AST types and `parse_template` / `compile_template`.
- **The Python module name comes from the `#[pymodule]` function name** (`_rust`)
  and must match the `module-name` setting in the Python package's
  `pyproject.toml`. See [`packages/py/citry_core/AGENTS.md`](../../packages/py/citry_core/AGENTS.md).
- **Every `#[pyclass]` / `#[pyfunction]` exposed here must be mirrored** in
  [`packages/py/citry_core/citry_core/_rust.pyi`](../../packages/py/citry_core/citry_core/_rust.pyi).
  The stub is hand-written and is the IDE/type-check contract.

## Verifying changes

Build the Python extension and run the Python tests from the package directory:

```bash
cd packages/py/citry_core && uv run maturin develop && cd -
uv run pytest
```
