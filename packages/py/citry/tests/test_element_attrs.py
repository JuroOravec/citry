"""
Tests for dynamic attribute rendering on plain HTML elements
(docs/design/html_attrs.md): the ``ElementAttrsNode`` runtime node, the
``c-bind`` spread, True/False/None attribute values, class/style merging
across sources, the ``on_attrs_resolved`` extension hook, and how attribute
regions take part in the Const precompute.
"""

# ruff: noqa: ANN

import re

import pytest

from citry import Citry, Component, Const, Extension
from citry.component_render import _compile_nested_template
from citry.constness import precompute_const_parts
from citry.nodes import ElementAttrsNode

_CID_RE = re.compile(r' data-cid-\w+=""')


def _html(template, **data):
    """Render a component whose template_data returns ``data``; strip cid markers."""
    c = Citry()

    class Comp(Component):
        citry = c

        def template_data(self, kwargs, slots):
            return dict(data)

    Comp.template = template
    return _CID_RE.sub("", Comp().render().serialize())


class TestBooleanValues:
    def test_true_renders_bare_attribute(self):
        assert _html('<button c-disabled="x">go</button>', x=True) == "<button disabled>go</button>"

    def test_false_omits_attribute(self):
        assert _html('<button c-disabled="x">go</button>', x=False) == "<button>go</button>"

    def test_none_omits_attribute(self):
        assert _html('<button c-disabled="x">go</button>', x=None) == "<button>go</button>"

    def test_value_less_dynamic_attribute_is_rejected(self):
        # A dynamic attribute's value is an expression, so a bare or empty
        # one has nothing to evaluate and is almost certainly a mistake (the
        # user meant the static `foo`, or forgot the value). Parse-time error.
        with pytest.raises(SyntaxError, match="must have a non-empty value"):
            _html("<div c-foo>hi</div>")
        with pytest.raises(SyntaxError, match="must have a non-empty value"):
            _html('<div c-foo="">hi</div>')

    def test_value_less_attr_on_component_is_rejected(self):
        # Same rule on component tags.
        c = Citry()

        class Child(Component):
            citry = c
            template = "x"

        class Parent(Component):
            citry = c
            template = "<c-Child c-foo />"

        with pytest.raises(SyntaxError, match="must have a non-empty value"):
            Parent().render()

    def test_value_less_control_flow_shorthand_still_works(self):
        # c-else / c-empty take no value by design and stay allowed.
        assert _html('<p c-if="x">a</p><p c-else>b</p>', x=False) == "<p>b</p>"
        assert _html('<li c-for="i in items">{{ i }}</li><li c-empty>none</li>', items=[]) == "<li>none</li>"

    def test_extension_built_attr_with_true_value_resolves_true(self):
        # Node classes are public API: an extension building an ExprHtmlAttr
        # by hand (via on_template_compiled) may pass `True` as the boolean
        # form. There is nothing to evaluate; the attribute is simply on.
        from citry.citry_context import CitryContext
        from citry.nodes import ExprHtmlAttr

        attr = ExprHtmlAttr("", (0, 0), "c-foo", True, ())  # noqa: FBT003 (the compiler emits positional args)
        assert attr.resolve(CitryContext()) is True


class TestCBindSpread:
    def test_spreads_mapping_onto_element(self):
        tpl = """<div c-bind="{'class': 'btn', 'disabled': True, 'data-id': item['id']}">y</div>"""
        assert _html(tpl, item={"id": 123}) == '<div class="btn" disabled data-id="123">y</div>'

    def test_later_bind_wins_for_plain_keys(self):
        tpl = """<div c-bind="{'id': 'first'}" c-bind="{'id': 'second'}">y</div>"""
        assert _html(tpl) == '<div id="second">y</div>'

    def test_source_order_decides_against_static_attrs(self):
        # A static attr after a dynamic one wins; static vs dynamic makes no
        # difference, only source order does.
        assert _html("<div c-bind=\"{'id': 'dyn'}\" id=\"static\">y</div>") == '<div id="static">y</div>'

    def test_attribute_position_is_first_seen(self):
        tpl = """<div id="a" class="x" c-bind="{'id': 'b'}">y</div>"""
        assert _html(tpl) == '<div id="b" class="x">y</div>'

    def test_non_mapping_raises_type_error(self):
        with pytest.raises(TypeError, match="c-bind on <div> must resolve to a mapping"):
            _html('<div c-bind="x">y</div>', x=42)

    def test_none_contributes_nothing(self):
        # An optional attribute dict that is None is a no-op, so the call site
        # needs no `or {}` guard (matches Vue's `v-bind="null"`). None is the
        # only non-mapping value allowed; other types still raise (above).
        assert _html('<div c-bind="attrs" id="x">y</div>', attrs=None) == '<div id="x">y</div>'
        assert _html('<div c-bind="a" c-bind="b">y</div>', a=None, b={"id": "z"}) == '<div id="z">y</div>'


