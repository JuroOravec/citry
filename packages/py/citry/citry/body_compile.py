"""
Turn a component's render body into a Python function that produces its output.

This is an optimisation to squeeze out ~3% of the total render time
(measured on a large template with many components).

A render body is the list of static strings and nodes a template compiles to
(after ``constness.precompute_const_parts`` has computed the parts that depend only on
constant inputs). Citry could render it by walking that list every render,
calling ``node.render(context)`` on each node, the way Django walks its node
tree. Instead, this module generates, once per body, a Python function that
produces the body's output directly: a static string becomes a literal
``parts.append("...")``, a ``<c-if>``/``<c-for>`` becomes a real Python
``if``/``for``, and a ``{{ expr }}`` becomes an inline "evaluate, then append".
Running that function is the whole render: there is no list left to walk and no
per-node method call. (This is what makes an engine like Jinja2 fast: the
template becomes ordinary compiled code, instead of a tree something else
interprets.)

Two things this must not change, and does not:

- **Constant parts stay precomputed.** The input is the body *after*
  ``precompute_const_parts`` ran, so the parts that depend only on constant inputs are
  already plain strings before this runs. Nothing here recomputes them.
- **Component nesting stays unbounded.** A ``<c-child>`` is handed to its
  ``ComponentNode.render``, which returns a ``DeferredComponent`` (it does not
  render the child). The generated function returns the same
  ``list[RenderPart]`` walking the body would, so ``render_impl`` renders
  children through its own queue, never by Python recursion (so there is no
  recursion-depth limit on how deeply components nest).

The cheap, mechanical nodes become inline code right here (static text,
``<c-if>``, ``<c-for>``, ``{{ expr }}``). The rest are left to their own
``render`` method, in two groups:

- A ``<c-slot>``'s fallback, a ``<c-fill>``, a component's default content, and
  a nested template each render a body of their own. Those render methods
  generate a function for that body the same way (``render_function_for``), so
  the whole tree ends up as generated functions, not walked, just reached one
  ``render`` call at a time.
- Element attributes and ``<c-child>`` components have no body to generate from:
  attribute work (resolve/escape/evaluate) is intrinsic and moving it inline
  removes nothing (measured: no speed-up on attribute-heavy bodies), and a child
  component is rendered later from a queue (its own body is generated at its own
  build site). Both stay with their ``render`` method.

See ``docs/design/performance.md`` section 6.10.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from citry.citry_context import CitryContext
from citry.citry_render import CitryRender, _render_value
from citry.component_render import _attach_template_position, _merge_dependencies
from citry.nodes import ExprHtmlAttr, ExprNode, ForNode, IfNode, _find_attr
from citry_core.safe_eval import compile_expr

if TYPE_CHECKING:
    from collections.abc import Callable

    from citry.citry_render import RenderPart


def compile_body(body: list[Any], *, sandboxed: bool) -> Callable[[CitryContext], list[RenderPart]]:
    """
    Build the render function for ``body``: ``func(context) -> list[RenderPart]``.

    ``body`` is the list of static strings and nodes after ``precompute_const_parts`` (its
    parts that depend only on constant inputs already computed). ``sandboxed``
    selects the expression-evaluation mode (the instance's ``sandbox_expressions``
    setting), matching what a node would use, so the output is identical to
    walking the body.
    """
    evals: list[Callable[[Any], Any]] = []
    nodes: list[Any] = []
    iters: list[Callable[[Any], Any]] = []
    lines: list[str] = []
    counter = [0]

    def fresh(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix}{counter[0]}"

    def emit_value_and_append(ctxv: str, ind: int, ni: int, value_expr: str) -> None:
        # The value-then-append sequence shared by ExprNode and delegated nodes.
        # `_cur` records the node so a raise can attach its template position; the
        # isinstance guard copies dependencies out of a foreign CitryRender (the
        # same check _render_body does). For `{{ item.value }}` it generates:
        #     _cur = _N[3]
        #     _x = _RV(_E[1](ctx.variables), provides=ctx.provides)
        #     if isinstance(_x, _CR) and _x.context is not ctx: _MD(ctx, _x.context)
        #     _p.append(_x)
        # and for a delegated node `_x = _N[5].render(ctx)` takes the second line.
        pad = "    " * ind
        lines.append(f"{pad}_cur = _N[{ni}]")
        lines.append(f"{pad}_x = {value_expr}")
        lines.append(f"{pad}if isinstance(_x, _CR) and _x.context is not {ctxv}: _MD({ctxv}, _x.context)")
        lines.append(f"{pad}_p.append(_x)")

    def emit_if(ni: int, branches: tuple, ctxv: str, ind: int) -> None:
        # `<c-if cond="a">A</c-if><c-elif cond="b">B</c-elif><c-else>C</c-else>`
        # becomes a real Python if/else chain (each later branch nested in the
        # previous else, so its cond evaluates only when reached):
        #     _cur = _N[2]
        #     _if1 = _E[0](ctx.variables)
        #     if _if1:
        #         <A>
        #     else:
        #         _cur = _N[2]
        #         _if2 = _E[1](ctx.variables)
        #         if _if2:
        #             <B>
        #         else:        # the <c-else>; absent -> no else, so nothing renders
        #             <C>
        pad = "    " * ind
        branch = branches[0]
        cond = _find_attr(branch[1], "cond")
        if cond is None:  # a bare <c-else> (or the else branch): always render
            before = len(lines)
            emit(branch[2], ctxv, ind)
            if len(lines) == before:
                lines.append(f"{pad}pass")
            return
        # A `cond` attribute (c-if/c-elif) is always an expression, never the
        # value-less boolean attribute form, so `.expr` is a str here.
        evals.append(compile_expr(cast("str", cast("ExprHtmlAttr", cond).expr), sandboxed=sandboxed))
        ei = len(evals) - 1
        tmp = fresh("_if")
        lines.append(f"{pad}_cur = _N[{ni}]")
        lines.append(f"{pad}{tmp} = _E[{ei}]({ctxv}.variables)")
        lines.append(f"{pad}if {tmp}:")
        before = len(lines)
        emit(branch[2], ctxv, ind + 1)
        if len(lines) == before:
            lines.append(f"{pad}    pass")
        rest = branches[1:]
        if rest:
            lines.append(f"{pad}else:")
            emit_if(ni, rest, ctxv, ind + 1)

    def emit_for(node: ForNode, ctxv: str, ind: int) -> None:
        # `<c-for each="x in xs">B</c-for><c-empty>E</c-empty>` becomes a real
        # Python for loop. Each iteration builds a child context that overlays the
        # loop targets on the parent's variables; the body renders against it. A
        # counter drives the optional <c-empty> branch:
        #     _cur = _N[4]
        #     _c1 = 0
        #     for _v1 in _IT[0](ctx.variables):
        #         _c1 += 1
        #         _cc1 = _CC(variables={**ctx.variables, **dict(zip(('x',), _v1))}, extra=ctx.extra, ...)
        #         <B, rendered with _cc1 as the context>
        #     if _c1 == 0:
        #         <E>
        pad = "    " * ind
        nodes.append(node)
        ni = len(nodes) - 1
        for_branch = node.branches[0]
        targets = tuple(for_branch[3])
        each = cast("ExprHtmlAttr", _find_attr(for_branch[1], "each"))
        iters.append(compile_expr(f"(({', '.join(targets)},) for {each.expr})", sandboxed=sandboxed))
        ii = len(iters) - 1
        cnt, val, cctx = fresh("_c"), fresh("_v"), fresh("_cc")
        lines.append(f"{pad}_cur = _N[{ni}]")
        lines.append(f"{pad}{cnt} = 0")
        lines.append(f"{pad}for {val} in _IT[{ii}]({ctxv}.variables):")
        lines.append(f"{pad}    {cnt} += 1")
        lines.append(
            f"{pad}    {cctx} = _CC(variables={{**{ctxv}.variables, **dict(zip({targets!r}, {val}))}}, "
            f"extra={ctxv}.extra, component={ctxv}.component, provides={ctxv}.provides, sandboxed={ctxv}.sandboxed)"
        )
        before = len(lines)
        emit(for_branch[2], cctx, ind + 1)
        if len(lines) == before:
            lines.append(f"{pad}    pass")
        if len(node.branches) > 1:  # the optional <c-empty> branch
            lines.append(f"{pad}if {cnt} == 0:")
            before = len(lines)
            emit(node.branches[1][2], ctxv, ind + 1)
            if len(lines) == before:
                lines.append(f"{pad}    pass")

    def emit(items: list[Any], ctxv: str, ind: int) -> None:
        pad = "    " * ind
        for item in items:
            if isinstance(item, str):
                # Static text: a literal append, no escaping (it is already HTML).
                #     _p.append('<div class="x">')
                lines.append(f"{pad}_p.append({item!r})")
            elif isinstance(item, ExprNode):
                # `{{ expr }}`: evaluate the precompiled expression, run it through
                # _render_value (escape / inline a nested render / drop None), append.
                #     _x = _RV(_E[1](ctx.variables), provides=ctx.provides)  # (+ _cur/merge/append)
                nodes.append(item)
                ni = len(nodes) - 1
                evals.append(compile_expr(item.expr, sandboxed=sandboxed))
                ei = len(evals) - 1
                emit_value_and_append(ctxv, ind, ni, f"_RV(_E[{ei}]({ctxv}.variables), provides={ctxv}.provides)")
            elif isinstance(item, IfNode):
                # `<c-if>/<c-elif>/<c-else>` -> an inlined Python if/else chain (emit_if).
                nodes.append(item)
                emit_if(len(nodes) - 1, item.branches, ctxv, ind)
            elif isinstance(item, ForNode):
                # `<c-for>/<c-empty>` -> an inlined Python for loop + empty guard (emit_for).
                emit_for(item, ctxv, ind)
            else:
                # Delegate the work-heavy nodes to their own render (the resolve /
                # escape / eval cost is intrinsic, so inlining buys nothing): element
                # attributes, components (-> a DeferredComponent), slots, fills,
                # nested-template values, extension-injected nodes.
                #     _x = _N[5].render(ctx)  # (+ _cur/merge/append, see emit_value_and_append)
                nodes.append(item)
                ni = len(nodes) - 1
                emit_value_and_append(ctxv, ind, ni, f"_N[{ni}].render({ctxv})")

    emit(body, "ctx", 2)
    body_src = "\n".join(lines) if lines else "        pass"
    # The emitted lines become the body of one function:
    #     def _render(ctx, _p):
    #         _cur = None
    #         try:
    #             <emitted body: the appends, ifs, and fors above>
    #         except Exception as _err:
    #             if _cur is not None: _ATP(_err, _cur, ctx)
    #             raise
    # `_cur` tracks the node currently executing, so a raise attaches its
    # template position once (the innermost failing node), exactly as the walk's
    # per-node try/except does. A nested walk attaches first and this is a no-op.
    src = (
        "def _render(ctx, _p):\n"
        "    _cur = None\n"
        "    try:\n"
        f"{body_src}\n"
        "    except Exception as _err:\n"
        "        if _cur is not None: _ATP(_err, _cur, ctx)\n"
        "        raise"
    )
    namespace: dict[str, Any] = {
        "_RV": _render_value,
        "_MD": _merge_dependencies,
        "_ATP": _attach_template_position,
        "_CR": CitryRender,
        "_CC": CitryContext,
        "_E": evals,
        "_N": nodes,
        "_IT": iters,
    }
    exec(compile(src, "<citry render body>", "exec"), namespace)  # noqa: S102

    generated = namespace["_render"]

    def render(context: CitryContext) -> list[RenderPart]:
        parts: list[RenderPart] = []
        generated(context, parts)
        return parts

    render.generated_source = src  # type: ignore[attr-defined]  # for inspection/debugging
    return render


def render_function_for(
    holder: object,
    build_body: Callable[[], list[Any]],
    *,
    sandboxed: bool,
) -> Callable[[CitryContext], list[RenderPart]]:
    """
    The render function for a sub-body, generated once and cached on ``holder``.

    A component's top body is generated to a function at its build site, but a
    few nodes render a sub-body of their own: a ``<c-slot>``'s fallback content,
    a ``<c-fill>``'s content, a component's default-slot content, a nested
    template. This generates a function for that body the same way, and caches it
    on ``holder`` (the node that owns the body). The node is the right anchor:
    it lives exactly as long as the body it owns, whereas keying by the body
    itself is unsafe, since the Const cache can drop a body and the next one may
    land at the same identity. ``build_body`` produces the body and is called
    only the first time (later renders return the cached function and do not
    rebuild the body).
    """
    fn = getattr(holder, "_compiled_render", None)
    if fn is None:
        fn = compile_body(build_body(), sandboxed=sandboxed)
        holder._compiled_render = fn  # type: ignore[attr-defined]
    return fn
