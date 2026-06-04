"""
The Component base class.

A Component is a reusable unit of UI. It owns a template, optionally
defines typed inputs (via inner classes), and produces rendered output
through its lifecycle methods.

Example:
    Minimal component::

        from citry import Component

        class Greeting(Component):
            template = '<p>Hello {{ name }}!</p>'

            def template_data(self, kwargs):
                return {"name": kwargs.get("name", "World")}

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

"""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from typing import Any, ClassVar

from citry.citry import Citry, citry


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

        # Register with the Citry instance
        citry_instance = getattr(cls, "citry", None)
        if citry_instance is None:
            citry_instance = citry
            cls.citry = citry_instance  # type: ignore[attr-defined]
        citry_instance._register_component(cls)  # type: ignore[arg-type]

        return cls  # type: ignore[return-value]

    def __del__(cls) -> None:
        citry_instance = getattr(cls, "citry", None)
        if citry_instance is not None:
            citry_instance._unregister_component(cls)  # type: ignore[arg-type]


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
