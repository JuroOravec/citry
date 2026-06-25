"""
Shim that compiles a template two ways and offers both body walks to compare.

For one template source we build:

- the Python node list (what ``generate_template()`` returns today), walked by
  the live ``_render_body``; and
- the Rust render plan (``compile_render_plan``), walked by the Rust executor.

Both come from the same compiler intermediate form, so the plan entries line up
one-to-one with the node list by position. The Rust executor only crosses into
Python to evaluate a ``{{ expr }}`` (calling the same compiled evaluator the
Python walk uses) and to render any node kind it does not yet model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from citry import nodes as _nodes
from citry.citry_context import CitryContext
from citry.citry_render import CitryRender, DeferredComponent
from citry.component_render import _get_compiled_template, _normalize_data, _render_body
from citry_core._rust import render_plan as _render_plan_mod
from citry_core._rust import template_parser as _template_parser

if TYPE_CHECKING:
    from citry.nodes import BodyItem

# The runtime node classes the generated ``generate_template()`` instantiates.
# The generated code refers to them by bare name, so they must be in its
# namespace, alongside the original ``source`` string (used for diagnostics).
_NODE_CLASS_NAMES = (
    "ExprNode",
    "TemplateNode",
    "ComponentNode",
    "IfNode",
    "ForNode",
    "SlotNode",
    "FillNode",
    "ElementAttrsNode",
    "StaticHtmlAttr",
    "ExprHtmlAttr",
    "TemplateHtmlAttr",
)


def compile_node_list(source: str) -> list[BodyItem]:
    """Compile ``source`` to the Python node list the runtime walks today."""
    ast = _template_parser.parse_template(source, "python")
    code = _template_parser.compile_template(ast, "python")
    namespace: dict[str, Any] = {"source": source}
    for name in _NODE_CLASS_NAMES:
        namespace[name] = getattr(_nodes, name)
    exec(code, namespace)  # noqa: S102 - generated, trusted compiler output
    return namespace["generate_template"]()


def compile_plan(source: str) -> Any:
    """Compile ``source`` to the Rust render plan."""
    ast = _template_parser.parse_template(source, "python")
    return _render_plan_mod.compile_render_plan(ast)


def make_context(variables: dict[str, Any]) -> CitryContext:
    """A minimal render context (no component, no extensions) for the walk."""
    return CitryContext(variables=variables)


def _flatten_parts(parts: list[Any]) -> str:
    """
    Join a parts list to a string, recursing into nested ``CitryRender``s.

    A ``<c-if>`` or ``<c-for>`` body renders to a nested ``CitryRender`` (same
    context, no component boundary), which the real serializer joins recursively.
    The modelled cases never produce a component or deferred part, so a plain
    recursive join matches the serializer's output for these bodies.
    """
    out: list[str] = []
    for part in parts:
        if isinstance(part, CitryRender):
            out.append(_flatten_parts(part.parts))
        else:
            out.append(str(part))
    return "".join(out)


def python_render(node_list: list[BodyItem], context: CitryContext) -> str:
    """Walk the body with the live Python ``_render_body`` and join the parts."""
    return _flatten_parts(_render_body(node_list, context))


def select_if_branch(if_node: Any, context: CitryContext) -> int:
    """
    Index of the first matching ``<c-if>`` branch, or ``-1`` if none matches.

    Reuses the real ``IfNode.active_branch_body`` (the exact selection logic) and
    maps the chosen body back to its branch index.
    """
    body = if_node.active_branch_body(context)
    if body is None:
        return -1
    for index, branch in enumerate(if_node.branches):
        if branch[2] is body:
            return index
    return -1


def for_iterations(for_node: Any, context: CitryContext) -> tuple[list[CitryContext], CitryContext | None]:
    """
    Per-iteration scopes for a ``<c-for>`` loop body, plus the empty fallback.

    Reuses the real ``ForNode.iter_bodies`` (faithful loop-variable binding and
    scoping), separating the loop iterations from the optional ``<c-empty>``
    branch by identity of the body they carry.
    """
    loop_body = for_node.branches[0][2]
    loop_contexts: list[CitryContext] = []
    empty_context: CitryContext | None = None
    for body, child in for_node.iter_bodies(context):
        if body is loop_body:
            loop_contexts.append(child)
        else:
            empty_context = child
    return loop_contexts, empty_context


def rust_render(plan: Any, node_list: list[BodyItem], context: CitryContext) -> str:
    """Walk the body with the Rust executor and return the assembled string."""
    return plan.render(
        node_list,
        context.variables,
        context,
        select_if_branch,
        for_iterations,
        prepare_component,
        render_foreign,
    )


# ----- Component-boundary drive (Rust walks the whole component tree) -----

# A render plan and a body node list, each built once per component class. The
# real engine caches its (folded) body too, so building it fresh every render
# would be an unrepresentative cost that masks the body-walk difference.
_PLAN_CACHE: dict[type, Any] = {}
_BODY_CACHE: dict[type, list[BodyItem]] = {}


def _plan_for_class(comp_cls: type) -> Any:
    """The render plan for a component class, compiled once from its template."""
    plan = _PLAN_CACHE.get(comp_cls)
    if plan is None:
        compiled = _get_compiled_template(comp_cls)
        source = compiled.source if compiled is not None else ""
        plan = compile_plan(source)
        _PLAN_CACHE[comp_cls] = plan
    return plan


def _body_for_class(comp_cls: type) -> list[BodyItem]:
    """
    The component's body node list, built once and reused across renders (as
    the real engine reuses its cached folded body).
    """
    body = _BODY_CACHE.get(comp_cls)
    if body is None:
        compiled = _get_compiled_template(comp_cls)
        body = compiled.generate() if compiled is not None and compiled.generate is not None else []
        _BODY_CACHE[comp_cls] = body
    return body


def _prepare_element(element: Any, parent: Any, provides: Any) -> tuple[list[BodyItem], CitryContext, Any]:
    """
    Build a component and return its body, render context, and own plan.

    Replicates the prepare half of ``_render_one`` (build the instance, run
    ``template_data``, build the context) for a simple component (no slots, no
    ``on_render`` hook), then returns the UNFOLDED body. Const-folding is
    output-preserving, so the unfolded body walked against the unfolded plan
    yields the same HTML as the real (folding) engine.
    """
    comp_cls = element.comp_cls
    extensions = comp_cls.citry.extensions
    component = comp_cls._create_instance(kwargs=element.kwargs, slots=element.slots, parent=parent, provides=provides)
    extensions._init_component_instance(component)
    extensions.on_component_input(component)
    tpl_data = _normalize_data(component.template_data(component.kwargs, component.slots), comp_cls.TemplateData)
    context = CitryContext(variables=tpl_data, component=component)
    active_provides = component._provides_inherited
    if component._provides_own:
        active_provides = {**active_provides, **component._provides_own}
    context.provides = active_provides
    if component.on_render() is not None:
        msg = "the render-plan prototype does not support on_render hooks"
        raise NotImplementedError(msg)
    return _body_for_class(comp_cls), context, _plan_for_class(comp_cls)


def prepare_root(element: Any) -> tuple[list[BodyItem], CitryContext, Any]:
    """Prepare the root component of a tree for the Rust-driven walk."""
    return _prepare_element(element, None, None)


def prepare_component(component_node: Any, context: CitryContext) -> tuple[list[BodyItem], CitryContext, Any]:
    """Prepare a child component reached at a ``<c-child>`` tag during the walk."""
    deferred = component_node.render(context)
    return _prepare_element(deferred.element, context.component, deferred.provides)


def real_render(element: Any) -> str:
    """Reference: the real engine's resolved render tree, flattened (no markers)."""
    return _flatten_parts(element.render().parts)


