// Tests for HTML-like template tag structure
// Opening/closing tags, self-closing tags, end tag attributes

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, body_node, end_tag, node_elem, self_closing_node, start_tag,
        static_attr, template, token,
    };

    #[test]
    fn test_unclosed_tag_errors() {
        // Unclosed tags should produce an error
        assert_parse_error("<c-my-tag>", "error");
        assert_parse_error("<c-my-tag attr=\"val\">", "error");
        assert_parse_error("<div><c-my-tag></div>", "error");
    }

    #[test]
    fn test_tag_with_close_tag() {
        // Input: <c-my-tag></c-my-tag>
        //        0123456789012345678901
        let input = "<c-my-tag></c-my-tag>";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-my-tag>", 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 10, 1, 11),
                token("c-my-tag", 12, 1, 13),
            ),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_tag_with_close_tag_and_attrs() {
        // Input: <c-my-tag class="foo"></c-my-tag>
        //        0         1         2         3
        //        0123456789012345678901234567890123
        let input = r#"<c-my-tag class="foo"></c-my-tag>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<c-my-tag class="foo">"#, 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![static_attr(
                    token("class", 10, 1, 11),
                    token("foo", 17, 1, 18),
                )],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 22, 1, 23),
                token("c-my-tag", 24, 1, 25),
            ),
            template(vec![]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_end_tag_with_attrs_errors() {
        // End tags should not allow attributes
        assert_parse_error(
            r#"<c-my-tag></c-my-tag key="val">"#,
            "must not contain any attributes",
        );

        // End tag with boolean attribute should also fail
        assert_parse_error(
            r#"<c-my-tag></c-my-tag foo>"#,
            "must not contain any attributes",
        );

        // Same for HTML tags
        assert_parse_error(
            r#"<div></div class="foo">"#,
            "must not contain any attributes",
        );
    }

    #[test]
    fn test_self_closing_tag() {
        // Input: <c-my-tag />
        //        0123456789012
        let input = "<c-my-tag />";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token("<c-my-tag />", 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_self_closing_tag_no_space() {
        // Input: <c-my-tag/>
        //        01234567890
        let input = "<c-my-tag/>";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token("<c-my-tag/>", 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_self_closing_tag_with_attrs() {
        // Input: <c-my-tag class="foo" />
        //        0         1         2
        //        012345678901234567890123
        let input = r#"<c-my-tag class="foo" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-my-tag class="foo" />"#, 0, 1, 1),
            token("c-my-tag", 1, 1, 2),
            vec![static_attr(
                token("class", 10, 1, 11),
                token("foo", 17, 1, 18),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }
}
