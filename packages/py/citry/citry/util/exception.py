"""
Helpers that put the component path into render error messages.

When rendering fails somewhere deep in a component tree, the bare exception
("KeyError: 'rows'") does not say which component was rendering. These helpers
attach the path from the root component down to the failure site onto the
exception itself, so the user sees:

    KeyError: An error occurred while rendering components
    MyPage > Card(slot:body) > Avatar:
    'rows'

The path frames accumulate on the exception object (its ``_components``
attribute), and the message prefix is rewritten each time frames are added.
Carrying the path on the exception means it survives bubbling, re-raising,
and user ``try``/``except`` passthroughs, with no state threaded through the
render loop. See docs/design/on_render.md section 6.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from citry_core.safe_eval import format_error_with_context

if TYPE_CHECKING:
    from collections.abc import Generator

# Marker phrase in the rewritten message. Checked on each rewrite so adding
# more path frames replaces the old prefix line instead of stacking prefixes.
_PREFIX_MARKER = "An error occurred while rendering components"


def set_component_error_message(err: Exception, component_path: list[str]) -> None:
    """
    Prepend ``component_path`` to the error's component path and rewrite its message.

    The new frames go in front of any frames already on the error: as an error
    bubbles up the component tree, each level adds its enclosing components,
    so the outermost component ends up first. The message becomes::

        An error occurred while rendering components MyPage > Card > Avatar:
        <original message>

    The same attribute name (``_components``) as django-components is used, so
    when django-components wraps citry the two layers cooperate on one path.
    """
    if not hasattr(err, "_components"):
        err._components = []  # type: ignore[attr-defined]

    components: list[str] = getattr(err, "_components", [])
    components = err._components = [*component_path, *components]  # type: ignore[attr-defined]

    comp_path = " > ".join(components)
    prefix = f"{_PREFIX_MARKER} {comp_path}:\n"

    # Read the current message from ``args`` (see https://stackoverflow.com/a/75549200).
    if len(err.args) and err.args[0] is not None:
        orig_msg = str(err.args[0])
        # If we prefixed this error before, drop the old prefix line.
        if components and _PREFIX_MARKER in orig_msg:
            orig_msg = orig_msg.split("\n", 1)[-1]
    else:
        # Some exceptions (e.g. Pydantic's) build their message without using
        # ``args``. We still set ``args`` (and ``_components`` stays readable),
        # but the prefix may not show in ``str(err)`` for those.
        # (django-components also printed the prefix to stdout here; citry
        # does not print from library code.)
        orig_msg = str(err)

    err.args = (prefix + orig_msg,)


@contextmanager
def with_component_error_message(component_path: list[str]) -> Generator[None, None, None]:
    """
    Add ``component_path`` to the message of any error raised inside the block.

    The error is re-raised as-is (same exception object), only with the path
    frames added via ``set_component_error_message``.
    """
    try:
        yield
    except Exception as err:
        set_component_error_message(err, component_path)
        # ``from None`` re-raises the original error without adding this
        # helper frame to the traceback chain.
        raise err from None


def set_template_position_error_message(
    err: Exception,
    source: str,
    position: tuple[int, int],
    component_name: str | None,
) -> None:
    """
    Append an underlined template snippet for ``position`` to the error message.

    ``source`` is the whole template string and ``position`` the failing
    node's start/end indices in it. The snippet shows the failing lines with
    real line numbers and a ``^^^`` underline, headed by a line naming the
    template's owner ("In template of 'Page':").

    Runs once per error, so the innermost failing node wins: a later call for
    the same error (e.g. from the enclosing ``<c-if>``'s render) is a no-op.
    The marker is separate from safe_eval's, so an expression error keeps
    safe_eval's expression-level snippet and gains this template-level one.
    """
    if getattr(err, "_template_position", False):
        return
    err._template_position = True  # type: ignore[attr-defined]

    # Put the header between the current message and the snippet. The
    # formatter re-emits the current message as the head of the new one, so
    # appending the header to the message first lands it just above the
    # snippet block.
    header = f"In template of {component_name!r}:" if component_name is not None else "In template:"
    if len(err.args) and err.args[0] is not None:
        msg = str(err.args[0])
    else:
        msg = str(err)
    err.args = (f"{msg}\n\n{header}" if msg else header,)

    format_error_with_context(err, source, position[0], position[1], "template", add_prefix=False)


@contextmanager
def add_slot_to_error_message(component_name: str, slot_name: str) -> Generator[None, None, None]:
    """
    Add a slot frame (``Card(slot:body)``) to any error raised inside the block.

    Used at the slot invocation site, so the path shows which slot the failing
    content was filled into. The frame goes in front of frames added deeper in
    the tree; the message itself is rewritten by the next
    ``with_component_error_message`` further up.
    """
    try:
        yield
    except Exception as err:
        if not hasattr(err, "_components"):
            err._components = []  # type: ignore[attr-defined]

        err._components.insert(0, f"{component_name}(slot:{slot_name})")  # type: ignore[attr-defined]
        raise err from None
