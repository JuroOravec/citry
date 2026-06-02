use std::collections::{HashMap, HashSet};
use std::rc::Rc;

use pest::Parser;

use crate::ast::{
    Comment, Expr, HtmlAttr, HtmlAttrKind, HtmlEndTag, HtmlStartTag, Node, StaticNamedSlot,
    Template, TemplateElement, Text, Token,
};
use crate::constants::{
    CONTROL_FLOW_GROUPS, CONTROL_FLOW_TAGS, C_COMPONENT_TAG, C_FILL_TAG, C_FOR_TAG, C_SLOT_TAG,
    FORBIDDEN_HTML_TAG_NAMES, HTML_VOID_ELEMENTS, RESERVED_TAG_NAMES, TAG_ATTR_RULES,
    TAG_ORDERING_RULES,
};
use crate::error::{assert_rule, assert_rules, ParseError};
use crate::grammar::{GrammarParser, Rule};
use crate::lang::lang::{Lang, LangImpl};
use crate::parser_context::{ParserContext, TagRules};
use crate::utils::pest::{span_from_str, unwrap_pair};

/// Result of processing an HTML tag
enum HtmlTagResult {
    /// Start tag - Will start new layer in stack
    StartTag(HtmlStartTag),
    /// End tag - Will close current layer in stack
    EndTag(HtmlEndTag),
    /// Self-closing tag - Will be added to current layer in stack
    /// without changing the stack.
    SelfClosing(Node),
}

/// Stack entry for tracking open HTML tags with bodies
///
/// This has the same fields as `Node::WithBody`, except for the `end_tag`
struct TagStackEntry {
    /// The start tag with attributes
    start_tag: HtmlStartTag,
    /// The body content (template elements inside the tag)
    body: Template,
}

/// Parse a complete template into a Template AST
///
/// **Arguments**
/// * `input` - The template string to parse
/// * `lang` - Optional language implementation - Specifies which language to use
///            for parsing expressions (e.g. Python, PHP, JS, ...).
///            Default is Python.
/// * `user_rules` - Optional user-defined validation rules
///
/// This is the V3 parser that supports HTML-compatible templates with:
/// - HTML tags and components (`<c-*>`)
/// - Template expressions `{{ ... }}`
/// - Template comments `{# ... #}`
/// - HTML comments `<!-- ... -->`
/// - `c-*` attributes for dynamic behavior
pub fn parse_template(
    input: &str,
    lang: Option<Lang>,
    user_rules: Option<&Rc<HashMap<String, TagRules>>>,
) -> Result<Template, ParseError> {
    // Resolve the language enum to an Rc<dyn LangImpl>
    let lang_impl = lang.unwrap_or(Lang::Python).to_lang_impl();
    parse_template_with_custom_lang(input, Some(&lang_impl), user_rules)
}

/// Parse a complete template into a Template AST with a custom language implementation.
///
/// This is same as `parse_template()`, but allows you to specify a custom language implementation,
/// instead of using pre-defined enum values.
///
/// **Arguments**
/// * `input` - The template string to parse
/// * `lang` - Optional language implementation - Specifies which language to use
///            for parsing expressions (e.g. Python, PHP, JS, ...)
///            Default is Python.
/// * `user_rules` - Optional user-defined validation rules
///
/// This is the V3 parser that supports HTML-compatible templates with:
/// - HTML tags and components (`<c-*>`)
/// - Template expressions `{{ ... }}`
/// - Template comments `{# ... #}`
/// - HTML comments `<!-- ... -->`
/// - `c-*` attributes for dynamic behavior
pub fn parse_template_with_custom_lang(
    input: &str,
    lang: Option<&Rc<dyn LangImpl>>,
    user_rules: Option<&Rc<HashMap<String, TagRules>>>,
) -> Result<Template, ParseError> {
    // NOTE: This function accepts references of Rc's to avoid consuming the Rc instances.
    // But if we receive None, we have to create a new Rc instance.
    // Thus we also clone the Rc internally, so that in both Some/None cases we end up
    // owning the Rc instances.
    let lang = lang
        .map(|l| Rc::clone(l))
        .unwrap_or_else(|| Lang::Python.to_lang_impl());
    let rules = user_rules
        .map(|r| Rc::clone(r))
        .unwrap_or_else(|| Rc::new(HashMap::new()));

    let context = ParserContext::new(&lang, &rules);
    parse_template_inner(input, &context)
}

/// Internal method to parse a template with a context that may have offsets
/// This is also used when parsing a nested template string,
/// e.g. `c-body="<>Hello {{ name }}<>"` or `c-body="<div>Hello {{ name }}</div>"`.
fn parse_template_inner(input: &str, context: &ParserContext) -> Result<Template, ParseError> {
    // Handle empty input early
    if input.is_empty() {
        return Ok(Template {
            elements: vec![],
            comments: vec![],
            used_variables: vec![],
            slots: vec![],
        });
    }

    let mut pairs = GrammarParser::parse(Rule::template, input).map_err(|e| {
        ParseError::from_span(
            span_from_str(input),
            format!("Failed to parse template: {}", e),
        )
    })?;

    // Stack for tracking open HTML tags with bodies
    let mut tag_stack: Vec<TagStackEntry> = Vec::new();

    // There should be only one top-level template
    let template_pair = pairs.next().ok_or_else(|| {
        ParseError::from_span(span_from_str(input), "Template is empty".to_string())
    })?;
    assert_rule(&template_pair, Rule::template)?;

    // template -> template_element*
    let template_elements_with_comments = template_pair.into_inner();

    // Filter out template_elements whose child is a template_comment
    let (template_element_pairs, template_comments) =
        context.extract_comments_from_pairs(template_elements_with_comments)?;

    // Root template being built
    let mut root_template = Template {
        elements: vec![],
        comments: template_comments,
        used_variables: vec![],
        slots: vec![],
    };

    for template_element_pair in template_element_pairs {
        // Skip EOI (End Of Input) marker
        if template_element_pair.as_rule() == Rule::EOI {
            continue;
        }
        assert_rule(&template_element_pair, Rule::template_element)?;

        // Process the element
        process_template_element(
            template_element_pair,
            &mut tag_stack,
            &mut root_template,
            context,
        )?;
    }

    // Check for unclosed tags on the stack
    if !tag_stack.is_empty() {
        let last_unclosed_entry = tag_stack.last().unwrap();
        let last_unclosed_tag_name = &last_unclosed_entry.start_tag.name.content;
        let last_unclosed_start_tag_span = last_unclosed_entry
            .start_tag
            .token
            .as_span_with_input(input)
            .unwrap();
        return Err(ParseError::from_span(
            last_unclosed_start_tag_span,
            format!(
                "Unclosed tag <{}>: expected </{}> before end of template",
                last_unclosed_tag_name, last_unclosed_tag_name
            ),
        ));
    }

    Ok(root_template)
}

fn process_template_element(
    element_pair: pest::iterators::Pair<Rule>,
    tag_stack: &mut Vec<TagStackEntry>,
    root_template: &mut Template,
    context: &ParserContext,
) -> Result<(), ParseError> {
    // template_element -> html_comment | html_directive | html_processing_instruction | html_tag
    //                     | template_expression | template_comment | text
    let element_span = element_pair.as_span();
    let inner = element_pair.into_inner().next().ok_or_else(|| {
        ParseError::from_span(
            element_span,
            "template_element should always have an inner rule".to_string(),
        )
    })?;
    let inner_rule = inner.as_rule();

    match inner_rule {
        // HTML comments: treat as Text but also add as comment
        Rule::html_comment => {
            let template = get_current_template(tag_stack, root_template);
            let (text, comment) = process_html_comment(inner, context)?;
            template.elements.push(TemplateElement::Text(text));
            template.comments.push(comment);
        }
        // Template comments: NOT added as Text, only captured as comments
        Rule::template_comment => {
            let template = get_current_template(tag_stack, root_template);
            let comment = process_template_comment(inner, context)?;
            template.comments.push(comment);
        }
        // All of these are treated as plain text
        Rule::html_directive | Rule::html_processing_instruction | Rule::text => {
            let template = get_current_template(tag_stack, root_template);
            let text = process_text(inner, context)?;
            template.elements.push(TemplateElement::Text(text));
        }
        Rule::html_raw => {
            let template = get_current_template(tag_stack, root_template);
            let node = process_html_raw(inner, context)?;
            template.elements.push(TemplateElement::Node(node));
        }
        Rule::template_expression => {
            let template = get_current_template(tag_stack, root_template);
            let expr = process_template_expression(inner, context)?;
            // Propagate upwards
            template.used_variables.extend(expr.used_variables.clone());
            template.comments.extend(expr.comments.clone());
            template.elements.push(TemplateElement::Expr(expr));
        }
        Rule::html_tag => {
            // Handle HTML tags (start/end/self-closing)
            let tag_span = inner.as_span();
            let tag_result = process_html_tag(inner, context)?;
            match tag_result {
                // Push as body element of the current layer
                HtmlTagResult::SelfClosing(node) => {
                    finalize_node(node, tag_stack, root_template, context)?;
                }
                // Create new layer in the stack (unless it's a void element)
                HtmlTagResult::StartTag(start_tag) => {
                    // Check if this is an HTML void element (br, img, input, etc.)
                    // These don't need closing tags and are treated as self-closing
                    let tag_name = start_tag.name.content.as_str();
                    if HTML_VOID_ELEMENTS.contains(&tag_name) {
                        // Collect used_variables from attrs
                        let used_variables: Vec<Token> = start_tag
                            .attrs
                            .iter()
                            .flat_map(|attr| attr.used_variables.clone())
                            .collect();
                        // Treat void element as self-closing
                        let node = Node::SelfClosing {
                            used_variables,
                            comments: start_tag.comments.clone(),
                            start_tag,
                            introduced_variables: vec![],
                            contains_fills: false,
                        };
                        finalize_node(node, tag_stack, root_template, context)?;
                    } else {
                        let body = Template {
                            elements: vec![],
                            comments: vec![],
                            used_variables: vec![],
                            slots: vec![],
                        };
                        tag_stack.push(TagStackEntry { start_tag, body });
                    }
                }
                // Close current layer in the stack
                HtmlTagResult::EndTag(end_tag) => {
                    let end_tag_name = &end_tag.name.content;

                    // Check if tag stack is empty
                    if tag_stack.is_empty() {
                        return Err(ParseError::from_span(
                            tag_span,
                            format!(
                                "Unexpected closing tag '</{}>': no matching opening tag",
                                end_tag_name
                            ),
                        ));
                    }

                    // Check if end tag matches the current stack entry
                    let stack_entry = tag_stack.last().unwrap();
                    if &stack_entry.start_tag.name.content != end_tag_name {
                        return Err(ParseError::from_span(
                            tag_span,
                            format!(
                                "Mismatched tags: expected closing tag '</{}>', found '</{}>'",
                                stack_entry.start_tag.name.content, end_tag_name
                            ),
                        ));
                    }

                    // Pop current layer from stack
                    let TagStackEntry { start_tag, body } = tag_stack.pop().unwrap();

                    let introduced_variables = extract_introduced_variables(&start_tag, context)?;

                    // Create Node and push to parent context
                    let node = Node::from_start_and_end_tags(
                        start_tag,
                        end_tag,
                        body,
                        introduced_variables,
                    );

                    finalize_node(node, tag_stack, root_template, context)?;
                }
            }
        }
        _ => {
            return Err(ParseError::from_span(
                inner.as_span(),
                format!("Unexpected template element rule: {:?}", inner_rule),
            ));
        }
    }
    Ok(())
}

