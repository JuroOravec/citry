"""
Tests for render-path error tracing (docs/design/on_render.md section 6): an
error raised during a render carries the component path ("Page > Card >
Avatar") in its message, with slot frames ("Card(slot:body)") where the
failing content was filled into a slot.

The path frames come from the component instances' ``parent`` links (added in
``component_render.py``), the slot frames from ``SlotNode.render``. Errors
bubble up the component tree (docs/design/on_render.md section 5): each
enclosing component's ``on_component_rendered`` extension hook may swallow
the error by returning replacement output, and an unhandled error raises
from the root.
"""

import pytest

from citry import Citry, Component
from citry.extension import Extension

PREFIX = "An error occurred while rendering components"


def _boom():
    raise ValueError("boom")


class TestComponentPath:
    def test_root_only_failure(self):
        c = Citry()

        class Root(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        assert exc_info.value.args[0] == f"{PREFIX} Root:\nboom"

    def test_nested_component_failure(self):
        c = Citry()

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Middle(Component):
            citry = c
            template = "<section><c-leaf /></section>"

        class Root(Component):
            citry = c
            template = "<main><c-middle /></main>"

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        assert exc_info.value.args[0] == f"{PREFIX} Root > Middle > Leaf:\nboom"

    def test_expression_failure_inside_control_flow(self):
        # An error inside a <c-if>/<c-for> body names the component; the
        # control-flow blocks add no frames of their own.
        c = Citry()

        class Root(Component):
            citry = c
            template = '<c-if cond="flag"><c-for each="x in items"><span>{{ broken() }}</span></c-for></c-if>'

            def template_data(self, kwargs, slots=None):
                return {"flag": True, "items": [1], "broken": _boom}

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        # safe_eval decorates call errors with its own message and caret, so
        # assert on the path line, not the whole message.
        assert exc_info.value.args[0].startswith(f"{PREFIX} Root:\n")
        assert "boom" in exc_info.value.args[0]

    def test_failure_before_instance_exists(self):
        # Kwargs validation fails in _create_instance, before the child
        # component instance exists; the path still names the child.
        c = Citry()

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            class Kwargs:
                title: str

        class Root(Component):
            citry = c
            template = '<main><c-leaf c-bind="extra" /></main>'

            def template_data(self, kwargs, slots=None):
                return {"extra": {"title": "x", "bogus": 1}}

        with pytest.raises(TypeError) as exc_info:
            Root().render()

        assert exc_info.value.args[0].startswith(f"{PREFIX} Root > Leaf:\n")

    def test_embedded_element_failure(self):
        # A composed-but-unrendered element handed in via {{ ... }} renders
        # inside this component; its frames nest under this component's path.
        # The failure itself (template_data) has no node position, so the
        # template snippet shows the embedding site ({{ em }}).
        c = Citry()

        class Embedded(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Root(Component):
            citry = c
            template = "<main>{{ em }}</main>"

            def template_data(self, kwargs, slots=None):
                return {"em": Embedded()}

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        msg = exc_info.value.args[0]
        assert msg.startswith(f"{PREFIX} Root > Embedded:\nboom")
        assert "In template of 'Root':" in msg
        assert "     1 | <main>{{ em }}</main>" in msg

    def test_extension_raise_at_finalize_carries_path(self):
        class BoomLeaf(Extension):
            name = "boom_leaf"

            def on_component_rendered(self, ctx):
                if type(ctx.component).__name__ == "Leaf":
                    raise ValueError("boom")

        c = Citry(extensions=[BoomLeaf])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

        class Root(Component):
            citry = c
            template = "<main><c-leaf /></main>"

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        assert exc_info.value.args[0] == f"{PREFIX} Root > Leaf:\nboom"


class TestSlotFrames:
    def test_failing_fill_content_gets_slot_frame(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="body" /></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="body"><span>{{ broken() }}</span></c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"broken": _boom}

        with pytest.raises(ValueError, match="boom") as exc_info:
            Page().render()

        assert exc_info.value.args[0].startswith(f"{PREFIX} Page > Card > Card(slot:body):\n")
        assert "boom" in exc_info.value.args[0]

    def test_failing_fallback_content_gets_slot_frame(self):
        # No fill given, so the slot renders its own body; a failure there is
        # attributed to the slot too.
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="body">{{ broken() }}</c-slot></div>'

            def template_data(self, kwargs, slots=None):
                return {"broken": _boom}

        with pytest.raises(ValueError, match="boom") as exc_info:
            Card().render()

        assert exc_info.value.args[0].startswith(f"{PREFIX} Card > Card(slot:body):\n")
        assert "boom" in exc_info.value.args[0]

    def test_component_deferred_from_fill_has_component_path(self):
        # A component written inside fill content renders later (deferred);
        # its path comes from its parent chain. The slot frame is not present
        # for deferred descendants (documented divergence from
        # django-components; docs/design/on_render.md section 6.2).
        c = Citry()

        class Failing(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Card(Component):
            citry = c
            template = '<div><c-slot name="body" /></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="body"><c-failing /></c-fill></c-card>'

        with pytest.raises(ValueError, match="boom") as exc_info:
            Page().render()

        assert exc_info.value.args[0] == f"{PREFIX} Page > Failing:\nboom"


class TestTemplatePosition:
    """
    The template-snippet layer of error tracing (docs/design/on_render.md
    section 6.3): errors from a node's render carry an underlined snippet of
    the template at the failing node, with real line numbers. Expected
    strings were locked from observed output.
    """

    def test_expression_error_shows_template_lines(self):
        c = Citry()

        class Leaf(Component):
            citry = c
            template = "<article>\n  <h1>title</h1>\n  <p>{{ broken() }}</p>\n</article>"

            def template_data(self, kwargs, slots=None):
                return {"broken": _boom}

        with pytest.raises(ValueError, match="boom") as exc_info:
            Leaf().render()

        msg = exc_info.value.args[0]
        # The three layers stack: path line, safe_eval's expression snippet
        # (expression-relative "line 1"), then the template snippet with the
        # real line number.
        assert msg.startswith(f"{PREFIX} Leaf:\n")
        assert "Error in call: ValueError: boom" in msg
        assert "In template of 'Leaf':" in msg
        assert "     3 |   <p>{{ broken() }}</p>" in msg
        assert "\n              ^^^^^^^^^^^^^^\n" in msg

    def test_innermost_node_wins(self):
        # The failing expression inside <c-if> + <c-for> produces one
        # template snippet (the expression's), not one per enclosing node.
        c = Citry()

        class Loop(Component):
            citry = c
            template = (
                '<c-if cond="flag">\n  <c-for each="x in items">\n    <b>{{ broken() }}</b>\n  </c-for>\n</c-if>'
            )

            def template_data(self, kwargs, slots=None):
                return {"flag": True, "items": [1], "broken": _boom}

        with pytest.raises(ValueError, match="boom") as exc_info:
            Loop().render()

        msg = exc_info.value.args[0]
        assert msg.count("In template") == 1
        assert "     3 |     <b>{{ broken() }}</b>" in msg

    def test_required_slot_error_gets_slot_span(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div>\n  <c-slot name="body" required />\n</div>'

        with pytest.raises(RuntimeError, match="required") as exc_info:
            Card().render()

        msg = exc_info.value.args[0]
        assert msg.startswith(f"{PREFIX} Card:\n")
        assert "In template of 'Card':" in msg
        assert '     2 |   <c-slot name="body" required />' in msg

    def test_fill_content_error_names_writer_template(self):
        # Fill content renders inside Frame, but the nodes come from Page's
        # template, so the snippet shows Page's source.
        c = Citry()

        class Frame(Component):
            citry = c
            template = '<section><c-slot name="body" /></section>'

        class Page(Component):
            citry = c
            template = '<c-frame>\n  <c-fill name="body">\n    <em>{{ broken() }}</em>\n  </c-fill>\n</c-frame>'

            def template_data(self, kwargs, slots=None):
                return {"broken": _boom}

        with pytest.raises(ValueError, match="boom") as exc_info:
            Page().render()

        msg = exc_info.value.args[0]
        assert msg.startswith(f"{PREFIX} Page > Frame > Frame(slot:body):\n")
        assert "In template of 'Page':" in msg
        assert "     3 |     <em>{{ broken() }}</em>" in msg

    def test_node_injected_without_position_is_skipped(self):
        # A node injected by an extension may not carry source/position; the
        # error then gets the component path but no template snippet.
        class ExplodingNode:
            def render(self, context):
                raise ValueError("boom")

        class Injector(Extension):
            name = "injector"

            def on_template_compiled(self, ctx):
                ctx.nodes.append(ExplodingNode())

        c = Citry(extensions=[Injector])

        class Root(Component):
            citry = c
            template = "<p>hi</p>"

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        assert exc_info.value.args[0].startswith(f"{PREFIX} Root:\n")
        assert "In template" not in exc_info.value.args[0]


class TestErrorBubbling:
    """
    Error bubbling (docs/design/on_render.md section 5): a failing component's
    error travels up the component tree; each enclosing component's
    ``on_component_rendered`` extension hook may swallow it by returning
    replacement output; an unhandled error raises from the root.
    """

    def test_extension_swallows_descendant_error(self):
        class Boundary(Extension):
            name = "boundary"

            def on_component_rendered(self, ctx):
                if ctx.error is not None and type(ctx.component).__name__ == "Middle":
                    return "<p>recovered</p>"
                return None

        c = Citry(extensions=[Boundary])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Middle(Component):
            citry = c
            template = "<section><c-leaf /></section>"

        class Root(Component):
            citry = c
            template = "<main><c-middle /></main>"

        html = Root().render().serialize()
        assert ">recovered</p>" in html
        assert "leaf" not in html

    def test_ancestors_receive_error_and_failing_component_does_not(self):
        # The hook fires for each enclosing component with (render=None,
        # error). The failing component itself never finished rendering, so
        # its own hook does not fire (divergence from django-components).
        calls = []

        class Recorder(Extension):
            name = "recorder"

            def on_component_rendered(self, ctx):
                calls.append((type(ctx.component).__name__, ctx.render, ctx.error))

        c = Citry(extensions=[Recorder])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Middle(Component):
            citry = c
            template = "<section><c-leaf /></section>"

        class Root(Component):
            citry = c
            template = "<main><c-middle /></main>"

        with pytest.raises(ValueError, match="boom"):
            Root().render()

        assert [name for name, _, _ in calls] == ["Middle", "Root"]
        for _, render, error in calls:
            assert render is None
            assert isinstance(error, ValueError)

    def test_sibling_after_failed_child_is_discarded(self):
        rendered = []
        c = Citry()

        class Bad(Component):
            citry = c
            template = "<i>bad</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Good(Component):
            citry = c
            template = "<i>good</i>"

            def template_data(self, kwargs, slots=None):
                rendered.append("Good")
                return {}

        class Root(Component):
            citry = c
            template = "<main><c-bad /><c-good /></main>"

        with pytest.raises(ValueError, match="boom"):
            Root().render()

        assert rendered == []

    def test_error_swallowed_at_distant_ancestor(self):
        # The error passes unhandled through B and A and is swallowed at Root.
        class Boundary(Extension):
            name = "boundary"

            def on_component_rendered(self, ctx):
                if ctx.error is not None and type(ctx.component).__name__ == "Root":
                    return "<p>recovered</p>"
                return None

        c = Citry(extensions=[Boundary])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class B(Component):
            citry = c
            template = "<div><c-leaf /></div>"

        class A(Component):
            citry = c
            template = "<div><c-b /></div>"

        class Root(Component):
            citry = c
            template = "<main><c-a /></main>"

        html = Root().render().serialize()
        assert ">recovered</p>" in html

    def test_sibling_of_recovered_component_still_renders(self):
        # Recovery at Middle replaces only Middle's output; Root's other
        # children render as usual.
        class Boundary(Extension):
            name = "boundary"

            def on_component_rendered(self, ctx):
                if ctx.error is not None and type(ctx.component).__name__ == "Middle":
                    return "<p>recovered</p>"
                return None

        c = Citry(extensions=[Boundary])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Middle(Component):
            citry = c
            template = "<section><c-leaf /></section>"

        class Other(Component):
            citry = c
            template = "<aside>other</aside>"

        class Root(Component):
            citry = c
            template = "<main><c-middle /><c-other /></main>"

        html = Root().render().serialize()
        assert ">recovered</p>" in html
        assert "<aside" in html
        assert "other" in html

    def test_finalize_raise_bubbles_and_is_swallowed_above(self):
        # An error raised by an extension at Leaf's finalize bubbles like a
        # render error and can be swallowed at an ancestor.
        class BoomAtLeaf(Extension):
            name = "boom_at_leaf"

            def on_component_rendered(self, ctx):
                if ctx.error is None and type(ctx.component).__name__ == "Leaf":
                    raise ValueError("boom")

        class Boundary(Extension):
            name = "boundary"

            def on_component_rendered(self, ctx):
                if ctx.error is not None and type(ctx.component).__name__ == "Middle":
                    return "<p>recovered</p>"
                return None

        c = Citry(extensions=[BoomAtLeaf, Boundary])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

        class Middle(Component):
            citry = c
            template = "<section><c-leaf /></section>"

        class Root(Component):
            citry = c
            template = "<main><c-middle /></main>"

        html = Root().render().serialize()
        assert ">recovered</p>" in html

    def test_unhandled_error_keeps_path_without_duplicate_frames(self):
        # The error passes through every ancestor's finalize on the way out;
        # the path frames must not be re-added along the way.
        class Passive(Extension):
            name = "passive"

            def on_component_rendered(self, ctx):
                return None

        c = Citry(extensions=[Passive])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

            def template_data(self, kwargs, slots=None):
                raise ValueError("boom")

        class Middle(Component):
            citry = c
            template = "<section><c-leaf /></section>"

        class Root(Component):
            citry = c
            template = "<main><c-middle /></main>"

        with pytest.raises(ValueError, match="boom") as exc_info:
            Root().render()

        assert exc_info.value.args[0] == f"{PREFIX} Root > Middle > Leaf:\nboom"
