use python_safe_eval::transformer::{
    parse_expression_with_adjusted_error_ranges, transform_expression_string,
    Comment as SafeEvalComment, Token as SafeEvalToken,
};
use ruff_python_ast::Expr as PythonAstExpr;

use crate::ast::{Comment, Token};
use crate::lang::lang::{ForLoopVars, LangImpl, LangSpecArgument, ParseExprResult};

/// Python language implementation
#[derive(Copy, Clone)]
pub struct PythonLang;

/// Static instance of PythonLang for use as a default
pub static PYTHON_LANG: PythonLang = PythonLang;

impl LangImpl for PythonLang {
    fn parse_expression(&self, source: &str) -> Result<ParseExprResult, String> {
        // Delegate to python_safe_eval to parse the expression and get metadata about
        // used variables, assigned variables, and comments.
        let transform_result = transform_expression_string(source)?;

        // Convert SafeEvalToken to citry_template_parser Token
        let convert_token = |safe_token: SafeEvalToken| -> Token {
            Token {
                content: safe_token.content,
                start_index: safe_token.start_index,
                end_index: safe_token.end_index,
                line_col: (safe_token.line_col.0, safe_token.line_col.1),
            }
        };

        // Convert SafeEvalComment to citry_template_parser Comment
        let convert_comment = |comment: SafeEvalComment| -> Comment {
            Comment {
                token: convert_token(comment.token),
                value: convert_token(comment.value),
            }
        };

        Ok(ParseExprResult {
            used_vars: transform_result
                .used_vars
                .into_iter()
                .map(convert_token)
                .collect(),
            assigned_vars: transform_result
                .assigned_vars
                .into_iter()
                .map(convert_token)
                .collect(),
            comments: transform_result
                .comments
                .into_iter()
                .map(convert_comment)
                .collect(),
        })
    }

    fn parse_forloop_variables(&self, source: &str) -> Result<ForLoopVars, String> {
        // `a, b in items` is not a valid expression on its own, so we wrap it in a
        // generator and analyse that: `(None for a, b in items)`. Both halves of
        // the result come from this one wrapped clause.
        let prefix = "(None for ";
        let prefix_len = prefix.len();
        let wrapped_expr = format!("{}{})", prefix, source);

        // --- Introduced (loop target) variables ---
        // Parse the comprehension and walk each generator's target. (Parsing
        // errors are reported against the ORIGINAL source, hence the prefix-aware
        // helper.)
        let ast = parse_expression_with_adjusted_error_ranges(&wrapped_expr, source, prefix_len)?;

        // Extract the expression from the module
        let module = ast.syntax();

        // Check if it's a generator expression
        let generators = match module.body.as_ref() {
            PythonAstExpr::Generator(expr_gen) => {
                // Must have at least one generator
                if expr_gen.generators.is_empty() {
                    return Err(
                        "Tag '<c-for>' 'each' attribute must contain at least one 'for ... in ...' clause."
                            .to_string(),
                    );
                }
                &expr_gen.generators
            }
            _ => {
                return Err(
                    "Tag '<c-for>' 'each' attribute must be a comprehension expression (e.g., 'target in iterable' or 'x in range(3) for y in range(2) if x > y')."
                        .to_string(),
                );
            }
        };

        // Extract variable tokens from all generators
        let mut introduced = Vec::new();
        for comprehension in generators {
            let var_tokens = _extract_variable_names_from_comp_target(
                &comprehension.target,
                source,
                prefix_len,
            )?;
            // NOTE: This should never raise, because Ruff would error first.
            if var_tokens.is_empty() {
                return Err(
                    "Tag '<c-for>' 'each' attribute: each 'for ... in ...' clause must have at least one loop variable."
                        .to_string(),
                );
            }
            introduced.extend(var_tokens);
        }
        // If no variables were found, raise error
        // NOTE: This should never raise, because Ruff would error first.
        if introduced.is_empty() {
            return Err(
                "Tag '<c-for>' 'each' attribute must have at least one loop variable.".to_string(),
            );
        }

        // --- Used (free) variables ---
        // Reuse the scope-aware expression analyser on the same wrapped clause. It
        // treats the comprehension targets as bound, so the reported used
        // variables are exactly the free variables of the iterable/condition
        // clauses. The tokens are positioned relative to `wrapped_expr`; shift
        // them back so they are relative to `source`. A token inside the synthetic
        // prefix is not part of the user's source and is dropped (the prefix only
        // contains the `None` keyword, never a used variable, so this is a safety
        // net).
        let used = self
            .parse_expression(&wrapped_expr)?
            .used_vars
            .into_iter()
            .filter_map(|mut token| {
                if token.start_index < prefix_len {
                    return None;
                }
                token.start_index -= prefix_len;
                token.end_index -= prefix_len;
                // The synthetic prefix is single-line, so only first-line columns shift.
                if token.line_col.0 == 1 {
                    token.line_col = (1, token.line_col.1 - prefix_len);
                }
                Some(token)
            })
            .collect();

        Ok(ForLoopVars { introduced, used })
    }

