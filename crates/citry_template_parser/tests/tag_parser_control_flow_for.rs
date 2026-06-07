// Tests for control flow: c-for / c-empty

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, body_node_full, end_tag, expr_attr, expr_elem, node_elem,
        self_closing_node_full, start_tag, static_attr, template, template_with_vars, token,
        with_used_vars,
    };

    #[test]
    fn test_c_for_tag() {
        // ---------------------------------------------------------------
        // Part 1: Basic c-for with "item in items"
        // ---------------------------------------------------------------
        // Input: <c-for each="item in items"><li>{{ item }}</li></c-for>
        //        0         1         2         3         4         5
        //        0123456789012345678901234567890123456789012345678901234567
        let input = r#"<c-for each="item in items"><li>{{ item }}</li></c-for>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![node_elem(body_node_full(
                start_tag(
                    token(r#"<c-for each="item in items">"#, 0, 1, 1),
                    token("c-for", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr(token("each", 7, 1, 8), token("item in items", 13, 1, 14)),
                        vec![token("items", 21, 1, 22)],
                    )],
                    false,
                ),
                end_tag(token("</c-for>", 47, 1, 48), token("c-for", 49, 1, 50)),
                // c-for body
                template_with_vars(
                    vec![node_elem(body_node_full(
                        start_tag(
                            token("<li>", 28, 1, 29),
                            token("li", 29, 1, 30),
                            vec![],
                            false,
                        ),
                        end_tag(token("</li>", 42, 1, 43), token("li", 44, 1, 45)),
                        // li body
                        template_with_vars(
                            vec![expr_elem(
                                token("{{ item }}", 32, 1, 33),
                                token("item ", 35, 1, 36),
                                vec![token("item", 35, 1, 36)],
                            )],
                            vec![token("item", 35, 1, 36)],
                        ),
                        // li used_variables
                        vec![token("item", 35, 1, 36)],
                        // li introduced_variables
                        vec![],
                        // li comments
                        vec![],
                        // li contains_fills
                        false,
                    ))],
                    vec![token("item", 35, 1, 36)],
                ),
                // c-for used_variables: `items` from the `each` clause (`item` is
                // introduced by the loop and removed).
                vec![token("items", 21, 1, 22)],
                // c-for introduced_variables
                vec![token("item", 13, 1, 14)],
                // c-for comments
                vec![],
                // c-for contains_fills
                false,
            ))],
            vec![token("items", 21, 1, 22)],
        );

        assert_eq!(result, expected);

        // ---------------------------------------------------------------
        // Part 2: c-for with outer_var to verify variable propagation
        // ---------------------------------------------------------------
        // Input: <c-for each="item in items"><li>{{ item }}{{ outer_var }}</li></c-for>
        //        0         1         2         3         4         5         6
        //        0123456789012345678901234567890123456789012345678901234567890123456789
        let input = r#"<c-for each="item in items"><li>{{ item }}{{ outer_var }}</li></c-for>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![node_elem(body_node_full(
                start_tag(
                    token(r#"<c-for each="item in items">"#, 0, 1, 1),
                    token("c-for", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr(token("each", 7, 1, 8), token("item in items", 13, 1, 14)),
                        vec![token("items", 21, 1, 22)],
                    )],
                    false,
                ),
                end_tag(token("</c-for>", 62, 1, 63), token("c-for", 64, 1, 65)),
                // c-for body
                template_with_vars(
                    vec![node_elem(body_node_full(
                        start_tag(
                            token("<li>", 28, 1, 29),
                            token("li", 29, 1, 30),
                            vec![],
                            false,
                        ),
                        end_tag(token("</li>", 57, 1, 58), token("li", 59, 1, 60)),
                        // li body
                        template_with_vars(
                            vec![
                                expr_elem(
                                    token("{{ item }}", 32, 1, 33),
                                    token("item ", 35, 1, 36),
                                    vec![token("item", 35, 1, 36)],
                                ),
                                expr_elem(
                                    token("{{ outer_var }}", 42, 1, 43),
                                    token("outer_var ", 45, 1, 46),
                                    vec![token("outer_var", 45, 1, 46)],
                                ),
                            ],
                            vec![token("item", 35, 1, 36), token("outer_var", 45, 1, 46)],
                        ),
                        // li used_variables
                        vec![token("item", 35, 1, 36), token("outer_var", 45, 1, 46)],
                        // li introduced_variables
                        vec![],
                        // li comments
                        vec![],
                        // li contains_fills
                        false,
                    ))],
                    vec![token("item", 35, 1, 36), token("outer_var", 45, 1, 46)],
                ),
                // c-for used_variables: outer_var (from the body) and items (from
                // the `each` clause); item is introduced by the loop and removed.
                vec![token("outer_var", 45, 1, 46), token("items", 21, 1, 22)],
                // c-for introduced_variables
                vec![token("item", 13, 1, 14)],
                // c-for comments
                vec![],
                // c-for contains_fills
                false,
            ))],
            vec![token("outer_var", 45, 1, 46), token("items", 21, 1, 22)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_empty_follows_c_for() {
        let input = r#"<c-for each="item in items"><li>{{ item }}</li></c-for><c-empty><p>No items</p></c-empty>"#;
        let template = parse_template(input, None, None).unwrap();
        assert_eq!(template.elements.len(), 2);
    }

    #[test]
    fn test_c_empty_without_c_for() {
        assert_parse_error("<c-empty><p>No items</p></c-empty>", "must follow one of");
    }

    #[test]
    fn test_c_for_without_each() {
        assert_parse_error("<c-for><li>item</li></c-for>", "'each'");
    }

    #[test]
    fn test_c_for_extra_attrs() {
        assert_parse_error(
            r#"<c-for each="x in y" foo="bar"><li>x</li></c-for>"#,
            "can only have",
        );
    }

    #[test]
    fn test_c_empty_with_attrs() {
        assert_parse_error(
            r#"<c-for each="x in y"><li>x</li></c-for><c-empty foo="bar"><p>None</p></c-empty>"#,
            "can only have",
        );
    }

    #[test]
    fn test_c_for_each_boolean() {
        assert_parse_error("<c-for each><li>item</li></c-for>", "must have a value");
    }

    #[test]
    fn test_c_for_each_empty_string() {
        assert_parse_error(
            r#"<c-for each=""><li>item</li></c-for>"#,
            "Failed to parse 'each'",
        );
    }

    #[test]
    fn test_c_for_each_whitespace_string() {
        assert_parse_error(
            r#"<c-for each="   "><li>item</li></c-for>"#,
            "Failed to parse 'each'",
        );
    }

    #[test]
    fn test_c_for_each_valid_pattern() {
        // Standard "x in y" pattern should succeed
        let input = r#"<c-for each="item in items"><li>x</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with valid each pattern should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_valid_pattern_whitespace() {
        // Standard "x in y" pattern should succeed
        let input = r#"<c-for each="  item in items  "><li>x</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with valid each pattern should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_valid_pattern_multiple_targets() {
        // Multiple targets should succeed
        let input = r#"<c-for each="  item1, item2 in items  "><li>x</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with valid each pattern should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_valid_pattern_multiple_generators() {
        // Multiple generators should succeed
        let input =
            r#"<c-for each="  item1, item2 in row in matrix for col in row"><li>x</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with valid each pattern should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_valid_pattern_multiple_generators_with_ifs() {
        // Multiple generators should succeed
        let input = r#"<c-for each="  item1, item2 in row in matrix for col in row if row.visible and col.visible"><li>x</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with valid each pattern should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_valid_pattern_multiple_generators_with_ifs_invalid() {
        // A stray `11` at the end should fail
        assert_parse_error(
            r#"<c-for each="  item1, item2 in row in matrix for col in row if row.visible and col.visible 11"><li>x</li></c-for>"#,
            "Failed to parse 'each'",
        );
    }

    #[test]
    fn test_c_for_each_python_expression_iterable() {
        // Iterable can be a Python expression (e.g. parenthesized expression)
        let input = r#"<c-for each="item in (items + other_items)"><li>{{ item }}</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with parenthesized expression iterable should succeed: {:?}",
            result.err()
        );

        // Iterable can be a literal list
        let input = r#"<c-for each="item in [1, 2, 3]"><li>{{ item }}</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with literal list iterable should succeed: {:?}",
            result.err()
        );

        // Iterable can be a literal dict (iterates over keys)
        let input = r#"<c-for each="key in {'a': 1, 'b': 2}"><li>{{ key }}</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with literal dict iterable should succeed: {:?}",
            result.err()
        );

        // Iterable can be a literal set
        let input = r#"<c-for each="item in {'x', 'y', 'z'}"><li>{{ item }}</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with literal set iterable should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_empty_targets() {
        assert_parse_error(
            r#"<c-for each=", in items"><li>x</li></c-for>"#,
            "Failed to parse 'each'",
        );
    }

    #[test]
    fn test_c_for_each_trailing_comma() {
        // Trailing comma in targets is valid in Python (tuple unpacking allows it),
        // so `x, y, in items` is equivalent to `(x, y,) in items`.
        let input = r#"<c-for each="x, y, in items"><li>x</li></c-for>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with trailing comma in targets is valid Python: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_multiline() {
        // The `each` attribute value can be a multiline string
        let input = "<c-for each=\"\n  item\n  in\n  items\n\"><li>{{ item }}</li></c-for>";
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with multiline each should succeed: {:?}",
            result.err()
        );

        // Multiline with multiple targets
        let input = "<c-for each=\"\n  key,\n  value\n  in\n  my_dict.items()\n\"><li>{{ key }}: {{ value }}</li></c-for>";
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with multiline each and multiple targets should succeed: {:?}",
            result.err()
        );

        // Multiline with Python comments on some lines
        let input = "<c-for each=\"\n  item  # loop variable\n  in\n  items  # the collection\n\"><li>{{ item }}</li></c-for>";
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with multiline each and Python comments should succeed: {:?}",
            result.err()
        );

        // Multiline with Python comments and complex expression
        let input = "<c-for each=\"\n  key, value  # unpack tuple\n  in\n  data.items()  # iterate over dict\n  if value > 0  # filter positive\n\"><li>{{ key }}</li></c-for>";
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for with multiline each, comments, and filter should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_c_for_each_invalid_patterns() {
        // These patterns are validated at the safe_eval level and should fail
        let values = vec![
            "1",         // Invalid assignment target
            "a",         // Invalid assignment target
            "[1, 2, 3]", // Not a valid for-in pattern
            "a in",      // Missing iterable
            "in b",      // Missing variable
            "a b",       // Missing 'in' keyword
            "a in b in", // Too many 'in' keywords
        ];

        for val in values {
            let input = format!(r#"<c-for each="{}"><li>x</li></c-for>"#, val);
            let result = parse_template(&input, None, None);
            assert!(result.is_err(), "c-for with each=\"{}\" should fail", val,);
        }
    }

    #[test]
    fn test_c_for_self_closing() {
        // Input: <c-for each="x in y" />
        //        0         1         2
        //        01234567890123456789012
        let input = r#"<c-for each="x in y" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![node_elem(self_closing_node_full(
                start_tag(
                    token(r#"<c-for each="x in y" />"#, 0, 1, 1),
                    token("c-for", 1, 1, 2),
                    vec![with_used_vars(
                        expr_attr(token("each", 7, 1, 8), token("x in y", 13, 1, 14)),
                        vec![token("y", 18, 1, 19)],
                    )],
                    true,
                ),
                // used_variables: `y` from the `each` clause (`x` is the loop target)
                vec![token("y", 18, 1, 19)],
                // introduced_variables
                vec![token("x", 13, 1, 14)],
                // comments
                vec![],
                // contains_fills
                false,
            ))],
            vec![token("y", 18, 1, 19)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_empty_self_closing() {
        let input = r#"<c-for each="x in y"><li>x</li></c-for><c-empty />"#;
        let template = parse_template(input, None, None).unwrap();
        assert_eq!(template.elements.len(), 2);
    }
}
