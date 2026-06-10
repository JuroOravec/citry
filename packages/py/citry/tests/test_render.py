"""
Tests for the CitryRender / CitryContext rendering structs (skeleton).

These cover the three-phase pipeline shape (see docs/design/rendering.md):
``Component(...) -> CitryElement``, ``.render() -> CitryRender``,
``.serialize() -> str``, plus the convenience coercions. Node rendering and
the dependency flow are later phases.
"""

# ruff: noqa: ANN

from citry import Citry, CitryContext, CitryElement, CitryRender, Component


def _card(template="<p>hi</p>"):
    """Build a CitryElement for a single-template component (fresh Citry each call)."""
    c = Citry()

    class Card(Component):
        citry = c

    Card.template = template
    return Card()


class TestRenderReturnsCitryRender:
    def test_render_returns_citry_render(self):
        rendered = _card().render()
        assert isinstance(rendered, CitryRender)

    def test_render_is_not_a_string(self):
        # The whole point of the split: render() yields an object, not HTML.
        assert not isinstance(_card().render(), str)

    def test_citry_render_carries_context(self):
        rendered = _card().render()
        assert isinstance(rendered.context, CitryContext)

    def test_each_render_is_a_fresh_object(self):
        el = _card()
        assert el.render() is not el.render()


class TestSerialize:
    def test_serialize_joins_static_template(self):
        assert _card("<p>hi</p>").render().serialize() == '<p data-cid-c1="">hi</p>'

    def test_serialize_is_repeatable(self):
        rendered = _card("<p>hi</p>").render()
        assert rendered.serialize() == '<p data-cid-c1="">hi</p>'
        assert rendered.serialize() == '<p data-cid-c1="">hi</p>'

    def test_serialize_joins_multiple_parts(self):
        # A CitryRender joins its parts in order...
        ctx = CitryContext()
        rendered = CitryRender(parts=["<div>", "a", "b", "</div>"], context=ctx)
        assert rendered.serialize() == "<div>ab</div>"

    def test_serialize_recurses_into_nested_render(self):
        # ...and a nested CitryRender part is serialized recursively (this is
        # how an embedded pre-rendered subtree inlines its HTML).
        ctx = CitryContext()
        inner = CitryRender(parts=["<span>inner</span>"], context=ctx)
        outer = CitryRender(parts=["<p>", inner, "</p>"], context=ctx)
        assert outer.serialize() == "<p><span>inner</span></p>"


class TestCoercions:
    def test_str_of_render_serializes(self):
        rendered = _card("<p>hi</p>").render()
        assert str(rendered) == '<p data-cid-c1="">hi</p>'

    def test_bytes_of_render_serializes(self):
        rendered = _card("<p>hi</p>").render()
        assert bytes(rendered) == b'<p data-cid-c1="">hi</p>'

    def test_str_of_element_runs_full_chain(self):
        # str(Component(...)) goes element -> render -> serialize with defaults.
        el = _card("<p>hi</p>")
        assert isinstance(el, CitryElement)
        assert str(el) == '<p data-cid-c1="">hi</p>'


class TestContext:
    def test_context_holds_template_variables(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None):
                return {"title": "Hello", "count": 3}

        rendered = Card(x=1).render()
        assert rendered.context.variables == {"title": "Hello", "count": 3}

    def test_extra_starts_empty(self):
        # The tree-wide extension scratch space is empty in this skeleton.
        rendered = _card().render()
        assert rendered.context.extra == {}

    def test_no_template_yields_empty_render(self):
        c = Citry()

        class Empty(Component):
            citry = c

        rendered = Empty().render()
        assert isinstance(rendered, CitryRender)
        assert rendered.serialize() == ""