    // Generate code for a Python function that returns a list of node objects (TextNode, ExprNode, etc.)
    // that represent the template structure.
    //
    // ```python
    // def generate_template():
    //     body = [
    //         """Hello, \"John\"!""",
    //         ExprNode(source, (14, 19), """a + b""", ("a", "b")),
    //         ComponentNode(source, (14, 19), (HtmlAttr(...), ...),
    //         """<a href=\"""",
    //         ExprNode(source, (14, 19), """base + 'foo'""", ("base",)),
    //         """\">Click me!</a>""",
    //         ...
    //     ]
    //     return body
    // ```
    //
    // The body is kept as a list, so it can be optimized at runtime by replacing
    // nodes with their result as text, if we find that they are static.
    fn compile(&self, args: Vec<LangSpecArgument>) -> Result<String, String> {
        let mut final_code = String::new();
        final_code.push_str("def generate_template():\n");
        final_code.push_str("    body = ");
        final_code.push_str(&format_list(&args));
        final_code.push_str("\n");
        final_code.push_str("    return body\n");

        Ok(final_code)
    }
}

/// Format a single `LangSpecArgument` as a Python string representation.
fn format_lang_spec_arg(arg: &LangSpecArgument) -> String {
    match arg {
        LangSpecArgument::Variable(name) => name.clone(),
        LangSpecArgument::UnsafeString(content) => escape_text_in_triple_quotes(content),
        LangSpecArgument::SafeString(content) => format!("\"{}\"", content),
        LangSpecArgument::Int(value) => value.to_string(),
        LangSpecArgument::Bool(value) => {
            if *value {
                "True".to_string()
            } else {
                "False".to_string()
            }
        }
        // Format a list of strings as a Python tuple, e.g. `(a, b,)`
        // Always includes trailing comma to ensure single-item tuples are valid: `(a,)` not `(a)`
        LangSpecArgument::Tuple(elements) => {
            let items: Vec<String> = elements.iter().map(format_lang_spec_arg).collect();
            let tuple_str = if items.is_empty() {
                "()".to_string()
            } else {
                format!("({},)", items.join(", "))
            };
            tuple_str
        }
        // Format a list of strings as a Python list, e.g. `[a, b,]`
        // Always includes trailing comma for consistency
        LangSpecArgument::List(elements) => format_list(&elements),
        // Generate function / instance call, e.g.
        // ```py
        // NodeClass(
        //    source,
        //    (start, end),
        //    (HtmlAttr(...), HtmlAttr(...), ...),
        //    [body_item1, body_item2, ...],
        //    ("var1", "var2", ...),
        //    ("introduced_var1", "introduced_var2", ...),
        // )
        // ```
        LangSpecArgument::Struct(struct_arg) => {
            let items: Vec<String> = struct_arg
                .arguments
                .iter()
                .map(format_lang_spec_arg)
                .collect();
            format!("{}({})", struct_arg.name, items.join(", "))
        }
    }
}

