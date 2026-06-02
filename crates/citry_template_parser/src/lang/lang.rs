use std::rc::Rc;

use crate::ast::{Comment, Token};
use crate::lang::go::GO_LANG;
use crate::lang::js::JS_LANG;
use crate::lang::php::PHP_LANG;
use crate::lang::python::PYTHON_LANG;
use crate::lang::rust::RUST_LANG;

/// Supported template expression languages
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lang {
    /// Python expressions (default)
    Python,
    /// PHP expressions
    Php,
    /// JavaScript/TypeScript expressions
    Js,
    /// Go expressions (using Expr or CEL-Go syntax, not raw Go code)
    Go,
    /// Rust expressions (using CEL-Rust, fasteval, or evalexpr syntax, not raw Rust code)
    Rust,
}

impl Lang {
    /// Convert the enum variant to an Rc<dyn LangImpl>
    pub fn to_lang_impl(&self) -> Rc<dyn LangImpl> {
        match self {
            Lang::Python => Rc::new(PYTHON_LANG),
            Lang::Php => Rc::new(PHP_LANG),
            Lang::Js => Rc::new(JS_LANG),
            Lang::Go => Rc::new(GO_LANG),
            Lang::Rust => Rc::new(RUST_LANG),
        }
    }
}

/// Result of parsing an expression string
///
/// This is language-agnostic and uses citry_template_parser's Token type
/// (not the language-specific token types from python_safe_eval or other parsers).
#[derive(Debug, Clone)]
pub struct ParseExprResult {
    /// Tokens for variables that are used from the outside context
    pub used_vars: Vec<Token>,
    /// Tokens for variables that are assigned via walrus operator (:=)
    /// (Python-specific, but included for consistency)
    pub assigned_vars: Vec<Token>,
    /// Comments found in the original source
    pub comments: Vec<Comment>,
}

/// Trait for language-specific expression parsing implementations
pub trait LangImpl {
    /// Parse an expression string and return the AST along with variable usage information
    ///
    /// # Arguments
    /// * `source` - The expression string to parse (e.g., `"x + y"`)
    ///
    /// # Returns
    /// * `Ok(ParseExprResult)` - The parsed expression with variable tracking
    /// * `Err(String)` - A string error message (will be converted to ParseError by caller)
    fn parse_expression(&self, source: &str) -> Result<ParseExprResult, String>;

    /// Parse a for-loop expression (e.g., `each` attribute in `<c-for each="...">`)
    ///
    /// This extracts loop variables from the expression.
    /// For Python, this handles comprehensions like `x, y, z in my_list`.
    /// For PHP, this would handle `foreach` syntax like `foreach ($items as $x)`.
    ///
    /// # Arguments
    /// * `source` - The for-loop expression string (e.g., `"x, y, z in my_list"`)
    ///
    /// # Returns
    /// * `Ok(Vec<Token>)` - List of loop variable tokens with positions relative to the source string
    /// * `Err(String)` - A string error message (will be converted to ParseError by caller)
    ///
    /// # Note
    /// The returned tokens have positions relative to the `source` string.
    /// The caller is responsible for adjusting positions to match the template context.
    fn parse_forloop_expression(&self, source: &str) -> Result<Vec<Token>, String>;

    /// Compile a template AST into language-specific source code.
    ///
    /// This converts the abstract language specification into concrete source code
    /// for the target language (e.g., Python, PHP, JavaScript, etc.).
    ///
    /// For example, for Python, this function generates code for a function
    /// that returns a list of node objects (TextNode, ExprNode, etc.)
    /// that represent the template structure:
    ///
    /// ```python
    /// def generate_template():
    ///     body = [
    ///         """Hello, \"John\"!""",
    ///         ExprNode(source, (14, 19), """a + b""", ("a", "b")),
    ///         ComponentNode(source, (14, 19), (HtmlAttr(...), ...),
    ///         """<a href=\"""",
    ///         ExprNode(source, (14, 19), """base + 'foo'""", ("base",)),
    ///         """\">Click me!</a>""",
    ///         ...
    ///     ]
    ///     return body
    /// ```
    ///
    /// # Arguments
    /// * `args` - A vector of `LangSpecArgument` representing the compiled template structure
    ///
    /// # Returns
    /// * `Ok(String)` - The generated source code as a string
    /// * `Err(String)` - A string error message (will be converted to CompileError by caller)
    fn compile(&self, args: Vec<LangSpecArgument>) -> Result<String, String>;
}

// #########################################################
// LANGUAGE-AGNOSTIC CODE GENERATION STRUCTURES
// #########################################################

/// Abstract representation of code to be generated.
///
/// This is language-agnostic and can be converted to concrete language code
/// by each `LangImpl` implementation.
///
/// Arguments can be variables, strings, numbers, booleans, tuples, lists, or function calls/structs.
#[derive(Debug, Clone, PartialEq)]
pub enum LangSpecArgument {
    /// A variable reference (e.g., `source`).
    ///
    /// When converted to code, this will be printed without quotes.
    Variable(String),
    /// A string that needs escaping when converted to code.
    ///
    /// This string may contain special characters or newlines and needs escaping.
    ///
    /// For example, in Python this might become `"""value"""` depending on content.
    UnsafeString(String),
    /// A string that doesn't need escaping when converted to code.
    ///
    /// For example, in Python this might become `"a"` (simple string literal).
    SafeString(String),
    /// The integer value
    Int(usize),
    /// A boolean value (e.g., `true`, `false` in most languages, or `True`, `False` in Python)
    Bool(bool),
    /// A tuple containing other arguments.
    ///
    /// For example, `(14, 19)` or `("a", "b")`.
    ///
    /// If the specific language doens't support tuples, this will be converted to a list.
    Tuple(Vec<LangSpecArgument>),
    /// A list containing other arguments.
    ///
    /// For example, `["a", "b"]` or `[1, 2, 3]`.
    List(Vec<LangSpecArgument>),
    /// Generate a struct / class instance. You can also think of this as a function call.
    ///
    /// E.g. in Python, this may look like this:
    /// ```py
    /// ExprHtmlAttr(
    ///     source,                   # original template source string as variable
    ///     (start, end),             # positional metadata
    ///     """key""",                # Attribute key (escaped because unsafe string)
    ///     """value""",              # Attribute value (expression) (escaped because unsafe string)
    ///     ("a", "b"),               # variables used in the expression (variables) (safe strings deined by us)
    /// )
    /// ```
    Struct(LangSpecStruct),
}

/// A struct / class instance with a name and arguments.
///
/// E.g. in Python, this may look like this:
/// ```py
/// NodeClass(
///     source,                   # original template source string
///     (start, end),             # positional metadata
///     (ExprHtmlAttr(...), ...), # attributes (HtmlAttr calls)
///     [body_item1, ...],        # body node list
///     ("var1", "var2", ...),    # used variables tuple
///     ("introduced_var1", "introduced_var2", ...), # introduced variables tuple
/// )
/// ```
#[derive(Debug, Clone, PartialEq)]
pub struct LangSpecStruct {
    /// The struct / class name (e.g., `NodeClass`)
    pub name: String,
    /// The arguments to the struct / class instance
    pub arguments: Vec<LangSpecArgument>,
}
