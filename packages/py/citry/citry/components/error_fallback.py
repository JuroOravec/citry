"""
The ``<c-error-fallback>`` built-in component.

An error boundary, like React's ErrorBoundary: wraps content that might fail
to render, and shows fallback content instead of letting the error escape::

    <c-error-fallback fallback="Oops, something went wrong">
      <c-user-table />
    </c-error-fallback>

If ``<c-user-table>`` renders fine, it is shown as-is. If anything inside it
raises while rendering, the fallback text is shown in its place and the rest
of the page renders normally.

For richer fallback content, fill the ``fallback`` slot instead of passing
the attribute. The fill receives the error as slot data. As always, fills
cannot mix with other content, so the guarded content then goes into the
``default`` fill::

    <c-error-fallback>
      <c-fill name="default">
        <c-user-table />
      </c-fill>
      <c-fill name="fallback" data="d">
        <p>Oops: {{ d["error"] }}</p>
      </c-fill>
    </c-error-fallback>

Giving both the attribute and the fill is an error. With neither, the
boundary renders nothing when the content fails. Errors raised by the
fallback content itself are not caught here; they continue to the next
boundary up, which is the right behavior for nested boundaries.

The whole behavior is the ``on_render`` generator hook
(docs/design/on_render.md sections 3.2 and 7): the yield receives the
rendered content or the error, and returning fallback content swallows the
error.

Each ``Citry`` instance gets its own subclass of the component, created
lazily by ``make_builtin_components`` (a Component class binds to one Citry
instance at class-definition time, so the built-in cannot be shared).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from citry.component import Component

if TYPE_CHECKING:
    from citry.citry import Citry
    from citry.citry_render import OnRenderGenerator, RenderReplacement
    from citry.slots import SlotInput


def make_error_fallback_component(citry_instance: Citry) -> type[Component]:
    """Create (and thereby register) the ``<c-error-fallback>`` component for one Citry instance."""

    class ErrorFallback(Component):
        """
        Catch render errors in the wrapped content and show fallback content instead.

        The guarded content is the tag body (the default slot). The fallback
        is the ``fallback`` attribute (a string), or the ``fallback`` fill,
        which receives the error as slot data (``data["error"]``).
        """

        citry = citry_instance
        name = "error-fallback"
        template = "<c-slot />"

        class Kwargs:
            fallback: str | None = None

        class Slots:
            default: SlotInput | None = None
            fallback: SlotInput | None = None

        def on_render(self) -> OnRenderGenerator:
            fallback_text = self.kwargs.fallback
            fallback_slot = self.raw_slots.get("fallback")
            if fallback_text is not None and fallback_slot is not None:
                msg = "<c-error-fallback> got both the 'fallback' attribute and a 'fallback' fill; give only one."
                raise RuntimeError(msg)

            _result, error = yield None
            if error is None:
                # The content rendered fine; keep it.
                return None

            if fallback_slot is not None:
                # The fill sees the error as slot data, and inherits the
                # provide/inject entries active around this boundary. The
                # invoked slot returns a str or a CitryRender (the cast
                # narrows away the broader part type).
                part = fallback_slot({"error": error}, provides=self._provides_inherited)
                return cast("RenderReplacement", part)
            return fallback_text if fallback_text is not None else ""

    return ErrorFallback