/// Logic that runs when we construct a Node (either from SelfClosing, or finished with bodied Node).
fn finalize_node(
    mut node: Node,
    tag_stack: &mut Vec<TagStackEntry>,
    root_template: &mut Template,
    context: &ParserContext,
) -> Result<(), ParseError> {
    // Extract fill nodes and determine contains_fills
    let fill_nodes = match &node {
        Node::WithBody { body, .. } => extract_fill_nodes(body, false, false),
        Node::SelfClosing { .. } => vec![],
    };
    let contains_fills = !fill_nodes.is_empty();

    validate_node(&node, &fill_nodes, tag_stack, context)?;
    let parent_template = get_current_template(tag_stack, root_template);
    validate_node_against_parent(&node, parent_template)?;

    // Let components know how to handle body based on whether it contains fills
    node.set_contains_fills(contains_fills);

    // Extract slot if this is a <c-slot> tag
    if let Some(slot) = extract_slot_from_node(&node) {
        parent_template.slots.push(slot);
    }

    // Propagate slots from body upwards (if node has body)
    if let Node::WithBody { body, .. } = &node {
        parent_template.slots.extend(body.slots.clone());
    }

    // Propagate upwards
    parent_template.comments.extend(node.comments().clone());
    parent_template
        .used_variables
        .extend(node.used_variables().clone());
    parent_template.elements.push(TemplateElement::Node(node));

    Ok(())
}