class TestClassAndStyleMerging:
    def test_class_merges_across_sources(self):
        tpl = """<div c-bind="{'class': 'from-bind'}" c-class="'override'">y</div>"""
        assert _html(tpl) == '<div class="from-bind override">y</div>'

    def test_interlacing_example(self):
        # The README "Attribute spreading" example: class merges all three
        # contributions, id keeps the last one.
        tpl = (
            '<div class="default"'
            " c-bind=\"{'class': 'from-bind', 'id': 'first'}\""
            " c-class=\"'override'\""
            " c-bind=\"{'id': 'second'}\""
            ">y</div>"
        )
        assert _html(tpl) == '<div class="default from-bind override" id="second">y</div>'

    def test_none_class_contributes_nothing(self):
        tpl = """<div c-bind="{'class': None}" c-class="'btn'">y</div>"""
        assert _html(tpl) == '<div class="btn">y</div>'

    def test_class_structured_value(self):
        assert _html("<div c-class=\"['btn', {'active': ok}]\">y</div>", ok=False) == '<div class="btn">y</div>'
        assert _html("<div c-class=\"['btn', {'active': ok}]\">y</div>", ok=True) == '<div class="btn active">y</div>'

    def test_style_merges_none_skips_false_removes(self):
        tpl = """<div class="a" c-style="s" c-bind="extra">y</div>"""
        out = _html(tpl, s={"color": None}, extra={"style": "color: blue"})
        assert out == '<div class="a" style="color: blue;">y</div>'

    def test_style_structured_value(self):
        assert _html("<div c-style=\"{'color': 'red', 'width': False}\">y</div>") == '<div style="color: red;">y</div>'


class TestEscaping:
    def test_values_are_escaped(self):
        assert _html('<div c-title="t">y</div>', t='a " b') == '<div title="a &#34; b">y</div>'

    def test_class_expression_strings_are_escaped(self):
        assert _html('<div c-class="cls">y</div>', cls='"><script>') == '<div class="&#34;&gt;&lt;script&gt;">y</div>'


class TestOnAttrsResolvedHook:
    def test_hook_rewrites_resolved_attrs(self):
        class Rewriter(Extension):
            name = "rewriter"

            def on_attrs_resolved(self, ctx):
                attrs = dict(ctx.attrs)
                attrs["data-tag"] = ctx.tag_name
                return attrs

        c = Citry(extensions=[Rewriter])

        class Comp(Component):
            citry = c
            template = "<span c-class=\"'x'\">y</span>"

        out = _CID_RE.sub("", Comp().render().serialize())
        assert out == '<span class="x" data-tag="span">y</span>'

    def test_hook_sees_normalized_class_and_booleans(self):
        seen = {}

        class Spy(Extension):
            name = "spy"

            def on_attrs_resolved(self, ctx):
                seen.update(ctx.attrs)

        c = Citry(extensions=[Spy])

        class Comp(Component):
            citry = c
            template = '<div c-class="[\'a\', {\'b\': True}]" c-hidden="False" c-open="True">y</div>'

        Comp().render().serialize()
        assert seen == {"class": "a b", "open": True}

    def test_hook_not_fired_for_static_only_elements(self):
        calls = []

        class Spy(Extension):
            name = "spy"

            def on_attrs_resolved(self, ctx):
                calls.append(ctx.tag_name)

        c = Citry(extensions=[Spy])

        class Comp(Component):
            citry = c
            template = '<div class="static"><p c-class="\'x\'">y</p></div>'

        Comp().render().serialize()
        # Only the <p> has a dynamic attribute; the static <div> never
        # resolves attributes at render time.
        assert calls == ["p"]


