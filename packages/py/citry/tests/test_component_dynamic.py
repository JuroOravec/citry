"""
Tests for the ``<c-component>`` (dynamic component) and ``<c-element>``
(dynamic HTML element) built-ins. See docs/design/dynamic_component.md.

The static-`is` forms compile away (covered by the Rust compiler tests in
``crates/citry_template_parser/tests/tag_compiler_dynamic.rs``); the tests
here exercise them end to end plus the full runtime (dynamic) paths.
"""

# ruff: noqa: ANN

import pytest

from citry import Citry, Component, Extension
from citry.component_registry import AlreadyRegistered, NotRegistered


def _chain_template_data(target_name):
    """A ``template_data`` for one chain level, closing over its target's name."""

    def template_data(self, kwargs, slots=None):  # noqa: ARG001
        return {"t": target_name}

    return template_data


def _make_card(c):
    """A simple slotted component used as the dynamic target."""

    class Card(Component):
        citry = c
        template = '<div class="card">{{ title }}: <c-slot /></div>'

        def template_data(self, kwargs, slots=None):
            return {"title": kwargs.get("title", "untitled")}

    return Card


class TestDynamicComponent:
    def test_static_is_renders_component(self):
        c = Citry()
        _make_card(c)

        class Page(Component):
            citry = c
            template = "<c-component is=\"card\" c-title=\"'Hi'\">body</c-component>"

        # Compiled away to <c-card>: same output, no wrapper render
        # (the id counter is c1=Page, c2=Card).
        assert str(Page()) == '<div class="card" data-cid-c2="" data-cid-c1="">Hi: body</div>'

    def test_dynamic_is_with_name_variable(self):
        c = Citry()
        _make_card(c)

        class Page(Component):
            citry = c
            template = "<c-component c-is=\"comp\" c-title=\"'Hi'\">body</c-component>"

            def template_data(self, kwargs, slots=None):
                return {"comp": "card"}

        # Same element output as the static form; the transparent wrapper
        # adds no marker of its own (ids: c1=Page, c2=wrapper, c3=Card).
        assert str(Page()) == '<div class="card" data-cid-c3="" data-cid-c1="">Hi: body</div>'

    def test_dynamic_is_with_component_class(self):
        c = Citry()
        card_cls = _make_card(c)

        class Page(Component):
            citry = c
            template = '<c-component c-is="comp">body</c-component>'

            def template_data(self, kwargs, slots=None):
                return {"comp": card_cls}

        assert str(Page()) == '<div class="card" data-cid-c3="" data-cid-c1="">untitled: body</div>'

    def test_is_via_c_bind_spread(self):
        c = Citry()
        _make_card(c)

        class Page(Component):
            citry = c
            template = "<c-component c-bind=\"{'is': 'card', 'title': 'Spread'}\" />"

        assert str(Page()) == '<div class="card" data-cid-c3="" data-cid-c1="">Spread: </div>'

    def test_named_slots_pass_through(self):
        c = Citry()

        class Panel(Component):
            citry = c
            template = '<div><c-slot name="header">H-FB</c-slot>|<c-slot /></div>'

        class Page(Component):
            citry = c
            template = (
                '<c-component c-is="comp">'
                '<c-fill name="header">HEAD</c-fill>'
                '<c-fill name="default">BODY</c-fill>'
                "</c-component>"
            )

            def template_data(self, kwargs, slots=None):
                return {"comp": "panel"}

        assert str(Page()) == '<div data-cid-c3="" data-cid-c1="">HEAD|BODY</div>'

    def test_fills_the_target_lacks_stay_unused(self):
        c = Citry()
        _make_card(c)

        class Page(Component):
            citry = c
            template = (
                '<c-component c-is="comp">'
                '<c-fill name="default">body</c-fill>'
                '<c-fill name="nonexistent">ignored</c-fill>'
                "</c-component>"
            )

            def template_data(self, kwargs, slots=None):
                return {"comp": "card"}

        rendered = str(Page())
        assert "ignored" not in rendered
        assert "body" in rendered

    def test_unexpected_kwarg_raises_from_target(self):
        c = Citry()

        class Strict(Component):
            citry = c
            template = "<p>{{ title }}</p>"

            class Kwargs:
                title: str

            def template_data(self, kwargs, slots=None):
                return {"title": kwargs.title}

        class Page(Component):
            citry = c
            template = "<c-component c-is=\"comp\" c-title=\"'x'\" c-bogus=\"1\" />"

            def template_data(self, kwargs, slots=None):
                return {"comp": "strict"}

        with pytest.raises(TypeError, match="bogus"):
            str(Page())

    def test_unknown_name_raises_with_element_hint(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-component c-is="comp" />'

            def template_data(self, kwargs, slots=None):
                return {"comp": "no-such-comp"}

        with pytest.raises(NotRegistered, match=r"use <c-element> instead"):
            str(Page())

    def test_missing_is_raises(self):
        c = Citry()

        # `is` absent entirely is a parse error (Rust rules); reaching the
        # built-in without it needs the c-bind spread form.
        class Page(Component):
            citry = c
            template = '<c-component c-bind="{}" />'

        with pytest.raises(TypeError, match="requires an 'is' value"):
            str(Page())

    def test_none_is_raises(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-component c-is="comp" />'

            def template_data(self, kwargs, slots=None):
                return {"comp": None}

        with pytest.raises(TypeError, match="requires an 'is' value"):
            str(Page())

    def test_invalid_is_type_raises(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-component c-is="comp" />'

            def template_data(self, kwargs, slots=None):
                return {"comp": 42}

        with pytest.raises(TypeError, match="got int"):
            str(Page())

    def test_citry_element_as_is_raises(self):
        c = Citry()
        card_cls = _make_card(c)

        class Page(Component):
            citry = c
            template = '<c-component c-is="comp" />'

            def template_data(self, kwargs, slots=None):
                return {"comp": card_cls(title="x")}

        with pytest.raises(TypeError, match=r"Embed it with '\{\{ \.\.\. \}\}'"):
            str(Page())

    def test_provide_flows_through_the_wrapper(self):
        c = Citry()

        class Reader(Component):
            citry = c
            template = "<p>{{ val }}</p>"

            def template_data(self, kwargs, slots=None):
                return {"val": self.inject("theme").mode}

        class Page(Component):
            citry = c
            template = '<c-provide key="theme" mode="dark"><c-component c-is="comp" /></c-provide>'

            def template_data(self, kwargs, slots=None):
                return {"comp": "reader"}

        assert "dark" in str(Page())

    def test_chained_dynamic_components(self):
        # Each wrapper-in-wrapper level adds Python stack frames (the
        # documented limitation in docs/design/dynamic_component.md section
        # 8); realistic chains are a handful deep, and depth 50 must work.
        c = Citry()

        class Leaf(Component):
            citry = c
            template = "leaf"

        prev = "leaf"
        for i in range(50):
            cls_name = f"Level{i}"
            type(
                cls_name,
                (Component,),
                {
                    "citry": c,
                    "template": '<c-component c-is="t" />',
                    "template_data": _chain_template_data(prev),
                },
            )
            prev = cls_name.lower()

        assert "leaf" in str(c.get(prev)())


class TestDynamicElement:
    def test_static_is_renders_element(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element is="section" class="s">inner</c-element>'

        # Compiled away to a literal <section>; the parent's marker lands on
        # it as the root element, like a statically written tag.
        assert str(Page()) == '<section class="s" data-cid-c1="">inner</section>'

    def test_dynamic_is_renders_element(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" class="x">hello {{ w }}</c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "section", "w": "world"}

        assert str(Page()) == '<section class="x" data-cid-c1="">hello world</section>'

    def test_custom_element_name(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" data-x="1">hi</c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "my-widget"}

        assert str(Page()) == '<my-widget data-x="1" data-cid-c1="">hi</my-widget>'

    def test_svg_camel_case_name_renders_verbatim(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag">x</c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "clipPath"}

        assert str(Page()) == '<clipPath data-cid-c1="">x</clipPath>'

    def test_attrs_static_dynamic_and_bind_with_class_merging(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = (
                "<c-element c-is=\"tag\" c-id=\"'el' + '1'\""
                " c-bind=\"{'class': ['a', {'b': True, 'c': False}], 'disabled': True}\" />"
            )

            def template_data(self, kwargs, slots=None):
                return {"tag": "hr"}

        assert str(Page()) == '<hr id="el1" class="a b" disabled data-cid-c1=""/>'

    def test_attr_values_are_escaped(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" c-title="evil">x</c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "span", "evil": '"><script>'}

        assert str(Page()) == '<span title="&#34;&gt;&lt;script&gt;" data-cid-c1="">x</span>'

    def test_explicit_default_fill_renders_as_children(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag"><c-fill name="default">child</c-fill></c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "div"}

        assert str(Page()) == '<div data-cid-c1="">child</div>'

    def test_void_element_stays_compact(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" class="x" />'

            def template_data(self, kwargs, slots=None):
                return {"tag": "br"}

        assert str(Page()) == '<br class="x" data-cid-c1=""/>'

    def test_void_element_with_body_raises(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag">stuff</c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "br"}

        with pytest.raises(ValueError, match="void element 'br' cannot have children"):
            str(Page())

    @pytest.mark.parametrize("bad_tag", ["bad name", "a>b", 'a"b', "1abc", ""])
    def test_invalid_tag_name_raises(self, bad_tag):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" />'

            def template_data(self, kwargs, slots=None):
                return {"tag": bad_tag}

        with pytest.raises((TypeError, ValueError), match="<c-element>"):
            str(Page())

    def test_non_string_tag_raises(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" />'

            def template_data(self, kwargs, slots=None):
                return {"tag": 42}

        with pytest.raises(TypeError, match="naming the HTML tag"):
            str(Page())

    def test_dynamic_named_fill_raises(self):
        c = Citry()

        # A static named fill is a parse error (Rust slot rules); the dynamic
        # `c-name` spelling only resolves at render, where the built-in
        # rejects it.
        class Page(Component):
            citry = c
            template = '<c-element c-is="tag"><c-fill c-name="n">X</c-fill></c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "div", "n": "header"}

        with pytest.raises(ValueError, match="only accepts the default slot"):
            str(Page())

    def test_nested_template_attr_value_raises_on_dynamic_path(self):
        c = Citry()

        # `c-foo="<b>{{ x }}</b>"`-style nested-template values resolve to a
        # CitryRender, which the dynamic path cannot flatten safely; the
        # static-`is` form supports them (it compiles to a real element).
        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" c-foo="<b>{{ x }}</b>" />'

            def template_data(self, kwargs, slots=None):
                return {"tag": "div", "x": "hi"}

        with pytest.raises(TypeError, match="does not support nested-template attribute"):
            str(Page())


class TestAttributeParity:
    """`<c-element>` attributes must render like a statically written element."""

    def _render_stripped(self, comp_cls):
        import re

        return re.sub(r' data-cid-\w+=""', "", str(comp_cls()))

    @pytest.mark.parametrize(
        "attrs",
        [
            'class="a"',
            "c-class=\"['a', {'b': True}]\"",
            "c-style=\"{'color': 'red', 'margin-top': 0}\"",
            'data-x="1" c-data-y="2"',
            'c-disabled="True" c-hidden="False" c-title="None"',
            "c-bind=\"{'a': 'x'}\" c-bind=\"{'b': 'y'}\"",
        ],
    )
    def test_output_matches_static_element(self, attrs):
        c1 = Citry()

        class Dynamic(Component):
            citry = c1
            template = f'<c-element c-is="tag" {attrs}>x</c-element>'

            def template_data(self, kwargs, slots=None):
                return {"tag": "div"}

        c2 = Citry()

        class Static(Component):
            citry = c2
            template = f"<div {attrs}>x</div>"

        assert self._render_stripped(Dynamic) == self._render_stripped(Static)

    def test_on_attrs_resolved_fires_with_element_payload(self):
        calls = []

        class Spy(Extension):
            name = "spy"

            def on_attrs_resolved(self, ctx):
                calls.append((ctx.tag_name, dict(ctx.attrs)))

        c = Citry(extensions=[Spy])

        class Page(Component):
            citry = c
            template = '<c-element c-is="tag" class="x" c-n="1" />'

            def template_data(self, kwargs, slots=None):
                return {"tag": "hr"}

        str(Page())
        assert ("hr", {"class": "x", "n": 1}) in calls


class TestRegistryReservation:
    def test_component_name_is_reserved(self):
        c = Citry()
        with pytest.raises(AlreadyRegistered, match="reserved for the built-in <c-component>"):

            class MyComp(Component):
                citry = c
                name = "component"

    def test_element_class_name_is_reserved(self):
        c = Citry()
        with pytest.raises(AlreadyRegistered, match="reserved for the built-in <c-element>"):

            class Element(Component):
                citry = c

    def test_builtins_are_per_instance(self):
        c1 = Citry()
        c2 = Citry()
        assert c1.get("component") is not c2.get("component")
        assert c1.get("element") is not c2.get("element")

    def test_no_shadowing_between_namespaces(self):
        c = Citry()

        class Table(Component):
            citry = c
            template = "<p>component table</p>"

        class PageComp(Component):
            citry = c
            template = '<c-component c-is="t" />'

            def template_data(self, kwargs, slots=None):
                return {"t": "table"}

        class PageEl(Component):
            citry = c
            template = '<c-element c-is="t">cell</c-element>'

            def template_data(self, kwargs, slots=None):
                return {"t": "table"}

        assert "component table" in str(PageComp())
        assert str(PageEl()).startswith("<table")
