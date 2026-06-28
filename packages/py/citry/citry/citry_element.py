"""
CitryElement - the intermediate representation returned by Component().

When a user writes ``MyCard(title="Hello")``, they get back a
CitryElement, not a rendered string and not a Component instance.
The CitryElement holds the component class, kwargs, and slots,
and can be rendered later with ``.render()`` or ``str()``.

This is analogous to React's RenderElement. The split between
composition (creating the CitryElement) and rendering (calling
``.render()``) enables:

- Caching the CitryElement instead of a finished string (solves
  the frozen-ID and lost-variables problems from DJC #1650).
- Passing render objects as values to other components or slots.
- Different render targets (HTML string, streaming, etc.).
- The render pipeline minting fresh per-instance state (render_id,
  JS/CSS variables) on each ``.render()`` call.

Example:
    Compose a component tree without rendering::

        from citry import Component

        class Card(Component):
            template = '<div class="card">{{ title }}</div>'

        class Page(Component):
            template = '<main>{{ content }}</main>'

        # Composition phase - no rendering happens yet
        card = Card(title="Hello")
        page = Page(content=card)

        # Rendering phase - produces a CitryRender, then serialize to HTML
        rendered = page.render()        # -> CitryRender
        html = rendered.serialize()     # -> str
        # Or in one step with defaults: html = str(page)

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from citry.citry_render import CitryRender
    from citry.component import Component


class CitryElement:
    """
    Intermediate representation of a component invocation.

    Created by ``Component()``. Holds the component class and the
    kwargs/slots that were passed. Rendering is deferred until
    ``.render()`` is called.

    Attributes:
        comp_cls: The Component subclass to render.
        kwargs: The keyword arguments passed to the component.
        slots: The slot fills passed to the component. Filled from either
            channel: the reserved ``slots=`` kwarg when composing from Python
            (``MyComp(title="x", slots={...})``), or the collected ``<c-fill>``
            tags / implicit default body when composed by a parent template.
            Values are raw inputs here (strings, functions, elements, Slots);
            they normalize to ``Slot`` instances when the component instance is
            created at render time.

    """

    __slots__ = ("comp_cls", "kwargs", "slots")

    def __init__(
        self,
        comp_cls: type[Component],
        kwargs: dict[str, Any],
        slots: dict[str, Any] | None = None,
    ) -> None:
        self.comp_cls = comp_cls
        self.kwargs = kwargs
        self.slots = slots or {}

    def render(self, *, template_globals: Mapping[str, Any] | None = None) -> CitryRender:
        """
        Render this component into a ``CitryRender``.

        Each call mints fresh per-instance state (render_id, etc.), so the same
        CitryElement can be rendered multiple times with distinct identities.

        ``template_globals`` adds or overrides template variables for this one
        render, layered on top of the instance's ``citry.template_globals`` and
        under each component's own ``template_data``. They reach every component
        in the render, including nested children, embedded elements, and slot
        content, which suits per-request values (the current user, a request id)
        that should not be stored on the shared instance.

        Returns a ``CitryRender`` (the render-phase output), not a string. Call
        ``.serialize()`` on it (or ``str()``) to get the HTML. ``str()`` on the
        element itself runs the full chain with sensible defaults (and no
        ``template_globals``).
        """
        # Imported lazily to break the import cycle: component_render imports the
        # node classes, the nodes import CitryElement (for auto-rendering a
        # composed element found in an expression), so CitryElement must not pull
        # in component_render at module load.
        from citry.component_render import render_impl  # noqa: PLC0415

        return render_impl(self, render_globals=dict(template_globals) if template_globals is not None else None)

    def __str__(self) -> str:
        # Convenience: str(element) runs the full pipeline
        # (render -> serialize) with default options.
        return str(self.render())

    def __repr__(self) -> str:
        cls_name = self.comp_cls.__name__
        kwargs_str = ", ".join(f"{k}={v!r}" for k, v in self.kwargs.items())
        return f"{cls_name}({kwargs_str})"
