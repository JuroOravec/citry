"""
Built-in components.

These are ordinary citry components that ship with the engine and back the
built-in tags the README promises: ``<c-provide>``, ``<c-component>``, and
``<c-element>`` (here), with ``<c-js>`` and ``<c-css>`` to follow. The parser
treats these tags as regular component tags on purpose (see
``crates/citry_template_parser/src/constants.rs``), so the whole behavior
lives in Python.

To ensure the user cannot overwrite them, ``ComponentRegistry`` uses
``BUILTIN_COMPONENT_NAMES`` to track the reserved names. And rejects
the registration of user components with those names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from citry.components.dynamic import make_dynamic_component, make_dynamic_element
from citry.components.provide import make_provide_component

if TYPE_CHECKING:
    from citry.citry import Citry


def make_builtin_components(citry_instance: Citry) -> None:
    """Create and register the built-in components for one Citry instance."""
    make_provide_component(citry_instance)
    make_dynamic_component(citry_instance)
    make_dynamic_element(citry_instance)
