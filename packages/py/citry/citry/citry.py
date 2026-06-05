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

if TYPE_CHECKING:
    from citry.component import Component


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

    def __init__(self, **settings: Any) -> None:
        # TODO - Add type once known
        self._settings = settings
        self.registry = ComponentRegistry()

    # Convenience delegations so users can write citry.get("card")
    # instead of citry.registry.get("card").

    def register(self, comp_cls: type[Component], name: str | None = None) -> None:
        """Register a component. See ``ComponentRegistry.register``."""
        self.registry.register(comp_cls, name)

    def unregister(self, comp_cls_or_name: type[Component] | str) -> None:
        """Unregister a component. See ``ComponentRegistry.unregister``."""
        self.registry.unregister(comp_cls_or_name)

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

    def clear(self) -> None:
        """Clear all state: registered components, caches, etc."""
        self.registry.clear()

    def __repr__(self) -> str:
        return f"Citry(components={len(self.registry)})"


# The default Citry instance, used when Component.citry is not set.
# Created eagerly at import time. If Citry.__init__ grows dependencies
# that import from this package, switch to __getattr__-based laziness.
citry = Citry()
