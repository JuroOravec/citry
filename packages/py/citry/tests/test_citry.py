"""Tests for the Citry global instance."""

# ruff: noqa: ANN

from citry import Citry, Component
from citry import citry as default_citry


class TestCitryInstance:
    def test_create_empty(self):
        c = Citry()
        assert len(c.components) == 0

    def test_repr(self):
        c = Citry()
        assert repr(c) == "Citry(components=0)"

    def test_clear(self):
        c = Citry()

        class A(Component):
            citry = c

        assert len(c.components) >= 1
        c.clear()
        assert len(c.components) == 0

    def test_settings_stored(self):
        c = Citry(debug=True, base_dir="/tmp")
        assert c._settings == {"debug": True, "base_dir": "/tmp"}


class TestDefaultCitryInstance:
    def test_default_instance_is_citry(self):
        assert isinstance(default_citry, Citry)

    def test_default_instance_is_stable(self):
        from citry import citry as d2

        assert default_citry is d2


class TestComponentRegistration:
    def test_component_assigned_to_default(self):
        class MyComp(Component):
            pass

        assert MyComp.citry is default_citry
        assert MyComp in default_citry.components

    def test_component_assigned_to_explicit_citry(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        assert MyComp.citry is c
        assert MyComp in c.components
        assert MyComp not in default_citry.components

    def test_multiple_components_same_citry(self):
        c = Citry()

        class A(Component):
            citry = c

        class B(Component):
            citry = c

        assert A in c.components
        assert B in c.components
        assert len(c.components) >= 2

    def test_components_on_different_citry_instances(self):
        c1 = Citry()
        c2 = Citry()

        class A(Component):
            citry = c1

        class B(Component):
            citry = c2

        assert A in c1.components
        assert A not in c2.components
        assert B in c2.components
        assert B not in c1.components
