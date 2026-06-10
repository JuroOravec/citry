"""
Tests for parse-time validation of component usage (citry/tag_rules.py).

A component's ``Kwargs``/``Slots`` declarations become parser ``user_rules``,
so a template that uses the component with unknown or missing kwargs/fills
fails when the template is parsed (at the parent's first render), not at
render time and not silently.
"""

import pytest

from citry import Citry, Component, SlotInput
from citry.tag_rules import build_tag_rules


def _declared_card(c):
    class Card(Component):
        citry = c
        template = '<div>{{ title }}<c-slot name="header" /></div>'

        class Kwargs:
            title: str
            size: int = 10

        class Slots:
            header: SlotInput
            footer: "SlotInput | None" = None

        def template_data(self, kwargs, slots=None):
            return {"title": kwargs.title}

    return Card


class TestBuildTagRules:
    def test_rules_derived_from_declarations(self):
        c = Citry()
        _declared_card(c)
        rules = build_tag_rules(c)

        card_rules = rules["c-card"]
        assert card_rules.allowed_attrs == [
            ["title", "c-title"],
            ["size", "c-size"],
            ["c-if"],
            ["c-elif"],
            ["c-else"],
            ["c-for"],
            ["c-empty"],
        ]
        assert card_rules.required_attrs == [["title", "c-title"]]
        assert card_rules.allowed_slots == ["header", "footer"]
        assert card_rules.required_slots == ["header"]

    def test_undeclared_component_gets_no_rules(self):
        c = Citry()

        class Plain(Component):
            citry = c
            template = "<p>x</p>"

        assert "c-plain" not in build_tag_rules(c)

    def test_kwargs_only_leaves_slots_unrestricted(self):
        c = Citry()

        class KwOnly(Component):
            citry = c
            template = "<p>x</p>"

            class Kwargs:
                title: str

        rules = build_tag_rules(c)["c-kw-only"]
        assert rules.allowed_slots is None
        assert rules.required_slots == []
        assert rules.allowed_attrs is not None

    def test_rules_for_both_registered_name_forms(self):
        c = Citry()

        class MyCard(Component):
            citry = c
            template = "<p>x</p>"

            class Kwargs:
                title: str

        rules = build_tag_rules(c)
        assert "c-mycard" in rules
        assert "c-my-card" in rules

    def test_cache_invalidated_on_register(self):
        c = Citry()
        assert c._tag_rules() == {}

        _declared_card(c)
        assert "c-card" in c._tag_rules()


