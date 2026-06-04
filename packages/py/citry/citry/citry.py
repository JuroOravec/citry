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

if TYPE_CHECKING:
    from citry.component import Component


class Citry:
    """
    Global instance that scopes all component state.

    A Citry instance owns:
    - A registry of component classes
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
        self._components: set[type[Component]] = set()

    def _register_component(self, comp_cls: type[Component]) -> None:
        """
        Register a component class with this Citry instance.

        Called automatically by ComponentMeta at class definition time.
        """
        self._components.add(comp_cls)

    def _unregister_component(self, comp_cls: type[Component]) -> None:
        """Remove a component class from this instance's registry."""
        self._components.discard(comp_cls)

    @property
    def components(self) -> frozenset[type[Component]]:
        """The set of component classes registered with this instance."""
        return frozenset(self._components)

    def clear(self) -> None:
        """Clear all state: registered components, caches, etc."""
        self._components.clear()

    def __repr__(self) -> str:
        return f"Citry(components={len(self._components)})"


# The default Citry instance, used when Component.citry is not set.
# Created eagerly at import time. If Citry.__init__ grows dependencies
# that import from this package, switch to __getattr__-based laziness.
citry = Citry()
