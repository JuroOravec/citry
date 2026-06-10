"""
Tests for the value nodes: ExprNode and TemplateNode (rendering.md phase 2).

Covers expression evaluation via safe_eval, autoescaping in both body-text and
attribute positions, the None/SafeString rules, and the embedded-CitryRender /
CitryElement detection. The HTML-attr nodes (StaticHtmlAttr/ExprHtmlAttr/
TemplateHtmlAttr) are phase 3 (they resolve to component kwargs).
"""

# ruff: noqa: ANN

from citry import Citry, Component, Const
from citry.util.html import SafeString


def _html(template, **data):
    """Render a component whose template_data returns `data`; return the HTML."""
    c = Citry()

    class Comp(Component):
        citry = c

        def template_data(self, kwargs, slots=None):
            return dict(data)

    Comp.template = template
    return Comp().render().serialize()


class TestExprNodeEval:
    def test_renders_variable(self):
        assert _html("<p>{{ x }}</p>", x="hello") == '<p data-cid-c1="">hello</p>'

    def test_evaluates_expression(self):
        assert _html("<p>{{ a + b }}</p>", a=2, b=3) == '<p data-cid-c1="">5</p>'

    def test_repeated_render_is_stable(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>{{ x }}</p>"

            def template_data(self, kwargs, slots=None):
                return {"x": "v"}

        el = Comp()
        # Each render mints a fresh id, so the data-cid marker differs
        # between the two renders even though the structure is identical.
        assert el.render().serialize() == '<p data-cid-c1="">v</p>'
        assert el.render().serialize() == '<p data-cid-c2="">v</p>'


class TestExprNodeEscaping:
    def test_escapes_body_text(self):
        assert (
            _html("<p>{{ x }}</p>", x="<b>hi & 'bye'</b>")
            == '<p data-cid-c1="">&lt;b&gt;hi &amp; &#39;bye&#39;&lt;/b&gt;</p>'
        )

    def test_escapes_in_attribute_position(self):
        # c-href becomes a dynamic attribute; the value must be quote-safe.
        assert _html('<a c-href="x">l</a>', x='a"b & c') == '<a href="a&#34;b &amp; c" data-cid-c1="">l</a>'

    def test_none_renders_as_empty_string(self):
        assert _html("<p>{{ x }}</p>", x=None) == '<p data-cid-c1=""></p>'

    def test_safestring_passes_through_unescaped(self):
        assert _html("<p>{{ x }}</p>", x=SafeString("<b>bold</b>")) == '<p data-cid-c1=""><b>bold</b></p>'

    def test_const_value_is_escaped_transparently(self):
        # Const is a transparent proxy: escape sees the underlying value.
        assert _html("<p>{{ x }}</p>", x=Const("<i>")) == '<p data-cid-c1="">&lt;i&gt;</p>'


class TestExprNodeEmbedding:
    def _card(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>{{ label }}</span>"

            def template_data(self, kwargs, slots=None):
                return {"label": "IN"}

        return Card

    def test_embeds_pre_rendered_citry_render(self):
        rendered = self._card()().render()  # a CitryRender
        # Inlined as trusted HTML (the inner <span> tags are NOT re-escaped).
        assert (
            _html("<main>{{ c }}</main>", c=rendered) == '<main data-cid-c2=""><span data-cid-c1="">IN</span></main>'
        )

    def test_auto_renders_a_citry_element(self):
        element = self._card()()  # a CitryElement (not yet rendered)
        assert _html("<main>{{ c }}</main>", c=element) == '<main data-cid-c1=""><span data-cid-c2="">IN</span></main>'


class TestTemplateNode:
    def test_renders_nested_template(self):
        # c-body holds a nested template; it renders against the same context.
        assert (
            _html('<div c-body="<span>{{ x }}</span>">end</div>', x="hi")
            == '<div body="<span>hi</span>" data-cid-c1="">end</div>'
        )

    def test_nested_template_escapes_inner_expression(self):
        assert (
            _html('<div c-body="<span>{{ x }}</span>">end</div>', x="<i>")
            == '<div body="<span>&lt;i&gt;</span>" data-cid-c1="">end</div>'
        )
