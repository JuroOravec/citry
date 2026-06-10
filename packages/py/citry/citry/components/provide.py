"""
The ``<c-provide>`` built-in component.

Wraps content and makes data available to every component rendered inside
it, which reads the data with ``Component.inject()``::

    <c-provide key="user_data" c-user="user">
      <c-user-card />   <!-- can call self.inject("user_data").user -->
    </c-provide>

The ``key`` attribute names the provided data; every other attribute is a
provided field (static attributes as strings, ``c-*`` attributes evaluated,
``c-bind`` spread). The component is transparent: it adds no markup and no
``data-cid`` marker of its own. See docs/design/provide.md section 6.

Each ``Citry`` instance gets its own subclass of the component, created
lazily by ``make_builtin_components`` (a Component class binds to one Citry
instance at class-definition time, so the built-in cannot be shared).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from citry.component import Component

if TYPE_CHECKING:
    from citry.citry import Citry


def make_provide_component(citry_instance: Citry) -> type[Component]:
    """Create (and thereby register) the ``<c-provide>`` component for one Citry instance."""

    class Provide(Component):
        """
        Provide data to the components rendered inside this tag.

        ``key`` (required) names the data; all other attributes become the
        provided fields, injectable below as
        ``self.inject(key).<field>``.
        """

        citry = citry_instance
        transparent = True
        template = "<c-slot />"

        def template_data(
            self,
            kwargs: Any,
            slots: Any | None = None,  # noqa: ARG002
        ) -> dict[str, Any]:
            data = dict(kwargs)
            key = data.pop("key", None)
            if key is None:
                msg = "<c-provide> requires a 'key' attribute naming the provided data."
                raise ValueError(msg)
            self.provide(key, **data)
            return {}

    return Provide
