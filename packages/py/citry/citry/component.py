"""
The Component base class.

A Component is a reusable unit of UI. It owns a template, optionally
defines typed inputs (via inner classes), and produces rendered output
through its lifecycle methods.

Calling a Component class returns a CitryElement (composition phase),
not a rendered string. Rendering happens when ``.render()`` is called
on the CitryElement.

Example:
    Minimal component::

        from citry import Component

        class Greeting(Component):
            template = '<p>Hello {{ name }}!</p>'

            def template_data(self, kwargs):
                return {"name": kwargs.get("name", "World")}

        # Composition - returns a CitryElement
        element = Greeting(name="World")

        # Rendering - produces HTML (not yet implemented)
        # html = element.render()

    Component with typed inputs::

        from citry import Component

        class Card(Component):
            template = '''
                <div class="card">
                    <h2>{{ title }}</h2>
                    <div>{{ body }}</div>
                </div>
            '''

            class Kwargs:
                title: str
                body: str = ""

            def template_data(self, kwargs):
                return {
                    "title": kwargs.title,
                    "body": kwargs.body,
                }

        # Compose without rendering
        card = Card(title="Hello", body="Content")

"""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from citry.citry import Citry, citry
from citry.citry_element import CitryElement
from citry.component_render import gen_render_id
from citry.util.misc import to_dict

if TYPE_CHECKING:
    from collections.abc import Callable


