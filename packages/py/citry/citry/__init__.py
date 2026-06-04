# citry - Framework-agnostic component engine for HTML templating
#
# This package provides the rendering runtime for Citry templates:
# component lifecycle, slots, rendering pipeline, and the node classes
# that the V3 compiler output instantiates.
#
# For the Rust-powered parser and compiler, see citry_core.

from citry.citry import Citry, citry
from citry.component import Component

__all__ = [
    "Citry",
    "Component",
    "citry",
]
