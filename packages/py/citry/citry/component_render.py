"""
Component render pipeline.

This module contains the core rendering logic. When a CitryElement is
rendered (via ``.render()``), it calls ``render_impl`` which:

1. Creates a real Component instance (via ``_create_instance``), which
   normalizes inputs and sets instance state (id, kwargs, slots, parent, root)
2. Calls ``template_data()`` and validates it against ``TemplateData``
3. Builds a ``CitryContext`` (the render-scoped state) and the template body
   (a node list), walks the body into a parts list, and returns a
   ``CitryRender`` wrapping the parts plus the context

``render_impl`` returns a ``CitryRender`` (not a string). Serialization to HTML
happens later, via ``CitryRender.serialize()`` (or ``str()``). See
docs/design/rendering.md for the three-phase model.

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

from citry.citry_context import CitryContext
from citry.citry_render import CitryRender
from citry.constants import COMP_ID_PREFIX, UID_LENGTH
from citry.constness import const_value, is_const
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
    from citry.citry_render import RenderPart
    from citry.component import Component
    from citry.nodes import BodyItem


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
) -> CitryRender:
    """
    Core render implementation.

    This is the internal entry point called by ``CitryElement.render()``.
    It creates a real Component instance, calls the data methods, builds (or
    reuses) the template body, and walks it into a ``CitryRender``.

    Args:
        element: The CitryElement to render. Carries the component class,
            kwargs, slots, and the cached body (node list).
        parent: The parent Component instance if rendering inside another
            component's template. Used to set parent/root references.

    Returns:
        A ``CitryRender`` holding the rendered parts and the ``CitryContext``
        used during the render. Call ``.serialize()`` (or ``str()``) on it to
        get the HTML string.

    """
    comp_cls = element.comp_cls
    citry_instance = comp_cls.citry
    extensions = citry_instance.extensions

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

    # 2. Attach the per-component extension configs (eg `component.view`,
    #    AKA `component.<ext.name>`), then run on_component_input.
    #    NOTE: the typed component.kwargs / slots are already built in __init__,
    #    so input mutations land on raw_kwargs / raw_slots but do not yet propagate
    #    to the typed views; that propagation is deferred (docs/design/extensions.md section 7.1).
    extensions._init_component_instance(component)
    extensions.on_component_input(component)

    # 3. Call template_data() (per-render; intentionally not cached).
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

    # 4. on_component_data: extensions may add/modify template variables.
    extensions.on_component_data(component, tpl_data)

    # 5. Build the render-scoped context. ``variables`` are the template
    #    variables (the template_data output); ``extra`` is the tree-wide
    #    scratch space extensions will populate (deps, etc.) - empty for now.
    #    The Const markers stay in ``variables`` so they flow down to descendant
    #    components, each of which can detect const-ness and cache accordingly.
    #    Const is a transparent proxy, so nodes treat a const value exactly like
    #    the underlying value.
    context = CitryContext(variables=tpl_data, component=component)

    # 6. Build the body (node list). The body-generating function is
    #    parsed+compiled+exec'd once per component class (cached on the class).
    #    The body is then loaded from the Citry-scoped cache keyed by the
    #    component class plus the *const signature* (which context variables are
    #    marked Const, and to what values). The body is NOT yet specialized per
    #    signature (no folding), so every signature maps to an equivalent node
    #    list for now; this wires up the const flow so folding can slot in
    #    later. See docs/design/constness.md.
    #
    #    on_template_compiled fires here (per built body, before caching), so an
    #    extension can transform the node list once and have the transform
    #    cached. See docs/design/extensions.md section 7.4.
    generator = _get_body_generator(comp_cls)
    if generator is None:
        body: list[BodyItem] = []
    else:

        def build() -> list[BodyItem]:
            return extensions.on_template_compiled(comp_cls, generator())

        # If the template_data() returned any `Const` fields,
        # this is where we build/load the cached optimized body.
        signature = _const_signature(tpl_data)
        body = citry_instance._const_body(comp_cls, signature, build)

    # 7. Walk the body into a parts list and wrap it in a CitryRender.
    parts = _render_body(body, context)
    rendered = CitryRender(parts=parts, context=context)

    # 8. on_component_rendered: extensions may post-process the render (return a
    #    new CitryRender/str) or replace the result with an error (raise).
    new_render, error = extensions.on_component_rendered(component, rendered, None)
    if error is not None:
        raise error
    if isinstance(new_render, str):
        return CitryRender(parts=[new_render], context=context)
    if new_render is not None:
        return new_render
    return rendered


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
        raise NotImplementedError(
            f"Component {comp_cls.__name__} uses template_file={comp_cls.template_file!r}, "
            f"but file-based templates are not yet implemented."
        )

    return None


def _get_body_generator(comp_cls: type[Component]) -> Callable[[], list[BodyItem]] | None:
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

        # on_template_loaded fires once per class, since the generator is cached
        # on the class. This hook lets extensions modify the template string before parse.
        if template_str is not None:
            template_str = comp_cls.citry.extensions.on_template_loaded(comp_cls, template_str)

        comp_cls._template_body_generator = _compile_body_generator(template_str) if template_str is not None else None
    return comp_cls.__dict__["_template_body_generator"]


def _compile_body_generator(template_str: str) -> Callable[[], list[BodyItem]]:
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


def _render_body(body: list[BodyItem], context: CitryContext) -> list[RenderPart]:
    """
    Walk a body (list of static strings and node objects) into a parts list.

    Strings are static text and pass through unchanged. Node objects are
    rendered with the render-scoped ``context``; each contributes a ``str`` or a
    nested ``CitryRender`` to the parts.

    When a node returns a ``CitryRender`` produced by a *different* render (an
    embedded pre-rendered subtree, for example a value found in an expression),
    its collected metadata is merged into this render's context. A
    ``CitryRender`` carrying *this* context (for example a nested template, which
    shares the surrounding component's context) needs no merge.

    Returns a list of parts (``str`` or nested ``CitryRender``) for a
    ``CitryRender`` to hold, rather than a joined string: joining is deferred to
    ``CitryRender.serialize()`` so embedded subtrees stay composable.
    """
    parts: list[RenderPart] = []
    for item in body:
        if isinstance(item, str):
            parts.append(item)
            continue
        part = item.render(context)
        if isinstance(part, CitryRender) and part.context is not context:
            _merge_dependencies(context, part.context)
        parts.append(part)

    return parts


def _merge_dependencies(into: CitryContext, source: CitryContext) -> None:
    """
    Merge an embedded subtree's collected metadata into the consuming context.

    This is the seam for the JS/CSS dependency flow (docs/design/rendering.md
    section 6): a pre-rendered subtree's dependencies must bubble up into the
    tree that embeds it. No extension populates ``extra`` yet, so this is
    currently a structural no-op; the dependency extension will define the merge
    semantics (ordered de-duplication across the tree, not last-writer-wins).
    """
    into.extra.update(source.extra)


def _const_signature(context: dict[str, Any]) -> frozenset[tuple[str, Any]]:
    """
    Build a hashable signature of the const-marked context variables.

    Keys the const body cache: a different set of const variables, or different
    const values, is a different signature. Unhashable const values fall back to
    their ``repr`` (a placeholder; see the hashing notes in
    ``docs/design/constness.md`` for the intended canonical form).
    """
    return frozenset((name, _freeze(const_value(value))) for name, value in context.items() if is_const(value))


def _freeze(value: Any) -> Any:
    """Return ``value`` if hashable, else a stable-ish string stand-in."""
    try:
        hash(value)
    except TypeError:
        return repr(value)
    else:
        return value
