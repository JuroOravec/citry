"""
Tests for the Slot value (citry/slots.py) and the ``{{ my_slot }}`` detection.

Covers construction from every input form, escaping, standalone and repeated
invocation, the fallback handle, ``str()`` coercion, ``normalize_slot_fills``,
and Slots embedded in template expressions. The slot resolution at ``<c-slot>``
sites and fill collection at the component boundary are later phases (see
docs/design/slots.md section 14).
"""

import pytest

from citry import Citry, CitryRender, Component, Slot, SlotContext
from citry.slots import normalize_slot_fills
from citry.util.html import SafeString


class TestSlotConstruction:
    def test_string_contents_are_escaped(self):
        slot = Slot("<b>hi</b> & 'quotes'")
        assert slot() == "&lt;b&gt;hi&lt;/b&gt; &amp; &#39;quotes&#39;"

    def test_safestring_contents_pass_through(self):
        slot = Slot(SafeString("<b>hi</b>"))
        assert slot() == "<b>hi</b>"

    def test_scalar_contents(self):
        assert Slot(42)() == "42"

    def test_contents_kept_for_debugging(self):
        slot = Slot("hi", component_name="card", slot_name="header")
        assert slot.contents == "hi"
        assert repr(slot) == "<Slot component_name='card' slot_name='header'>"

    def test_slot_in_slot_raises(self):
        with pytest.raises(TypeError, match="another Slot instance"):
            Slot(Slot("x"))

    def test_non_callable_content_func_raises(self):
        with pytest.raises(TypeError, match="must be a callable"):
            Slot("x", content_func="not callable")


class TestSlotCall:
    def test_function_receives_data(self):
        slot = Slot(lambda ctx: f"Hello, {ctx.data['name']}!")
        assert slot({"name": "John"}) == "Hello, John!"

    def test_no_data_means_empty_mapping(self):
        slot = Slot(lambda ctx: str(len(ctx.data)))
        assert slot() == "0"

    def test_function_result_is_escaped(self):
        slot = Slot(lambda _ctx: "<b>unsafe</b>")
        assert slot() == "&lt;b&gt;unsafe&lt;/b&gt;"

    def test_function_safestring_result_not_escaped(self):
        slot = Slot(lambda _ctx: SafeString("<b>safe</b>"))
        assert slot() == "<b>safe</b>"

    def test_function_none_result_renders_empty(self):
        slot = Slot(lambda _ctx: None)
        assert slot() == ""

    def test_repeated_calls_with_different_data(self):
        slot = Slot(lambda ctx: f"n={ctx.data['n']}")
        assert slot({"n": 1}) == "n=1"
        assert slot({"n": 2}) == "n=2"

    def test_fallback_is_a_slot(self):
        captured = {}

        def content(ctx: SlotContext) -> str:
            captured["fallback"] = ctx.fallback
            return str(ctx.fallback)

        slot = Slot(content)
        assert slot(fallback=Slot("FB")) == "FB"
        assert isinstance(captured["fallback"], Slot)

    def test_fallback_defaults_to_none(self):
        slot = Slot(lambda ctx: "yes" if ctx.fallback is None else "no")
        assert slot() == "yes"


class TestSlotFromComponents:
    def test_element_contents_render_on_call(self):
        c = Citry()

        class Hello(Component):
            citry = c
            template = "<p>hi</p>"

        slot = Slot(Hello())
        part = slot()
        assert isinstance(part, CitryRender)
        assert part.serialize() == '<p data-cid-c1="">hi</p>'

    def test_element_contents_render_fresh_per_call(self):
        c = Citry()

        class Hello(Component):
            citry = c
            template = "<p>hi</p>"

        slot = Slot(Hello())
        # Each call re-renders the element, minting a fresh render id.
        assert str(slot) == '<p data-cid-c1="">hi</p>'
        assert str(slot) == '<p data-cid-c2="">hi</p>'

    def test_render_contents_are_inlined(self):
        c = Citry()

        class Hello(Component):
            citry = c
            template = "<p>hi</p>"

        rendered = Hello().render()
        slot = Slot(rendered)
        assert slot() is rendered


