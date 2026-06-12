"""
The ``<c-component>`` and ``<c-element>`` built-in components.

Two sibling tags that choose their render target at render time
(docs/design/dynamic_component.md):

- ``<c-component is="...">`` renders a *component*: ``is`` is a registered
  component name or a ``Component`` class. All other attributes become the
  target's kwargs, and the body (fills included) becomes its slots::

      <c-component c-is="table_comp" c-rows="rows">
        <c-fill name="pagination"><c-pagination /></c-fill>
      </c-component>

- ``<c-element is="...">`` renders a *plain HTML element*: ``is`` is the tag
  name, decided at render time. All other attributes become the element's
  HTML attributes, and the body becomes its children::

      <c-element c-is="form_content_tag" class="form-content">
        ...children...
      </c-element>

Any tag name is accepted by ``<c-element>`` (custom web components included),
the same trust statically written HTML gets. A misspelled *component* name
still fails loudly, because ``<c-component>`` never falls back to elements.

Both tags' static-`is` forms never reach these classes: the compiler turns
``<c-component is="MyComp">`` into the named component and
``<c-element is="div">`` (with no fills) into the literal element, so only
the dynamic forms (``c-is``, or ``is`` via ``c-bind``) resolve here.

Each ``Citry`` instance gets its own subclasses, created lazily by
``make_builtin_components`` (a Component class binds to one Citry instance at
class-definition time, so the built-ins cannot be shared).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from citry.attrs import format_attrs, merge_attrs
from citry.citry_element import CitryElement
from citry.citry_render import CitryRender
from citry.component import Component
from citry.component_registry import _VALID_NAME_RE, NotRegistered
from citry.constness import const_value
from citry.util.html import SafeString
from citry_core.template_parser import HTML_VOID_ELEMENTS

if TYPE_CHECKING:
    from citry.citry import Citry
    from citry.slots import Slot


def make_dynamic_component(citry_instance: Citry) -> type[Component]:
    """Create (and thereby register) the ``<c-component>`` component for one Citry instance."""

    class DynamicComponent(Component):
        """
        Render the component named by ``is`` in this tag's place.

        ``is`` (required) is a registered component name or a ``Component``
        class; every other attribute is passed to it as a kwarg, and the
        body (fills included) as its slots.
        """

        citry = citry_instance
        name = "component"
        transparent = True
        template = "{{ target }}"

        def template_data(
            self,
            kwargs: Any,  # noqa: ARG002
            slots: Any | None = None,  # noqa: ARG002
        ) -> dict[str, Any]:
            data = dict(self.raw_kwargs)
            comp_cls = _resolve_component(self, const_value(data.pop("is", None)))
            # The target renders in this tag's place: remaining kwargs and the
            # full slots pass through, so the target's own Kwargs/Slots
            # validation speaks for unexpected inputs.
            return {"target": CitryElement(comp_cls, data, self.raw_slots)}

    return DynamicComponent


def _resolve_component(component: Component, value: Any) -> type[Component]:
    """Resolve the ``is`` value of ``<c-component>`` to a component class."""
    if not value:
        msg = "<c-component> requires an 'is' value: a registered component name or a Component class."
        raise TypeError(msg)
    if isinstance(value, str):
        try:
            return component.citry.get(value)
        except NotRegistered as err:
            msg = f"{err} To render a plain HTML element, use <c-element> instead."
            raise NotRegistered(msg) from err
    if isinstance(value, type) and issubclass(value, Component):
        return value
    if isinstance(value, CitryElement):
        msg = (
            "<c-component> 'is' got an already-composed element. "
            "Embed it with '{{ ... }}' instead, or pass its class."
        )
        raise TypeError(msg)
    msg = f"<c-component> 'is' must be a component name or a Component class, got {type(value).__name__}."
    raise TypeError(msg)


def make_dynamic_element(citry_instance: Citry) -> type[Component]:
    """Create (and thereby register) the ``<c-element>`` component for one Citry instance."""

    class DynamicElement(Component):
        """
        Render a plain HTML element whose tag name is the ``is`` value.

        ``is`` (required) is the tag name; every other attribute becomes an
        HTML attribute of the element, and the body its children. Void
        elements (``br``, ``img``, ...) reject a body.
        """

        citry = citry_instance
        name = "element"
        transparent = True
        # The open/close tags are computed values: one generic class covers
        # every tag name, instead of a synthesized class per name
        # (docs/design/dynamic_component.md section 5.1).
        template = "{{ open }}<c-slot />{{ close }}"

        def template_data(
            self,
            kwargs: Any,  # noqa: ARG002
            slots: Any | None = None,  # noqa: ARG002
        ) -> dict[str, Any]:
            attrs = dict(self.raw_kwargs)
            tag = const_value(attrs.pop("is", None))
            _validate_tag_name(tag)
            _reject_named_fills(self.raw_slots)

            attr_str = _format_element_attrs(self, tag, attrs)

            # Void elements cannot have children; the empty open/close pair
            # below otherwise brackets the default slot (the tag's body).
            if tag in HTML_VOID_ELEMENTS:
                if self.raw_slots:
                    msg = f"<c-element>: void element '{tag}' cannot have children."
                    raise ValueError(msg)
                return {"open": SafeString(f"<{tag}{attr_str}/>"), "close": ""}
            return {
                "open": SafeString(f"<{tag}{attr_str}>"),
                "close": SafeString(f"</{tag}>"),
            }

    return DynamicElement


def _validate_tag_name(tag: Any) -> None:
    """
    Reject ``is`` values that are not syntactically valid tag names.

    The tag name lands verbatim in the output (the attribute *values* are
    escaped by ``format_attrs``), so this check is also what keeps the
    interpolation in ``template_data`` safe.
    """
    if not tag or not isinstance(tag, str):
        msg = f"<c-element> requires an 'is' value naming the HTML tag, got {type(tag).__name__}."
        raise TypeError(msg)
    if not _VALID_NAME_RE.match(tag):
        msg = (
            f"<c-element>: {tag!r} is not a valid HTML tag name. "
            f"Must start with a letter and contain only letters, digits, hyphens, underscores, or dots."
        )
        raise ValueError(msg)


def _reject_named_fills(raw_slots: dict[str, Slot]) -> None:
    """
    Reject named fills: an element has children, but no named slots.

    Static named fills are already parse errors (the Rust slot rules); this
    catches the dynamic spellings (``c-name`` fills, ``c-bind`` slots) that
    only resolve at render time.
    """
    named = sorted(name for name in raw_slots if name != "default")
    if named:
        msg = f"<c-element> only accepts the default slot (the tag's body); got fills named: {', '.join(named)}."
        raise ValueError(msg)


def _format_element_attrs(component: Component, tag: str, attrs: dict[str, Any]) -> str:
    """
    Format the element's attributes the way a statically written element's
    are: normalize class/style, drop ``False``/``None``, fire the
    ``on_attrs_resolved`` extension hook, escape values (``attrs.py`` is the
    shared value layer; docs/design/html_attrs.md).

    Returns ``""`` or a string with a leading space (`` class="btn"``).
    """
    contributions = {key: const_value(value) for key, value in attrs.items()}
    for value in contributions.values():
        # A nested-template attribute value resolves to a CitryRender, whose
        # parts may hold not-yet-rendered child components, so it cannot be
        # flattened to a string here. The static-`is` form supports it (it
        # compiles to a real element); the dynamic form rejects it.
        if isinstance(value, CitryRender):
            msg = (
                "<c-element> with a dynamic 'is' does not support nested-template attribute "
                'values. Use a static is="...", or precompute the value in template_data().'
            )
            raise TypeError(msg)

    merged = merge_attrs(contributions)
    resolved = {key: value for key, value in merged.items() if value is not None and value is not False}
    resolved = component.citry.extensions.on_attrs_resolved(
        component=component,
        tag_name=tag,
        attrs=resolved,
    )
    formatted = format_attrs(resolved)
    return f" {formatted}" if formatted else ""
