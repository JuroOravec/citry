// Tests for the V3 template compiler.
//
// The compiler (`compile_template`) turns a parsed `Template` AST into
// language-specific source code. For Python (the default), it generates a
// `generate_template()` function that returns a `body` list of node objects
// (text strings, ExprNode, ComponentNode, IfNode, ForNode, SlotNode, FillNode,
// and HtmlAttr calls).
//
// These tests assert on the exact generated Python source string.
//
// Conventions observed in the generated code:
// - Lists are formatted with a trailing comma: `[a, b,]`, empty is `[]`.
// - Tuples are formatted with a trailing comma: `(a, b,)`, empty is `()`,
//   single is `(x,)`.
// - Strings use triple double-quotes with ALL `"` escaped as `\"` (so even
//   `"""` inside content can't terminate the string): `"""a \"b\" c"""`.
// - Static text and static HTML are coalesced into single strings.
// - Component names are normalized: `<c-Card>` -> `"""card"""`.

mod common;

#[cfg(test)]
mod tests {
    use citry_template_parser::compiler::compile_template;
    use citry_template_parser::parser::parse_template;

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

    // =============================================================================
    // BOILERPLATE / EMPTY
    // =============================================================================

    #[test]
    fn test_empty_template() {
        assert_compile("", "[]");
    }

    // =============================================================================
    // PLAIN TEXT
    // =============================================================================

