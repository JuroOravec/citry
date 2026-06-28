"""Tests for the Component base class."""

# ruff: noqa: ANN

import pytest

from citry import Citry, CitryElement, Component, Slot


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

    def test_cls_kwarg_does_not_collide_with_metaclass(self):
        # `cls` is positional-only on ComponentMeta.__call__, so a component may
        # accept a keyword argument named `cls` (e.g. an HTML class).
        c = Citry()

        class MyComp(Component):
            citry = c

        ro = MyComp(cls="card", title="Hi")
        assert isinstance(ro, CitryElement)
        assert ro.comp_cls is MyComp
        assert ro.kwargs == {"cls": "card", "title": "Hi"}


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

            def template_data(self, kwargs, slots):
                return {"greeting": f"Hello {kwargs['name']}!"}

        inst = MyComp._create_instance()
        # The framework always calls template_data with both kwargs and slots
        # (see component_render.py); this override declares the documented
        # (kwargs, slots) signature, so both must be supplied.
        data = inst.template_data(kwargs={"name": "World"}, slots=None)
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
        # Slot inputs normalize to Slot values (docs/design/slots.md section 9.2).
        assert set(inst.raw_slots) == {"header"}
        assert isinstance(inst.raw_slots["header"], Slot)
        assert inst.raw_slots["header"]() == "H"

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

            def template_data(self, kwargs, slots):
                return {"title": "Hello"}

        assert MyComp(title="x").render().serialize() == '<p data-cid-c1="">hi</p>'

    def test_namedtuple_template_data_renders(self):
        # Before normalization `dict(namedtuple)` raised ValueError.
        from typing import NamedTuple

        class Data(NamedTuple):
            title: str

        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots):
                return Data(title="Hello")

        assert MyComp(title="x").render().serialize() == '<p data-cid-c1="">hi</p>'

    def test_dataclass_template_data_renders(self):
        from dataclasses import dataclass

        @dataclass
        class Data:
            title: str

        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots):
                return Data(title="Hello")

        assert MyComp(title="x").render().serialize() == '<p data-cid-c1="">hi</p>'


class TestTemplateDataValidation:
    """If a component declares a `TemplateData` schema, the data is validated against it."""

    def test_valid_data_passes(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            class TemplateData:
                title: str

            def template_data(self, kwargs, slots):
                return {"title": "Hello"}

        assert MyComp(title="x").render().serialize() == '<p data-cid-c1="">hi</p>'

    def test_missing_required_field_raises(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            class TemplateData:
                title: str

            def template_data(self, kwargs, slots):
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

            def template_data(self, kwargs, slots):
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

            def template_data(self, kwargs, slots):
                return MyComp.TemplateData(title="Hello")

        assert MyComp(title="x").render().serialize() == '<p data-cid-c1="">hi</p>'

    def test_no_template_data_schema_skips_validation(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots):
                return {"anything": "goes", "count": 3}

        assert MyComp(title="x").render().serialize() == '<p data-cid-c1="">hi</p>'


class TestGeneratorCaching:
    """The body-generating function is cached per component class."""

    def test_repeated_render_is_stable(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

        ro = MyComp(title="x")
        assert ro.render().serialize() == '<p data-cid-c1="">hi</p>'
        assert ro.render().serialize() == '<p data-cid-c2="">hi</p>'  # fresh id per render

    def test_generator_cached_on_class_and_shared(self):
        c = Citry()

        class MyComp(Component):
            citry = c
            template = "<p>hi</p>"

        assert "_citry_template" not in MyComp.__dict__

        MyComp(title="a").render()
        compiled = MyComp.__dict__["_citry_template"]
        assert callable(compiled.generate)

        # A second CitryElement reuses the same class-level compiled template.
        MyComp(title="b").render()
        assert MyComp.__dict__["_citry_template"] is compiled

    def test_subclass_template_override_gets_own_generator(self):
        c = Citry()

        class Base(Component):
            citry = c
            template = "<p>base</p>"

        class Child(Base):
            template = "<p>child</p>"

        Base(x=1).render()
        Child(x=1).render()

        assert Base.__dict__["_citry_template"] is not Child.__dict__["_citry_template"]
        assert Base(x=1).render().serialize() == '<p data-cid-c3="">base</p>'
        assert Child(x=1).render().serialize() == '<p data-cid-c4="">child</p>'


class TestAncestors:
    def test_root_component_has_no_ancestors(self):
        c = Citry()
        seen = []

        class Root(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots):
                seen.append(list(self.ancestors))

        Root().render()
        assert seen == [[]]

    def test_yields_chain_nearest_first_including_root(self):
        c = Citry()
        seen = []

        class Leaf(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots):
                seen.append([type(a).__name__ for a in self.ancestors])

        class Middle(Component):
            citry = c
            template = "<section><c-leaf /></section>"

        class Root(Component):
            citry = c
            template = "<main><c-middle /></main>"

        Root().render()
        assert seen == [["Middle", "Root"]]

    def test_isinstance_check_use_case(self):
        # The use case ancestors exists for: "is this component rendered
        # inside a Theme?" The chain follows who wrote the component (the
        # `parent` contract), so this holds when Theme's own template renders
        # the widget; content passed into Theme's slots keeps its writer's
        # chain instead (see the fill test below).
        c = Citry()
        seen = []

        class Widget(Component):
            citry = c
            template = "<i>w</i>"

            def template_data(self, kwargs, slots):
                seen.append(any(type(a).__name__ == "Theme" for a in self.ancestors))

        class Theme(Component):
            citry = c
            template = "<div><c-widget /></div>"

        class Page(Component):
            citry = c
            template = "<main><c-theme /><c-widget /></main>"

        Page().render()
        assert seen == [True, False]

    def test_embedded_element_starts_a_fresh_chain(self):
        # An element rendered via {{ em }} has no parent link, so its chain
        # is empty (same contract as `parent`).
        c = Citry()
        seen = []

        class Embedded(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots):
                seen.append(list(self.ancestors))

        class Root(Component):
            citry = c
            template = "<main>{{ em }}</main>"

            def template_data(self, kwargs, slots):
                return {"em": Embedded()}

        Root().render()
        assert seen == [[]]

    def test_fill_content_follows_the_writer_chain(self):
        # A component written inside a fill has the fill's author as parent;
        # the slot owner is not in its chain (same contract as `parent`).
        c = Citry()
        seen = []

        class Inner(Component):
            citry = c
            template = "<i>x</i>"

            def template_data(self, kwargs, slots):
                seen.append([type(a).__name__ for a in self.ancestors])

        class Card(Component):
            citry = c
            template = '<div><c-slot name="body" /></div>'

        class Page(Component):
            citry = c
            template = '<c-card><c-fill name="body"><c-inner /></c-fill></c-card>'

        Page().render()
        assert seen == [["Page"]]
