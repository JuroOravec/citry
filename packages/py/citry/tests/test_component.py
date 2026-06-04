"""Tests for the Component base class."""

# ruff: noqa: ANN

from citry import Component, RenderObject


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


class TestComponentCall:
    def test_calling_component_returns_render_object(self):
        class MyComp(Component):
            pass

        result = MyComp(title="Hello")
        assert isinstance(result, RenderObject)

    def test_render_object_holds_class_and_kwargs(self):
        class MyComp(Component):
            pass

        ro = MyComp(title="Hello", size=10)
        assert ro.comp_cls is MyComp
        assert ro.kwargs == {"title": "Hello", "size": 10}

    def test_render_object_repr(self):
        class MyComp(Component):
            pass

        ro = MyComp(title="Hello")
        assert "MyComp" in repr(ro)
        assert "title" in repr(ro)

    def test_render_object_empty_kwargs(self):
        class MyComp(Component):
            pass

        ro = MyComp()
        assert ro.kwargs == {}
        assert ro.slots == {}


class TestCreateInstance:
    def test_create_instance_returns_component(self):
        class MyComp(Component):
            pass

        inst = MyComp._create_instance()
        assert isinstance(inst, MyComp)
        assert isinstance(inst, Component)

    def test_create_instance_passes_init_kwargs(self):
        class MyComp(Component):
            def __init__(self, render_id=None):
                self.render_id = render_id

        inst = MyComp._create_instance(render_id="abc123")
        assert inst.render_id == "abc123"


class TestTemplateData:
    def test_default_returns_none(self):
        class MyComp(Component):
            pass

        inst = MyComp._create_instance()
        assert inst.template_data(kwargs={}) is None

    def test_override_returns_dict(self):
        class MyComp(Component):
            def template_data(self, kwargs, slots=None, context=None):
                return {"greeting": f"Hello {kwargs['name']}!"}

        inst = MyComp._create_instance()
        data = inst.template_data(kwargs={"name": "World"})
        assert data == {"greeting": "Hello World!"}


class TestComponentRepr:
    def test_repr(self):
        class MyComp(Component):
            pass

        inst = MyComp._create_instance()
        assert repr(inst) == "<MyComp>"