class ComponentMeta(type):
    """
    Metaclass for Component classes.

    At class definition time, this metaclass:
    1. Reads the ``citry`` field (or uses the default Citry instance).
    2. Registers the component class with its Citry instance.
    3. Converts inner data classes (Kwargs, Slots, etc.) without explicit
       bases to dataclasses (with slots) for ergonomic input typing.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        attrs: dict[str, Any],
    ) -> ComponentMeta:
        # Detect whether we're defining the Component base class itself
        # vs a user subclass like `class MyCard(Component): ...`.
        #
        # A class is an instance of its metaclass. So once Component is
        # created (with metaclass=ComponentMeta), `isinstance(Component,
        # ComponentMeta)` is True. Any subclass of Component will have
        # Component in its `bases`, and Component passes the isinstance
        # check.
        #
        # When ComponentMeta.__new__ runs for Component itself, none of
        # its bases (just `object`) are instances of ComponentMeta, so
        # the check is False and we skip registration.
        #
        # When it runs for `class MyCard(Component)`, bases contains
        # Component, which IS an instance of ComponentMeta, so the check
        # is True and we proceed with registration.
        is_component_subclass = any(isinstance(b, ComponentMeta) for b in bases)
        if not is_component_subclass:
            return super().__new__(mcs, name, bases, attrs)  # type: ignore[return-value]

        # Convert inner data classes (Kwargs, Slots, TemplateData) to
        # dataclasses if they don't explicitly declare a base class or
        # the @dataclass decorator. This lets users write:
        #     class Kwargs:
        #         title: str
        #         size: int = 10
        # and get a dataclass with slots automatically.
        for data_class_name in ("Kwargs", "Slots", "TemplateData"):
            data_class = attrs.get(data_class_name)
            if data_class is None or not isinstance(data_class, type):
                continue
            if is_dataclass(data_class):
                continue
            if data_class.__bases__ != (object,):
                continue
            attrs[data_class_name] = dataclass(slots=True)(data_class)

        cls = super().__new__(mcs, name, bases, attrs)

        # Register with the Citry instance.
        # Uses the class name (or Component.name override) as the
        # registration name. The Citry.register() method handles
        # normalization (lowercasing, kebab-case derivation) and
        # duplicate detection.
        citry_instance = getattr(cls, "citry", None)
        if citry_instance is None:
            citry_instance = citry
            cls.citry = citry_instance  # type: ignore[attr-defined]
        citry_instance.register(cls)  # type: ignore[arg-type]

        return cls  # type: ignore[return-value]

    def __call__(cls, **kwargs: Any) -> CitryElement:
        """
        Intercept ``MyComp(title="Hi")`` to return a CitryElement.

        In citry, calling a Component class is the **composition** phase.
        It creates a CitryElement that describes what to render, without
        rendering it yet. Actual Component instances are created later
        during the **rendering** phase via ``_create_instance()``.

        This is analogous to React's ``<MyComp title="Hi" />`` producing
        a RenderElement, not a rendered DOM node.
        """
        return CitryElement(cls, kwargs)  # type: ignore[arg-type]

    def _create_instance(cls, **init_kwargs: Any) -> Component:
        """
        Create an actual Component instance (internal, for rendering).

        Bypasses ``__call__`` (which returns a CitryElement) by going
        through ``type.__call__`` directly. This is how the rendering
        pipeline creates real Component instances with render-time state
        (render_id, resolved context, etc.).

        Not part of the public API.
        """
        # In Python, writing `MyClass()` calls `type(MyClass).__call__(MyClass)`,
        # i.e. the metaclass's __call__. Our ComponentMeta.__call__ returns a
        # CitryElement. To create an actual instance, we skip our metaclass and
        # call type.__call__ directly, which is the base implementation that runs
        # cls.__new__ + cls.__init__ and returns a real instance of cls.
        return type.__call__(cls, **init_kwargs)  # type: ignore[return-value]

    def __del__(cls) -> None:
        citry_instance = getattr(cls, "citry", None)
        if citry_instance is not None:
            try:
                citry_instance.unregister(cls)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                pass


class Component(metaclass=ComponentMeta):
    """
    Base class for all Citry components.

    A component is a reusable unit of UI defined by:
    - A **template** (Citry V3 HTML-like syntax)
    - Optional **typed inputs** (via inner ``Kwargs``, ``Slots`` classes)
    - A **data method** that maps inputs to template variables

    Subclass this to define your own components. At minimum, set
    ``template`` (inline string) or ``template_file`` (path to file).
    """

    citry: ClassVar[Citry | None] = None
    """The Citry instance this component is registered with.

    Set this to assign the component to a specific Citry instance.
    If not set, the component is assigned to the default instance.
    """

    name: ClassVar[str | None] = None
    """Override the name under which this component is registered.

    By default, the class name is used (lowercased + kebab-case).
    Set this to register under a specific name instead::

        class MyWidget(Component):
            name = "fancy-widget"
            # registered as "fancy-widget", not "mywidget" / "my-widget"
    """

    template: ClassVar[str | None] = None
    """Inline template string (Citry V3 HTML-like syntax)."""

    template_file: ClassVar[str | None] = None
    """Path to a template file. Mutually exclusive with ``template``."""

    Kwargs: ClassVar[type | None] = None
    """Optional typed keyword arguments.

    Define as a plain class with type annotations. The metaclass
    converts it to a dataclass (with slots) automatically::

        class Card(Component):
            class Kwargs:
                title: str
                body: str = ""
    """

    Slots: ClassVar[type | None] = None
    """Optional typed slot definitions."""

    TemplateData: ClassVar[type | None] = None
    """Optional typed template data output."""

    _template_body_generator: ClassVar[Callable[[], list[Any]] | None] = None
    """Internal: the parsed+compiled body-generating function for this
    component's template, built once per class on first render and cached
    here (the Citry analog of Django's ``Component._template``). Calling it
    yields a fresh node list. Populated and read via ``__dict__`` by the
    render pipeline; not a user-facing field.
    """

    # ----- Instance fields -----
    # Declared here for typing and documentation. Values are set in
    # __init__, which is called by _render_impl via _create_instance().
    # Not available during composition (MyComp() returns a CitryElement).

    id: str
    """Unique render ID for this component instance.

    A fresh ID is minted every time a CitryElement is rendered, so the
    same CitryElement rendered twice produces two distinct IDs.
    """

    kwargs: Any
    """The resolved keyword arguments.

    If the component defines a ``Kwargs`` dataclass, this is an instance
    of that class. Otherwise, a plain dict.
    """

    raw_kwargs: dict[str, Any]
    """The keyword arguments as a plain dict, even if a ``Kwargs``
    dataclass is defined. Useful when you need dict access regardless
    of typing.
    """

    slots: Any
    """The resolved slot fills.

    If the component defines a ``Slots`` dataclass, this is an instance
    of that class. Otherwise, a plain dict.
    """

    raw_slots: dict[str, Any]
    """The slot fills as a plain dict, even if a ``Slots`` dataclass
    is defined. Useful when you need dict access regardless
    of typing.
    """

    parent: Component | None
    """The parent component instance, or None if this is a root component."""

    root: Component
    """The root component of the current render tree.

    For root components, ``self.root is self``. Never None.
    """

    def __init__(
        self,
        id: str | None = None,
        kwargs: Any = None,
        slots: Any = None,
        parent: Component | None = None,
    ) -> None:
        self.id = id if id is not None else gen_render_id()

        cls = type(self)

        # Normalize inputs to plain dicts. kwargs/slots may arrive as a dict,
        # a NamedTuple, or a dataclass (e.g. a typed `Kwargs`/`Slots`
        # instance), so run them through `to_dict`. The outer `dict(...)`
        # copies, so mutations during one render never leak back into a
        # CitryElement that may be rendered again.
        raw_kwargs: dict[str, Any] = dict(to_dict(kwargs)) if kwargs is not None else {}
        raw_slots: dict[str, Any] = dict(to_dict(slots)) if slots is not None else {}

        # Set typed kwargs/slots if the component defines a dataclass,
        # otherwise keep as plain dict.
        self.kwargs = cls.Kwargs(**raw_kwargs) if cls.Kwargs is not None else raw_kwargs
        self.slots = cls.Slots(**raw_slots) if cls.Slots is not None else raw_slots

        # raw_ variants are always plain dicts
        self.raw_kwargs = raw_kwargs
        self.raw_slots = raw_slots

        self.parent = parent
        self.root = parent.root if parent is not None else self

    def template_data(
        self,
        kwargs: Any,
        slots: Any | None = None,
        context: Any | None = None,
    ) -> dict[str, Any] | None:
        """
        Return the template context variables.

        Override this to map component inputs to template variables.
        The returned dict is used as the rendering context.

        Args:
            kwargs: The keyword arguments passed to the component.
            slots: The slot fills passed to the component.
            context: The parent rendering context (if any).

        Returns:
            A dict of template variables, or None to use kwargs directly.

        """
        return None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"
