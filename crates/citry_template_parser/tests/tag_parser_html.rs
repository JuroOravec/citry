// Tests for regular HTML tags

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        body_node, body_node_full, end_tag, expr_attr, node_elem, self_closing_node, start_tag,
        template, template_attr, template_with_vars, token, with_used_vars,
    };

    #[test]
    fn test_html_tag_basic() {
        // Input: <div></div>
        //        01234567890
        let input = "<div></div>";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<div>", 0, 1, 1),
                token("div", 1, 1, 2),
                vec![],
                false,
            ),
            end_tag(token("</div>", 5, 1, 6), token("div", 7, 1, 8)),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_html_void_element() {
        // Void elements like <br>, <img>, <input> don't need closing tags
        // Input: <br>
        //        0123
        let input = "<br>";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token("<br>", 0, 1, 1),
            token("br", 1, 1, 2),
            vec![],
            false,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_html_void_element_self_closing() {
        // Input: <br />
        //        012345
        let input = "<br />";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token("<br />", 0, 1, 1),
            token("br", 1, 1, 2),
            vec![],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_html_non_void_self_closing() {
        // Non-void elements can be self-closing (like JSX)
        // Input: <div/>
        //        012345
        let input = "<div/>";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token("<div/>", 0, 1, 1),
            token("div", 1, 1, 2),
            vec![],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_html_tag_with_c_attrs() {
        // Regular HTML tags can have c-* attributes
        // Input: <div c-class="active"></div>
        //        0         1         2
        //        0123456789012345678901234567
        let input = r#"<div c-class="active"></div>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![node_elem(body_node_full(
                start_tag(
                    token(r#"<div c-class="active">"#, 0, 1, 1),
                    token("div", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr(token("c-class", 5, 1, 6), token("active", 14, 1, 15)),
                        vec![token("active", 14, 1, 15)],
                    )],
                    false,
                ),
                end_tag(token("</div>", 22, 1, 23), token("div", 24, 1, 25)),
                template(vec![]),
                vec![token("active", 14, 1, 15)],
                vec![],
                vec![],
                false,
            ))],
            vec![token("active", 14, 1, 15)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_html_tag_with_c_bind() {
        // Input: <div c-bind="props"></div>
        //        0         1         2
        //        01234567890123456789012345
        let input = r#"<div c-bind="props"></div>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![node_elem(body_node_full(
                start_tag(
                    token(r#"<div c-bind="props">"#, 0, 1, 1),
                    token("div", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr(token("c-bind", 5, 1, 6), token("props", 13, 1, 14)),
                        vec![token("props", 13, 1, 14)],
                    )],
                    false,
                ),
                end_tag(token("</div>", 20, 1, 21), token("div", 22, 1, 23)),
                template(vec![]),
                vec![token("props", 13, 1, 14)],
                vec![],
                vec![],
                false,
            ))],
            vec![token("props", 13, 1, 14)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_html_tag_with_nested_template() {
        // Input: <div c-title="<span>Hi</span>"></div>
        //        0         1         2         3
        //        0123456789012345678901234567890123456
        let input = r#"<div c-title="<span>Hi</span>"></div>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<div c-title="<span>Hi</span>">"#, 0, 1, 1),
                token("div", 1, 1, 2),
                vec![template_attr(
                    token("c-title", 5, 1, 6),
                    token("<span>Hi</span>", 14, 1, 15),
                )],
                false,
            ),
            end_tag(token("</div>", 31, 1, 32), token("div", 33, 1, 34)),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }
}
