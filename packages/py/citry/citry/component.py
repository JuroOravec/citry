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

from contextlib import suppress
from dataclasses import dataclass, is_dataclass
from typing import TYPE_CHECKING, Any, ClassVar, cast

from citry.citry import Citry, citry
from citry.citry_element import CitryElement
from citry.component_render import gen_render_id
from citry.provide import MISSING, inject_value, make_provided, validate_provide_key
from citry.slots import Slot, normalize_slot_fills
from citry.util.misc import to_dict

if TYPE_CHECKING:
    from citry.citry_render import OnRenderGenerator, RenderReplacement
    from citry.component_render import _CompiledTemplate


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
            return super().__new__(mcs, name, bases, attrs)

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

        cls = cast("type[Component]", super().__new__(mcs, name, bases, attrs))

        # Resolve the Citry instance: an explicit ``citry`` field on the class,
        # or the inherited default (the base ``Component.citry``). Always set.
        citry_instance = cls.citry

        # Fire the class-created hook and let extensions rebuild their nested
        # config classes as subclasses of their Config base (e.g. ``class View:``
        # -> a subclass of the view extension's Config), before registration.
        # Extensions are present at
        # class-definition time, so no deferral is needed (docs/design/extensions.md).
        extensions = citry_instance.extensions
        extensions.on_component_class_created(cls)
        extensions._init_component_class(cls)

        # Register with the Citry instance. Uses the class name (or
        # Component.name override) as the registration name; Citry.register()
        # handles normalization and duplicate detection and fires
        # ``on_component_registered``.
        citry_instance.register(cls)

        return cls

    def __call__(cls, /, **kwargs: Any) -> CitryElement:
        """
        Intercept ``MyComp(title="Hi")`` to return a CitryElement.

        ``cls`` is positional-only (``/``) so a component may take a keyword
        argument named ``cls`` (for example an HTML ``class`` passed as
        ``MyComp(cls="card")``) without colliding with the metaclass's own
        first parameter.

        ``slots`` is a reserved input name: it is taken out of the kwargs and
        carried separately as the component's slot fills
        (``MyComp(title="Hi", slots={"header": ...})``), so a component cannot
        take a regular kwarg named ``slots``. See docs/design/slots.md
        section 9.

        In citry, calling a Component class is the **composition** phase.
        It creates a CitryElement that describes what to render, without
        rendering it yet. Actual Component instances are created later
        during the **rendering** phase via ``_create_instance()``.

        This is analogous to React's ``<MyComp title="Hi" />`` producing
        a RenderElement, not a rendered DOM node.
        """
        slots = kwargs.pop("slots", None)
        return CitryElement(cls, kwargs, slots)  # type: ignore[arg-type]

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
        if citry_instance is None:
            return

        # __del__ runs at GC / interpreter shutdown, where the Citry instance or
        # its extension manager may already be torn down. Suppress only the
        # *access* to the manager, so genuine errors raised inside the hook still
        # surface rather than being silently swallowed.
        extensions = None
        with suppress(Exception):
            extensions = citry_instance.extensions
        if extensions is not None:
            extensions.on_component_class_deleted(cls)  # type: ignore[arg-type]

        # The class may never have been registered, or the registry may be torn
        # down at shutdown; unregistering is best-effort here.
        with suppress(Exception):
            citry_instance.unregister(cls)  # type: ignore[arg-type]


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

    citry: ClassVar[Citry] = citry
    """The Citry instance this component is registered with.

    Defaults to the module-level default instance. Set this to assign the
    component to a specific Citry instance instead.
    """

    transparent: ClassVar[bool] = False
    """Whether this component's output joins the surrounding component's
    serialization frame.

    A transparent component is structural rather than visual: its rendered
    output gets no ``data-cid-<id>`` marker and is not framed as a child
    component at serialize time. Used by built-ins like ``<c-provide>`` that
    only wrap content. Hooks, the render id, and dependency merging behave
    the same as for any component.
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

    _template_body_generator: ClassVar[_CompiledTemplate | None] = None
    """Internal: the compiled form of this component's template (the
    body-generating function plus parse-time metadata), built once per class
    on first render and cached here (the Citry analog of Django's
    ``Component._template``). Calling its ``generate`` yields a fresh node
    list. Populated and read via ``__dict__`` by the render pipeline; not a
    user-facing field.
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
    """The resolved slot fills, with every value normalized to a ``Slot``.

    If the component defines a ``Slots`` dataclass, this is an instance
    of that class. Otherwise, a plain dict.
    """

    raw_slots: dict[str, Slot]
    """The slot fills as a plain dict of ``Slot`` values, even if a ``Slots``
    dataclass is defined. Useful when you need dict access regardless
    of typing.
    """

    parent: Component | None
    """The parent component instance, or None if this is a root component."""

    root: Component
    """The root component of the current render tree.

    For root components, ``self.root is self``. Never None.
    """

    _provides_inherited: dict[str, Any]
    """Internal: the provide/inject entries this instance inherited from the
    render path above it (captured where its tag sits). Read by ``inject``.
    """

    _provides_own: dict[str, Any]
    """Internal: the entries this instance registered via ``provide``, passed
    on to its descendants (never visible to its own ``inject``).
    """

    def __init__(
        self,
        # The public field is `component.id`, so the parameter shadows the builtin on purpose.
        id: str | None = None,  # noqa: A002
        kwargs: Any = None,
        slots: Any = None,
        parent: Component | None = None,
        provides: dict[str, Any] | None = None,
    ) -> None:
        self.id = id if id is not None else gen_render_id()

        cls = type(self)

        # Normalize inputs to plain dicts. kwargs/slots may arrive as a dict,
        # a NamedTuple, or a dataclass (e.g. a typed `Kwargs`/`Slots`
        # instance), so run them through `to_dict`. The outer `dict(...)`
        # copies, so mutations during one render never leak back into a
        # CitryElement that may be rendered again.
        raw_kwargs: dict[str, Any] = dict(to_dict(kwargs)) if kwargs is not None else {}
        # Slot inputs (strings, functions, elements, renders, Slot instances)
        # additionally normalize to `Slot` values; `normalize_slot_fills`
        # builds a fresh dict, so the copy is preserved.
        raw_slots: dict[str, Slot] = (
            normalize_slot_fills(to_dict(slots), component_name=cls.__name__) if slots is not None else {}
        )

        # Set typed kwargs/slots if the component defines a dataclass,
        # otherwise keep as plain dict.
        self.kwargs = cls.Kwargs(**raw_kwargs) if cls.Kwargs is not None else raw_kwargs
        self.slots = cls.Slots(**raw_slots) if cls.Slots is not None else raw_slots

        # raw_ variants are always plain dicts
        self.raw_kwargs = raw_kwargs
        self.raw_slots = raw_slots

        self.parent = parent
        self.root = parent.root if parent is not None else self

        # The inherited mapping is shared, not copied: a component that
        # provides builds a new mapping instead of changing an existing one,
        # so sharing is safe.
        self._provides_inherited = provides if provides is not None else {}
        self._provides_own = {}

    # The base implementation ignores its arguments (it returns None); they are
    # the documented signature for subclasses to override, hence the noqa's.
    def template_data(
        self,
        kwargs: Any,  # noqa: ARG002
        slots: Any | None = None,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """
        Return the template variables.

        Override this to map component inputs to template variables.
        The returned dict is what the template's expressions see.

        Args:
            kwargs: The keyword arguments passed to the component.
            slots: The slot fills passed to the component.

        Returns:
            A dict of template variables, or None for no variables.

        """
        return None

    def on_render(self) -> RenderReplacement | OnRenderGenerator | None:
        """
        Hook to replace or post-process this component's rendered output.

        Called on every render of this component, after ``template_data`` and
        just before the template renders. Return ``None`` (the default) to
        render the template as usual. Return content to use it as the
        component's whole output instead; the template is then not rendered
        at all. Accepted content (see docs/design/on_render.md section 3):

        - a ``str``, used as-is (NOT autoescaped: it is this component's own
          output, the same trust as its template)
        - a composed element (``OtherComponent(title="hi")``), rendered in
          this component's place
        - an already-rendered ``CitryRender``, inlined
        - a ``Slot``, invoked with no data

        Because ``None`` means "no replacement", return ``""`` to output
        literally nothing.

        Everything the hook needs is on ``self``: ``kwargs``, ``slots``,
        ``parent``, ``inject()``. To pass data to the template, use
        ``template_data``; this hook is for replacing output.

        For example, render a placeholder instead of the template when there
        is no data::

            class MyTable(Component):
                template = "<table>...</table>"

                def on_render(self):
                    if not self.raw_kwargs.get("rows"):
                        return "<p>No data</p>"
                    return None

        **Generator form.** Include a ``yield`` to also see the component's
        finished output, children included, and react to it - for example to
        catch a failing child (this is how error boundaries work)::

            class Guarded(Component):
                template = "..."

                def on_render(self):
                    # BEFORE: runs just before the template renders.
                    result, error = yield

                    # AFTER: result is the completed CitryRender, or None
                    # if rendering failed (then error is the exception).
                    if error is not None:
                        return "<p>Something went wrong</p>"
                    return None

        The protocol (full detail in docs/design/on_render.md section 3.2):

        - A bare ``yield`` (or ``yield None``) on the first yield means
          "render my template as usual"; yielding content means "use this as
          my output instead" (same accepted values as above).
        - The yield receives ``(result, error)`` once that output has fully
          settled: ``result`` is the live ``CitryRender`` (not a string; do
          not serialize it here unless you are replacing the output with the
          serialized form), or ``None`` when rendering failed, with ``error``
          set. Exactly one of the two is set.
        - You can yield any number of times; each ``yield <content>``
          replaces the output, renders it, and receives the new
          ``(result, error)``. A bare ``yield`` after the first answers
          immediately with the current result unchanged.
        - End with ``return <content>`` to set the final output, ``raise`` to
          make that the component's error, or plain ``return`` to keep the
          current result (an unhandled error keeps bubbling).
        """
        return None

    def provide(self, key: str, /, **data: Any) -> None:
        """
        Make ``data`` available to this component's descendants.

        Any component rendered below this one (including components inside
        slot content rendered below it) can read the data with
        ``self.inject(key)``. The data does NOT enter the template variables;
        descendants opt in explicitly. See docs/design/provide.md.

        Call this from ``template_data``. The data is frozen into an
        immutable payload at this point, so what descendants inject always
        has exactly the fields given here, as attributes::

            class Page(Component):
                template = '<c-user-card />'

                def template_data(self, kwargs, slots=None):
                    self.provide("user_data", user=kwargs["user"])
                    return {}

            class UserCard(Component):
                template = '<div>{{ name }}</div>'

                def template_data(self, kwargs, slots=None):
                    return {"name": self.inject("user_data").user}

        In templates, the same thing is written with the ``<c-provide>``
        built-in component: ``<c-provide key="user_data" c-user="user">``.

        Args:
            key: Name the data is provided under (a non-empty identifier).
                Positional-only, so a data field named ``key`` is allowed.
            **data: The provided fields.

        """
        validate_provide_key(key)
        self._provides_own[key] = make_provided(data)

    def inject(self, key: str, default: Any = MISSING) -> Any:
        """
        Read data a component above this one provided under ``key``.

        The data must have been provided by a component on the render path
        above this one (via ``Component.provide`` or the ``<c-provide>``
        built-in); the nearest provider wins when the same key is provided
        twice. A component's own ``provide`` calls are visible to its
        descendants only, never to its own ``inject``.

        The returned payload is immutable, with the provided fields as
        attributes: ``self.inject("user_data").user``. Works during
        ``template_data`` and keeps working after the render for as long as
        the component instance is kept.

        Args:
            key: The name the data was provided under.
            default: Returned when nothing was provided under ``key``. An
                explicit ``None`` works. Without a default, a missing key
                raises ``KeyError``.

        """
        return inject_value(self._provides_inherited, key, default, type(self).__name__)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"
