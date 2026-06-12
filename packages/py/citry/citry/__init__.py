# citry - Framework-agnostic component engine for HTML templating
#
# This package provides the rendering runtime for Citry templates:
# component lifecycle, slots, rendering pipeline, and the node classes
# that the V3 compiler output instantiates.
#
# For the Rust-powered parser and compiler, see citry_core.
#
# API stability: the names exported HERE (listed in __all__) are the public
# API, and only these are promised not to break between releases. Submodules
# (citry.slots, citry.nodes, ...) may be imported from, but their contents
# are internal and free to change between releases.

from citry.attrs import (
    format_attrs,
    merge_attrs,
    normalize_class,
    normalize_style,
    parse_string_style,
)
from citry.citry import (
    Citry,
    citry,
)
from citry.citry_context import CitryContext
from citry.citry_element import CitryElement
from citry.citry_render import CitryRender, OnRenderGenerator, RenderReplacement
from citry.component import Component
from citry.component_registry import AlreadyRegistered, ComponentRegistry, NotRegistered
from citry.constness import Const
from citry.extension import (
    Extension,
    ExtensionCommand,
    ExtensionConfig,
    ExtensionManager,
    OnAttrsResolvedContext,
    OnComponentClassCreatedContext,
    OnComponentClassDeletedContext,
    OnComponentDataContext,
    OnComponentInputContext,
    OnComponentRegisteredContext,
    OnComponentRenderedContext,
    OnComponentUnregisteredContext,
    OnExtensionCreatedContext,
    OnSlotRenderedContext,
    OnTemplateCompiledContext,
    OnTemplateLoadedContext,
)
from citry.nodes import (
    ComponentNode,
    ElementAttrsNode,
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
from citry.slots import (
    Slot,
    SlotContext,
    SlotFunc,
    SlotInput,
    SlotResult,
)

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
    "ElementAttrsNode",
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
    "OnAttrsResolvedContext",
    "OnComponentClassCreatedContext",
    "OnComponentClassDeletedContext",
    "OnComponentDataContext",
    "OnComponentInputContext",
    "OnComponentRegisteredContext",
    "OnComponentRenderedContext",
    "OnComponentUnregisteredContext",
    "OnExtensionCreatedContext",
    "OnRenderGenerator",
    "OnSlotRenderedContext",
    "OnTemplateCompiledContext",
    "OnTemplateLoadedContext",
    "RenderReplacement",
    "Slot",
    "SlotContext",
    "SlotFunc",
    "SlotInput",
    "SlotNode",
    "SlotResult",
    "StaticHtmlAttr",
    "TemplateHtmlAttr",
    "TemplateNode",
    "citry",
    "format_attrs",
    "merge_attrs",
    "normalize_class",
    "normalize_style",
    "parse_string_style",
]
