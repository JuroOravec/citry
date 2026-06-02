// Tests for comments: HTML <!-- -->, Template {# #}, and Python # comments

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::ast::{HtmlAttrKind, Node, TemplateElement};
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, body_node, body_node_full, bool_attr, comment, end_tag,
        end_tag_with_comments, expr_attr, expr_elem_with_comments, node_elem,
        self_closing_node_full, start_tag, start_tag_with_comments, static_attr, template,
        template_with_comments, template_with_comments_and_vars, text_elem, token,
        with_attr_comments, with_used_vars,
    };

    // #######################################
    // COMMENTS: HTML <!-- ... -->
    // #######################################

    #[test]
    fn test_html_comment() {
        let input = "<!-- This is a comment -->";
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_comments(
            vec![text_elem("<!-- This is a comment -->", 0, 1, 1)],
            vec![comment(
                token("<!-- This is a comment -->", 0, 1, 1),
                // Value includes BOTH surrounding spaces (symmetric).
                token(" This is a comment ", 4, 1, 5),
            )],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_html_comment_inside_tag_body() {
        let input = "<a><!-- comment --></a>";
        let result = parse_template(input, None, None).unwrap();

        let c = comment(
            token("<!-- comment -->", 3, 1, 4),
            token(" comment ", 7, 1, 8),
        );

        let expected = template_with_comments(
            vec![node_elem(body_node_full(
                start_tag(token("<a>", 0, 1, 1), token("a", 1, 1, 2), vec![], false),
                end_tag(token("</a>", 19, 1, 20), token("a", 21, 1, 22)),
                template_with_comments(
                    vec![text_elem("<!-- comment -->", 3, 1, 4)],
                    vec![c.clone()],
                ),
                vec![],
                vec![],
                vec![c.clone()],
                false,
            ))],
            vec![c],
        );

        assert_eq!(result, expected);
    }

    // TODO - ASSER FOR PROPER ERROR
    #[test]
    fn test_html_comment_inside_start_tag() {
        // HTML comment inside a start tag should fail
        let input = "<a <!-- comment --> >";
        assert_parse_error(input, "error");
    }

    // TODO - ASSER FOR PROPER ERROR
    #[test]
    fn test_html_comment_inside_end_tag() {
        // HTML comment inside an end tag should fail
        let input = "<a></a <!-- comment --> >";
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_html_comment_inside_static_attr() {
        // HTML comment syntax inside a quoted attribute is just literal text
        let input = r#"<a class="<!-- x -->"></a>"#;
        let result = parse_template(input, None, None).unwrap();

        // Not a real comment - just literal text in an attribute value
        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<a class="<!-- x -->">"#, 0, 1, 1),
                token("a", 1, 1, 2),
                vec![static_attr(
                    token("class", 3, 1, 4),
                    token("<!-- x -->", 10, 1, 11),
                )],
                false,
            ),
            end_tag(token("</a>", 22, 1, 23), token("a", 24, 1, 25)),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }

    // TODO - ASSER FOR PROPER ERROR
    #[test]
    fn test_html_comment_inside_c_attr_expression() {
        // <!-- --> inside a c-* attr starts with <! (not <[alpha]), so it's treated
        // as Expression, not Template. And "<!-- x -->" is not valid Python.
        let input = r#"<a c-class="<!-- x -->"></a>"#;
        assert_parse_error(input, "error");
    }

    // TODO - DO PROPER FULL ASSERTION HERE
    #[test]
    fn test_html_comment_inside_c_attr_template() {
        // HTML comment inside a c-* template attr with a proper tag wrapper
        let input = r#"<a c-body="<div><!-- x --></div>"></a>"#;
        let tpl = parse_template(input, None, None).unwrap();

        // Comment inside nested template propagates up
        assert_eq!(tpl.comments.len(), 1);
        assert_eq!(tpl.elements.len(), 1);
        match &tpl.elements[0] {
            TemplateElement::Node(Node::WithBody { start_tag, .. }) => {
                assert_eq!(start_tag.attrs.len(), 1);
                assert_eq!(start_tag.attrs[0].kind, HtmlAttrKind::Template);
                assert_eq!(start_tag.attrs[0].key.content, "c-body");
            }
            other => panic!("Expected Node::WithBody, got {:?}", other),
        }
    }

    #[test]
    fn test_html_comment_inside_expression() {
        // {{ <!-- x --> }} is not valid Python
        let input = "{{ <!-- x --> }}";
        assert_parse_error(input, "error");
    }

    // #######################################
    // COMMENTS: Template {# ... #}
    // #######################################

    #[test]
    fn test_template_comment() {
        // Input: {# This is a template comment #}
        //        0         1         2         3
        //        01234567890123456789012345678901
        let input = "{# This is a template comment #}";
        let result = parse_template(input, None, None).unwrap();

        let c = comment(
            token("{# This is a template comment #}", 0, 1, 1),
            token(" This is a template comment ", 2, 1, 3),
        );

        // Template comments produce no visible elements
        let expected = template_with_comments(vec![], vec![c]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_among_text() {
        // Input: Hello {# comment #} world
        //        0         1         2
        //        0123456789012345678901234
        let input = "Hello {# comment #} world";
        let result = parse_template(input, None, None).unwrap();

        let c = comment(token("{# comment #}", 6, 1, 7), token(" comment ", 8, 1, 9));

        // Template comment removed from elements; text before and after preserved
        // (the space after `#}` is now kept as the leading char of " world").
        let expected = template_with_comments(
            vec![text_elem("Hello ", 0, 1, 1), text_elem(" world", 19, 1, 20)],
            vec![c],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_among_text_in_nested_template() {
        // Deeply nested template - keep simpler assertion
        let input = r#"<a c-body="<div>Hello {# comment #} world</div>"></a>"#;
        let tpl = parse_template(input, None, None).unwrap();

        // Comment inside nested template propagates up
        assert_eq!(tpl.comments.len(), 1);
        assert_eq!(tpl.elements.len(), 1);
    }

    #[test]
    fn test_template_comment_inside_tag_body() {
        // Input: <a>{# comment #}</a>
        //        0         1
        //        01234567890123456789
        let input = "<a>{# comment #}</a>";
        let result = parse_template(input, None, None).unwrap();

        let c = comment(token("{# comment #}", 3, 1, 4), token(" comment ", 5, 1, 6));

        // Template comment in body goes only to top-level template.comments,
        // NOT into body template or node comments
        let expected = template_with_comments(
            vec![node_elem(body_node(
                start_tag(token("<a>", 0, 1, 1), token("a", 1, 1, 2), vec![], false),
                end_tag(token("</a>", 16, 1, 17), token("a", 18, 1, 19)),
                template(vec![]),
            ))],
            vec![c],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_inside_start_tag() {
        // Template comments between attrs in start tag
        // Input: <a {# comment #} class="foo"></a>
        //        0         1         2         3
        //        01234567890123456789012345678901 2
        let input = r#"<a {# comment #} class="foo"></a>"#;
        let result = parse_template(input, None, None).unwrap();

        let c = comment(token("{# comment #}", 3, 1, 4), token(" comment ", 5, 1, 6));

        let expected = template_with_comments(
            vec![node_elem(body_node_full(
                start_tag_with_comments(
                    token(r#"<a {# comment #} class="foo">"#, 0, 1, 1),
                    token("a", 1, 1, 2),
                    vec![static_attr(
                        token("class", 17, 1, 18),
                        token("foo", 24, 1, 25),
                    )],
                    false,
                    vec![c.clone()],
                ),
                end_tag(token("</a>", 29, 1, 30), token("a", 31, 1, 32)),
                template(vec![]),
                vec![],
                vec![],
                vec![c.clone()],
                false,
            ))],
            vec![c],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_inside_self_closing_tag() {
        // Template comment between attrs in a self-closing tag
        // Input: <br {# comment #} class="foo" />
        //        0         1         2         3
        //        01234567890123456789012345678901
        let input = r#"<br {# comment #} class="foo" />"#;
        let result = parse_template(input, None, None).unwrap();

        let c = comment(token("{# comment #}", 4, 1, 5), token(" comment ", 6, 1, 7));

        let expected = template_with_comments(
            vec![node_elem(self_closing_node_full(
                start_tag_with_comments(
                    token(r#"<br {# comment #} class="foo" />"#, 0, 1, 1),
                    token("br", 1, 1, 2),
                    vec![static_attr(
                        token("class", 18, 1, 19),
                        token("foo", 25, 1, 26),
                    )],
                    true,
                    vec![c.clone()],
                ),
                vec![],
                vec![],
                vec![c.clone()],
                false,
            ))],
            vec![c],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_inside_end_tag() {
        // {# comment #} in an end tag
        // Input: <a class="foo"></a {# comment #} >
        //        0         1         2         3
        //        0123456789012345678901234567890123
        let input = r#"<a class="foo"></a {# comment #} >"#;
        let result = parse_template(input, None, None).unwrap();

        let c = comment(
            token("{# comment #}", 19, 1, 20),
            token(" comment ", 21, 1, 22),
        );

        let expected = template_with_comments(
            vec![node_elem(body_node_full(
                start_tag(
                    token(r#"<a class="foo">"#, 0, 1, 1),
                    token("a", 1, 1, 2),
                    vec![static_attr(
                        token("class", 3, 1, 4),
                        token("foo", 10, 1, 11),
                    )],
                    false,
                ),
                end_tag_with_comments(
                    token("</a {# comment #} >", 15, 1, 16),
                    token("a", 17, 1, 18),
                    vec![c.clone()],
                ),
                template(vec![]),
                vec![],
                vec![],
                vec![c.clone()],
                false,
            ))],
            vec![c],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_inside_static_attr() {
        // {# ... #} inside a quoted static attribute is just literal text
        // Input: <a class="{# x #}"></a>
        //        0         1         2
        //        01234567890123456789012
        let input = r#"<a class="{# x #}"></a>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<a class="{# x #}">"#, 0, 1, 1),
                token("a", 1, 1, 2),
                vec![static_attr(
                    token("class", 3, 1, 4),
                    token("{# x #}", 10, 1, 11),
                )],
                false,
            ),
            end_tag(token("</a>", 19, 1, 20), token("a", 21, 1, 22)),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_inside_c_attr_template() {
        // {# ... #} inside a c-* template attr with a proper tag wrapper
        // Nested template - keep simpler assertion
        let input = r#"<a c-body="<div>{# comment #}</div>"></a>"#;
        let tpl = parse_template(input, None, None).unwrap();

        // Comment inside nested template propagates up
        assert_eq!(tpl.comments.len(), 1);
        assert_eq!(tpl.elements.len(), 1);
        match &tpl.elements[0] {
            TemplateElement::Node(Node::WithBody { start_tag, .. }) => {
                assert_eq!(start_tag.attrs.len(), 1);
                assert_eq!(start_tag.attrs[0].kind, HtmlAttrKind::Template);
                assert_eq!(start_tag.attrs[0].key.content, "c-body");
            }
            other => panic!("Expected Node::WithBody, got {:?}", other),
        }
    }

    // #######################################
    // COMMENTS: Python # comments
    // #######################################

    #[test]
    fn test_python_comment_not_in_text() {
        // # in plain text is just text, not a comment
        // Input: # hello
        //        0123456
        let input = "# hello";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![text_elem("# hello", 0, 1, 1)]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_python_comment_not_in_static_attr() {
        // # in a static attr value is just literal text
        // Input: <a class="# hello"></a>
        //        0         1         2
        //        01234567890123456789012
        let input = r##"<a class="# hello"></a>"##;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r##"<a class="# hello">"##, 0, 1, 1),
                token("a", 1, 1, 2),
                vec![static_attr(
                    token("class", 3, 1, 4),
                    token("# hello", 10, 1, 11),
                )],
                false,
            ),
            end_tag(token("</a>", 19, 1, 20), token("a", 21, 1, 22)),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_python_comment_inside_start_tag() {
        // `#` and `comment` in a start tag are parsed as boolean attributes, NOT as comments
        // Input: <a # comment class="foo"></a>
        //        0         1         2
        //        0123456789012345678901234567 8
        let input = r#"<a # comment class="foo"></a>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<a # comment class="foo">"#, 0, 1, 1),
                token("a", 1, 1, 2),
                vec![
                    bool_attr(token("#", 3, 1, 4)),
                    bool_attr(token("comment", 5, 1, 6)),
                    static_attr(token("class", 13, 1, 14), token("foo", 20, 1, 21)),
                ],
                false,
            ),
            end_tag(token("</a>", 25, 1, 26), token("a", 27, 1, 28)),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_python_comment_inside_end_tag() {
        // `#` in an end tag is parsed as an attribute, which is not allowed in end tags
        let input = r#"<a class="foo"></a # comment>"#;
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_python_comment_in_expression() {
        // # inside {{ }} is treated as a Python comment
        // Input: {{ x # comment }}
        //        0         1
        //        01234567890123456
        let input = "{{ x # comment }}";
        let result = parse_template(input, None, None).unwrap();

        let c = comment(token("# comment ", 5, 1, 6), token(" comment ", 6, 1, 7));

        let expected = template_with_comments_and_vars(
            vec![expr_elem_with_comments(
                token("{{ x # comment }}", 0, 1, 1),
                token("x # comment ", 3, 1, 4),
                vec![token("x", 3, 1, 4)],
                vec![c.clone()],
            )],
            vec![c],
            vec![token("x", 3, 1, 4)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_template_comment_before_expression() {
        // {# comment #} is not allowed inside {{ }}
        let input = "{{ {# before #} x }}";
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_template_comment_after_expression() {
        // {# comment #} after the python expr inside {{ }} fails
        let input = "{{ x {# after #} }}";
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_template_comment_inside_expression_fails() {
        // {# comment #} in the middle of a python expression should fail
        let input = "{{ x + {# oops #} y }}";
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_python_comment_in_c_attr_expression() {
        // # in c-* expression attr is a Python comment
        // Input: <a c-class="x # comment"></a>
        //        0         1         2
        //        01234567890123456789012345678
        let input = r#"<a c-class="x # comment"></a>"#;
        let result = parse_template(input, None, None).unwrap();

        let c = comment(token("# comment", 14, 1, 15), token(" comment", 15, 1, 16));

        let expected = template_with_comments_and_vars(
            vec![node_elem(body_node_full(
                start_tag(
                    token(r#"<a c-class="x # comment">"#, 0, 1, 1),
                    token("a", 1, 1, 2),
                    vec![with_attr_comments(
                        with_used_vars(
                            expr_attr(token("c-class", 3, 1, 4), token("x # comment", 12, 1, 13)),
                            vec![token("x", 12, 1, 13)],
                        ),
                        vec![c.clone()],
                    )],
                    false,
                ),
                end_tag(token("</a>", 25, 1, 26), token("a", 27, 1, 28)),
                template(vec![]),
                vec![token("x", 12, 1, 13)],
                vec![],
                vec![c.clone()],
                false,
            ))],
            vec![c],
            vec![token("x", 12, 1, 13)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_python_comment_not_in_c_attr_template() {
        // `# comment` inside a nested template is just plain text, not a Python comment
        // Nested template - keep simpler assertion
        let input = r#"<a c-body="<div># this is text</div>"></a>"#;
        let tpl = parse_template(input, None, None).unwrap();

        // Not a comment - just text inside the nested template
        assert!(tpl.comments.is_empty());
        assert!(tpl.used_variables.is_empty());
        assert_eq!(tpl.elements.len(), 1);
        match &tpl.elements[0] {
            TemplateElement::Node(Node::WithBody { start_tag, .. }) => {
                assert_eq!(start_tag.attrs.len(), 1);
                assert_eq!(start_tag.attrs[0].kind, HtmlAttrKind::Template);
                assert_eq!(start_tag.attrs[0].key.content, "c-body");
            }
            other => panic!("Expected Node::WithBody, got {:?}", other),
        }
    }
}
