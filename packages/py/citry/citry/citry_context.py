"""
CitryContext - the render-scoped state threaded through one render.

A CitryContext is created at the start of a component's render and passed down
as the template body is walked. It carries the two distinct kinds of state that
flow through a render, kept separate on purpose (see docs/design/rendering.md):

1. ``variables`` - the per-component template variables (the ``template_data``
   output). These do NOT cross a component boundary: a child component gets
   fresh variables from its own ``template_data``, not the parent's.
2. ``extra`` - a tree-wide scratch space for extensions. Extensions stash
   data here during the render, and it is merged from a child's context into
   the parent's (via the ``on_render_context_merge`` hook) when the child's
   ``CitryRender`` is consumed, so data can bubble up across component
   boundaries. Because ``extra`` is shared by everything in the render,
   **its top-level keys are namespaced by owner**: each extension uses a key
   named after itself (the built-in dependencies extension uses
   ``extra["dependencies"]``), and citry-core concepts that more than one
   party may contribute to live under ``extra["citry"]`` (see
   ``EXTRA_CITRY_KEY`` and ``_add_root_markers`` below).
3. ``provides`` - the provide/inject entries active at this point of the
   render (see docs/design/provide.md). Unlike ``extra``, this data only
   flows DOWN, never back up: a component hands it to its children, and a
   ``<c-slot>`` hands it into the slot content it renders. The mapping is
   treated as read-only: a component that provides builds a new mapping with
   its additions instead of changing this one, so contexts can share it
   freely.

``ComponentNode`` is the boundary: each component render gets its own
CitryContext.

Named ``CitryContext`` to keep it clearly distinct from Django's ``Context``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from citry.component import Component

# Namespace for citry-core data inside ``extra``. The ``extra`` bag is shared
# across the whole render tree, so top-level keys are namespaced by owner to
# avoid collisions: each extension uses its own name, and citry-core concepts
# that several parties may contribute to live under this key. The root-marker
# seam (``_add_root_markers``) is the first of these.
EXTRA_CITRY_KEY: Final = "citry"

# Sub-key under ``extra[EXTRA_CITRY_KEY]`` holding the extra root-element
# marker attributes. Read/written through ``_add_root_markers`` /
# ``_get_root_markers``, not directly.
_ROOT_MARKERS_KEY: Final = "root_markers"


class CitryContext:
    """
    Render-scoped state for a single component render.

    Attributes:
        variables: The per-component template variables (the ``template_data``
            output). Read by nodes when evaluating expressions.
        component: The ``Component`` instance currently rendering. Gives a node
            access to the component tree (its ``citry`` registry for resolving
            child component names, and its ``parent``/``root`` linkage). The
            current component is stored on the context, so each component render
            gets its own ``CitryContext``.
        extra: Tree-wide scratch space for extensions (for example the
            collected JS/CSS dependency records). Top-level keys are
            namespaced by owner; see the module docstring.
        provides: The provide/inject entries (key -> immutable payload)
            active at this point of the render. Read-only by convention;
            ``Component.provide`` builds a new mapping rather than mutating
            this one.

    """

    __slots__ = ("component", "extra", "provides", "sandboxed", "variables")

    def __init__(
        self,
        variables: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        component: Component | None = None,
        provides: dict[str, Any] | None = None,
        sandboxed: bool = True,
    ) -> None:
        self.variables = variables if variables is not None else {}
        self.extra = extra if extra is not None else {}
        self.component = component
        self.provides = provides if provides is not None else {}
        # Whether expressions evaluated in this context use the security sandbox.
        self.sandboxed = sandboxed

    def _add_root_markers(self, markers: Iterable[str]) -> None:
        """
        Add extra HTML attributes to this component's root element(s).

        Internal: the contribution side of the root-marker seam, used by the
        built-in dependencies extension and the serializer. Not public API
        (the exact storage may change); an external extension that needs it
        should treat it as unstable.

        Serialization splices these next to the ``data-cid-<id>`` marker on
        the component's root element(s); for example the dependencies
        extension adds a ``data-ccss-<hash>`` attribute so a CSS-variables
        stylesheet can scope its custom properties to the component.

        Per-component state: call it on the component's own context. It is
        not merged across component boundaries. Stored under the citry-core
        ``extra`` namespace (``EXTRA_CITRY_KEY``), so it never collides with
        an extension's own ``extra`` entries.
        """
        citry_extra: dict[str, Any] = self.extra.setdefault(EXTRA_CITRY_KEY, {})
        citry_extra.setdefault(_ROOT_MARKERS_KEY, []).extend(markers)

    def _get_root_markers(self) -> list[str]:
        """The extra root-element markers added via ``_add_root_markers`` (serialization reads this). Internal."""
        citry_extra: dict[str, Any] = self.extra.get(EXTRA_CITRY_KEY, {})
        return citry_extra.get(_ROOT_MARKERS_KEY, [])

    def __repr__(self) -> str:
        return f"CitryContext(variables={list(self.variables)}, extra={list(self.extra)})"
