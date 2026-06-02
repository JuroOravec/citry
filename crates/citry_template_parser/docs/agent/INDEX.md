# Agent knowledge - citry_template_parser

Deep architecture for the V3 template parser and compiler. For repo-wide rules
see [`/CLAUDE.md`](../../../../CLAUDE.md). For cross-crate facts (the V1/V2/V3
version model, the binding architecture, repo-wide anti-patterns) see
[`/docs/agent/INDEX.md`](../../../../docs/agent/INDEX.md).
For quick pointers and gotchas see [`../../AGENTS.md`](../../AGENTS.md).

When you discover a non-obvious fact while working in this crate, propose a new
entry here. Keep each one to a paragraph; link to source with `file:line`.

---

## The pipeline

```
template string
  -> Pest grammar (grammar.pest)        : tokens / rule tree
  -> parser.rs (parse_template)         : Template AST (tree of Node / TemplateElement)
  -> compiler.rs (compile_template)     : Vec<LangSpecArgument> (codegen IR)
  -> lang/<lang>.rs (LangImpl::compile)  : host-language source string
```

For Python the final string is a `generate_template()` function that returns a
`body` list of runtime node objects. Those node classes live on the Python
side (not yet implemented; see the cross-crate INDEX "Open project plans").

---

## Grammar (`grammar.pest`)

Pest rule atomicity markers matter a lot here:

- `{ }` non-atomic: Pest inserts implicit whitespace between sequence elements
  and repetitions (because a `WHITESPACE` rule is defined).
- `@{ }` atomic: no implicit whitespace, and inner rules are silenced (no
  tokens). Cascades to called rules.
- `${ }` compound-atomic: no implicit whitespace, but inner rules still produce
  tokens. The no-whitespace property cascades to called rules.

**`template` is compound-atomic (`${ }`) on purpose.** A `WHITESPACE = _{ ... }`
rule is defined, so a non-atomic `template` would let Pest silently skip
whitespace between `template_element` repetitions, dropping (for example) the
space right after a closing tag. Making `template` compound-atomic stops that.
Because atomicity cascades, `html_comment` and `html_raw` (reached from
`template_element`) are also matched without implicit whitespace; this is why
HTML-comment values include their surrounding spaces symmetrically, and why
`<c-raw attr>` matches the raw rule (the parser then rejects the attribute, see
Validation). The tag rules (`html_start_tag`, `html_end_tag`,
`html_self_closing_tag`) are already `${ }` and use explicit `spacing` /
`spacing_with_whitespace` rules, so they are unaffected.

