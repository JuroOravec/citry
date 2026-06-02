use thiserror::Error;

use crate::grammar::Rule;

#[derive(Debug, Error, PartialEq)]
pub enum CompileError {
    #[error("Compile error: {0}")]
    Generic(String),
    #[error("Compile error: {0}")]
    Syntax(String),
}

impl From<String> for CompileError {
    fn from(error: String) -> Self {
        CompileError::Generic(error)
    }
}

impl From<&str> for CompileError {
    fn from(error: &str) -> Self {
        CompileError::Generic(error.to_string())
    }
}

#[derive(Error, Debug)]
pub enum ParseError {
    #[error("Parse error: {0}")]
    Syntax(#[from] pest::error::Error<Rule>),
    #[error("Parse error: {0}")]
    Value(String),
}

impl ParseError {
    /// Helper function to create a ParseError with position information from a span
    pub fn from_span(span: pest::Span, message: String) -> ParseError {
        ParseError::Syntax(pest::error::Error::new_from_span(
            pest::error::ErrorVariant::CustomError { message },
            span,
        ))
    }
}

pub fn assert_rule(pair: &pest::iterators::Pair<Rule>, rule: Rule) -> Result<(), ParseError> {
    if pair.as_rule() != rule {
        return Err(ParseError::from_span(
            pair.as_span(),
            format!("Expected {:?}, got {:?}", rule, pair.as_rule()),
        ));
    }
    Ok(())
}

pub fn assert_rules(pair: &pest::iterators::Pair<Rule>, rules: &[Rule]) -> Result<(), ParseError> {
    if !rules.contains(&pair.as_rule()) {
        return Err(ParseError::from_span(
            pair.as_span(),
            format!("Expected one of {:?}, got {:?}", rules, pair.as_rule()),
        ));
    }
    Ok(())
}
