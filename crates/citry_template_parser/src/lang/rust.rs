use crate::ast::Token;
use crate::lang::lang::{LangImpl, LangSpecArgument, ParseExprResult};

/// Rust language implementation
///
/// ## Important Note: Expression Language
///
/// **Rust expressions in templates are NOT raw Rust code.** Instead, they use domain-specific
/// expression languages designed for safe, runtime evaluation. This is because:
///
/// - Rust is a compiled language with no native runtime code execution
/// - Rust has no built-in `eval()` function
/// - Expression languages provide safer, more controlled evaluation
///
/// The expression language will be one of:
/// - **CEL-Rust** (Common Expression Language) - Same language as CEL-Go
/// - **fasteval** - Fast and safe algebraic expression evaluator
/// - **evalexpr** - Powerful expression evaluation engine
/// - **Rhai** - Embedded scripting language (can be restricted to expressions)
/// - **Reval** - Lightweight expression evaluator
///
/// ## Available Rust Expression Language Crates
///
/// ### 1. CEL-Rust (Recommended for standardization)
/// - **Repository**: https://github.com/cel-rust/cel-rust
/// - **Type**: Common Expression Language interpreter in Rust
/// - **Features**:
///   - Same language as CEL-Go (cross-language compatibility)
///   - Non-Turing complete (safer)
///   - C-like syntax
///   - Supports lists, maps, JSON, Protocol Buffers
///   - Macros for bounded iteration
/// - **Installation**: `cel` or `cel-parser` crate
/// - **Example expressions**:
///   - `user.name == "admin"`
///   - `request.time - resource.age < duration("24h")`
///
/// ### 2. fasteval (Recommended for performance)
/// - **Repository**: https://github.com/likebike/fasteval
/// - **Type**: Fast and safe evaluation of algebraic expressions
/// - **Features**:
///   - Extremely fast (top performance in benchmarks)
///   - Safe for untrusted input (restricts to mathematical operations by default)
///   - Supports both interpreted and compiled evaluation modes
///   - Customizable limits (expression size, nesting depth, etc.)
/// - **Installation**: `fasteval` crate
/// - **Example expressions**:
///   - `2 + 3 * 4`
///   - `sin(x) + cos(y)`
///
/// ### 3. evalexpr
/// - **Repository**: https://github.com/ISibboI/evalexpr
/// - **Type**: Powerful expression evaluation engine
/// - **Features**:
///   - Wide range of operators
///   - User-defined functions
///   - Serde support (serialization/deserialization)
///   - C-style comments support
///   - Type safety
/// - **Installation**: `evalexpr` crate
/// - **Example expressions**:
///   - `x + y * z`
///   - `if x > 5 then "high" else "low"`
///
/// ### 4. Rhai
/// - **Repository**: https://github.com/rhaiscript/rhai
/// - **Type**: Embedded scripting language (can be restricted to expressions)
/// - **Features**:
///   - Full scripting language (can be limited to expressions only)
///   - JavaScript/Rust-like syntax
///   - Tight integration with Rust functions and types
///   - Plugin system with procedural macros
///   - Can disable keywords/operators for safety
/// - **Installation**: `rhai` crate
/// - **Note**: More powerful than needed for simple expressions, but can be restricted
///
/// ### 5. Reval (Rust Evaluator)
/// - **Repository**: https://github.com/antonmedv/reval
/// - **Type**: Lightweight expression evaluator
/// - **Features**:
///   - Simple DSL or JSON format
///   - Can be used as a rules engine
///   - Parses into expression AST objects
/// - **Installation**: `reval` crate
///
/// ### 6. expressions
/// - **Type**: Flexible expression parser and evaluator
/// - **Features**:
///   - Custom types through traits
///   - Lazy evaluation for boolean operators
/// - **Installation**: `expressions` crate
///
/// ## Rust AST Parsing
///
/// Rust has built-in AST parsing via the compiler:
/// - **`rustc_parse`** - Official Rust compiler parser (internal)
/// - **`ra_ap_rustc_parse`** - Republished version for rust-analyzer (available on crates.io)
/// - **rust-analyzer parser** - Hand-written parser used by rust-analyzer
///
/// However, since we're parsing expression languages (CEL, fasteval, etc.), not raw Rust code,
/// we would need parsers for those specific languages, not Rust's parser.
///
/// ## Runtime Code Execution in Rust
///
/// Rust does NOT natively support executing arbitrary code at runtime.
/// There is no built-in `eval()` function.
///
/// For Python, JS and PHP, the compiler returns code to execute.
///
/// For Rust, the compiler would have to return a Rust function or the template AST
/// as objects (not code), OR use expression language evaluators like CEL-Rust or fasteval.
///
/// ## Implementation Notes
///
/// For Rust expressions (in CEL/fasteval/evalexpr syntax), we need to:
/// - Parse expressions using the chosen expression language parser
/// - Extract used variables (e.g., `x`, `y` in `x + y`)
/// - Handle expression-specific syntax:
///   - Arithmetic operations: `+`, `-`, `*`, `/`
///   - Comparisons: `>`, `<`, `==`, `!=`
///   - Logical operators: `&&`, `||`, `!`
///   - Function calls: `sin(x)`, `max(a, b)`
///   - Conditional expressions: `if x > 5 then "high" else "low"` (if supported)
///
/// For Rust for-loop expressions (in `<c-for each="...">`), we need to:
/// - Parse iteration syntax from the chosen expression language
/// - Extract loop variables
/// - Handle destructuring (if supported by the expression language)
///
/// Note: The exact syntax depends on which expression language is chosen:
/// - CEL-Rust has macros for bounded iteration
/// - fasteval is focused on mathematical expressions (may not support loops)
/// - evalexpr may have iteration support
/// - Rhai supports full loops (if not restricted)
///
/// ## Rust Expression Model
///
/// Expression languages like CEL-Rust, fasteval, and evalexpr have similar concepts to Python:
///
/// **Similarities:**
/// - **Expressions evaluate to a value**: Both treat expressions as constructs that
///   produce a value
/// - **Nesting**: Expressions can contain other expressions
/// - **AST structure**: Expression languages have expression node types similar to Python:
///   - Binary operations
///   - Unary operations
///   - Function calls
///   - Variable references
///   - Literals
///
/// **Differences:**
/// - **Non-Turing complete**: Languages like CEL-Rust are intentionally non-Turing complete
///   for safety (no loops, recursion, etc.)
/// - **Limited complexity**: Expression languages are designed to be simpler and safer
///   than full programming languages
/// - **Type safety**: Many Rust expression evaluators support static typing
///
/// **For Our Use Case:**
/// For parsing template expressions like `{{ x + y }}` or `{{ user.name == "admin" }}`,
/// expression languages work similarly to Python:
/// - We can parse expressions into an AST
/// - We can traverse the AST to extract variables
/// - Expressions can nest (function calls, comparisons, etc.)
///
/// ## Using the Compiler with Rust Macros
///
/// The template compiler can be used with Rust procedural macros to generate Rust code
/// at compile time. This is different from runtime expression evaluation.
///
/// **How Rust Macros Work:**
/// - **Procedural macros** are Rust functions that run at compile time
/// - They transform `TokenStream` → `TokenStream`
/// - They can call any Rust function, use any crate, and generate arbitrary code
/// - They are regular Rust functions, just executed during compilation
///
/// **Using the Compiler with Macros:**
///
/// You can pass a function/callback to generate Rust code. There are two main approaches:
///
/// ### Approach 1: Pass a callback function
///
/// Refactor `compile_template` to accept a callback that "prints" code:
///
/// ```ignore
/// pub fn compile_template<F>(template: Template, mut code_writer: F) -> Result<(), CompileError>
/// where
///     F: FnMut(&str),  // Function that "prints" code
/// {
///     code_writer("fn generate_template() -> Vec<Node> {\n");
///     code_writer("    let mut body = vec![\n");
///     // ... generate code by calling code_writer
///     code_writer("    ];\n");
///     code_writer("    body\n");
///     code_writer("}\n");
///     Ok(())
/// }
/// ```
///
/// Then in a procedural macro:
///
/// ```ignore
/// use proc_macro::TokenStream;
///
/// #[proc_macro]
/// pub fn template(input: TokenStream) -> TokenStream {
///     let template = parse_template(input);
///     let mut rust_code = String::new();
///     compile_template(template, |code| {
///         rust_code.push_str(code);
///     }).unwrap();
///     rust_code.parse().unwrap()
/// }
/// ```
///
/// ### Approach 2: Use `quote!` macro (Recommended)
///
/// The `quote` crate is designed for this. Refactor to return a `proc_macro2::TokenStream`:
///
/// ```ignore
/// use quote::quote;
///
/// pub fn compile_template_rust(template: Template) -> Result<proc_macro2::TokenStream, CompileError> {
///     let body_items = compile_template_body(template)?;
///     
///     // Generate Rust code using quote!
///     Ok(quote! {
///         fn generate_template() -> Vec<Node> {
///             let body = vec![
///                 #(#body_items),*
///             ];
///             body
///         }
///     })
/// }
/// ```
///
/// Then in your macro:
///
/// ```ignore
/// #[proc_macro]
/// pub fn template(input: TokenStream) -> TokenStream {
///     let template = parse_template(input);
///     let tokens = compile_template_rust(template).unwrap();
///     TokenStream::from(tokens)
/// }
/// ```
///
/// **Benefits of the `quote!` approach:**
/// - Type-safe code generation
/// - Handles Rust syntax correctly (no manual escaping)
/// - Integrates seamlessly with procedural macros
/// - Better than string concatenation
///
/// **Can Macros Use Other Functions?**
///
/// Yes! Procedural macros are regular Rust functions that:
/// - Run at compile time
/// - Can call any Rust function
/// - Can use any crate
/// - Transform `TokenStream` → `TokenStream`
///
/// **Can You Pass Code Generation Functions?**
///
/// Yes! You can:
/// 1. Pass a closure/callback that writes code (like `final_code.push_str` for Python)
/// 2. Return a `TokenStream` from `quote!`
/// 3. Use a builder pattern with methods that accumulate code
///
/// **For Template Compilation:**
///
/// The compiler could be made generic to support both:
/// - **Python**: Generate string code (current implementation with `final_code.push_str`)
/// - **Rust**: Generate `TokenStream` using `quote!` macro
///
/// This would allow the same compiler logic to work for both languages, just with different
/// code generation backends.
#[derive(Copy, Clone)]
pub struct RustLang;

