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

The slow step, the body-generating function (parse + compile + exec of the
template), is built once per **component class** and cached on the class, since
it is the same for a given template. Calling it yields a fresh node list each
render. (Per-element/per-signature body caching belongs to the parked
const-folding design; see docs/design/constness.md.)

This is a skeleton. Some features from django-components are not yet
ported (context snapshotting, JS/CSS media). They will be added iteratively.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from citry.citry_context import CitryContext
from citry.citry_render import CitryRender, DeferredComponent
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
    from citry_core.template_parser import TagRules


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
    provides: dict[str, Any] | None = None,
) -> CitryRender:
    """
    Render a component and everything inside it, returning a finished CitryRender.

    Called by ``CitryElement.render()``. It renders the top component with
    ``_render_one``, which leaves each nested ``<c-child>`` as an unrendered
    ``DeferredComponent``. This function then renders those children one at a
    time, working through a list instead of calling itself, so a deeply nested
    page never hits Python's recursion limit (see
    docs/design/deferred_rendering.md).

    A component's ``on_component_rendered`` hook runs once everything inside that
    component has been rendered (so children run before their parents), and at
    that same point the child's collected dependencies are copied into its
    parent.

    Args:
        element: The component to render (its class, kwargs, slots, and cached
            template body).
        parent: The parent Component instance when rendering inside another
            component's template. Sets the parent/root links.
        provides: The provide/inject entries the rendered component inherits
            (see docs/design/provide.md). Empty for a plain user call; set
            when an element is rendered from inside another render (an
            embedded ``{{ element }}`` or slot content), so the subtree keeps
            the provides active at its render site.

    Returns:
        A finished ``CitryRender`` with every child rendered (no
        ``DeferredComponent`` parts left). Call ``.serialize()`` (or ``str()``)
        on it to get the HTML.

    """
    root_render = _render_one(element, parent, provides)

    # We keep a stack of two kinds of work:
    #   - _RenderTask: render one deferred child, and put its result where the
    #     DeferredComponent was.
    #   - _FinalizeTask: run that child's after-render hook and copy its
    #     dependencies into the parent.
    # When we render a child we add its _FinalizeTask first, then its own
    # children on top. We always take from the top of the stack, so a child and
    # everything inside it finish before we run the parent's _FinalizeTask. (This
    # is the approach django-components uses, but on objects instead of HTML
    # strings.)
    stack: list[_RenderTask | _FinalizeTask] = [_FinalizeTask(root_render, None)]
    stack.extend(reversed(_scan_deferred(root_render)))

    root_result = root_render
    while stack:
        task = stack.pop()
        # Case: Render nested component
        if isinstance(task, _RenderTask):
            child_render = _render_one(task.deferred.element, task.deferred.parent, task.deferred.provides)
            _replace_in_parts(task.position.parts, task.position.idx, task.deferred, child_render)
            stack.append(_FinalizeTask(child_render, task.position))
            stack.extend(reversed(_scan_deferred(child_render)))
        # Case: Finalize nested component
        else:
            final = _finalize(task.render)
            if task.position is None:
                root_result = final
            else:
                _replace_in_parts(task.position.parts, task.position.idx, task.render, final)
                _merge_dependencies(task.position.parent_context, final.context)

    return root_result


class _DeferredComponentPosition(NamedTuple):
    """Where a ``DeferredComponent`` sits, so we can put its rendered result there."""

    parts: list[RenderPart]  # the list the DeferredComponent is in
    idx: int  # its position in that list (named `idx`, not `index`, so it doesn't hide tuple.index)
    parent_context: CitryContext  # the parent component's context; where this child's dependencies go


class _RenderTask(NamedTuple):
    """Render one deferred child component."""

    deferred: DeferredComponent
    position: _DeferredComponentPosition


class _FinalizeTask(NamedTuple):
    """Run a rendered component's after-render hook and copy its dependencies up."""

    render: CitryRender
    position: _DeferredComponentPosition | None  # None for the top (root) component


