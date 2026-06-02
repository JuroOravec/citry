// Tests for control flow: c-if / c-elif / c-else

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, body_node, bool_attr, end_tag, node_elem, self_closing_node,
        start_tag, static_attr, template, text_elem, token,
    };

    // =========================================================================
    // Basic c-if with body
    // =========================================================================

    #[test]
    fn test_c_if_tag() {
        // Input: <c-if cond="show"><p>Hello</p></c-if>
        //        0         1         2         3
        //        0123456789012345678901234567890123456
        let input = r#"<c-if cond="show"><p>Hello</p></c-if>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<c-if cond="show">"#, 0, 1, 1),
                token("c-if", 1, 1, 2),
                vec![static_attr(
                    token("cond", 6, 1, 7),
                    token("show", 12, 1, 13),
                )],
                false,
            ),
            end_tag(token("</c-if>", 30, 1, 31), token("c-if", 32, 1, 33)),
            template(vec![node_elem(body_node(
                start_tag(
                    token("<p>", 18, 1, 19),
                    token("p", 19, 1, 20),
                    vec![],
                    false,
                ),
                end_tag(token("</p>", 26, 1, 27), token("p", 28, 1, 29)),
                template(vec![text_elem("Hello", 21, 1, 22)]),
            ))]),
        ))]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // c-elif follows c-if
    // =========================================================================

    #[test]
    fn test_c_elif_follows_c_if() {
        // Input: <c-if cond="a"><p>A</p></c-if><c-elif cond="b"><p>B</p></c-elif>
        //        0         1         2         3         4         5         6
        //        0123456789012345678901234567890123456789012345678901234567890123
        let input = r#"<c-if cond="a"><p>A</p></c-if><c-elif cond="b"><p>B</p></c-elif>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" with <p>A</p> body
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 23, 1, 24), token("c-if", 25, 1, 26)),
                template(vec![node_elem(body_node(
                    start_tag(
                        token("<p>", 15, 1, 16),
                        token("p", 16, 1, 17),
                        vec![],
                        false,
                    ),
                    end_tag(token("</p>", 19, 1, 20), token("p", 21, 1, 22)),
                    template(vec![text_elem("A", 18, 1, 19)]),
                ))]),
            )),
            // c-elif cond="b" with <p>B</p> body
            node_elem(body_node(
                start_tag(
                    token(r#"<c-elif cond="b">"#, 30, 1, 31),
                    token("c-elif", 31, 1, 32),
                    vec![static_attr(
                        token("cond", 38, 1, 39),
                        token("b", 44, 1, 45),
                    )],
                    false,
                ),
                end_tag(
                    token("</c-elif>", 55, 1, 56),
                    token("c-elif", 57, 1, 58),
                ),
                template(vec![node_elem(body_node(
                    start_tag(
                        token("<p>", 47, 1, 48),
                        token("p", 48, 1, 49),
                        vec![],
                        false,
                    ),
                    end_tag(token("</p>", 51, 1, 52), token("p", 53, 1, 54)),
                    template(vec![text_elem("B", 50, 1, 51)]),
                ))]),
            )),
        ]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // c-elif follows c-elif
    // =========================================================================

    #[test]
    fn test_c_elif_follows_c_elif() {
        // Input: <c-if cond="a">A</c-if><c-elif cond="b">B</c-elif><c-elif cond="c">C</c-elif>
        //        0         1         2         3         4         5         6         7
        //        01234567890123456789012345678901234567890123456789012345678901234567890123456789
        let input =
            r#"<c-if cond="a">A</c-if><c-elif cond="b">B</c-elif><c-elif cond="c">C</c-elif>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" body="A"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 16, 1, 17), token("c-if", 18, 1, 19)),
                template(vec![text_elem("A", 15, 1, 16)]),
            )),
            // c-elif cond="b" body="B"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-elif cond="b">"#, 23, 1, 24),
                    token("c-elif", 24, 1, 25),
                    vec![static_attr(
                        token("cond", 31, 1, 32),
                        token("b", 37, 1, 38),
                    )],
                    false,
                ),
                end_tag(
                    token("</c-elif>", 41, 1, 42),
                    token("c-elif", 43, 1, 44),
                ),
                template(vec![text_elem("B", 40, 1, 41)]),
            )),
            // c-elif cond="c" body="C"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-elif cond="c">"#, 50, 1, 51),
                    token("c-elif", 51, 1, 52),
                    vec![static_attr(
                        token("cond", 58, 1, 59),
                        token("c", 64, 1, 65),
                    )],
                    false,
                ),
                end_tag(
                    token("</c-elif>", 68, 1, 69),
                    token("c-elif", 70, 1, 71),
                ),
                template(vec![text_elem("C", 67, 1, 68)]),
            )),
        ]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // c-else follows c-if
    // =========================================================================

    #[test]
    fn test_c_else_follows_c_if() {
        // Input: <c-if cond="a">A</c-if><c-else>B</c-else>
        //        0         1         2         3         4
        //        01234567890123456789012345678901234567890123
        let input = r#"<c-if cond="a">A</c-if><c-else>B</c-else>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" body="A"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 16, 1, 17), token("c-if", 18, 1, 19)),
                template(vec![text_elem("A", 15, 1, 16)]),
            )),
            // c-else body="B"
            node_elem(body_node(
                start_tag(
                    token("<c-else>", 23, 1, 24),
                    token("c-else", 24, 1, 25),
                    vec![],
                    false,
                ),
                end_tag(
                    token("</c-else>", 32, 1, 33),
                    token("c-else", 34, 1, 35),
                ),
                template(vec![text_elem("B", 31, 1, 32)]),
            )),
        ]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // c-else follows c-elif
    // =========================================================================

    #[test]
    fn test_c_else_follows_c_elif() {
        // Input: <c-if cond="a">A</c-if><c-elif cond="b">B</c-elif><c-else>C</c-else>
        //        0         1         2         3         4         5         6
        //        0123456789012345678901234567890123456789012345678901234567890123456789
        let input = r#"<c-if cond="a">A</c-if><c-elif cond="b">B</c-elif><c-else>C</c-else>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" body="A"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 16, 1, 17), token("c-if", 18, 1, 19)),
                template(vec![text_elem("A", 15, 1, 16)]),
            )),
            // c-elif cond="b" body="B"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-elif cond="b">"#, 23, 1, 24),
                    token("c-elif", 24, 1, 25),
                    vec![static_attr(
                        token("cond", 31, 1, 32),
                        token("b", 37, 1, 38),
                    )],
                    false,
                ),
                end_tag(
                    token("</c-elif>", 41, 1, 42),
                    token("c-elif", 43, 1, 44),
                ),
                template(vec![text_elem("B", 40, 1, 41)]),
            )),
            // c-else body="C"
            node_elem(body_node(
                start_tag(
                    token("<c-else>", 50, 1, 51),
                    token("c-else", 51, 1, 52),
                    vec![],
                    false,
                ),
                end_tag(
                    token("</c-else>", 59, 1, 60),
                    token("c-else", 61, 1, 62),
                ),
                template(vec![text_elem("C", 58, 1, 59)]),
            )),
        ]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // Error: ordering constraints
    // =========================================================================

    #[test]
    fn test_c_elif_without_c_if() {
        assert_parse_error(
            r#"<c-elif cond="a">A</c-elif>"#,
            "must follow one of",
        );
    }

    #[test]
    fn test_c_else_without_c_if() {
        assert_parse_error("<c-else>A</c-else>", "must follow one of");
    }

    #[test]
    fn test_c_elif_after_c_else() {
        assert_parse_error(
            r#"<c-if cond="a">A</c-if><c-else>B</c-else><c-elif cond="c">C</c-elif>"#,
            "must follow one of",
        );
    }

    #[test]
    fn test_c_else_after_c_else() {
        assert_parse_error(
            r#"<c-if cond="a">A</c-if><c-else>B</c-else><c-else>C</c-else>"#,
            "must follow one of",
        );
    }

    // =========================================================================
    // Error: missing cond attribute
    // =========================================================================

    #[test]
    fn test_c_if_without_cond() {
        assert_parse_error(
            "<c-if><p>Hello</p></c-if>",
            "must have a 'cond' attribute",
        );
    }

    #[test]
    fn test_c_elif_without_cond() {
        assert_parse_error(
            r#"<c-if cond="a">A</c-if><c-elif>B</c-elif>"#,
            "must have a 'cond' attribute",
        );
    }

    // =========================================================================
    // Error: extra / invalid attributes
    // =========================================================================

    #[test]
    fn test_c_if_extra_attrs() {
        assert_parse_error(
            r#"<c-if cond="x" foo="bar"><p>Hello</p></c-if>"#,
            "can only have the following attributes",
        );
    }

    #[test]
    fn test_c_elif_extra_attrs() {
        assert_parse_error(
            r#"<c-if cond="x">A</c-if><c-elif cond="x" foo="bar"><p>Hello</p></c-elif>"#,
            "can only have the following attributes",
        );
    }

    #[test]
    fn test_c_else_with_attrs() {
        assert_parse_error(
            r#"<c-if cond="x">A</c-if><c-else foo="bar">B</c-else>"#,
            "can only have the following attributes",
        );
    }

    // =========================================================================
    // Boolean cond (no value)
    // =========================================================================

    #[test]
    fn test_c_if_cond_boolean() {
        // Input: <c-if cond><p>Hello</p></c-if>
        //        0         1         2
        //        012345678901234567890123456789
        let input = "<c-if cond><p>Hello</p></c-if>";
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-if cond>", 0, 1, 1),
                token("c-if", 1, 1, 2),
                vec![bool_attr(token("cond", 6, 1, 7))],
                false,
            ),
            end_tag(token("</c-if>", 23, 1, 24), token("c-if", 25, 1, 26)),
            template(vec![node_elem(body_node(
                start_tag(
                    token("<p>", 11, 1, 12),
                    token("p", 12, 1, 13),
                    vec![],
                    false,
                ),
                end_tag(token("</p>", 19, 1, 20), token("p", 21, 1, 22)),
                template(vec![text_elem("Hello", 14, 1, 15)]),
            ))]),
        ))]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // Empty string cond
    // =========================================================================

    #[test]
    fn test_c_if_cond_empty_string() {
        // Input: <c-if cond=""><p>Hello</p></c-if>
        //        0         1         2         3
        //        0123456789012345678901234567890123
        let input = r#"<c-if cond=""><p>Hello</p></c-if>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token(r#"<c-if cond="">"#, 0, 1, 1),
                token("c-if", 1, 1, 2),
                vec![static_attr(
                    token("cond", 6, 1, 7),
                    token("", 12, 1, 13),
                )],
                false,
            ),
            end_tag(token("</c-if>", 26, 1, 27), token("c-if", 28, 1, 29)),
            template(vec![node_elem(body_node(
                start_tag(
                    token("<p>", 14, 1, 15),
                    token("p", 15, 1, 16),
                    vec![],
                    false,
                ),
                end_tag(token("</p>", 22, 1, 23), token("p", 24, 1, 25)),
                template(vec![text_elem("Hello", 17, 1, 18)]),
            ))]),
        ))]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // Various cond values (loop-based, kept as-is)
    // =========================================================================

    #[test]
    fn test_c_if_cond_various_values() {
        // Various data types as cond value should all parse
        let values = vec!["1", "myvar", "[1, 2, 3]"];

        for val in values {
            let input = format!(r#"<c-if cond="{}"><p>Hello</p></c-if>"#, val);
            let result = parse_template(&input, None, None);
            assert!(
                result.is_ok(),
                "c-if with cond=\"{}\" should succeed, got: {:?}",
                val,
                result.err()
            );
        }
    }

    // =========================================================================
    // c-elif boolean cond
    // =========================================================================

    #[test]
    fn test_c_elif_cond_boolean() {
        // Input: <c-if cond="a">A</c-if><c-elif cond><p>Hello</p></c-elif>
        //        0         1         2         3         4         5
        //        0123456789012345678901234567890123456789012345678901234567
        let input = r#"<c-if cond="a">A</c-if><c-elif cond><p>Hello</p></c-elif>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" body="A"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 16, 1, 17), token("c-if", 18, 1, 19)),
                template(vec![text_elem("A", 15, 1, 16)]),
            )),
            // c-elif cond (boolean) with <p>Hello</p> body
            node_elem(body_node(
                start_tag(
                    token("<c-elif cond>", 23, 1, 24),
                    token("c-elif", 24, 1, 25),
                    vec![bool_attr(token("cond", 31, 1, 32))],
                    false,
                ),
                end_tag(
                    token("</c-elif>", 48, 1, 49),
                    token("c-elif", 50, 1, 51),
                ),
                template(vec![node_elem(body_node(
                    start_tag(
                        token("<p>", 36, 1, 37),
                        token("p", 37, 1, 38),
                        vec![],
                        false,
                    ),
                    end_tag(token("</p>", 44, 1, 45), token("p", 46, 1, 47)),
                    template(vec![text_elem("Hello", 39, 1, 40)]),
                ))]),
            )),
        ]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // c-elif empty string cond
    // =========================================================================

    #[test]
    fn test_c_elif_cond_empty_string() {
        // Input: <c-if cond="a">A</c-if><c-elif cond=""><p>Hello</p></c-elif>
        //        0         1         2         3         4         5         6
        //        0123456789012345678901234567890123456789012345678901234567890
        let input = r#"<c-if cond="a">A</c-if><c-elif cond=""><p>Hello</p></c-elif>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" body="A"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 16, 1, 17), token("c-if", 18, 1, 19)),
                template(vec![text_elem("A", 15, 1, 16)]),
            )),
            // c-elif cond="" with <p>Hello</p> body
            node_elem(body_node(
                start_tag(
                    token(r#"<c-elif cond="">"#, 23, 1, 24),
                    token("c-elif", 24, 1, 25),
                    vec![static_attr(
                        token("cond", 31, 1, 32),
                        token("", 37, 1, 38),
                    )],
                    false,
                ),
                end_tag(
                    token("</c-elif>", 51, 1, 52),
                    token("c-elif", 53, 1, 54),
                ),
                template(vec![node_elem(body_node(
                    start_tag(
                        token("<p>", 39, 1, 40),
                        token("p", 40, 1, 41),
                        vec![],
                        false,
                    ),
                    end_tag(token("</p>", 47, 1, 48), token("p", 49, 1, 50)),
                    template(vec![text_elem("Hello", 42, 1, 43)]),
                ))]),
            )),
        ]);

        assert_eq!(result, expected);
    }

    // =========================================================================
    // c-elif various cond values (loop-based, kept as-is)
    // =========================================================================

    #[test]
    fn test_c_elif_cond_various_values() {
        // Various data types as cond value should all parse
        let values = vec!["1", "myvar", "[1, 2, 3]"];

        for val in values {
            let input = format!(
                r#"<c-if cond="a">A</c-if><c-elif cond="{}"><p>Hello</p></c-elif>"#,
                val
            );
            let result = parse_template(&input, None, None);
            assert!(
                result.is_ok(),
                "c-elif with cond=\"{}\" should succeed, got: {:?}",
                val,
                result.err()
            );
        }
    }

    // =========================================================================
    // Self-closing tags
    // =========================================================================

    #[test]
    fn test_c_if_self_closing() {
        // Input: <c-if cond="x" />
        //        0         1
        //        01234567890123456
        let input = r#"<c-if cond="x" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(self_closing_node(start_tag(
            token(r#"<c-if cond="x" />"#, 0, 1, 1),
            token("c-if", 1, 1, 2),
            vec![static_attr(
                token("cond", 6, 1, 7),
                token("x", 12, 1, 13),
            )],
            true,
        )))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_elif_self_closing() {
        // Input: <c-if cond="a">A</c-if><c-elif cond="b" />
        //        0         1         2         3         4
        //        01234567890123456789012345678901234567890123
        let input = r#"<c-if cond="a">A</c-if><c-elif cond="b" />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" body="A"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 16, 1, 17), token("c-if", 18, 1, 19)),
                template(vec![text_elem("A", 15, 1, 16)]),
            )),
            // c-elif cond="b" self-closing
            node_elem(self_closing_node(start_tag(
                token(r#"<c-elif cond="b" />"#, 23, 1, 24),
                token("c-elif", 24, 1, 25),
                vec![static_attr(
                    token("cond", 31, 1, 32),
                    token("b", 37, 1, 38),
                )],
                true,
            ))),
        ]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_c_else_self_closing() {
        // Input: <c-if cond="a">A</c-if><c-else />
        //        0         1         2         3
        //        0123456789012345678901234567890123
        let input = r#"<c-if cond="a">A</c-if><c-else />"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![
            // c-if cond="a" body="A"
            node_elem(body_node(
                start_tag(
                    token(r#"<c-if cond="a">"#, 0, 1, 1),
                    token("c-if", 1, 1, 2),
                    vec![static_attr(
                        token("cond", 6, 1, 7),
                        token("a", 12, 1, 13),
                    )],
                    false,
                ),
                end_tag(token("</c-if>", 16, 1, 17), token("c-if", 18, 1, 19)),
                template(vec![text_elem("A", 15, 1, 16)]),
            )),
            // c-else self-closing
            node_elem(self_closing_node(start_tag(
                token("<c-else />", 23, 1, 24),
                token("c-else", 24, 1, 25),
                vec![],
                true,
            ))),
        ]);

        assert_eq!(result, expected);
    }
}
