"""
CitryRender - the output of rendering a CitryElement.

The rendering pipeline has three phases, each with its own struct (see
docs/design/rendering.md):

    Component(**kwargs)       -> CitryElement   compose: "what to render"
    CitryElement.render()     -> CitryRender    render: parts + collected metadata
    CitryRender.serialize()   -> str (HTML)     serialize: join + place deps

``CitryRender`` is the middle struct, and on purpose it is NOT a string. Keeping
the render output as an object lets an already-rendered piece be reused. You can
pass a ``CitryRender`` to another component (as a kwarg, inside ``{{ ... }}``, or
in an attribute); the component that receives it pulls in its HTML and copies up
its collected data (JS/CSS dependencies). Turning it into a string
(``str()``/``serialize()``) is the final step that produces the HTML. This is the
citry form of django-components #1650 ("cache the render object, not the string").

A ``CitryRender`` holds:

- ``parts``: an ordered list whose items can be different types. Each part is a
  ``str`` (static or already-rendered text) or a nested ``CitryRender`` (a piece
  not yet joined into text). Joining only at the end keeps reuse cheap and keeps
  the dependencies readable until the final serialize.
- ``context``: the ``CitryContext`` used during the render. For now the whole
  context is kept (the collected data lives in its ``extra``); this can be
  narrowed to specific fields once we know what serialize needs.

Serialization joins the parts, stamps the ``data-cid-<id>`` markers, and
places the collected dependencies into the page per the ``deps_strategy`` /
``deps_position`` arguments (docs/design/dependencies.md section 7),
including the ``fragment`` strategy for HTML partials.

Example:
    Render and serialize a component::

        from citry import Component

        class Hello(Component):
            template = "<p>Hello!</p>"

        rendered = Hello().render()      # -> CitryRender
        html = rendered.serialize()      # -> "<p>Hello!</p>"
        assert str(rendered) == html     # str() is a convenience for serialize()

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from citry.citry_element import CitryElement
from citry.constness import const_value
from citry.slots import Slot
from citry.util.html import escape

if TYPE_CHECKING:
    from collections.abc import Generator

    from citry.citry_context import CitryContext
    from citry.component import Component

# One piece of rendered output. It is one of:
#   - str: final text.
#   - CitryRender: a nested render not yet joined into text.
#   - DeferredComponent: a child component not yet rendered (render() renders it
#     before any serialize()).
#   - Placeholder: a spot whose final text an extension supplies at serialize
#     time (the <c-js>/<c-css> built-ins render these).
# A CitryRender's `parts`, and what a node's render() returns, are made of these.
RenderPart: TypeAlias = "str | CitryRender | DeferredComponent | Placeholder"

# How collected JS/CSS dependencies are handled when serializing (see
# CitryRender.serialize and docs/design/dependencies.md section 7.1).
DepsStrategy: TypeAlias = Literal["document", "simple", "fragment", "ignore"]

# Where the dependency tags go for the "document"/"simple" strategies.
DepsPosition: TypeAlias = Literal["smart", "prepend", "append"]

# What ``Component.on_render`` may return to replace the component's whole
# output (docs/design/on_render.md section 3): final text (a ``str``, used
# as-is, not autoescaped), a composed element (rendered in the component's
# place), an already-rendered subtree, or a ``Slot`` (invoked with no data).
# ``None`` is not part of the alias: returning ``None`` means "no
# replacement, render the template as usual".
RenderReplacement: TypeAlias = "str | CitryElement | CitryRender | Slot"

# The shape of ``Component.on_render`` when it contains a ``yield`` (the
# generator form, docs/design/on_render.md section 3.2). The generator yields
# a replacement (or ``None`` for "render my template as usual"), receives
# back ``(result, error)`` once that content has fully settled (children
# included), and may end with ``return <replacement>`` to set the final
# output. Exactly one of ``result`` / ``error`` is set.
OnRenderGenerator: TypeAlias = (
    "Generator[RenderReplacement | None, tuple[CitryRender | None, Exception | None], RenderReplacement | None]"
)


class CitryRender:
    """
    The result of rendering a ``CitryElement`` (the render-phase output).

    Attributes:
        parts: Ordered list of ``str`` or nested ``CitryRender`` fragments.
        context: The ``CitryContext`` used to produce this render.
        is_component_root: True only for the render that is a component's whole
            output (produced by the render pipeline, one per component
            instance). Interior renders (a ``<c-if>``/``<c-for>`` block, a
            nested template, slot-fill content rendered in the enclosing
            scope) are False. Serialization uses this to tell a completed
            child-component subtree (which becomes its own marked frame) from
            content that joins into the surrounding frame; the component on
            the context cannot tell these apart, because slot-fill content
            carries the context of the component that wrote it, not the one
            it renders inside.

    """

    __slots__ = ("context", "is_component_root", "parts")

    def __init__(
        self,
        parts: list[RenderPart],
        context: CitryContext,
        *,
        is_component_root: bool = False,
    ) -> None:
        self.parts = parts
        self.context = context
        self.is_component_root = is_component_root

    def serialize(self, deps_strategy: DepsStrategy = "document", deps_position: DepsPosition = "smart") -> str:
        """
        Turn this render into a final HTML string.

        Each component's root element(s) get a ``data-cid-<id>`` marker so the
        rendered HTML records which component produced which part of the page,
        and the JS/CSS collected from the rendered components is placed into the
        output per the chosen strategy and position.

        Args:
            deps_strategy: How to handle the collected JS/CSS.

                - ``"document"`` (default): emit the tags, plus the
                  client-side dependency manager and the page manifest when
                  any component registered a per-instance callback
                  (``$onComponent``), so ``js_data()`` reaches the browser.
                - ``"simple"``: the tags only, no JavaScript runtime. For
                  static pages and emails; per-instance JS does not run
                  (CSS variables still work, they are pure CSS).
                - ``"fragment"``: HTML meant to be inserted into an
                  already-loaded page (an HTMX swap, ``fetch`` +
                  ``innerHTML``, ...): nothing is inlined; the output ends
                  with a JSON manifest of URLs the client-side manager
                  fetches, each once per page however many fragments need
                  it. Requires a mounted web integration.
                - ``"ignore"``: no tags inserted.
            deps_position: Where the tags go (``document``/``simple`` only).

                - ``"smart"`` (default): into the ``<c-js>``/``<c-css>``
                  placeholders when present, else CSS before the first
                  ``</head>`` and JS before the last ``</body>``, else
                  CSS is prepended and JS appended.
                - ``"prepend"`` / ``"append"``: all tags before/after the
                  whole output.

        Raises ``RuntimeError`` if any child component was left unrendered (a
        ``DeferredComponent`` still in the parts), which can only happen if this
        render did not come from ``render()``.

        """
        # Imported here, not at module load, to avoid an import cycle:
        # serialize.py imports CitryRender from this module.
        from citry.serialize import serialize_render  # noqa: PLC0415

        return serialize_render(self, deps_strategy=deps_strategy, deps_position=deps_position)

    def __str__(self) -> str:
        return self.serialize()

    def __bytes__(self) -> bytes:
        return self.serialize().encode()

    def __repr__(self) -> str:
        return f"CitryRender(parts={len(self.parts)})"


class Placeholder:
    """
    A spot in the output whose final text is supplied at serialize time.

    Rendered output is normally text and nested renders, fixed once rendered.
    A Placeholder marks a position whose content is only known when the whole
    page is serialized: the ``<c-js>`` / ``<c-css>`` built-ins render one
    each, and the dependencies extension fills them with the collected
    script/style tags via the ``on_serialize`` hook.

    Attributes:
        key: What belongs at this spot (e.g. ``"deps:js"``). The serializer
            reports each occurrence to the ``on_serialize`` hook under this
            key plus a counter, and an extension that knows the key supplies
            the text; an occurrence no extension fills serializes to nothing.

    """

    __slots__ = ("key",)

    def __init__(self, key: str) -> None:
        self.key = key

    def __repr__(self) -> str:
        return f"Placeholder({self.key!r})"


class DeferredComponent:
    """
    A child component that has not been rendered yet.

    When the parent's template reaches a ``<c-child>`` tag, citry does not render
    the child right there. Doing so would mean one component renders the next,
    which renders the next, so a deeply nested page would hit Python's recursion
    limit. Instead the parent records the child as a ``DeferredComponent`` (with
    its inputs already worked out) and carries on. ``render_impl`` later renders
    the recorded children one at a time, swapping each ``DeferredComponent`` for
    the child's ``CitryRender``. See docs/design/deferred_rendering.md section 4.

    Attributes:
        element: The child to render: its component class plus the inputs
            (kwargs/slots), already worked out. The inputs are read while the
            parent is still rendering, so a loop variable from an enclosing
            ``<c-for>`` keeps the right value.
        parent: The parent ``Component`` instance. Used to set the child's
            ``parent``/``root`` links when it is rendered.
        provides: The provide/inject entries active where the ``<c-child>``
            tag sits, read while the parent is still rendering, at the same
            time as the kwargs (see docs/design/provide.md section 4.2). The
            child inherits these when the queue renders it.

    """

    __slots__ = ("element", "parent", "provides")

    def __init__(
        self,
        element: CitryElement,
        parent: Component,
        provides: dict[str, Any] | None = None,
    ) -> None:
        self.element = element
        self.parent = parent
        self.provides = provides if provides is not None else {}

    def __repr__(self) -> str:
        return f"DeferredComponent({self.element!r})"


def _render_value(value: Any, provides: dict[str, Any] | None = None) -> RenderPart:
    """
    Convert an evaluated expression value into a body part.

    This is the bridge from an arbitrary Python value (the result of evaluating
    a ``{{ ... }}`` expression, or a value handed into an attribute) to a
    ``RenderPart``. The rules (see docs/design/rendering.md section 3.1 and
    docs/design/slots.md section 3.5):

    - ``None`` renders as the empty string (not the literal ``"None"``).
    - A ``Slot`` is invoked with no data, so ``{{ my_slot }}`` renders slot
      content in place. (Calling it with data, ``{{ my_slot(d) }}``, also lands
      here: the call already produced a render part, handled by the rules
      below.) The slot's fallback handle is a Slot too, so ``{{ fallback }}``
      renders through this same branch.
    - A ``CitryElement`` (a composed-but-unrendered element handed into an
      expression) is rendered now, so its output and dependencies flow into the
      surrounding tree.
    - A ``CitryRender`` (an already-rendered subtree) is inlined as-is; it is
      trusted HTML, and the surrounding ``_render_body`` merges its dependencies.
    - Anything else is autoescaped. ``escape`` respects the ``__html__``
      protocol, so a ``SafeString`` (trusted HTML) passes through unescaped.

    ``provides`` are the provide/inject entries active where the value was
    found; an element rendered here inherits them, so a component embedded
    via ``{{ element }}`` or slot content can ``inject`` what its render site
    provides (docs/design/provide.md section 4.4).

    A ``Const`` marker is unwrapped first: the value is becoming output here,
    so the marker has no further role, and the identity check below
    (``value is None``) must see the real value, not the proxy.
    """
    value = const_value(value)
    if value is None:
        return ""
    if isinstance(value, Slot):
        return value(provides=provides)
    if isinstance(value, CitryElement):
        # Imported here, not at module load: component_render imports this
        # module, so a top-level import back into it would be circular.
        from citry.component_render import render_impl  # noqa: PLC0415

        value = render_impl(value, provides=provides)
    if isinstance(value, CitryRender):
        return value
    return escape(value)
