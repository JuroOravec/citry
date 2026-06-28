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
from citry.cache import CitryCache, InMemoryCache
from citry.citry import (
    Citry,
    citry,
)
from citry.citry_context import CitryContext
from citry.citry_element import CitryElement
from citry.citry_render import (
    CitryRender,
    DepsPosition,
    DepsStrategy,
    OnRenderGenerator,
    Placeholder,
    RenderReplacement,
)
from citry.citry_template import CitryTemplate
from citry.command import CommandArg, CommandArgGroup, CommandSubcommand
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
    OnCssLoadedContext,
    OnExtensionCreatedContext,
    OnFilesResetContext,
    OnJsLoadedContext,
    OnRenderContextMergeContext,
    OnSerializeContext,
    OnSlotRenderedContext,
    OnTemplateCompiledContext,
    OnTemplateLoadedContext,
)
from citry.extensions.dependencies import (
    CitryDependencies,
    Dependency,
    DependencyRecord,
    OnDependenciesContext,
    Script,
    Style,
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
from citry.util.routing import RouteResponse, URLRoute

__all__ = [
    "AlreadyRegistered",
    "Citry",
    "CitryCache",
    "CitryContext",
    "CitryDependencies",
    "CitryElement",
    "CitryRender",
    "CitrySettings",
    "CitryTemplate",
    "CommandArg",
    "CommandArgGroup",
    "CommandSubcommand",
    "Component",
    "ComponentNode",
    "ComponentRegistry",
    "Const",
    "Dependency",
    "DependencyRecord",
    "DepsPosition",
    "DepsStrategy",
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
    "InMemoryCache",
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
    "OnCssLoadedContext",
    "OnDependenciesContext",
    "OnExtensionCreatedContext",
    "OnFilesResetContext",
    "OnJsLoadedContext",
    "OnRenderContextMergeContext",
    "OnRenderGenerator",
    "OnSerializeContext",
    "OnSlotRenderedContext",
    "OnTemplateCompiledContext",
    "OnTemplateLoadedContext",
    "Placeholder",
    "RenderReplacement",
    "RouteResponse",
    "Script",
    "Slot",
    "SlotContext",
    "SlotFunc",
    "SlotInput",
    "SlotNode",
    "SlotResult",
    "StaticHtmlAttr",
    "Style",
    "TemplateHtmlAttr",
    "TemplateNode",
    "URLRoute",
    "citry",
    "format_attrs",
    "merge_attrs",
    "normalize_class",
    "normalize_style",
    "parse_string_style",
]
