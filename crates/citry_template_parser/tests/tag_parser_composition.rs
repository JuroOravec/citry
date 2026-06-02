// Tests for component composition

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{
        assert_parse_error, body_node, end_tag, node_elem, self_closing_node, start_tag, template,
        text_elem, token,
    };

    #[test]
    fn test_composition() {
        // <c-outer><c-inner /></c-outer>
        // 0        9         20
        let input = r#"<c-outer><c-inner /></c-outer>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-outer>", 0, 1, 1),
                token("c-outer", 1, 1, 2),
                vec![],
                false,
            ),
            end_tag(
                token("</c-outer>", 20, 1, 21),
                token("c-outer", 22, 1, 23),
            ),
            template(vec![node_elem(self_closing_node(start_tag(
                token("<c-inner />", 9, 1, 10),
                token("c-inner", 10, 1, 11),
                vec![],
                true,
            )))]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_composition_with_mixed_content() {
        // <c-card><h1>Title</h1><p>Content</p></c-card>
        // 0       8   12   17   22  25      32  36
        let input = r#"<c-card><h1>Title</h1><p>Content</p></c-card>"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template(vec![node_elem(body_node(
            start_tag(
                token("<c-card>", 0, 1, 1),
                token("c-card", 1, 1, 2),
                vec![],
                false,
            ),
            end_tag(
                token("</c-card>", 36, 1, 37),
                token("c-card", 38, 1, 39),
            ),
            template(vec![
                node_elem(body_node(
                    start_tag(
                        token("<h1>", 8, 1, 9),
                        token("h1", 9, 1, 10),
                        vec![],
                        false,
                    ),
                    end_tag(token("</h1>", 17, 1, 18), token("h1", 19, 1, 20)),
                    template(vec![text_elem("Title", 12, 1, 13)]),
                )),
                node_elem(body_node(
                    start_tag(
                        token("<p>", 22, 1, 23),
                        token("p", 23, 1, 24),
                        vec![],
                        false,
                    ),
                    end_tag(token("</p>", 32, 1, 33), token("p", 34, 1, 35)),
                    template(vec![text_elem("Content", 25, 1, 26)]),
                )),
            ]),
        ))]);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_composition_mismatched_component_tags() {
        assert_parse_error(
            "<c-btn><c-table></c-btn></c-table>",
            "Mismatched tags",
        );
    }

    #[test]
    fn test_composition_mismatched_html_tags() {
        assert_parse_error("<a><div></a></div>", "Mismatched tags");
    }
}