def _scan_deferred(render: CitryRender) -> list[_RenderTask]:
    """
    Find the child components inside ``render`` that still need rendering.

    Returns one ``_RenderTask`` per ``DeferredComponent``, descending into
    every nested ``CitryRender``. Most nested renders share this component's
    context (``<c-if>``/``<c-for>`` blocks, nested templates), but slot-fill
    content invoked during this render carries the context of the component
    that *wrote* the fill, and components inside it defer like any other, so
    cross-context renders are searched too. Descending into an embedded,
    already-completed subtree is harmless: ``render_impl`` finished its queue,
    so it contains no ``DeferredComponent`` parts.

    Each task's ``parent_context`` is the context of the nested render the
    deferred sits in: that is the lexical owner (for fill content, the
    component whose template wrote it), which is where the child's
    dependencies belong (see docs/design/slots.md section 8).
    """
    tasks: list[_RenderTask] = []

    def walk(parts: list[RenderPart], parent_context: CitryContext) -> None:
        for i, part in enumerate(parts):
            if isinstance(part, DeferredComponent):
                tasks.append(_RenderTask(part, _DeferredComponentPosition(parts, i, parent_context)))
            elif isinstance(part, CitryRender):
                walk(part.parts, part.context)

    walk(render.parts, render.context)
    return tasks


def _replace_in_parts(parts: list[RenderPart], index: int, target: object, new: RenderPart) -> None:
    """
    Put ``new`` where ``target`` currently is in ``parts``.

    ``index`` is where ``target`` was last seen, so we check that spot first. If
    the list has changed (for example user code or an extension edited
    ``parts``), we scan the whole list for ``target`` instead. Each render step
    swaps one item for one item, so positions normally stay put.
    """
    if 0 <= index < len(parts) and parts[index] is target:
        parts[index] = new
        return
    for i, part in enumerate(parts):
        if part is target:
            parts[i] = new
            return
    msg = "deferred part vanished from its .parts list before resolution"
    raise RuntimeError(msg)


def _finalize(render: CitryRender) -> CitryRender:
    """
    Run a rendered component's ``on_component_rendered`` hook and apply the result.

    An extension may return a new ``CitryRender`` or ``str`` to replace the
    output, or raise to turn it into an error that propagates. This runs once the
    component and everything inside it have been rendered.
    """
    component = render.context.component
    if component is None:
        return render
    new_render, error = component.citry.extensions.on_component_rendered(component, render, None)
    if error is not None:
        raise error
    if isinstance(new_render, str):
        return CitryRender(parts=[new_render], context=render.context, is_component_root=render.is_component_root)
    if new_render is not None:
        # The replacement stands in for the component's whole output, so it
        # inherits the root-render marking (serialization frames depend on it).
        new_render.is_component_root = render.is_component_root
        return new_render
    return render


