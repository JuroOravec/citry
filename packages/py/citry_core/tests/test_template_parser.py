"""
Tests for the V3 template parser Python surface.

Covers: parse_template, compile_template, AST inspection, round-trip
(parse -> compile -> exec with stub nodes), error handling, and the
lang parameter.
"""

# ruff: noqa: S102,ANN

import pytest

from citry_core.template_parser import (
    TagRules,
    Template,
    compile_template,
    parse_template,
)

# =========================================================================
# Dummy runtime node classes
# =========================================================================
#
# The compiler emits source code that instantiates runtime node classes by
# name. citry_core owns only the parser and compiler; the real node classes
# live in the higher-level ``citry`` package, which depends on citry_core
# (not the other way around). To keep these tests within citry_core's own
# layer, we define minimal stand-ins here.
#
# Each constructor mirrors the exact argument order the compiler emits (the
# compiler output is the contract). The stubs only capture those arguments as
# attributes so the round-trip tests can assert on the resulting node tree.


class ExprNode:
    def __init__(self, source, position, expr, used_vars):
        self.source = source
        self.position = position
        self.expr = expr
        self.used_vars = used_vars


class TemplateNode:
    def __init__(self, source, position, expr, used_vars):
        self.source = source
        self.position = position
        self.expr = expr
        self.used_vars = used_vars


class StaticHtmlAttr:
    def __init__(self, source, position, key, value, used_vars):
        self.source = source
        self.position = position
        self.key = key
        self.value = value
        self.used_vars = used_vars


class ExprHtmlAttr:
    def __init__(self, source, position, key, expr, used_vars):
        self.source = source
        self.position = position
        self.key = key
        self.expr = expr
        self.used_vars = used_vars


class TemplateHtmlAttr:
    def __init__(self, source, position, key, template, used_vars):
        self.source = source
        self.position = position
        self.key = key
        self.template = template
        self.used_vars = used_vars


class ComponentNode:
    def __init__(self, source, position, attrs, body, used_vars, name, contains_fills):
        self.source = source
        self.position = position
        self.attrs = attrs
        self.body = body
        self.used_vars = used_vars
        self.name = name
        self.contains_fills = contains_fills


class IfNode:
    def __init__(self, source, branches, used_vars):
        self.source = source
        self.branches = branches
        self.used_vars = used_vars


class ForNode:
    def __init__(self, source, branches, used_vars):
        self.source = source
        self.branches = branches
        self.used_vars = used_vars


class SlotNode:
    def __init__(self, source, position, attrs, body, used_vars, introduced_vars):
        self.source = source
        self.position = position
        self.attrs = attrs
        self.body = body
        self.used_vars = used_vars
        self.introduced_vars = introduced_vars


class FillNode:
    def __init__(self, source, position, attrs, body, used_vars, introduced_vars):
        self.source = source
        self.position = position
        self.attrs = attrs
        self.body = body
        self.used_vars = used_vars
        self.introduced_vars = introduced_vars


# =========================================================================
# parse_template - basic parsing
# =========================================================================


class TestParseTemplate:
    def test_plain_text(self):
        t = parse_template("Hello, world!")
        assert isinstance(t, Template)
        assert len(t.elements) == 1

    def test_expression(self):
        t = parse_template("{{ name }}")
        assert len(t.elements) == 1
        assert len(t.used_variables) == 1
        assert t.used_variables[0].content == "name"

    def test_html_tag(self):
        t = parse_template("<div>hi</div>")
        assert len(t.elements) == 1
        node = t.elements[0]._0
        assert node.name == "div"

    def test_component(self):
        t = parse_template('<c-Card title="Hello" />')
        assert len(t.elements) == 1
        node = t.elements[0]._0
        assert node.name == "c-Card"
        assert len(node.start_tag.attrs) == 1
        assert node.start_tag.attrs[0].key.content == "title"

    def test_expression_variables_tracked(self):
        t = parse_template("{{ a + b }}")
        var_names = [v.content for v in t.used_variables]
        assert "a" in var_names
        assert "b" in var_names

    def test_control_flow_if(self):
        t = parse_template('<c-if cond="x">yes</c-if>')
        assert len(t.elements) == 1

    def test_control_flow_for(self):
        t = parse_template('<c-for each="item in items">{{ item }}</c-for>')
        assert len(t.elements) == 1

    def test_slot_and_fill(self):
        t = parse_template('<c-Card><c-fill name="header">h</c-fill></c-Card>')
        assert len(t.elements) == 1
        comp = t.elements[0]._0
        assert comp.contains_fills is True

    def test_raw(self):
        t = parse_template("<c-raw>{{ not parsed }}</c-raw>")
        assert len(t.elements) == 1

    def test_comment_tracked(self):
        t = parse_template("Hello {# comment #} world")
        assert len(t.comments) == 1
        assert t.comments[0].value.content == " comment "

    def test_empty_template(self):
        t = parse_template("")
        assert len(t.elements) == 0


