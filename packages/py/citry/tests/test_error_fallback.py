"""
Tests for the ``<c-error-fallback>`` built-in component
(docs/design/on_render.md section 7): an error boundary that catches render
errors in its guarded content (the default slot) and shows the ``fallback``
attribute or the ``fallback`` fill instead.
"""

import pytest

from citry import AlreadyRegistered, Citry, Component


def _make_failing(c):
    class Failing(Component):
        citry = c
        template = "<i>x</i>"

        def template_data(self, kwargs, slots=None):
            raise ValueError("boom")

    return Failing


class TestErrorFallback:
    def test_no_error_renders_content(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<main><c-error-fallback fallback="Oops"><b>all good</b></c-error-fallback></main>'

        html = Page().render().serialize()
        assert ">all good</b>" in html
        assert "Oops" not in html

    def test_fallback_attribute_on_child_component_error(self):
        c = Citry()
        _make_failing(c)

        class Page(Component):
            citry = c
            template = '<main><c-error-fallback fallback="Oops"><c-failing /></c-error-fallback></main>'

        html = Page().render().serialize()
        assert "Oops" in html
        assert "<i>" not in html

    def test_fallback_attribute_on_synchronous_content_error(self):
        # The guarded content renders inside the boundary's own body walk; a
        # plain expression error there is caught too.
        c = Citry()

        class Page(Component):
            citry = c
            template = '<main><c-error-fallback fallback="Oops"><b>{{ broken() }}</b></c-error-fallback></main>'

            def template_data(self, kwargs, slots=None):
                def boom():
                    raise ValueError("sync boom")

                return {"broken": boom}

        html = Page().render().serialize()
        assert "Oops" in html

    def test_fallback_slot_receives_error_as_data(self):
        c = Citry()
        _make_failing(c)

        class Page(Component):
            citry = c
            template = (
                "<main><c-error-fallback>"
                '<c-fill name="default"><c-failing /></c-fill>'
                '<c-fill name="fallback" data="d"><p>Caught: {{ d["error"] }}</p></c-fill>'
                "</c-error-fallback></main>"
            )

        html = Page().render().serialize()
        assert ">Caught: " in html
        assert "boom" in html

    def test_fallback_slot_from_python_gets_error_object(self):
        caught = []
        c = Citry()
        failing = _make_failing(c)
        error_fallback = c.registry.get("error-fallback")

        def fallback(ctx):
            caught.append(ctx.data["error"])
            return "recovered"

        html = (
            error_fallback(
                slots={"default": lambda _ctx: failing(), "fallback": fallback},
            )
            .render()
            .serialize()
        )

        assert "recovered" in html
        assert isinstance(caught[0], ValueError)

    def test_attribute_and_slot_together_raise(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = (
                '<main><c-error-fallback fallback="x">'
                '<c-fill name="default"><i>y</i></c-fill>'
                '<c-fill name="fallback">z</c-fill>'
                "</c-error-fallback></main>"
            )

        with pytest.raises(RuntimeError, match="give only one"):
            Page().render()

    def test_no_fallback_renders_nothing_on_error(self):
        c = Citry()
        _make_failing(c)

        class Page(Component):
            citry = c
            template = "<main>before<c-error-fallback><c-failing /></c-error-fallback>after</main>"

        html = Page().render().serialize()
        assert "before" in html
        assert "after" in html
        assert "<i>" not in html

    def test_rest_of_page_renders_around_caught_error(self):
        c = Citry()
        _make_failing(c)

        class Aside(Component):
            citry = c
            template = "<aside>untouched</aside>"

        class Page(Component):
            citry = c
            template = '<main><c-error-fallback fallback="Oops"><c-failing /></c-error-fallback><c-aside /></main>'

        html = Page().render().serialize()
        assert "Oops" in html
        assert ">untouched</aside>" in html

    def test_nested_boundaries_inner_wins(self):
        c = Citry()
        _make_failing(c)

        class Page(Component):
            citry = c
            template = (
                '<main><c-error-fallback fallback="outer">'
                '<c-error-fallback fallback="inner"><c-failing /></c-error-fallback>'
                "</c-error-fallback></main>"
            )

        html = Page().render().serialize()
        assert "inner" in html
        assert "outer" not in html

    def test_failing_fallback_bubbles_to_outer_boundary(self):
        c = Citry()
        _make_failing(c)

        class Inner(Component):
            citry = c
            template = (
                "<c-error-fallback>"
                '<c-fill name="default"><c-failing /></c-fill>'
                '<c-fill name="fallback">{{ also_broken() }}</c-fill>'
                "</c-error-fallback>"
            )

            def template_data(self, kwargs, slots=None):
                def boom2():
                    raise ValueError("fallback boom")

                return {"also_broken": boom2}

        class Page(Component):
            citry = c
            template = '<main><c-error-fallback fallback="outer caught"><c-inner /></c-error-fallback></main>'

        html = Page().render().serialize()
        assert "outer caught" in html

    def test_escaped_error_names_guarded_child(self):
        # With no boundary handling it, the error's path names the failing
        # component inside the boundary.
        c = Citry()
        _make_failing(c)

        class Page(Component):
            citry = c
            template = "<main><c-error-fallback><c-failing /></c-error-fallback></main>"

        class Bare(Component):
            citry = c
            template = "<main><c-failing /></main>"

        with pytest.raises(ValueError, match="boom") as exc_info:
            Bare().render()

        assert "Bare > Failing" in exc_info.value.args[0]

    def test_unexpected_kwargs_rejected(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<main><c-error-fallback bogus="x"><b>y</b></c-error-fallback></main>'

        with pytest.raises(Exception, match="bogus"):
            Page().render()

    def test_name_is_reserved(self):
        c = Citry()

        with pytest.raises(AlreadyRegistered, match="error-fallback"):

            class ErrorFallback(Component):
                citry = c
                template = "<p>impostor</p>"
