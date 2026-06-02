// Tests for nested templates in c-* attributes
// Fragment syntax, template detection, self-closing tags in templates, etc.

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, node_elem, self_closing_node, self_closing_node_vars, start_tag,
        template, template_attr, template_with_vars, token, with_used_vars,
    };

    // --- Fragment syntax <>...</> ---

    #[test]
    fn test_c_attr_template_fragment() {
        // Fragment syntax <>...</> should be detected as Template kind
        // <c-my-tag c-body="<>Hello {{ name }}</>" />
        // 0         1         2         3         4
        // 0123456789012345678901234567890123456789012
        let input = r#"<c-my-tag c-body="<>Hello {{ name }}</>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let name_var = token("name", 29, 1, 30);

        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token(
                        r#"<c-my-tag c-body="<>Hello {{ name }}</>" />"#,
                        0,
                        1,
                        1,
                    ),
                    token("c-my-tag", 1, 1, 2),
                    vec![with_used_vars(
                        template_attr(
                            token("c-body", 10, 1, 11),
                            token("<>Hello {{ name }}</>", 18, 1, 19),
                        ),
                        vec![name_var.clone()],
                    )],
                    true,
                ),
                vec![name_var.clone()],
            ))],
            vec![name_var],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_fragment_multiple_children() {
        // Fragment with multiple children
        // <c-my-tag c-body="<> <span>A</span> <span>B</span> </>" />
        // 0         1         2         3         4         5
        // 01234567890123456789012345678901234567890123456789012345678
        let input = r#"<c-my-tag c-body="<> <span>A</span> <span>B</span> </>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body="<> <span>A</span> <span>B</span> </>" />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<> <span>A</span> <span>B</span> </>", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_fragment_with_whitespace() {
        // Whitespace around fragment delimiters
        // <c-my-tag c-body=" <>Hello</> " />
        // 0         1         2         3
        // 0123456789012345678901234567890123
        let input = r#"<c-my-tag c-body=" <>Hello</> " />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body=" <>Hello</> " />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token(" <>Hello</> ", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    // --- Tightened template detection: things that should NOT be templates ---

    #[test]
    fn test_c_attr_not_template_space_after_lt() {
        // "< THIS IS TEXT >" - space after < means not a template, treated as Expression
        // which fails because < is not valid Python
        let input = r#"<c-my-tag c-x="< THIS IS TEXT >" />"#;
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_c_attr_not_template_double_angle() {
        // "<< lol >>" - second char is <, not alpha, so not a template
        let input = r#"<c-my-tag c-x="<< lol >>" />"#;
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_c_attr_not_template_spaced_angles() {
        // "< > </ >" - space between < and >, so not a template
        let input = r#"<c-my-tag c-x="< > </ >" />"#;
        assert_parse_error(input, "error");
    }

    // --- Content around nested templates ---

    #[test]
    fn test_c_attr_template_with_text_before() {
        // Text before a template tag: doesn't start with < after trim, so it's Expression
        // and will fail because it's not valid Python
        let input = r#"<c-my-tag c-body="hello <span>A</span>" />"#;
        assert_parse_error(input, "error");
    }

    #[test]
    fn test_c_attr_template_with_text_after() {
        // Text after closing tag: doesn't end with > after trim, so Expression
        let input = r#"<c-my-tag c-body="<span>A</span> world" />"#;
        assert_parse_error(input, "error");
    }

    // --- Multiple root normal tags ---

    // --- Multiple root tags in nested templates ---

    #[test]
    fn test_c_attr_template_multiple_root_tags() {
        // Multiple root tags in nested template
        // <c-my-tag c-body="<span>A</span><span>B</span>" />
        // 0         1         2         3         4
        // 01234567890123456789012345678901234567890123456789
        let input = r#"<c-my-tag c-body="<span>A</span><span>B</span>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body="<span>A</span><span>B</span>" />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<span>A</span><span>B</span>", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_different_root_tags() {
        // Different root tags in nested template
        // <c-my-tag c-body="<span>A</span><div>B</div>" />
        // 0         1         2         3         4
        // 012345678901234567890123456789012345678901234567
        let input = r#"<c-my-tag c-body="<span>A</span><div>B</div>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body="<span>A</span><div>B</div>" />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<span>A</span><div>B</div>", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_single_tag_with_whitespace() {
        // Single tag with whitespace around it should be OK
        // <c-my-tag c-body=" <span>A</span> " />
        // 0         1         2         3
        // 01234567890123456789012345678901234567
        let input = r#"<c-my-tag c-body=" <span>A</span> " />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body=" <span>A</span> " />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token(" <span>A</span> ", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_single_tag_with_text_before() {
        // Text before a tag: doesn't start with < after trim, so Expression (and likely fails)
        let input = r#"<c-my-tag c-body="hello <span>A</span>" />"#;
        assert_parse_error(input, "error");
    }

    // --- c-* component tags in nested templates ---

    #[test]
    fn test_c_attr_template_single_component() {
        // <c-my-tag c-body="<c-btn>Click</c-btn>" />
        // 0         1         2         3         4
        // 01234567890123456789012345678901234567890
        let input = r#"<c-my-tag c-body="<c-btn>Click</c-btn>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body="<c-btn>Click</c-btn>" />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<c-btn>Click</c-btn>", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_multiple_components() {
        // Multiple top-level components
        // <c-my-tag c-body="<c-a>A</c-a><c-b>B</c-b>" />
        // 0         1         2         3         4
        // 0123456789012345678901234567890123456789012345
        let input = r#"<c-my-tag c-body="<c-a>A</c-a><c-b>B</c-b>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body="<c-a>A</c-a><c-b>B</c-b>" />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<c-a>A</c-a><c-b>B</c-b>", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_component_with_whitespace() {
        // Single component with whitespace should be OK
        // <c-my-tag c-body=" <c-btn>Click</c-btn> " />
        // 0         1         2         3         4
        // 01234567890123456789012345678901234567890123
        let input = r#"<c-my-tag c-body=" <c-btn>Click</c-btn> " />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag c-body=" <c-btn>Click</c-btn> " />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token(" <c-btn>Click</c-btn> ", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_component_with_text_before() {
        // Text before component: not Template kind, fails as Expression
        let input = r#"<c-my-tag c-body="hello <c-btn>Click</c-btn>" />"#;
        assert_parse_error(input, "error");
    }

    // --- Self-closing tag in nested template ---

    #[test]
    fn test_c_attr_template_self_closing_component() {
        // Self-closing component tag in nested template
        // <c-my-tag c-body="<c-icon />" />
        // 0         1         2         3
        // 01234567890123456789012345678901
        let input = r#"<c-my-tag c-body="<c-icon />" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-my-tag c-body="<c-icon />" />"#, 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<c-icon />", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_self_closing_html() {
        // Self-closing regular HTML tag in nested template
        // <c-my-tag c-body="<div />" />
        // 0         1         2
        // 0123456789012345678901234567
        let input = r#"<c-my-tag c-body="<div />" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-my-tag c-body="<div />" />"#, 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<div />", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_self_closing_no_space() {
        // Self-closing with no space before />
        // <c-my-tag c-body="<br/>" />
        // 0         1         2
        // 012345678901234567890123456
        let input = r#"<c-my-tag c-body="<br/>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-my-tag c-body="<br/>" />"#, 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token("<br/>", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_template_self_closing_with_whitespace() {
        // Self-closing with whitespace around it
        // <c-my-tag c-body=" <c-icon /> " />
        // 0         1         2         3
        // 0123456789012345678901234567890123
        let input = r#"<c-my-tag c-body=" <c-icon /> " />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-my-tag c-body=" <c-icon /> " />"#, 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![template_attr(
                token("c-body", 10, 1, 11),
                token(" <c-icon /> ", 18, 1, 19),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }
}