# =========================================================================
# compile_template - check generated source
# =========================================================================


class TestCompileTemplate:
    def test_plain_text(self):
        t = parse_template("Hello!")
        code = compile_template(t)
        assert "def generate_template():" in code
        assert '"""Hello!"""' in code

    def test_expression(self):
        t = parse_template("{{ x }}")
        code = compile_template(t)
        assert "ExprNode" in code
        assert '"x"' in code

    def test_component(self):
        t = parse_template("<c-Card />")
        code = compile_template(t)
        assert "ComponentNode" in code
        assert '"""card"""' in code

    def test_if_node(self):
        t = parse_template('<c-if cond="x">yes</c-if>')
        code = compile_template(t)
        assert "IfNode" in code

    def test_for_node(self):
        t = parse_template('<c-for each="item in items">{{ item }}</c-for>')
        code = compile_template(t)
        assert "ForNode" in code

    def test_static_html_attr(self):
        t = parse_template('<c-Card title="Hello" />')
        code = compile_template(t)
        assert "StaticHtmlAttr" in code

    def test_expr_html_attr(self):
        t = parse_template('<c-Card c-title="t" />')
        code = compile_template(t)
        assert "ExprHtmlAttr" in code


# =========================================================================
# Round-trip: parse -> compile -> exec with stub nodes
# =========================================================================


class TestRoundTrip:
    @staticmethod
    def _exec_template(input_str):
        """Parse, compile, exec, and return the body list."""
        t = parse_template(input_str)
        code = compile_template(t)
        ns = {
            "source": input_str,
            "ExprNode": ExprNode,
            "TemplateNode": TemplateNode,
            "ComponentNode": ComponentNode,
            "IfNode": IfNode,
            "ForNode": ForNode,
            "SlotNode": SlotNode,
            "FillNode": FillNode,
            "StaticHtmlAttr": StaticHtmlAttr,
            "ExprHtmlAttr": ExprHtmlAttr,
            "TemplateHtmlAttr": TemplateHtmlAttr,
        }
        exec(code, ns)
        return ns["generate_template"]()

    def test_plain_text(self):
        body = self._exec_template("Hello!")
        assert body == ["Hello!"]

    def test_expression(self):
        body = self._exec_template("{{ x }}")
        assert len(body) == 1
        assert isinstance(body[0], ExprNode)
        assert body[0].used_vars == ("x",)

    def test_text_and_expression(self):
        body = self._exec_template("Hello {{ name }}!")
        assert len(body) == 3
        assert body[0] == "Hello "
        assert isinstance(body[1], ExprNode)
        assert body[2] == "!"

    def test_component(self):
        body = self._exec_template("<c-Card />")
        assert len(body) == 1
        assert isinstance(body[0], ComponentNode)
        assert body[0].name == "card"

    def test_component_with_static_attr(self):
        body = self._exec_template('<c-Card title="Hello" />')
        comp = body[0]
        assert isinstance(comp, ComponentNode)
        assert len(comp.attrs) == 1
        assert isinstance(comp.attrs[0], StaticHtmlAttr)

    def test_if_node(self):
        body = self._exec_template('<c-if cond="x">yes</c-if>')
        assert len(body) == 1
        assert isinstance(body[0], IfNode)
        assert len(body[0].branches) == 1

    def test_if_elif_else(self):
        body = self._exec_template('<c-if cond="x">a</c-if><c-elif cond="y">b</c-elif><c-else>c</c-else>')
        assert isinstance(body[0], IfNode)
        assert len(body[0].branches) == 3

    def test_for_node(self):
        body = self._exec_template('<c-for each="item in items">{{ item }}</c-for>')
        assert isinstance(body[0], ForNode)

    def test_for_with_empty(self):
        body = self._exec_template('<c-for each="item in items">{{ item }}</c-for><c-empty>none</c-empty>')
        assert isinstance(body[0], ForNode)
        assert len(body[0].branches) == 2

    def test_slot(self):
        body = self._exec_template('<c-slot name="header" />')
        assert isinstance(body[0], SlotNode)

    def test_fill_inside_component(self):
        body = self._exec_template('<c-Card><c-fill name="header">h</c-fill></c-Card>')
        comp = body[0]
        assert isinstance(comp, ComponentNode)
        assert comp.contains_fills is True
        assert len(comp.body) == 1
        assert isinstance(comp.body[0], FillNode)

    def test_static_html_coalesced(self):
        body = self._exec_template("<div>hi</div>")
        assert body == ["<div>hi</div>"]

    def test_raw(self):
        body = self._exec_template("<c-raw>{{ not parsed }}</c-raw>")
        assert isinstance(body[0], ComponentNode)
        assert body[0].name == "raw"
        assert body[0].body == ["{{ not parsed }}"]

    def test_nested_components(self):
        body = self._exec_template("<c-Outer><c-Inner /></c-Outer>")
        outer = body[0]
        assert isinstance(outer, ComponentNode)
        assert outer.name == "outer"
        inner = outer.body[0]
        assert isinstance(inner, ComponentNode)
        assert inner.name == "inner"