Pest grammars cannot match nested structure dynamically (a closing tag cannot
be required to match its opener's name in the grammar), so the grammar only
recognizes individual start / end / self-closing tags; the tree is assembled in
the parser with a stack.

`<c-raw>` content is grabbed as raw text by the grammar (`html_raw_content`)
because it may not be valid template syntax.

## AST (`ast.rs`)

Top type is `Template { elements, comments, used_variables, slots }`. A
`TemplateElement` is one of `Text`, `Expr` (a `{{ }}` expression), `Node` (a
tag), or it is a comment (collected into `comments`, not kept as an element,
except HTML comments which are also kept as `Text`). A `Node` is either
`SelfClosing { start_tag, .. }` or `WithBody { start_tag, end_tag, body, .. }`,
and carries `used_variables`, `introduced_variables`, `comments`, and
`contains_fills`. `HtmlAttr` carries `key`, `value`, `inner_value`,
`quote_char`, `kind` (`Static` / `Expression` / `Template`), `used_variables`,
and `comments`. `Token` is the shared span type (`content`, `start_index`,
`end_index`, `line_col`).

Types annotated `#[pyclass]` are the Python contract. Changing their shape is a
high-risk change: update the PyO3 registration, the `_rust.pyi` stub, and the
Python wrapper together (CLAUDE.md Mechanism 4).

## Parser (`parser.rs`)

`parse_template(input, lang, user_rules)` builds the tree:

- An HTML tag stack assembles `WithBody` nodes; a closing tag pops and must
  match the open tag's name, else a mismatched-tags error.
- Void elements (`constants::HTML_VOID_ELEMENTS`) are treated as self-closing.
- `c-*` attributes are classified: a value that parses as a nested template
  (starts with `<tag` or `<>` and ends correspondingly) becomes `Template`;
  otherwise `Expression`. Plain attributes are `Static`. Fragment delimiters
  `<>...</>` are stripped at the attribute level (not in the grammar).
- Variable tracking: `used_variables` is collected from attributes and body in
  source order (a `Vec`, not a set, so order is stable);
  `introduced_variables` come from `<c-for>` loop targets and `<c-fill>`
  `data` / `default`. Python variable extraction delegates to
  `python_safe_eval` via the `LangImpl`.
- Control-flow grouping (`<c-if>/<c-elif>/<c-else>`, `<c-for>/<c-empty>`) is
  validated for adjacency and ordering (`constants::TAG_ORDERING_RULES`).

Validation runs through `validate_node` (fill placement, attributes present,
attribute conflicts, `c-bind`, fill names, variable shadowing). **`<c-raw>` is
the exception:** `process_html_raw` builds the node directly and bypasses
`validate_node`, so it calls `validate_attributes_present` itself to reject
attributes on raw tags. Attribute and slot rules per tag are data-driven in
`constants::TAG_ATTR_RULES_DATA` / `TAG_SLOT_RULES_DATA`.

## Compiler (`compiler.rs`) and the output-format contract

The **module-level docstring** at the top of `compiler.rs` is the definitive
reference for the node types emitted, their signatures, and the formatting
conventions (trailing commas, triple-quoted strings, coalescing, name
normalization, void-element rendering, determinism). Read it first; this
section covers only the high-level flow and agent-relevant non-obvious facts.

`compile_template(template, lang)` first calls
`wrap_nodes_with_control_flow_attrs` (turning `c-if`/`c-for` attributes on a
regular tag into wrapping `<c-if>`/`<c-for>` nodes; IF has higher priority than
FOR, so IF wraps FOR), then walks elements into a `Vec<LangSpecArgument>`, then
hands that to `LangImpl::compile`. Consecutive static strings are coalesced.

`LangSpecArgument` (in `lang/lang.rs`) is the language-agnostic codegen IR:
`Variable`, `UnsafeString` (escaped), `SafeString`, `Int`, `Bool`, `Tuple`,
`List`, `Struct { name, arguments }`.

Non-obvious facts not covered in the module doc:

- On a regular HTML tag (not a component), dynamic `c-*` attributes are split
  inline as string fragments + `ExprNode`/`TemplateNode` between them,
  concatenated at runtime. They are *not* wrapped in `*HtmlAttr` calls (those
  only appear in component/slot/fill attribute tuples).
- Expression content retains its trailing whitespace from `{{ expr }}`.
- `<c-raw>` compiles as a `ComponentNode` named `"""raw"""`, not a dedicated
  node type.

Compiler tests are in `tests/tag_compiler.rs` and assert exact generated
strings (the observe-then-lock style).

## Lang trait (`lang/lang.rs`)

`LangImpl` has `parse_expression` (returns used / assigned vars and comments),
`parse_forloop_expression` (extracts loop target variables), and `compile`
(turns the codegen IR into a source string). `Lang` is the enum
(`Python`/`Php`/`Js`/`Go`/`Rust`); `Lang::to_lang_impl` maps to the static
impl. **Only `python.rs` is complete** (it uses `python_safe_eval` and Ruff's
Python AST); the other four are structural stubs that extract variables with
regex heuristics and do not do real parsing. Adding or changing a trait method
is a cross-language change.

## Tests

One file per feature area under `tests/` (structure, html, kwargs,
boolean_attrs, dynamic_attrs, expressions, comments, nested_templates, spreads,
control_flow_if, control_flow_for, fills, composition, raw, user_rules), plus
`tag_compiler.rs` for compiler output. Shared AST builders are in
`tests/common/mod.rs`. Parser tests assert the full AST via `assert_eq!`;
compiler tests assert the exact generated string. Both are authored
observe-then-lock. Illustrative code blocks in doc comments (in `lang/rust.rs`
and `parser_context.rs`) are marked ```` ```ignore ```` so the doctest runner
skips them.
