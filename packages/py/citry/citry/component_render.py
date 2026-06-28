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

The slow step, compiling the template (parse + compile + exec) into a
body-generating function, runs once per **component class** and is cached on
the class, since it is the same for a given template. On top of that sits the
``Const`` optimization: parts of the template that depend only on inputs
marked ``Const()`` ("same value on every render") are computed once and the
result is cached per component class and per set of ``Const`` values, so
repeat renders skip that work. See docs/design/constness.md and
citry/constness.py.

Rendering is deferred and stack-driven (no recursion limit on nesting depth),
collects each component's JS/CSS dependencies, and drives the ``on_render``
hook; see docs/design/deferred_rendering.md and on_render.md. Django's
context snapshotting is deliberately not ported: a component receives only
its own props and slots, never an inherited context.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, NamedTuple

from citry.assets import load_template
from citry.citry_context import CitryContext
from citry.citry_element import CitryElement
from citry.citry_render import CitryRender, DeferredComponent
from citry.citry_template import CitryTemplate
from citry.constness import const_value, extract_const_vars, precompute_const_parts
from citry.nodes import (
    ComponentNode,
    ElementAttrsNode,
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
from citry.slots import Slot
from citry.util.exception import (
    set_component_error_message,
    set_template_origin_error_message,
    set_template_position_error_message,
)
from citry.util.misc import is_generator, to_dict
from citry_core.template_parser import compile_template, parse_template

if TYPE_CHECKING:
    from collections.abc import Callable

    from citry.citry_render import OnRenderGenerator, RenderPart, RenderReplacement
    from citry.component import Component
    from citry.nodes import BodyItem
    from citry_core.template_parser import TagRules


# Per-render template globals: the variables passed to a single render through
# Component.render(template_globals=...). Held in a context variable because the
# value is the same for the whole render and must reach every nested render
# (deferred children, embedded {{ element }} values, slot content) without being
# threaded through each node and slot; a concurrent render on another thread or
# task keeps its own value. None means no per-render override was given.
_render_globals: ContextVar[dict[str, Any] | None] = ContextVar("citry_render_globals", default=None)


def render_impl(
    element: CitryElement,
    parent: Component | None = None,
    provides: dict[str, Any] | None = None,
    *,
    render_globals: dict[str, Any] | None = None,
) -> CitryRender:
    """
    Render a component and everything inside it into a finished ``CitryRender``.

    The public render entry: ``CitryElement.render`` calls it, and a composed
    element found in a ``{{ ... }}`` expression renders through it too.

    ``render_globals`` are the per-render template variables from
    ``Component.render(template_globals=...)``. They are merged into every
    component in this render, on top of the instance's ``citry.template_globals``
    and under a component's own ``template_data``. They are kept in a context
    variable for the duration of the render, so every nested render sees them
    without being passed the value. ``None`` (the default) adds no override and
    leaves any enclosing render's globals in place, so a nested ``render_impl``
    call does not disturb the render it runs inside.
    """
    if render_globals is None:
        return _render_tree(element, parent, provides)
    token = _render_globals.set(render_globals)
    try:
        return _render_tree(element, parent, provides)
    finally:
        _render_globals.reset(token)


def _render_tree(
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

    A component's after-render hooks run once everything inside that component
    has been rendered (so children run before their parents): first its own
    ``on_render`` generator is resumed with the settled result (it may replace
    the output, any number of times), then extensions' ``on_component_rendered``
    runs, and the child's collected dependencies are copied into its parent.

    When a component's render fails, the error travels up the component tree:
    each enclosing component's ``on_render`` generator, then extensions'
    ``on_component_rendered``, runs with the error and may swallow it by
    producing replacement output. An error nothing handles is raised from
    here, carrying the component path in its message
    (docs/design/on_render.md sections 5-6).

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
    root_render, root_generator = _render_one_traced(element, parent, provides)

    # We keep a stack of two kinds of work:
    #   - _RenderTask: render one deferred child, and put its result where the
    #     DeferredComponent was.
    #   - _FinalizeTask: run that child's after-render hooks and copy its
    #     dependencies into the parent.
    # When we render a child we add its _FinalizeTask first, then its own
    # children on top. We always take from the top of the stack, so a child and
    # everything inside it finish before we run the parent's _FinalizeTask. (This
    # is the approach django-components uses, but on objects instead of HTML
    # strings.)
    stack: list[_RenderTask | _FinalizeTask] = [_FinalizeTask(root_render, None, root_generator)]
    stack.extend(reversed(_scan_deferred(root_render)))

    root_result = root_render

    def commit(old: CitryRender, final: CitryRender, position: _DeferredComponentPosition | None) -> None:
        # Put a component's settled output where it belongs: at its recorded
        # position in the parent's parts (copying its collected dependencies
        # up), or as the new root result.
        nonlocal root_result
        if position is None:
            root_result = final
        else:
            _replace_in_parts(position.parts, position.idx, old, final)
            _merge_dependencies(position.parent_context, final.context)

    def requeue(task: _FinalizeTask, content: RenderReplacement, generator: OnRenderGenerator | None) -> None:
        # The component's on_render generator replaced its output. Render the
        # new content in its place (children deferred as usual) and finalize
        # the component again once the new content settles; the generator (if
        # still live) is then resumed with that result.
        old = task.render
        component = old.context.component
        if component is None:
            msg = "an on_render generator settled on a render that has no component."
            raise RuntimeError(msg)
        new_render = CitryRender(
            parts=_replacement_parts(content, old.context, component),
            context=old.context,
            is_component_root=old.is_component_root,
        )
        if task.position is not None:
            _replace_in_parts(task.position.parts, task.position.idx, old, new_render)
        stack.append(_FinalizeTask(new_render, task.position, generator))
        stack.extend(reversed(_scan_deferred(new_render)))

    def settle(task: _FinalizeTask, error: Exception | None) -> CitryRender | None:
        # Settle a component whose subtree has finished rendering (or, when
        # ``error`` is set, whose subtree failed): drive its on_render
        # generator, then run the extension hook via _finalize.
        #
        # Returns the final render to commit, or None when the generator
        # produced new content that was queued for re-processing (this task's
        # replacement finalize is then on the stack). Raises when the error,
        # incoming or raised here, was not handled, so the caller bubbles it.
        render: CitryRender | None = task.render if error is None else None
        generator = task.generator
        while generator is not None:
            try:
                yielded = generator.send((render, error))
            except StopIteration as stop:
                if stop.value is not None:
                    # `return <content>`: the final output; the generator is
                    # done, so the re-queued finalize carries no generator.
                    requeue(task, stop.value, None)
                    return None
                # Plain `return`: keep the current result (and error).
                break
            except Exception as gen_error:  # noqa: BLE001
                # The generator raised: that becomes the component's error.
                # A fresh error gets this component's path; re-raising the
                # error it was sent keeps the original frames.
                if gen_error is not error:
                    set_component_error_message(gen_error, _component_path(task.render.context.component))
                render, error = None, gen_error
                break
            if yielded is None:
                # Bare yield after the first: answer immediately with the
                # unchanged result.
                continue
            try:
                requeue(task, yielded, generator)
            except TypeError as bad_yield:
                # The yielded value was not renderable; deliver the failure
                # back to this generator, like any error in its content.
                set_component_error_message(bad_yield, _component_path(task.render.context.component))
                render, error = None, bad_yield
                continue
            return None
        return _finalize(task.render, error)

    def bubble(error: Exception) -> None:
        # A component's render failed; give its ancestors a chance to handle
        # the error (docs/design/on_render.md section 5).
        #
        # The stack is pushed depth-first, so everything above an ancestor's
        # _FinalizeTask is exactly that ancestor's pending subtree work.
        # Popping to the nearest _FinalizeTask therefore discards the dead
        # output's remaining work and lands on the nearest enclosing
        # component. That component's on_render generator, then extensions,
        # may swallow the error by producing replacement output, which ends
        # the unwind. Otherwise the error continues to the next ancestor, and
        # out of render_impl at the root.
        while stack:
            task = stack.pop()
            if not isinstance(task, _FinalizeTask):
                continue
            try:
                final = settle(task, error)
            except Exception as unhandled:  # noqa: BLE001
                error = unhandled
                continue
            if final is not None:
                commit(task.render, final, task.position)
            # final is None: the generator queued replacement output, which
            # also ends the unwind (the component is re-processing).
            return
        raise error

    while stack:
        task = stack.pop()
        # Case: Render nested component
        if isinstance(task, _RenderTask):
            try:
                child_render, generator = _render_one_traced(
                    task.deferred.element,
                    task.deferred.parent,
                    task.deferred.provides,
                )
            except Exception as error:  # noqa: BLE001
                bubble(error)
                continue
            _replace_in_parts(task.position.parts, task.position.idx, task.deferred, child_render)
            stack.append(_FinalizeTask(child_render, task.position, generator))
            stack.extend(reversed(_scan_deferred(child_render)))
        # Case: Finalize nested component
        else:
            try:
                final = settle(task, None)
            except Exception as error:  # noqa: BLE001
                bubble(error)
                continue
            if final is not None:
                commit(task.render, final, task.position)

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
    """Run a rendered component's after-render hooks and copy its dependencies up."""

    render: CitryRender
    position: _DeferredComponentPosition | None  # None for the top (root) component
    # The component's live on_render generator when the hook yielded; resumed
    # with the settled result when this task runs (None for most components).
    generator: OnRenderGenerator | None = None


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


def _component_path(component: Component | None) -> list[str]:
    """
    The class names from the root component down to ``component``, inclusive.

    Walks the ``parent`` links upward and reverses, so the root comes first.
    These names are the path frames put into error messages ("MyPage > Card >
    Avatar"; see docs/design/on_render.md section 6). An embedded element
    rendered from an expression has no parent link; its chain starts at
    itself, and the path of the component it is embedded in is prepended when
    the error passes through that component's render (``_render_one_traced``).
    """
    names: list[str] = []
    while component is not None:
        names.append(type(component).__name__)
        component = component.parent
    names.reverse()
    return names


def _render_one_traced(
    element: CitryElement,
    parent: Component | None = None,
    provides: dict[str, Any] | None = None,
) -> tuple[CitryRender, OnRenderGenerator | None]:
    """
    ``_render_one``, with the component path added to any error raised.

    The path is the parent chain plus this component's class name, which is
    the same chain the created instance would report (its ``parent`` is set
    from this ``parent`` argument), and is available even when the failure
    happens before the instance exists (e.g. kwargs validation).
    """
    try:
        return _render_one(element, parent, provides)
    except Exception as err:
        set_component_error_message(err, [*_component_path(parent), element.comp_cls.__name__])
        raise


def _finalize(render: CitryRender, error: Exception | None) -> CitryRender:
    """
    Settle a rendered component: run ``on_component_rendered`` and apply the result.

    Runs once the component and everything inside it have been rendered, or,
    when ``error`` is set, when a component inside it failed and the error is
    bubbling up (docs/design/on_render.md section 5). The extension hook
    receives the rendered output, or ``None`` together with the error when
    rendering failed. An extension may replace the output with a new
    ``CitryRender`` or ``str`` (which also swallows the error), or raise to
    replace the error. An error that is not swallowed is raised here, to
    continue bubbling.
    """
    component = render.context.component
    if component is None:
        if error is not None:
            raise error
        return render
    new_render, out_error = component.citry.extensions.on_component_rendered(
        component,
        None if error is not None else render,
        error,
    )
    if out_error is not None:
        # A fresh error (raised by an extension just now) gets this
        # component's path; a bubbling error passing through unchanged
        # already carries the frames from where it happened.
        if out_error is not error:
            set_component_error_message(out_error, _component_path(component))
        raise out_error
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
) -> tuple[CitryRender, OnRenderGenerator | None]:
    """
    Render one component, without rendering the components inside it.

    Creates the Component instance, runs the data methods, calls the
    ``on_render`` hook, builds (or reuses) the template body, and turns it
    into a ``CitryRender``. Any ``<c-child>`` tags in the template become
    unrendered ``DeferredComponent`` parts; rendering those, and running
    ``on_component_rendered``, is done by ``render_impl``.

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
        parts, plus the component's live ``on_render`` generator when the hook
        yielded (``None`` otherwise). ``render_impl`` resumes the generator with
        the settled result once the component's subtree has rendered.

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

    # 3. Call the data methods (per-render; intentionally not cached).
    #    template_data() feeds the template variables; js_data() / css_data()
    #    feed the component's JS/CSS variables, consumed by the built-in
    #    `dependencies` extension (docs/design/dependencies.md section 5).
    #    Each may return a dict, a NamedTuple, or the component's typed
    #    dataclass; `_normalize_data` converts to a plain dict and validates
    #    against the declared schema. No defensive copy is needed (unlike
    #    kwargs/slots): the data is produced fresh by user code on every
    #    render, not shared state.
    tpl_data = _normalize_data(component.template_data(component.kwargs, component.slots), comp_cls.TemplateData)
    js_data = _normalize_data(component.js_data(component.kwargs, component.slots), comp_cls.JsData)
    css_data = _normalize_data(component.css_data(component.kwargs, component.slots), comp_cls.CssData)

    # 3.5 Overlay template globals: variables exposed to every component's
    #     template without being returned from each template_data(). Two layers,
    #     lowest precedence first: this instance's citry.template_globals, then
    #     any per-render globals from Component.render(template_globals=...). The
    #     component's own data wins over both, so all globals go under tpl_data.
    #     Merged after the schema check above, so a global need not appear in a
    #     component's declared TemplateData. Skipped when there are none, so a
    #     render with no globals pays nothing here.
    instance_globals = citry_instance.template_globals
    render_globals = _render_globals.get()
    if instance_globals or render_globals:
        tpl_data = {**instance_globals, **(render_globals or {}), **tpl_data}

    # 4. Build the render-scoped context. ``variables`` are the template
    #    variables (the template_data output); ``extra`` is the tree-wide
    #    scratch space extensions populate (dependency records, etc.).
    #    The Const markers stay in ``variables`` so they flow down to descendant
    #    components, each of which can detect const-ness and cache accordingly.
    #    Const is a transparent proxy, so nodes treat a const value exactly like
    #    the underlying value.
    context = CitryContext(
        variables=tpl_data,
        component=component,
        sandboxed=citry_instance.settings.sandbox_expressions,
    )

    # 4.5 on_component_data: extensions may add/modify the data, and stash
    #     tree-wide state into ``context.extra`` (e.g. the dependencies
    #     extension's render records).
    extensions.on_component_data(component, context, tpl_data, js_data, css_data)

    # 5. ``provides`` are the entries this component inherited plus anything
    #    it registered itself via ``Component.provide`` during template_data;
    #    a new mapping is built only when the component actually provided
    #    something (see docs/design/provide.md section 4.1).
    active_provides = component._provides_inherited
    if component._provides_own:
        active_provides = {**active_provides, **component._provides_own}
    context.provides = active_provides

    # 5.5 The per-component render hook (docs/design/on_render.md section 3).
    #     Returning None (the default) renders the template as usual.
    #     Returning content makes it the component's whole output, and the
    #     template body below is never built or walked. A generator runs up
    #     to its first yield here (the "before" phase), and what it yielded
    #     picks the output the same way; the live generator then travels with
    #     the component's finalize task and is resumed with the settled
    #     result once the whole subtree has rendered (``settle`` in
    #     ``render_impl``).
    hook_result = component.on_render()
    generator: OnRenderGenerator | None = None
    parts: list[RenderPart] | None = None
    if is_generator(hook_result):
        # Prime the generator (runs the before-phase, up to the first
        # yield). A bare first yield means "render the template as usual";
        # yielded or returned content becomes the output instead.
        generator = hook_result
        parts, generator = _send_into_generator(generator, None, context, component, default_on_none=True)
    elif hook_result is not None:
        parts = _replacement_parts(hook_result, context, component)

    if parts is not None:
        return CitryRender(parts=parts, context=context, is_component_root=not comp_cls.transparent), generator

    # 6. Build the body (the list of static strings and node objects the
    #    template compiles to). Parsing and compiling the template runs once
    #    per component class (cached on the class).
    #
    #    Then the Const optimization kicks in. extract_const_vars() collects
    #    the template variables wrapped in Const() ("same value on every
    #    render") and turns them into a cache key. The first render with a
    #    given set of Const values builds the node list and runs precompute_const_parts()
    #    on it, which does the work that depends only on those values right
    #    away: e.g. "{{ cols }}" with cols=Const(3) becomes the text "3", and
    #    a <c-if> whose condition uses only Const values keeps just the
    #    branch that matches. The result is cached, so later renders with the
    #    same Const values reuse it and skip all of that work. See
    #    docs/design/constness.md and citry/constness.py.
    #
    #    on_template_compiled fires here (per built node list, before the
    #    optimization and caching), so an extension can transform the node
    #    list once and have the transform cached. See
    #    docs/design/extensions.md section 7.4.
    #
    #    Only variables the template actually uses (``compiled.used_vars``)
    #    go into the cache key; a Const value the template never reads cannot
    #    change the output, so keying on it would only create duplicate cache
    #    entries. A node injected by an extension may use a variable outside
    #    that set; such a variable simply stays un-optimized and re-evaluates
    #    each render, which is always safe.
    try:
        compiled = _get_compiled_template(comp_cls)
        generate = compiled.generate if compiled is not None else None
        if compiled is None or generate is None:
            body: list[BodyItem] = []
        else:
            const_vars, signature = extract_const_vars(tpl_data, used_vars=compiled.used_vars)

            def build() -> list[BodyItem]:
                return precompute_const_parts(
                    extensions.on_template_compiled(comp_cls, generate()),
                    const_vars,
                    # Precomputing an attribute region bakes its dict before extensions
                    # see it, so keep the regions live when anyone subscribes.
                    precompute_attrs=not extensions.has_hook("on_attrs_resolved"),
                    sandboxed=citry_instance.settings.sandbox_expressions,
                )

            body = citry_instance._const_body_cache.get_or_build(comp_cls, signature, build)

        # 7. Walk the body into a parts list and wrap it in a CitryRender. Any nested
        #    components are left as unrendered DeferredComponent parts; render_impl
        #    renders them and runs on_component_rendered for each one once everything
        #    inside it has been rendered. This render is the component's whole
        #    output, so it is marked as the component's root render (serialization
        #    relies on the flag to find component frame boundaries). A transparent
        #    component opts out: its output joins the surrounding frame and gets no
        #    data-cid marker (e.g. the <c-provide> built-in).
        parts = _render_body(body, context)
    except Exception as render_error:
        if generator is None:
            raise
        # The component's own template failed; deliver the error to its live
        # on_render generator, the same ``(None, error)`` it would receive
        # for a failing child. This is what lets an error boundary guard its
        # own slot content, which renders right here in its body walk. The
        # generator may produce replacement output; if it does not (plain
        # return), the error continues out as usual.
        parts, generator = _send_into_generator(
            generator,
            (None, render_error),
            context,
            component,
            default_on_none=False,
        )
        if parts is None:
            raise

    return CitryRender(parts=parts, context=context, is_component_root=not comp_cls.transparent), generator


def _send_into_generator(
    generator: OnRenderGenerator,
    send_arg: Any,
    context: CitryContext,
    component: Component,
    *,
    default_on_none: bool,
) -> tuple[list[RenderPart] | None, OnRenderGenerator | None]:
    """
    Send into an ``on_render`` generator until it produces an outcome.

    Used inside ``_render_one``, at priming time (``send_arg`` is ``None``)
    and when the component's own template render failed (``send_arg`` is
    ``(None, error)``). Returns ``(parts, generator)``: the replacement parts
    (``None`` for "no replacement") and the generator if it is still live
    (``None`` once it finished).

    An unrenderable yielded value (the ``TypeError`` from the coercion) is
    delivered back into the generator as ``(None, error)``, so every yield
    uniformly receives the settled result or failure of what it yielded.

    A bare yield (``yield`` / ``yield None``) means "render the template as
    usual" while priming (``default_on_none=True``). After an error was
    delivered (``default_on_none=False``) it means "answer again with the
    unchanged result", so the same value is re-sent, mirroring the settle
    loop in ``render_impl``.
    """
    while True:
        try:
            yielded = generator.send(send_arg)
        except StopIteration as stop:
            if stop.value is None:
                # Plain return: no replacement, generator done.
                return None, None
            return _replacement_parts(stop.value, context, component), None
        if yielded is None:
            if default_on_none:
                return None, generator
            continue
        try:
            return _replacement_parts(yielded, context, component), generator
        except TypeError as bad_yield:
            set_component_error_message(bad_yield, _component_path(component))
            send_arg = (None, bad_yield)


def _replacement_parts(value: RenderReplacement, context: CitryContext, component: Component) -> list[RenderPart]:
    """
    Convert an ``on_render`` replacement value into the component's parts list.

    The accepted values mirror what a ``{{ ... }}`` expression accepts
    (``_render_value`` in citry_render.py), with two differences: a ``str``
    is the component's own output, so it is used as-is rather than
    autoescaped, and an unsupported type is an error rather than being
    escaped to text (docs/design/on_render.md section 3.1).
    """
    # A Const marker is unwrapped first (a replacement built from a literal
    # template attribute arrives Const-wrapped); the value becomes output
    # here, so the marker has no further role, and the proxy must not leak
    # into the parts.
    value = const_value(value)
    if isinstance(value, str):
        return [value]
    if isinstance(value, Slot):
        # Invoked with no data, like {{ my_slot }}. Slot content renders with
        # the scope of the component that wrote it, so its collected data is
        # copied into this render (the same merge as _render_body does).
        part = value(provides=context.provides)
        if isinstance(part, CitryRender) and part.context is not context:
            _merge_dependencies(context, part.context)
        return [part]
    if isinstance(value, CitryElement):
        # Deferred like a <c-child> tag in the template: the render_impl loop
        # renders it, so a replacement chain can never exhaust the Python
        # call stack.
        return [DeferredComponent(value, parent=component, provides=context.provides)]
    if isinstance(value, CitryRender):
        # An already-rendered subtree is inlined; its collected data is
        # copied into this render.
        if value.context is not context:
            _merge_dependencies(context, value.context)
        return [value]
    msg = (
        f"{type(component).__name__}.on_render() returned {type(value).__name__!r}; "
        "expected a str, a composed element, a CitryRender, a Slot, or None."
    )
    raise TypeError(msg)


def _get_compiled_template(comp_cls: type[Component]) -> CitryTemplate | None:
    """
    Return the component's template with its compiled form filled in.

    The template is loaded via ``assets.load_template``, which resolves
    ``template`` / ``template_file``, reads the file when needed, fires
    ``on_template_loaded``, and caches the ``CitryTemplate`` on the class (see
    docs/design/asset_loading.md). On the first render this function compiles
    the source and fills the struct's ``generate`` / ``used_vars`` in place,
    so the loaded and compiled halves share one cache and one invalidation
    (``Component.reset_template()``). Each call to ``generate`` produces a
    fresh node list. Returns ``None`` when the component has no template.

    A parse or compile error is re-raised with the template's origin (the file
    path, or ``module::Class`` for inline) prefixed to its message, so a
    syntax error names where the template came from.
    """
    template = load_template(comp_cls)
    if template is None:
        return None
    if template.generate is None:
        try:
            _compile_template(template, comp_cls.citry._tag_rules())
        except Exception as err:
            set_template_origin_error_message(err, template.origin)
            raise
    return template


def _compile_template(
    template: CitryTemplate,
    user_rules: dict[str, TagRules] | None = None,
) -> None:
    """
    Parse, compile, and exec a template's source, filling its compiled form.

    Uses the citry_core pipeline: parse -> compile -> exec. The
    ``generate_template`` function from the exec'd namespace becomes
    ``template.generate``; calling it returns a fresh list of static strings
    and runtime node objects. The parsed AST's root ``used_variables`` (which
    are transitive) become ``template.used_vars``.

    ``user_rules`` are the parse-time validation rules derived from the
    registered components' declarations (``Citry._tag_rules()``), so a
    template using a declared component fails here, at parse time, on unknown
    or missing kwargs/fills.

    The compiled code creates node objects (ExprNode, ComponentNode, etc.) by
    name. Those names are supplied through the ``ns`` namespace below, so the
    generated code can find them.
    """
    ast = parse_template(template.source, user_rules=user_rules)
    template.used_vars = frozenset(token.content for token in ast.used_variables)
    code = compile_template(ast)

    # Build the namespace for exec. "source" is the original template string,
    # passed to nodes for error reporting and diagnostics. This namespace
    # becomes the returned function's globals, so the node classes and source
    # stay bound to it.
    ns: dict[str, Any] = {
        "source": template.source,
        "ExprNode": ExprNode,
        "TemplateNode": TemplateNode,
        "ComponentNode": ComponentNode,
        "ElementAttrsNode": ElementAttrsNode,
        "IfNode": IfNode,
        "ForNode": ForNode,
        "SlotNode": SlotNode,
        "FillNode": FillNode,
        "StaticHtmlAttr": StaticHtmlAttr,
        "ExprHtmlAttr": ExprHtmlAttr,
        "TemplateHtmlAttr": TemplateHtmlAttr,
    }
    exec(code, ns)  # noqa: S102
    template.generate = ns["generate_template"]


def _compile_nested_template(
    template_str: str,
    user_rules: dict[str, TagRules] | None = None,
) -> Callable[[], list[BodyItem]]:
    """
    Compile a nested template fragment into its body-generating function.

    Used by the nodes that carry a template *inside* an attribute value (a
    ``c-body="<span>{{ x }}</span>"`` on a component). Such a fragment is not
    a component class's template, so there is no class-level ``CitryTemplate``
    to fill; a throwaway one wraps the fragment for the shared compile step.
    Position-in-the-outer-template error context is attached by the node's
    render wrapper, not here.
    """
    template = CitryTemplate(source=template_str, origin="<nested template>")
    _compile_template(template, user_rules)
    generate = template.generate
    if generate is None:  # pragma: no cover - _compile_template always sets it
        msg = "nested template failed to compile"
        raise RuntimeError(msg)
    return generate


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
        try:
            part = item.render(context)
        except Exception as err:
            _attach_template_position(err, item, context)
            raise
        if isinstance(part, CitryRender) and part.context is not context:
            _merge_dependencies(context, part.context)
        parts.append(part)

    return parts


def _attach_template_position(err: Exception, node: BodyItem, context: CitryContext) -> None:
    """
    Add the failing node's template snippet to the error message.

    Every compiler-emitted node carries ``source`` (the whole template
    string) and ``position`` (its start/end indices in it); a node injected
    by an extension may not, in which case this does nothing. The snippet is
    added once per error, by the innermost failing node: control-flow bodies
    render through ``_render_body`` recursively, so the enclosing node's
    pass through here is a no-op (see ``set_template_position_error_message``).

    The header names ``context.component`` as the template's owner. That
    holds for slot-fill content too: a fill body renders with the context of
    the component that wrote it, and its nodes come from that component's
    template.
    """
    source = getattr(node, "source", None)
    position = getattr(node, "position", None)
    if not isinstance(source, str) or not isinstance(position, tuple) or len(position) != 2:
        return
    component = context.component
    component_name = type(component).__name__ if component is not None else None
    # Best-effort: name where the template came from in the snippet header.
    # The template is already loaded and cached by the time a node renders, so
    # this is a cache read; any failure just drops the origin from the header.
    origin: str | None = None
    if component is not None:
        try:
            template = load_template(type(component))
        except Exception:  # noqa: BLE001 - error reporting must not raise
            template = None
        if template is not None:
            origin = template.origin
    set_template_position_error_message(err, source, position, component_name, origin)


def _normalize_data(maybe_data: Any, schema_cls: type | None) -> dict[str, Any]:
    """
    Normalize one data method's result to a plain dict and validate it.

    The result of ``template_data()`` / ``js_data()`` / ``css_data()`` may be
    a dict, a NamedTuple, or the component's typed dataclass, so convert with
    ``to_dict``. When the component declares the matching schema class
    (``TemplateData``/``JsData``/``CssData``), constructing
    ``schema_cls(**data)`` raises on missing or unexpected fields; skipped
    when the method already returned a schema instance, since that was
    validated on construction.
    """
    data: dict[str, Any] = to_dict(maybe_data) if maybe_data is not None else {}
    if schema_cls is not None and not isinstance(maybe_data, schema_cls):
        schema_cls(**data)
    return data


def _merge_dependencies(into: CitryContext, source: CitryContext) -> None:
    """
    Fire the ``on_render_context_merge`` hook: a nested render's output was consumed
    by an enclosing render, so each extension merges its own slice of
    ``source.extra`` into ``into.extra`` with its own policy (the dependencies
    extension appends its records preserving order; see
    docs/design/rendering.md section 6 and docs/design/extensions.md section
    9.1). The core owns only the firing, not the merge semantics.

    A render with no component on either context has no ``Citry`` instance to
    reach extensions through; there is nothing to merge for it either, since
    only component renders collect tree-wide state.
    """
    component = into.component if into.component is not None else source.component
    if component is None:
        return
    component.citry.extensions.on_render_context_merge(into, source)
