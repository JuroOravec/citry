use citry_template_parser::ast::{
    Comment, Expr, HtmlAttr, HtmlAttrKind, HtmlEndTag, HtmlStartTag, Node, StaticNamedSlot,
    Template, TemplateElement, Text, Token,
};
use citry_template_parser::parser::parse_template;
use citry_template_parser::ParseError;

// =============================================================================
// TOKEN
// =============================================================================

/// Helper function to create a Token struct.
/// Takes content, start_index, line number, and column number.
/// Calculates end_index automatically as start_index + content.len().
pub fn token(content: &str, start_index: usize, line: usize, col: usize) -> Token {
    Token {
        content: content.to_string(),
        start_index,
        end_index: start_index + content.len(),
        line_col: (line, col),
    }
}

// =============================================================================
// HTML ATTRIBUTE HELPERS
// =============================================================================

/// Build a generic HtmlAttr from key, optional inner_value, quote_char, and kind.
/// Auto-computes `token` (full attr span) and `value` (inner_value with quotes).
fn build_attr(
    key: Token,
    inner_value: Option<Token>,
    quote_char: Option<char>,
    kind: HtmlAttrKind,
) -> HtmlAttr {
    let (attr_token, value) = match (&inner_value, quote_char) {
        // Quoted value: key="val" or key='val'
        (Some(iv), Some(q)) => {
            let value_content = format!("{}{}{}", q, iv.content, q);
            let value_start = iv.start_index.saturating_sub(1);
            let value_end = iv.end_index + 1;
            let value_lc = (iv.line_col.0, iv.line_col.1.saturating_sub(1));
            let value_token = Token {
                content: value_content,
                start_index: value_start,
                end_index: value_end,
                line_col: value_lc,
            };

            let attr_content = format!("{}={}{}{}", key.content, q, iv.content, q);
            let attr_end = value_end;
            let attr_token = Token {
                content: attr_content,
                start_index: key.start_index,
                end_index: attr_end,
                line_col: key.line_col,
            };
            (attr_token, Some(value_token))
        }
        // Unquoted value: key=val
        (Some(iv), None) => {
            let attr_content = format!("{}={}", key.content, iv.content);
            let attr_token = Token {
                content: attr_content,
                start_index: key.start_index,
                end_index: iv.end_index,
                line_col: key.line_col,
            };
            let value_token = iv.clone();
            (attr_token, Some(value_token))
        }
        // Boolean attr: no value
        (None, _) => {
            let attr_token = key.clone();
            (attr_token, None)
        }
    };

    HtmlAttr {
        token: attr_token,
        key,
        value,
        inner_value,
        quote_char,
        kind,
        comments: vec![],
        used_variables: vec![],
    }
}

/// Build a static key="value" attribute (double-quoted).
pub fn static_attr(key: Token, inner_value: Token) -> HtmlAttr {
    build_attr(key, Some(inner_value), Some('"'), HtmlAttrKind::Static)
}

/// Build a static key='value' attribute (single-quoted).
pub fn static_attr_sq(key: Token, inner_value: Token) -> HtmlAttr {
    build_attr(key, Some(inner_value), Some('\''), HtmlAttrKind::Static)
}

/// Build an unquoted static attribute: key=val.
pub fn unquoted_attr(key: Token, inner_value: Token) -> HtmlAttr {
    build_attr(key, Some(inner_value), None, HtmlAttrKind::Static)
}

/// Build a boolean attribute (no value).
pub fn bool_attr(key: Token) -> HtmlAttr {
    build_attr(key, None, None, HtmlAttrKind::Static)
}

/// Build a double-quoted Expression attribute (c-* prefix).
pub fn expr_attr(key: Token, inner_value: Token) -> HtmlAttr {
    build_attr(key, Some(inner_value), Some('"'), HtmlAttrKind::Expression)
}

/// Build an unquoted Expression attribute.
pub fn expr_attr_unquoted(key: Token, inner_value: Token) -> HtmlAttr {
    build_attr(key, Some(inner_value), None, HtmlAttrKind::Expression)
}