def _drive_element(element: Any, parent: Any, provides: Any) -> str:
    """Drive one component (a root element or a deferred child) in Rust."""
    body, context, plan = _prepare_element(element, parent, provides)
    return plan.render(
        body,
        context.variables,
        context,
        select_if_branch,
        for_iterations,
        prepare_component,
        render_foreign,
    )


def _resolve_part(part: Any) -> str:
    """
    Resolve a render part to a string with no serialize-time markers.

    A string passes through, a nested ``CitryRender`` flattens recursively, and a
    ``DeferredComponent`` (a nested component inside slot content) is driven
    through the same Rust walk. This is what lets a fill body that contains a
    ``<c-child>`` render correctly.
    """
    if isinstance(part, str):
        return part
    if isinstance(part, CitryRender):
        return "".join(_resolve_part(p) for p in part.parts)
    if isinstance(part, DeferredComponent):
        return _drive_element(part.element, part.parent, part.provides)
    return str(part)


def render_foreign(node: Any, context: CitryContext) -> str:
    """
    Render a node kind the Rust walk does not model and resolve it to a string.

    This is the slot/fill path: the real ``SlotNode.render`` does the fill lookup
    and the writer-scope render (the part that genuinely cannot leave Python), and
    we flatten or drive its result. It also covers other foreign nodes (a
    nested-template attribute, ...), which simply return strings.
    """
    return _resolve_part(node.render(context))


def rust_drive(element: Any) -> str:
    """Drive the whole component tree from the root with the Rust executor."""
    return _drive_element(element, None, None)


def _py_walk(node_list: list[BodyItem], context: CitryContext) -> str:
    """A Python mirror of the Rust walk, for an all-Python timing baseline."""
    parts: list[str] = []
    for item in node_list:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, _nodes.ComponentNode):
            body, child_ctx, _ = prepare_component(item, context)
            parts.append(_py_walk(body, child_ctx))
        elif isinstance(item, _nodes.IfNode):
            branch = select_if_branch(item, context)
            if branch >= 0:
                parts.append(_py_walk(item.branches[branch][2], context))
        elif isinstance(item, _nodes.ForNode):
            loop_contexts, empty_context = for_iterations(item, context)
            if loop_contexts:
                loop_body = item.branches[0][2]
                for child in loop_contexts:
                    parts.append(_py_walk(loop_body, child))
            elif empty_context is not None:
                parts.append(_py_walk(item.branches[1][2], empty_context))
        else:
            parts.append(render_foreign(item, context))
    return "".join(parts)


def python_drive(element: Any) -> str:
    """Drive the whole component tree from the root with the Python mirror walk."""
    body, context, _plan = prepare_root(element)
    return _py_walk(body, context)
