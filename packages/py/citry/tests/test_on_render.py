"""
Tests for the ``Component.on_render`` hook (docs/design/on_render.md
sections 3-4). Plain form: returning ``None`` renders the template as usual;
returning content (``str`` / composed element / ``CitryRender`` / ``Slot``)
replaces the component's whole output and the template is never rendered.
Generator form: code before the first yield runs before the template renders,
each yield receives the settled ``(result, error)``, and the generator may
replace the output, catch a child's error, or raise.
"""

import pytest

from citry import Citry, CitryRender, Component, Extension
from citry.citry_render import DeferredComponent


def _has_deferred(render):
    """True if any DeferredComponent part remains anywhere in the render."""

    def walk(parts):
        for part in parts:
            if isinstance(part, DeferredComponent):
                return True
            if isinstance(part, CitryRender) and walk(part.parts):
                return True
        return False

    return walk(render.parts)


class TestOnRenderPlainForm:
    def test_default_renders_template(self):
        c = Citry()

        class Plain(Component):
            citry = c
            template = "<p>template</p>"

        assert ">template</p>" in Plain().render().serialize()

    def test_none_renders_template(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>template</p>"

            def on_render(self):
                return None

        assert ">template</p>" in Comp().render().serialize()

    def test_str_replaces_output_and_skips_template(self):
        rendered_data = []
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>{{ tracked() }}</p>"

            def template_data(self, kwargs, slots=None):
                def tracked():
                    rendered_data.append("template rendered")
                    return "x"

                return {"tracked": tracked}

            def on_render(self):
                return "<b>replaced</b>"

        html = Comp().render().serialize()
        assert ">replaced</b>" in html
        assert "<p>" not in html
        # The template body was never walked.
        assert rendered_data == []

    def test_str_is_not_autoescaped(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return '<script>let a = "1";</script>'

        html = Comp().render().serialize()
        assert html == '<script data-cid-c1="">let a = "1";</script>'

    def test_empty_str_means_empty_output(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return ""

        assert Comp().render().serialize() == ""

    def test_element_replacement_renders_in_place(self):
        c = Citry()

        class Other(Component):
            citry = c
            template = "<i>{{ name }}</i>"

            class Kwargs:
                name: str

            def template_data(self, kwargs, slots=None):
                return {"name": kwargs.name}

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return Other(name="delegated")

        html = Comp().render().serialize()
        assert ">delegated</i>" in html
        assert "<p>" not in html

    def test_element_replacement_with_nested_children(self):
        c = Citry()

        class Inner(Component):
            citry = c
            template = "<em>inner</em>"

        class Outer(Component):
            citry = c
            template = "<div><c-inner /></div>"

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return Outer()

        html = Comp().render().serialize()
        assert ">inner</em>" in html

    def test_element_replacement_sets_parent_link(self):
        seen = []
        c = Citry()

        class Other(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots=None):
                seen.append(type(self.parent).__name__ if self.parent else None)

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return Other()

        Comp().render()
        assert seen == ["Comp"]

    def test_citry_render_replacement_is_inlined(self):
        c = Citry()

        class Other(Component):
            citry = c
            template = "<i>prerendered</i>"

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return Other().render()

        html = Comp().render().serialize()
        assert ">prerendered</i>" in html

    def test_slot_replacement_renders_fill(self):
        # Slot semantics apply unchanged: a plain-string fill is text (it is
        # escaped when the slot is invoked).
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return self.raw_slots["body"]

        html = Comp(slots={"body": "from <slot>"}).render().serialize()
        assert "from &lt;slot&gt;" in html
        assert "<p>" not in html

    def test_unsupported_type_raises_type_error(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                return 42

        with pytest.raises(TypeError, match=r"Comp\.on_render"):
            Comp().render()

    def test_component_without_template(self):
        # The hook fires for template-less components too; without a
        # replacement, the output is empty.
        c = Citry()

        class NoTemplate(Component):
            citry = c

            def on_render(self):
                return "<p>made up</p>"

        assert str(NoTemplate()) == '<p data-cid-c1="">made up</p>'

    def test_works_for_nested_components(self):
        c = Citry()

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            def on_render(self):
                return "<i>hooked</i>"

        class Root(Component):
            citry = c
            template = "<main><c-leaf /></main>"

        html = Root().render().serialize()
        assert ">hooked</i>" in html
        assert "leaf" not in html

    def test_transparent_component_gets_no_marker(self):
        c = Citry()

        class Glass(Component):
            citry = c
            transparent = True
            template = "<p>x</p>"

            def on_render(self):
                return "<p>see-through</p>"

        class Root(Component):
            citry = c
            template = "<main><c-glass /></main>"

        html = Root().render().serialize()
        assert "<p>see-through</p>" in html

    def test_error_in_hook_carries_component_path(self):
        c = Citry()

        class Leaf(Component):
            citry = c
            template = "<i>x</i>"

            def on_render(self):
                raise ValueError("boom")

        class Root(Component):
            citry = c
            template = "<main><c-leaf /></main>"

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        assert exc_info.value.args[0].startswith(
            "An error occurred while rendering components Root > Leaf:\n",
        )


class TestOnRenderGeneratorForm:
    """
    The generator form (docs/design/on_render.md section 3.2): code before the
    first yield runs before the template renders; the yield receives the
    component's settled ``(result, error)``; the generator may replace the
    output (any number of times), raise, or keep the result.
    """

    def test_before_phase_runs_before_template(self):
        order = []
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>{{ tracked() }}</p>"

            def template_data(self, kwargs, slots=None):
                def tracked():
                    order.append("template")
                    return "x"

                return {"tracked": tracked}

            def on_render(self):
                order.append("before")
                yield

        Comp().render()
        assert order == ["before", "template"]

    def test_bare_yield_receives_settled_render(self):
        received = []
        c = Citry()

        class Inner(Component):
            citry = c
            template = "<em>inner</em>"

        class Comp(Component):
            citry = c
            template = "<div><c-inner /></div>"

            def on_render(self):
                result, error = yield
                received.append((result, error))

        html = Comp().render().serialize()
        assert ">inner</em>" in html

        (result, error) = received[0]
        assert error is None
        assert isinstance(result, CitryRender)
        # The subtree is settled: no DeferredComponent parts remain anywhere.
        assert not _has_deferred(result)

    def test_first_yield_content_replaces_template(self):
        received = []
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>template</p>"

            def on_render(self):
                result, error = yield "<b>yielded</b>"
                received.append((result, error))

        html = Comp().render().serialize()
        assert ">yielded</b>" in html
        assert "template" not in html
        assert received[0][1] is None

    def test_return_after_yield_replaces_output(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>template</p>"

            def on_render(self):
                _result, _error = yield
                return "<b>final</b>"

        html = Comp().render().serialize()
        assert ">final</b>" in html
        assert "template" not in html

    def test_plain_return_keeps_output(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>kept</p>"

            def on_render(self):
                _result, _error = yield

        assert ">kept</p>" in Comp().render().serialize()

    def test_raise_after_yield_becomes_component_error(self):
        c = Citry()

        class Leaf(Component):
            citry = c
            template = "<i>x</i>"

            def on_render(self):
                _result, _error = yield
                raise ValueError("post-yield boom")

        class Root(Component):
            citry = c
            template = "<main><c-leaf /></main>"

        with pytest.raises(ValueError, match="post-yield boom") as exc_info:
            Root().render()

        assert exc_info.value.args[0].startswith(
            "An error occurred while rendering components Root > Leaf:\n",
        )

    def test_error_boundary_catches_child_error(self):
        # The ErrorFallback pattern: a failing child's error is delivered to
        # the enclosing generator, which swallows it with fallback output.
        c = Citry()

        class Failing(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Guard(Component):
            citry = c
            template = "<div><c-failing /></div>"

            def on_render(self):
                _result, error = yield
                if error is not None:
                    return "<p>fallback</p>"
                return None

        class Root(Component):
            citry = c
            template = "<main><c-guard /></main>"

        html = Root().render().serialize()
        assert ">fallback</p>" in html

    def test_unhandled_error_keeps_bubbling_past_generator(self):
        # A generator that returns None on error does not swallow it.
        seen = []
        c = Citry()

        class Failing(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Observer(Component):
            citry = c
            template = "<div><c-failing /></div>"

            def on_render(self):
                _result, error = yield
                seen.append(error)

        with pytest.raises(ValueError, match="boom"):
            Observer().render()

        assert len(seen) == 1
        assert isinstance(seen[0], ValueError)

    def test_multiple_yields_each_receive_settled_result(self):
        received = []
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>original</p>"

            def on_render(self):
                result_a, _ = yield
                received.append(result_a.serialize())
                result_b, _ = yield "<b>second</b>"
                received.append(result_b.serialize())
                return "<u>third</u>"

        html = Comp().render().serialize()
        assert ">third</u>" in html
        assert ">original</p>" in received[0]
        assert ">second</b>" in received[1]

    def test_bare_yield_after_first_peeks_unchanged_result(self):
        received = []
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>once</p>"

            def on_render(self):
                result_a, _ = yield
                result_b, _ = yield None
                received.append(result_a is result_b)

        Comp().render()
        assert received == [True]

    def test_yielded_element_with_children_settles_before_resume(self):
        received = []
        c = Citry()

        class Inner(Component):
            citry = c
            template = "<em>inner</em>"

        class Replacement(Component):
            citry = c
            template = "<div><c-inner /></div>"

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                result, error = yield Replacement()
                received.append((result, error))

        html = Comp().render().serialize()
        assert ">inner</em>" in html

        result, error = received[0]
        assert error is None
        assert not _has_deferred(result)

    def test_error_in_yielded_content_returns_to_same_generator(self):
        # An error inside content the generator yielded comes back to the
        # same generator, which can recover.
        c = Citry()

        class Failing(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                _result, error = yield Failing()
                if error is not None:
                    return "<p>recovered</p>"
                return None

        html = Comp().render().serialize()
        assert ">recovered</p>" in html

    def test_unrenderable_yield_returns_to_same_generator(self):
        received = []
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>x</p>"

            def on_render(self):
                _result, error = yield 42
                received.append(error)
                return "<p>recovered</p>"

        html = Comp().render().serialize()
        assert ">recovered</p>" in html
        assert isinstance(received[0], TypeError)

    def test_generator_returning_before_yield_acts_like_plain_form(self):
        c = Citry()

        class Comp(Component):
            citry = c
            template = "<p>template</p>"

            def on_render(self):
                if True:
                    return "<b>early</b>"
                yield  # makes this a generator function

        html = Comp().render().serialize()
        assert ">early</b>" in html
        assert "template" not in html

    def test_extension_hook_runs_after_generator_settles(self):
        seen = []

        class Recorder(Extension):
            name = "recorder"

            def on_component_rendered(self, ctx):
                if ctx.render is not None:
                    seen.append(ctx.render.serialize())

        c = Citry(extensions=[Recorder])

        class Comp(Component):
            citry = c
            template = "<p>original</p>"

            def on_render(self):
                yield
                return "<b>final</b>"

        Comp().render()
        # The extension sees only the generator's final output, once.
        assert len(seen) == 1
        assert ">final</b>" in seen[0]

    def test_deep_generator_chain_does_not_recurse(self):
        # A generator at every level of a deep tree; the drive loop keeps
        # depth flat, so this stays well past Python's recursion limit.
        c = Citry()
        depth = 600

        class Leaf(Component):
            citry = c
            template = "<i>bottom</i>"

        def make_on_render():
            def on_render(self):  # noqa: ARG001
                _result, _error = yield

            return on_render

        prev_tag = "leaf"
        top: type[Component] = Leaf
        for i in range(depth):
            # type() with the proper name, so each class registers uniquely.
            top = type(
                f"Level{i}",
                (Component,),
                {
                    "citry": c,
                    "template": f"<div><c-{prev_tag} /></div>",
                    "on_render": make_on_render(),
                },
            )
            prev_tag = f"level{i}"

        html = top().render().serialize()
        assert ">bottom</i>" in html
