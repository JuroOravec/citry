// Tests for dynamic attributes (c-* prefix) in HTML-like tags

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        expr_attr, expr_attr_unquoted, node_elem, self_closing_node_vars, start_tag,
        template_attr, template_with_vars, token, with_used_vars,
    };

    #[test]
    fn test_c_attr_expression() {
        // <c-my-tag c-class="is_active" />
        // 0         1         2         3
        // 01234567890123456789012345678901
        let input = r#"<c-my-tag c-class="is_active" />"#;
        let result = parse_template(input, None, None).unwrap();

        let is_active_var = token("is_active", 19, 1, 20);

        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token(r#"<c-my-tag c-class="is_active" />"#, 0, 1, 1),
                    token("c-my-tag", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr(
                            token("c-class", 10, 1, 11),
                            token("is_active", 19, 1, 20),
                        ),
                        vec![is_active_var.clone()],
                    )],
                    true,
                ),
                vec![is_active_var.clone()],
            ))],
            vec![is_active_var],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_unquoted_value() {
        // Unquoted c-* attribute value should be interpreted as Expression
        // <c-my-tag c-class=is_active />
        // 0         1         2
        // 012345678901234567890123456789
        let input = "<c-my-tag c-class=is_active />";
        let result = parse_template(input, None, None).unwrap();

        let is_active_var = token("is_active", 18, 1, 19);

        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token("<c-my-tag c-class=is_active />", 0, 1, 1),
                    token("c-my-tag", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr_unquoted(
                            token("c-class", 10, 1, 11),
                            token("is_active", 18, 1, 19),
                        ),
                        vec![is_active_var.clone()],
                    )],
                    true,
                ),
                vec![is_active_var.clone()],
            ))],
            vec![is_active_var],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_attr_with_template() {
        // c-* attribute with nested template (starts/ends with HTML)
        // <c-my-tag c-title="<span>{{ name }}</span>" />
        // 0         1         2         3         4
        // 0123456789012345678901234567890123456789012345
        let input = r#"<c-my-tag c-title="<span>{{ name }}</span>" />"#;
        let result = parse_template(input, None, None).unwrap();

        let name_var = token("name", 28, 1, 29);

        let expected = template_with_vars(
            vec![node_elem(self_closing_node_vars(
                start_tag(
                    token(
                        r#"<c-my-tag c-title="<span>{{ name }}</span>" />"#,
                        0,
                        1,
                        1,
                    ),
                    token("c-my-tag", 1, 1, 2),
                    vec![with_used_vars(
                        template_attr(
                            token("c-title", 10, 1, 11),
                            token("<span>{{ name }}</span>", 19, 1, 20),
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
}
