"""
CitryRender - the output of rendering a CitryElement.

The rendering pipeline has three phases, each with its own struct (see
docs/design/rendering.md):

    Component(**kwargs)       -> CitryElement   compose: "what to render"
    CitryElement.render()     -> CitryRender    render: parts + collected metadata
    CitryRender.serialize()   -> str (HTML)     serialize: join + place deps

``CitryRender`` is the middle struct. It is deliberately NOT a string: keeping
the render output as an object is what lets a pre-rendered subtree stay
composable. A ``CitryRender`` can be handed to another component (as a kwarg,
inside ``{{ ... }}``, or in an attribute); the consuming tree detects it,
merges its collected metadata (JS/CSS deps) upward, and inlines its HTML. Only
coercing to a string (``str()``/``serialize()``) collapses it to final HTML.
This is the citry form of django-components #1650 ("cache the render object,
not the string").

A ``CitryRender`` holds:

- ``parts``: an ordered, heterogeneous list. Each part is either a ``str``
  (static or already-serialized text) or a nested ``CitryRender`` (an embedded
  subtree not yet joined). Deferring the join keeps embedding cheap and keeps
  the deps recoverable until the final serialize.
- ``context``: the ``CitryContext`` used during the render. For now the whole
  context is kept (the collected metadata lives in its ``extra``); this can be
  narrowed to specific fields once serialization needs are known.

Serialization is currently just the recursive join of the parts. Placing
collected dependencies into ``<head>``/``<body>`` (document mode) and the
fragment-mode and injection-strategy choices are future work (see
docs/design/rendering.md sections 5-6).

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

from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from citry.citry_context import CitryContext

# A single piece of rendered output: either final text, or a nested CitryRender
# (an embedded subtree whose serialization is deferred). A CitryRender's parts
# and a node's render() result are both made of these.
RenderPart: TypeAlias = "str | CitryRender"


class CitryRender:
    """
    The result of rendering a ``CitryElement`` (the render-phase output).

    Attributes:
        parts: Ordered list of ``str`` or nested ``CitryRender`` fragments.
        context: The ``CitryContext`` used to produce this render.

    """

    __slots__ = ("context", "parts")

    def __init__(self, parts: list[RenderPart], context: CitryContext) -> None:
        self.parts = parts
        self.context = context

    def serialize(self) -> str:
        """
        Join the parts into a final HTML string.

        Nested ``CitryRender`` parts are serialized recursively. Placement of
        collected dependencies (head/body) and serialization strategies
        (document vs fragment mode) are not implemented yet; see
        docs/design/rendering.md.
        """
        out: list[str] = []
        for part in self.parts:
            out.append(part.serialize() if isinstance(part, CitryRender) else part)
        return "".join(out)

    def __str__(self) -> str:
        return self.serialize()

    def __bytes__(self) -> bytes:
        return self.serialize().encode()

    def __repr__(self) -> str:
        return f"CitryRender(parts={len(self.parts)})"
