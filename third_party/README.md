# Third-party dependencies

This directory contains upstream git submodules and vendored dependencies that are not part of our core codebase.

## Structure

Third-party dependencies are organized by language:

- `rust/` - Rust crates and dependencies
- `py/` - Python packages
- `js/` - JavaScript/TypeScript packages
- `go/` - Go packages
- `php/` - PHP packages

## Current dependencies

### Rust

- **ruff** (`rust/ruff/`) - Python parser and AST library used by `djc-safe-eval`

  - **URL**: https://github.com/astral-sh/ruff.git
  - **Used by**: `crates/djc-safe-eval`
  - **License**: MIT
  - **Update policy**: Pin to specific tags/commits, update intentionally

  NOTE: While Rust's Cargo has a feature to define a dependency via git URL,
  this didn't work for unknown reason. And Ruff's Python parser is an internal package. Hence why this is defined as git submodule.

## Adding a new submodule

See the [Common Development Tasks](../docs/codebase.md#adding-a-git-submodule) documentation for instructions on adding new git submodules.

## License compliance

All third-party dependencies should have their licenses documented here. Ensure compliance with all upstream licenses when using these dependencies.
