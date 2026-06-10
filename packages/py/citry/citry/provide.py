"""
Provide/inject: passing data deep down the component tree.

A component makes data available to everything rendered below it with
``Component.provide(key, **data)`` (or the ``<c-provide>`` built-in
component), and a descendant opts in with ``Component.inject(key)``. The data
never enters the template variables; only components that ask for it see it.
This is the citry form of React's ContextProvider and Vue's
``provide()``/``inject()``.

The data travels on ``CitryContext.provides`` along the render path (the
chain of contexts that rendering passes through), so it reaches components
inside slot content rendered below the provider, not just components written
below it. See docs/design/provide.md for the full model.

This module holds the building blocks: the immutable payload
(``make_provided``), the key validation, the inject lookup, and the
``MISSING`` sentinel that lets ``inject(key, None)`` genuinely default to
``None``.
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Any, Final, NamedTuple


class _MissingType:
    """The type of the ``MISSING`` sentinel (a singleton)."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final = _MissingType()
"""
Sentinel for "no default given" in ``Component.inject``.

Distinct from ``None`` on purpose: ``inject(key, None)`` returns ``None``
when the key was never provided, while ``inject(key)`` raises.
"""


def validate_provide_key(key: Any) -> str:
    """
    Check that ``key`` can name provided data, and return it.

    A key must be a non-empty string that is a valid Python identifier, so it
    can be looked up unambiguously and (in the future) addressed from any
    host language.
    """
    if not isinstance(key, str) or not key:
        msg = f"Provide key must be a non-empty string, got {key!r}."
        raise ValueError(msg)
    if not key.isidentifier():
        msg = f"Provide key must be a valid identifier, got {key!r}."
        raise ValueError(msg)
    return key


def make_provided(data: dict[str, Any]) -> tuple:
    """
    Freeze provided data into an immutable payload.

    The payload is a ``NamedTuple`` built for the given fields, so the object
    a component injects is immutable, supports attribute access
    (``inject("user_data").user``), and always carries every provided field.
    """
    fields = [(field, Any) for field in data]
    payload_cls = NamedTuple("Provided", fields)  # type: ignore[misc]
    return payload_cls(**data)


def inject_value(
    provides: dict[str, Any],
    key: str,
    default: Any,
    component_name: str,
) -> Any:
    """
    Look up ``key`` among the provides a component inherited.

    Returns the payload, or ``default`` when the key was never provided and a
    default was given. Otherwise raises ``KeyError`` explaining what to do,
    with a "did you mean" hint when a similarly named key exists.
    """
    if key in provides:
        return provides[key]

    if default is not MISSING:
        return default

    msg = (
        f"Component {component_name!r} tried to inject {key!r} but no ancestor provided it."
        f" Make sure a component above {component_name!r} provides {key!r},"
        f' e.g. with <c-provide key="{key}" ...> or Component.provide().'
    )
    close = get_close_matches(key, list(provides), n=1, cutoff=0.7)
    if close:
        msg += f" Did you mean {close[0]!r}?"
    raise KeyError(msg)
