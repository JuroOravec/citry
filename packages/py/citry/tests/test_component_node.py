"""
Tests for ComponentNode rendering (rendering.md phase 3).

A parent template references a child component; ComponentNode resolves the
attributes into the child's kwargs, looks the child up in the parent's Citry
registry, and renders it across a context boundary. Body content (slots/fills)
is a later phase.
"""

# ruff: noqa: ANN

import pytest

from citry import Citry, Component


class TestComponentNodeBasic:
    def test_renders_child_component(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>card</span>"

        class Page(Component):
            citry = c
            template = "<main><c-card /></main>"

        assert Page().render().serialize() == "<main><span>card</span></main>"

    def test_name_lookup_is_case_insensitive(self):
        c = Citry()

        class MyCard(Component):
            citry = c
            template = "<span>ok</span>"

        class Page(Component):
            citry = c
            template = "<main><c-my-card /></main>"

        assert Page().render().serialize() == "<main><span>ok</span></main>"


class TestComponentNodeAttrs:
    def _card_echo(self, c, var):
        """A Card that echoes one kwarg into its template."""

        class Card(Component):
            citry = c
            template = "<span>{{ out }}</span>"

            def template_data(self, kwargs, slots=None, context=None):
                return {"out": kwargs.get(var)}

        return Card

    def test_static_attr_becomes_kwarg(self):
        c = Citry()
        self._card_echo(c, "title")

        class Page(Component):
            citry = c
            template = '<main><c-card title="Hi" /></main>'

        assert Page().render().serialize() == "<main><span>Hi</span></main>"

    def test_dynamic_attr_is_evaluated(self):
        c = Citry()
        self._card_echo(c, "title")

        class Page(Component):
            citry = c
            template = '<main><c-card c-title="who" /></main>'

            def template_data(self, kwargs, slots=None, context=None):
                return {"who": "World"}

        assert Page().render().serialize() == "<main><span>World</span></main>"

    def test_boolean_attr_becomes_true(self):
        c = Citry()
        self._card_echo(c, "disabled")

        class Page(Component):
            citry = c
            template = "<main><c-card disabled /></main>"

        assert Page().render().serialize() == "<main><span>True</span></main>"

    def test_c_bind_spreads_mapping_into_kwargs(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>{{ a }}-{{ b }}</span>"

            def template_data(self, kwargs, slots=None, context=None):
                return {"a": kwargs["a"], "b": kwargs["b"]}

        class Page(Component):
            citry = c
            template = '<main><c-card c-bind="extra" /></main>'

            def template_data(self, kwargs, slots=None, context=None):
                return {"extra": {"a": 1, "b": 2}}

        assert Page().render().serialize() == "<main><span>1-2</span></main>"

    def test_dynamic_attr_value_is_escaped_by_the_child(self):
        # The attr resolves to a raw Python value (unescaped); the child escapes
        # it when rendering it through an ExprNode.
        c = Citry()
        self._card_echo(c, "title")

        class Page(Component):
            citry = c
            template = '<main><c-card c-title="raw" /></main>'

            def template_data(self, kwargs, slots=None, context=None):
                return {"raw": "<b>"}

        assert Page().render().serialize() == "<main><span>&lt;b&gt;</span></main>"

    def test_template_attr_becomes_rendered_kwarg(self):
        # c-body on a component is a nested template, rendered in the parent's
        # scope, passed to the child as a CitryRender kwarg.
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>{{ body }}</span>"

            def template_data(self, kwargs, slots=None, context=None):
                return {"body": kwargs["body"]}

        class Page(Component):
            citry = c
            template = '<main><c-card c-body="<b>{{ x }}</b>" /></main>'

            def template_data(self, kwargs, slots=None, context=None):
                return {"x": "hi"}

        assert Page().render().serialize() == "<main><span><b>hi</b></span></main>"


class TestComponentNodeBoundary:
    def test_child_does_not_inherit_parent_variables(self):
        # A parent variable must not leak into the child's render context.
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>{{ x }}</span>"  # no template_data -> no `x`

        class Page(Component):
            citry = c
            template = "<main><c-card /></main>"

            def template_data(self, kwargs, slots=None, context=None):
                return {"x": "parent-only"}

        with pytest.raises(KeyError):
            Page().render().serialize()

    def test_child_parent_and_root_linkage(self):
        c = Citry()
        seen = {}

        class Card(Component):
            citry = c
            template = "<span>x</span>"

            def template_data(self, kwargs, slots=None, context=None):
                seen["parent"] = self.parent
                seen["root"] = self.root
                return {}

        class Page(Component):
            citry = c
            template = "<main><c-card /></main>"

        Page().render().serialize()
        assert isinstance(seen["parent"], Page)
        assert seen["root"] is seen["parent"]  # parent is the root of this tree


class TestComponentNodeBodyDeferred:
    def test_body_content_raises_not_implemented(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>x</span>"

        class Page(Component):
            citry = c
            template = "<main><c-card>body</c-card></main>"

        with pytest.raises(NotImplementedError):
            Page().render().serialize()

    def test_fill_body_raises_not_implemented(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>x</span>"

        class Page(Component):
            citry = c
            template = '<main><c-card><c-fill name="h">f</c-fill></c-card></main>'

        with pytest.raises(NotImplementedError):
            Page().render().serialize()
