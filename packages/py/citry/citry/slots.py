"""
The Slot value: the one normalized form for slot content.

Slot content can be supplied many ways: a ``<c-fill>`` body in a template, the
implicit default-slot body, a plain string, a Python function, an already
composed ``CitryElement``, or an already rendered ``CitryRender``. All of them
normalize to a ``Slot``: a callable that is invoked at the ``<c-slot>`` site
with the slot data and a handle to the slot's fallback content. See
docs/design/slots.md section 3.

A Slot is:

- **Lazy.** Nothing renders until the Slot is called.
- **Repeatable.** The same Slot may be called many times with different data
  (for example a ``<c-slot>`` inside a loop calls its fill once per item).
- **Standalone.** Calling a Slot needs no component or render context::

      slot = Slot(lambda ctx: f"Hello, {ctx.data['name']}!")
      slot({"name": "John"})   # 'Hello, John!'

The slot's fallback content is itself a ``Slot`` (``SlotContext.fallback``),
not a separate type, so ``{{ fallback }}`` in a fill body renders through the
same path as any other slot value.

Escaping: a plain string (or scalar) is escaped when the Slot is constructed;
a function's return value is escaped when the Slot is called. A
``SafeString``, ``CitryElement``, or ``CitryRender`` result is trusted and is
not escaped. This matches how ``{{ expr }}`` results are escaped.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeAlias, TypeVar

from citry.citry_element import CitryElement
from citry.util.html import SafeString, escape

if TYPE_CHECKING:
    from citry.citry_render import CitryRender, RenderPart

TSlotData = TypeVar("TSlotData", bound=Mapping)

SlotName: TypeAlias = str

SlotResult: TypeAlias = "str | SafeString | CitryRender"
"""
What a slot function may return.

A plain ``str`` is escaped when the slot renders; a ``SafeString`` or
``CitryRender`` is trusted and inlined as-is.
"""


@dataclass(frozen=True)
class SlotContext(Generic[TSlotData]):
    """
    The single argument a slot function receives.

    Example:
        ::

            def my_slot(ctx: SlotContext) -> str:
                return f"Hello, {ctx.data['name']}!"

    """

    data: TSlotData
    """
    Data passed to the slot by the ``<c-slot>`` tag (its extra attributes), or
    by the caller when the Slot is invoked directly. An empty mapping when no
    data was given.
    """

    fallback: Slot | None = None
    """
    The slot's fallback content (the body of the ``<c-slot>`` tag), as a Slot.

    ``None`` when the Slot is called directly, outside a ``<c-slot>`` site.
    Coerce it to a string (or render it via ``{{ fallback }}``) to render the
    fallback.
    """

    provides: Mapping[str, Any] | None = None
    """
    The provide/inject entries active where the Slot was invoked (the
    ``<c-slot>`` site or expression site). ``None`` when the Slot is called
    directly, outside a render. Template-defined fills use this so their
    bodies render with the invoking site's provides; a slot function may read
    it to inspect provided data. See docs/design/provide.md section 4.3.
    """


class SlotFunc(Protocol[TSlotData]):
    """
    The signature of a slot content function.

    Example:
        ::

            def header(ctx: SlotContext) -> str:
                if ctx.data.get("name"):
                    return f"Hello, {ctx.data['name']}!"
                return str(ctx.fallback)

    """

    # `ctx` is positional-only: the slot machinery always passes it positionally,
    # so implementations may name the parameter anything.
    def __call__(self, ctx: SlotContext[TSlotData], /) -> SlotResult | CitryElement: ...


class Slot(Generic[TSlotData]):
    """
    Normalized slot content: a lazy, repeatable, standalone callable.

    Construct it from a string, a function, a ``CitryElement``, or a
    ``CitryRender``. Calling the Slot returns a render part (a ``str`` or a
    ``CitryRender``); ``str(slot)`` renders and serializes in one step.

    Example:
        ::

            Slot("Hello!")                                # static content
            Slot(lambda ctx: f"Hi {ctx.data['name']}!")   # content function
            Slot(Card(title="Hi"))                        # composed element

    """

    __slots__ = ("component_name", "content_func", "contents", "extra", "slot_name", "source_position")

    def __init__(
        self,
        contents: Any,
        *,
        content_func: SlotFunc[TSlotData] | None = None,
        component_name: str | None = None,
        slot_name: str | None = None,
        source_position: tuple[int, int] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        # A Slot wrapping another Slot is ambiguous (whose metadata wins?), the
        # same rule as django-components. To copy a Slot, construct a new one
        # from its `contents` and `content_func` (see `normalize_slot_fills`).
        if isinstance(contents, Slot):
            msg = "Slot received another Slot instance as `contents`"
            raise TypeError(msg)

        self.contents = contents
        """The original value the Slot was created from."""
        self.component_name = component_name
        """Name of the component this slot content was given to (for debugging)."""
        self.slot_name = slot_name
        """Name of the slot this content fills (for debugging)."""
        self.source_position = source_position
        """The ``(start, end)`` span of the ``<c-fill>`` in its template, if any."""
        self.extra: dict[str, Any] = extra if extra is not None else {}
        """Scratch space for extensions to attach per-slot metadata."""

        if content_func is None:
            content_func = self._resolve_content_func(contents)
        if not callable(content_func):
            msg = f"Slot 'content_func' must be a callable, got: {content_func!r}"
            raise TypeError(msg)
        self.content_func: SlotFunc[TSlotData] = content_func
        """The content function. Call the Slot itself instead of calling this directly."""

    def __call__(
        self,
        data: TSlotData | None = None,
        fallback: Slot | None = None,
        *,
        provides: dict[str, Any] | None = None,
    ) -> RenderPart:
        """
        Render the slot content and return it as a render part.

        The result is a ``str`` (escaped text) or a ``CitryRender`` (a rendered
        subtree, with its collected data intact). Pass ``data`` to expose slot
        data to the content function; pass ``fallback`` to give it access to
        the slot's fallback content. ``provides`` carries the provide/inject
        entries active at the invoking site (set by the ``<c-slot>`` and
        expression machinery); content rendered here inherits them.
        """
        # Imported here, not at module load: citry_render imports Slot (for the
        # `{{ my_slot }}` detection in _render_value), so a top-level import
        # back into it would be circular.
        from citry.citry_render import _render_value  # noqa: PLC0415

        ctx: SlotContext[Any] = SlotContext(
            data=data if data is not None else {},
            fallback=fallback,
            provides=provides,
        )
        result = self.content_func(ctx)
        return _render_value(result, provides=provides)

    def __str__(self) -> str:
        """
        Render with no data and serialize to an HTML string.

        Like ``CitryRender.serialize()``, this is one-shot: the string can no
        longer merge its collected data (JS/CSS dependencies) into another
        tree. Keep the value a Slot for as long as you compose.
        """
        from citry.citry_render import CitryRender  # noqa: PLC0415

        part = self()
        if isinstance(part, CitryRender):
            return part.serialize()
        return str(part)

    def __repr__(self) -> str:
        comp_name = f"'{self.component_name}'" if self.component_name else None
        slot_name = f"'{self.slot_name}'" if self.slot_name else None
        return f"<{type(self).__name__} component_name={comp_name} slot_name={slot_name}>"

    @staticmethod
    def _resolve_content_func(contents: Any) -> SlotFunc[TSlotData]:
        """
        Build the content function for a non-function ``contents`` value.

        - A callable is the content function itself.
        - Anything else becomes a function returning a fixed value: a
          ``CitryElement``/``CitryRender`` is returned as-is (rendered or
          inlined at call time), and any other value is escaped NOW, so unsafe
          text is neutralized as early as possible. ``escape`` respects
          ``__html__``, so a ``SafeString`` stays trusted.
        """
        if callable(contents):
            return contents

        # Imported here, not at module load: citry_render imports this module.
        from citry.citry_render import CitryRender  # noqa: PLC0415

        value: Any = contents if isinstance(contents, (CitryElement, CitryRender)) else escape(contents)

        def render_func(_ctx: SlotContext[TSlotData]) -> Any:
            return value

        return render_func


SlotInput: TypeAlias = "SlotResult | SlotFunc[TSlotData] | Slot[TSlotData] | CitryElement"
"""
All forms in which slot content can be passed to a component.

