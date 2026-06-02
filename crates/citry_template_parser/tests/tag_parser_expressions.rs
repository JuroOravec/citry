// Tests for expressions ({{ ... }})

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::parser::parse_template;

    use super::common::{expr_elem, template_with_vars, text_elem, token};

    #[test]
    fn test_expression_in_text() {
        // Input: "Hello {{ name }}!"
        //         0123456789012345678
        //         H e l l o   { {   n a m e   } } !
        //         0 1 2 3 4 5 6 7 8 9 . . . . . . 16
        let input = "Hello {{ name }}!";
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![
                text_elem("Hello ", 0, 1, 1),
                expr_elem(
                    token("{{ name }}", 6, 1, 7),
                    token("name ", 9, 1, 10),
                    vec![token("name", 9, 1, 10)],
                ),
                text_elem("!", 16, 1, 17),
            ],
            vec![token("name", 9, 1, 10)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_expression_complex() {
        // Input: "{{ items[0].name.upper() }}"
        //         0123456789...
        //         { {   i t e m s [ 0 ] . n  a  m  e  .  u  p  p  e  r  (  )     }  }
        //         0 1 2 3 4 5 6 7 8 9 . 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26
        let input = "{{ items[0].name.upper() }}";
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![expr_elem(
                token("{{ items[0].name.upper() }}", 0, 1, 1),
                token("items[0].name.upper() ", 3, 1, 4),
                vec![token("items", 3, 1, 4)],
            )],
            vec![token("items", 3, 1, 4)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_expression_string_with_closing_braces() {
        // Strings containing }} should not break out of the expression
        let inputs = vec![
            r#"{{ "hello }}" }}"#,
            r#"{{ 'hello }}' }}"#,
            r#"{{ """}}""" }}"#,
            r#"{{ '''}}''' }}"#,
        ];

        for input in inputs {
            let result = parse_template(input, None, None);
            assert!(
                result.is_ok(),
                "Expression with }} in string should work: {} - error: {:?}",
                input,
                result.err()
            );
        }
    }

    #[test]
    fn test_expression_func_call() {
        // Input: "{{ len(items) }}"
        //         { {   l e n ( i t  e  m  s  )     }  }
        //         0 1 2 3 4 5 6 7 8  9  10 11 12 13 14 15
        let input = "{{ len(items) }}";
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![expr_elem(
                token("{{ len(items) }}", 0, 1, 1),
                token("len(items) ", 3, 1, 4),
                vec![token("len", 3, 1, 4), token("items", 7, 1, 8)],
            )],
            vec![token("len", 3, 1, 4), token("items", 7, 1, 8)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_expression_list_comprehension() {
        // Input: "{{ [x for x in items] }}"
        //         { {   [ x   f o r   x     i  n     i  t  e  m  s  ]     }  }
        //         0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23
        let input = "{{ [x for x in items] }}";
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![expr_elem(
                token("{{ [x for x in items] }}", 0, 1, 1),
                token("[x for x in items] ", 3, 1, 4),
                vec![token("items", 15, 1, 16)],
            )],
            vec![token("items", 15, 1, 16)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_expression_arithmetic() {
        // Input: "{{ a + b * c }}"
        //         { {   a   +   b   *   c     }  }
        //         0 1 2 3 4 5 6 7 8 9 10 11 12 13 14
        let input = "{{ a + b * c }}";
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![expr_elem(
                token("{{ a + b * c }}", 0, 1, 1),
                token("a + b * c ", 3, 1, 4),
                vec![
                    token("a", 3, 1, 4),
                    token("b", 7, 1, 8),
                    token("c", 11, 1, 12),
                ],
            )],
            vec![
                token("a", 3, 1, 4),
                token("b", 7, 1, 8),
                token("c", 11, 1, 12),
            ],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_expression_string_ops() {
        // Input: {{ "hello" + " " + name }}
        //        { {   "  h  e  l  l  o  "     +     "     "     +     n  a  m  e     }  }
        //        0 1 2 3  4  5  6  7  8  9  10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25
        let input = r#"{{ "hello" + " " + name }}"#;
        let result = parse_template(input, None, None).unwrap();

        let expected = template_with_vars(
            vec![expr_elem(
                token(r#"{{ "hello" + " " + name }}"#, 0, 1, 1),
                token(r#""hello" + " " + name "#, 3, 1, 4),
                vec![token("name", 19, 1, 20)],
            )],
            vec![token("name", 19, 1, 20)],
        );

        assert_eq!(result, expected);
    }

    #[test]
    fn test_expression_data_types() {
        let inputs = vec![
            "{{ [1, 2] }}",       // list
            r#"{{ {"a": 1} }}"#,  // dict
            "{{ {1, 2} }}",       // set
            "{{ 42 }}",           // int
            "{{ 3.14 }}",         // float
            "{{ 1e10 }}",         // scientific notation
            "{{ -1.2e2 }}",       // scientific notation
            "{{ float('inf') }}", // inf
            "{{ myvar }}",        // variable
        ];

        for input in inputs {
            let result = parse_template(input, None, None);
            assert!(
                result.is_ok(),
                "Expression {} should parse, got: {:?}",
                input,
                result.err()
            );
        }
    }
}