class TestKwargsValidation:
    def test_unknown_attr_fails_at_parse(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="x" bogus="1"><c-fill name="header">H</c-fill></c-card>'

        with pytest.raises(SyntaxError, match="can only have the following attributes"):
            str(Page())

    def test_missing_required_kwarg_fails_at_parse(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="header">H</c-fill></c-card>'

        with pytest.raises(SyntaxError, match="must have one of the following attributes: 'title', 'c-title'"):
            str(Page())

    def test_dynamic_attr_form_accepted(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card c-title="t"><c-fill name="header">H</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"t": "T"}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">TH</div>'

    def test_static_and_dynamic_same_kwarg_fails(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="a" c-title="b"><c-fill name="header">H</c-fill></c-card>'

        with pytest.raises(SyntaxError):
            str(Page())

    def test_c_bind_bypasses_attr_checks(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card c-bind="props"><c-fill name="header">H</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"props": {"title": "T"}}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">TH</div>'

    def test_control_flow_attrs_allowed(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="T" c-if="flag"><c-fill name="header">H</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"flag": True}

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">TH</div>'

    def test_optional_kwarg_can_be_omitted(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="T"><c-fill name="header">H</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">TH</div>'


class TestSlotsValidation:
    def test_unknown_fill_fails_at_parse(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="T"><c-fill name="header">H</c-fill><c-fill name="bogus">B</c-fill></c-card>'

        with pytest.raises(SyntaxError, match="does not allow a slot named 'bogus'"):
            str(Page())

    def test_missing_required_slot_fails_at_parse(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="T"><c-fill name="footer">F</c-fill></c-card>'

        with pytest.raises(SyntaxError, match="must have a slot named 'header'"):
            str(Page())

    def test_implicit_default_content_rejected_when_not_declared(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="T">just text</c-card>'

        with pytest.raises(SyntaxError, match="does not allow a 'default' slot"):
            str(Page())

    def test_optional_slot_can_be_omitted(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="T"><c-fill name="header">H</c-fill></c-card>'

        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">TH</div>'

    def test_dynamic_fill_name_defers_per_name_checks(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-card title="T"><c-fill c-name="which">X</c-fill></c-card>'

            def template_data(self, kwargs, slots=None):
                return {"which": "header"}

        # A dynamic fill could resolve to the required name, so the per-name
        # check is deferred to runtime; this one does resolve to it.
        assert str(Page()) == '<div data-cid-c2="" data-cid-c1="">TX</div>'


class TestValidationScope:
    def test_case_insensitive_tag_spelling(self):
        c = Citry()
        _declared_card(c)

        class Page(Component):
            citry = c
            template = '<c-Card title="T" bogus="1"><c-fill name="header">H</c-fill></c-Card>'

        with pytest.raises(SyntaxError, match="can only have the following attributes"):
            str(Page())

    def test_nested_template_attr_is_validated(self):
        c = Citry()
        _declared_card(c)

        class Holder(Component):
            citry = c
            template = "<div>{{ body }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"body": kwargs["body"]}

        class Page(Component):
            citry = c
            template = "<c-holder c-body=\"<c-card bogus='1' />\" />"

        with pytest.raises(SyntaxError, match="can only have the following attributes"):
            str(Page())

    def test_component_registered_after_parent_class_still_validated(self):
        c = Citry()

        class Page(Component):
            citry = c
            template = '<c-late bogus="1" />'

        # `late` is declared AFTER Page's class definition but BEFORE Page's
        # first render; rules are built at parse time (first render), so the
        # declaration is seen.
        class Late(Component):
            citry = c
            template = "<p>x</p>"

            class Kwargs:
                title: str = "t"

        with pytest.raises(SyntaxError, match="can only have the following attributes"):
            str(Page())


# A stand-in following Pydantic's attribute protocol (v2: `model_fields` of
# infos with `is_required()`), so the duck-typed support is exercised without
# pydantic installed. The base class matters: like pydantic's BaseModel, it
# keeps the inner class from being auto-converted to a dataclass by the
# Component metaclass (which only converts plain `(object,)`-based classes).
class _FakeFieldInfo:
    def __init__(self, required):
        self._required = required

    def is_required(self):
        return self._required


class _FakeModelBase:
    model_fields: dict = {}

    def __init__(self, **data):
        for name in self.model_fields:
            setattr(self, name, data.get(name))


class TestFieldIntrospection:
    def test_get_fields_dataclass(self):
        from dataclasses import dataclass

        from citry.util.misc import FieldSpec, get_fields

        @dataclass
        class Kw:
            title: str
            size: int = 10

        assert get_fields(Kw) == [FieldSpec("title", required=True), FieldSpec("size", required=False)]

    def test_get_fields_namedtuple(self):
        from typing import NamedTuple

        from citry.util.misc import FieldSpec, get_fields

        class Kw(NamedTuple):
            title: str
            size: int = 10

        assert get_fields(Kw) == [FieldSpec("title", required=True), FieldSpec("size", required=False)]

    def test_get_fields_pydantic_v2_protocol(self):
        from citry.util.misc import FieldSpec, get_fields

        class Kw(_FakeModelBase):
            model_fields = {"title": _FakeFieldInfo(required=True), "size": _FakeFieldInfo(required=False)}

        assert get_fields(Kw) == [FieldSpec("title", required=True), FieldSpec("size", required=False)]

    def test_get_fields_pydantic_v1_protocol(self):
        from types import SimpleNamespace

        from citry.util.misc import FieldSpec, get_fields

        class Kw:
            __fields__ = {"title": SimpleNamespace(required=True), "size": SimpleNamespace(required=False)}

        assert get_fields(Kw) == [FieldSpec("title", required=True), FieldSpec("size", required=False)]

    def test_get_fields_unrecognized(self):
        from citry.util.misc import get_fields

        class Plain:
            title: str

        assert get_fields(None) is None
        assert get_fields(Plain) is None
        assert get_fields("not a class") is None

    def test_to_dict_pydantic_protocol_instance(self):
        from citry.util.misc import to_dict

        class Kw(_FakeModelBase):
            model_fields = {"title": _FakeFieldInfo(required=True)}

        assert to_dict(Kw(title="T")) == {"title": "T"}


class TestNonDataclassDeclarations:
    def test_namedtuple_kwargs_validated_and_render(self):
        from typing import NamedTuple

        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ title }}</p>"

            class Kwargs(NamedTuple):
                title: str
                size: int = 10

            def template_data(self, kwargs, slots=None):
                return {"title": kwargs.title}

        class Good(Component):
            citry = c
            template = '<c-card title="T" />'

        class Bad(Component):
            citry = c
            template = '<c-card title="T" bogus="1" />'

        assert str(Good()) == '<p data-cid-c2="" data-cid-c1="">T</p>'
        with pytest.raises(SyntaxError, match="can only have the following attributes"):
            str(Bad())

    def test_pydantic_protocol_kwargs_validated_and_render(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ title }}</p>"

            class Kwargs(_FakeModelBase):
                model_fields = {"title": _FakeFieldInfo(required=True)}

            def template_data(self, kwargs, slots=None):
                return {"title": kwargs.title}

        class Good(Component):
            citry = c
            template = '<c-card title="T" />'

        class Bad(Component):
            citry = c
            template = "<c-card />"

        assert str(Good()) == '<p data-cid-c2="" data-cid-c1="">T</p>'
        with pytest.raises(SyntaxError, match="must have one of the following attributes"):
            str(Bad())

    def test_real_pydantic_model(self):
        pydantic = pytest.importorskip("pydantic")

        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ title }}</p>"

            class Kwargs(pydantic.BaseModel):
                title: str
                size: int = 10

            def template_data(self, kwargs, slots=None):
                return {"title": kwargs.title}

        class Bad(Component):
            citry = c
            template = '<c-card title="T" bogus="1" />'

        with pytest.raises(SyntaxError, match="can only have the following attributes"):
            str(Bad())
