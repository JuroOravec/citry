# AGENTS.md - crates/citry_html_transform

Adds or modifies attributes on HTML elements (root element and/or all elements)
using a `quick-xml` based pass over the markup. Small and stable.

For repo-level rules see [`/CLAUDE.md`](../../CLAUDE.md). For cross-crate facts
see [`/docs/agent/INDEX.md`](../../docs/agent/INDEX.md).

## Where to look

- `src/lib.rs` - re-exports `transform_html` and `HtmlTransformerConfig`.
- `src/transformer.rs` - the transformation logic.
- `tests/transformer.rs` - the tests.

## Who depends on it

`crates/citry_core_py` exposes it to Python as the `html_transform` submodule
(wrapped on the Python side in `citry_core/html_transform/`).

## Verifying changes

```bash
cargo test -p citry_html_transform
```
