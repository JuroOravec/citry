"""Tests for the Const marker and the const-keyed body cache (skeleton)."""

# ruff: noqa: ANN

from citry import Citry, Component, Const
from citry.constness import const_value, is_const


class TestConstMarker:
    def test_is_const(self):
        assert is_const(Const(3))
        assert not is_const(3)
        assert not is_const("x")

    def test_const_value_unwraps(self):
        assert const_value(Const(3)) == 3
        assert const_value(Const("hi")) == "hi"

    def test_const_value_passthrough_for_plain(self):
        assert const_value(3) == 3
        assert const_value("hi") == "hi"

    def test_repr(self):
        assert repr(Const(3)) == "Const(3)"


class TestConstFlow:
    def test_const_input_renders(self):
        # A Const input passed through template_data must not break rendering.
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None):
                return {"cols": kwargs["cols"]}

        assert Card(cols=Const(3)).render().serialize() == '<p data-cid-c1="">hi</p>'

    def test_const_signature_keys_the_cache(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None):
                return {"cols": kwargs["cols"]}

        # Different const values -> different signatures -> two cache entries.
        Card(cols=Const(3)).render()
        Card(cols=Const(5)).render()
        assert len(c._const_body_cache) == 2

        # Same signature again -> cache hit, no new entry.
        Card(cols=Const(3)).render()
        assert len(c._const_body_cache) == 2

    def test_non_const_var_not_in_signature(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None):
                return {"cols": kwargs["cols"]}

        # Plain (non-Const) values do not enter the signature, so both renders
        # share the empty signature and a single cache entry.
        Card(cols=3).render()
        Card(cols=5).render()
        assert len(c._const_body_cache) == 1

    def test_body_is_equivalent_across_signatures_for_now(self):
        # No folding yet: distinct signatures cache distinct list objects, but
        # their contents are identical.
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None):
                return {"cols": kwargs["cols"]}

        Card(cols=Const(3)).render()
        Card(cols=Const(5)).render()
        bodies = list(c._const_body_cache.values())
        assert bodies[0] == bodies[1]
        assert bodies[0] is not bodies[1]

    def test_clear_empties_the_cache(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

        Card().render()
        assert len(c._const_body_cache) >= 1
        c.clear()
        assert len(c._const_body_cache) == 0

    def test_unhashable_const_value_does_not_crash(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None):
                return {"rows": kwargs["rows"]}

        # A list is unhashable; the signature falls back to a repr stand-in.
        assert Card(rows=Const([1, 2, 3])).render().serialize() == '<p data-cid-c1="">hi</p>'
        assert len(c._const_body_cache) == 1
