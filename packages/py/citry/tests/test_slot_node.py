"""
Tests for slot resolution at the ``<c-slot>`` site (docs/design/slots.md
section 5) and the ``on_slot_rendered`` extension hook (section 7).

With phase 4 in place, slots work end to end through templates alone: the
parent passes content with ``<c-fill>`` (or the implicit default body), and
the child's ``<c-slot>`` renders it, so several tests mirror the README's
slot examples verbatim.
"""

import pytest

from citry import Citry, Component, Extension, Slot


class TestFillOrFallback:
    def test_named_slot_renders_fill(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="header">FB</c-slot></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header">H</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">H</div>'

    def test_unfilled_slot_renders_fallback(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="header">FB</c-slot></div>'

        class Page(Component):
            citry = c
            template = "<c-card />"

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">FB</div>'

    def test_unfilled_empty_slot_renders_nothing(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="header" /></div>'

        class Page(Component):
            citry = c
            template = "<c-card />"

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1=""></div>'

    def test_fallback_renders_in_child_scope(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<div><c-slot>Hi {{ who }}</c-slot></div>"

            def template_data(self, kwargs, slots=None):
                return {"who": "child"}

        class Page(Component):
            citry = c
            template = "<c-card />"

        # The fallback body renders as if the <c-slot> tags were not there,
        # i.e. against the child's own variables.
        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">Hi child</div>'

    def test_fill_renders_in_parent_scope(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="h">FB</c-slot></div>'

            def template_data(self, kwargs, slots=None):
                return {"who": "child"}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="h">Hi {{ who }}</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"who": "parent"}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">Hi parent</div>'


class TestDefaultSlot:
    def test_readme_button_example(self):
        c = Citry()

        class Button(Component):
            citry = c
            template = "<button><c-slot>Click me</c-slot></button>"

        class Bare(Component):
            citry = c
            template = "<c-button />"

        class Filled(Component):
            citry = c
            template = "<c-button>Submit</c-button>"

        # Usage without fill renders the fallback; with content, the fill.
        assert str(Bare()) == '<button data-cid-c2="" data-cid-c1="">Click me</button>'
        # The per-test id counter continues across renders: c3 is Filled, c4 its Button.
        assert str(Filled()) == '<button data-cid-c4="" data-cid-c3="">Submit</button>'

    def test_explicit_default_fill_targets_unnamed_slot(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<div><c-slot /></div>"

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="default">X</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">X</div>'

    def test_python_slots_fill_template_slots(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="header">FB</c-slot></div>'

        assert str(Card(slots={"header": "from python"})) == '<div data-cid-c1="">from python</div>'


class TestRequiredSlot:
    def test_required_unfilled_raises(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="actions" required /></div>'

        with pytest.raises(RuntimeError, match="Slot 'actions' of component 'Card' is marked as required"):
            str(Card())

    def test_required_error_suggests_close_fill_name(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="header" required /></div>'

        with pytest.raises(RuntimeError, match="Did you mean 'headre'"):
            str(Card(slots={"headre": "typo"}))

    def test_required_filled_is_fine(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="actions" required>FB</c-slot></div>'

        assert str(Card(slots={"actions": "OK"})) == '<div data-cid-c1="">OK</div>'

    def test_required_in_untaken_branch_does_not_raise(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-if cond="flag"><c-slot name="actions" required /></c-if>no slot</div>'

            def template_data(self, kwargs, slots=None):
                return {"flag": False}

        # Resolution is render-time by design: a slot in an untaken branch
        # never renders, so it cannot complain.
        assert str(Card()) == '<div data-cid-c1="">no slot</div>'

    def test_dynamic_c_required(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="actions" c-required="strict" /></div>'

            def template_data(self, kwargs, slots=None):
                return {"strict": self.raw_kwargs.get("strict", False)}

        assert str(Card()) == '<div data-cid-c1=""></div>'
        with pytest.raises(RuntimeError, match="marked as required"):
            str(Card(strict=True))


class TestScopedSlotData:
    def test_slot_data_reaches_fill(self):
        c = Citry()

        class UserList(Component):
            citry = c
            template = '<ul><c-for each="u in users"><li><c-slot name="item" c-user="u" /></li></c-for></ul>'

            def template_data(self, kwargs, slots=None):
                return {"users": ["Ann", "Bob"]}

        class Page(Component):
            citry = c
            template = '<c-user-list><c-fill name="item" data="s">Hi {{ s["user"] }}</c-fill></c-user-list>'

        # The same fill renders once per slot site, each with that
        # iteration's data.
        assert str(Page()) == '<ul data-cid-c2="" data-cid-c1=""><li>Hi Ann</li><li>Hi Bob</li></ul>'

    def test_static_attrs_become_string_data(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="x" kind="static" /></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="x" data="d">{{ d["kind"] }}</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">static</div>'

    def test_c_bind_spreads_slot_data_and_props(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot c-bind="props" /></div>'

            def template_data(self, kwargs, slots=None):
                return {"props": {"name": "item", "n": 42}}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="item" data="d">n={{ d["n"] }}</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">n=42</div>'

    def test_fill_without_data_opt_in_ignores_data(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="x" c-n="1" /></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="x">plain</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">plain</div>'

    def test_dynamic_slot_name(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot c-name="which" /></div>'

            def template_data(self, kwargs, slots=None):
                return {"which": "header"}

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header">H</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">H</div>'


class TestFallbackAccess:
    def test_fill_can_wrap_fallback(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="title"><h1>Fallback Title</h1></c-slot></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="title" fallback="fb"><b>[{{ fb }}]</b></c-fill></c-card>'

        # The README's "wrap the fallback with extra markup" example.
        assert str(Page()) == ('<div data-cid-c2="" data-cid-c1=""><b>[<h1>Fallback Title</h1>]</b></div>')

    def test_fallback_coerced_multiple_times(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="t">FB</c-slot></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="t" fallback="fb">{{ fb }}+{{ fb }}</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">FB+FB</div>'


class TestSlotComposition:
    def test_same_fill_renders_at_multiple_slot_sites(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="x" />|<c-slot name="x" /></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="x">F</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">F|F</div>'

    def test_passthrough_slot(self):
        c = Citry()

        class Inner(Component):
            citry = c
            template = '<i><c-slot name="x">inner-fb</c-slot></i>'

        class Mid(Component):
            citry = c
            # Mid forwards its own "x" slot into Inner's "x" slot. The
            # <c-slot> inside the fill body resolves against MID's fills,
            # because the fill body closed over Mid's context.
            template = '<c-inner><c-fill name="x"><c-slot name="x">mid-fb</c-slot></c-fill></c-inner>'

        class Page(Component):
            citry = c
            template = '<c-mid><c-fill name="x">from page</c-fill></c-mid>'

        class PageNoFill(Component):
            citry = c
            template = "<c-mid />"

        assert str(Page()) == '<i data-cid-c3="" data-cid-c2="" data-cid-c1="">from page</i>'
        # Second render: c4 is PageNoFill, c5 Mid, c6 Inner.
        assert str(PageNoFill()) == '<i data-cid-c6="" data-cid-c5="" data-cid-c4="">mid-fb</i>'

    def test_slot_inside_slot_fallback(self):
        c = Citry()

        class Card(Component):
            citry = c
            # The outer slot's fallback contains another slot.
            template = '<div><c-slot name="outer"><c-slot name="inner">deep-fb</c-slot></c-slot></div>'

        class PageFillsInner(Component):
            citry = c
            template = '<c-card><c-fill name="inner">I</c-fill></c-card>'

        class PageFillsOuter(Component):
            citry = c
            template = '<c-card><c-fill name="outer">O</c-fill></c-card>'

        # Filling only the inner slot renders the outer fallback with it;
        # filling the outer slot short-circuits the inner one entirely.
        assert str(PageFillsInner()) == '<div data-cid-c2="" data-cid-c1="">I</div>'
        # Second render: c3 is PageFillsOuter, c4 its Card.
        assert str(PageFillsOuter()) == '<div data-cid-c4="" data-cid-c3="">O</div>'

    def test_component_inside_fill_rendered_at_slot_site(self):
        c = Citry()

        class Icon(Component):
            citry = c
            template = "<svg>icon</svg>"

        class Card(Component):
            citry = c
            template = '<div><c-slot name="x" /></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="x"><c-icon /></c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1=""><svg data-cid-c3="">icon</svg></div>'


class TestOnSlotRenderedHook:
    def test_hook_observes_slot_renders(self):
        seen = []

        class Spy(Extension):
            name = "spy"

            def on_slot_rendered(self, ctx):
                seen.append((type(ctx.component).__name__, ctx.slot_name, ctx.slot_is_required, str(ctx.result)))

        c = Citry(extensions=[Spy])

        class Card(Component):
            citry = c
            template = '<div><c-slot name="h">FB</c-slot></div>'

        str(Card(slots={"h": "H"}))
        str(Card())
        assert seen == [("Card", "h", False, "H"), ("Card", "h", False, "FB")]

    def test_hook_replaces_result(self):
        class Upper(Extension):
            name = "upper"

            def on_slot_rendered(self, ctx):
                return str(ctx.result).upper()

        c = Citry(extensions=[Upper])

        class Card(Component):
            citry = c
            template = '<div><c-slot name="h">fb</c-slot></div>'

        assert str(Card(slots={"h": "hi"})) == '<div data-cid-c1="">HI</div>'

    def test_hook_raise_propagates(self):
        class Boom(Extension):
            name = "boom"

            def on_slot_rendered(self, ctx):
                msg = "no slots today"
                raise ValueError(msg)

        c = Citry(extensions=[Boom])

        class Card(Component):
            citry = c
            template = "<div><c-slot /></div>"

        with pytest.raises(ValueError, match="no slots today"):
            str(Card())

    def test_hook_sees_fill_slot_vs_fallback_slot(self):
        kinds = []

        class Spy(Extension):
            name = "spy"

            def on_slot_rendered(self, ctx):
                kinds.append(isinstance(ctx.slot, Slot))

        c = Citry(extensions=[Spy])

        class Card(Component):
            citry = c
            template = '<div><c-slot name="h">FB</c-slot></div>'

        str(Card(slots={"h": "H"}))
        str(Card())
        # Both paths hand the hook a Slot: the fill, or the fallback wrapper.
        assert kinds == [True, True]


class TestSlotErrors:
    def test_boolean_name_raises(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<div><c-slot name /></div>"

        with pytest.raises(RuntimeError, match="must resolve to a non-empty string"):
            str(Card())

    def test_c_bind_must_be_mapping(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot c-bind="props" /></div>'

            def template_data(self, kwargs, slots=None):
                return {"props": ["not", "a", "mapping"]}

        with pytest.raises(RuntimeError, match="must resolve to a mapping"):
            str(Card())