/// Static instance of RustLang for use as a default
pub static RUST_LANG: RustLang = RustLang;

impl LangImpl for RustLang {
    fn parse_expression(&self, _source: &str) -> Result<ParseExprResult, String> {
        // TODO: Implement Rust expression parsing (CEL-Rust, fasteval, or evalexpr syntax)
        //
        // Steps:
        // 1. Determine which expression language is being used (CEL-Rust, fasteval, evalexpr, etc.)
        // 2. Use the appropriate parser for that language
        // 3. Re-implement python_safe_eval's transform_expression_string but for the chosen
        //    expression language
        // 4. Convert the result to citry_template_parser Token and Comment types
        // 5. Return ParseExprResult
        //
        // Note: The expressions are NOT raw Rust code, but rather expression language syntax.
        // Example CEL-Rust expressions:
        // - `user.name == "admin"`
        // - `request.time - resource.age < duration("24h")`
        //
        // Example fasteval expressions:
        // - `2 + 3 * 4`
        // - `sin(x) + cos(y)`
        //
        // Example evalexpr expressions:
        // - `x + y * z`
        // - `if x > 5 then "high" else "low"`
        Err("Rust expression parsing is not yet implemented. Expressions use CEL-Rust, fasteval, or evalexpr syntax, not raw Rust code.".to_string())
    }

