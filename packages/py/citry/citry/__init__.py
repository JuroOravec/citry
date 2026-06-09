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
from citry.citry_context import CitryContext
from citry.citry_element import CitryElement
from citry.citry_render import CitryRender
from citry.component import Component
from citry.component_registry import AlreadyRegistered, ComponentRegistry, NotRegistered
from citry.constness import Const
from citry.extension import (
    Extension,
    ExtensionCommand,
    ExtensionConfig,
    ExtensionManager,
    OnComponentClassCreatedContext,
    OnComponentClassDeletedContext,
    OnComponentDataContext,
    OnComponentInputContext,
    OnComponentRegisteredContext,
    OnComponentRenderedContext,
    OnComponentUnregisteredContext,
    OnExtensionCreatedContext,
    OnTemplateCompiledContext,
    OnTemplateLoadedContext,
)
from citry.nodes import (
    ComponentNode,
    ExprHtmlAttr,
    ExprNode,
    FillNode,
    ForNode,
    HtmlAttr,
    IfNode,
    Node,
    SlotNode,
    StaticHtmlAttr,
    TemplateHtmlAttr,
    TemplateNode,
)
from citry.settings import CitrySettings

__all__ = [
    "AlreadyRegistered",
    "Citry",
    "CitryContext",
    "CitryElement",
    "CitryRender",
    "CitrySettings",
    "Component",
    "ComponentNode",
    "ComponentRegistry",
    "Const",
    "ExprHtmlAttr",
    "ExprNode",
    "Extension",
    "ExtensionCommand",
    "ExtensionConfig",
    "ExtensionManager",
    "FillNode",
    "ForNode",
    "HtmlAttr",
    "IfNode",
    "Node",
    "NotRegistered",
    "OnComponentClassCreatedContext",
    "OnComponentClassDeletedContext",
    "OnComponentDataContext",
    "OnComponentInputContext",
    "OnComponentRegisteredContext",
    "OnComponentRenderedContext",
    "OnComponentUnregisteredContext",
    "OnExtensionCreatedContext",
    "OnTemplateCompiledContext",
    "OnTemplateLoadedContext",
    "SlotNode",
    "StaticHtmlAttr",
    "TemplateHtmlAttr",
    "TemplateNode",
    "citry",
]