/// Build a double-quoted Template attribute (c-* prefix, nested template).
pub fn template_attr(key: Token, inner_value: Token) -> HtmlAttr {
    build_attr(key, Some(inner_value), Some('"'), HtmlAttrKind::Template)
}

/// Modifier: set used_variables on an HtmlAttr.
pub fn with_used_vars(mut attr: HtmlAttr, vars: Vec<Token>) -> HtmlAttr {
    attr.used_variables = vars;
    attr
}

/// Modifier: set comments on an HtmlAttr.
pub fn with_attr_comments(mut attr: HtmlAttr, comments: Vec<Comment>) -> HtmlAttr {
    attr.comments = comments;
    attr
}

// =============================================================================
// TAG HELPERS
// =============================================================================

/// Build an HtmlStartTag with comments defaulting to empty.
pub fn start_tag(
    token: Token,
    name: Token,
    attrs: Vec<HtmlAttr>,
    is_self_closing: bool,
) -> HtmlStartTag {
    HtmlStartTag {
        token,
        name,
        attrs,
        is_self_closing,
        comments: vec![],
    }
}

/// Build an HtmlStartTag with explicit comments.
pub fn start_tag_with_comments(
    token: Token,
    name: Token,
    attrs: Vec<HtmlAttr>,
    is_self_closing: bool,
    comments: Vec<Comment>,
) -> HtmlStartTag {
    HtmlStartTag {
        token,
        name,
        attrs,
        is_self_closing,
        comments,
    }
}

/// Build an HtmlEndTag with comments defaulting to empty.
pub fn end_tag(token: Token, name: Token) -> HtmlEndTag {
    HtmlEndTag {
        token,
        name,
        comments: vec![],
    }
}

/// Build an HtmlEndTag with explicit comments.
pub fn end_tag_with_comments(token: Token, name: Token, comments: Vec<Comment>) -> HtmlEndTag {
    HtmlEndTag {
        token,
        name,
        comments,
    }
}

// =============================================================================
// NODE HELPERS
// =============================================================================

/// Build a Node::SelfClosing with default empty fields.
pub fn self_closing_node(start_tag: HtmlStartTag) -> Node {
    Node::SelfClosing {
        start_tag,
        used_variables: vec![],
        introduced_variables: vec![],
        comments: vec![],
        contains_fills: false,
    }
}

/// Build a Node::SelfClosing with used_variables.
pub fn self_closing_node_vars(start_tag: HtmlStartTag, used_variables: Vec<Token>) -> Node {
    Node::SelfClosing {
        start_tag,
        used_variables,
        introduced_variables: vec![],
        comments: vec![],
        contains_fills: false,
    }
}

/// Build a Node::WithBody with default empty fields.
pub fn body_node(start_tag: HtmlStartTag, end_tag: HtmlEndTag, body: Template) -> Node {
    Node::WithBody {
        start_tag,
        end_tag,
        body,
        used_variables: vec![],
        introduced_variables: vec![],
        comments: vec![],
        contains_fills: false,
    }
}

/// Build a Node::WithBody with all fields explicit.
#[allow(clippy::too_many_arguments)]
pub fn body_node_full(
    start_tag: HtmlStartTag,
    end_tag: HtmlEndTag,
    body: Template,
    used_variables: Vec<Token>,
    introduced_variables: Vec<Token>,
    comments: Vec<Comment>,
    contains_fills: bool,
) -> Node {
    Node::WithBody {
        start_tag,
        end_tag,
        body,
        used_variables,
        introduced_variables,
        comments,
        contains_fills,
    }
}

/// Build a Node::SelfClosing with all fields explicit.
pub fn self_closing_node_full(
    start_tag: HtmlStartTag,
    used_variables: Vec<Token>,
    introduced_variables: Vec<Token>,
    comments: Vec<Comment>,
    contains_fills: bool,
) -> Node {
    Node::SelfClosing {
        start_tag,
        used_variables,
        introduced_variables,
        comments,
        contains_fills,
    }
}

// =============================================================================
// TEMPLATE HELPERS
// =============================================================================