# =========================================================================
# Error handling
# =========================================================================


class TestErrors:
    def test_unclosed_tag_raises_syntax_error(self):
        with pytest.raises(SyntaxError):
            parse_template("<c-my-tag>")

    def test_mismatched_tags_raises_syntax_error(self):
        with pytest.raises(SyntaxError):
            parse_template("<div></span>")

    def test_unknown_lang_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown language"):
            parse_template("hello", lang="cobol")


# =========================================================================
# Lang parameter
# =========================================================================


class TestLangParameter:
    def test_default_is_python(self):
        t = parse_template("{{ x }}")
        assert len(t.used_variables) == 1

    def test_explicit_python(self):
        t = parse_template("{{ x }}", lang="python")
        assert len(t.used_variables) == 1

    def test_js_parses_text_only(self):
        # JS lang stub is structural only; expressions raise "not yet implemented".
        # But text-only templates parse fine with any lang.
        t = parse_template("<div>hi</div>", lang="js")
        assert len(t.elements) == 1

    def test_js_expression_not_implemented(self):
        # JS expression parsing is a stub and raises SyntaxError.
        with pytest.raises(SyntaxError, match="not yet implemented"):
            parse_template("{{ x }}", lang="js")

    def test_javascript_alias(self):
        # "javascript" is accepted as an alias for "js".
        t = parse_template("<div>hi</div>", lang="javascript")
        assert len(t.elements) == 1


# =========================================================================
# TagRules (user_rules parameter)
# =========================================================================


class TestTagRules:
    def test_allowed_attrs_passes(self):
        rules = {"c-card": TagRules(allowed_attrs=[["title"]])}
        t = parse_template('<c-card title="hi"></c-card>', user_rules=rules)
        assert len(t.elements) == 1

    def test_disallowed_attr_raises(self):
        rules = {"c-card": TagRules(allowed_attrs=[["title"]])}
        with pytest.raises(SyntaxError):
            parse_template('<c-card bogus="no"></c-card>', user_rules=rules)

    def test_required_attr_missing_raises(self):
        rules = {"c-card": TagRules(required_attrs=[["title"]])}
        with pytest.raises(SyntaxError):
            parse_template("<c-card></c-card>", user_rules=rules)
