"""
CitryTemplate - the loaded template of a component class.

A ``CitryTemplate`` is what the asset loader produces from a component's
``template`` / ``template_file`` declaration: the template string plus where it
came from. It completes the ``Citry``-prefixed struct family
(``CitryElement`` for composition, ``CitryRender`` for render output,
``CitryContext`` for render state): this one belongs to the loading phase.

The struct also carries the template's compiled form (the body-generating
function plus parse-time metadata), filled in lazily by the render pipeline on
the first render. Loaded source and compiled form share one lifecycle, so they
live on one object with one per-class cache and one invalidation
(``Component.reset_template()``). The compile *code* stays in
``component_render.py``; it writes into this struct. See
docs/design/asset_loading.md section 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from citry.nodes import BodyItem


class DeclaredSlot(NamedTuple):
    """
    A ``<c-slot>`` the template declares, kept for checking the component's own
    template against its ``Slots`` schema (see docs/design/slots.md section 9.5):
    the static slot name and its (line, column) for error messages.
    """

    name: str
    line: int
    col: int


@dataclass(slots=True)
class CitryTemplate:
    """
    A component's loaded template: the source string, its origin, and its
    compiled form (once first rendered).

    Attributes:
        source: The template string, after ``on_template_loaded`` hooks ran.
        origin: Where the template came from, for error messages and debugging.
            The absolute file path for a file template, or
            ``"<module file>::<ClassName>"`` for an inline one.
        filepath: The resolved template file, or ``None`` when the template
            was inlined on the class.
        generate: Internal. The compiled body-generating function; calling it
            yields a fresh node list. ``None`` until the render pipeline
            compiles the template on first render.
        used_vars: Internal. Every variable name the template uses, including
            in nested tags (the parse-time ``Template.used_variables``). Empty
            until compiled. The ``Const`` optimization keys its cache only on
            these.
        declared_slots: Internal. The ``<c-slot>`` tags the template declares
            (static names only), used to check the component against its
            ``Slots`` schema. Empty until compiled.

    """

    source: str
    origin: str
    filepath: Path | None = None

    # The compiled form, populated by component_render on first render.
    generate: Callable[[], list[BodyItem]] | None = None
    used_vars: frozenset[str] = field(default_factory=frozenset)
    declared_slots: tuple[DeclaredSlot, ...] = ()

    def __repr__(self) -> str:
        compiled = "compiled" if self.generate is not None else "not compiled"
        return f"CitryTemplate(origin={self.origin!r}, source_len={len(self.source)}, {compiled})"
