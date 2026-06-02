pub mod ast;
pub mod compiler;
pub mod constants;
pub mod error;
pub mod grammar;
pub mod lang {
    pub mod go;
    pub mod js;
    pub mod lang;
    pub mod php;
    pub mod python;
    pub mod rust;
}
pub mod parser;
pub mod parser_context;
pub mod utils {
    pub mod pest;
}

// Re-export the types that users need
pub use crate::ast::{
    Comment, Expr, HtmlAttr, HtmlAttrKind, HtmlEndTag, HtmlStartTag, Node, StaticNamedSlot,
    Template, TemplateElement, Text, Token,
};
pub use crate::error::ParseError;
pub use crate::lang::lang::{Lang, LangImpl, ParseExprResult};
pub use crate::parser::{parse_template, parse_template_with_custom_lang};
pub use crate::parser_context::{ParserContext, TagRules};
