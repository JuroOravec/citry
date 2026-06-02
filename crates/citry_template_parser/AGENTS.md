# AGENTS.md - crates/citry_template_parser

The V3 template parser and compiler: it turns a Citry template string into an
AST, and compiles that AST into host-language source code. This is the active
frontier of the project and the highest-risk crate to change.

For repo-level rules see [`/CLAUDE.md`](../../CLAUDE.md). For cross-crate facts
see [`/docs/agent/INDEX.md`](../../docs/agent/INDEX.md). For
deep architecture of this crate (grammar, AST, parser, compiler, lang impls,
validation, the exact compiler output format), see
[`docs/agent/INDEX.md`](docs/agent/INDEX.md).

## Where to look

- `src/grammar.pest` - the Pest grammar. Read the atomicity gotcha below before
  touching it.
- `src/grammar.rs` - the `pest_derive` parser binding (`Rule` enum).
- `src/ast.rs` - AST node structs. `#[pyclass]` types are the Python contract.
- `src/parser.rs` - `parse_template`; builds the tree with an HTML tag stack,
  classifies `c-*` attributes, tracks variables, runs validation.
- `src/compiler.rs` - `compile_template`; turns the AST into host-language
  source (for Python, a `generate_template()` function returning a node list).
- `src/lang/lang.rs` - the `LangImpl` trait and the `LangSpecArgument` codegen
  IR. `src/lang/{python,js,php,go,rust}.rs` - per-language impls (Python is
  complete; the others are structural stubs).
- `src/constants.rs` - tag names, node class names, void elements, attribute
  validation rules, control-flow groups, tag ordering rules.
- `src/parser_context.rs` - `ParserContext` and user-supplied `TagRules`.
- `tests/` - one file per feature area, plus `tests/common/mod.rs` (AST builder
  helpers) and `tests/tag_compiler.rs` (compiler output assertions).

## Gotchas

- **Pest atomicity cascades.** The `template` rule is compound-atomic (`${ }`)
  to stop implicit whitespace being dropped between elements; that atomicity
  flows into `html_comment` and `html_raw`. Do not change a rule's atomicity
  without checking the rules it calls. Full explanation in the deep INDEX.
- **Compiler output must be deterministic.** Never iterate a `HashSet` into the
  emitted string; dedupe preserving first-seen order.
- **Tests are observe-then-lock.** Run the parser/compiler, observe real output,
  then assert it exactly. Do not hand-compute token offsets or codegen strings.
- **V1/V2/V3 context.** This crate implements V3. The `v2_*.md` files are
  working notes, not a spec. See the cross-crate INDEX for the version model.
- **Not yet wired to Python.** The PyO3 module that would expose this crate is
  commented out in `crates/citry_core_py/src/lib.rs`.

## Verifying changes

```bash
cargo test -p citry_template_parser          # 226 unit tests + ignored doctests
cargo test -p citry_template_parser --no-fail-fast   # see every file's result
```

Run the suite more than once after grammar/compiler changes to catch
non-determinism.