    fn parse_forloop_expression(&self, _source: &str) -> Result<Vec<Token>, String> {
        // TODO: Implement Rust for-loop variable extraction
        //
        // Steps:
        // 1. Determine which expression language is being used
        // 2. Use the appropriate parser for that language
        // 3. Extract loop variables from the iteration expression
        //    - For CEL-Rust: may use macros for bounded iteration
        //    - For fasteval: likely not applicable (mathematical expressions)
        //    - For evalexpr: depends on iteration support
        //    - For Rhai: full loop support if not restricted
        // 4. Calculate line/column positions for each variable
        // 5. Return Vec<Token> with positions relative to the source string
        //
        // Note: The exact syntax depends on the expression language:
        // - CEL-Rust has macros for bounded iteration
        // - fasteval is focused on math (may not support loops)
        // - evalexpr may have iteration support
        // - Rhai supports full loops (if not restricted)
        //
        // The `each` attribute in `<c-for each="...">` should contain the iteration
        // expression in the chosen language's syntax.
        Err("Rust for-loop variable extraction is not yet implemented. Expressions use CEL-Rust, fasteval, or evalexpr syntax, not raw Rust code.".to_string())
    }

    fn compile(&self, _args: Vec<LangSpecArgument>) -> Result<String, String> {
        Err("Rust code generation is not yet implemented".to_string())
    }
}
