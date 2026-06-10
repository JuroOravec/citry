"""
The extension (plugin) system.

Extensions let third-party code (and citry's own subsystems, such as the future
JS/CSS dependency handling) hook into the component lifecycle without touching
the core. An extension is a subclass of :class:`Extension` that implements one or
more ``on_*`` hook methods and, optionally, exposes a per-component nested config
class (the ``Component.View`` / ``Component.Cache`` mechanism) and CLI commands.

Extensions are scoped to a :class:`~citry.citry.Citry` instance (per DJC #1413,
all engine state lives on the ``Citry`` instance). Pass them at construction::

    from citry import Citry, Component, Extension

    class TimingExtension(Extension):
        name = "timing"

        def on_component_rendered(self, ctx):
            print(f"{type(ctx.component).__name__} rendered")

    app = Citry(extensions=[TimingExtension])

The full design, the hook catalog, and the divergences from django-components
are in ``docs/design/extensions.md``. This module is the phase-1 skeleton: it
wires the lifecycle, registration, render, and template hooks. The short-circuit
/ caching, dependency, slot, and CSS/JS hooks are deferred to later phases.
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
    from citry.citry_render import CitryRender, RenderPart
    from citry.component import Component
    from citry.nodes import BodyItem, SlotNode
    from citry.slots import Slot


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
    template_data: dict[str, Any]
    """The template variables from ``Component.template_data()`` (mutable)."""


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


################################################
# COMMANDS
################################################


class ExtensionCommand:
    """
    Base class for an extension's CLI command.

    A stub for now: an extension lists command classes in ``Extension.commands``,
    and the manager can look one up by name. There is no command *runner* yet;
    that arrives with the CLI/tooling work. URL routing (DJC's ``Extension.urls``)
    is not carried over (see docs/design/extensions.md section 11).
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
    Storybook extension). See docs/design/extensions.md section 5.1.
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
    extension actually overrides). The full hook catalog is in
    docs/design/extensions.md.
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


################################################
# EXTENSION MANAGER
################################################

_Result = Literal["none", "map", "first"]


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
    later phases use for extension-owned custom hooks.
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
        instances: list[Extension] = []
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
        # Name -> instance map for O(1) ``get_extension``. A duplicate name
        # collapses here, but ``_validate_names`` scans the full tuple and raises
        # on duplicates, so an ambiguous map can never be used.
        self._extensions_by_name = {inst.name: inst for inst in instances}
        # Make extensions list immutable
        return tuple(instances)

    def _validate_names(self) -> None:
        if not self._extensions:
            # No extensions to validate. Importantly, skip the Component import so
            # the default ``citry = Citry()`` (built while citry.py is still
            # importing, before component.py exists) does not hit an import cycle.
            return
        from citry.component import Component  # noqa: PLC0415

        seen: set[str] = set()
        for extension in self._extensions:
            if hasattr(Component, extension.name) or hasattr(Component, extension.class_name):
                msg = f"Extension name {extension.name!r} conflicts with existing Component API"
                raise ValueError(msg)
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
        others to implement (docs/design/extensions.md section 9).

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
        self.emit(
            "on_component_input",
            OnComponentInputContext(
                citry=self.citry,
                component=component,
                kwargs=component.raw_kwargs,
                slots=component.raw_slots,
            ),
        )

    def on_component_data(self, component: Component, template_data: dict[str, Any]) -> None:
        self.emit(
            "on_component_data",
            OnComponentDataContext(citry=self.citry, component=component, template_data=template_data),
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
