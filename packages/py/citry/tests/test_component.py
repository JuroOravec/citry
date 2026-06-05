"""Tests for the Component base class."""

# ruff: noqa: ANN

from citry import Citry, Component, RenderObject


class TestComponentFields:
    def test_template_field(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>Hello</p>"

        assert MyComp.template == "<p>Hello</p>"

    def test_template_file_field(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template_file = "my_comp.html"

        assert MyComp.template_file == "my_comp.html"

    def test_kwargs_auto_dataclass(self):
        c = Citry()

        class MyComp(Component):
            citry = c

            class Kwargs:
                title: str
                size: int = 10

        from dataclasses import is_dataclass

        assert is_dataclass(MyComp.Kwargs)
        instance = MyComp.Kwargs(title="Hello")
        assert instance.title == "Hello"
        assert instance.size == 10

    def test_kwargs_already_dataclass_not_double_wrapped(self):
        c = Citry()
        from dataclasses import dataclass

        @dataclass
        class MyKwargs:
            title: str

        class MyComp(Component):
            citry = c
            Kwargs = MyKwargs

        assert MyComp.Kwargs is MyKwargs

    def test_kwargs_with_explicit_base_not_converted(self):
        c = Citry()
        from typing import NamedTuple

        class MyKwargs(NamedTuple):
            title: str

        class MyComp(Component):
            citry = c
            Kwargs = MyKwargs

        assert MyComp.Kwargs is MyKwargs

    def test_slots_auto_dataclass(self):
        c = Citry()

        class MyComp(Component):
            citry = c

            class Slots:
                header: str
                footer: str = ""

        from dataclasses import is_dataclass

        assert is_dataclass(MyComp.Slots)
        instance = MyComp.Slots(header="H")
        assert instance.header == "H"
        assert instance.footer == ""

    def test_auto_dataclass_has_slots(self):
        c = Citry()

        class MyComp(Component):
            citry = c

            class Kwargs:
                title: str

        assert hasattr(MyComp.Kwargs, "__slots__")


class TestComponentCall:
    def test_calling_component_returns_render_object(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        result = MyComp(title="Hello")
        assert isinstance(result, RenderObject)

    def test_render_object_holds_class_and_kwargs(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        ro = MyComp(title="Hello", size=10)
        assert ro.comp_cls is MyComp
        assert ro.kwargs == {"title": "Hello", "size": 10}

    def test_render_object_repr(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        ro = MyComp(title="Hello")
        assert "MyComp" in repr(ro)
        assert "title" in repr(ro)

    def test_render_object_empty_kwargs(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        ro = MyComp()
        assert ro.kwargs == {}
        assert ro.slots == {}


class TestCreateInstance:
    def test_create_instance_returns_component(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        inst = MyComp._create_instance()
        assert isinstance(inst, MyComp)
        assert isinstance(inst, Component)

    def test_create_instance_passes_init_kwargs(self):
        c = Citry()

        class MyComp(Component):
            citry = c

            def __init__(self, render_id=None):
                self.render_id = render_id

        inst = MyComp._create_instance(render_id="abc123")
        assert inst.render_id == "abc123"


class TestTemplateData:
    def test_default_returns_none(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        inst = MyComp._create_instance()
        assert inst.template_data(kwargs={}) is None

    def test_override_returns_dict(self):
        c = Citry()

        class MyComp(Component):
            citry = c

            def template_data(self, kwargs, slots=None, context=None):
                return {"greeting": f"Hello {kwargs['name']}!"}

        inst = MyComp._create_instance()
        data = inst.template_data(kwargs={"name": "World"})
        assert data == {"greeting": "Hello World!"}


class TestComponentRepr:
    def test_repr(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        inst = MyComp._create_instance()
        assert repr(inst) == "<MyComp>"


class TestComponentName:
    def test_name_field_overrides_class_name(self):
        c = Citry()

        class MyWidget(Component):
            citry = c
            name = "fancy-widget"

        assert c.has("fancy-widget")
        assert not c.has("mywidget")

    def test_default_name_from_class(self):
        c = Citry()

        class UserCard(Component):
            citry = c

        assert c.has("usercard")
        assert c.has("user-card")
