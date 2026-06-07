// Tests for spreads (c-bind) in HTML-like tags

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, expr_attr, expr_attr_unquoted, node_elem, self_closing_node_vars,
        start_tag, static_attr, template_with_vars, token, with_used_vars,
    };

    #[test]
    fn test_c_bind_spread() {
        // In Citry, spreads are done with c-bind (similar to Vue's v-bind)
        // <c-my-tag c-bind="my_dict" />
        // 0         1         2
        // 01234567890123456789012345678
        let input = r#"<c-my-tag c-bind="my_dict" />"#;
        let result = parse_template(input, None, None).unwrap();
        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token(r#"<c-my-tag c-bind="my_dict" />"#, 0, 1, 1),
                    token("c-my-tag", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr(token("c-bind", 10, 1, 11), token("my_dict", 18, 1, 19)),
                        vec![token("my_dict", 18, 1, 19)],
                    )],
                    true,
                ),
                vec![token("my_dict", 18, 1, 19)],
            ))],
            vec![token("my_dict", 18, 1, 19)],
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_bind_with_other_attrs() {
        // <c-my-tag key1="val1" c-bind="my_dict" key2="val2" />
        // 0         1         2         3         4         5
        // 01234567890123456789012345678901234567890123456789012
        let input = r#"<c-my-tag key1="val1" c-bind="my_dict" key2="val2" />"#;
        let result = parse_template(input, None, None).unwrap();
        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token(
                        r#"<c-my-tag key1="val1" c-bind="my_dict" key2="val2" />"#,
                        0,
                        1,
                        1,
                    ),
                    token("c-my-tag", 1, 1, 2),
                    vec![
                        static_attr(token("key1", 10, 1, 11), token("val1", 16, 1, 17)),
                        with_used_vars(
                            expr_attr(token("c-bind", 22, 1, 23), token("my_dict", 30, 1, 31)),
                            vec![token("my_dict", 30, 1, 31)],
                        ),
                        static_attr(token("key2", 39, 1, 40), token("val2", 45, 1, 46)),
                    ],
                    true,
                ),
                vec![token("my_dict", 30, 1, 31)],
            ))],
            vec![token("my_dict", 30, 1, 31)],
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_multiple_c_bind() {
        // <c-my-tag c-bind="dict1" key="val" c-bind="dict2" />
        // 0         1         2         3         4         5
        // 0123456789012345678901234567890123456789012345678901
        let input = r#"<c-my-tag c-bind="dict1" key="val" c-bind="dict2" />"#;
        let result = parse_template(input, None, None).unwrap();
        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token(
                        r#"<c-my-tag c-bind="dict1" key="val" c-bind="dict2" />"#,
                        0,
                        1,
                        1,
                    ),
                    token("c-my-tag", 1, 1, 2),
                    vec![
                        with_used_vars(
                            expr_attr(token("c-bind", 10, 1, 11), token("dict1", 18, 1, 19)),
                            vec![token("dict1", 18, 1, 19)],
                        ),
                        static_attr(token("key", 25, 1, 26), token("val", 30, 1, 31)),
                        with_used_vars(
                            expr_attr(token("c-bind", 35, 1, 36), token("dict2", 43, 1, 44)),
                            vec![token("dict2", 43, 1, 44)],
                        ),
                    ],
                    true,
                ),
                vec![token("dict1", 18, 1, 19), token("dict2", 43, 1, 44)],
            ))],
            vec![token("dict1", 18, 1, 19), token("dict2", 43, 1, 44)],
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_multiple_c_bind_same_value() {
        // Multiple c-bind with the same value on the same tag should be allowed,
        // because each c-bind spreads the dict at its position among the attrs.
        // <c-my-tag c-bind="my_dict" key="val" c-bind="my_dict" />
        // 0         1         2         3         4         5
        // 01234567890123456789012345678901234567890123456789012345
        let input = r#"<c-my-tag c-bind="my_dict" key="val" c-bind="my_dict" />"#;
        let result = parse_template(input, None, None).unwrap();
        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token(
                        r#"<c-my-tag c-bind="my_dict" key="val" c-bind="my_dict" />"#,
                        0,
                        1,
                        1,
                    ),
                    token("c-my-tag", 1, 1, 2),
                    vec![
                        with_used_vars(
                            expr_attr(token("c-bind", 10, 1, 11), token("my_dict", 18, 1, 19)),
                            vec![token("my_dict", 18, 1, 19)],
                        ),
                        static_attr(token("key", 27, 1, 28), token("val", 32, 1, 33)),
                        with_used_vars(
                            expr_attr(token("c-bind", 37, 1, 38), token("my_dict", 45, 1, 46)),
                            vec![token("my_dict", 45, 1, 46)],
                        ),
                    ],
                    true,
                ),
                vec![token("my_dict", 18, 1, 19), token("my_dict", 45, 1, 46)],
            ))],
            vec![token("my_dict", 18, 1, 19), token("my_dict", 45, 1, 46)],
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_bind_no_value() {
        // c-bind as boolean attr (no value) should fail - c-bind must have a non-empty value
        assert_parse_error("<c-my-tag c-bind />", "must have a non-empty value");
    }

    #[test]
    fn test_c_bind_empty_value() {
        // c-bind with empty string value should fail
        assert_parse_error(r#"<c-my-tag c-bind="" />"#, "must have a non-empty value");
    }

    #[test]
    fn test_c_bind_whitespace_value() {
        // c-bind with whitespace-only value should fail
        assert_parse_error(
            r#"<c-my-tag c-bind="   " />"#,
            "must have a non-empty value",
        );
    }

    #[test]
    fn test_c_bind_unquoted_value() {
        // c-bind with unquoted value
        // <c-my-tag c-bind=my_dict />
        // 0         1         2
        // 012345678901234567890123456
        let input = "<c-my-tag c-bind=my_dict />";
        let result = parse_template(input, None, None).unwrap();
        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token("<c-my-tag c-bind=my_dict />", 0, 1, 1),
                    token("c-my-tag", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr_unquoted(token("c-bind", 10, 1, 11), token("my_dict", 17, 1, 18)),
                        vec![token("my_dict", 17, 1, 18)],
                    )],
                    true,
                ),
                vec![token("my_dict", 17, 1, 18)],
            ))],
            vec![token("my_dict", 17, 1, 18)],
        );
        assert_eq!(result, expected);
    }
}
