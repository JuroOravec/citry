"""Tests for the Component base class."""

# ruff: noqa: ANN

import pytest

from citry import Citry, CitryElement, Component


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
    def test_calling_component_returns_citry_element(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        result = MyComp(title="Hello")
        assert isinstance(result, CitryElement)

    def test_citry_element_holds_class_and_kwargs(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        ro = MyComp(title="Hello", size=10)
        assert ro.comp_cls is MyComp
        assert ro.kwargs == {"title": "Hello", "size": 10}

    def test_citry_element_repr(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        ro = MyComp(title="Hello")
        assert "MyComp" in repr(ro)
        assert "title" in repr(ro)

    def test_citry_element_empty_kwargs(self):
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


class TestInputNormalization:
    """kwargs/slots may be a dict, NamedTuple, or dataclass; all normalize to a dict."""

    def test_dict_kwargs_is_defensively_copied(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        src = {"title": "Hi"}
        inst = MyComp._create_instance(kwargs=src)
        assert inst.raw_kwargs == {"title": "Hi"}
        # A re-render must not be able to mutate the caller's dict.
        assert inst.raw_kwargs is not src

    def test_namedtuple_kwargs(self):
        from typing import NamedTuple

        c = Citry()

        class MyComp(Component):
            citry = c

        class K(NamedTuple):
            title: str
            size: int = 10

        inst = MyComp._create_instance(kwargs=K(title="Hi"))
        assert inst.raw_kwargs == {"title": "Hi", "size": 10}

    def test_dataclass_kwargs(self):
        from dataclasses import dataclass

        c = Citry()

        class MyComp(Component):
            citry = c

        @dataclass
        class K:
            title: str
            size: int = 10

        inst = MyComp._create_instance(kwargs=K(title="Hi"))
        assert inst.raw_kwargs == {"title": "Hi", "size": 10}

    def test_dataclass_slots(self):
        from dataclasses import dataclass

        c = Citry()

        class MyComp(Component):
            citry = c

        @dataclass
        class S:
            header: str

        inst = MyComp._create_instance(slots=S(header="H"))
        assert inst.raw_slots == {"header": "H"}

    def test_none_inputs_default_to_empty_dicts(self):
        c = Citry()

        class MyComp(Component):
            citry = c

        inst = MyComp._create_instance()
        assert inst.raw_kwargs == {}
        assert inst.raw_slots == {}

    def test_typed_input_rebuilt_as_declared_kwargs(self):
        # A NamedTuple input is normalized to a dict, then rebuilt as the
        # component's own declared Kwargs dataclass.
        from dataclasses import is_dataclass
        from typing import NamedTuple

        c = Citry()

        class MyComp(Component):
            citry = c

            class Kwargs:
                title: str

        class K(NamedTuple):
            title: str

        inst = MyComp._create_instance(kwargs=K(title="Hi"))
        assert is_dataclass(inst.kwargs)
        assert inst.kwargs.title == "Hi"
        assert inst.raw_kwargs == {"title": "Hi"}


class TestTemplateDataNormalization:
    """template_data() may return a dict, NamedTuple, or dataclass."""

    def test_dict_template_data_renders(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None, context=None):
                return {"title": "Hello"}

        assert MyComp(title="x").render() == "<p>hi</p>"

    def test_namedtuple_template_data_renders(self):
        # Before normalization `dict(namedtuple)` raised ValueError.
        from typing import NamedTuple

        class Data(NamedTuple):
            title: str

        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None, context=None):
                return Data(title="Hello")

        assert MyComp(title="x").render() == "<p>hi</p>"

    def test_dataclass_template_data_renders(self):
        from dataclasses import dataclass

        @dataclass
        class Data:
            title: str

        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None, context=None):
                return Data(title="Hello")

        assert MyComp(title="x").render() == "<p>hi</p>"


class TestTemplateDataValidation:
    """If a component declares a `TemplateData` schema, the data is validated against it."""

    def test_valid_data_passes(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            class TemplateData:
                title: str

            def template_data(self, kwargs, slots=None, context=None):
                return {"title": "Hello"}

        assert MyComp(title="x").render() == "<p>hi</p>"

    def test_missing_required_field_raises(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            class TemplateData:
                title: str

            def template_data(self, kwargs, slots=None, context=None):
                return {}

        with pytest.raises(TypeError):
            MyComp(title="x").render()

    def test_unexpected_field_raises(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            class TemplateData:
                title: str

            def template_data(self, kwargs, slots=None, context=None):
                return {"title": "Hello", "bogus": 1}

        with pytest.raises(TypeError):
            MyComp(title="x").render()

    def test_template_data_instance_skips_revalidation(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            class TemplateData:
                title: str

            def template_data(self, kwargs, slots=None, context=None):
                return MyComp.TemplateData(title="Hello")

        assert MyComp(title="x").render() == "<p>hi</p>"

    def test_no_template_data_schema_skips_validation(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots=None, context=None):
                return {"anything": "goes", "count": 3}

        assert MyComp(title="x").render() == "<p>hi</p>"


class TestGeneratorCaching:
    """The body-generating function is cached per component class."""

    def test_repeated_render_is_stable(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

        ro = MyComp(title="x")
        assert ro.render() == "<p>hi</p>"
        assert ro.render() == "<p>hi</p>"  # repeatable

    def test_generator_cached_on_class_and_shared(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

        assert "_template_body_generator" not in MyComp.__dict__

        MyComp(title="a").render()
        gen = MyComp.__dict__["_template_body_generator"]
        assert callable(gen)

        # A second CitryElement reuses the same class-level generator.
        MyComp(title="b").render()
        assert MyComp.__dict__["_template_body_generator"] is gen

    def test_subclass_template_override_gets_own_generator(self):
        c = Citry()

        class Base(Component):
            citry = c
            template = "<p>base</p>"

        class Child(Base):
            template = "<p>child</p>"

        Base(x=1).render()
        Child(x=1).render()

        assert Base.__dict__["_template_body_generator"] is not Child.__dict__["_template_body_generator"]
        assert Base(x=1).render() == "<p>base</p>"
        assert Child(x=1).render() == "<p>child</p>"
