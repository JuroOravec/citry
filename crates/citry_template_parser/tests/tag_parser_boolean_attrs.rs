// Tests for positional args / boolean attributes in HTML-like tags

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{body_node, bool_attr, end_tag, node_elem, start_tag, template, token};

    #[test]
    fn test_positional_args_not_supported() {
        // In the new HTML syntax, positional args (bare values without keys) are not supported
        // All attributes must be key=value pairs or boolean attributes
        let inputs = vec![
            "<c-my-tag value></c-my-tag>", // Boolean attr is OK
            "<c-my-tag value />",          // Boolean attr self-closing is OK
        ];

        // These should parse successfully as boolean attributes
        for input in inputs {
            let result = parse_template(input, None, None);
            assert!(
                result.is_ok(),
                "Input should succeed (boolean attr): {} - error: {:?}",
                input,
                result.err()
            );
        }
    }

    #[test]
    fn test_boolean_attr_numeric() {
        // Numeric-looking text is still a valid attr name (no = sign, so it's boolean)
        // <c-my-tag 123></c-my-tag>
        // 0         1         2
        // 0123456789012345678901234
        let input = "<c-my-tag 123></c-my-tag>";
        let result = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-my-tag 123>", 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![bool_attr(token("123", 10, 1, 11))],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 14, 1, 15),
                token("c-my-tag", 16, 1, 17),
            ),
            template(vec![]),
        ))]);
        assert_eq!(result, expected);
    }

    #[test]
    fn test_boolean_attr_quoted() {
        // Quoted strings are valid attr names (Chrome allows this)
        // <c-my-tag "hello"></c-my-tag>
        // 0         1         2
        // 0123456789012345678901234567890
        let input = r#"<c-my-tag "hello"></c-my-tag>"#;
        let result = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<c-my-tag "hello">"#, 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![bool_attr(token(r#""hello""#, 10, 1, 11))],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 18, 1, 19),
                token("c-my-tag", 20, 1, 21),
            ),
            template(vec![]),
        ))]);
        assert_eq!(result, expected);
    }

    #[test]
    fn test_boolean_attr_single_quoted() {
        // Single-quoted strings are valid attr names
        // <c-my-tag 'hello'></c-my-tag>
        // 0         1         2
        // 0123456789012345678901234567890
        let input = "<c-my-tag 'hello'></c-my-tag>";
        let result = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-my-tag 'hello'>", 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![bool_attr(token("'hello'", 10, 1, 11))],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 18, 1, 19),
                token("c-my-tag", 20, 1, 21),
            ),
            template(vec![]),
        ))]);
        assert_eq!(result, expected);
    }

    #[test]
    fn test_boolean_attr_brackets() {
        // Brackets are valid in attr names (Angular-style binding syntax)
        // <c-my-tag [123]></c-my-tag>
        // 0         1         2
        // 012345678901234567890123456
        let input = "<c-my-tag [123]></c-my-tag>";
        let result = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-my-tag [123]>", 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![bool_attr(token("[123]", 10, 1, 11))],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 16, 1, 17),
                token("c-my-tag", 18, 1, 19),
            ),
            template(vec![]),
        ))]);
        assert_eq!(result, expected);
    }

    #[test]
    fn test_boolean_attr_parens() {
        // Parentheses are valid in attr names (Angular-style event binding)
        // <c-my-tag (click)></c-my-tag>
        // 0         1         2
        // 0123456789012345678901234567890
        let input = "<c-my-tag (click)></c-my-tag>";
        let result = parse_template(input, None, None).unwrap();
        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-my-tag (click)>", 0, 1, 1),
                token("c-my-tag", 1, 1, 2),
                vec![bool_attr(token("(click)", 10, 1, 11))],
                false,
            ),
            end_tag(
                token("</c-my-tag>", 18, 1, 19),
                token("c-my-tag", 20, 1, 21),
            ),
            template(vec![]),
        ))]);
        assert_eq!(result, expected);
    }
}
