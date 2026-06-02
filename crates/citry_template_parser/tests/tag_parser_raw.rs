// Tests for raw content (<c-raw> tag)

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, body_node, end_tag, node_elem, start_tag, template, text_elem, token,
    };

    #[test]
    fn test_c_raw_tag() {
        // Input: <c-raw>{{ not parsed }} {% also not %} {# nor this #}</c-raw>
        //        0      7                                              53
        let input = r#"<c-raw>{{ not parsed }} {% also not %} {# nor this #}</c-raw>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-raw>", 0, 1, 1),
                token("c-raw", 1, 1, 2),
                vec![],
                false,
            ),
            end_tag(
                token("</c-raw>", 53, 1, 54),
                token("c-raw", 55, 1, 56),
            ),
            template(vec![text_elem(
                "{{ not parsed }} {% also not %} {# nor this #}",
                7,
                1,
                8,
            )]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_raw_self_closing() {
        // c-raw as self-closing should fail (grammar has no self-closing variant for raw)
        assert_parse_error("<c-raw />", "c-raw");
    }

    #[test]
    fn test_c_raw_with_attrs() {
        // c-raw does not allow any attributes. The grammar matches the attribute
        // (raw tags accept attrs syntactically, for error reporting), and the
        // parser rejects it via the standard attribute validation.
        assert_parse_error(
            r#"<c-raw class="foo">content</c-raw>"#,
            "Tag '<c-raw>' can only have the following attributes",
        );
    }

    #[test]
    fn test_c_raw_nested() {
        // Nested c-raw: the first </c-raw> closes the outer one,
        // leaving a stray </c-raw> which should be an error
        assert_parse_error(
            "<c-raw>outer<c-raw>inner</c-raw></c-raw>",
            "reserved and cannot be used as a regular HTML tag",
        );
    }

    #[test]
    fn test_c_raw_with_c_tags_inside() {
        // c-* tags inside c-raw are treated as raw text
        // Input: <c-raw><c-if cond="x">hello</c-if></c-raw>
        //        0      7                             34
        let input = r#"<c-raw><c-if cond="x">hello</c-if></c-raw>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-raw>", 0, 1, 1),
                token("c-raw", 1, 1, 2),
                vec![],
                false,
            ),
            end_tag(
                token("</c-raw>", 34, 1, 35),
                token("c-raw", 36, 1, 37),
            ),
            template(vec![text_elem(
                r#"<c-if cond="x">hello</c-if>"#,
                7,
                1,
                8,
            )]),
        ))]);

        assert_eq!(result, expected);
    }
}