    #[test]
    fn test_plain_text() {
        assert_compile("Hello, world!", r#"["""Hello, world!""",]"#);
    }

    #[test]
    fn test_text_with_quotes_is_escaped() {
        // Double quotes in text are escaped as \" even inside triple quotes.
        assert_compile(r#"Say "hi""#, r#"["""Say \"hi\"""",]"#);
    }

    // =============================================================================
    // EXPRESSIONS {{ ... }}
    // =============================================================================

    #[test]
    fn test_expr_simple() {
        // Note: expression content retains its trailing whitespace ("name ").
        assert_compile("{{ name }}", r#"[ExprNode(source, (0, 10,), """name """, ("name",)),]"#);
    }

    #[test]
    fn test_expr_with_surrounding_text() {
        assert_compile(
            "Hello {{ name }}!",
            r#"["""Hello """, ExprNode(source, (6, 16,), """name """, ("name",)), """!""",]"#,
        );
    }

    #[test]
    fn test_expr_arithmetic_multiple_vars() {
        assert_compile(
            "{{ a + b }}",
            r#"[ExprNode(source, (0, 11,), """a + b """, ("a", "b",)),]"#,
        );
    }

    #[test]
    fn test_expr_no_vars_has_empty_tuple() {
        assert_compile("{{ 1 + 2 }}", r#"[ExprNode(source, (0, 11,), """1 + 2 """, ()),]"#);
    }

    #[test]
    fn test_two_expressions_not_coalesced() {
        assert_compile(
            "{{ a }}{{ b }}",
            r#"[ExprNode(source, (0, 7,), """a """, ("a",)), ExprNode(source, (7, 14,), """b """, ("b",)),]"#,
        );
    }

    // =============================================================================
    // STATIC HTML
    // =============================================================================

    #[test]
    fn test_html_basic() {
        assert_compile("<div>hi</div>", r#"["""<div>hi</div>""",]"#);
    }

    #[test]
    fn test_html_with_static_attr() {
        assert_compile(
            r#"<div class="foo">hi</div>"#,
            r#"["""<div class=\"foo\">hi</div>""",]"#,
        );
    }

    #[test]
    fn test_html_void_element_stays_compact() {
        // `<br>` renders as `<br/>` (self-closing, not expanded).
        assert_compile("<br>", r#"["""<br/>""",]"#);
    }

    #[test]
    fn test_html_void_element_self_closing() {
        assert_compile("<br/>", r#"["""<br/>""",]"#);
    }

    #[test]
    fn test_html_non_void_self_closing_expands() {
        // `<div/>` expands to `<div></div>`.
        assert_compile("<div/>", r#"["""<div></div>""",]"#);
    }

    #[test]
    fn test_consecutive_html_coalesced() {
        assert_compile(
            "<div>a</div><span>b</span>",
            r#"["""<div>a</div><span>b</span>""",]"#,
        );
    }

    // =============================================================================
    // DYNAMIC ATTRIBUTES ON HTML TAGS
    // =============================================================================
    // On a regular HTML tag, a dynamic `c-*` attribute is split: the static
    // parts become string fragments and the dynamic value becomes an ExprNode
    // embedded inline (concatenated into the surrounding HTML string at runtime).

    #[test]
    fn test_html_expr_attr() {
        assert_compile(
            r#"<div c-class="cls">hi</div>"#,
            r#"["""<div class=\"""", ExprNode(source, (14, 17,), """cls""", ("cls",)), """\">hi</div>""",]"#,
        );
    }

    #[test]
    fn test_html_empty_attr_becomes_boolean() {
        // `class=""` is normalized to a bare boolean attribute `class`.
        assert_compile(
            r#"<div class="">hi</div>"#,
            r#"["""<div class>hi</div>""",]"#,
        );
    }

    #[test]
    fn test_html_c_bind_strips_prefix() {
        // On an HTML tag, c-bind has its `c-` prefix stripped like any c-* attr.
        assert_compile(
            r#"<div c-bind="attrs">hi</div>"#,
            r#"["""<div bind=\"""", ExprNode(source, (13, 18,), """attrs""", ("attrs",)), """\">hi</div>""",]"#,
        );
    }

    #[test]
    fn test_html_expr_attr_with_trailing_text() {
        assert_compile(
            r#"<a c-href="url">link</a>"#,
            r#"["""<a href=\"""", ExprNode(source, (11, 14,), """url""", ("url",)), """\">link</a>""",]"#,
        );
    }

    // =============================================================================
    // COMPONENTS <c-*>
    // =============================================================================
    // ComponentNode signature:
    //   ComponentNode(source, (start, end,), (attrs,), [body], (used_vars,), """name""", contains_fills)

    #[test]
    fn test_component_self_closing() {
        assert_compile(
            "<c-Card />",
            r#"[ComponentNode(source, (0, 10,), (), [], (), """card""", False),]"#,
        );
    }

    #[test]
    fn test_component_name_normalized_lowercase() {
        // `c-Card` -> name `"""card"""`.
        assert_compile(
            "<c-Card></c-Card>",
            r#"[ComponentNode(source, (0, 17,), (), [], (), """card""", False),]"#,
        );
    }

    #[test]
    fn test_component_kebab_name_preserved() {
        assert_compile(
            "<c-my-card />",
            r#"[ComponentNode(source, (0, 13,), (), [], (), """my-card""", False),]"#,
        );
    }

    #[test]
    fn test_component_with_static_attr() {
        assert_compile(
            r#"<c-Card title="Hello" />"#,
            r#"[ComponentNode(source, (0, 24,), (StaticHtmlAttr(source, (8, 21,), """title""", """Hello""", ()),), [], (), """card""", False),]"#,
        );
    }

    #[test]
    fn test_component_with_expr_attr() {
        // Dynamic attr keeps the `c-` prefix in its key, and its var is tracked
        // both on the attr and on the component's used_vars.
        assert_compile(
            r#"<c-Card c-title="t" />"#,
            r#"[ComponentNode(source, (0, 22,), (ExprHtmlAttr(source, (8, 19,), """c-title""", """t""", ("t",)),), [], ("t",), """card""", False),]"#,
        );
    }

    #[test]
    fn test_component_with_template_attr() {
        // A c-* attr whose value is a nested template becomes a TemplateHtmlAttr.
        assert_compile(
            r#"<c-Card c-body="<span>{{ x }}</span>" />"#,
            r#"[ComponentNode(source, (0, 40,), (TemplateHtmlAttr(source, (8, 37,), """c-body""", """<span>{{ x }}</span>""", ("x",)),), [], ("x",), """card""", False),]"#,
        );
    }

    #[test]
    fn test_component_with_body() {
        assert_compile(
            "<c-Card>body</c-Card>",
            r#"[ComponentNode(source, (0, 21,), (), ["""body""",], (), """card""", False),]"#,
        );
    }

    #[test]
    fn test_nested_components() {
        assert_compile(
            "<c-Outer><c-Inner /></c-Outer>",
            r#"[ComponentNode(source, (0, 30,), (), [ComponentNode(source, (9, 20,), (), [], (), """inner""", False),], (), """outer""", False),]"#,
        );
    }

    // =============================================================================
    // CONTROL FLOW: IF / ELIF / ELSE
    // =============================================================================
    // IfNode signature:
    //   IfNode(source, (branch1, branch2, ...), (used_vars,))
    // where each branch is:
    //   ((start, end,), (attrs,), [body], (branch_used_vars,))

    #[test]
    fn test_if_simple() {
        assert_compile(
            r#"<c-if cond="x">yes</c-if>"#,
            r#"[IfNode(source, (((0, 25,), (StaticHtmlAttr(source, (6, 14,), """cond""", """x""", ()),), ["""yes""",], (),),), ()),]"#,
        );
    }

    #[test]
    fn test_if_elif_else() {
        assert_compile(
            r#"<c-if cond="x">a</c-if><c-elif cond="y">b</c-elif><c-else>c</c-else>"#,
            r#"[IfNode(source, (((0, 23,), (StaticHtmlAttr(source, (6, 14,), """cond""", """x""", ()),), ["""a""",], (),), ((23, 50,), (StaticHtmlAttr(source, (31, 39,), """cond""", """y""", ()),), ["""b""",], (),), ((50, 68,), (), ["""c""",], (),),), ()),]"#,
        );
    }

    // =============================================================================
    // CONTROL FLOW: FOR / EMPTY
    // =============================================================================
    // ForNode signature mirrors IfNode: branches are (for-branch, empty-branch?).

    #[test]
    fn test_for_simple() {
        assert_compile(
            r#"<c-for each="item in items">{{ item }}</c-for>"#,
            r#"[ForNode(source, (((0, 46,), (StaticHtmlAttr(source, (7, 27,), """each""", """item in items""", ()),), [ExprNode(source, (28, 38,), """item """, ("item",)),], ("item",),),), ()),]"#,
        );
    }

    #[test]
    fn test_for_with_empty() {
        assert_compile(
            r#"<c-for each="item in items">{{ item }}</c-for><c-empty>none</c-empty>"#,
            r#"[ForNode(source, (((0, 46,), (StaticHtmlAttr(source, (7, 27,), """each""", """item in items""", ()),), [ExprNode(source, (28, 38,), """item """, ("item",)),], ("item",),), ((46, 69,), (), ["""none""",], (),),), ()),]"#,
        );
    }

    // =============================================================================
    // CONTROL FLOW AS ATTRIBUTES (c-if / c-for on regular tags)
    // =============================================================================
    // A control flow attribute wraps its host tag in the corresponding node.
    // The host tag's compiled output becomes the body of the wrapping node.

    #[test]
    fn test_attr_c_if_wraps_host() {
        assert_compile(
            r#"<div c-if="x">hi</div>"#,
            r#"[IfNode(source, (((0, 22,), (ExprHtmlAttr(source, (5, 13,), """cond""", """x""", ("x",)),), ["""<div>hi</div>""",], (),),), ("x",)),]"#,
        );
    }

    #[test]
    fn test_attr_c_for_wraps_host() {
        assert_compile(
            r#"<div c-for="item in items">{{ item }}</div>"#,
            r#"[ForNode(source, (((0, 43,), (ExprHtmlAttr(source, (5, 26,), """each""", """item in items""", ("item", "items",)),), ["""<div>""", ExprNode(source, (27, 37,), """item """, ("item",)), """</div>""",], (),),), ("item", "items",)),]"#,
        );
    }

    #[test]
    fn test_attr_c_if_and_c_for_nest_if_outer() {
        // IF has higher priority than FOR, so the IfNode wraps the ForNode.
        assert_compile(
            r#"<div c-if="x" c-for="item in items">{{ item }}</div>"#,
            r#"[IfNode(source, (((0, 52,), (ExprHtmlAttr(source, (5, 13,), """cond""", """x""", ("x",)),), [ForNode(source, (((0, 52,), (ExprHtmlAttr(source, (14, 35,), """each""", """item in items""", ("item", "items",)),), ["""<div>""", ExprNode(source, (36, 46,), """item """, ("item",)), """</div>""",], (),),), ("item", "x", "items",)),], (),),), ("item", "x", "items",)),]"#,
        );
    }

    // =============================================================================
    // SLOT / FILL
    // =============================================================================
    // SlotNode/FillNode signature:
    //   SlotNode(source, (start, end,), (attrs,), [body], (used_vars,), (introduced_vars,))

    #[test]
    fn test_slot_simple() {
        assert_compile(
            r#"<c-slot name="header" />"#,
            r#"[SlotNode(source, (0, 24,), (StaticHtmlAttr(source, (8, 21,), """name""", """header""", ()),), [], (), ()),]"#,
        );
    }

    #[test]
    fn test_fill_inside_component_sets_contains_fills() {
        // Component with a <c-fill> child sets contains_fills = True.
        assert_compile(
            r#"<c-Card><c-fill name="header">h</c-fill></c-Card>"#,
            r#"[ComponentNode(source, (0, 49,), (), [FillNode(source, (8, 40,), (StaticHtmlAttr(source, (16, 29,), """name""", """header""", ()),), ["""h""",], (), ()),], (), """card""", True),]"#,
        );
    }

    // =============================================================================
    // RAW
    // =============================================================================

    #[test]
    fn test_raw_body_kept_verbatim() {
        // `<c-raw>` becomes a ComponentNode named "raw" whose body is the raw,
        // unparsed text (the `{{ ... }}` is NOT turned into an ExprNode).
        assert_compile(
            "<c-raw>{{ not parsed }}</c-raw>",
            r#"[ComponentNode(source, (0, 31,), (), ["""{{ not parsed }}""",], (), """raw""", False),]"#,
        );
    }

    // =============================================================================
    // WHITESPACE BEHAVIOR
    // =============================================================================
    // Whitespace between template elements is preserved. (Before the `template`
    // grammar rule was made compound-atomic, Pest's implicit inter-element
    // whitespace silently dropped the space immediately after a closing tag.)

    #[test]
    fn test_whitespace_after_closing_tag_is_preserved() {
        // The space between `</div>` and `Bye` is kept.
        assert_compile("<div>x</div> Bye", r#"["""<div>x</div> Bye""",]"#);
    }

    #[test]
    fn test_whitespace_between_tags_is_preserved() {
        // The space between `</div>` and `<span>` is kept (and coalesced into
        // the single static string).
        assert_compile(
            "<div>x</div> <span>y</span>",
            r#"["""<div>x</div> <span>y</span>""",]"#,
        );
    }

    #[test]
    fn test_whitespace_before_tag_is_preserved() {
        // Leading text whitespace (not after a closing tag) is preserved.
        assert_compile("Hi <div>x</div>", r#"["""Hi <div>x</div>""",]"#);
    }
}
