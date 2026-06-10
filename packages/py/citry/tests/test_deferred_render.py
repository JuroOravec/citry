"""
Tests for deferred component rendering (docs/design/deferred_rendering.md, Phase A).

``ComponentNode`` no longer recurses; it returns a ``DeferredComponent`` part,
and ``render_impl`` drives a heap-bound, depth-first queue that resolves every
deferred component. This makes render depth unbounded, keeps loop-variable kwargs
correct, fires ``on_component_rendered`` children-first the moment each subtree is
complete, and bubbles dependencies up at finalize time.
"""

# ruff: noqa: ANN

import pytest

from citry import Citry, CitryContext, CitryRender, Component
from citry.citry_render import DeferredComponent
from citry.extension import Extension


class TestInfiniteDepth:
    def test_renders_far_past_recursion_limit(self):
        # A chain C0 -> C1 -> ... -> C600, each rendering the next. Eager
        # recursion blows the Python stack around ~60 levels; the queue is
        # heap-bound, so this must render.
        c = Citry()
        depth = 600

        for i in range(depth + 1):
            child_tag = f"<c-c{i + 1} />" if i < depth else "leaf"
            Component_i = type(
                f"C{i}",
                (Component,),
                {"citry": c, "template": f"<span>{child_tag}</span>"},
            )
            # Keep a reference alive so the class is not GC'd / unregistered.
            globals()[f"_C{i}"] = Component_i

        out = globals()["_C0"]().render().serialize()
        assert out.count("<span ") == depth + 1
        assert out.endswith("leaf" + "</span>" * (depth + 1))


class TestLoopVarKwargs:
    def test_loop_variable_resolved_eagerly_per_iteration(self):
        # Each <c-card> kwarg references the loop variable `i`. Kwargs must be
        # resolved while the per-iteration context is live, not at drive time.
        c = Citry()

        class Card(Component):
            citry = c
            template = "<b>{{ n }}</b>"

            def template_data(self, kwargs, slots=None):
                return {"n": kwargs["n"]}

        class Page(Component):
            citry = c
            template = '<ul><c-for each="i in items"><c-card c-n="i" /></c-for></ul>'

            def template_data(self, kwargs, slots=None):
                return {"items": [1, 2, 3]}

        assert Page().render().serialize() == (
            '<ul data-cid-c1=""><b data-cid-c2="">1</b><b data-cid-c3="">2</b><b data-cid-c4="">3</b></ul>'
        )


class TestFinalizeOrder:
    def _order_recorder(self):
        order: list[str] = []

        class Recorder(Extension):
            name = "recorder"

            def on_component_rendered(self, ctx):
                order.append(type(ctx.component).__name__)

        return order, Recorder

    def test_children_finalize_before_parents(self):
        order, Recorder = self._order_recorder()
        c = Citry(extensions=[Recorder])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

        class Mid(Component):
            citry = c
            template = "<div><c-leaf /></div>"

        class Root(Component):
            citry = c
            template = "<main><c-mid /></main>"

        Root().render().serialize()
        assert order == ["Leaf", "Mid", "Root"]

    def test_siblings_finalize_in_source_order(self):
        order, Recorder = self._order_recorder()
        c = Citry(extensions=[Recorder])

        class A(Component):
            citry = c
            template = "<i>a</i>"

        class B(Component):
            citry = c
            template = "<i>b</i>"

        class Root(Component):
            citry = c
            template = "<main><c-a /><c-b /></main>"

        Root().render().serialize()
        assert order == ["A", "B", "Root"]


class TestDepsBubble:
    def test_descendant_deps_reach_root_extra(self):
        # Each component stashes its own marker into its render context's extra
        # during on_component_rendered. The finalize-time merge (child -> parent)
        # must carry a deep descendant's marker all the way to the root's extra.
        class Stash(Extension):
            name = "stash"

            def on_component_rendered(self, ctx):
                ctx.render.context.extra[type(ctx.component).__name__] = True

        c = Citry(extensions=[Stash])

        class Leaf(Component):
            citry = c
            template = "<i>x</i>"

        class Mid(Component):
            citry = c
            template = "<div><c-leaf /></div>"

        class Root(Component):
            citry = c
            template = "<main><c-mid /></main>"

        rendered = Root().render()
        assert rendered.context.extra == {"Leaf": True, "Mid": True, "Root": True}


class TestSerializeGuard:
    def test_unresolved_deferred_raises_on_serialize(self):
        ctx = CitryContext()
        # A DeferredComponent left in parts means the drive loop never ran.
        bogus = DeferredComponent.__new__(DeferredComponent)  # no element needed
        rendered = CitryRender(parts=["<p>", bogus, "</p>"], context=ctx)
        with pytest.raises(RuntimeError, match="unresolved DeferredComponent"):
            rendered.serialize()


class TestNestedRenderedHook:
    def test_string_replace_through_nested_tree(self):
        # on_component_rendered returning a string replaces a *nested* child's
        # output (not just the root), spliced back into the parent.
        class WrapLeaf(Extension):
            name = "wrap_leaf"

            def on_component_rendered(self, ctx):
                if type(ctx.component).__name__ == "Leaf":
                    return "<leaf-wrapped/>"
                return None

        c = Citry(extensions=[WrapLeaf])

        class Leaf(Component):
            citry = c
            template = "<i>leaf</i>"

        class Root(Component):
            citry = c
            template = "<main><c-leaf /></main>"

        assert Root().render().serialize() == '<main data-cid-c1=""><leaf-wrapped data-cid-c2=""/></main>'

    def test_raise_through_nested_tree_propagates(self):
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

        with pytest.raises(ValueError, match="boom"):
            Root().render().serialize()