/// Format a vector of `LangSpecArgument` as a Python list.
///
/// Converts each `LangSpecArgument` to its Python string representation.
fn format_list(args: &Vec<LangSpecArgument>) -> String {
    let items: Vec<String> = args.iter().map(format_lang_spec_arg).collect();
    let list_str = if items.is_empty() {
        "[]".to_string()
    } else {
        format!("[{},]", items.join(", "))
    };
    list_str
}

/// Extract variable tokens from a Python AST comprehension target.
///
/// AKA the `x, y, z` part in `(... for x, y, z in ...)`
///
/// Handles:
/// - `ExprName` → `x, y, z for my_list`
/// - `ExprTuple` → `(x, y, z) for my_tuple`
/// - `ExprStarred` → `a, *my_list for my_list`
///
/// Returns a vector of Tokens with positions relative to the source string.
///
/// **Errors:**
/// - If the expression type is not a valid target (e.g., attribute access, calls, etc.)
fn _extract_variable_names_from_comp_target(
    expr: &PythonAstExpr,
    source: &str,
    prefix_len: usize,
) -> Result<Vec<Token>, String> {
    match expr {
        PythonAstExpr::Name(expr_name) => {
            // Get the range from the AST (relative to the wrapped expression)
            let range = expr_name.range;
            let ast_start = range.start().to_usize();
            let ast_end = range.end().to_usize();

            // Adjust positions: subtract prefix_len to get position in original expression
            let adjusted_start = ast_start.saturating_sub(prefix_len);
            let adjusted_end = ast_end.saturating_sub(prefix_len);

            // Calculate line and column from the adjusted byte offset
            let (line, col) = _byte_offset_to_line_col(source, adjusted_start);
            let content = expr_name.id.as_str().to_string();

            Ok(vec![Token {
                content,
                start_index: adjusted_start,
                end_index: adjusted_end,
                line_col: (line, col),
            }])
        }
        PythonAstExpr::Tuple(expr_tuple) => {
            let mut tokens = Vec::new();
            for elt in &expr_tuple.elts {
                tokens.extend(_extract_variable_names_from_comp_target(elt, source, prefix_len)?);
            }
            Ok(tokens)
        }
        PythonAstExpr::Starred(expr_starred) => {
            _extract_variable_names_from_comp_target(&expr_starred.value, source, prefix_len)
        }
        // Other expression types are not valid targets
        _ => Err(format!(
            "Invalid expression type in loop variable: expected variable name, tuple, or starred expression, but found: {:?}",
            std::mem::discriminant(expr)
        )),
    }
}

/// Calculate line and column from a byte offset in a string
///
/// Returns (line, column) where both are 1-indexed.
fn _byte_offset_to_line_col(source: &str, byte_offset: usize) -> (usize, usize) {
    // Clamp offset to source length
    let offset = byte_offset.min(source.len());

    // Count newlines up to the offset
    let mut line = 1;
    let mut last_newline_pos = 0;

    // Iterate through the string up to the offset, counting newlines
    for (pos, ch) in source.char_indices() {
        if pos >= offset {
            break;
        }
        if ch == '\n' {
            line += 1;
            last_newline_pos = pos + 1; // +1 to skip the newline itself
        }
    }

    // Column is the byte offset from the last newline (or start), plus 1 (1-indexed)
    let column = (offset - last_newline_pos) + 1;

    (line, column)
}

/// Escape text content for use in Python triple-quoted strings.
///
/// This escapes backslashes, double quotes (including triple-quote sequences),
/// and carriage returns. Always uses triple double quotes `"""` for consistency.
///
/// A literal newline is left as-is: it is legal inside a triple-quoted string and
/// round-trips faithfully. A carriage return must be escaped as `\r`, because
/// Python applies universal-newline normalization to *source* before tokenizing,
/// so a raw `\r` (or `\r\n`) inside a literal would be silently rewritten to `\n`,
/// losing the original bytes.
fn escape_text_in_triple_quotes(text: &str) -> String {
    // Escape backslashes first (so we don't double-escape), then escape double
    // quotes (so even `"""` becomes `\"\"\"` and won't terminate the string),
    // then carriage returns (so they survive Python's universal-newline handling).
    let escaped = text
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\r', "\\r");
    format!("\"\"\"{}\"\"\"", escaped)
}
