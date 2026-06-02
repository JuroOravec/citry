// Tests for fill placement, constraints, overflow detection, identity, and duplicates

mod common;

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::rc::Rc;

    use citry_template_parser::parser::parse_template;
    use citry_template_parser::parser_context::TagRules;

    use super::common::assert_parse_error;

    // #######################################
    // FILL PLACEMENT AND CONSTRAINTS
    // #######################################

    #[test]
    fn test_fill_cannot_mix_with_other_tags() {
        // <c-fill> tags cannot be siblings with non-fill, non-control-flow tags

        // <div> then <c-fill>
        let input = r#"<c-my-comp><div>Hello</div><c-fill name="footer">B</c-fill></c-my-comp>"#;
        assert_parse_error(input, "must be grouped");

        // <c-fill> then <div>
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><div>Hello</div></c-my-comp>"#;
        assert_parse_error(input, "must be grouped");

        // Multiple <c-fill> tags together is fine
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-fill name="footer">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "Multiple c-fill siblings should succeed: {:?}",
            result.err()
        );

        // <c-fill> then <c-if> containing only c-fill
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-if cond="x"><c-fill name="footer">B</c-fill></c-if></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill then c-if (containing only c-fill) should succeed: {:?}",
            result.err()
        );

        // <c-if> containing only c-fill then <c-fill>
        let input = r#"<c-my-comp><c-if cond="x"><c-fill name="header">A</c-fill></c-if><c-fill name="footer">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-if (containing only c-fill) then c-fill should succeed: {:?}",
            result.err()
        );

        // <c-fill> then <c-for> containing only c-fill
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-for each="s in slots"><c-fill c-name="s">X</c-fill></c-for></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill then c-for (containing only c-fill) should succeed: {:?}",
            result.err()
        );

        // <c-for> containing only c-fill then <c-fill>
        let input = r#"<c-my-comp><c-for each="s in slots"><c-fill c-name="s">X</c-fill></c-for><c-fill name="footer">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-for (containing only c-fill) then c-fill should succeed: {:?}",
            result.err()
        );

        // <c-fill> then nested control flow (c-if > c-for > c-fill)
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-if cond="x"><c-for each="s in slots"><c-fill c-name="s">X</c-fill></c-for></c-if></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill then nested control flow containing only c-fill should succeed: {:?}",
            result.err()
        );

        // Nested control flow (c-if > c-for > c-fill) then <c-fill>
        let input = r#"<c-my-comp><c-if cond="x"><c-for each="s in slots"><c-fill c-name="s">X</c-fill></c-for></c-if><c-fill name="footer">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "Nested control flow containing only c-fill then c-fill should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_fill_control_flow_sibling_must_contain_only_fills() {
        // c-if with <div> AFTER c-fill
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-if cond="x"><div>Not a fill</div></c-if></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // c-if with <div> BEFORE c-fill
        let input = r#"<c-my-comp><c-if cond="x"><div>Bad</div></c-if><c-fill name="header">A</c-fill></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // c-if with text AFTER c-fill
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-if cond="x">Some text</c-if></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // c-if with text BEFORE c-fill
        let input = r#"<c-my-comp><c-if cond="x">Some text</c-if><c-fill name="header">A</c-fill></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // c-if with expression AFTER c-fill
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-if cond="x">{{ expr }}</c-if></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // c-if with expression BEFORE c-fill
        let input = r#"<c-my-comp><c-if cond="x">{{ expr }}</c-if><c-fill name="header">A</c-fill></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // c-if with component AFTER c-fill
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-if cond="x"><c-other>Z</c-other></c-if></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // c-if with component BEFORE c-fill
        let input = r#"<c-my-comp><c-if cond="x"><c-other>Z</c-other></c-if><c-fill name="header">A</c-fill></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // Nested control flow with bad content AFTER c-fill
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-if cond="x"><c-for each="s in slots"><div>Bad</div></c-for></c-if></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");

        // Nested control flow with bad content BEFORE c-fill
        let input = r#"<c-my-comp><c-if cond="x"><c-for each="s in slots"><div>Bad</div></c-for></c-if><c-fill name="header">A</c-fill></c-my-comp>"#;
        assert_parse_error(input, "contains non-fill content");
    }

    #[test]
    fn test_fill_cannot_nest_inside_fill() {
        // <c-fill> cannot be nested inside another <c-fill>
        let input = r#"<c-my-comp><c-fill name="outer"><c-fill name="inner">X</c-fill></c-fill></c-my-comp>"#;
        assert_parse_error(input, "cannot be inside");
    }

    #[test]
    fn test_fill_must_be_inside_component() {
        // <c-fill> at the top level (not inside any component) should fail
        let input = r#"<c-fill name="footer">X</c-fill>"#;
        assert_parse_error(input, "must be inside a component");

        // <c-fill> inside a regular HTML tag should fail
        let input = r#"<div><c-fill name="footer">X</c-fill></div>"#;
        assert_parse_error(input, "must be inside a component");
    }

    #[test]
    fn test_fill_inside_control_flow() {
        // <c-fill> CAN be inside control flow tags when those are inside a component

        // Inside c-if
        let input =
            r#"<c-my-comp><c-if cond="x"><c-fill name="header">A</c-fill></c-if></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill inside c-if should succeed: {:?}",
            result.err()
        );

        // Inside c-elif
        let input = r#"<c-my-comp><c-if cond="x"><c-fill name="a">A</c-fill></c-if><c-elif cond="y"><c-fill name="b">B</c-fill></c-elif></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill inside c-elif should succeed: {:?}",
            result.err()
        );

        // Inside c-else
        let input = r#"<c-my-comp><c-if cond="x"><c-fill name="a">A</c-fill></c-if><c-else><c-fill name="b">B</c-fill></c-else></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill inside c-else should succeed: {:?}",
            result.err()
        );

        // Inside c-for
        let input = r#"<c-my-comp><c-for each="item in items"><c-fill name="row">X</c-fill></c-for></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill inside c-for should succeed: {:?}",
            result.err()
        );

        // Inside c-empty (after c-for)
        let input = r#"<c-my-comp><c-for each="item in items"><c-fill name="row">X</c-fill></c-for><c-empty><c-fill name="empty">None</c-fill></c-empty></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill inside c-empty should succeed: {:?}",
            result.err()
        );

        // Counter examples: same templates WITHOUT the encapsulating <c-my-comp> should fail
        // because <c-fill> must be inside a component tag.

        // c-fill inside c-if at root
        let input = r#"<c-if cond="x"><c-fill name="header">A</c-fill></c-if>"#;
        assert_parse_error(input, "must be inside a component");

        // c-fill inside c-elif at root
        let input =
            r#"<c-if cond="x">A</c-if><c-elif cond="y"><c-fill name="b">B</c-fill></c-elif>"#;
        assert_parse_error(input, "must be inside a component");

        // c-fill inside c-else at root
        let input = r#"<c-if cond="x">A</c-if><c-else><c-fill name="b">B</c-fill></c-else>"#;
        assert_parse_error(input, "must be inside a component");

        // c-fill inside c-for at root
        let input = r#"<c-for each="item in items"><c-fill name="row">X</c-fill></c-for>"#;
        assert_parse_error(input, "must be inside a component");

        // c-fill inside c-empty at root
        let input = r#"<c-for each="item in items">X</c-for><c-empty><c-fill name="empty">None</c-fill></c-empty>"#;
        assert_parse_error(input, "must be inside a component");
    }

    #[test]
    fn test_fill_inside_reserved_tag_c_raw() {
        // <c-raw> treats everything inside as raw text, so <c-fill> inside it
        // is not parsed as a tag - it's just literal text
        let input = r#"<c-my-comp><c-raw><c-fill name="header">A</c-fill></c-raw></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-fill inside c-raw is treated as raw text, should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_fill_with_data_and_default_attrs() {
        // <c-fill> with data attr introduces a variable that is available in the body.
        // The introduced variable is excluded from the node's used_variables (not propagated to parent).
        let input = r#"<c-my-comp><c-fill name="header" data="x">{{ x }}</c-fill></c-my-comp>"#;
        let template = parse_template(input, None, None).unwrap();

        // "x" is introduced by data="x", so it should NOT appear in the template's used_variables
        let used_var_names: Vec<&str> = template
            .used_variables
            .iter()
            .map(|v| v.content.as_str())
            .collect();
        assert!(
            !used_var_names.contains(&"x"),
            "template.used_variables should NOT contain 'x' (introduced by data attr): {:?}",
            used_var_names
        );

        // Same for default attr
        let input = r#"<c-my-comp><c-fill name="header" default="y">{{ y }}</c-fill></c-my-comp>"#;
        let template = parse_template(input, None, None).unwrap();

        let used_var_names: Vec<&str> = template
            .used_variables
            .iter()
            .map(|v| v.content.as_str())
            .collect();
        assert!(
            !used_var_names.contains(&"y"),
            "template.used_variables should NOT contain 'y' (introduced by default attr): {:?}",
            used_var_names
        );

        // Using a variable NOT introduced by the fill - should be in used_variables
        let input = r#"<c-my-comp><c-fill name="header" data="x">{{ z }}</c-fill></c-my-comp>"#;
        let template = parse_template(input, None, None).unwrap();

        let used_var_names: Vec<&str> = template
            .used_variables
            .iter()
            .map(|v| v.content.as_str())
            .collect();
        assert!(
            used_var_names.contains(&"z"),
            "template.used_variables should contain 'z' (from outer scope): {:?}",
            used_var_names
        );
        assert!(
            !used_var_names.contains(&"x"),
            "template.used_variables should NOT contain 'x' (introduced by data attr): {:?}",
            used_var_names
        );

        // Other attributes on c-fill should fail (only name, c-name, data, default, c-bind are allowed)
        let input = r#"<c-my-comp><c-fill name="header" class="foo">X</c-fill></c-my-comp>"#;
        assert_parse_error(input, "can only have");
    }

    #[test]
    fn test_fill_duplicate_names() {
        // Duplicate static fill names should always fail, even without user-defined rules
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-fill name="header">B</c-fill></c-my-comp>"#;
        assert_parse_error(input, "Duplicate");

        // Duplicate c-name values should also fail
        let input = r#"<c-my-comp><c-fill c-name="slot_var">A</c-fill><c-fill c-name="slot_var">B</c-fill></c-my-comp>"#;
        assert_parse_error(input, "Duplicate");

        // Different names are fine
        let input = r#"<c-my-comp><c-fill name="header">A</c-fill><c-fill name="footer">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "Different fill names should succeed: {:?}",
            result.err()
        );
    }

    // #######################################
    // FILL OVERFLOW DETECTION
    // Overflow happens when there are more dynamic fills than allowed slots.
    // #######################################

    #[test]
    fn test_fill_overflow_all_slots_filled_plus_dynamic() {
        // allowed_slots=["h", "f"], 2 static fills + 1 dynamic fill (not in control flow) -> error
        // The dynamic fill will either duplicate an existing slot or use a non-allowed name.
        let mut rules = HashMap::new();
        rules.insert(
            "c-a".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["h".to_string(), "f".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        let input = r#"<c-a><c-fill name="h">X</c-fill><c-fill name="f">Y</c-fill><c-fill c-name="some_var">Z</c-fill></c-a>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        let err = result.unwrap_err();
        let err_msg = format!("{}", err);
        assert!(
            err_msg.contains("slot(s)"),
            "Expected 'slot(s)' in overflow error, got: {}",
            err_msg
        );
    }

    #[test]
    fn test_fill_overflow_one_remaining_slot() {
        // allowed_slots=["h", "f"], 1 static fill + 1 dynamic fill -> ok (1 remaining slot)
        let mut rules = HashMap::new();
        rules.insert(
            "c-a".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["h".to_string(), "f".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        let input = r#"<c-a><c-fill name="h">X</c-fill><c-fill c-name="some_var">Z</c-fill></c-a>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "1 static fill + 1 dynamic fill with 2 allowed slots should succeed (1 remaining): {:?}",
            result.err()
        );
    }

    #[test]
    fn test_fill_overflow_single_allowed_slot() {
        // allowed_slots=["h"], 1 static fill + 1 dynamic fill -> error (0 remaining)
        let mut rules = HashMap::new();
        rules.insert(
            "c-a".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["h".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        let input = r#"<c-a><c-fill name="h">X</c-fill><c-fill c-name="some_var">Z</c-fill></c-a>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        let err = result.unwrap_err();
        let err_msg = format!("{}", err);
        assert!(
            err_msg.contains("slot(s)"),
            "Expected 'slot(s)' in overflow error, got: {}",
            err_msg
        );
    }

    #[test]
    fn test_fill_overflow_dynamic_inside_control_flow_excluded() {
        // allowed_slots=["h"], 1 static fill + 1 dynamic fill inside <c-if> -> ok
        // Fills inside control flow are excluded from the overflow check.
        let mut rules = HashMap::new();
        rules.insert(
            "c-a".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["h".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Static fill at top level + dynamic fill inside c-if (excluded from overflow)
        let input = r#"<c-a><c-fill name="h">X</c-fill><c-if cond="x"><c-fill c-name="some_var">Z</c-fill></c-if></c-a>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Dynamic fill inside c-if should be excluded from overflow check: {:?}",
            result.err()
        );

        // Compare: same fills NOT inside control flow would fail (tested in test_fill_overflow_single_allowed_slot)
    }

    #[test]
    fn test_fill_overflow_dynamic_cbind_outside_control_flow() {
        // allowed_slots=["h"], 1 static fill + 1 c-bind fill (not in control flow) -> error
        let mut rules = HashMap::new();
        rules.insert(
            "c-a".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["h".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        let input = r#"<c-a><c-fill name="h">X</c-fill><c-fill c-bind="my_dict">Z</c-fill></c-a>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        let err = result.unwrap_err();
        let err_msg = format!("{}", err);
        assert!(
            err_msg.contains("slot(s)"),
            "Expected 'slot(s)' in overflow error with c-bind, got: {}",
            err_msg
        );
    }

    #[test]
    fn test_fill_overflow_dynamic_inside_c_for_excluded() {
        // allowed_slots=["h"], 1 static fill + 1 dynamic fill inside <c-for> -> ok
        let mut rules = HashMap::new();
        rules.insert(
            "c-a".to_string(),
            TagRules {
                allowed_attrs: None,
                required_attrs: vec![],
                allowed_slots: Some(vec!["h".to_string()]),
                required_slots: vec![],
            },
        );
        let rules_rc = Rc::new(rules);

        // Static fill at top level + dynamic fill inside c-for (excluded from overflow)
        let input = r#"<c-a><c-fill name="h">X</c-fill><c-for each="s in slots"><c-fill c-name="s">Z</c-fill></c-for></c-a>"#;
        let result = parse_template(input, None, Some(&rules_rc));
        assert!(
            result.is_ok(),
            "Dynamic fill inside c-for should be excluded from overflow check: {:?}",
            result.err()
        );
    }

    // #######################################
    // FILL IDENTITY AND DUPLICATE c-bind
    // #######################################

    #[test]
    fn test_fill_duplicate_cbind_same_value() {
        // Two <c-fill> with same single c-bind value -> error (same identity)
        let input =
            r#"<c-my-comp><c-fill c-bind="x">A</c-fill><c-fill c-bind="x">B</c-fill></c-my-comp>"#;
        assert_parse_error(input, "Duplicate");
    }

    #[test]
    fn test_fill_duplicate_cbind_different_values() {
        // Two <c-fill> with different c-bind values -> ok (different identities)
        let input =
            r#"<c-my-comp><c-fill c-bind="x">A</c-fill><c-fill c-bind="y">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "Different c-bind values should succeed: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_fill_duplicate_cbind_same_ordered_tuple() {
        // Two <c-fill> with same ordered tuple of c-bind values -> error
        let input = r#"<c-my-comp><c-fill c-bind="a" c-bind="b">A</c-fill><c-fill c-bind="a" c-bind="b">B</c-fill></c-my-comp>"#;
        assert_parse_error(input, "Duplicate");
    }

    #[test]
    fn test_fill_duplicate_cbind_different_order() {
        // Two <c-fill> with same c-bind values in different order -> ok (can resolve to different values, so different identity tuples)
        let input = r#"<c-my-comp><c-fill c-bind="a" c-bind="b">A</c-fill><c-fill c-bind="b" c-bind="a">B</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "c-bind with different order should succeed (different identity): {:?}",
            result.err()
        );
    }

    // #######################################
    // FILL IDENTITY RESOLUTION
    // #######################################

    #[test]
    fn test_fill_identity_cbind_then_name_resolves_to_static() {
        // <c-fill c-bind="b" name="a"> -> rightmost is `name` -> StaticName("a")
        // <c-fill name="a"> -> also StaticName("a")
        // Both resolve to StaticName("a"), so this is a duplicate -> error
        let input = r#"<c-my-comp><c-fill c-bind="b" name="a">X</c-fill><c-fill name="a">Y</c-fill></c-my-comp>"#;
        assert_parse_error(input, "Duplicate");
    }

    #[test]
    fn test_fill_identity_name_then_cbind_resolves_to_dynamic_bind() {
        // <c-fill name="a" c-bind="b"> -> rightmost is `c-bind` -> DynamicBind([("c-bind","b"), ("name","a")])
        // <c-fill name="a"> -> StaticName("a")
        // Different identity types -> ok (not a duplicate)
        let input = r#"<c-my-comp><c-fill name="a" c-bind="b">X</c-fill><c-fill name="a">Y</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "name='a' c-bind='b' (DynamicBind) vs name='a' (StaticName) should not be duplicates: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_fill_identity_cbind_cbind_cname_resolves_to_dynamic_name() {
        // <c-fill c-bind="c" c-bind="b" c-name="a"> -> rightmost is `c-name` -> DynamicName("a")
        // <c-fill c-name="a"> -> also DynamicName("a")
        // Both resolve to DynamicName("a") -> duplicate error
        let input = r#"<c-my-comp><c-fill c-bind="c" c-bind="b" c-name="a">X</c-fill><c-fill c-name="a">Y</c-fill></c-my-comp>"#;
        assert_parse_error(input, "Duplicate");
    }

    #[test]
    fn test_fill_identity_cbind_name_cbind_resolves_to_dynamic_bind() {
        // <c-fill c-bind="c" name="a" c-bind="b"> -> rightmost is `c-bind`
        //   -> DynamicBind([("c-bind","b"), ("name","a")])  (c-bind="c" before name is ignored)
        // This is a unique identity, should not conflict with a simple StaticName("a")
        let input = r#"<c-my-comp><c-fill c-bind="c" name="a" c-bind="b">X</c-fill><c-fill name="a">Y</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "DynamicBind([c-bind=b, name=a]) vs StaticName(a) should not be duplicates: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_fill_identity_cbind_cname_cbind_resolves_to_dynamic_bind() {
        // <c-fill c-bind="c" c-name="a" c-bind="b"> -> rightmost is `c-bind`
        //   -> DynamicBind([("c-bind","b"), ("c-name","a")])  (c-bind="c" before c-name is ignored)
        // Should not conflict with DynamicName("a")
        let input = r#"<c-my-comp><c-fill c-bind="c" c-name="a" c-bind="b">X</c-fill><c-fill c-name="a">Y</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "DynamicBind([c-bind=b, c-name=a]) vs DynamicName(a) should not be duplicates: {:?}",
            result.err()
        );
    }

    #[test]
    fn test_fill_identity_two_cbinds_only() {
        // <c-fill c-bind="c" c-bind="b"> -> rightmost is `c-bind`
        //   -> DynamicBind([("c-bind","b"), ("c-bind","c")])  (no name/c-name, all included)
        // Two of these should be duplicates
        let input = r#"<c-my-comp><c-fill c-bind="c" c-bind="b">X</c-fill><c-fill c-bind="c" c-bind="b">Y</c-fill></c-my-comp>"#;
        assert_parse_error(input, "Duplicate");

        // But different order should be ok
        let input = r#"<c-my-comp><c-fill c-bind="c" c-bind="b">X</c-fill><c-fill c-bind="b" c-bind="c">Y</c-fill></c-my-comp>"#;
        let result = parse_template(input, None, None);
        assert!(
            result.is_ok(),
            "Different c-bind order should not be duplicates: {:?}",
            result.err()
        );
    }
}
