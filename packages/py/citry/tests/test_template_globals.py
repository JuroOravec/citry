"""
Tests for ``template_globals``: variables exposed to every component's template
without being returned from each ``template_data()``.

Set them at construction (``Citry(template_globals=...)``) or change them on a
live instance through ``citry.template_globals`` (a plain dict). A component's
own ``template_data`` wins on a key clash, so globals act as defaults.
"""

import pytest

from citry import Citry, Component
from citry import citry as default_instance


class TestTemplateGlobalsBasics:
    def test_global_is_visible_without_template_data(self):
        app = Citry(template_globals={"site_name": "Acme"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ site_name }}</p>
            """

        assert "Acme" in Card().render().serialize()

    def test_global_reaches_every_component_in_the_tree(self):
        # The headline value: a global crosses the component boundary that
        # template variables normally do not, so a nested child sees it too
        # without the parent forwarding it.
        app = Citry(template_globals={"brand": "Acme"})

        class Card(Component):
            citry = app
            template = """
            <span>{{ brand }}</span>
            """

        class Page(Component):
            citry = app
            template = """
            <main>{{ brand }}<c-card /></main>
            """

        html = Page().render().serialize()

        assert html.count("Acme") == 2

    def test_each_instance_keeps_its_own_globals(self):
        app_a = Citry(template_globals={"x": "A"})
        app_b = Citry(template_globals={"x": "B"})

        class CardA(Component):
            citry = app_a
            template = """
            <p>{{ x }}</p>
            """

        class CardB(Component):
            citry = app_b
            template = """
            <p>{{ x }}</p>
            """

        assert "A" in CardA().render().serialize()
        assert "B" in CardB().render().serialize()

    def test_no_globals_by_default(self):
        app = Citry()

        assert app.template_globals == {}


class TestTemplateGlobalsConfiguration:
    def test_globals_can_be_added_after_construction(self):
        # An instance built without globals (like the import-time default) can
        # still be configured afterward.
        app = Citry()
        app.template_globals["greeting"] = "hello"

        class Card(Component):
            citry = app
            template = """
            <p>{{ greeting }}</p>
            """

        assert "hello" in Card().render().serialize()

    def test_default_instance_is_configurable_after_import(self):
        # The user's headline scenario: the default `citry` instance is created
        # at import, before user code runs, so globals must be settable later.
        default_instance.template_globals["flash"] = "saved"
        try:

            class Banner(Component):
                template = """
                <p>{{ flash }}</p>
                """

            assert "saved" in Banner().render().serialize()
        finally:
            del default_instance.template_globals["flash"]

    def test_globals_support_dict_mutation(self):
        app = Citry(template_globals={"a": "1"})
        app.template_globals.update({"b": "2"})
        app.template_globals["c"] = "3"
        del app.template_globals["a"]

        class Card(Component):
            citry = app
            template = """
            <p>{{ b }}{{ c }}</p>
            """

        assert "23" in Card().render().serialize()
        assert "a" not in app.template_globals

    def test_changing_a_global_between_renders_is_reflected(self):
        # Globals are plain (not Const) values, so a part of the template that
        # reads one is recomputed each render rather than cached; changing the
        # global between renders must show up in the next render's output.
        app = Citry(template_globals={"flag": "on"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ flag }}</p>
            """

        assert "on" in Card().render().serialize()

        app.template_globals["flag"] = "off"

        second = Card().render().serialize()
        assert "off" in second
        assert "on" not in second

    def test_construction_mapping_is_copied_both_ways(self):
        # The live store is decoupled from the mapping passed at construction:
        # changing one must not leak into the other.
        seed = {"x": "1"}
        app = Citry(template_globals=seed)

        seed["x"] = "mutated"
        app.template_globals["y"] = "2"

        assert app.template_globals == {"x": "1", "y": "2"}
        assert seed == {"x": "mutated"}


class TestTemplateGlobalsPrecedence:
    def test_component_template_data_overrides_a_global(self):
        app = Citry(template_globals={"label": "global"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ label }}</p>
            """

            def template_data(self, kwargs, slots):
                return {"label": "local"}

        html = Card().render().serialize()

        assert "local" in html
        assert "global" not in html

    def test_global_is_not_subject_to_a_component_schema(self):
        # Globals are merged after the component's TemplateData is validated, so
        # a global key absent from the declared schema is not an "unexpected
        # field" and still reaches the template.
        app = Citry(template_globals={"site_name": "Acme"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ title }} {{ site_name }}</p>
            """

            class TemplateData:
                title: str

            def template_data(self, kwargs, slots):
                return {"title": "Hello"}

        html = Card().render().serialize()

        assert "Hello" in html
        assert "Acme" in html


