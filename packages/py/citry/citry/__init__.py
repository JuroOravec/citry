# citry - Framework-agnostic component engine for HTML templating
#
# This package provides the rendering runtime for Citry templates:
# component lifecycle, slots, rendering pipeline, and the node classes
# that the V3 compiler output instantiates.
#
# For the Rust-powered parser and compiler, see citry_core.

from citry.citry import (
    Citry,
    citry,
)
from citry.citry_element import CitryElement
from citry.component import Component
from citry.component_registry import AlreadyRegistered, ComponentRegistry, NotRegistered
from citry.nodes import (
    ComponentNode,
    ExprHtmlAttr,
    ExprNode,
    FillNode,
    ForNode,
    IfNode,
    SlotNode,
    StaticHtmlAttr,
    TemplateHtmlAttr,
    TemplateNode,
)

__all__ = [
    "AlreadyRegistered",
    "Citry",
    "CitryElement",
    "Component",
    "ComponentNode",
    "ComponentRegistry",
    "ExprHtmlAttr",
    "ExprNode",
    "FillNode",
    "ForNode",
    "IfNode",
    "NotRegistered",
    "SlotNode",
    "StaticHtmlAttr",
    "TemplateHtmlAttr",
    "TemplateNode",
    "citry",
]