/// Build a Template with default empty fields.
pub fn template(elements: Vec<TemplateElement>) -> Template {
    Template {
        elements,
        comments: vec![],
        used_variables: vec![],
        slots: vec![],
    }
}

/// Build a Template with used_variables.
pub fn template_with_vars(
    elements: Vec<TemplateElement>,
    used_variables: Vec<Token>,
) -> Template {
    Template {
        elements,
        comments: vec![],
        used_variables,
        slots: vec![],
    }
}

/// Build a Template with comments.
pub fn template_with_comments(
    elements: Vec<TemplateElement>,
    comments: Vec<Comment>,
) -> Template {
    Template {
        elements,
        comments,
        used_variables: vec![],
        slots: vec![],
    }
}

/// Build a Template with comments and used_variables.
pub fn template_with_comments_and_vars(
    elements: Vec<TemplateElement>,
    comments: Vec<Comment>,
    used_variables: Vec<Token>,
) -> Template {
    Template {
        elements,
        comments,
        used_variables,
        slots: vec![],
    }
}

/// Build a Template with all fields explicit.
pub fn template_full(
    elements: Vec<TemplateElement>,
    comments: Vec<Comment>,
    used_variables: Vec<Token>,
    slots: Vec<StaticNamedSlot>,
) -> Template {
    Template {
        elements,
        comments,
        used_variables,
        slots,
    }
}

// =============================================================================
// TEMPLATE ELEMENT HELPERS
// =============================================================================

/// Build a TemplateElement::Text from content and position.
pub fn text_elem(content: &str, start_index: usize, line: usize, col: usize) -> TemplateElement {
    TemplateElement::Text(Text {
        token: token(content, start_index, line, col),
    })
}

/// Build a TemplateElement::Node wrapping a Node.
pub fn node_elem(node: Node) -> TemplateElement {
    TemplateElement::Node(node)
}

/// Build a TemplateElement::Expr with default empty comments.
pub fn expr_elem(tok: Token, value: Token, used_variables: Vec<Token>) -> TemplateElement {
    TemplateElement::Expr(Expr {
        token: tok,
        value,
        used_variables,
        comments: vec![],
    })
}

/// Build a TemplateElement::Expr with explicit comments.
pub fn expr_elem_with_comments(
    tok: Token,
    value: Token,
    used_variables: Vec<Token>,
    comments: Vec<Comment>,
) -> TemplateElement {
    TemplateElement::Expr(Expr {
        token: tok,
        value,
        used_variables,
        comments,
    })
}

// =============================================================================
// COMMENT HELPER
// =============================================================================

/// Build a Comment from token and value.
pub fn comment(tok: Token, value: Token) -> Comment {
    Comment {
        token: tok,
        value,
    }
}

// =============================================================================
// SLOT HELPER
// =============================================================================

/// Build a StaticNamedSlot.
pub fn slot(tok: Token, required: Option<bool>) -> StaticNamedSlot {
    StaticNamedSlot {
        token: tok,
        required,
    }
}

// =============================================================================
// PARSE HELPERS
// =============================================================================

/// Helper function to parse a template and return the first node.
pub fn parse_first_node(input: &str) -> Result<Node, ParseError> {
    let template = parse_template(input, None, None)?;

    for element in template.elements {
        if let TemplateElement::Node(node) = element {
            return Ok(node);
        }
    }

    Err(ParseError::Value("No node found in template".to_string()))
}

/// Helper function to check if parsing fails.
pub fn parse_should_fail(input: &str) -> bool {
    parse_template(input, None, None).is_err()
}

/// Assert that parsing fails and the error message contains the expected substring.
pub fn assert_parse_error(input: &str, expected_msg_substring: &str) {
    let result = parse_template(input, None, None);
    match result {
        Ok(_) => panic!(
            "Expected parsing to fail for input: {}\n  Expected error containing: {}",
            input, expected_msg_substring
        ),
        Err(e) => {
            let error_msg = format!("{}", e);
            assert!(
                error_msg.contains(expected_msg_substring),
                "Error message mismatch for input: {}\n  Expected substring: {}\n  Actual error: {}",
                input,
                expected_msg_substring,
                error_msg
            );
        }
    }
}
