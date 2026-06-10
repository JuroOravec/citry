"""
Tests for fill collection at the component boundary (docs/design/slots.md
section 4) and the Python ``slots=`` channel (section 9).

The receiving components consume their slots through ``template_data(kwargs,
slots)`` plus ``{{ slot_var }}`` / ``{{ slot_var(data) }}`` expressions, which
is the supported path until ``<c-slot>`` resolution lands (phase 4).
"""

import pytest

from citry import Citry, CitryContext, Component, Slot, SlotInput
from citry.nodes import ExprNode, FillSink, Node, collect_fills_from_body


def _make_citry():
    return Citry()


class TestPythonSlotsChannel:
    def test_slots_kwarg_extracted_from_call(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = "<p>x</p>"

        element = Page(title="x", slots={"header": "Hi"})
        assert element.kwargs == {"title": "x"}
        assert element.slots == {"header": "Hi"}

    def test_no_slots_kwarg_means_empty(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = "<p>x</p>"

        assert Page().slots == {}

    def test_python_slots_render_via_template_data(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = "<div>{{ header }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"header": slots["header"]}

        assert str(Page(slots={"header": "Hi"})) == '<div data-cid-c1="">Hi</div>'

    def test_python_slots_are_normalized_to_slot_instances(self):
        c = _make_citry()
        seen = {}

        class Page(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                seen.update(slots)
                return {}

        str(Page(slots={"header": "Hi", "footer": lambda _ctx: "F"}))
        assert isinstance(seen["header"], Slot)
        assert isinstance(seen["footer"], Slot)
        assert seen["header"].slot_name == "header"
        assert seen["header"].component_name == "Page"

    def test_typed_slots_class(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = "<div>{{ h }}</div>"

            class Slots:
                header: SlotInput

            def template_data(self, kwargs, slots=None):
                return {"h": slots.header}

        assert str(Page(slots={"header": "Hi"})) == '<div data-cid-c1="">Hi</div>'


class TestImplicitDefaultSlot:
    def _card(self, c):
        class Card(Component):
            citry = c
            template = "<div>{{ body }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"body": slots.get("default", "EMPTY")}

        return Card

    def test_body_content_fills_default_slot(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = "<c-card>Hello!</c-card>"

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">Hello!</div>'

    def test_default_body_renders_in_parent_scope(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = "<c-card>Hello {{ name }}!</c-card>"

            def template_data(self, kwargs, slots=None):
                return {"name": "Jo"}

        # `name` comes from Page's scope; Card has no `name` variable.
        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">Hello Jo!</div>'

    def test_whitespace_only_body_makes_no_slot(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = "<c-card>\n   \n</c-card>"

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">EMPTY</div>'

    def test_no_body_makes_no_slot(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = "<c-card />"

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">EMPTY</div>'


class TestNamedFills:
    def _card(self, c):
        class Card(Component):
            citry = c
            template = "<div>{{ h }}|{{ f }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"h": slots.get("header", ""), "f": slots.get("footer", "")}

        return Card

    def test_named_fills_collected(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header">H</c-fill><c-fill name="footer">F</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">H|F</div>'

    def test_whitespace_between_fills_dropped(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = '<c-card>\n  <c-fill name="header">H</c-fill>\n  <c-fill name="footer">F</c-fill>\n</c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">H|F</div>'

    def test_fill_body_renders_in_parent_scope(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header">{{ greeting }}</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"greeting": "Yo"}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">Yo|</div>'

    def test_fill_slot_metadata(self):
        c = _make_citry()
        seen = {}

        class Card(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                seen.update(slots)
                return {}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header">H</c-fill></c-card>'

        str(Page())
        slot = seen["header"]
        assert isinstance(slot, Slot)
        assert slot.slot_name == "header"
        assert slot.component_name == "card"
        assert slot.source_position is not None


class TestFillsUnderControlFlow:
    def _card(self, c):
        class Card(Component):
            citry = c
            template = "<div>{{ h }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"h": slots.get("header", "NONE")}

        return Card

    def test_fill_in_taken_if_branch_collected(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = '<c-card><c-if cond="flag"><c-fill name="header">ON</c-fill></c-if></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"flag": True}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">ON</div>'

    def test_fill_in_untaken_if_branch_not_collected(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = '<c-card><c-if cond="flag"><c-fill name="header">ON</c-fill></c-if></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"flag": False}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">NONE</div>'

    def test_else_branch_fill_collected(self):
        c = _make_citry()
        self._card(c)

        class Page(Component):
            citry = c
            template = (
                '<c-card><c-if cond="flag"><c-fill name="header">A</c-fill></c-if>'
                '<c-else><c-fill name="header">B</c-fill></c-else></c-card>'
            )

            def template_data(self, kwargs, slots=None):
                return {"flag": False}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">B</div>'

    def test_dynamic_fills_in_loop(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<div>{{ a }}|{{ b }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"a": slots.get("a", ""), "b": slots.get("b", "")}

        class Page(Component):
            citry = c
            template = '<c-card><c-for each="s in names"><c-fill c-name="s">F-{{ s }}</c-fill></c-for></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"names": ["a", "b"]}

        # Each fill closes over its own iteration, so the bodies differ.
        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">F-a|F-b</div>'

    def test_loop_variable_captured_per_component(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<li>{{ h }}</li>"

            def template_data(self, kwargs, slots=None):
                return {"h": slots["header"]}

        class Page(Component):
            citry = c
            template = '<c-for each="x in items"><c-card><c-fill name="header">{{ x }}</c-fill></c-card></c-for>'

            def template_data(self, kwargs, slots=None):
                return {"items": [1, 2]}

        # The fill body is rendered later (the child renders through the
        # queue), but each closure captured its own iteration's `x`.
        assert str(Page()) == '<li data-cid-c2="" data-cid-c1="">1</li><li data-cid-c3="" data-cid-c1="">2</li>'

    def test_duplicate_dynamic_fill_names_raise(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<p>x</p>"

        class Page(Component):
            citry = c
            template = '<c-card><c-for each="s in names"><c-fill c-name="s">X</c-fill></c-for></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"names": ["dup", "dup"]}

        with pytest.raises(RuntimeError, match="Multiple fills target the same slot name 'dup'"):
            str(Page())


class TestFillProps:
    def test_c_bind_spread_supplies_name(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<div>{{ h }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"h": slots.get("header", "")}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill c-bind="props">X</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"props": {"name": "header"}}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">X</div>'

    def test_c_bind_unsupported_key_raises(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<p>x</p>"

        class Page(Component):
            citry = c
            template = '<c-card><c-fill c-bind="props">X</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"props": {"name": "h", "bogus": 1}}

        with pytest.raises(RuntimeError, match="unsupported key 'bogus'"):
            str(Page())

    def test_boolean_name_raises(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<p>x</p>"

        class Page(Component):
            citry = c
            template = "<c-card><c-fill name>X</c-fill></c-card>"

        with pytest.raises(RuntimeError, match="must resolve to a non-empty string"):
            str(Page())

    def test_data_var_must_be_identifier(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<p>x</p>"

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="h" data="not valid">X</c-fill></c-card>'

        with pytest.raises(RuntimeError, match="valid Python identifier"):
            str(Page())

    def test_same_data_and_fallback_var_raises(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<p>x</p>"

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="h" data="d" fallback="d">X</c-fill></c-card>'

        with pytest.raises(RuntimeError, match="same variable"):
            str(Page())


class TestScopedSlotData:
    def test_fill_data_var_receives_slot_data(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<div>{{ item(payload) }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"item": slots["item"], "payload": {"user": "Jo"}}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="item" data="d">U={{ d["user"] }}</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">U=Jo</div>'

    def test_fill_data_combines_with_parent_scope(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<div>{{ item(payload) }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"item": slots["item"], "payload": {"n": 2}}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="item" data="d">{{ prefix }}{{ d["n"] }}</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"prefix": "no."}

        # `prefix` is Page's variable; `d` is the slot data from Card.
        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">no.2</div>'

    def test_fill_fallback_var_receives_fallback(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = "<div>{{ item(payload, fb) }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"item": slots["item"], "payload": {}, "fb": Slot("FALLBACK")}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="item" fallback="f">[{{ f }}]</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">[FALLBACK]</div>'

    def test_fill_invoked_repeatedly_with_different_data(self):
        c = _make_citry()

        class Card(Component):
            citry = c
            template = '<ul><c-for each="u in users"><li>{{ item({"user": u}) }}</li></c-for></ul>'

            def template_data(self, kwargs, slots=None):
                return {"item": slots["item"], "users": ["A", "B"]}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="item" data="d">Hi {{ d["user"] }}</c-fill></c-card>'

        assert str(Page()) == '<ul data-cid-c2="" data-cid-c1=""><li>Hi A</li><li>Hi B</li></ul>'


class TestComponentsInsideSlotContent:
    def test_component_inside_fill_renders(self):
        c = _make_citry()

        class Inner(Component):
            citry = c
            template = "<span>IN</span>"

        class Card(Component):
            citry = c
            template = "<div>{{ h }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"h": slots["header"]}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header"><c-inner /></c-fill></c-card>'

        # Render order: Page (c1), Card (c2), then the deferred Inner found
        # inside the invoked fill content (c3).
        assert str(Page()) == '<div data-cid-c2="" data-cid-c1=""><span data-cid-c3="">IN</span></div>'

    def test_component_inside_default_slot_renders(self):
        c = _make_citry()

        class Inner(Component):
            citry = c
            template = "<span>IN</span>"

        class Card(Component):
            citry = c
            template = "<div>{{ body }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"body": slots["default"]}

        class Page(Component):
            citry = c
            template = "<c-card>before <c-inner /> after</c-card>"

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">before <span data-cid-c3="">IN</span> after</div>'

    def test_three_level_slot_passthrough(self):
        c = _make_citry()

        class Leaf(Component):
            citry = c
            template = "<i>LEAF</i>"

        class Mid(Component):
            citry = c
            template = "<b>{{ body }}</b>"

            def template_data(self, kwargs, slots=None):
                return {"body": slots["default"]}

        class Card(Component):
            citry = c
            template = "<div>{{ h }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"h": slots["header"]}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header"><c-mid><c-leaf /></c-mid></c-fill></c-card>'

        # Page (c1) -> Card (c2) -> Mid found in Card's fill content (c3) ->
        # Leaf found in Mid's default-slot content (c4).
        assert str(Page()) == (
            '<div data-cid-c2="" data-cid-c1=""><b data-cid-c3=""><i data-cid-c4="">LEAF</i></b></div>'
        )


class TestCollectFillsDispatch:
    """
    Fill collection dispatches through ``Node.collect_fills`` (open dispatch,
    docs/design/slots.md section 4.4), so node kinds an extension injects can
    take part without the collector knowing about them.
    """

    def test_base_node_rejected_in_fill_group(self):
        sink = FillSink("card")
        with pytest.raises(RuntimeError, match=r"Tag \(Node\) cannot appear next to '<c-fill>'"):
            Node().collect_fills(CitryContext(), sink)

    def test_expr_node_rejected_with_friendly_message(self):
        node = ExprNode("src", (0, 0), "x", ("x",))
        with pytest.raises(RuntimeError, match="Expression cannot appear next to '<c-fill>'"):
            node.collect_fills(CitryContext(), sink=FillSink("card"))

    def test_text_beside_fills_rejected_by_body_walk(self):
        sink = FillSink("card")
        with pytest.raises(RuntimeError, match="Text cannot appear next to '<c-fill>'"):
            collect_fills_from_body(["not whitespace"], CitryContext(), sink)

    def test_custom_node_can_register_fills(self):
        # An extension-style node participates by overriding collect_fills.
        class AutoHeader(Node):
            def collect_fills(self, context, sink):
                sink.add("header", Slot("auto"))

        sink = FillSink("card")
        collect_fills_from_body(["  ", AutoHeader()], CitryContext(), sink)
        assert sink.fills["header"]() == "auto"

    def test_sink_rejects_duplicate_names(self):
        sink = FillSink("card")
        sink.add("header", Slot("a"))
        with pytest.raises(RuntimeError, match="Multiple fills target the same slot name 'header'"):
            sink.add("header", Slot("b"))
