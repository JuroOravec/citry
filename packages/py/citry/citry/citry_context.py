"""
CitryContext - the render-scoped state threaded through one render.

A CitryContext is created at the start of a component's render and passed down
as the template body is walked. It carries the two distinct kinds of state that
flow through a render, kept separate on purpose (see docs/design/rendering.md):

1. ``variables`` - the per-component template variables (the ``template_data``
   output). These do NOT cross a component boundary: a child component gets
   fresh variables from its own ``template_data``, not the parent's.
2. ``extra`` - a tree-wide scratch space for extensions. Extensions (for
   example the future JS/CSS dependency extension) stash data here during the
   render; that data is meant to bubble up across component boundaries.

``ComponentNode`` is the boundary: each component render gets its own
CitryContext. The tree-wide ``extra`` data is merged from a child's context
into the parent's when the child's ``CitryRender`` is consumed. That merge is
not implemented yet (no extensions populate ``extra`` in this skeleton); it is
the documented seam for the dependency flow.

Named ``CitryContext`` to keep it clearly distinct from Django's ``Context``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from citry.component import Component


class CitryContext:
    """
    Render-scoped state for a single component render.

    Attributes:
        variables: The per-component template variables (the ``template_data``
            output). Read by nodes when evaluating expressions.
        component: The ``Component`` instance currently rendering. Gives a node
            access to the component tree (its ``citry`` registry for resolving
            child component names, and its ``parent``/``root`` linkage). Per the
            decision in docs/design/rendering.md section 4.1, the current
            component is stored on the context, so each component render gets its
            own ``CitryContext``.
        extra: Tree-wide scratch space for extensions (for example collected
            JS/CSS dependencies). Empty in this skeleton.

    """

    __slots__ = ("component", "extra", "variables")

    def __init__(
        self,
        variables: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        component: Component | None = None,
    ) -> None:
        self.variables = variables if variables is not None else {}
        self.extra = extra if extra is not None else {}
        self.component = component

    def __repr__(self) -> str:
        return f"CitryContext(variables={list(self.variables)}, extra={list(self.extra)})"
