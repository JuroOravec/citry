"""Tests for the Component base class."""

# ruff: noqa: ANN

from citry import Component


class TestComponentFields:
    def test_template_field(self):
        class MyComp(Component):
            template = "<p>Hello</p>"

        assert MyComp.template == "<p>Hello</p>"

    def test_template_file_field(self):
        class MyComp(Component):
            template_file = "my_comp.html"

        assert MyComp.template_file == "my_comp.html"

    def test_kwargs_auto_dataclass(self):
        class MyComp(Component):
            class Kwargs:
                title: str
                size: int = 10

        from dataclasses import is_dataclass

        assert is_dataclass(MyComp.Kwargs)
        instance = MyComp.Kwargs(title="Hello")
        assert instance.title == "Hello"
        assert instance.size == 10

    def test_kwargs_already_dataclass_not_double_wrapped(self):
        from dataclasses import dataclass

        @dataclass
        class MyKwargs:
            title: str

        class MyComp(Component):
            Kwargs = MyKwargs

        assert MyComp.Kwargs is MyKwargs

    def test_kwargs_with_explicit_base_not_converted(self):
        from typing import NamedTuple

        class MyKwargs(NamedTuple):
            title: str

        class MyComp(Component):
            Kwargs = MyKwargs

        assert MyComp.Kwargs is MyKwargs

    def test_slots_auto_dataclass(self):
        class MyComp(Component):
            class Slots:
                header: str
                footer: str = ""

        from dataclasses import is_dataclass

        assert is_dataclass(MyComp.Slots)
        instance = MyComp.Slots(header="H")
        assert instance.header == "H"
        assert instance.footer == ""

    def test_auto_dataclass_has_slots(self):
        class MyComp(Component):
            class Kwargs:
                title: str

        assert hasattr(MyComp.Kwargs, "__slots__")


class TestGetTemplateData:
    def test_default_returns_none(self):
        class MyComp(Component):
            pass

        comp = MyComp()
        assert comp.template_data(kwargs={}) is None

    def test_override_returns_dict(self):
        class MyComp(Component):
            def template_data(self, kwargs, slots=None, context=None):
                return {"greeting": f"Hello {kwargs['name']}!"}

        comp = MyComp()
        data = comp.template_data(kwargs={"name": "World"})
        assert data == {"greeting": "Hello World!"}


class TestComponentRepr:
    def test_repr(self):
        class MyComp(Component):
            pass

        assert repr(MyComp()) == "<MyComp>"
