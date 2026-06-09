"""
The Citry global instance - scopes all component state.

A Citry instance owns a component registry, settings, and transient
rendering state. All Component classes are assigned to a Citry instance
(either explicitly via ``Component.citry = my_citry`` or implicitly to
the default instance).

Example:
    Using the default instance (most common)::

        from citry import Component

        class MyTable(Component):
            template = "<table>...</table>"

    Using a custom instance::

        from citry import Citry, Component

        my_citry = Citry()

        class MyTable(Component):
            citry = my_citry
            template = "<table>...</table>"

    Isolated instances for testing::

        def test_my_component():
            test_citry = Citry()
            # Components registered here don't leak to other tests
            class MyTable(Component):
                citry = test_citry
                template = "..."

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from citry.component_registry import ComponentRegistry
from citry.extension import ExtensionManager
from citry.settings import CitrySettings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from citry.component import Component
    from citry.extension import Extension


class Citry:
    """
    Global instance that scopes all component state.

    A Citry instance owns:
    - A ``registry`` (``ComponentRegistry``) mapping names to classes
    - Settings (to be expanded as the engine grows)
    - Transient rendering state

    All Component classes are assigned to a Citry instance at class
    definition time. If no instance is specified, the default instance
    is used.

    Benefits over module-level globals:
    - All transient state has a maximum lifetime bound to the Citry
      instance. Deleting the instance cleans up everything.
    - Tests can use isolated instances for clean state.
    - Multiple independent component trees can coexist.
    """

    def __init__(
        self,
        extensions: Sequence[type[Extension] | Extension | str] = (),
        extensions_defaults: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.settings = CitrySettings(
            extensions=tuple(extensions),
            extensions_defaults=dict(extensions_defaults) if extensions_defaults is not None else {},
        )
        self.registry = ComponentRegistry()
        # Const-keyed body cache: (component class, const signature) -> body.
        # Skeleton for the const-folding feature (docs/design/constness.md);
        # the body is not yet specialized per signature.
        self._const_body_cache: dict[tuple[type[Component], frozenset[tuple[str, Any]]], list[Any]] = {}

        # The extension/hook system, scoped to this Citry instance (DJC #1413).
        # Extensions are present from construction, so hooks fire immediately.
        self.extensions = ExtensionManager(self, self.settings.extensions)
        self.extensions.on_extension_created()

    def __repr__(self) -> str:
        return f"Citry(components={len(self.registry)})"

    # Convenience delegations so users can write citry.get("card")
    # instead of citry.registry.get("card").

    def register(self, comp_cls: type[Component], name: str | None = None) -> None:
        """
        Register a component. See ``ComponentRegistry.register``.

        Fires ``on_component_registered`` once per call, after the registry
        accepts the class.
        """
        self.registry.register(comp_cls, name)
        registered_name = name or getattr(comp_cls, "name", None) or comp_cls.__name__
        self.extensions.on_component_registered(registered_name, comp_cls)

    def unregister(self, comp_cls_or_name: type[Component] | str) -> None:
        """
        Unregister a component. See ``ComponentRegistry.unregister``.

        Fires ``on_component_unregistered`` once per call, after the registry
        removes the class.
        """
        # Resolve the class (and a representative name) before removal, so the
        # hook context is populated whether called by class or by name.
        if isinstance(comp_cls_or_name, str):
            comp_cls = self.registry.get(comp_cls_or_name)
            removed_name = comp_cls_or_name
        else:
            comp_cls = comp_cls_or_name
            removed_name = getattr(comp_cls, "name", None) or comp_cls.__name__
        self.registry.unregister(comp_cls_or_name)
        self.extensions.on_component_unregistered(removed_name, comp_cls)

    def get(self, name: str) -> type[Component]:
        """Look up a component by name. See ``ComponentRegistry.get``."""
        return self.registry.get(name)

    def has(self, name: str) -> bool:
        """Check if a component is registered. See ``ComponentRegistry.has``."""
        return self.registry.has(name)

    @property
    def components(self) -> dict[str, type[Component]]:
        """All registered components as a name -> class mapping."""
        return self.registry.all()

    def _const_body(
        self,
        comp_cls: type[Component],
        signature: frozenset[tuple[str, Any]],
        build: Callable[[], list[Any]],
    ) -> list[Any]:
        """
        Return the cached body for ``(comp_cls, signature)``, building it once.

        Skeleton: the body is the unoptimized node list, equivalent across
        signatures for now (no folding). See ``docs/design/constness.md``.
        """
        key = (comp_cls, signature)
        cached = self._const_body_cache.get(key)
        if cached is None:
            cached = build()
            self._const_body_cache[key] = cached
        return cached

    def clear(self) -> None:
        """Clear all state: registered components, caches, etc."""
        self.registry.clear()
        self._const_body_cache.clear()


# The default Citry instance, used when Component.citry is not set.
# Created eagerly at import time. If Citry.__init__ grows dependencies
# that import from this package, switch to __getattr__-based laziness.
citry = Citry()
