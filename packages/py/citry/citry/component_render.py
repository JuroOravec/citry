"""
Component render pipeline.

This module contains the core rendering logic. When a CitryElement is
rendered (via ``.render()``), it calls ``render_impl`` which:

1. Creates a real Component instance (via ``_create_instance``), which
   normalizes inputs and sets instance state (id, kwargs, slots, parent, root)
2. Calls ``template_data()`` and validates it against ``TemplateData``
3. Builds the template body (a node list) and renders it

The expensive step, the body-generating function (parse + compile + exec of
the template), is built once per **component class** and cached on the class,
since it is invariant for a given template. Calling it yields a fresh node
list each render. (Per-element/per-signature body caching belongs to the
parked const-folding design; see docs/design/constness.md.)

This is a skeleton. Many features from django-components are not yet
ported (extensions/hooks, context snapshotting, deferred rendering,
JS/CSS media, provide/inject). They will be added iteratively.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from citry.constants import COMP_ID_PREFIX, UID_LENGTH
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
from citry.util.misc import to_dict
from citry.util.nanoid import generate
from citry_core.template_parser import compile_template, parse_template

if TYPE_CHECKING:
    from collections.abc import Callable

    from citry.citry_element import CitryElement
    from citry.component import Component


_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gen_id() -> str:
    """Generate a unique alphanumeric ID (6 chars, ~1 in 3.3M collision chance)."""
    return generate(_ID_ALPHABET, size=UID_LENGTH)


def gen_render_id() -> str:
    """Generate a unique render ID for a component instance (e.g. ``c1A2b3c``)."""
    return COMP_ID_PREFIX + gen_id()


def render_impl(
    element: CitryElement,
    parent: Component | None = None,
) -> str:
    """
    Core render implementation.

    This is the internal entry point called by ``CitryElement.render()``.
    It creates a real Component instance, calls the data methods, builds (or
    reuses) the template body, and renders it.

    Args:
        element: The CitryElement to render. Carries the component class,
            kwargs, slots, and the cached body (node list).
        parent: The parent Component instance if rendering inside another
            component's template. Used to set parent/root references.

    Returns:
        The rendered HTML string.

    """
    comp_cls = element.comp_cls

    # 1. Create component instance with all state.
    #    Uses _create_instance() which bypasses ComponentMeta.__call__
    #    (that returns a CitryElement) and calls Component.__init__.
    #    __init__ handles input normalization (dict/NamedTuple/dataclass ->
    #    dict, copied), id generation, typed kwargs/slots, raw_ variants,
    #    and parent/root references.
    component = comp_cls._create_instance(
        kwargs=element.kwargs,
        slots=element.slots,
        parent=parent,
    )

    # 2. Call template_data() (per-render; intentionally not cached).
    #    The return value may be a dict, a NamedTuple, or the component's
    #    typed `TemplateData` dataclass, so normalize it with `to_dict`.
    #    No defensive copy is needed (unlike kwargs/slots): the data is
    #    produced fresh by user code on every render, not shared state.
    maybe_data = component.template_data(component.kwargs, component.slots)
    tpl_data: dict[str, Any] = to_dict(maybe_data) if maybe_data is not None else {}

    #    If the component declares a TemplateData schema, validate the data
    #    against it. Constructing TemplateData(**data) raises on missing or
    #    unexpected fields. Skip when template_data() already returned a
    #    TemplateData instance, since it was validated on construction.
    template_data_cls = comp_cls.TemplateData
    if template_data_cls is not None and not isinstance(maybe_data, template_data_cls):
        template_data_cls(**tpl_data)

    # 3. Build the body (node list) and render it. The body-generating
    #    function is parsed+compiled+exec'd once per component class (cached on
    #    the class); calling it yields a fresh node list each render. Reusing
    #    an already-optimized body across renders is the job of the parked
    #    const-folding cache (docs/design/constness.md), not implemented here.
    generator = _get_body_generator(comp_cls)
    if generator is None:
        return ""
    body = generator()

    return _render_body(body, tpl_data)


# TODO - WRONG! Whether the template is inlined or in file,
#        we should convert it to "Template" - NOT a string.
def _get_template_string(comp_cls: type[Component]) -> str | None:
    """
    Resolve the component's template to a string.

    For now, supports only ``Component.template`` (inline string).
    ``Component.template_file`` (loading from disk) will be added later,
    along with template caching at the class level (per DJC #1326).
    """
    if comp_cls.template is not None:
        return comp_cls.template

    if comp_cls.template_file is not None:
        # TODO: Load template from file. For now, raise a clear error.
        raise NotImplementedError(
            f"Component {comp_cls.__name__} uses template_file={comp_cls.template_file!r}, "
            f"but file-based templates are not yet implemented."
        )

    return None


def _get_body_generator(comp_cls: type[Component]) -> Callable[[], list[Any]] | None:
    """
    Return the cached body-generating function for a component's template.

    The template is parsed, compiled, and exec'd once per component class; the
    resulting ``generate_template`` function is cached on the class. Each call
    to it produces a fresh node list (one per render). Returns ``None`` when the
    component has no template.

    The cache is read and written via the class's own ``__dict__`` (not via
    attribute access), so it is keyed to the specific class: a subclass that
    overrides ``template`` builds its own generator instead of inheriting the
    parent's. (Accessing it as an attribute would also bind it as a method,
    since it holds a plain function.)
    """
    if "_template_body_generator" not in comp_cls.__dict__:
        template_str = _get_template_string(comp_cls)
        comp_cls._template_body_generator = _compile_body_generator(template_str) if template_str is not None else None
    return comp_cls.__dict__["_template_body_generator"]


def _compile_body_generator(template_str: str) -> Callable[[], list[Any]]:
    """
    Parse, compile, and exec a template string into a body-generating function.

    Uses the citry_core pipeline: parse -> compile -> exec. Returns the
    ``generate_template`` function from the exec'd namespace; calling it
    returns a fresh list of static strings and runtime node objects.

    The compiled code references node classes (ExprNode, ComponentNode, etc.).
    For now these are stubs that store their arguments but raise
    NotImplementedError on render; they will be replaced with real
    implementations as the rendering pipeline matures.
    """
    ast = parse_template(template_str)
    code = compile_template(ast)

    # Build the namespace for exec. "source" is the original template string,
    # passed to nodes for error reporting and diagnostics. This namespace
    # becomes the returned function's globals, so the node classes and source
    # stay bound to it.
    ns: dict[str, Any] = {
        "source": template_str,
        "ExprNode": ExprNode,
        "TemplateNode": TemplateNode,
        "ComponentNode": ComponentNode,
        "IfNode": IfNode,
        "ForNode": ForNode,
        "SlotNode": SlotNode,
        "FillNode": FillNode,
        "StaticHtmlAttr": StaticHtmlAttr,
        "ExprHtmlAttr": ExprHtmlAttr,
        "TemplateHtmlAttr": TemplateHtmlAttr,
    }
    exec(code, ns)  # noqa: S102
    return ns["generate_template"]


def _render_body(body: list[Any], context: dict[str, Any]) -> str:
    """
    Render a body (list of static strings and node objects) to an HTML string.

    Strings are static text and pass through unchanged. Node objects are
    rendered with the per-render ``context``. (Nodes are currently stubs that
    raise NotImplementedError on render, so for now they are repr'd.)
    """
    parts: list[str] = []
    for item in body:
        if isinstance(item, str):
            parts.append(item)
        else:
            # TODO: Call item.render(context) once nodes are implemented.
            # For now, node objects are stubs, so we repr them.
            parts.append(repr(item))

    return "".join(parts)