class TestRenderTimeTemplateGlobals:
    def test_render_time_global_is_visible(self):
        app = Citry()

        class Card(Component):
            citry = app
            template = """
            <p>{{ user }}</p>
            """

        assert "alice" in Card().render(template_globals={"user": "alice"}).serialize()

    def test_instance_and_render_time_globals_combine(self):
        app = Citry(template_globals={"a": "1"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ a }}{{ b }}</p>
            """

        assert "12" in Card().render(template_globals={"b": "2"}).serialize()

    def test_render_time_overrides_an_instance_global(self):
        app = Citry(template_globals={"x": "instance"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ x }}</p>
            """

        html = Card().render(template_globals={"x": "render"}).serialize()
        assert "render" in html
        assert "instance" not in html

    def test_component_data_overrides_a_render_time_global(self):
        app = Citry()

        class Card(Component):
            citry = app
            template = """
            <p>{{ x }}</p>
            """

            def template_data(self, kwargs, slots):
                return {"x": "component"}

        html = Card().render(template_globals={"x": "render"}).serialize()
        assert "component" in html
        assert "render" not in html

    def test_render_time_global_reaches_nested_children(self):
        # Render-wide: every component in the deferred render sees it.
        app = Citry()

        class Card(Component):
            citry = app
            template = """
            <span>{{ u }}</span>
            """

        class Page(Component):
            citry = app
            template = """
            <main>{{ u }}<c-card /></main>
            """

        html = Page().render(template_globals={"u": "X"}).serialize()
        assert html.count("X") == 2

    def test_render_time_global_reaches_embedded_element(self):
        # A composed element handed into an expression renders through a nested
        # render_impl, which inherits the render-time globals from the context
        # variable.
        app = Citry()

        class Inner(Component):
            citry = app
            template = """
            <span>{{ u }}</span>
            """

        class Outer(Component):
            citry = app
            template = """
            <div>{{ inner }}</div>
            """

            def template_data(self, kwargs, slots):
                return {"inner": Inner()}

        assert "X" in Outer().render(template_globals={"u": "X"}).serialize()

    def test_render_time_global_reaches_slot_content(self):
        app = Citry()

        class Card(Component):
            citry = app
            template = """
            <div><c-slot /></div>
            """

        class Page(Component):
            citry = app
            template = """
            <main><c-card>{{ u }}</c-card></main>
            """

        assert "X" in Page().render(template_globals={"u": "X"}).serialize()

    def test_render_time_global_does_not_leak_to_a_later_render(self):
        # The context variable is reset when the render returns, so a later
        # render without an override falls back to the instance value rather
        # than seeing the previous render's override.
        app = Citry(template_globals={"u": "default"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ u }}</p>
            """

        first = Card().render(template_globals={"u": "X"}).serialize()
        second = Card().render().serialize()

        assert "X" in first
        assert "X" not in second
        assert "default" in second

    def test_render_time_global_does_not_mutate_the_instance(self):
        app = Citry(template_globals={"u": "instance"})

        class Card(Component):
            citry = app
            template = """
            <p>{{ u }}</p>
            """

        assert "render" in Card().render(template_globals={"u": "render"}).serialize()
        assert "instance" in Card().render().serialize()
        assert app.template_globals == {"u": "instance"}

    def test_render_time_global_is_cleared_after_a_failed_render(self):
        # The override is reset even when the render raises (it lives in a
        # finally), so a per-render value cannot leak into a later render. This
        # matters for per-request data: a failed request must not bleed into the
        # next one.
        app = Citry(template_globals={"u": "default"})

        class Boom(Component):
            citry = app
            template = """
            <p>{{ u }}</p>
            """

            def template_data(self, kwargs, slots):
                raise RuntimeError("boom")

        class Card(Component):
            citry = app
            template = """
            <p>{{ u }}</p>
            """

        with pytest.raises(RuntimeError):
            Boom().render(template_globals={"u": "leaked"})

        second = Card().render().serialize()
        assert "leaked" not in second
        assert "default" in second


class TestRenderTimeTemplateGlobalsNesting:
    """A nested render started inside another render (e.g. in template_data)."""

    def test_nested_render_with_its_own_override_is_isolated(self):
        # The inner override applies only to the inner render; the outer render's
        # value is restored when the nested render returns.
        app = Citry()

        class Inner(Component):
            citry = app
            template = """
            <span>{{ u }}</span>
            """

        class Outer(Component):
            citry = app
            template = """
            <div>{{ inner_html }}|{{ u }}</div>
            """

            def template_data(self, kwargs, slots):
                return {"inner_html": Inner().render(template_globals={"u": "inner"})}

        html = Outer().render(template_globals={"u": "outer"}).serialize()
        assert "inner" in html  # the nested render used its own override
        assert "outer" in html  # the outer value was restored after it returned

    def test_nested_render_without_an_override_inherits_the_outer_globals(self):
        # With no override, a nested render inherits the enclosing render's
        # per-render globals, the same way an embedded {{ element }} does.
        app = Citry()

        class Inner(Component):
            citry = app
            template = """
            <span>{{ u }}</span>
            """

        class Outer(Component):
            citry = app
            template = """
            <div>{{ inner_html }}</div>
            """

            def template_data(self, kwargs, slots):
                return {"inner_html": Inner().render()}

        assert "outer" in Outer().render(template_globals={"u": "outer"}).serialize()

    def test_nested_render_opts_out_of_inherited_globals_with_empty_dict(self):
        # Passing an empty dict shadows the inherited per-render globals, so the
        # nested render sees only the instance globals.
        app = Citry(template_globals={"u": "instance"})

        class Inner(Component):
            citry = app
            template = """
            <span>{{ u }}</span>
            """

        class Outer(Component):
            citry = app
            template = """
            <div>{{ inner_html }}</div>
            """

            def template_data(self, kwargs, slots):
                return {"inner_html": Inner().render(template_globals={})}

        html = Outer().render(template_globals={"u": "render"}).serialize()
        assert "instance" in html
        assert "render" not in html