class TestSlotStr:
    def test_str_of_string_slot(self):
        assert str(Slot("hi")) == "hi"

    def test_str_of_function_slot(self):
        assert str(Slot(lambda _ctx: "made")) == "made"

    def test_str_escapes(self):
        assert str(Slot("<b>")) == "&lt;b&gt;"


class TestSlotInExpressions:
    def test_slot_in_expression_renders(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = "<div>{{ s }}</div>"

            def template_data(self, kwargs, slots):
                return {"s": Slot("hello")}

        assert str(Page()) == '<div data-cid-c1="">hello</div>'

    def test_slot_in_expression_is_escaped(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = "<div>{{ s }}</div>"

            def template_data(self, kwargs, slots):
                return {"s": Slot("<b>unsafe</b>")}

        assert str(Page()) == '<div data-cid-c1="">&lt;b&gt;unsafe&lt;/b&gt;</div>'

    def test_slot_called_with_data_in_expression(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = "<div>{{ s(d) }}</div>"

            def template_data(self, kwargs, slots):
                return {
                    "s": Slot(lambda ctx: f"Hello, {ctx.data['name']}!"),
                    "d": {"name": "Jo"},
                }

        assert str(Page()) == '<div data-cid-c1="">Hello, Jo!</div>'

    def test_slot_wrapping_element_in_expression(self):
        c = Citry()

        class Inner(Component):
            citry = c
            template = "<span>in</span>"

        class Page(Component):
            citry = c
            template = "<div>{{ s }}</div>"

            def template_data(self, kwargs, slots):
                return {"s": Slot(Inner())}

        # Page renders first (c1), then the embedded element renders (c2).
        assert str(Page()) == '<div data-cid-c1=""><span data-cid-c2="">in</span></div>'


class TestNormalizeSlotFills:
    def test_string_becomes_slot(self):
        fills = normalize_slot_fills({"header": "Hi"}, component_name="card")
        slot = fills["header"]
        assert isinstance(slot, Slot)
        assert slot() == "Hi"
        assert slot.component_name == "card"
        assert slot.slot_name == "header"

    def test_none_is_dropped(self):
        assert normalize_slot_fills({"header": None}) == {}

    def test_function_becomes_slot(self):
        fills = normalize_slot_fills({"footer": lambda _ctx: "made"})
        assert fills["footer"]() == "made"
        assert fills["footer"].slot_name == "footer"

    def test_complete_slot_kept_as_is(self):
        slot = Slot("x", component_name="card", slot_name="header")
        fills = normalize_slot_fills({"header": slot}, component_name="other")
        assert fills["header"] is slot

    def test_incomplete_slot_copied_not_mutated(self):
        slot = Slot("x", extra={"k": "v"})
        fills = normalize_slot_fills({"header": slot}, component_name="card")
        copied = fills["header"]
        assert copied is not slot
        assert copied.component_name == "card"
        assert copied.slot_name == "header"
        # The original is untouched.
        assert slot.component_name is None
        assert slot.slot_name is None
        # The extra bag is copied, not shared.
        copied.extra["k2"] = "v2"
        assert "k2" not in slot.extra
        # The content function is reused.
        assert copied() == "x"

    def test_element_becomes_slot(self):
        c = Citry()

        class Hello(Component):
            citry = c
            template = "<p>hi</p>"

        fills = normalize_slot_fills({"body": Hello()})
        part = fills["body"]()
        assert isinstance(part, CitryRender)


class TestDeclaredSlotCheck:
    """
    The definition-time check comparing a component's own ``<c-slot>`` tags
    against its ``Slots`` schema (docs/design/slots.md section 9.5). Runs at
    first render, and only when ``Slots`` is declared (a closed schema).
    """

    def test_slot_not_in_schema_is_a_dead_slot(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="ghost"/>'

            class Slots:
                header: str = ""

        with pytest.raises(RuntimeError, match=r"does not declare 'ghost', so no caller can fill it"):
            str(Card())

    def test_dead_slot_suggests_a_close_name(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="heder"/>'

            class Slots:
                header: str = ""

        with pytest.raises(RuntimeError, match=r"Did you mean 'header'\?"):
            str(Card())

    def test_required_slot_with_optional_field_is_allowed(self):
        # `required` on <c-slot> and a default on the Slots field are orthogonal
        # (the fill may be passed from outside), so the combination is allowed:
        # it declares "side", so the dead-slot check does not fire.
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side" required/>'

            class Slots:
                side: str = "default text"  # optional: has a default

        assert "passed" in str(Card(slots={"side": "passed"}))

    def test_matching_declaration_is_fine(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="body"/>'

            class Slots:
                body: str = ""

        str(Card())  # does not raise

    def test_required_slot_required_in_schema_is_fine(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="x" required/>'

            class Slots:
                x: str  # required: no default

        assert "filled" in str(Card(slots={"x": "filled"}))

    def test_no_slots_class_skips_the_check(self):
        c = Citry()

        class Card(Component):
            citry = c
            # Any slot name is legitimate without a schema, so no dead-slot error.
            template = '<c-slot name="anything"/>'

        assert "x" in str(Card(slots={"anything": "x"}))

    def test_bare_default_slot_needs_a_default_field(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<c-slot/>"  # the default slot, named "default"

            class Slots:
                header: str = ""

        with pytest.raises(RuntimeError, match=r"does not declare 'default'"):
            str(Card())

    def test_default_slot_declared_is_fine(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<c-slot/>"

            class Slots:
                default: str = ""

        str(Card())  # does not raise

    def test_dynamic_slot_name_is_not_flagged(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot c-name="which"/>'

            class Slots:
                real: str = ""

            def template_data(self, kwargs, slots):
                return {"which": "real"}

        # A dynamic name is not a static declaration, so the check ignores it; at
        # render it resolves to the declared "real" slot.
        str(Card())  # does not raise

    def test_slot_nested_in_control_flow_is_still_checked(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="True"><c-slot name="ghost"/></c-if>'

            class Slots:
                header: str = ""

        with pytest.raises(RuntimeError, match=r"does not declare 'ghost'"):
            str(Card())


class TestSlotFieldDefaultFill:
    """
    A non-``None`` default on a typed ``Slots`` field is used as the slot's fill
    when the caller omits it (docs/design/slots.md section 5): it satisfies a
    ``required`` slot and renders in place. A passed fill wins over it, and a
    ``None`` default (the "optional" marker) leaves the in-template body as the
    fallback.
    """

    def test_required_slot_uses_field_default_when_omitted(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side" required/>'

            class Slots:
                side: str = "DEFAULT"

        assert str(Card()) == "DEFAULT"

    def test_passed_fill_overrides_field_default(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side" required/>'

            class Slots:
                side: str = "DEFAULT"

        assert str(Card(slots={"side": "FILL"})) == "FILL"

    def test_optional_slot_uses_field_default_when_omitted(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side"/>'

            class Slots:
                side: str = "DEFAULT"

        assert str(Card()) == "DEFAULT"

    def test_none_default_falls_through_to_the_body(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side">BODY</c-slot>'

            class Slots:
                side: str | None = None

        assert str(Card()) == "BODY"

    def test_required_slot_with_none_default_still_raises(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side" required/>'

            class Slots:
                side: str | None = None

        with pytest.raises(RuntimeError, match=r"required, but no fill was provided"):
            str(Card())

    def test_field_default_wins_over_in_template_body(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side">BODY</c-slot>'

            class Slots:
                side: str = "DEFAULT"

        assert str(Card()) == "DEFAULT"

    def test_no_slots_class_keeps_the_body_fallback(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="side">BODY</c-slot>'

        assert str(Card()) == "BODY"
