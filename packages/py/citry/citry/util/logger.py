"""
Citry's logging: a package logger and a hot-path-safe TRACE level.

Everything citry logs goes through ``logging.getLogger("citry")``, so a project
configures citry's logs the standard way: set the level and handlers of the
``"citry"`` logger. On top of the usual levels, citry adds a **TRACE** level
(numeric 5, below ``DEBUG``) for a detailed view of the render walk.

Trace calls are built to be nearly free when TRACE is off: they check whether it
is enabled before building any message, so the render hot path pays only a cheap
level check. For a trace argument that is not free to compute (a component's
ancestor path, say), guard building it with :func:`is_tracing` so nothing is
computed when TRACE is off.

Measured cost on the large benchmark page (about 2300 traced events per render):
with TRACE off the added instrumentation is below the render benchmark's noise
floor (no measurable slowdown); with TRACE on the render is roughly 1.9x slower
(about 5 microseconds per emitted record, the built-in cost of creating and
dispatching a logging record, and more with a handler that writes to disk or a
terminal). So TRACE is a debugging aid, not something to leave on in production.

To see TRACE logs, set the ``"citry"`` logger to level 5, e.g.
``logging.getLogger("citry").setLevel(5)`` or ``logging.basicConfig(level=5)``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

# TRACE sits below DEBUG (10). It is registered lazily on first use, so importing
# this module has no global side effect, and a "TRACE" level another library
# already defined is reused rather than clobbered.
_DEFAULT_TRACE_LEVEL = 5
_trace_level = -1  # -1 until resolved by _ensure_trace_level()

logger = logging.getLogger("citry")


def _ensure_trace_level() -> int:
    """Resolve (once) the numeric level named "TRACE", registering it if needed."""
    global _trace_level  # noqa: PLW0603
    if _trace_level != -1:
        return _trace_level
    # Reuse an existing "TRACE" level if another library already named one;
    # getLevelName returns the number for a registered name, else a string.
    existing = logging.getLevelName("TRACE")
    if isinstance(existing, int):
        _trace_level = existing
    else:
        _trace_level = _DEFAULT_TRACE_LEVEL
        logging.addLevelName(_trace_level, "TRACE")
    return _trace_level


def is_tracing() -> bool:
    """
    Whether citry TRACE logging is enabled right now.

    Cheap to call. Use it to guard building trace arguments that are not free to
    compute (a component's ancestor path, for example), so the render hot path
    pays nothing for them when TRACE is off.
    """
    return logger.isEnabledFor(_ensure_trace_level())


def trace(message: str, *args: Any, **kwargs: Any) -> None:
    """
    Log ``message`` at citry's TRACE level, or do nothing when TRACE is off.

    ``args`` are the usual :mod:`logging` %-style lazy arguments, formatted only
    if the record is actually emitted.
    """
    level = _ensure_trace_level()
    if logger.isEnabledFor(level):
        logger.log(level, message, *args, **kwargs)


def trace_node_msg(action: str, node_type: str, position: tuple[int, int] | None = None, msg: str = "") -> None:
    """
    Trace one node render event, or do nothing when TRACE is off.

    ``node_type`` is the node class name and ``position`` its ``(start, end)``
    span in the template source (citry nodes have no id, so the span identifies
    them), e.g. ``RENDER NODE ExprNode @12:20``.
    """
    level = _ensure_trace_level()
    if not logger.isEnabledFor(level):
        return
    where = f" @{position[0]}:{position[1]}" if position else ""
    logger.log(level, f"{action} NODE {node_type}{where} {msg}".rstrip())


def trace_component_msg(
    action: str,
    component_name: str,
    component_id: str | None = None,
    slot_name: str | None = None,
    component_path: list[str] | None = None,
    slot_fills: Iterable[str] | None = None,
    extra: str = "",
) -> None:
    """
    Trace one render event for a component or slot, in a consistent format.

    Does nothing when TRACE is off (checked before any string is built). Empty
    fields are dropped, so a message carries only what was passed, e.g.
    ``RENDER COMPONENT: 'Card' ID c12 PATH: Root > Card FILLS: header``.
    ``slot_fills`` is any iterable of fill names; a mapping contributes its keys.
    """
    level = _ensure_trace_level()
    if not logger.isEnabledFor(level):
        return
    fields = [action, f"COMPONENT: {component_name!r}"]
    if component_id:
        fields.append(f"ID {component_id}")
    if slot_name:
        fields.append(f"SLOT: {slot_name!r}")
    if component_path:
        fields.append("PATH: " + " > ".join(component_path))
    if slot_fills is not None:
        fills = list(slot_fills)
        if fills:
            fields.append("FILLS: " + ", ".join(fills))
    if extra:
        fields.append(extra)
    logger.log(level, " ".join(fields))
