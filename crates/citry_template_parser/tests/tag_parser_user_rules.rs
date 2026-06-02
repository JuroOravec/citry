// Tests for user rules (config) - allowed/required attrs, allowed/required slots

mod common;

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::rc::Rc;

    use citry_template_parser::parser::parse_template;
    use citry_template_parser::parser_context::TagRules;

    #[test]
    fn test_user_rules_allowed_attrs() {
        // Define rules that only allow 'id' and 'class' for c-my-comp
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: Some(vec![vec!["id".to_string()], vec!["class".to_string()]]),
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Valid: only allowed attrs
        let input = r#"<c-my-comp id="1" class="foo"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Valid attrs should succeed: {:?}",
            result.err()
        );

        // Invalid: 'data' is not in allowed attrs
        let input = r#"<c-my-comp data="x"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(result.is_err(), "Invalid attr 'data' should fail");
    }

    #[test]
    fn test_user_rules_required_attrs() {
        // Define rules that require 'id' for c-my-comp
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None, // any attrs allowed
                required_attrs: vec![vec!["id".to_string()]],
                allowed_slots: None,
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Valid: required attr present
        let input = r#"<c-my-comp id="1"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "With required attr should succeed: {:?}",
            result.err()
        );

        // Invalid: required attr missing
        let input = r#"<c-my-comp class="foo"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(result.is_err(), "Missing required attr should fail");
    }

    #[test]
    fn test_user_rules_allowed_attrs_with_c_bind() {
        // c-bind always bypasses allowed_attrs - it doesn't need to be listed
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: Some(vec![vec!["id".to_string()], vec!["class".to_string()]]),
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Valid: c-bind bypasses allowed_attrs even though it's not listed
        let input = r#"<c-my-comp c-bind="my_dict"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "c-bind should bypass allowed_attrs check: {:?}",
            result.err()
        );

        // Valid: c-bind alongside other allowed attrs
        let input = r#"<c-my-comp id="1" c-bind="my_dict"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "c-bind with other allowed attrs should succeed: {:?}",
            result.err()
        );

        // Invalid: non-c-bind attrs still checked ('data' not allowed)
        let input = r#"<c-my-comp data="x" c-bind="my_dict"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Non-c-bind invalid attr should still fail even with c-bind present"
        );
    }

    #[test]
    fn test_user_rules_required_attrs_with_c_bind() {
        // c-bind bypasses required_attrs validation, because the required
        // attributes could be provided dynamically via the spread dict.
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None, // any attrs allowed
                required_attrs: vec![vec!["id".to_string()]],
                allowed_slots: None,
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Without c-bind, missing required attr fails
        let input = r#"<c-my-comp class="foo"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Missing required attr without c-bind should fail"
        );

        // With c-bind, required attr check is skipped (dict could contain 'id')
        let input = r#"<c-my-comp c-bind="my_dict"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "c-bind should bypass required_attrs check: {:?}",
            result.err()
        );

        // c-bind alongside the required attr also works
        let input = r#"<c-my-comp id="1" c-bind="extras"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "c-bind with required attr present should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_fallback() {
        // Tag without rules should allow any attributes
        let mut rules = HashMap::new();
        rules.insert(
            "c-other".to_string(),
            TagRules {
                allowed_attrs: Some(vec![]),
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // c-my-comp has no rules defined, so any attrs are allowed
        let input = r#"<c-my-comp foo="bar" baz="qux"></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Tag without rules should allow any attrs: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_allowed_slots() {
        // Define rules that only allow 'default' and 'footer' slots for c-my-comp
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["default".to_string(), "footer".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Valid: body content treated as implicit "default" slot
        let input = r#"<c-my-comp>Hello</c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Implicit default slot should succeed: {:?}",
            result.err()
        );

        // Valid: explicit allowed slot names
        let input = r#"<c-my-comp><c-fill name="default">A</c-fill><c-fill name="footer">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Allowed slot names should succeed: {:?}",
            result.err()
        );

        // Invalid: 'sidebar' is not in allowed slots
        let input = r#"<c-my-comp><c-fill name="sidebar">X</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Disallowed slot name 'sidebar' should fail"
        );
    }

    #[test]
    fn test_user_rules_allowed_slots_none() {
        // No slot restrictions (allowed_slots = None) - any slot name is OK
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Valid: body content treated as implicit "default" slot
        let input = r#"<c-my-comp>Hello</c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Implicit default slot should succeed: {:?}",
            result.err()
        );

        // Valid: any slot names are allowed when allowed_slots is None
        let input = r#"<c-my-comp><c-fill name="anything">X</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Any slot should be allowed when allowed_slots is None: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_allowed_slots_empty() {
        // No slots allowed (allowed_slots = Some([])) - body content should fail
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec![]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Invalid: body content is an implicit "default" slot, which is not allowed
        let input = r#"<c-my-comp>Hello</c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Body content should fail when no slots are allowed"
        );

        // Invalid: disallowed explicit slot name
        let input = r#"<c-my-comp><c-fill name="anything">X</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Disallowed slot name 'anything' should fail"
        );

        // Valid: empty body (no slots)
        let input = r#"<c-my-comp></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Empty body should succeed when no slots are allowed: {:?}",
            result.err()
        );

        // Valid: empty body self-closing (no slots)
        let input = r#"<c-my-comp/>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Empty body self-closing should succeed when no slots are allowed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_required_slots() {
        // Define rules that require 'default' and 'footer' slots
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec!["default".to_string(), "footer".to_string()],
            },
        );
        let rules_rc = Rc::new(rules);

        // Valid: both required slots present
        let input = r#"<c-my-comp><c-fill name="default">A</c-fill><c-fill name="footer">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Both required slots present should succeed: {:?}",
            result.err()
        );

        // Invalid: missing 'footer' slot
        let input = r#"<c-my-comp><c-fill name="default">A</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Missing required 'footer' slot should fail"
        );

        // Valid: implicit "default" slot via body content (no explicit <c-fill> tags)
        // Note: implicit default only works when there are NO <c-fill> tags at all.
        // When <c-fill> tags are present, all slots must be explicit.
        let input = r#"<c-my-comp>Default content</c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Implicit default alone should fail when 'footer' is also required"
        );
    }

    #[test]
    fn test_user_rules_required_slots_with_c_name() {
        // Even with dynamic c-name, we can still count fills vs required slots.
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec!["default".to_string(), "footer".to_string()],
            },
        );
        let rules_rc = Rc::new(rules);

        // 1 dynamic fill < 2 required slots => fails (can't possibly cover both)
        let input = r#"<c-my-comp><c-fill c-name="slot_var">X</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "1 dynamic fill for 2 required slots should fail"
        );

        // 2 dynamic fills (different) >= 2 required slots => passes (each could resolve to a different required name)
        let input = r#"<c-my-comp><c-fill c-name="var_a">A</c-fill><c-fill c-name="var_b">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "2 dynamic fills for 2 required slots should succeed: {:?}",
            result.err()
        );

        // 2 dynamic fills (same) >= 2 required slots => BUT raises because duplicate c-name
        let input = r#"<c-my-comp><c-fill c-name="var_a">A</c-fill><c-fill c-name="var_a">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "2 dynamic fills (same) for 2 required slots should fail because of duplicate c-name: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_allowed_slots_skipped_with_c_name() {
        // When <c-fill> uses c-name (dynamic), allowed slots check is also skipped
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["default".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Static name "sidebar" would fail, but dynamic c-name bypasses the check
        let input = r#"<c-my-comp><c-fill c-name="slot_var">X</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Dynamic c-name should skip allowed slots check: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_required_slots_with_c_bind() {
        // Even with dynamic c-bind, we can still count fills vs required slots.
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec!["default".to_string(), "footer".to_string()],
            },
        );
        let rules_rc = Rc::new(rules);

        // 1 dynamic c-bind fill < 2 required slots => fails
        let input = r#"<c-my-comp><c-fill c-bind="my_dict">X</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "1 c-bind fill for 2 required slots should fail"
        );

        // 2 dynamic c-bind fills (different) >= 2 required slots => passes
        let input = r#"<c-my-comp><c-fill c-bind="my_dict_a">X</c-fill><c-fill c-bind="my_dict_b">Y</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "2 c-bind fills for 2 required slots should succeed: {:?}",
            result.err()
        );

        // 2 dynamic c-bind fills (same) >= 2 required slots => BUT raises because duplicate c-bind
        let input = r#"<c-my-comp><c-fill c-bind="my_dict_a">A</c-fill><c-fill c-bind="my_dict_a">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "2 c-bind fills (same) for 2 required slots should fail because of duplicate c-bind: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_required_slots_dynamic_fill_inside_c_for() {
        // A dynamic fill inside <c-for> is unbounded.
        // ```html
        // <c-my-comp>
        //   <c-for each="item in items">
        //     <c-fill c-name="item">X</c-fill>
        //   </c-for>
        // </c-my-comp>
        // ```
        // In this case, the loop could provide all required slots, so it should succeed.
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec!["default".to_string(), "footer".to_string()],
            },
        );
        let rules_rc = Rc::new(rules);

        // 1 dynamic c-name fill inside c-for => passes (loop could provide all required slots)
        let input = r#"<c-my-comp><c-for each="item in items"><c-fill c-name="item">X</c-fill></c-for></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Dynamic fill inside c-for should skip count check: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_user_rules_required_slots_dynamic_fill_inside_c_empty() {
        // A dynamic fill inside <c-empty> is NOT unbounded - c-empty renders at most once.
        // ```html
        // <c-my-comp>
        //   <c-for>...</c-for>
        //   <c-empty>
        //     <c-fill c-name="slot_var">X</c-fill>
        //   </c-empty>
        // </c-my-comp>
        // ```
        // In this case, the fill should be counted as 1, so it should succeed.
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec!["default".to_string(), "footer".to_string()],
            },
        );
        let rules_rc = Rc::new(rules);

        // 1 dynamic fill inside c-empty (which renders at most once) < 2 required => fails
        let input = r#"<c-my-comp><c-for each="item in items">X</c-for><c-empty><c-fill c-name="slot_var">Y</c-fill></c-empty></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Dynamic fill inside c-empty (not c-for) should still fail count check"
        );
    }

    #[test]
    fn test_user_rules_required_slots_static_fill_inside_c_for() {
        // A static fill inside <c-for> still counts as 1 - looping doesn't change the name.
        // ```html
        // <c-my-comp>
        //   <c-for each="item in items">
        //     <c-fill name="default">X</c-fill>
        //   </c-for>
        // </c-my-comp>
        // ```
        // In this case, the loop could provide all required slots, so it should succeed.
        // But it should fail if the name is repeated at runtime.
        let mut rules = HashMap::new();
        rules.insert(
            "c-my-comp".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: None,
                required_slots: vec!["default".to_string(), "footer".to_string()],
            },
        );
        let rules_rc = Rc::new(rules);

        // 1 static fill inside c-for < 2 required => fails (same name repeated doesn't help)
        let input = r#"<c-my-comp><c-for each="item in items"><c-fill name="default">X</c-fill></c-for></c-my-comp>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_err(),
            "Static fill inside c-for still counts as 1, should fail for 2 required slots"
        );
    }
}
