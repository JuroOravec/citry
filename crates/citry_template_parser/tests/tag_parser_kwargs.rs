// Tests for kwargs (key=value) attributes in HTML-like tags

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::ast::Node;
    use citry_template_parser::parser::parse_template;

    use super::common::{
        body_node, bool_attr, end_tag, node_elem, parse_first_node, self_closing_node, start_tag,
        static_attr, template, token, unquoted_attr,
    };

    #[test]
    fn test_kwarg_basic() {
        // <c-my-tag key="val"></c-my-tag>
        // 0         1         2         3
        // 0123456789012345678901234567890
        let input = r#"<c-my-tag key="val"></c-my-tag>"#;
        let actual = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<c-my-tag key="val">"#, 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![static_attr(
                    token("key", 10, 1, 11),
                    token("val", 15, 1, 16),
                )],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 20, 1, 21),
                token("c-my-tag", 22, 1, 23),
            ),
            template(vec![]),
        ))]);
        assert_eq!(actual, expected);
    }

    #[test]
    fn test_kwarg_whitespace_around_equals() {
        // HTML allows whitespace around = in attributes
        let inputs = vec![
            r#"<c-my-tag key = "val" />"#,
            r#"<c-my-tag key= "val" />"#,
            r#"<c-my-tag key ="val" />"#,
        ];

        for input in inputs {
            let result = parse_first_node(input);
            assert!(
                result.is_ok(),
                "Input should succeed (whitespace around =): {} - error: {:?}",
                input,
                result.err()
            );
        }
    }

    #[test]
    fn test_kwarg_special_chars_in_key() {
        // <c-my-tag :key="v1" .key="v2" @click.stop="handler" attr:key="val" />
        // 0         1         2         3         4         5         6
        // 0123456789012345678901234567890123456789012345678901234567890123456789
        let input = r#"<c-my-tag :key="v1" .key="v2" @click.stop="handler" attr:key="val" />"#;
        let actual = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(
                r#"<c-my-tag :key="v1" .key="v2" @click.stop="handler" attr:key="val" />"#,
                0,
                1,
                1,
            ),
            token("c-my-tag", 1, 1, 2),
            vec![
                static_attr(token(":key", 10, 1, 11), token("v1", 16, 1, 17)),
                static_attr(token(".key", 20, 1, 21), token("v2", 26, 1, 27)),
                static_attr(token("@click.stop", 30, 1, 31), token("handler", 43, 1, 44)),
                static_attr(token("attr:key", 52, 1, 53), token("val", 62, 1, 63)),
            ],
            true,
        )))]);
        assert_eq!(actual, expected);
    }

    #[test]
    fn test_kwarg_complex_key_names() {
        // These are all valid HTML attr names since brackets, parens, quotes
        // are allowed in attribute keys
        let cases = vec![
            (r#"<c-my-tag _('hello')="val" />"#, "_('hello')"),
            (r#"<c-my-tag "key"="val" />"#, "\"key\""),
            (r#"<c-my-tag key[0]="val" />"#, "key[0]"),
        ];

        for (input, expected_key) in cases {
            let node = parse_first_node(input).unwrap();
            match node {
                Node::SelfClosing { start_tag, .. } => {
                    assert_eq!(
                        start_tag.attrs[0].key.content, expected_key,
                        "For input: {}",
                        input
                    );
                    assert_eq!(
                        start_tag.attrs[0].inner_value.as_ref().unwrap().content,
                        "val"
                    );
                }
                _ => panic!("Expected Node::SelfClosing for input: {}", input),
            }
        }
    }

    #[test]
    fn test_kwarg_empty_value() {
        // <c-my-tag key="" />
        // 0         1
        // 0123456789012345678
        let input = r#"<c-my-tag key="" />"#;
        let actual = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-my-tag key="" />"#, 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![static_attr(token("key", 10, 1, 11), token("", 15, 1, 16))],
            true,
        )))]);
        assert_eq!(actual, expected);
    }

    #[test]
    fn test_kwarg_whitespace_only_value() {
        // <c-my-tag key="   " />
        // 0         1         2
        // 0123456789012345678901
        let input = r#"<c-my-tag key="   " />"#;
        let actual = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-my-tag key="   " />"#, 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![static_attr(
                token("key", 10, 1, 11),
                token("   ", 15, 1, 16),
            )],
            true,
        )))]);
        assert_eq!(actual, expected);
    }

    #[test]
    fn test_kwarg_unquoted_value() {
        // <c-my-tag key=abc />
        // 0         1
        // 01234567890123456789
        let input = "<c-my-tag key=abc />";
        let actual = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token("<c-my-tag key=abc />", 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![unquoted_attr(
                token("key", 10, 1, 11),
                token("abc", 14, 1, 15),
            )],
            true,
        )))]);
        assert_eq!(actual, expected);
    }

    #[test]
    fn test_kwarg_unquoted_value_stops_at_whitespace() {
        // <c-my-tag key=a b />
        // 0         1
        // 01234567890123456789
        let input = "<c-my-tag key=a b />";
        let actual = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token("<c-my-tag key=a b />", 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![
                unquoted_attr(token("key", 10, 1, 11), token("a", 14, 1, 15)),
                bool_attr(token("b", 16, 1, 17)),
            ],
            true,
        )))]);
        assert_eq!(actual, expected);
    }
}
