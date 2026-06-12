// Tests for the dynamic-target built-in tags: `<c-component>` (dynamic
// component) and `<c-element>` (dynamic HTML element).
//
// See docs/design/dynamic_component.md. The compiler handles the static
// cases at compile time:
// - `<c-component is="X">` rewrites to the named component node (`<c-X>`).
// - `<c-element is="x">` (no fills in the body) rewrites to the plain HTML
//   element, exactly as if it had been written statically.
// Dynamic cases (`c-is`, or `is` via `c-bind`) compile to a regular
// ComponentNode named "component" / "element", resolved at render time by
// the Python built-in components.
//
// Assertions follow the conventions of tag_compiler.rs (exact generated
// Python source, authored observe-then-lock).

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::compiler::compile_template;
    use citry_template_parser::parser::parse_template;

    use super::common::assert_parse_error;

    /// Wrap an expected `body` list in the `generate_template()` boilerplate.
    fn wrap(body_list: &str) -> String {
        format!(
            "def generate_template():\n    body = {}\n    return body\n",
            body_list
        )
    }

    /// Parse + compile `input`, then assert the generated code matches
    /// `wrap(expected_body_list)`.
    fn assert_compile(input: &str, expected_body_list: &str) {
        let template = parse_template(input, None, None)
            .unwrap_or_else(|e| panic!("parse failed for {input:?}: {e:?}"));
        let result = compile_template(template, None)
            .unwrap_or_else(|e| panic!("compile failed for {input:?}: {e:?}"));
        assert_eq!(result, wrap(expected_body_list), "input: {input:?}");
    }

    /// Parse + compile `input`, expect a compile error whose message contains
    /// `expected_msg`.
    fn assert_compile_error(input: &str, expected_msg: &str) {
        let template = parse_template(input, None, None)
            .unwrap_or_else(|e| panic!("parse failed for {input:?}: {e:?}"));
        let err = compile_template(template, None)
            .expect_err(&format!("expected compile error for {input:?}"));
        let msg = err.to_string();
        assert!(
            msg.contains(expected_msg),
            "input: {input:?}\nexpected message containing: {expected_msg:?}\ngot: {msg:?}"
        );
    }

    // =============================================================================
    // <c-component> - static `is` rewrite
    // =============================================================================

    #[test]
    fn test_component_static_is_rewrites_to_named_component() {
        // `is` is dropped, the remaining attrs and the body carry over, and
        // the component name is the static value (lowercased).
        assert_compile(
            r#"<c-component is="MyComp" c-x="y">hi</c-component>"#,
            r#"[ComponentNode(source, (0, 49,), (ExprHtmlAttr(source, (25, 32,), """c-x""", """y""", ("y",)),), ["""hi""",], ("y",), """mycomp""", False),]"#,
        );
    }

    #[test]
    fn test_component_dynamic_is_compiles_to_component_builtin() {
        assert_compile(
            r#"<c-component c-is="comp" />"#,
            r#"[ComponentNode(source, (0, 27,), (ExprHtmlAttr(source, (13, 24,), """c-is""", """comp""", ("comp",)),), [], ("comp",), """component""", False),]"#,
        );
    }

    #[test]
    fn test_component_empty_static_is_stays_on_runtime_path() {
        // `is=""` normalizes to a boolean attribute (True), so there is no
        // static name to rewrite to; the built-in rejects the value at render.
        assert_compile(
            r#"<c-component is="" />"#,
            r#"[ComponentNode(source, (0, 21,), (StaticHtmlAttr(source, (13, 18,), """is""", True, ()),), [], (), """component""", False),]"#,
        );
    }

    #[test]
    fn test_component_is_and_c_is_conflict_is_compile_error() {
        assert_compile_error(
            r#"<c-component is="MyComp" c-is="other" />"#,
            "<c-component> accepts either 'is' or 'c-is', not both",
        );
    }

    #[test]
    fn test_component_requires_is_or_bind() {
        assert_parse_error(
            "<c-component />",
            "Tag '<c-component>' must have one of the following attributes: 'is', 'c-is', 'c-bind'.",
        );
    }

    // =============================================================================
    // <c-element> - static `is` rewrite to a plain HTML element
    // =============================================================================

    #[test]
    fn test_element_static_is_rewrites_to_plain_element() {
        // Compiles exactly as if `<div class="a">hi {{ name }}</div>` had
        // been written: static parts flattened to strings.
        assert_compile(
            r#"<c-element is="div" class="a">hi {{ name }}</c-element>"#,
            r#"["""<div class=\"a\">hi """, ExprNode(source, (33, 43,), """name """, ("name",)), """</div>""",]"#,
        );
    }

    #[test]
    fn test_element_static_is_with_dynamic_attrs_uses_element_attrs_node() {
        // Same as a static element with a `c-*` attribute: the attribute
        // region compiles to one ElementAttrsNode.
        assert_compile(
            r#"<c-element is="div" c-class="cls">hi</c-element>"#,
            r#"["""<div""", ElementAttrsNode(source, (0, 34,), (ExprHtmlAttr(source, (20, 33,), """c-class""", """cls""", ("cls",)),), ("cls",)), """>hi</div>""",]"#,
        );
    }

    #[test]
    fn test_element_static_void_self_closing_stays_compact() {
        assert_compile(r#"<c-element is="br" />"#, r#"["""<br/>""",]"#);
    }

    #[test]
    fn test_element_static_void_with_whitespace_body_stays_compact() {
        // Whitespace-only body is formatting, not content.
        assert_compile(r#"<c-element is="br">  </c-element>"#, r#"["""<br/>""",]"#);
    }

    #[test]
    fn test_element_static_non_void_empty_expands() {
        assert_compile(
            r#"<c-element is="section"></c-element>"#,
            r#"["""<section></section>""",]"#,
        );
    }

    #[test]
    fn test_element_static_camel_case_name_renders_verbatim() {
        // SVG names like clipPath keep the author's casing.
        assert_compile(
            r#"<c-element is="clipPath" c-d="path">x</c-element>"#,
            r#"["""<clipPath""", ElementAttrsNode(source, (0, 36,), (ExprHtmlAttr(source, (25, 35,), """c-d""", """path""", ("path",)),), ("path",)), """>x</clipPath>""",]"#,
        );
    }

    #[test]
    fn test_element_static_void_with_content_is_compile_error() {
        assert_compile_error(
            r#"<c-element is="br">stuff</c-element>"#,
            "<c-element>: void element 'br' cannot have children",
        );
    }

    #[test]
    fn test_element_static_invalid_tag_name_is_compile_error() {
        assert_compile_error(
            r#"<c-element is="bad name" />"#,
            "is not a valid HTML tag name",
        );
    }

    // =============================================================================
    // <c-element> - runtime path
    // =============================================================================

    #[test]
    fn test_element_dynamic_is_compiles_to_element_builtin() {
        assert_compile(
            r#"<c-element c-is="tag" class="a">hi</c-element>"#,
            r#"[ComponentNode(source, (0, 46,), (ExprHtmlAttr(source, (11, 21,), """c-is""", """tag""", ("tag",)), StaticHtmlAttr(source, (22, 31,), """class""", """a""", ()),), ["""hi""",], ("tag",), """element""", False),]"#,
        );
    }

    #[test]
    fn test_element_static_is_with_default_fill_stays_on_runtime_path() {
        // An explicit `<c-fill name="default">` is legal; unwrapping it at
        // compile time is not worth the complexity, so the built-in resolves
        // it at render.
        assert_compile(
            r#"<c-element is="div"><c-fill name="default">X</c-fill></c-element>"#,
            r#"[ComponentNode(source, (0, 65,), (StaticHtmlAttr(source, (11, 19,), """is""", """div""", ()),), [FillNode(source, (20, 53,), (StaticHtmlAttr(source, (28, 42,), """name""", """default""", ()),), ["""X""",], (), ()),], (), """element""", True),]"#,
        );
    }

    // =============================================================================
    // <c-element> - parse rules
    // =============================================================================

    #[test]
    fn test_element_is_and_c_is_conflict_is_compile_error() {
        assert_compile_error(
            r#"<c-element is="div" c-is="tag" />"#,
            "<c-element> accepts either 'is' or 'c-is', not both",
        );
    }

    #[test]
    fn test_element_requires_is_or_bind() {
        assert_parse_error(
            "<c-element />",
            "Tag '<c-element>' must have one of the following attributes: 'is', 'c-is', 'c-bind'.",
        );
    }

    #[test]
    fn test_element_named_fill_is_parse_error() {
        // An element has children but no named slots.
        assert_parse_error(
            r#"<c-element is="div"><c-fill name="header">X</c-fill></c-element>"#,
            "Tag '<c-element>' does not allow a slot named 'header'.",
        );
    }
}
