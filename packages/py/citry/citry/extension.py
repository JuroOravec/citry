"""
The extension (plugin) system.

Extensions let third-party code (and citry's own subsystems, such as the
built-in JS/CSS dependency handling) hook into the component lifecycle without
touching the core. An extension is a subclass of :class:`Extension` that
implements one or more ``on_*`` hook methods and, optionally, exposes a
per-component nested config class (the ``Component.View`` / ``Component.Cache``
mechanism), HTTP routes (``Extension.urls``), and CLI commands.

Extensions are scoped to a :class:`~citry.citry.Citry` instance (per DJC #1413,
all engine state lives on the ``Citry`` instance). Pass them at construction::

    from citry import Citry, Component, Extension

    class TimingExtension(Extension):
        name = "timing"

        def on_component_rendered(self, ctx):
            print(f"{type(ctx.component).__name__} rendered")

    app = Citry(extensions=[TimingExtension])

The full design, the hook catalog, and the divergences from django-components
are in ``docs/design/extensions.md``. It wires the lifecycle, registration,
render, template, slot, JS/CSS, merge (``on_render_context_merge``), and
serialize hooks, plus the ``emit`` mechanism for extension-owned custom hooks
(the dependencies extension's ``on_dependencies``). The short-circuit /
caching hooks (a future cache extension) are the main piece still deferred.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from importlib import import_module
from typing import TYPE_CHECKING, Any, ClassVar, Literal
from weakref import ReferenceType, ref

from citry.util.misc import snake_to_pascal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from citry.citry import Citry
    from citry.citry_context import CitryContext
    from citry.citry_render import CitryRender, RenderPart
    from citry.component import Component
    from citry.nodes import BodyItem, SlotNode
    from citry.slots import Slot
    from citry.util.routing import URLRoute


################################################
# HOOK CONTEXTS
#
# Frozen dataclasses, consistent with citry's metaclass (which
# converts inner Kwargs/Slots to dataclasses); threaded across extensions with
# ``dataclasses.replace``. The surface is minimal: contexts carry ``citry`` plus,
# when a component instance exists, ``component``. Fields trivially derivable
# from those (component class, component id, registry) are not duplicated.
# See docs/design/extensions.md section 3.
################################################


@dataclass(frozen=True, slots=True)
class OnExtensionCreatedContext:
    citry: Citry
    """The ``Citry`` instance the extension belongs to."""
    extension: Extension
    """The created extension instance."""


@dataclass(frozen=True, slots=True)
class OnComponentClassCreatedContext:
    citry: Citry
    """The ``Citry`` instance the component class belongs to."""
    component_class: type[Component]
    """The created Component class."""


@dataclass(frozen=True, slots=True)
class OnComponentClassDeletedContext:
    citry: Citry
    """The ``Citry`` instance the component class belongs to."""
    component_class: type[Component]
    """The to-be-deleted Component class."""


@dataclass(frozen=True, slots=True)
class OnComponentRegisteredContext:
    citry: Citry
    """The ``Citry`` instance the component was registered with."""
    name: str
    """The name the component was registered under."""
    component_class: type[Component]
    """The registered Component class."""


@dataclass(frozen=True, slots=True)
class OnComponentUnregisteredContext:
    citry: Citry
    """The ``Citry`` instance the component was unregistered from."""
    name: str
    """The name the component was registered under."""
    component_class: type[Component]
    """The unregistered Component class."""


@dataclass(frozen=True, slots=True)
class OnComponentInputContext:
    citry: Citry
    """The ``Citry`` instance the component belongs to."""
    component: Component
    """The Component instance being rendered."""
    kwargs: dict[str, Any]
    """The keyword arguments passed to the component (mutable plain dict)."""
    slots: dict[str, Any]
    """The slot fills passed to the component (mutable plain dict)."""


@dataclass(frozen=True, slots=True)
class OnComponentDataContext:
    citry: Citry
    """The ``Citry`` instance the component belongs to."""
    component: Component
    """The Component instance being rendered."""
    context: CitryContext
    """The render-scoped ``CitryContext`` for this component's render.
    Extensions stash tree-wide state in ``context.extra`` (for example the
    dependencies extension's render records); it bubbles up through
    ``on_render_context_merge`` as nested renders are consumed. ``context.provides``
    is not yet populated when this hook fires."""
    template_data: dict[str, Any]
    """The template variables from ``Component.template_data()`` (mutable)."""
    js_data: dict[str, Any]
    """The JS variables from ``Component.js_data()`` (mutable). Consumed by
    the built-in ``dependencies`` extension."""
    css_data: dict[str, Any]
    """The CSS variables from ``Component.css_data()`` (mutable). Consumed by
    the built-in ``dependencies`` extension."""


@dataclass(frozen=True, slots=True)
class OnComponentRenderedContext:
    citry: Citry
    """The ``Citry`` instance the component belongs to."""
    component: Component
    """The Component instance that was rendered."""
    render: CitryRender | str | None
    """The rendered output, or ``None`` if rendering failed."""
    error: Exception | None
    """The error raised during rendering, or ``None`` if it succeeded."""


@dataclass(frozen=True, slots=True)
class OnSlotRenderedContext:
    citry: Citry
    """The ``Citry`` instance the component belongs to."""
    component: Component
    """The component whose template holds the ``<c-slot>`` that was rendered."""
    slot: Slot
    """The Slot that was rendered: the fill, or the fallback when no fill was given."""
    slot_name: str
    """The resolved slot name (``"default"`` for an unnamed slot)."""
    slot_node: SlotNode
    """The runtime ``SlotNode`` at whose site the slot rendered."""
    slot_is_required: bool
    """Whether the slot resolved as required."""
    result: RenderPart
    """The rendered output (a ``str`` or a ``CitryRender``)."""


@dataclass(frozen=True, slots=True)
class OnAttrsResolvedContext:
    citry: Citry
    """The ``Citry`` instance the component belongs to."""
    component: Component
    """The component whose template holds the element."""
    tag_name: str
    """The HTML tag the attributes belong to (e.g. ``"div"``)."""
    attrs: dict[str, Any]
    """The resolved attribute dict: ``class``/``style`` already normalized to
    strings, booleans still ``True``, omitted attributes already absent."""


@dataclass(frozen=True, slots=True)
class OnTemplateLoadedContext:
    citry: Citry
    """The ``Citry`` instance the component class belongs to."""
    component_class: type[Component]
    """The Component class whose template was loaded."""
    content: str
    """The template string (before parsing)."""


@dataclass(frozen=True, slots=True)
class OnTemplateCompiledContext:
    citry: Citry
    """The ``Citry`` instance the component class belongs to."""
    component_class: type[Component]
    """The Component class whose template was compiled."""
    nodes: list[BodyItem]
    """The generated body node list."""


@dataclass(frozen=True, slots=True)
class OnJsLoadedContext:
    citry: Citry
    """The ``Citry`` instance the component class belongs to."""
    component_class: type[Component]
    """The Component class whose JS was loaded."""
    content: str
    """The JS content (inline or read from ``js_file``)."""


@dataclass(frozen=True, slots=True)
class OnCssLoadedContext:
    citry: Citry
    """The ``Citry`` instance the component class belongs to."""
    component_class: type[Component]
    """The Component class whose CSS was loaded."""
    content: str
    """The CSS content (inline or read from ``css_file``)."""


@dataclass(frozen=True, slots=True)
class OnFilesResetContext:
    citry: Citry
    """The ``Citry`` instance the component class belongs to."""
    component_class: type[Component]
    """The Component class whose loaded asset files were reset."""


@dataclass(frozen=True, slots=True)
class OnRenderContextMergeContext:
    citry: Citry
    """The ``Citry`` instance the render belongs to."""
    parent_context: CitryContext
    """The context of the render that consumed the nested one."""
    child_context: CitryContext
    """The context of the consumed nested render."""


@dataclass(frozen=True, slots=True)
class OnSerializeContext:
    citry: Citry
    """The ``Citry`` instance the render belongs to."""
    context: CitryContext
    """The root render's ``CitryContext`` (its ``extra`` carries everything
    that bubbled up during the render)."""
    html: str
    """The joined HTML (threaded: return a new string to replace it)."""
    placeholders: dict[str, str]
    """The placeholder parts found during serialization: unique placeholder id
    (the ``Placeholder.key`` plus a counter, e.g. ``"deps:js:1"``) to the exact
    text standing in for it in ``html``."""
    deps_strategy: str
    """The ``serialize(deps_strategy=...)`` argument."""
    deps_position: str
    """The ``serialize(deps_position=...)`` argument."""


################################################
# COMMANDS
################################################


class ExtensionCommand:
    """
    Base class for an extension's CLI command.

    A stub for now: an extension lists command classes in ``Extension.commands``,
    and the manager can look one up by name. There is no command *runner* yet;
    that arrives with the CLI/tooling work. (Extension HTTP routes are a
    separate surface, ``Extension.urls``.)
    """

    name: ClassVar[str]
    """The command name (``citry ext run <extension> <name>``)."""

    help: ClassVar[str] = ""
    """One-line description of the command."""

    def handle(self, *args: Any, **kwargs: Any) -> None:
        """Run the command. Override in a subclass."""


################################################
# PER-COMPONENT CONFIG
################################################


class ExtensionConfig:
    """
    Base for the per-component nested config class (reached as ``Extension.Config``).

    An extension named ``"view"`` (``class_name == "View"``) lets a user define a
    nested ``class View:`` on a component. The manager rebuilds that nested class
    as a subclass of this base (binding ``component_class``), then instantiates it
    per render and attaches it as ``component.view``.

    The component back-reference is a weakref, and the component may be ``None``
    for extensions that run outside a component lifecycle (for example a future
    Storybook extension).
    """

    component_class: ClassVar[type[Component]]
    """The Component class this config is defined on (bound by the manager)."""

    def __init__(self, component: Component | None) -> None:
        # Weak ref to avoid a component <-> config reference cycle. ``None`` when
        # the extension runs outside a component lifecycle.
        self._component_ref: ReferenceType[Component] | None = ref(component) if component is not None else None

    @property
    def component(self) -> Component:
        """
        The owning Component instance.

        Raises ``RuntimeError`` if this config runs outside a component lifecycle
        (no component), or if the component has been garbage-collected.
        """
        if self._component_ref is None:
            msg = f"{type(self).__name__} runs outside a component lifecycle (no component)"
            raise RuntimeError(msg)
        component = self._component_ref()
        if component is None:
            msg = "Component has been garbage collected"
            raise RuntimeError(msg)
        return component


################################################
# EXTENSION BASE
################################################


class Extension:
    """
    Base class for all extensions.

    Subclass this, set ``name`` (a lowercase Python identifier), and implement the
    ``on_*`` hooks you care about. Every hook has an empty default, so an
    extension only overrides what it needs (the manager calls only the hooks an
    extension actually overrides). The ``on_*`` methods below are the full hook
    catalog.
    """

    name: ClassVar[str]
    """Name of the extension. Lowercase, a valid Python identifier. Determines
    the attribute the per-component config is reachable under
    (``component.<name>``) and, via :attr:`class_name`, the nested class name."""

    class_name: ClassVar[str]
    """PascalCase name of the per-component nested config class, derived from
    :attr:`name` at subclass creation (``my_extension`` -> ``MyExtension``)."""

    Config: ClassVar[type[ExtensionConfig]] = ExtensionConfig
    """Base class the per-component nested config inherits from."""

    commands: ClassVar[list[type[ExtensionCommand]]] = []
    """CLI commands this extension provides (see :class:`ExtensionCommand`)."""

    citry: Citry
    """The ``Citry`` instance this extension instance belongs to. Set by the
    manager when the extension is attached (extensions are per-instance, so
    the back-reference is unambiguous)."""

    @property
    def urls(self) -> list[URLRoute]:
        """
        HTTP routes this extension provides (see ``citry/util/routing.py``).

        Mounted by the web-integration adapters as part of ``Citry.urls``: a
        user extension's routes live under ``ext/<extension name>/``;
        built-in extensions own their paths directly. Override as an
        attribute or property; handlers can reach engine state through
        ``self.citry``.
        """
        return []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "name", None):
            msg = f"Extension {cls.__name__} must define a 'name'"
            raise ValueError(msg)
        if not cls.name.isidentifier():
            msg = f"Extension name must be a valid Python identifier, got {cls.name!r}"
            raise ValueError(msg)
        if not cls.name.islower():
            msg = f"Extension name must be lowercase, got {cls.name!r}"
            raise ValueError(msg)
        if not getattr(cls, "class_name", None):
            cls.class_name = snake_to_pascal(cls.name)

    # ----- Extension lifecycle -----

    def on_extension_created(self, ctx: OnExtensionCreatedContext) -> None:
        """Called once when this extension instance is created."""

    # ----- Component class lifecycle -----

    def on_component_class_created(self, ctx: OnComponentClassCreatedContext) -> None:
        """Called after a Component class is defined, before it is registered."""

    def on_component_class_deleted(self, ctx: OnComponentClassDeletedContext) -> None:
        """Called before a Component class is garbage-collected."""

    def on_component_registered(self, ctx: OnComponentRegisteredContext) -> None:
        """Called after a Component class is registered."""

    def on_component_unregistered(self, ctx: OnComponentUnregisteredContext) -> None:
        """Called after a Component class is unregistered."""

    # ----- Component render -----

    def on_component_input(self, ctx: OnComponentInputContext) -> None:
        """
        Called when a component starts rendering, before ``template_data``.

        Inspect or mutate ``ctx.kwargs`` / ``ctx.slots`` in place.
        """

    def on_component_data(self, ctx: OnComponentDataContext) -> None:
        """
        Called after ``template_data``; mutate ``ctx.template_data`` to add or
        change template variables.
        """

    def on_component_rendered(self, ctx: OnComponentRenderedContext) -> CitryRender | str | None:
        """
        Called after a component (and its children) rendered. Return a new
        ``CitryRender`` / ``str`` to replace the output, raise to replace the
        error, or return ``None`` to keep the original.
        """

    def on_slot_rendered(self, ctx: OnSlotRenderedContext) -> RenderPart | None:
        """
        Called after a ``<c-slot>`` site rendered (a fill, or the fallback).

        Return a new render part (``str`` or ``CitryRender``) to replace the
        output, or ``None`` to keep the original. Raising propagates.
        """

    def on_attrs_resolved(self, ctx: OnAttrsResolvedContext) -> dict[str, Any] | None:
        """
        Called after an HTML element's dynamic attributes resolved to their
        final dict, before it is formatted into the output. Return a new dict
        to replace the attributes, or ``None`` to keep them.

        Fires per element per render, only for elements with at least one
        dynamic attribute (a ``c-*`` value or a ``c-bind`` spread).
        """

    def on_render_context_merge(self, ctx: OnRenderContextMergeContext) -> None:
        """
        Called when a nested render's output is consumed by an enclosing
        render (a child component settling into its parent, or an
        already-rendered value embedded via an expression or slot).

        Merge your extension's slice of ``ctx.child_context.extra`` into
        ``ctx.parent_context.extra``, with your own policy (the dependencies
        extension, for example, appends records preserving order). The core
        does not merge anything itself.
        """

    def on_serialize(self, ctx: OnSerializeContext) -> str | None:
        """
        Called at the end of ``CitryRender.serialize()`` with the joined HTML.

        Return a new string to replace the output (threaded across
        extensions), or ``None`` to keep it. This is where serialize-time
        work that needs the whole page happens; the dependencies extension
        places the collected JS/CSS here, using ``ctx.placeholders`` for the
        ``<c-js>``/``<c-css>`` positions.
        """

    # ----- Template -----

    def on_template_loaded(self, ctx: OnTemplateLoadedContext) -> str | None:
        """
        Called once per class with the template string before it is parsed.
        Return a new string to modify it.
        """

    def on_template_compiled(self, ctx: OnTemplateCompiledContext) -> list[BodyItem] | None:
        """
        Called once per compiled body, with the generated node list. Mutate it
        in place or return a new list.
        """

    # ----- JS / CSS -----

    def on_js_loaded(self, ctx: OnJsLoadedContext) -> str | None:
        """
        Called once per class with the component's primary JS content (inline
        or read from ``js_file``). Return a new string to modify it.
        """

    def on_css_loaded(self, ctx: OnCssLoadedContext) -> str | None:
        """
        Called once per class with the component's primary CSS content (inline
        or read from ``css_file``). Return a new string to modify it.
        """


################################################
# EXTENSION MANAGER
################################################

_Result = Literal["none", "map", "first"]


def _builtin_extensions() -> tuple[type[Extension], ...]:
    """
    The built-in extensions every ``Citry`` instance carries.

    Prepended to the user's extension spec by ``ExtensionManager._build``, so
    their names are effectively reserved (a user extension reusing one fails
    the duplicate-name validation). Built-ins cannot be disabled or replaced
    (docs/design/asset_loading.md section 7.2).
    """
    # Imported here, not at module load: the built-in extension modules
    # subclass Extension from this module, so a top-level import would be
    # circular.
    from citry.extensions.dependencies import DependenciesExtension  # noqa: PLC0415

    return (DependenciesExtension,)


class ExtensionManager:
    """
    Fans each lifecycle hook out across a ``Citry`` instance's extensions.

    Owned by :class:`~citry.citry.Citry` and built once in its ``__init__``.
    Unlike DJC's module-level singleton, there is no deferred-event machinery: a
    component class is bound to its ``Citry`` (and thus these extensions) at
    definition time, so the extensions are always present when a hook fires.

    Dispatch is *smart*: for each hook name, only the extensions that actually
    override that hook are called (an extension that does not implement a hook
    costs nothing). The same name-keyed dispatch underlies :meth:`emit`, which
    extensions use for their own custom hooks (e.g. ``on_dependencies``).
    """

    def __init__(
        self,
        citry: Citry,
        extensions: Sequence[type[Extension] | Extension | str] = (),
    ) -> None:
        self.citry = citry
        # Name -> instance map, populated by ``_build`` for O(1) ``get_extension``.
        self._extensions_by_name: dict[str, Extension] = {}
        self._extensions: tuple[Extension, ...] = self._build(extensions)
        self._hook_extensions_cache: dict[str, tuple[Extension, ...]] = {}
        self._validate_names()

    def _build(
        self,
        extensions: Sequence[type[Extension] | Extension | str],
    ) -> tuple[Extension, ...]:
        instances: list[Extension] = [builtin() for builtin in _builtin_extensions()]
        for extension in extensions:
            resolved: type[Extension] | Extension
            # Case: Import path like `my_package.my_module.MyExtension`.
            if isinstance(extension, str):
                module_path, class_name = extension.rsplit(".", 1)
                resolved = getattr(import_module(module_path), class_name)
            # Case: class object or instance.
            else:
                resolved = extension
            instances.append(resolved() if isinstance(resolved, type) else resolved)
        # Attach the Citry back-reference (extensions are per-instance, so
        # each instance belongs to exactly one Citry).
        for instance in instances:
            instance.citry = self.citry
        # Name -> instance map for O(1) ``get_extension``. A duplicate name
        # collapses here, but ``_validate_names`` scans the full tuple and raises
        # on duplicates, so an ambiguous map can never be used.
        self._extensions_by_name = {inst.name: inst for inst in instances}
        # Make extensions list immutable
        return tuple(instances)

    def _validate_names(self) -> None:
        # The Component-API conflict check needs the Component class, which is
        # not importable while the default ``citry = Citry()`` is constructed
        # (citry.py is still mid-import and component.py imports it back). The
        # default instance carries only the built-in extensions, whose names
        # are known not to conflict, so skipping the API check there is safe;
        # any user-constructed Citry runs the full validation.
        try:
            from citry.component import Component  # noqa: PLC0415
        except ImportError:
            component: type | None = None
        else:
            component = Component

        seen: set[str] = set()
        for extension in self._extensions:
            if component is not None and (
                hasattr(component, extension.name) or hasattr(component, extension.class_name)
            ):
                msg = f"Extension name {extension.name!r} conflicts with existing Component API"
                raise ValueError(msg)
            # Built-in names are reserved: the built-ins come first in the
            # tuple, so a user extension reusing one fails here as a duplicate.
            if extension.name in seen:
                msg = f"Multiple extensions cannot share the name {extension.name!r}"
                raise ValueError(msg)
            seen.add(extension.name)

    def get_extension(self, name: str) -> Extension:
        extension = self._extensions_by_name.get(name)
        if extension is None:
            msg = f"Extension {name!r} not found"
            raise ValueError(msg)
        return extension

    def get_extension_command(self, name: str, command_name: str) -> type[ExtensionCommand]:
        for command in self.get_extension(name).commands:
            if command.name == command_name:
                return command
        msg = f"Command {command_name!r} not found in extension {name!r}"
        raise ValueError(msg)

    @property
    def urls(self) -> tuple[URLRoute, ...]:
        """
        The combined route table of every extension (read as ``Citry.urls``).

        Built-in extensions own their paths directly (e.g. the dependencies
        extension's ``cache/...`` and ``citry.js``); a user extension's
        routes are namespaced under ``ext/<extension name>/`` so they cannot
        collide with citry's own or each other's.
        """
        # Imported here, not at module load: routing is only needed when a
        # web integration asks for the table.
        from citry.util.routing import URLRoute  # noqa: PLC0415

        builtin_types = _builtin_extensions()
        routes: list[URLRoute] = []
        namespaced: list[URLRoute] = []
        for extension in self._extensions:
            extension_urls = tuple(extension.urls)
            if not extension_urls:
                continue
            if isinstance(extension, builtin_types):
                routes.extend(extension_urls)
            else:
                namespaced.append(URLRoute(f"ext/{extension.name}/", children=extension_urls))
        return (*routes, *namespaced)

    # ----- Smart dispatch -----

    def _extensions_with_hook(self, name: str) -> tuple[Extension, ...]:
        """
        Filter for extensions that implement a hook named ``name``. Cached per-name
        for efficiency since this is called on every hook emit.

        For a hook declared on :class:`Extension`, an extension defines it when
        its method differs from the base (i.e. it is overridden). For a custom
        hook not on the base (a future ``emit``-only hook), any extension that
        defines a method of that name qualifies.
        """
        # Remember which extensions define which hooks, so we don't have to
        # iterate all extensions on every hook call.
        cached = self._hook_extensions_cache.get(name)
        if cached is not None:
            return cached

        base_method = getattr(Extension, name, None)
        matching: list[Extension] = []
        for extension in self._extensions:
            method = getattr(type(extension), name, None)
            if not callable(method):
                continue
            if base_method is not None and method is base_method:
                continue  # inherited, not overridden
            matching.append(extension)
        result = tuple(matching)

        self._hook_extensions_cache[name] = result
        return result

    def emit(self, name: str, ctx: Any, result: _Result = "none", field: str | None = None) -> Any:
        """
        Dispatch hook ``name`` to the extensions that define it, combining the
        hooks' returned values per ``result``:

        - ``"none"``: call every extension, ignore returns; return ``None``.
        - ``"first"``: return the first non-``None`` return (short-circuit).
        - ``"map"``: thread ``ctx.<field>`` - each non-``None`` return replaces it
          (via ``dataclasses.replace``) and is passed to the next extension; the
          final field value is returned.

        An extension defines ``name`` by overriding it (see
        ``_extensions_with_hook``). ``name`` need not be a hook declared on
        :class:`Extension`, so an extension can fire its own custom hook for
        others to implement.

        Examples:
            Most named hooks delegate here. ``on_component_data`` notifies every
            extension that defines it (``"none"``)::

                manager.emit("on_component_data", ctx)

            ``on_template_loaded`` threads ``ctx.content`` through the extensions
            (``"map"``) and returns the final string::

                manager.emit("on_template_loaded", ctx, result="map", field="content")

            A custom hook can let an extension short-circuit (``"first"`` returns
            the first non-``None`` value)::

                manager.emit("on_my_event", ctx, result="first")

        """
        extensions = self._extensions_with_hook(name)
        if result == "none":
            for extension in extensions:
                getattr(extension, name)(ctx)
            return None
        if result == "first":
            for extension in extensions:
                out = getattr(extension, name)(ctx)
                if out is not None:
                    return out
            return None
        if result == "map":
            if field is None:
                msg = "emit(result='map') requires a field name"
                raise ValueError(msg)
            for extension in extensions:
                out = getattr(extension, name)(ctx)
                if out is not None:
                    ctx = replace(ctx, **{field: out})
            return getattr(ctx, field)
        msg = f"Unknown result policy {result!r}"
        raise ValueError(msg)

    # ----- Per-component config classes -----

    def _init_component_class(self, component_class: type[Component]) -> None:
        """
        Rebuild each extension's nested config class as a subclass of its ``Config`` base.

        For an extension named ``"view"`` (``class_name == "View"``): synthesize a
        new ``View`` whose bases are ``(user View, GlobalDefaults, ext.Config)`` -
        so attribute precedence is component-level > global defaults > factory -
        with ``component_class`` bound, and assign it back. If the component
        defines no nested class, the synthesized class is just ``ext.Config``.
        """
        defaults_all = self.citry.settings.extensions_defaults
        for extension in self._extensions:
            class_name = extension.class_name
            user_cls = getattr(component_class, class_name, None)

            bases: list[type] = [extension.Config]

            ext_defaults = defaults_all.get(extension.name)
            if ext_defaults:
                defaults_cls = type(f"{class_name}Defaults", (), dict(ext_defaults))
                bases.insert(0, defaults_cls)

            if isinstance(user_cls, type):
                bases.insert(0, user_cls)

            config_cls = type(class_name, tuple(bases), {"component_class": component_class})
            setattr(component_class, class_name, config_cls)

    def _init_component_instance(self, component: Component) -> None:
        """
        Instantiate each extension's config class with the component and attach
        it as ``component.<extension.name>``.
        """
        component_class = type(component)
        for extension in self._extensions:
            config_cls = getattr(component_class, extension.class_name, None)
            if not (isinstance(config_cls, type) and issubclass(config_cls, extension.Config)):
                # The class was defined before this extension's config was set up.
                # Should not happen in normal flow (the metaclass runs
                # _init_component_class), but recover defensively.
                self._init_component_class(component_class)
                config_cls = getattr(component_class, extension.class_name)
            setattr(component, extension.name, config_cls(component))

    # ----- Lifecycle hooks -----

    def on_extension_created(self) -> None:
        # Each extension receives a context naming itself, so this cannot go
        # through the shared-ctx ``emit``.
        for extension in self._extensions_with_hook("on_extension_created"):
            extension.on_extension_created(OnExtensionCreatedContext(citry=self.citry, extension=extension))

    def on_component_class_created(self, component_class: type[Component]) -> None:
        self.emit(
            "on_component_class_created",
            OnComponentClassCreatedContext(citry=self.citry, component_class=component_class),
        )

    def on_component_class_deleted(self, component_class: type[Component]) -> None:
        self.emit(
            "on_component_class_deleted",
            OnComponentClassDeletedContext(citry=self.citry, component_class=component_class),
        )

    def on_component_registered(self, name: str, component_class: type[Component]) -> None:
        self.emit(
            "on_component_registered",
            OnComponentRegisteredContext(citry=self.citry, name=name, component_class=component_class),
        )

    def on_component_unregistered(self, name: str, component_class: type[Component]) -> None:
        self.emit(
            "on_component_unregistered",
            OnComponentUnregisteredContext(citry=self.citry, name=name, component_class=component_class),
        )

    # ----- Render hooks -----

    def on_component_input(self, component: Component) -> None:
        # Skip building the context dataclass when no extension subscribes, the
        # same short-circuit the per-element/per-slot hooks use. This runs per
        # component, so the allocation is worth avoiding on the construction path.
        if not self.has_hook("on_component_input"):
            return
        self.emit(
            "on_component_input",
            OnComponentInputContext(
                citry=self.citry,
                component=component,
                kwargs=component.raw_kwargs,
                slots=component.raw_slots,
            ),
        )

    def on_component_data(
        self,
        component: Component,
        context: CitryContext,
        template_data: dict[str, Any],
        js_data: dict[str, Any],
        css_data: dict[str, Any],
    ) -> None:
        if not self.has_hook("on_component_data"):
            return
        self.emit(
            "on_component_data",
            OnComponentDataContext(
                citry=self.citry,
                component=component,
                context=context,
                template_data=template_data,
                js_data=js_data,
                css_data=css_data,
            ),
        )

    def on_render_context_merge(self, parent_context: CitryContext, child_context: CitryContext) -> None:
        self.emit(
            "on_render_context_merge",
            OnRenderContextMergeContext(citry=self.citry, parent_context=parent_context, child_context=child_context),
        )

    def on_serialize(
        self,
        context: CitryContext,
        html: str,
        placeholders: dict[str, str],
        deps_strategy: str,
        deps_position: str,
    ) -> str:
        return self.emit(
            "on_serialize",
            OnSerializeContext(
                citry=self.citry,
                context=context,
                html=html,
                placeholders=placeholders,
                deps_strategy=deps_strategy,
                deps_position=deps_position,
            ),
            result="map",
            field="html",
        )

    def on_component_rendered(
        self,
        component: Component,
        render: CitryRender | str | None,
        error: Exception | None,
    ) -> tuple[CitryRender | str | None, Exception | None]:
        """
        Thread the rendered output through the extensions; a return replaces the
        render, a raise replaces the error.
        """
        # Fires for every component; skip the context build when unsubscribed.
        if not self.has_hook("on_component_rendered"):
            return render, error
        ctx = OnComponentRenderedContext(citry=self.citry, component=component, render=render, error=error)
        for extension in self._extensions_with_hook("on_component_rendered"):
            try:
                out = extension.on_component_rendered(ctx)
            except Exception as err:  # noqa: BLE001
                ctx = replace(ctx, render=None, error=err)
            else:
                if out is not None:
                    ctx = replace(ctx, render=out, error=None)
        return ctx.render, ctx.error

    def on_slot_rendered(
        self,
        component: Component,
        slot: Slot,
        slot_name: str,
        slot_node: SlotNode,
        slot_is_required: bool,
        result: RenderPart,
    ) -> RenderPart:
        """
        Thread a slot's rendered output through the extensions; a return
        replaces the result, a raise propagates.
        """
        # Skip building the context when nothing subscribes: this fires for
        # every slot of every component, so the dataclass would otherwise be
        # built and thrown away on a hot path.
        if not self.has_hook("on_slot_rendered"):
            return result
        return self.emit(
            "on_slot_rendered",
            OnSlotRenderedContext(
                citry=self.citry,
                component=component,
                slot=slot,
                slot_name=slot_name,
                slot_node=slot_node,
                slot_is_required=slot_is_required,
                result=result,
            ),
            result="map",
            field="result",
        )

    def has_hook(self, name: str) -> bool:
        """Whether any installed extension implements the hook ``name``."""
        return bool(self._extensions_with_hook(name))

    def on_attrs_resolved(
        self,
        component: Component,
        tag_name: str,
        attrs: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Thread an element's resolved attribute dict through the extensions; a
        return replaces the dict, a raise propagates.

        This sits on a per-element per-render hot path, so when no extension
        implements the hook the dict is returned without building a context.
        """
        if not self._extensions_with_hook("on_attrs_resolved"):
            return attrs
        return self.emit(
            "on_attrs_resolved",
            OnAttrsResolvedContext(
                citry=self.citry,
                component=component,
                tag_name=tag_name,
                attrs=attrs,
            ),
            result="map",
            field="attrs",
        )

    # ----- Template hooks -----

    def on_template_loaded(self, component_class: type[Component], content: str) -> str:
        return self.emit(
            "on_template_loaded",
            OnTemplateLoadedContext(citry=self.citry, component_class=component_class, content=content),
            result="map",
            field="content",
        )

    def on_template_compiled(self, component_class: type[Component], nodes: list[BodyItem]) -> list[BodyItem]:
        return self.emit(
            "on_template_compiled",
            OnTemplateCompiledContext(citry=self.citry, component_class=component_class, nodes=nodes),
            result="map",
            field="nodes",
        )

    # ----- JS / CSS hooks -----

    def on_js_loaded(self, component_class: type[Component], content: str) -> str:
        return self.emit(
            "on_js_loaded",
            OnJsLoadedContext(citry=self.citry, component_class=component_class, content=content),
            result="map",
            field="content",
        )

    def on_css_loaded(self, component_class: type[Component], content: str) -> str:
        return self.emit(
            "on_css_loaded",
            OnCssLoadedContext(citry=self.citry, component_class=component_class, content=content),
            result="map",
            field="content",
        )

    def on_files_reset(self, component_class: type[Component]) -> None:
        """
        Notify extensions that a component class's loaded asset files were
        reset, so each drops its own per-class state (the ``dependencies``
        built-in drops its merged result here).

        Deliberately not declared on the :class:`Extension` base: this is the
        first consumer of the duck-typed custom-hook dispatch (an extension
        subscribes by defining a method named ``on_files_reset``).
        """
        self.emit(
            "on_files_reset",
            OnFilesResetContext(citry=self.citry, component_class=component_class),
        )
