"""Tests for the component registry."""

# ruff: noqa: ANN

import pytest

from citry import AlreadyRegistered, Citry, Component, NotRegistered


class TestRegistration:
    def test_auto_registered_on_class_definition(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        assert c.has("mycomp")

    def test_multiple_components(self):
        c = Citry()

        class CompA(Component):
            citry = c

        class CompB(Component):
            citry = c

        assert c.has("compa")
        assert c.has("compb")


class TestNameNormalization:
    def test_pascal_case_lowered(self):
        c = Citry()

        class MyCard(Component):
            citry = c

        assert c.has("mycard")

    def test_pascal_case_also_registers_kebab(self):
        c = Citry()

        class MyCard(Component):
            citry = c

        assert c.has("my-card")
        assert c.get("mycard") is c.get("my-card")

    def test_single_word_no_duplicate(self):
        c = Citry()

        class Card(Component):
            citry = c

        assert c.has("card")
        assert c.get("card") is Card

    def test_explicit_name_override(self):
        c = Citry()

        class MyWidget(Component):
            citry = c
            name = "fancy-widget"

        assert c.has("fancy-widget")

    def test_case_insensitive_lookup(self):
        c = Citry()

        class MyCard(Component):
            citry = c

        assert c.get("MyCard") is MyCard
        assert c.get("MYCARD") is MyCard
        assert c.get("mycard") is MyCard


class TestGet:
    def test_get_returns_class(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        assert c.get("mycomp") is MyComp

    def test_get_not_registered_raises(self):
        c = Citry()
        with pytest.raises(NotRegistered):
            c.get("nonexistent")


class TestHas:
    def test_has_registered(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        assert c.has("mycomp") is True

    def test_has_not_registered(self):
        c = Citry()
        assert c.has("nonexistent") is False


class TestComponentsDict:
    def test_components_dict(self):
        c = Citry()

        class Card(Component):
            citry = c

        comps = c.components
        assert "card" in comps
        assert comps["card"] is Card


class TestManualRegister:
    def test_manual_register_with_name(self):
        c = Citry()
        c2 = Citry()

        class Card(Component):
            citry = c

        c2.register(Card, name="my-card")
        assert c2.has("my-card")
        assert c2.get("my-card") is Card

    def test_reregister_same_class_is_noop(self):
        c = Citry()

        class Card(Component):
            citry = c

        c.register(Card)


class TestUnregister:
    def test_unregister_by_class(self):
        c = Citry()

        class Card(Component):
            citry = c

        assert c.has("card")
        c.unregister(Card)
        assert not c.has("card")

    def test_unregister_by_class_removes_all_names(self):
        c = Citry()

        class MyCard(Component):
            citry = c

        assert c.has("mycard")
        assert c.has("my-card")
        c.unregister(MyCard)
        assert not c.has("mycard")
        assert not c.has("my-card")

    def test_unregister_by_name(self):
        c = Citry()

        class Card(Component):
            citry = c

        c.unregister("card")
        assert not c.has("card")

    def test_unregister_not_registered_raises(self):
        c = Citry()
        with pytest.raises(NotRegistered):
            c.unregister("nonexistent")


class TestDuplicateDetection:
    def test_duplicate_name_raises(self):
        c = Citry()

        class Card(Component):
            citry = c

        with pytest.raises(AlreadyRegistered):

            class Card2(Component):
                citry = c
                name = "card"


class TestNameValidation:
    def test_valid_names(self):
        c = Citry()
        for valid_name in ["card", "my-card", "Card123", "a.b", "my_comp"]:

            class Tmp(Component):
                citry = c
                name = valid_name

            c.clear()

    def test_invalid_name_starts_with_digit(self):
        c = Citry()
        with pytest.raises(ValueError, match="Invalid component name"):

            class Bad(Component):
                citry = c
                name = "123card"

    def test_invalid_name_has_spaces(self):
        c = Citry()
        with pytest.raises(ValueError, match="Invalid component name"):

            class Bad(Component):
                citry = c
                name = "my card"
