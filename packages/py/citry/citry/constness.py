"""
Const marker for the const-folding feature.

``Const(value)`` marks a component input as constant across renders. It is a
transparent proxy (a ``wrapt.ObjectProxy`` subclass): it behaves exactly like
the wrapped value, so end-user code and template expressions can use a Const
value just like the underlying value, while the engine can still detect
const-ness (``isinstance(x, Const)``) as the value flows down the component
tree. The marker is never unwrapped during rendering, so each descendant that
receives a Const value can detect it and key its own body cache on it.

The render pipeline detects const-marked context variables and uses them to key
a body cache (see ``docs/design/constness.md``). Folding (specializing the body
per const signature) is not yet implemented.

Example:
    Mark an input constant::

        from citry import Component, Const

        class Card(Component):
            template = "<p>{{ cols }}</p>"

            def template_data(self, kwargs, slots=None):
                return {"cols": kwargs["cols"]}  # the marker flows through

        Card(cols=Const(3)).render()

"""

from __future__ import annotations

from typing import Any

import wrapt


class Const(wrapt.ObjectProxy):
    """
    A transparent marker that a value is constant across renders.

    Behaves exactly like the wrapped value (arithmetic, attribute and item
    access, method calls, comparisons, ``str``); only ``repr`` is overridden so
    the marker is visible in debugging. Detected with ``isinstance(x, Const)``.
    """

    def __repr__(self) -> str:
        return f"Const({self.__wrapped__!r})"


def is_const(value: Any) -> bool:
    """Return ``True`` if ``value`` is marked ``Const``."""
    return isinstance(value, Const)


def const_value(value: Any) -> Any:
    """Return the underlying value if ``value`` is ``Const``, else ``value``."""
    return value.__wrapped__ if isinstance(value, Const) else value
