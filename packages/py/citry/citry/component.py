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

            def template_data(self, kwargs, slots):
                return {"name": kwargs.get("name", "World")}

        # Composition - returns a CitryElement
        element = Greeting(name="World")

        # Rendering - produces a CitryRender; serialize() (or str()) -> HTML
        html = element.render().serialize()

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

            def template_data(self, kwargs, slots):
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
from hashlib import md5
from typing import TYPE_CHECKING, Any, ClassVar, cast

from citry.assets import load_css, load_js, load_template, validate_asset_pairs
from citry.assets import reset_files as _reset_files_impl
from citry.assets import reset_template as _reset_template_impl
from citry.citry import Citry, citry
from citry.citry_element import CitryElement
from citry.extensions.dependencies import get_dependencies as _get_dependencies_impl
from citry.provide import MISSING, inject_value, make_provided, validate_provide_key
from citry.slots import Slot, normalize_slot_fills
from citry.util.id import gen_render_id
from citry.util.misc import get_import_path, to_dict

if TYPE_CHECKING:
    from collections.abc import Iterator

    from citry.citry_render import OnRenderGenerator, RenderReplacement
    from citry.citry_template import CitryTemplate
    from citry.extensions.dependencies import CitryDependencies, Dependency


class ComponentMeta(type):
    """
    Metaclass for Component classes.

    At class definition time, this metaclass:
    1. Reads the ``citry`` field (or uses the default Citry instance).
    2. Registers the component class with its Citry instance.
    3. Converts inner data classes (Kwargs, Slots, etc.) without explicit
       bases to dataclasses (with slots) for ergonomic input typing.
    """

    # Per-class cache for the class_id property (stored on each component
    # class's own __dict__, never inherited).
    _class_id: str

    @property
    def class_id(cls) -> str:
        """
        A stable, URL-safe identifier for this component class, e.g.
        ``"Table_a1b2c3"``: the class name plus a short hash of its full
        import path.

        Deterministic across processes and restarts (it is derived from the
        import path, not from object identity), so it can key cache entries
        and script URLs that one worker writes and another serves. Reverse
        lookup goes through ``Citry.get_component_by_class_id``.
        """
        cached: str | None = cls.__dict__.get("_class_id")
        if cached is None:
            digest = md5(get_import_path(cls).encode(), usedforsecurity=False).hexdigest()[:6]
            cached = f"{cls.__name__}_{digest}"
            cls._class_id = cached
        return cached

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

        # Setting both members of an asset pair (e.g. `template` and
        # `template_file`) on the same class is an error; fail at class
        # definition. See docs/design/asset_loading.md section 3.2.
        validate_asset_pairs(name, attrs)

        # Convert inner data classes (Kwargs, Slots, and the data-method
        # schemas) to dataclasses if they don't explicitly declare a base
        # class or the @dataclass decorator. This lets users write:
        #     class Kwargs:
        #         title: str
        #         size: int = 10
        # and get a dataclass with slots automatically.
        for data_class_name in ("Kwargs", "Slots", "TemplateData", "JsData", "CssData"):
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
        take a regular kwarg named ``slots``.

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
    - A **template** (Citry template syntax)
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
    """Inline template string (Citry template syntax).

    Mutually exclusive with ``template_file``. Read the loaded template with
    ``get_template()``.
    """

    template_file: ClassVar[str | None] = None
    """Path to a template file. Mutually exclusive with ``template``.

    Resolved relative to the directory of this component's ``.py`` file first,
    then relative to each entry of ``Citry(dirs=...)``; absolute paths are used
    as-is.
    """

    js: ClassVar[str | None] = None
    """Inline primary JS for this component. Mutually exclusive with
    ``js_file``. Read the loaded content with ``get_js()``."""

    js_file: ClassVar[str | None] = None
    """Path to the component's primary JS file. Mutually exclusive with
    ``js``. Resolved like ``template_file``."""

    css: ClassVar[str | None] = None
    """Inline primary CSS for this component. Mutually exclusive with
    ``css_file``. Read the loaded content with ``get_css()``."""

    css_file: ClassVar[str | None] = None
    """Path to the component's primary CSS file. Mutually exclusive with
    ``css``. Resolved like ``template_file``."""

    # NOTE: Secondary assets are declared in a nested ``Dependencies`` class,
    # which belongs to the built-in `dependencies` extension (the extension
    # manager rebuilds it into the extension's per-component config). There is
    # deliberately no `Dependencies` ClassVar here; read the merged result
    # with ``get_dependencies()``. See docs/design/asset_loading.md section 7.

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

    JsData: ClassVar[type | None] = None
    """Optional typed schema for the ``js_data()`` output. Like
    ``TemplateData``, a plain annotated class converted to a dataclass."""

    CssData: ClassVar[type | None] = None
    """Optional typed schema for the ``css_data()`` output. Like
    ``TemplateData``, a plain annotated class converted to a dataclass."""

    _citry_template: ClassVar[CitryTemplate | None] = None
    """Internal: this component's loaded template (the ``CitryTemplate``,
    which also carries the compiled form once first rendered), resolved once
    per class and cached here (the Citry analog of Django's
    ``Component._template``). Populated and read via ``__dict__`` by the
    asset loader and the render pipeline; read it through ``get_template()``,
    not directly.
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
    """The component that wrote this one into its template. None for a root
    component, and for one rendered standalone (e.g. an element handed into
    an expression as ``{{ element }}``).

    The link follows authorship, not slot placement: a component written
    inside a ``<c-fill>`` keeps the fill's author as its parent, no matter
    whose slot the content lands in. (This differs from Vue, whose
    ``$parent`` points at the slot host.) To ask "what am I rendered
    inside, slots included", use ``provide``/``inject``, which travels the
    render path and crosses slot boundaries.
    """

    root: Component
    """The component at the top of the ``parent`` chain (the same
    authorship rule as ``parent``).

    For root components, ``self.root is self``. Never None.
    """

    _provides_inherited: dict[str, Any]
    """Internal: the provide/inject entries this instance inherited from the
    render path above it (captured where its tag sits). Read by ``inject``.
    """

    _provides_own: dict[str, Any] | None
    """Internal: the entries this instance registered via ``provide`` (``None``
    until the first ``provide`` call), passed
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
        cls = type(self)

        # Render id precedence: an explicit id wins; then this instance's
        # id_generator override (CitrySettings.id_generator); then the built-in
        # generator. The built-in stays a module-level call so a test can swap
        # it for every instance at once by patching gen_render_id.
        if id is not None:
            self.id = id
        elif cls.citry.id_generator is not None:
            self.id = cls.citry.id_generator()
        else:
            self.id = gen_render_id()

        # Normalize inputs to plain dicts. kwargs/slots may arrive as a dict,
        # a NamedTuple, or a dataclass (e.g. a typed `Kwargs`/`Slots`
        # instance), so run them through `to_dict`. The outer `dict(...)`
        # copies, so mutations during one render never leak back into a
        # CitryElement that may be rendered again.
        raw_kwargs: dict[str, Any] = dict(to_dict(kwargs)) if kwargs is not None else {}
        # Slot inputs (strings, functions, elements, renders, Slot instances)
        # additionally normalize to `Slot` values; `normalize_slot_fills`
        # builds a fresh dict, so the copy is preserved.
        # `element.slots` is `slots or {}`, so the common no-slots case is a falsy
        # empty dict, not None. A truthiness check skips the `normalize_slot_fills`
        # call (which would just rebuild an empty dict) for that case.
        raw_slots: dict[str, Slot] = (
            normalize_slot_fills(to_dict(slots), component_name=cls.__name__) if slots else {}
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
        # Allocated lazily by `provide()`; most components never provide. Readers
        # guard with truthiness, so `None` reads the same as an empty dict.
        self._provides_own = None

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

    def js_data(
        self,
        kwargs: Any,  # noqa: ARG002
        slots: Any | None = None,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """
        Return the JS variables for this render.

        Override this to expose per-render data to the component's JS
        (``Component.js``). The dict is serialized to JSON and delivered to
        the component's ``$onComponent`` callback in the browser; identical
        data is sent to the browser only once, however many instances share
        it. Consumed by the built-in ``dependencies`` extension.

        Args:
            kwargs: The keyword arguments passed to the component.
            slots: The slot fills passed to the component.

        Returns:
            A dict of JS variables, or None for no variables.

        """
        return None

    def css_data(
        self,
        kwargs: Any,  # noqa: ARG002
        slots: Any | None = None,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """
        Return the CSS variables for this render.

        Override this to expose per-render values to the component's CSS
        (``Component.css``) as CSS custom properties: a returned
        ``{"row-color": "red"}`` is usable in the CSS as
        ``var(--row-color)``, scoped to this component's elements. Identical
        data across renders shares one generated stylesheet. Consumed by the
        built-in ``dependencies`` extension.

        Args:
            kwargs: The keyword arguments passed to the component.
            slots: The slot fills passed to the component.

        Returns:
            A dict of CSS variables, or None for no variables.

        """
        return None

    # The base implementation ignores its arguments; they are the documented
    # signature for subclasses to override, hence the noqa's.
    @classmethod
    def on_dependencies(
        cls,
        scripts: list[Dependency],  # noqa: ARG003
        styles: list[Dependency],  # noqa: ARG003
    ) -> tuple[list[Dependency], list[Dependency]] | None:
        """
        Hook to adjust this component's JS/CSS tags before they enter the page.

        Called at serialize time, once per rendered instance of this
        component, with the ``Script``/``Style`` entries this component
        contributes (its ``Dependencies`` entries and its own
        ``Component.js``/``css``). Return a ``(scripts, styles)`` pair to
        replace the lists, mutate them in place, or return ``None`` (the
        default) to keep them. Removing the component's own script entries
        can break the component's behavior in the browser; this hook is for
        adding attributes, reordering, or dropping entries you know are
        provided elsewhere.

        To adjust the *page-wide* lists instead (every component's tags,
        after de-duplication), implement an extension with an
        ``on_dependencies`` method (see
        ``citry.extensions.dependencies.OnDependenciesContext``).
        """
        return None

    def on_render(self) -> RenderReplacement | OnRenderGenerator | None:
        """
        Hook to replace or post-process this component's rendered output.

        Called on every render of this component, after ``template_data`` and
        just before the template renders. Return ``None`` (the default) to
        render the template as usual. Return content to use it as the
        component's whole output instead; the template is then not rendered
        at all. Accepted content:

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

        The protocol:

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
        descendants opt in explicitly.

        Call this from ``template_data``. The data is frozen into an
        immutable payload at this point, so what descendants inject always
        has exactly the fields given here, as attributes::

            class Page(Component):
                template = '<c-user-card />'

                def template_data(self, kwargs, slots):
                    self.provide("user_data", user=kwargs["user"])
                    return {}

            class UserCard(Component):
                template = '<div>{{ name }}</div>'

                def template_data(self, kwargs, slots):
                    return {"name": self.inject("user_data").user}

        In templates, the same thing is written with the ``<c-provide>``
        built-in component: ``<c-provide key="user_data" c-user="user">``.

        Args:
            key: Name the data is provided under (a non-empty identifier).
                Positional-only, so a data field named ``key`` is allowed.
            **data: The provided fields.

        """
        validate_provide_key(key)
        if self._provides_own is None:
            self._provides_own = {}
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

    @property
    def ancestors(self) -> Iterator[Component]:
        """
        All ancestor components, nearest first: the parent, then the parent's
        parent, up to and including the root. Empty for a root component.

        Useful to check where a component sits, e.g.::

            is_themed = any(isinstance(c, Theme) for c in self.ancestors)

        The chain follows who *wrote* the component, the same as ``parent``:
        a component written inside a ``<c-fill>`` has the fill's author as
        its parent, not the component whose slot rendered it. So the check
        above holds when ``Theme``'s own template renders this component;
        for "am I rendered inside a Theme, slots included", have ``Theme``
        ``provide`` a value and ``inject`` it here, which travels the render
        path and crosses slot boundaries.
        """
        current = self.parent
        while current is not None:
            yield current
            current = current.parent

    # ----- Asset accessors -----
    # Thin delegates into citry/assets.py and the built-in `dependencies`
    # extension. The class fields (template, js_file, ...) stay exactly as
    # declared; these classmethods return the resolved/loaded values, cached
    # once per class. They are accessors, not override points: supplying a
    # template dynamically by overriding get_template() is unsupported.
    # See docs/design/asset_loading.md section 3.1.

    @classmethod
    def get_template(cls) -> CitryTemplate | None:
        """
        The loaded template (a ``CitryTemplate``), or ``None`` for a
        template-less component. Resolved from ``template`` /
        ``template_file`` once per class; ``on_template_loaded`` applied.
        """
        return load_template(cls)

    @classmethod
    def get_js(cls) -> str | None:
        """
        The loaded primary JS content, or ``None``. Resolved from ``js`` /
        ``js_file`` once per class; ``on_js_loaded`` applied.
        """
        return load_js(cls)

    @classmethod
    def get_css(cls) -> str | None:
        """
        The loaded primary CSS content, or ``None``. Resolved from ``css`` /
        ``css_file`` once per class; ``on_css_loaded`` applied.
        """
        return load_css(cls)

    @classmethod
    def get_dependencies(cls) -> CitryDependencies:
        """
        The merged secondary assets from this component's (and, per
        ``Dependencies.extend``, its bases') nested ``Dependencies`` class.
        Owned by the built-in ``dependencies`` extension.
        """
        return _get_dependencies_impl(cls)

    @classmethod
    def reset_template(cls) -> None:
        """
        Clear this class's loaded template (and its compiled form and cached
        ``Const`` optimization results), so the next render re-reads it.
        Subclasses that inherit this template cache their own copies; reset
        them too (``Citry.get_components_for_file`` lists every class using
        a given file).
        """
        _reset_template_impl(cls)

    @classmethod
    def reset_files(cls) -> None:
        """
        Clear this class's loaded JS/CSS (and, via the ``on_files_reset``
        hook, extension state such as the merged ``Dependencies``), so the
        next access re-reads them.
        """
        _reset_files_impl(cls)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"
