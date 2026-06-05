# citry - Framework-agnostic component engine for HTML templating
#
# This package provides the rendering runtime for Citry templates:
# component lifecycle, slots, rendering pipeline, and the node classes
# that the V3 compiler output instantiates.
#
# For the Rust-powered parser and compiler, see citry_core.

from citry.citry import Citry
from citry.citry import citry  # noqa: PLW0127
from citry.component import Component
from citry.component_registry import AlreadyRegistered, ComponentRegistry, NotRegistered
from citry.render_object import RenderObject

__all__ = [
    "AlreadyRegistered",
    "Citry",
    "Component",
    "ComponentRegistry",
    "NotRegistered",
    "RenderObject",
    "citry",
]