class TestConstPrecomputing:
    def _body(self, template):
        return _compile_nested_template(template, None)()

    def test_literal_attr_region_precomputes_to_text(self):
        body = self._body("<div c-class=\"['a', 'b']\">hi</div>")
        assert any(isinstance(item, ElementAttrsNode) for item in body)
        precomputed = precompute_const_parts(body, {})
        assert precomputed == ['<div class="a b">hi</div>']

    def test_const_marked_variable_precomputes(self):
        body = self._body('<div c-class="cls">hi</div>')
        precomputed = precompute_const_parts(body, {"cls": Const("btn")})
        assert precomputed == ['<div class="btn">hi</div>']

    def test_dynamic_variable_keeps_node(self):
        body = self._body('<div c-class="cls">hi</div>')
        precomputed = precompute_const_parts(body, {})
        assert any(isinstance(item, ElementAttrsNode) for item in precomputed)

    def test_precompute_attrs_false_keeps_literal_region(self):
        # The caller passes precompute_attrs=False when an extension implements
        # on_attrs_resolved, so the hook is not baked out of the body.
        body = self._body("<div c-class=\"['a', 'b']\">hi</div>")
        precomputed = precompute_const_parts(body, {}, precompute_attrs=False)
        assert any(isinstance(item, ElementAttrsNode) for item in precomputed)

    def test_subscribed_hook_still_runs_with_const_inputs(self):
        # End to end: with a hook installed, a Const input must not bake the
        # attr region, and the hook output must appear on every render.
        class Rewriter(Extension):
            name = "rewriter"

            def on_attrs_resolved(self, ctx):
                return {**ctx.attrs, "data-x": "1"}

        c = Citry(extensions=[Rewriter])

        class Comp(Component):
            citry = c
            template = '<div c-class="cls">hi</div>'

            class Kwargs:
                cls: str

            def template_data(self, kwargs, slots):
                return {"cls": kwargs.cls}

        first = _CID_RE.sub("", Comp(cls=Const("btn")).render().serialize())
        second = _CID_RE.sub("", Comp(cls=Const("btn")).render().serialize())
        assert first == second == '<div class="btn" data-x="1">hi</div>'


class TestConstInsideClassStyleList:
    """
    A ``Const``-marked string nested inside a class or style *list* must
    normalize like a plain string. A marker is a transparent proxy that
    reaches the normalizer's string branch but breaks its internal regex
    unless unwrapped (the value layer handles this in ``attrs.py``).
    """

    def test_explicit_const_in_class_list(self):
        assert _html("<div c-class=\"[a, 'b']\">y</div>", a=Const("a")) == '<div class="a b">y</div>'

    def test_explicit_const_in_style_list(self):
        out = _html("<div c-style=\"[s, {'color': 'red'}]\">y</div>", s=Const("width: 1px"))
        assert out == '<div style="width: 1px; color: red;">y</div>'

    def test_auto_const_static_attr_passed_into_class_list(self):
        # The benchmark-relevant path: a static attr on a component tag is
        # auto-marked Const, and the child forwards it unchanged into a class
        # list. Before the fix this raised TypeError in the normalizer.
        c = Citry()

        class Badge(Component):
            citry = c

            class Kwargs:
                tone: str

            def template_data(self, kwargs, slots):
                # raw_kwargs keeps the marker; tone flows into a class list.
                return {"tone": self.raw_kwargs["tone"]}

            template = "<span c-class=\"['badge', tone]\">x</span>"

        class Page(Component):
            citry = c
            template = '<c-Badge tone="ok" />'

        assert _CID_RE.sub("", Page().render().serialize()) == '<span class="badge ok">x</span>'
