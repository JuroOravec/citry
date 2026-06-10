"""Tests for the Citry global instance."""

# ruff: noqa: ANN

from citry import Citry, Component
from citry import citry as default_citry


class TestCitryInstance:
    def test_create_empty(self):
        c = Citry()
        # A fresh instance carries exactly the built-in components (created
        # lazily on the first lookup), nothing else.
        assert set(c.components) == {"provide"}

    def test_repr(self):
        c = Citry()
        assert repr(c) == "Citry(components=0)"

    def test_clear(self):
        c = Citry()

        class A(Component):
            citry = c

        assert "a" in c.components
        c.clear()
        # User components are gone; the built-ins are recreated on lookup.
        assert set(c.components) == {"provide"}

    def test_settings_stored(self):
        # Citry now takes a typed settings schema (CitrySettings) rather than
        # arbitrary kwargs. extensions_defaults is stored on it.
        c = Citry(extensions_defaults={"view": {"ttl": 60}})
        assert c.settings.extensions_defaults == {"view": {"ttl": 60}}
        assert c.settings.extensions == ()

    def test_has_registry(self):
        from citry import ComponentRegistry

        c = Citry()
        assert isinstance(c.registry, ComponentRegistry)


class TestDefaultCitryInstance:
    def test_default_instance_is_citry(self):
        assert isinstance(default_citry, Citry)

    def test_default_instance_is_stable(self):
        from citry import citry as d2

        assert default_citry is d2


class TestCitryComponentAssignment:
    def test_component_assigned_to_default(self):
        class MyComp(Component):
            pass

        assert MyComp.citry is default_citry
        assert default_citry.has("mycomp")

    def test_component_assigned_to_explicit_citry(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        assert c.has("mycomp")

    def test_components_on_different_instances(self):
        c1 = Citry()
        c2 = Citry()

        class CompA(Component):
            citry = c1

        class CompB(Component):
            citry = c2

        assert c1.has("compa")
        assert not c1.has("compb")
        assert c2.has("compb")
        assert not c2.has("compa")