def _render_one(
    element: CitryElement,
    parent: Component | None = None,
    provides: dict[str, Any] | None = None,
) -> CitryRender:
    """
    Render one component, without rendering the components inside it.

    Creates the Component instance, runs the data methods, builds (or reuses) the
    template body, and turns it into a ``CitryRender``. Any ``<c-child>`` tags in
    the template become unrendered ``DeferredComponent`` parts; rendering those,
    and running ``on_component_rendered``, is done by ``render_impl``.

    Args:
        element: The CitryElement to render. Carries the component class,
            kwargs, slots, and the cached body (node list).
        parent: The parent Component instance if rendering inside another
            component's template. Used to set parent/root references.
        provides: The provide/inject entries this component inherits (captured
            where its tag sits, or passed by the caller). Readable via
            ``Component.inject`` and passed on to its own descendants.

    Returns:
        A ``CitryRender`` whose parts may contain unresolved ``DeferredComponent``
        parts, plus the ``CitryContext`` used during the render.

    """
    comp_cls = element.comp_cls
    citry_instance = comp_cls.citry
    extensions = citry_instance.extensions

    # 1. Create component instance with all state.
    #    Uses _create_instance() which bypasses ComponentMeta.__call__
    #    (that returns a CitryElement) and calls Component.__init__.
    #    __init__ handles input normalization (dict/NamedTuple/dataclass ->
    #    dict, copied), id generation, typed kwargs/slots, raw_ variants,
    #    inherited provides, and parent/root references.
    component = comp_cls._create_instance(
        kwargs=element.kwargs,
        slots=element.slots,
        parent=parent,
        provides=provides,
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
    #    ``provides`` are the entries this component inherited plus anything
    #    it registered itself via ``Component.provide`` during template_data;
    #    a new mapping is built only when the component actually provided
    #    something (see docs/design/provide.md section 4.1).
    #    The Const markers stay in ``variables`` so they flow down to descendant
    #    components, each of which can detect const-ness and cache accordingly.
    #    Const is a transparent proxy, so nodes treat a const value exactly like
    #    the underlying value.
    active_provides = component._provides_inherited
    if component._provides_own:
        active_provides = {**active_provides, **component._provides_own}
    context = CitryContext(variables=tpl_data, component=component, provides=active_provides)

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

    # 7. Walk the body into a parts list and wrap it in a CitryRender. Any nested
    #    components are left as unrendered DeferredComponent parts; render_impl
    #    renders them and runs on_component_rendered for each one once everything
    #    inside it has been rendered. This render is the component's whole
    #    output, so it is marked as the component's root render (serialization
    #    relies on the flag to find component frame boundaries). A transparent
    #    component opts out: its output joins the surrounding frame and gets no
    #    data-cid marker (e.g. the <c-provide> built-in).
    parts = _render_body(body, context)
    return CitryRender(parts=parts, context=context, is_component_root=not comp_cls.transparent)

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

        comp_cls._template_body_generator = (
            _compile_body_generator(template_str, comp_cls.citry._tag_rules()) if template_str is not None else None
        )
    return comp_cls.__dict__["_template_body_generator"]


def _compile_body_generator(
    template_str: str,
    user_rules: dict[str, TagRules] | None = None,
) -> Callable[[], list[BodyItem]]:
    """
    Parse, compile, and exec a template string into a body-generating function.

    Uses the citry_core pipeline: parse -> compile -> exec. Returns the
    ``generate_template`` function from the exec'd namespace; calling it
    returns a fresh list of static strings and runtime node objects.

    ``user_rules`` are the parse-time validation rules derived from the
    registered components' declarations (``Citry._tag_rules()``), so a
    template using a declared component fails here, at parse time, on unknown
    or missing kwargs/fills.

    The compiled code creates node objects (ExprNode, ComponentNode, etc.) by
    name. Those names are supplied through the ``ns`` namespace below, so the
    generated code can find them.
    """
    ast = parse_template(template_str, user_rules=user_rules)
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
    Render a body (a list of static strings and nodes) into a list of parts.

    Static strings pass through unchanged. Each node is rendered with
    ``context`` and adds a part: a ``str``, a nested ``CitryRender``, or a
    ``DeferredComponent`` (a ``<c-child>`` tag, rendered later by ``render_impl``).

    A node may return a ``CitryRender`` from a *different* render: an
    already-rendered value found in a ``{{ ... }}`` expression. When that happens
    its dependencies are copied into this render's context. A ``CitryRender`` from
    *this* render (for example a ``<c-if>`` block or a nested template, which use
    the same context) does not need copying.

    The parts are returned as a list, not joined into one string, so that an
    already-rendered value embedded in the middle can still be read later. Joining
    happens in ``CitryRender.serialize()``.
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
    Copy one render's collected data into the render that contains it.

    This is where the JS/CSS dependency flow will live (docs/design/rendering.md
    section 6): a child render's dependencies need to reach the page that
    includes it. Nothing fills ``extra`` yet, so this does nothing for now; the
    dependency extension will decide the real rules (keep tree order, drop
    duplicates, rather than letting the last write win).
    """
    into.extra.update(source.extra)


def _const_signature(context: dict[str, Any]) -> frozenset[tuple[str, Any]]:
    """
    Build a cache key from the variables marked ``Const``.

    The body cache uses this key: a different set of ``Const`` variables, or the
    same ones with different values, gives a different key and so a different
    cached body. A ``Const`` value that cannot be used as a dict/set key falls
    back to its ``repr`` (a stand-in; see the hashing notes in
    ``docs/design/constness.md`` for the intended final form).
    """
    return frozenset((name, _freeze(const_value(value))) for name, value in context.items() if is_const(value))


def _freeze(value: Any) -> Any:
    """Return ``value`` unchanged if it can be a dict/set key, else its ``repr`` string."""
    try:
        hash(value)
    except TypeError:
        return repr(value)
    else:
        return value