/// Convert text pair to Text
fn process_text(
    text_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<Text, ParseError> {
    let token = context.create_token(&text_pair);
    Ok(Text { token })
}

/// Convert template comment pair to Comment
fn process_template_comment(
    comment_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<Comment, ParseError> {
    let token = context.create_token(&comment_pair);

    // Extract the content (without {# and #})
    // template_comment = "{#" ~ template_comment_content ~ "#}"
    let template_comment_content: pest::iterators::Pair<'_, _> =
        unwrap_pair(comment_pair, Rule::template_comment_content)?;
    let value_token = context.create_token(&template_comment_content);

    Ok(Comment {
        token,
        value: value_token,
    })
}

/// Convert html_comment pair to Text and Comment
fn process_html_comment(
    comment_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<(Text, Comment), ParseError> {
    // html_comment = "<!--" ~ html_comment_content ~ "-->"
    let token = context.create_token(&comment_pair);

    // Extract the content (without <!-- and -->)
    let comment_content = unwrap_pair(comment_pair, Rule::html_comment_content)?;
    let value_token = context.create_token(&comment_content);

    let comment = Comment {
        token: token.clone(),
        value: value_token,
    };
    let text = Text { token };

    Ok((text, comment))
}

/// Convert template_expression pair to Expr
fn process_template_expression(
    expr_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<Expr, ParseError> {
    let expr_token = context.create_token(&expr_pair);
    let expr_span = expr_pair.as_span();

    // template_expression -> "{{" ~ WHITESPACE ~ python_expr ~ WHITESPACE ~ "}}"
    // Filter out WHITESPACE
    // NOTE: Not collecting comments in context because template comments are not allowed inside {{ ... }}.
    let (mut filtered_pairs, template_comments) =
        context.extract_comments_from_pairs(expr_pair.into_inner())?;

    // Find expression_content - It should be the only non-comment, non-spacing pair
    let python_expr_pair = filtered_pairs.next().ok_or_else(|| {
        ParseError::from_span(
            expr_span,
            "python_expr should contain python_expr".to_string(),
        )
    })?;

    // Extract the value token (the content inside {{ ... }})
    let value_span = python_expr_pair.as_span();
    let value_token = context.create_token(&python_expr_pair);

    let (used_variables, python_comments) =
        process_expression(&value_token, Some(value_span), context)?;

    let mut comments = template_comments.clone();
    comments.extend(python_comments);

    Ok(Expr {
        token: expr_token,
        value: value_token,
        used_variables,
        comments,
    })
}

/// Process an expression using the language-specific implementation from the context.
fn process_expression(
    value_token: &Token,
    value_span: Option<pest::Span>,
    context: &ParserContext,
) -> Result<(Vec<Token>, Vec<Comment>), ParseError> {
    let transform_result = context
        .lang
        .parse_expression(&value_token.content)
        .map_err(|e| {
            let value_span = value_span.unwrap_or_else(|| value_token.as_span().unwrap());
            ParseError::from_span(value_span, format!("Failed to parse expression: {}", e))
        })?;

    // Calculate offsets for adjusting token positions
    let index_offset = value_token.start_index;
    let (value_line, value_col) = value_token.line_col;
    // line_offset: value_line - 1 (because lines are 1-indexed)
    let line_offset = value_line - 1;
    // col_offset: value_col - 1 (because cols are 1-indexed)
    let col_offset = value_col - 1;

    let used_vars: Vec<Token> = transform_result
        .used_vars
        .into_iter()
        .map(|token| token.offset(index_offset, line_offset, col_offset))
        .collect();

    let comments: Vec<Comment> = transform_result
        .comments
        .into_iter()
        .map(|comment| Comment {
            token: comment.token.offset(index_offset, line_offset, col_offset),
            value: comment.value.offset(index_offset, line_offset, col_offset),
        })
        .collect();

    Ok((used_vars, comments))
}

/// Process a nested template string to extract nested template tags
fn process_template_string(
    template_token: &Token,
    parent_context: &ParserContext,
) -> Result<Template, ParseError> {
    let content = &template_token.content;

    // Calculate offsets for the nested template, combining with parent offsets
    let (line, col) = template_token.line_col;

    // Template strings may be recursively nested, so we need to combine offsets:
    // - Line offset accumulates
    // - Column offset: parent's col_offset only applies if we're on line 1
    // - Index offset accumulates
    let new_line_offset = parent_context.line_offset + (line - 1);
    let new_col_offset = if line == 1 {
        parent_context.col_offset + (col - 1)
    } else {
        col - 1
    };
    let new_index_offset = parent_context.index_offset + template_token.start_index;

    let nested_context =
        parent_context.create_child_context(new_line_offset, new_col_offset, new_index_offset);

    // Parse the content as a template with updated offsets
    let template = parse_template_inner(&content, &nested_context)?;
    Ok(template)
}

/// Process an HTML tag (start, end, or self-closing)
fn process_html_tag(
    tag_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<HtmlTagResult, ParseError> {
    // html_tag -> html_start_tag | html_end_tag | html_self_closing_tag
    let tag_span = tag_pair.as_span();
    let inner = tag_pair.into_inner().next().ok_or_else(|| {
        ParseError::from_span(
            tag_span,
            "html_tag should contain a start, end, or self-closing tag".to_string(),
        )
    })?;
    let inner_rule = inner.as_rule();

    match inner_rule {
        Rule::html_start_tag => {
            let start_tag = process_html_start_tag(inner, context)?;
            Ok(HtmlTagResult::StartTag(start_tag))
        }
        Rule::html_end_tag => {
            let end_tag = process_html_end_tag(inner, context)?;
            Ok(HtmlTagResult::EndTag(end_tag))
        }
        Rule::html_self_closing_tag => {
            let node = process_html_self_closing_tag(inner, context)?;
            Ok(HtmlTagResult::SelfClosing(node))
        }
        _ => Err(ParseError::from_span(
            inner.as_span(),
            format!("Unexpected HTML tag rule: {:?}", inner_rule),
        )),
    }
}

/// Process html_start_tag pair into HtmlStartTag
fn process_html_start_tag(
    start_tag_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<HtmlStartTag, ParseError> {
    // html_start_tag = "<" ~ html_tag_name ~ (spacing_with_whitespace ~ html_attribute)* ~ spacing* ~ ">"
    let start_tag_span = start_tag_pair.as_span();
    let start_tag_token = context.create_token(&start_tag_pair);

    // Extract comments from spacing/spacing_with_whitespace pairs,
    // filtering them out and keeping only meaningful pairs (tag name, attributes).
    let (mut filtered_pairs, comments) =
        context.extract_comments_from_pairs(start_tag_pair.into_inner())?;

    // Get tag name
    let name_pair = filtered_pairs.next().ok_or_else(|| {
        ParseError::from_span(
            start_tag_span,
            "html_start_tag should contain html_tag_name".to_string(),
        )
    })?;
    // Accept both html_tag_name and html_raw_tag_name (for <c-raw> tags)
    assert_rules(&name_pair, &[Rule::html_tag_name, Rule::html_raw_tag_name])?;

    let name = context.create_token(&name_pair);
    let name_rule = name_pair.as_rule();

    // Check if this is a forbidden tag name (skip for html_raw_tag_name which is expected)
    if name_rule == Rule::html_tag_name && FORBIDDEN_HTML_TAG_NAMES.contains(&name.content.as_str())
    {
        return Err(ParseError::from_span(
            name_pair.as_span(),
            format!(
                "Tag name '{}' is reserved and cannot be used as a regular HTML tag. Use the special syntax instead.",
                name.content
            ),
        ));
    }

    // Parse attributes from the remaining filtered pairs
    let attrs = parse_html_attributes(filtered_pairs, context)?;
    let start_tag = HtmlStartTag {
        token: start_tag_token,
        name,
        attrs,
        is_self_closing: false,
        comments,
    };

    Ok(start_tag)
}

/// Process an HTML end tag: validates and returns the end tag
/// The caller should pop from stack and use the popped data along with this end_tag
fn process_html_end_tag(
    end_tag_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<HtmlEndTag, ParseError> {
    // html_end_tag = "</" ~ html_tag_name ~ (spacing_with_whitespace ~ html_attribute)* ~ spacing* ~ ">"
    let end_tag_span = end_tag_pair.as_span();
    let end_tag_rule = end_tag_pair.as_rule();
    let end_tag_token = context.create_token(&end_tag_pair);

    // Extract comments from spacing/spacing_with_whitespace pairs,
    // filtering them out and keeping only meaningful pairs (tag name, attributes).
    let (mut filtered_pairs, comments) =
        context.extract_comments_from_pairs(end_tag_pair.into_inner())?;

    // Get tag name
    let name_pair = filtered_pairs.next().ok_or_else(|| {
        ParseError::from_span(
            end_tag_span,
            format!("{:?} should contain tag name", end_tag_rule),
        )
    })?;
    assert_rules(&name_pair, &[Rule::html_tag_name, Rule::html_raw_tag_name])?;

    let name = context.create_token(&name_pair);
    let name_rule = name_pair.as_rule();

    // Check if this is a forbidden tag name (skip for html_raw_tag_name which is expected)
    if name_rule == Rule::html_tag_name && FORBIDDEN_HTML_TAG_NAMES.contains(&name.content.as_str())
    {
        return Err(ParseError::from_span(
            name_pair.as_span(),
            format!(
                "Tag name '{}' is reserved and cannot be used as a regular HTML tag. Use the special syntax instead.",
                name.content
            ),
        ));
    }

    // Check if end tag has any attributes, and raise error if so.
    // After comment extraction, only html_attribute pairs remain.
    let next_attr_pair = filtered_pairs.next();
    if let Some(attr_pair) = next_attr_pair {
        let attr_span = attr_pair.as_span();
        return Err(ParseError::from_span(
            attr_span,
            format!("{:?} must not contain any attributes", end_tag_rule),
        ));
    }

    let end_tag = HtmlEndTag {
        token: end_tag_token,
        name,
        comments,
    };

    Ok(end_tag)
}

/// Process a self-closing HTML tag: create Node::SelfClosing
fn process_html_self_closing_tag(
    self_closing_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<Node, ParseError> {
    // html_self_closing_tag = "<" ~ html_tag_name ~ (spacing_with_whitespace ~ html_attribute)* ~ spacing* ~ "/" ~ ">"
    let self_closing_span = self_closing_pair.as_span();
    let self_closing_token = context.create_token(&self_closing_pair);

    // Extract comments from spacing/spacing_with_whitespace pairs,
    // filtering them out and keeping only meaningful pairs (tag name, attributes).
    let (mut filtered_pairs, comments_from_tag) =
        context.extract_comments_from_pairs(self_closing_pair.into_inner())?;

    // Get tag name
    let name_pair = filtered_pairs.next().ok_or_else(|| {
        ParseError::from_span(
            self_closing_span,
            "html_self_closing_tag should contain html_tag_name".to_string(),
        )
    })?;
    assert_rule(&name_pair, Rule::html_tag_name)?;
    let name = context.create_token(&name_pair);

    // Check if this is a forbidden tag name
    if FORBIDDEN_HTML_TAG_NAMES.contains(&name.content.as_str()) {
        return Err(ParseError::from_span(
            name_pair.as_span(),
            format!(
                "Tag name '{}' is reserved and cannot be used as a regular HTML tag. Use the special syntax instead.",
                name.content
            ),
        ));
    }

    // Parse attributes from the remaining filtered pairs
    let attrs = parse_html_attributes(filtered_pairs, context)?;

    let used_variables = attrs
        .iter()
        .flat_map(|attr| attr.used_variables.clone())
        .collect();
    let comments_from_attrs = attrs.iter().flat_map(|attr| attr.comments.clone());
    let mut comments: Vec<Comment> = comments_from_tag.clone();
    comments.extend(comments_from_attrs);

    let start_tag = HtmlStartTag {
        token: self_closing_token,
        name,
        attrs,
        is_self_closing: true,
        comments: comments_from_tag,
    };

    let introduced_variables = extract_introduced_variables(&start_tag, context)?;

    Ok(Node::SelfClosing {
        start_tag,
        used_variables,
        introduced_variables,
        comments,
        contains_fills: false, // Self-closing nodes never have fills
    })
}

/// Parse HTML attributes from Pest pairs
fn parse_html_attributes<'a>(
    attrs_pairs: impl Iterator<Item = pest::iterators::Pair<'a, Rule>>,
    context: &ParserContext,
) -> Result<Vec<HtmlAttr>, ParseError> {
    let mut attrs = Vec::new();

    // Collect all html_attribute pairs, skipping spacing
    for attr_pair in attrs_pairs {
        // Skip spacing_with_whitespace and spacing rules
        // These are generated because HTML tag rules are compound-atomic (${ })
        let rule = attr_pair.as_rule();
        if rule == Rule::spacing_with_whitespace || rule == Rule::spacing {
            continue;
        }

        let attr = parse_html_attribute(attr_pair, context)?;
        attrs.push(attr);
    }

    Ok(attrs)
}

/// Parse a single html_attribute into HtmlAttr
fn parse_html_attribute(
    attr_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<HtmlAttr, ParseError> {
    assert_rule(&attr_pair, Rule::html_attribute)?;

    let attr_token = context.create_token(&attr_pair);
    let attr_span = attr_pair.as_span();

    // html_attribute = html_attribute_name ~ html_attribute_value?
    let mut inner: pest::iterators::Pairs<Rule> = attr_pair.into_inner();

    // Get attribute name
    let name_pair = inner.next().ok_or_else(|| {
        ParseError::from_span(
            attr_span,
            "html_attribute should contain html_attribute_name".to_string(),
        )
    })?;
    assert_rule(&name_pair, Rule::html_attribute_name)?;
    let key = context.create_token(&name_pair);

    // Get attribute value (optional)
    let maybe_value_pair = inner.next();
    // html_attribute_value = (double_quoted_value | single_quoted_value | unquoted_value)
    let maybe_value_content_pair = maybe_value_pair.map(
        |pair| {
            let pair_span = pair.as_span();
            pair.into_inner().next().ok_or_else(|| {
                ParseError::from_span(
                    pair_span,
                    "html_attribute_value should contain double_quoted_value, single_quoted_value, or unquoted_value".to_string(),
                )
            })
        }
    ).transpose()?;

    let (value, inner_value, quote_char) = match maybe_value_content_pair {
        // Quoted attribute, e.g. `key="value"` or `key='value'`
        Some(pair) if pair.as_rule() == Rule::double_quoted_value => {
            let value_token = context.create_token(&pair);
            let expr_token = value_token.clone().crop_cols(1, -1);
            (Some(value_token), Some(expr_token), Some('"'))
        }
        Some(pair) if pair.as_rule() == Rule::single_quoted_value => {
            let value_token = context.create_token(&pair);
            let expr_token = value_token.clone().crop_cols(1, -1);
            (Some(value_token), Some(expr_token), Some('\''))
        }
        // Unquoted attribute, e.g. `key=value`
        Some(pair) if pair.as_rule() == Rule::unquoted_value => {
            let value_token = context.create_token(&pair);
            let expr_token = value_token.clone();
            (Some(value_token), Some(expr_token), None)
        }
        // Boolean attribute (no value), e.g. `key`
        None => (None, None, None),
        Some(other) => {
            let value_span = other.as_span();
            return Err(ParseError::from_span(
                value_span,
                format!("Expected double_quoted_value, single_quoted_value, or unquoted_value, got {:?}", other),
            ));
        }
    };

    // Determine attribute kind based on key name and value
    // Clone inner_value since we need it later for HtmlAttr, but also need to use it for processing
    let inner_value_for_attr = inner_value.clone();
    let (kind, used_variables, comments) = if key.content.starts_with("c-") {
        // Check if it's a template attribute (value starts/ends with HTML tags or fragment).
        // E.g. `<span>...</span>` or `<>...</>`
        //
        // We require strict detection to avoid treating arbitrary text like
        // `< THIS IS TEXT >` or `<< lol >>` as templates:
        //
        // 1. Fragment: trimmed starts with `<>` and ends with `</>`
        // 2. HTML tag: trimmed starts with `<` + ASCII alpha (e.g. `<span`, `<c-btn`)
        //    AND ends with either a close tag (`</tag>`) or self-closing (`/>`)
        let (is_fragment, is_template) = inner_value
            .as_ref()
            .map(|inner_value| {
                let trimmed = inner_value.content.trim();

                // Fragment: <>...</>
                let is_fragment = trimmed.starts_with("<>") && trimmed.ends_with("</>");
                if is_fragment {
                    return (true, true);
                }

                // HTML tag: must start with <[a-zA-Z]
                let starts_with_tag = trimmed.len() >= 2
                    && trimmed.starts_with('<')
                    && trimmed.as_bytes()[1].is_ascii_alphabetic();

                if !starts_with_tag {
                    return (false, false);
                }

                // Must end with </tag_name> or />
                let ends_with_self_closing = trimmed.ends_with("/>");
                let ends_with_close_tag = if let Some(close_start) = trimmed.rfind("</") {
                    let after_close = &trimmed[close_start + 2..];
                    // After </ we expect: tag_name + optional whitespace + >
                    let after_close_trimmed = after_close.trim_end();
                    after_close_trimmed.ends_with('>')
                        && after_close_trimmed.len() > 1
                        && after_close_trimmed[..after_close_trimmed.len() - 1]
                            .trim_end()
                            .chars()
                            .all(|c| {
                                c.is_ascii_alphanumeric()
                                    || c == '-'
                                    || c == ':'
                                    || c == '_'
                                    || c == '.'
                            })
                } else {
                    false
                };

                (false, ends_with_close_tag || ends_with_self_closing)
            })
            .unwrap_or((false, false));

        if is_template {
            // c-... attribute WITH nested template value.
            // If fragment, strip the <> and </> delimiters (and surrounding whitespace)
            // before parsing the inner content as a template.
            let template = if is_fragment {
                let iv = inner_value.as_ref().unwrap();
                let content = &iv.content;
                let ws_before = content.len() - content.trim_start().len();
                let ws_after = content.len() - content.trim_end().len();
                let start_skip = (ws_before + 2) as isize; // whitespace + "<>"
                let end_skip = -((ws_after + 3) as isize); // "</>" + whitespace
                let fragment_inner = iv.clone().crop_cols(start_skip, end_skip);
                process_template_string(&fragment_inner, context)?
            } else {
                process_template_string(inner_value.as_ref().unwrap(), context)?
            };
            let comments = template.comments.clone();
            let used_variables = template.used_variables.clone();
            (HtmlAttrKind::Template, used_variables, comments)
        } else {
            // c-... attribute WITH expression value
            if let Some(ref inner_value_ref) = inner_value {
                let (used_variables, comments) =
                    process_expression(inner_value_ref, None, context)?;
                (HtmlAttrKind::Expression, used_variables, comments)
            // c-... attribute WITHOUT value
            } else {
                (HtmlAttrKind::Expression, Vec::new(), Vec::new())
            }
        }
    } else {
        // Non-prefixed attributes are static, e.g. `class="static_value"`
        (HtmlAttrKind::Static, Vec::new(), Vec::new())
    };

    Ok(HtmlAttr {
        token: attr_token,
        key,
        value,
        inner_value: inner_value_for_attr,
        quote_char,
        kind,
        comments,
        used_variables,
    })
}

/// Process an html_raw tag: <c-raw>...</c-raw>
/// Returns a Node::WithBody with the raw content as a single Text element
fn process_html_raw(
    raw_pair: pest::iterators::Pair<Rule>,
    context: &ParserContext,
) -> Result<Node, ParseError> {
    // html_raw = html_raw_start_tag ~ html_raw_content ~ html_raw_end_tag
    let raw_span = raw_pair.as_span();
    let mut inner = raw_pair.into_inner();

    // Get start tag
    let start_tag_pair = inner.next().ok_or_else(|| {
        ParseError::from_span(
            raw_span,
            "html_raw should contain html_raw_start_tag".to_string(),
        )
    })?;
    assert_rule(&start_tag_pair, Rule::html_raw_start_tag)?;
    let start_tag = process_html_start_tag(start_tag_pair, context)?;

    // Get content
    let content_pair = inner.next().ok_or_else(|| {
        ParseError::from_span(
            raw_span,
            "html_raw should contain html_raw_content".to_string(),
        )
    })?;
    assert_rule(&content_pair, Rule::html_raw_content)?;

    // Treat content as text
    let content_text = Text {
        token: context.create_token(&content_pair),
    };
    let body = Template {
        elements: vec![TemplateElement::Text(content_text)],
        comments: vec![],
        used_variables: vec![],
        slots: vec![],
    };

    // Get end tag
    let end_tag_pair = inner.next().ok_or_else(|| {
        ParseError::from_span(
            raw_span,
            "html_raw should contain html_raw_end_tag".to_string(),
        )
    })?;
    assert_rule(&end_tag_pair, Rule::html_raw_end_tag)?;
    let end_tag = process_html_end_tag(end_tag_pair, context)?;

    let node = Node::from_start_and_end_tags(start_tag, end_tag, body, vec![]);

    // `<c-raw>` allows no attributes. Validate here because raw nodes are pushed
    // directly to the template and bypass the normal `validate_node` path.
    validate_attributes_present(&node, context)?;

    Ok(node)
}

// Decide which template to push items to
fn get_current_template<'a>(
    tag_stack: &'a mut Vec<TagStackEntry>,
    root_template: &'a mut Template,
) -> &'a mut Template {
    if let Some(stack_entry) = tag_stack.last_mut() {
        &mut stack_entry.body
    } else {
        root_template
    }
}

// //////////////////////////////////////////////////////////
// VALIDATION
// //////////////////////////////////////////////////////////

/// Validate a Node, its attributes, and its children.
fn validate_node(
    node: &Node,
    fill_nodes: &[FillNodeInfo],
    tag_stack: &[TagStackEntry],
    context: &ParserContext,
) -> Result<(), ParseError> {
    validate_fill_placement(&node, tag_stack)?;
    validate_attributes_present(&node, context)?;
    validate_attribute_conflicts(&node)?;
    validate_c_bind_attrs(&node)?;
    validate_fill_names(&node, fill_nodes, context)?;
    validate_variable_shadowing(&node)?;

    Ok(())
}

/// Validate that all `c-bind` attributes have a non-empty value.
///
/// `c-bind` is used to spread a dictionary as attributes (similar to Vue's `v-bind`),
/// so it must have a value that evaluates to a dict. Boolean `c-bind` (no value),
/// empty `c-bind=""`, and whitespace-only `c-bind="   "` are all invalid.
fn validate_c_bind_attrs(node: &Node) -> Result<(), ParseError> {
    for attr in node.attrs() {
        if attr.key.content == "c-bind" {
            let has_nonempty_value = attr
                .inner_value
                .as_ref()
                .is_some_and(|v| !v.content.trim().is_empty());

            if !has_nonempty_value {
                return Err(ParseError::from_span(
                    attr.token.as_span().unwrap(),
                    "'c-bind' attribute must have a non-empty value.".to_string(),
                ));
            }
        }
    }
    Ok(())
}

/// Validate a Node against its parent template.
///
/// This runs after we popped the Node from the stack.
fn validate_node_against_parent(node: &Node, parent_template: &Template) -> Result<(), ParseError> {
    validate_tag_grouping(&node, parent_template)?;
    validate_fill_exclusivity(&node, parent_template)?;

    Ok(())
}

/// Validate that a `<c-fill>` node is inside a valid component.
///
/// `<c-fill>` must be inside a component tag (either `<c-component>` or a custom component like `<c-MyComp>`).
/// It can be nested inside transparent tags (`<c-if>`, `<c-elif>`, `<c-else>`, `<c-for>`, `<c-empty>`),
/// in which case we keep looking up the stack.
///
/// # Errors
/// - If `<c-fill>` is not inside any component (reached root)
/// - If `<c-fill>` is inside a regular HTML tag (doesn't start with `c-`)
/// - If `<c-fill>` is inside a reserved special tag
///
/// E.g. this is valid ✅:
/// ```html
/// <c-my-comp>
///   <c-fill name="footer"> </c-fill>
/// </c-my-comp>
/// ```
///
/// This is valid ✅:
/// ```html
/// <c-my-comp>
///   <c-for each="item in items">
///     <c-fill name="item"> </c-fill>
///   </c-for>
/// </c-my-comp>
/// ```
///
/// This is valid ✅:
/// ```html
/// <c-my-comp>
///   <c-if cond="is_visible">
///     <c-fill name="header"> </c-fill>
///   </c-if>
/// </c-my-comp>
/// ```
///
/// This is NOT valid (c-fill inside regular HTML tag) ❌:
/// ```html
/// <div>
///   <c-fill name="footer"> </c-fill>
/// </div>
/// ```
///
/// This is NOT valid (c-fill inside regular HTML tag) ❌:
/// ```html
/// <c-my-comp>
///   <div>
///     <c-fill name="footer"> </c-fill>
///   </div>
/// </c-my-comp>
/// ```
///
/// This is NOT valid (c-fill inside regular HTML tag) ❌:
/// ```html
/// <c-my-comp>
///   <c-if cond="is_visible">
///     <div>
///       <c-fill name="footer"> </c-fill>
///     </div>
///   </c-if>
/// </c-my-comp>
/// ```
fn validate_fill_placement(node: &Node, tag_stack: &[TagStackEntry]) -> Result<(), ParseError> {
    let tag_name = node.tag_name();

    // Only validate if this is a <c-fill> tag
    if tag_name != C_FILL_TAG {
        return Ok(());
    }

    // Get the start_tag token for error reporting
    let start_tag_token = &node.start_tag().token;
    let start_tag_span = start_tag_token.as_span().unwrap();

    // Walk up the tag stack, skipping transparent tags
    for stack_entry in tag_stack.iter().rev() {
        let parent_tag_name = stack_entry.start_tag.name.content.as_str();

        // If we find a transparent tag, continue looking up
        if CONTROL_FLOW_TAGS.contains(&parent_tag_name) {
            continue;
        }

        // If we find a reserved tag, raise error
        if RESERVED_TAG_NAMES.contains(&parent_tag_name) {
            return Err(ParseError::from_span(
                start_tag_span,
                format!(
                    "Tag '<c-fill>' cannot be inside '<{}>'. It must be inside a component tag (e.g., '<c-component>' or '<c-MyComp>').",
                    parent_tag_name
                ),
            ));
        }

        // If the tag doesn't start with 'c-', it's a regular HTML tag (e.g. '<div>') - raise error
        // NOTE: Regular HTML tags can be INSIDE `<c-fill>`, but not the other way around,
        // as <c-fill> mark the start of a content block.
        if !parent_tag_name.starts_with("c-") {
            return Err(ParseError::from_span(
                start_tag_span,
                format!(
                    "Tag '<c-fill>' cannot be inside '<{}>'. It must be inside a component tag (e.g., '<c-component>' or '<c-MyComp>').",
                    parent_tag_name
                ),
            ));
        }

        // If we reach here, the tag starts with 'c-' and is not reserved or transparent,
        // so it must be a component - this is valid!
        return Ok(());
    }

    // If we've exhausted the stack, we're at the root - raise error
    Err(ParseError::from_span(
        start_tag_span,
        "Tag '<c-fill>' must be inside a component tag (e.g., '<c-component>' or '<c-MyComp>')."
            .to_string(),
    ))
}

/// Validate that `<c-fill>` tags are not mixed with incompatible tags at the same level.
///
/// "Fill-compatible" tags are `<c-fill>` itself and control flow tags
/// (`c-if/c-elif/c-else/c-for/c-empty`). At a given sibling level, once a fill-compatible
/// tag appears, all subsequent siblings must also be fill-compatible (and vice versa).
///
/// When a control flow tag is a sibling of `<c-fill>`, its body must recursively contain
/// only `<c-fill>` and/or other control flow tags (no regular HTML, components, text, etc.).
///
/// # Valid examples
///
/// ```html
/// <c-my-comp>
///   <c-fill name="header">A</c-fill>
///   <c-fill name="footer">B</c-fill>
/// </c-my-comp>
/// ```
///
/// ```html
/// <c-my-comp>
///   <c-fill name="header">A</c-fill>
///   <c-if cond="x"><c-fill name="footer">B</c-fill></c-if>
/// </c-my-comp>
/// ```
///
/// # Invalid examples
///
/// ```html
/// <c-my-comp>
///   <c-fill name="header">A</c-fill>
///   <div>Hello</div>
/// </c-my-comp>
/// ```
///
/// ```html
/// <c-my-comp>
///   <c-fill name="header">A</c-fill>
///   <c-if cond="x"><div>Not a fill</div></c-if>
/// </c-my-comp>
/// ```
///
/// # Errors
/// - If a fill-compatible tag follows a non-fill-compatible sibling (or vice versa)
/// - If a control flow tag sibling of `<c-fill>` contains non-fill, non-control-flow content
fn validate_fill_exclusivity(node: &Node, template: &Template) -> Result<(), ParseError> {
    let tag_name = node.tag_name();

    // Find the last Node in template.elements (skip Text and Expr)
    let last_node = template.elements.iter().rev().find_map(|elem| match elem {
        TemplateElement::Node(n) => Some(n),
        _ => None,
    });

    // If there's no previous node, there's nothing to validate
    let Some(prev_node) = last_node else {
        return Ok(());
    };

    let prev_tag_name = prev_node.tag_name();

    // Get the start_tag token for error reporting
    let start_tag_token = &node.start_tag().token;
    let start_tag_span = start_tag_token.as_span().unwrap();

    /// A tag is "fill-compatible" if it's `<c-fill>` or a control flow tag.
    /// At a sibling level that contains `<c-fill>`, only fill-compatible tags are allowed.
    fn is_fill_compatible(tag: &str) -> bool {
        tag == C_FILL_TAG || CONTROL_FLOW_TAGS.contains(tag)
    }

    let is_current_compat = is_fill_compatible(tag_name);
    let is_prev_compat = is_fill_compatible(prev_tag_name);

    // Determine if we're in a "fill context" - i.e. there is at least one actual <c-fill>
    // tag among the siblings (including the current node being added). Without a <c-fill>,
    // control flow tags can be siblings of anything normally.
    let is_current_fill = tag_name == C_FILL_TAG;
    let has_fill_in_siblings = is_current_fill
        || template
            .elements
            .iter()
            .any(|elem| matches!(elem, TemplateElement::Node(n) if n.tag_name() == C_FILL_TAG));

    // If we're NOT in a fill context, no fill-related validation needed
    if !has_fill_in_siblings {
        return Ok(());
    }

    // We ARE in a fill context. Only fill-compatible tags are allowed.

    // If current is fill-compatible and previous is NOT, raise error
    if is_current_compat && !is_prev_compat {
        return Err(ParseError::from_span(
            start_tag_span,
            format!(
                "Tag '<{}>' cannot follow '<{}>' here. '<c-fill>' (and control flow) tags must be grouped together, not mixed with other tags.",
                tag_name, prev_tag_name
            ),
        ));
    }

    // If current is NOT fill-compatible and previous IS, raise error
    if !is_current_compat && is_prev_compat {
        return Err(ParseError::from_span(
            start_tag_span,
            format!(
                "Tag '<{}>' cannot follow '<{}>' here. '<c-fill>' (and control flow) tags must be grouped together, not mixed with other tags.",
                tag_name, prev_tag_name
            ),
        ));
    }

    // Both are fill-compatible. If a control flow tag is present, validate that its body
    // only contains fills and/or other control flow tags.
    if is_current_compat && is_prev_compat {
        // Validate the CURRENT node's body when it's a control flow tag
        // (c-fill bodies are fine - they contain the slot content).
        if CONTROL_FLOW_TAGS.contains(tag_name) {
            if let Node::WithBody { body, .. } = node {
                if !_contains_only_fills_and_control_flow(body) {
                    return Err(ParseError::from_span(
                        start_tag_span,
                        format!(
                            "Control flow tag '<{}>' is a sibling of '<c-fill>' but contains non-fill content. \
                            When mixed with '<c-fill>' tags, control flow tags must contain only '<c-fill>' or other control flow tags.",
                            tag_name
                        ),
                    ));
                }
            }
        }

        // Also validate the PREVIOUS node if it's a control flow tag.
        // This handles the case where the first sibling is a control flow tag and the second is <c-fill>.
        if CONTROL_FLOW_TAGS.contains(prev_tag_name) {
            if let Node::WithBody { body, .. } = prev_node {
                if !_contains_only_fills_and_control_flow(body) {
                    let prev_start_tag_span = prev_node.start_tag().token.as_span().unwrap();
                    return Err(ParseError::from_span(
                        prev_start_tag_span,
                        format!(
                            "Control flow tag '<{}>' is a sibling of '<c-fill>' but contains non-fill content. \
                            When mixed with '<c-fill>' tags, control flow tags must contain only '<c-fill>' or other control flow tags.",
                            prev_tag_name
                        ),
                    ));
                }
            }
        }
    }

    Ok(())
}

/// Check if a template body contains only `<c-fill>` tags and/or control flow tags (recursively).
///
/// Returns `true` if the body is "fill-only": every node is either `<c-fill>` or a control flow
/// tag whose body also satisfies this constraint. Text/expression elements are allowed only if
/// they contain only whitespace.
///
/// This is used to validate that control flow siblings of `<c-fill>` don't smuggle in
/// non-fill content like `<div>` or components.
fn _contains_only_fills_and_control_flow(template: &Template) -> bool {
    for element in &template.elements {
        match element {
            TemplateElement::Text(text) => {
                // Whitespace-only text is allowed (formatting/indentation)
                if !text.token.content.trim().is_empty() {
                    return false;
                }
            }
            TemplateElement::Expr(_) => {
                // Expressions are not allowed in fill-only context
                return false;
            }
            TemplateElement::Node(node) => {
                let tag_name = node.tag_name();
                if tag_name == C_FILL_TAG {
                    // <c-fill> is always OK
                    continue;
                } else if CONTROL_FLOW_TAGS.contains(tag_name) {
                    // Control flow tag: recursively check its body
                    if let Node::WithBody { body, .. } = node {
                        if !_contains_only_fills_and_control_flow(body) {
                            return false;
                        }
                    }
                    // Self-closing control flow is fine (empty body)
                } else {
                    // Any other tag (HTML, component, etc.) is not allowed
                    return false;
                }
            }
        }
    }
    true
}

/// Validate that introduced variables don't conflict with used variables.
///
/// This prevents variable shadowing where a node introduces a variable that is already
/// used in its body.
///
/// This simplifies the templates, because we don't need to worry about variable shadowing.
///
/// Applies to:
/// - `<c-for>` nodes: variables from the `each` attribute
/// - `<c-fill>` nodes: variables from `data` and `default` attributes
fn validate_variable_shadowing(node: &Node) -> Result<(), ParseError> {
    let tag_name = node.tag_name();

    // Get introduced variables from the node
    let introduced_vars = node.introduced_variables();

    if introduced_vars.is_empty() {
        return Ok(());
    }

    // Get used variables from the node's body
    let used_vars = node.used_variables();

    // Check for conflicts
    for introduced_var in introduced_vars {
        let introduced_name = &introduced_var.content;
        for used_var in used_vars {
            let used_name = &used_var.content;
            if used_name == introduced_name {
                return Err(ParseError::from_span(
                    introduced_var.as_span().unwrap(),
                    format!(
                        "Cannot define variable '{}' in tag '<{}>' - variable name is already taken. Variable shadowing is not allowed, use a different name.",
                        introduced_name, tag_name
                    ),
                ));
            }
        }
    }

    Ok(())
}

// Extract introduced variables (e.g. the loop variables from <c-for>, or `data/default` attributes of <c-fill>)
fn extract_introduced_variables(
    start_tag: &HtmlStartTag,
    context: &ParserContext,
) -> Result<Vec<Token>, ParseError> {
    if start_tag.name.content == C_FOR_TAG {
        _extract_for_loop_variables_from_start_tag(&start_tag, context)
    } else if start_tag.name.content == C_FILL_TAG {
        // For <c-fill>, simply take the contents from the static data/default attributes
        let mut var_tokens = Vec::new();
        for attr in &start_tag.attrs {
            if attr.key.content == "data" || attr.key.content == "default" {
                if let Some(inner_value) = &attr.inner_value {
                    var_tokens.push(inner_value.clone());
                }
            }
        }
        Ok(var_tokens)
    } else {
        // Other tags don't introduce variables
        Ok(vec![])
    }
}

/// Extract for loop variables from a <c-for> start tag.
fn _extract_for_loop_variables_from_start_tag(
    start_tag: &HtmlStartTag,
    context: &ParserContext,
) -> Result<Vec<Token>, ParseError> {
    if start_tag.name.content != C_FOR_TAG {
        // Other tags don't introduce variables
        return Ok(vec![]);
    }

    // Find the "each" attribute
    let each_attr = start_tag
        .attrs
        .iter()
        .find(|attr| attr.key.content == "each")
        .ok_or_else(|| {
            ParseError::from_span(
                start_tag.token.as_span().unwrap(),
                "Tag '<c-for>' must have an 'each' attribute.".to_string(),
            )
        })?;

    // Get the inner value (the expression without quotes)
    let each_value = each_attr.inner_value.as_ref().ok_or_else(|| {
        ParseError::from_span(
            each_attr.token.as_span().unwrap(),
            "Tag '<c-for>' attribute 'each' must have a value.".to_string(),
        )
    })?;

    // Delegate to language-specific implementation to parse the for-loop expression
    let var_tokens = context
        .lang
        .parse_forloop_expression(&each_value.content)
        .map_err(|e| {
            ParseError::from_span(
                each_value.as_span().unwrap(),
                format!("Failed to parse 'each' attribute: {}", e),
            )
        })?;

    // Adjust token positions to match the template context
    // Calculate offsets for adjusting token positions
    let index_offset = each_value.start_index;
    let (value_line, value_col) = each_value.line_col;
    // line_offset: value_line - 1 (because lines are 1-indexed)
    let line_offset = value_line - 1;
    // col_offset: value_col - 1 (because cols are 1-indexed)
    let col_offset = value_col - 1;

    let adjusted_tokens: Vec<Token> = var_tokens
        .into_iter()
        .map(|token| token.offset(index_offset, line_offset, col_offset))
        .collect();

    Ok(adjusted_tokens)
}

/// Validate that special tags and user-defined components have the correct attributes.
///
/// Checks if the attributes on the given Node are allowed/required.
///
/// The rules come from 2 sources:
/// 1. Internal `TAG_ATTR_RULES` (hard-codedd),
/// 2. User-defined rules. This allows us to raise error messages for user-defined tags.
fn validate_attributes_present(node: &Node, context: &ParserContext) -> Result<(), ParseError> {
    let tag_name = node.tag_name();
    let attrs = node.attrs();

    // Get the start_tag token for error reporting
    let start_tag_token = &node.start_tag().token;
    let start_tag_span = start_tag_token.as_span().unwrap();

    // Extract attribute names, excluding `c-bind` which always bypasses
    // allowed/required attrs checks (it spreads a dict at runtime, so it
    // could provide any attributes dynamically).
    let attr_names: Vec<&str> = attrs
        .iter()
        .map(|attr| attr.key.content.as_str())
        .filter(|&name| name != "c-bind")
        .collect();
    let attr_names_set: HashSet<&str> = attr_names.iter().copied().collect();
    let has_c_bind = attrs.iter().any(|attr| attr.key.content == "c-bind");

    // Check if this tag has validation rules - first check built-in rules, then user-provided rules
    let (allowed_attrs, required_attrs) = if let Some(builtin_rules) = TAG_ATTR_RULES.get(tag_name)
    {
        // Use built-in rules directly
        (&builtin_rules.allowed_attrs, &builtin_rules.required_attrs)
    } else if let Some(user_rules) = context.user_rules.get(tag_name) {
        // Use user-provided rules
        (&user_rules.allowed_attrs, &user_rules.required_attrs)
    } else {
        // No rules defined for this tag - allow any attributes (may be set dynamically with c-bind)
        return Ok(());
    };

    // Validate allowed attributes
    // - If `allowed_attrs` is `None`, any attributes are allowed.
    // - If `allowed_attrs` is `Some([])`, no attributes are allowed.
    // - If `allowed_attrs` is `Some([["c-name", "name"], ["data"]])`, either "c-name" OR "name" may be present (but not both),
    //   and "data" may be present as well.
    match allowed_attrs {
        // Any attributes allowed (only required_attrs are checked)
        // No further validation needed
        None => {}
        // Allowed attributes are set explicitly - validate against them.
        Some(allowed_groups) => {
            // Build a set of all allowed attribute names (flatten all groups)
            let allowed_set: HashSet<&str> = allowed_groups
                .iter()
                .flat_map(|group| group.iter().map(|s| s.as_str()))
                .collect();

            // Check that all attributes on the tag are in the allowed set
            let invalid_attrs: Vec<&str> = attr_names
                .iter()
                .filter(|&&name| !allowed_set.contains(name))
                .copied()
                .collect();

            // Raise error if any attributes are invalid
            if !invalid_attrs.is_empty() {
                let allowed_str = allowed_set
                    .clone()
                    .into_iter()
                    .collect::<Vec<&str>>()
                    .join("', '");
                return Err(ParseError::from_span(
                    start_tag_span,
                    format!(
                        "Tag '<{}>' can only have the following attributes: '{}'. Found invalid attributes: {}.",
                        tag_name,
                        allowed_str,
                        invalid_attrs.join(", ")
                    ),
                ));
            }

            // When we get here, we know that all attributes are contained in the allowed set.
            // Next we check that for each allowed group, there's at most only one attribute present.
            for allowed_group in allowed_groups {
                let mut found_in_group: Vec<&str> = Vec::new();
                for attr_name in attr_names.iter() {
                    if allowed_group
                        .iter()
                        .any(|allowed| allowed.as_str() == *attr_name)
                    {
                        found_in_group.push(*attr_name);
                    }
                }

                // Raise error if more than one attribute is found in the group
                if found_in_group.len() > 1 {
                    return Err(ParseError::from_span(
                        start_tag_span,
                        format!(
                            "Tag '<{}>' must have only one of the attributes: {}, but found multiple: {}.",
                            tag_name,
                            allowed_group.join(", "),
                            found_in_group.join(", ")
                        ),
                    ));
                }
            }
        }
    }

    // Validate required attributes
    // Each inner list in required_attrs means "one of" (at least one must be present).
    //
    // If `c-bind` is present, we skip the required attrs check entirely, because
    // `c-bind` spreads a dictionary into attributes at runtime, so the required
    // attributes may be provided dynamically.
    // E.g. `<c-my-comp c-bind="my_dict">` could resolve to `<c-my-comp id="1" class="foo">`
    if !has_c_bind {
        for required_group in required_attrs {
            // Check if the tag contains at least one of the attributes from the required group
            let has_any_required = required_group.iter().any(|required_attr_name: &String| {
                attr_names_set.contains(required_attr_name.as_str())
            });

            // If none matched, report error.
            if !has_any_required {
                if required_group.len() == 1 {
                    return Err(ParseError::from_span(
                        start_tag_span,
                        format!(
                            "Tag '<{}>' must have a '{}' attribute.",
                            tag_name, required_group[0]
                        ),
                    ));
                } else {
                    let options = required_group.join("', '");
                    return Err(ParseError::from_span(
                        start_tag_span,
                        format!(
                            "Tag '<{}>' must have one of the following attributes: '{}'.",
                            tag_name, options
                        ),
                    ));
                }
            }
        }
    }

    Ok(())
}

/// Validate that a tag does not have duplicate attributes or conflicting c-* and non-c-* variants.
///
/// **Case 1: Duplicate attributes**
///
/// A tag cannot have multiple attributes with the same name, except `c-bind`.
/// E.g., `<div class="x" class="y">` is invalid, but `<div c-bind="..." c-bind="...">` is allowed.
///
/// **Case 2: Conflicting variants**
///
/// A tag cannot have both `c-xxx` and `xxx` variants, except `c-bind`.
/// E.g., `<div class="x" c-class="y">` is invalid, but `<div c-bind="..." bind="...">` is allowed.
///
/// **Case 3: Control flow attribute conflicts**
///
/// A tag cannot have multiple attributes from the same control flow group:
/// - `[c-if, c-elif, c-else]` - only one allowed
/// - `[c-for, c-empty]` - only one allowed
///
/// However, attributes from different groups can coexist (e.g., `c-if` and `c-for` together is allowed).
///
/// **Case 4: Control flow priorities conflicts**
///
/// If a single tag uses attributes from several control flow group (e.g. IF and FOR),
/// then only the group with the highest priority can be non-first.
///
/// E.g. IF has higher priority over FOR, so for IF we can use also `c-elif`, `c-else`,
/// while from the FOR group we MUST use only `c-for`.
/// - ✅ <div c-if="x" c-for="y">
/// - ✅ <div c-elif="x" c-for="y">
/// - ✅ <div c-else="x" c-for="y">
///
/// - ❌ <div c-if="x" c-empty="y">
/// - ❌ <div c-elif="x" c-empty="y">
/// - ❌ <div c-else="x" c-empty="y">
///
/// **Errors**
///
/// - If duplicate attribute names are found (except c-bind)
/// - If both `c-xxx` and `xxx` variants are found (except c-bind)
/// - If multiple control flow attributes from the same group are found
fn validate_attribute_conflicts(node: &Node) -> Result<(), ParseError> {
    let attrs = node.attrs();

    // Track seen attribute base names (for non-c-* attrs, use the name as-is;
    // for c-* attrs, use the name without the "c-" prefix, except c-bind)
    let mut seen_base_names = HashSet::new();
    // Track full attribute names for duplicate detection (except c-bind)
    let mut seen_full_names = HashSet::new();

    // Track control flow attributes - Group name -> (group_index, attr_name, is_first_item, attr_span)
    let mut seen_control_flow_groups: HashMap<String, (usize, String, bool, pest::Span)> =
        HashMap::new();

    for attr in attrs {
        let attr_name = &attr.key.content;

        // c-bind are special case, because they get spread into other attributes.
        if attr_name == "c-bind" {
            continue;
        }

        // Case 1: Check for duplicate attribute names
        // E.g. `<div class="x" class="y">` is invalid.
        if !seen_full_names.insert(attr_name.clone()) {
            return Err(ParseError::from_span(
                attr.token.as_span().unwrap(),
                format!(
                    "Duplicate attribute '{}' found. Each attribute name can only appear once (except 'c-bind').",
                    attr_name
                ),
            ));
        }

        // Case 2: Check for conflicting c-* and non-c-* variants,
        // e.g. `<div class="x" c-class="y">` is invalid.
        let base_name = if attr_name.starts_with("c-") {
            // This is a c-* attribute - use the base name (without "c-" prefix)
            &attr_name[2..]
        } else {
            // This is a non-c-* attribute - use the name as-is
            attr_name
        };

        let base_name_already_present = !seen_base_names.insert(base_name.to_string());
        if base_name_already_present {
            return Err(ParseError::from_span(
                attr.token.as_span().unwrap(),
                format!(
                    "Cannot have both '{}' and 'c-{}' attributes on the same tag (except 'c-bind').",
                    attr_name, attr_name
                ),
            ));
        }

        // Case 3: Check for control flow attribute conflicts
        //
        // Multiple attrs from same group is invalid:
        // - ❌ <div c-if="x" c-elif="y">
        // - ❌ <div c-if="x" c-else>
        // - ❌ <div c-elif="x" c-else>
        // - ❌ <div c-for="x" c-empty>
        //
        // Multiple attrs from different groups is valid:
        // - ✅ <div c-if="x" c-for="y">
        for (group_index, group) in CONTROL_FLOW_GROUPS.iter().enumerate() {
            if !group.contains(&attr_name.as_str()) {
                continue;
            }

            // Each kind of control flow (IF, FOR) is defined as a group of tags that belong to the same group.
            // We use the first item from the group's list as group names (e.g. "c-if", "c-for").
            let group_name = group[0].to_string();

            // Check if we've already seen another attribute from this group.
            // E.g. `<div c-if="x" c-elif="y">` is invalid.
            if seen_control_flow_groups.contains_key(&group_name) {
                // We've already seen an attribute from this group.
                let (_, prev_attr, _, _) = seen_control_flow_groups.get(&group_name).unwrap();
                return Err(ParseError::from_span(
                    attr.token.as_span().unwrap(),
                    format!(
                        "Cannot have both '{}' and '{}' attributes on the same tag. Only one control flow attribute from the group [{}] is allowed.",
                        prev_attr,
                        attr_name,
                        group.join(", ")
                    ),
                ));
            }

            let is_first_item = attr_name == group[0];
            let attr_span = attr.token.as_span().unwrap();
            seen_control_flow_groups.insert(
                group_name,
                (group_index, attr_name.clone(), is_first_item, attr_span),
            );

            // Found the group that matches current attribute, no need to check
            // other groups.
            break;
        }
    }

    // Case 4: Check for control flow priorities conflicts
    //
    // If a single tag uses attributes from several control flow group (e.g. IF and FOR),
    // then only the group with the highest priority can be non-first.
    //
    // E.g. IF has higher priority over FOR, so for IF we can use also `c-elif`, `c-else`,
    // while from the FOR group we MUST use only `c-for`.
    // - ✅ <div c-if="x" c-for="y">
    // - ✅ <div c-elif="x" c-for="y">
    // - ✅ <div c-else="x" c-for="y">
    //
    // - ❌ <div c-if="x" c-empty="y">
    // - ❌ <div c-elif="x" c-empty="y">
    // - ❌ <div c-else="x" c-empty="y">
    //
    // We can't mix IF with EMPTY, because `<c-empty>` would be nested
    // inside <c-if>/<c-elif>/<c-else>, and so would no longer have access to its <c-for>
    // (which is expected to come before <c-empty>).
    //
    // Only check if we have multiple control flow groups
    if seen_control_flow_groups.len() > 1 {
        // Sort by group_index (priority) from 0 (highest) to up
        let mut sorted_groups: Vec<(usize, String, bool, pest::Span)> =
            seen_control_flow_groups.into_values().collect();
        sorted_groups.sort_by_key(|(group_index, _, _, _)| *group_index);

        // Take the first entry (highest priority group)
        let (_, first_attr, _, _) = &sorted_groups[0];

        // Check the remainder - all lower priority groups must use first items
        // At this point we know where is multiple attributes from multiple groups.
        // We also know that there CAN'T be multiple attributes from the SAME group.
        // So all items in `sorted_groups[1..]` will have different group_index. And this group_index
        // will be go higher, because we've already sorted the list by group_index.
        for (_, attr_name, is_first_item, attr_span) in &sorted_groups[1..] {
            if !is_first_item {
                return Err(ParseError::from_span(
                    *attr_span,
                    format!(
                        "Cannot have '{}' together with '{}'. '{}' has higher priority and will wrap the content before '{}'.",
                        first_attr,
                        attr_name,
                        first_attr,
                        attr_name,
                    ),
                ));
            }
        }
    }

    Ok(())
}

/// Validate that there are no duplicate `<c-fill>` names within a component node.
///
/// For `<c-fill>` tags, we check both "name" and "c-name" attributes:
/// - Multiple `<c-fill>` tags with the same `name` value → error
/// - Multiple `<c-fill>` tags with the same `c-name` value → error
/// - NOTE: We cannot compare across "name" and "c-name" attributes
///
/// This validation applies only to component Nodes with body (e.g. `<c-component>` or `<c-MyComp>`).
///
/// `<c-fill>` tags may be nested inside control flow nodes (e.g. `<c-if>/<c-elif>/<c-else>` and `<c-for>/<c-empty>`),
/// so first we need to extract them all recursively from the body.
///
/// **Slot Validation:**
/// - If no `<c-fill>` nodes are found but body has meaningful content, it's treated as the "default" slot
/// - Validates against slot rules (allowed_slots and required_slots)
///
/// **Errors**
///
/// - If duplicate `name` values are found
/// - If duplicate `c-name` values are found
/// - If slot name is not allowed (only when name value came from `name` attr, not dynamic `c-name`)
/// - If required slots are missing (only when no `<c-fill>` tags with `c-name` or `c-bind` attrs are present)
/// - If default slot is used but "default" slot name is not allowed
fn validate_fill_names(
    node: &Node,
    fill_nodes: &[FillNodeInfo],
    context: &ParserContext,
) -> Result<(), ParseError> {
    // Only validate component nodes with body
    let tag_name = node.tag_name();
    let is_component = tag_name == C_COMPONENT_TAG
        || (tag_name.starts_with("c-") && !RESERVED_TAG_NAMES.contains(&tag_name));

    if !is_component {
        return Ok(());
    }

    // Get slot rules for this tag (if any).
    // Even without rules, we still validate duplicates - that's always an error.
    let no_required: Vec<String> = vec![];
    let (allowed_slots, required_slots) = if let Some(builtin_rules) = TAG_ATTR_RULES.get(tag_name)
    {
        // Built-in rules for built-in tags
        (&builtin_rules.allowed_slots, &builtin_rules.required_slots)
    } else if let Some(user_rules) = context.user_rules.get(tag_name) {
        // User-defined rules for user-defined tags
        (&user_rules.allowed_slots, &user_rules.required_slots)
    } else {
        // No slot rules defined for this tag - allow any slots, require none,
        // but still check for duplicates below.
        (&None, &no_required)
    };

    let has_meaningful_content = match node {
        Node::WithBody { body, .. } => _has_fill_meaningful_content(body),
        Node::SelfClosing { .. } => false,
    };

    fn format_error(node: &Node, message: String) -> Result<(), ParseError> {
        let start_tag_token = &node.start_tag().token;
        let start_tag_span = start_tag_token.as_span().unwrap();
        Err(ParseError::from_span(start_tag_span, message.to_string()))
    }

    // Collect slot names from explicit <c-fill> tags
    let mut found_slots: HashSet<String> = HashSet::new();
    // Track the maximum possible number of unique fills at runtime.
    // Static `name` fills always count as 1. Dynamic fills (`c-name`/`c-bind`)
    // count as 1 unless inside a `<c-for>`, where they could provide unbounded fills.
    //
    // Examples:
    //   `<c-fill name="header">` => counts as 1 (static)
    //   `<c-fill c-name="slot_var">` => counts as 1 (dynamic, not in for loop)
    //   `<c-for each="s in slots"><c-fill c-name="s">` => unbounded (dynamic in for loop)
    //   `<c-for each="s in slots"><c-fill name="header">` => counts as 1 (static, even in for loop)
    //   `<c-empty><c-fill c-name="slot_var">` => counts as 1 (c-empty renders at most once)
    let mut max_possible_fills: usize = 0;
    let mut has_unbounded_dynamic_fill = false;
    // Whether any fill has a dynamic name (c-name or c-bind). When true,
    // the per-name required slot check is skipped since we can't know which
    // names the dynamic fills will resolve to at runtime.
    //
    // E.g. with `required_slots: ["default", "footer"]`:
    //   `<c-fill c-name="a"> <c-fill c-name="b">` => per-name check skipped
    //     (a and b could resolve to "default" and "footer" at runtime)
    //   `<c-fill name="default"> <c-fill name="footer">` => per-name check runs
    //     (both names are known statically)
    let mut has_any_dynamic_fill = false;

    if fill_nodes.is_empty() {
        // No explicit <c-fill> tags found
        // Check if body has meaningful content (treat as "default" slot)
        if has_meaningful_content {
            // Body has content - treat as implicit "default" slot
            found_slots.insert("default".to_string());
            max_possible_fills = 1;

            // Validate that implicit "default" slot is allowed
            if let Some(allowed_slots_list) = allowed_slots {
                if !allowed_slots_list.contains(&"default".to_string()) {
                    return format_error(
                        &node,
                        format!(
                            "Tag '<{}>' does not allow a 'default' slot, but body content was provided.",
                            tag_name
                        ),
                    );
                }
            }
        }
    } else {
        // Explicit <c-fill> tags found - validate them
        // Track identities for duplicate detection, one set per variant type
        let mut seen_static_names: HashMap<String, &Node> = HashMap::new();
        let mut seen_dynamic_names: HashMap<String, &Node> = HashMap::new();
        let mut seen_bind_tuples: HashMap<Vec<(String, String)>, &Node> = HashMap::new();

        // For overflow detection: count unique dynamic fills NOT inside any control flow tag.
        // These are fills whose identity is resolved at runtime (c-name or c-bind) and are
        // at the "top level" of the component body (not inside c-if/c-for/etc).
        let mut dynamic_fills_outside_control_flow: usize = 0;
        // Track static fill names that matched allowed_slots (for overflow remaining count)
        let mut static_fills_in_allowed: HashSet<String> = HashSet::new();

        for fill_info in fill_nodes {
            let fill_node = fill_info.node;
            let identity = _extract_fill_identity(fill_node);

            let is_dynamic = identity.is_dynamic();
            if is_dynamic {
                has_any_dynamic_fill = true;
            }

            // Validate identity and check for duplicates
            match &identity {
                FillIdentity::StaticName(name_value) => {
                    // Validate that this slot name is allowed.
                    // We can only validate static `name` attrs, not dynamic `c-name`.
                    // We skip if `allowed_slots` == None (any slot name allowed)
                    if let Some(allowed_slots_list) = allowed_slots {
                        if !allowed_slots_list.contains(name_value) {
                            return format_error(
                                fill_node,
                                format!(
                                    "Tag '<{}>' does not allow a slot named '{}'.",
                                    tag_name, name_value
                                ),
                            );
                        }
                        // Track this static fill for overflow detection
                        static_fills_in_allowed.insert(name_value.clone());
                    }

                    // Check for duplicate static name values
                    if seen_static_names.contains_key(name_value) {
                        return format_error(
                            fill_node,
                            format!(
                                "Duplicate <c-fill> with name='{}' found. Each fill name can only appear once.",
                                name_value
                            ),
                        );
                    }
                    seen_static_names.insert(name_value.clone(), fill_node);
                    found_slots.insert(name_value.clone());
                }
                FillIdentity::DynamicName(name_value) => {
                    // Check for duplicate c-name values
                    if seen_dynamic_names.contains_key(name_value) {
                        return format_error(
                            fill_node,
                            format!(
                                "Duplicate <c-fill> with c-name='{}' found. Each fill name can only appear once.",
                                name_value
                            ),
                        );
                    }
                    seen_dynamic_names.insert(name_value.clone(), fill_node);
                    found_slots.insert(name_value.clone());

                    // Track dynamic fills not inside control flow for overflow detection
                    if !fill_info.inside_control_flow {
                        dynamic_fills_outside_control_flow += 1;
                    }
                }
                FillIdentity::DynamicBind(pairs) => {
                    // Check for duplicate c-bind tuples (same ordered list of (key, value) pairs)
                    if seen_bind_tuples.contains_key(pairs) {
                        let pairs_str = pairs
                            .iter()
                            .map(|(k, v)| format!("{}=\"{}\"", k, v))
                            .collect::<Vec<_>>()
                            .join(" ");
                        return format_error(
                            fill_node,
                            format!(
                                "Duplicate <c-fill> with identical bind identity ({}) found. Each fill must have a unique identity.",
                                pairs_str
                            ),
                        );
                    }
                    seen_bind_tuples.insert(pairs.clone(), fill_node);

                    // Track dynamic fills not inside control flow for overflow detection
                    if !fill_info.inside_control_flow {
                        dynamic_fills_outside_control_flow += 1;
                    }
                }
                FillIdentity::None => {
                    // No identity attrs - skip duplicate check.
                    // Missing attrs are validated elsewhere (validate_attributes_present).
                }
            }

            // Count towards max possible fills:
            // - Static `name` fills always count as 1 (even inside for loop, the name doesn't change)
            //   E.g. `<c-for each="x in xs"><c-fill name="header">` => 1 (loop repeats same name)
            // - Dynamic fills (`c-name`/`c-bind`) inside `<c-for>` are unbounded
            //   E.g. `<c-for each="s in slots"><c-fill c-name="s">` => unbounded
            // - Dynamic fills NOT inside `<c-for>` count as 1
            //   E.g. `<c-fill c-name="slot_var">` => 1
            if is_dynamic && fill_info.inside_for_loop {
                has_unbounded_dynamic_fill = true;
            } else {
                max_possible_fills += 1;
            }
        }

        // Overflow check: if all allowed slots are statically filled and there are extra
        // dynamic fills outside of control flow, it's guaranteed to fail at runtime.
        //
        // The dynamic fill will either:
        //   - resolve to an already-filled slot name => duplicate error at runtime
        //   - resolve to a non-allowed slot name => not-allowed error at runtime
        //
        // This check explicitly excludes fills inside ANY control flow tag
        // (c-if/c-elif/c-else/c-for/c-empty) because conditional/loop branches make
        // it too complex to reason about statically.
        //
        // NOTE: A future improvement could analyze control flow branches to verify
        // that each branch doesn't exceed the allowed slot count, but this is not
        // implemented yet.
        //
        // Examples (with `allowed_slots=["h", "f"]`):
        //   `<c-fill name="h"> <c-fill name="f"> <c-fill c-name="x">` => error (0 remaining, 1 dynamic)
        //   `<c-fill name="h"> <c-fill c-name="x">` => ok (1 remaining, 1 dynamic)
        //   `<c-fill name="h"> <c-fill name="f"> <c-if ..><c-fill c-name="x"></c-if>` => ok (inside control flow)
        if let Some(allowed_slots_list) = allowed_slots {
            if dynamic_fills_outside_control_flow > 0 {
                let remaining = allowed_slots_list
                    .len()
                    .saturating_sub(static_fills_in_allowed.len());
                if dynamic_fills_outside_control_flow > remaining {
                    return format_error(
                        &node,
                        format!(
                            "Tag '<{}>' allows {} slot(s), but {} are statically filled and there are {} additional dynamic fill(s) outside control flow. \
                            The dynamic fill(s) will either duplicate an existing slot or use a non-allowed name.",
                            tag_name,
                            allowed_slots_list.len(),
                            static_fills_in_allowed.len(),
                            dynamic_fills_outside_control_flow,
                        ),
                    );
                }
            }
        }
    }

    // Validate required slots
    if !required_slots.is_empty() {
        if !has_unbounded_dynamic_fill {
            // Count check: even with dynamic fills, if the total number of possible
            // unique fills is fewer than required slots, we know it can't work.
            //
            // E.g. with `required_slots: ["default", "footer"]`:
            //   `<c-fill c-name="x">` => 1 fill < 2 required => error
            //   `<c-fill c-name="x"> <c-fill c-name="y">` => 2 fills >= 2 required => ok
            if max_possible_fills < required_slots.len() {
                return format_error(
                    &node,
                    format!(
                        "Tag '<{}>' requires {} slot(s), but only {} <c-fill> tag(s) were provided.",
                        tag_name,
                        required_slots.len(),
                        max_possible_fills,
                    ),
                );
            }

            // Per-name check: verify each required slot is present.
            // This only applies when ALL fills are static, because dynamic fills
            // (c-name/c-bind) could resolve to any name at runtime.
            //
            // E.g. with `required_slots: ["default", "footer"]`:
            //   `<c-fill name="default"> <c-fill name="header">` => "footer" missing => error
            //   `<c-fill name="default"> <c-fill c-name="x">` => skipped (x could be "footer")
            if !has_any_dynamic_fill {
                for required_slot in required_slots {
                    if !found_slots.contains(required_slot.as_str()) {
                        return format_error(
                            &node,
                            format!(
                                "Tag '<{}>' must have a slot named '{}'.",
                                tag_name, required_slot
                            ),
                        );
                    }
                }
            }
        }
    }

    Ok(())
}

/// Check if a template body has meaningful content (not empty and not just whitespace).
///
/// A body has NO meaningful content when:
/// 1. `body.elements` is empty, OR
/// 2. `body.elements` contains only a single text node that contains only whitespace.
fn _has_fill_meaningful_content(body: &Template) -> bool {
    if body.elements.is_empty() {
        return false;
    }

    // Check if it's a single text node with only whitespace
    if body.elements.len() == 1 {
        if let TemplateElement::Text(text) = &body.elements[0] {
            return !text.token.content.trim().is_empty();
        }
    }

    true
}

/// Info about a `<c-fill>` node found during extraction, including whether it's
/// nested inside a `<c-for>` loop or any control flow tag.
struct FillNodeInfo<'a> {
    node: &'a Node,
    /// Whether this fill is nested inside a `<c-for>` tag (directly or via other
    /// control flow tags). This matters for required slots validation: a dynamic
    /// fill inside a for loop could provide any number of fills at runtime.
    /// Note: `<c-empty>` does NOT count, as it renders at most once.
    ///
    /// Examples:
    /// - `<c-for each="s in slots"><c-fill c-name="s"></c-fill></c-for>` => true
    /// - `<c-if cond="x"><c-for each="s in slots"><c-fill c-name="s"></c-fill></c-for></c-if>` => true
    /// - `<c-empty><c-fill c-name="s"></c-fill></c-empty>` => false
    /// - `<c-fill c-name="s"></c-fill>` => false
    inside_for_loop: bool,
    /// Whether this fill is nested inside ANY control flow tag
    /// (`c-if/c-elif/c-else/c-for/c-empty`). Used for the overflow check:
    /// fills inside control flow are excluded from the "dynamic fills exceed
    /// remaining allowed slots" validation, because conditional/loop branches
    /// make it too complex to reason about statically.
    ///
    /// NOTE: A future improvement could analyze branches to verify that all
    /// branches provide at least the same fills, but this is not implemented yet.
    ///
    /// Examples:
    /// - `<c-if cond="x"><c-fill c-name="s"></c-fill></c-if>` => true
    /// - `<c-for each="s in slots"><c-fill c-name="s"></c-fill></c-for>` => true
    /// - `<c-fill c-name="s"></c-fill>` => false
    inside_control_flow: bool,
}

/// Recursively collect all `<c-fill>` nodes from a template body.
///
/// This searches through all elements, including those nested inside control flow nodes
/// (`<c-if>/<c-elif>/<c-else>` and `<c-for>/<c-empty>`).
///
/// Tracks two flags per fill:
/// - `inside_for_loop`: true only when inside a `<c-for>` ancestor (not `<c-empty>`)
/// - `inside_control_flow`: true when inside ANY control flow tag
///
/// Example: given this template body for `<c-my-comp>`:
/// ```html
/// <c-fill name="header">...</c-fill>
/// <c-for each="s in slots">
///   <c-fill c-name="s">...</c-fill>
/// </c-for>
/// <c-empty>
///   <c-fill name="fallback">...</c-fill>
/// </c-empty>
/// ```
/// Returns 3 FillNodeInfo entries:
/// - `name="header"` with `inside_for_loop: false, inside_control_flow: false`
/// - `c-name="s"` with `inside_for_loop: true, inside_control_flow: true`
/// - `name="fallback"` with `inside_for_loop: false, inside_control_flow: true`
fn extract_fill_nodes(
    template: &Template,
    inside_for_loop: bool,
    inside_control_flow: bool,
) -> Vec<FillNodeInfo<'_>> {
    let mut fill_nodes = Vec::new();

    for element in &template.elements {
        match element {
            TemplateElement::Node(node) => {
                let tag_name = node.tag_name();
                if tag_name == C_FILL_TAG {
                    fill_nodes.push(FillNodeInfo {
                        node,
                        inside_for_loop,
                        inside_control_flow,
                    });
                } else if CONTROL_FLOW_TAGS.contains(&tag_name) {
                    // Recursively search inside control flow nodes.
                    // Only `<c-for>` sets inside_for_loop to true.
                    // `<c-empty>` does NOT - it renders at most once.
                    // ALL control flow tags set inside_control_flow to true.
                    if let Node::WithBody { body, .. } = node {
                        let nested_inside_for = inside_for_loop || tag_name == C_FOR_TAG;
                        fill_nodes.extend(extract_fill_nodes(body, nested_inside_for, true));
                    }
                } else {
                    // NOTE: When we come across nested components or regular HTML tags,
                    // we stop the search and don't go deeper, as these are already part of the content itself,
                    // not content delimiters. So when we see a nested component or regular HTML tag,
                    // we can assume that what's inside the component is an implicit "default" slot.
                    //
                    // Of course, it could happen that there'd be both content-like tags and <c-fill> tags, e.g.
                    // ```html
                    // <c-my-comp>
                    //   <div>Hello</div>
                    //   <c-fill name="footer"> </c-fill>
                    // </c-my-comp>
                    // ```
                    // This would be invalid, and we check for it in `validate_fill_exclusivity()`.
                }
            }
            _ => {
                // Text and Expr don't contain nodes
            }
        }
    }

    fill_nodes
}

/// Extract the name from a `<c-fill>` node.
///
/// Returns `(Some(name), is_c_name, has_c_bind)` where:
/// - `Some(name)` is the name value (from either "name" or "c-name" attribute) or None if neither found.
/// - `is_c_name` indicates if it came from "c-name" (true) or "name" (false)
/// - `has_c_bind` indicates if the node has a "c-bind" attribute
///
/// Returns `None` if the node has neither "name" nor "c-name" attribute.
/// The "identity" of a `<c-fill>` node for uniqueness/duplicate checking.
///
/// Determined by walking the node's attributes right-to-left and finding the
/// rightmost `name`, `c-name`, or `c-bind` attribute.
///
/// - If rightmost is `name` -> `StaticName(value)`
/// - If rightmost is `c-name` -> `DynamicName(value)`
/// - If rightmost is `c-bind` -> collect all identity attrs (`name`/`c-name`/`c-bind`)
///   going backwards from the end, stopping at (and including) the first `name`/`c-name`.
///   If no `name`/`c-name` is found, all `c-bind` attrs are included.
///   -> `DynamicBind(ordered_pairs)`
/// - If none found -> `None`
///
/// Examples:
/// - `<c-fill c-bind="b" name="a">` -> rightmost=`name` -> `StaticName("a")`
/// - `<c-fill name="a" c-bind="b">` -> rightmost=`c-bind` -> `DynamicBind([("c-bind","b"), ("name","a")])`
/// - `<c-fill c-bind="c" name="a" c-bind="b">` -> `DynamicBind([("c-bind","b"), ("name","a")])`
/// - `<c-fill c-bind="c" c-name="a" c-bind="b">` -> `DynamicBind([("c-bind","b"), ("c-name","a")])`
/// - `<c-fill c-bind="c" c-bind="b">` -> `DynamicBind([("c-bind","b"), ("c-bind","c")])`
/// - `<c-fill c-bind="c" c-bind="b" c-name="a">` -> rightmost=`c-name` -> `DynamicName("a")`
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
enum FillIdentity {
    /// Rightmost identity attr is `name="..."` -> static slot name
    StaticName(String),
    /// Rightmost identity attr is `c-name="..."` -> dynamic slot name (variable)
    DynamicName(String),
    /// Rightmost identity attr is `c-bind="..."` -> dynamic bind(s).
    /// Contains ordered (key, value) pairs from rightmost backwards to closest
    /// `name`/`c-name` (inclusive). If no `name`/`c-name` found, all c-bind attrs included.
    DynamicBind(Vec<(String, String)>),
    /// No identity attrs at all (no name, c-name, or c-bind)
    None,
}

impl FillIdentity {
    /// Returns true if this identity is dynamic (resolved at runtime).
    fn is_dynamic(&self) -> bool {
        matches!(
            self,
            FillIdentity::DynamicName(_) | FillIdentity::DynamicBind(_)
        )
    }
}

/// Extract the identity of a `<c-fill>` node by walking its attributes right-to-left.
///
/// See [`FillIdentity`] for the full identity resolution rules.
fn _extract_fill_identity(node: &Node) -> FillIdentity {
    let attrs = node.attrs();

    // Identity attributes are: name, c-name, c-bind
    let identity_attrs: Vec<(&str, &str)> = attrs
        .iter()
        .filter_map(|attr| {
            let key = attr.key.content.as_str();
            match key {
                "name" | "c-name" | "c-bind" => {
                    let value = attr
                        .inner_value
                        .as_ref()
                        .map(|v| v.content.as_str())
                        .unwrap_or("");
                    Some((key, value))
                }
                _ => Option::None,
            }
        })
        .collect();

    if identity_attrs.is_empty() {
        return FillIdentity::None;
    }

    // Check the rightmost identity attribute
    let (rightmost_key, rightmost_value) = identity_attrs.last().unwrap();

    match *rightmost_key {
        "name" => FillIdentity::StaticName(rightmost_value.to_string()),
        "c-name" => FillIdentity::DynamicName(rightmost_value.to_string()),
        "c-bind" => {
            // Collect attrs from right to left, stopping at (and including) first name/c-name
            let mut pairs: Vec<(String, String)> = Vec::new();
            for &(key, value) in identity_attrs.iter().rev() {
                pairs.push((key.to_string(), value.to_string()));
                if key == "name" || key == "c-name" {
                    break;
                }
            }
            FillIdentity::DynamicBind(pairs)
        }
        _ => FillIdentity::None,
    }
}

/// Extract slot information from a `<c-slot>` node.
///
/// Returns `Some(StaticNamedSlot)` if:
/// - The node is a `<c-slot>` tag
/// - It has a static `name` attribute (not `c-name` or `c-bind`)
///
/// Returns `None` otherwise.
///
/// The `required` field is determined as:
/// - `Some(true)`: required (has static `required` attribute)
/// - `Some(false)`: not required (no `required`, nor `c-bind`, nor `c-required` attribute)
/// - `None`: unknown (no `required`, but has `c-bind` or `c-required` attribute)
fn extract_slot_from_node(node: &Node) -> Option<StaticNamedSlot> {
    let tag_name = node.tag_name();
    if tag_name != C_SLOT_TAG {
        return None;
    }

    let attrs = node.attrs();
    let mut name_token: Option<Token> = None;
    let mut has_required = false;
    let mut has_c_bind = false;
    let mut has_c_required = false;

    for attr in attrs {
        let attr_name = &attr.key.content;
        match attr_name.as_str() {
            "name" => {
                // Found static "name" attribute - extract the token
                if let Some(inner_value) = &attr.inner_value {
                    name_token = Some(inner_value.clone());
                }
            }
            "required" => {
                // Found "required" attribute
                has_required = true;
            }
            "c-bind" => {
                // Found "c-bind" attribute
                has_c_bind = true;
            }
            "c-required" => {
                // Found "c-required" attribute
                has_c_required = true;
            }
            _ => {}
        }
    }

    // Only create slot if we found a static "name" attribute
    let name_token = name_token?;

    // Determine required field
    let required = if has_required {
        // Explicitly required - There is `required` attribute
        Some(true)
    } else if has_c_bind || has_c_required {
        // Unknown - `required` NOT present, but `c-required` or `c-bind` may be set dynamically
        None
    } else {
        // Not required - no `required`, nor `c-required`, nor `c-bind` attribute
        Some(false)
    };

    Some(StaticNamedSlot {
        token: name_token,
        required,
    })
}

/// Validate that a node can follow the previous nodes in the template.
///
/// This checks tag ordering rules (e.g., `<c-elif>` can only follow `<c-if>`).
///
/// The control flow tags can be also replaced with Vue-like shortcut control flow ATTRIBUTES:
/// ```html
/// <c-if cond="is_visible">
///   <div>Hello</div>
/// </c-if>
/// ```
///
/// Becomes:
/// ```html
/// <div c-if="is_visible">Hello</div>
/// ```
///
/// So the validation needs to check for both the tag name and the attributes.
///
/// # Errors
/// - If the tag requires a previous tag but `template.elements` is empty
/// - If the tag requires a previous tag but `template.elements` contains no Nodes
/// - If the tag requires a previous tag but the last Node's name is not in the allowed set
///   and it neither has an attribute that matches one of the allowed attributes.
fn validate_tag_grouping(node: &Node, template: &Template) -> Result<(), ParseError> {
    let tag_name = node.tag_name();

    // If this tag has no ordering constraints, it's valid
    let Some(allowed_previous_tags) = TAG_ORDERING_RULES.get(tag_name) else {
        return Ok(());
    };

    // Get the start_tag token for error reporting
    let start_tag_token = &node.start_tag().token;
    let start_tag_span = start_tag_token.as_span().unwrap();

    // Format allowed tags for error message
    let allowed_tags_str = || -> String {
        allowed_previous_tags
            .iter()
            .map(|tag| format!("<{}>", tag))
            .collect::<Vec<String>>()
            .join(", ")
    };

    // Find the last Node in parent's template.elements (skip Text and Expr)
    // We are constructing the template as we go, so the last Node in the template will be the last FINISHED Node.
    // The Node that is being validated is NOT YET FINISHED, so it's not part of the template.
    // So the `previous_node` is practically the "previous element sibling"
    // See: https://developer.mozilla.org/en-US/docs/Web/API/Element/previousElementSibling
    let previous_node = template
        .elements
        .iter()
        .rev()
        .find_map(|elem| match elem {
            TemplateElement::Node(n) => Some(n),
            _ => None,
        })
        .ok_or_else(|| {
            // No previous node found
            ParseError::from_span(
                start_tag_span,
                format!(
                    "Tag '<{}>' must follow one of: {}. No previous tag found.",
                    tag_name,
                    allowed_tags_str()
                ),
            )
        })?;

    // We've found the previous node. Now check if it's allowed
    let prev_tag_name = previous_node.tag_name();
    let prev_tag_attr_names = previous_node
        .attrs()
        .iter()
        .map(|attr| attr.key.content.as_str())
        .collect::<Vec<&str>>();

    // For the grouping to be valid, the previous node must EITHER:
    // - Match the tag name, e.g `<c-if>`, `<c-for>`, etc.
    // - OR have an attribute that matches one of the allowed attributes for the current tag.
    //   E.g. `<div c-if="...">...</div>`
    if !allowed_previous_tags.contains(prev_tag_name)
        && !allowed_previous_tags
            .iter()
            .any(|allowed| prev_tag_attr_names.contains(allowed))
    {
        return Err(ParseError::from_span(
            start_tag_span,
            format!(
                "Tag '<{}>' must follow one of: {}. Found '<{}>' instead.",
                tag_name,
                allowed_tags_str(),
                prev_tag_name
            ),
        ));
    }

    Ok(())
}