Use this to type the fields of a component's ``Slots`` class::

    class Table(Component):
        class Slots:
            header: SlotInput
            footer: SlotInput[FooterSlotData]
"""


def normalize_slot_fills(
    fills: Mapping[SlotName, Any],
    component_name: str | None = None,
) -> dict[SlotName, Slot]:
    """
    Normalize a mapping of slot inputs into ``Slot`` instances.

    This is the boundary where Python-passed slots
    (``MyComp(slots={"header": ...})``) become ``Slot`` values:

    - ``None`` values are dropped (same as not passing the slot).
    - A ``Slot`` that already carries its names is kept as-is; one with
      missing names is copied (not mutated) with the names filled in.
    - A function becomes a ``Slot`` around it.
    - Anything else (string, ``SafeString``, ``CitryElement``,
      ``CitryRender``, scalar) becomes a static ``Slot``.
    """
    norm_fills: dict[SlotName, Slot] = {}

    for slot_name, content in fills.items():
        # No content given for this slot.
        if content is None:
            continue

        if isinstance(content, Slot):
            # Already a Slot with its names assigned: keep it.
            if content.slot_name and content.component_name:
                norm_fills[slot_name] = content
                continue
            # Copy the Slot (so the caller's instance is not mutated) and fill
            # in the missing names for tracing.
            norm_fills[slot_name] = Slot(
                content.contents,
                content_func=content.content_func,
                component_name=content.component_name or component_name,
                slot_name=content.slot_name or slot_name,
                source_position=content.source_position,
                extra=dict(content.extra),
            )
            continue

        # A function, or a static value (string, element, render, scalar).
        norm_fills[slot_name] = Slot(
            content,
            component_name=component_name,
            slot_name=slot_name,
        )

    return norm_fills
