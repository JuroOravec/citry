"""
The ``Script`` and ``Style`` dependency objects.

A ``Script`` describes one ``<script>`` tag and a ``Style`` one ``<style>`` or
``<link rel="stylesheet">`` tag. Each holds either inline ``content`` or a
``url`` (never both), plus extra HTML attributes. The dependencies extension
builds these from a component's declared assets when emitting JS/CSS into the
rendered page, and users can place them directly as entries in a component's
``Dependencies`` class for full control over the emitted tag::

    class Chart(Component):
        class Dependencies:
            js = [Script(url="https://cdn.example.com/chart.js", attrs={"defer": True})]
            css = {"print": Style(url="/static/print.css")}

Two objects are considered the same dependency when they point at the same
url, or (for inline ones) carry the same content; the emission step uses that
to drop duplicates while keeping the first occurrence.

Design: docs/design/dependencies.md section 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple, TypeAlias

from citry.attrs import format_attrs
from citry.util.html import SafeString

ScriptType: TypeAlias = Literal["css", "js"]

DependencyKind: TypeAlias = Literal["core", "component", "variables", "extra"]
"""
What a dependency is for:

- ``"core"``: required for citry itself to work (the client-side manager).
- ``"component"``: a component's own ``Component.js`` / ``Component.css``.
- ``"variables"``: a generated script carrying ``js_data()`` / ``css_data()``
  values.
- ``"extra"``: anything else, e.g. entries from a ``Dependencies`` class.
"""


class DependencyRecord(NamedTuple):
    """
    One "this component instance rendered" note, collected during a render.

    The dependencies extension appends one of these to the render-scoped
    ``CitryContext.extra`` per component render, and the notes bubble up to
    the root as nested renders are consumed. At serialize time the collected
    records are resolved into the actual ``Script``/``Style`` tags; the heavy
    content lives in the cache, keyed by the record's fields.
    """

    class_id: str
    """``Component.class_id`` of the rendered component's class."""
    component_id: str
    """The render id of the component instance (``component.id``)."""
    js_vars_hash: str | None = None
    """Hash of the instance's ``js_data()`` result, or ``None`` when it has none."""
    css_vars_hash: str | None = None
    """Hash of the instance's ``css_data()`` result, or ``None`` when it has none."""


# JavaScript MIME types that mean "classic script" (subject to IIFE wrapping).
# See https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/MIME_types#textjavascript
_JAVASCRIPT_MIME_TYPES = frozenset(
    {
        "text/javascript",
        "application/javascript",
        "application/ecmascript",
        "application/x-ecmascript",
        "application/x-javascript",
        "text/ecmascript",
        "text/javascript1.0",
        "text/javascript1.1",
        "text/javascript1.2",
        "text/javascript1.3",
        "text/javascript1.4",
        "text/javascript1.5",
        "text/jscript",
        "text/livescript",
        "text/x-ecmascript",
        "text/x-javascript",
    }
)


def _script_type_should_wrap(attrs: dict[str, str | bool]) -> bool:
    """
    Whether inline script content may be wrapped in a self-executing function.

    Wrap when there is no ``type`` attribute, an empty one, or a JavaScript
    MIME type (a classic script). Do not wrap ``importmap``, ``module``,
    ``speculationrules``, or any other value, where the wrapper would change
    meaning or break parsing.
    """
    type_val = attrs.get("type")

    # No type attribute, or a boolean `type` attribute: a classic script.
    if type_val is None or isinstance(type_val, bool):
        return True

    type_str = str(type_val).strip().lower()
    return type_str == "" or type_str in _JAVASCRIPT_MIME_TYPES


@dataclass(eq=False)
class Dependency:
    """
    Shared base of :class:`Script` and :class:`Style`.

    Holds either inline ``content`` or a ``url``, never both; rendering
    raises when neither or both are set.
    """

    content: str | None = None
    """Text inside the ``<script>`` or ``<style>`` tag. ``None`` for
    url-based dependencies."""
    url: str | None = None
    """If set, renders as ``<script src="...">`` /
    ``<link rel="stylesheet" href="...">`` instead of an inline tag."""
    attrs: dict[str, str | bool] = field(default_factory=dict)
    """Extra HTML attributes (``True`` renders a bare boolean attribute)."""
    kind: DependencyKind = "extra"
    """What this dependency is for; see :data:`DependencyKind`."""
    origin_class_id: str | None = None
    """``class_id`` of the component class this dependency came from, when
    known. Used in error messages and for per-component hooks."""

    def _render(self) -> tuple[str, dict[str, str | bool], str]:
        """Return ``(tag_name, all_attrs, content)``. Implemented by subclasses."""
        raise NotImplementedError

    def render(self) -> SafeString:
        """Render as an HTML tag string."""
        tag_name, all_attrs, content = self._render()
        attrs_str = format_attrs(all_attrs)
        attrs_prefix = " " + attrs_str if attrs_str else ""
        return SafeString(f"<{tag_name}{attrs_prefix}>{content}</{tag_name}>")

    def __html__(self) -> SafeString:
        """The rendered tag; lets a ``Script``/``Style`` stand anywhere a pre-rendered tag is accepted."""
        return self.render()

    def render_json(self) -> dict[str, str | dict[str, str | bool]]:
        """
        Render as a JSON-ready dict with ``tag``, ``attrs``, and ``content``.

        This is the shape the client-side manager consumes when it constructs
        the element in the browser.
        """
        tag_name, all_attrs, content = self._render()
        return {"tag": tag_name, "attrs": all_attrs, "content": content}

    def _check_validity(self) -> None:
        if self.url and self.content:
            msg = f"{self._err_msg()} cannot have both a url and inline content"
            raise ValueError(msg)
        if not self.url and not self.content:
            msg = f"{self._err_msg()} must have either a url or inline content"
            raise ValueError(msg)

        # Inline content must not contain its own closing tag: `</script>`
        # inside JS content would terminate the tag early in the browser.
        tag_name = type(self).__name__.lower()
        end_tag_substr = f"</{tag_name}"
        if self.content and end_tag_substr in self.content:
            msg = f"{self._err_msg()} contains a '{end_tag_substr}>' end tag. This is not allowed."
            raise ValueError(msg)

    def _err_msg(self) -> str:
        if self.origin_class_id:
            return f"{type(self).__name__} for component '{self.origin_class_id}'"
        return type(self).__name__

    # Two dependencies are "the same" when they point at the same url, or
    # (inline ones) carry the same content. This is what lets the emission
    # step dedupe with plain `dict.fromkeys`, keeping first-seen order.
    def __hash__(self) -> int:
        if self.url:
            return hash((type(self).__name__, self.url))
        if self.content is not None:
            return hash((type(self).__name__, self.content))
        return id(self)

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other) or not isinstance(other, Dependency):
            return False
        if self.url and other.url:
            return self.url == other.url
        if not self.url and not other.url and self.content is not None and other.content is not None:
            return self.content == other.content
        return self is other


@dataclass(eq=False)
class Script(Dependency):
    """
    One ``<script>`` tag.

    With ``url`` set, renders ``<script src="...">``; otherwise renders the
    ``content`` inline as ``<script>...</script>``.

    Example::

        Script(content="console.log('hi');", attrs={"type": "module"}, wrap=False)
        # <script type="module">console.log('hi');</script>
    """

    wrap: bool = True
    """
    Wrap inline content in a self-executing function, so its top-level
    variables do not leak into (or collide with) other scripts on the page::

        (function() {
        console.log('hi');
        })();

    Only applies to classic scripts (no ``type`` attribute or a JS MIME
    type); ``module``/``importmap``/other types are never wrapped.
    """

    def to_json(self) -> dict[str, Any]:
        """Serialize for cache storage; the inverse of :meth:`from_json`."""
        return {
            "kind": self.kind,
            "url": self.url,
            "content": self.content,
            "attrs": self.attrs,
            "wrap": self.wrap,
            "origin_class_id": self.origin_class_id,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Script:
        """Rebuild from :meth:`to_json` output."""
        return cls(
            kind=data["kind"],
            content=data["content"],
            url=data["url"],
            attrs=data["attrs"],
            wrap=data["wrap"],
            origin_class_id=data["origin_class_id"],
        )

    def _render(self) -> tuple[str, dict[str, str | bool], str]:
        self._check_validity()
        if self.url:
            all_attrs: dict[str, str | bool] = {**self.attrs, "src": self.url}
            content = ""
        else:
            all_attrs = self.attrs
            content = self.content or ""
            if content and self.wrap and _script_type_should_wrap(all_attrs):
                content = f"(function() {{\n{content}\n}})();"
        return ("script", all_attrs, content)


@dataclass(eq=False)
class Style(Dependency):
    """
    One stylesheet tag.

    With ``url`` set, renders ``<link rel="stylesheet" href="..."/>``;
    otherwise renders the ``content`` inline as ``<style>...</style>``.

    Example::

        Style(url="/static/print.css", attrs={"media": "print"})
        # <link media="print" rel="stylesheet" href="/static/print.css"/>
    """

    def to_json(self) -> dict[str, Any]:
        """Serialize for cache storage; the inverse of :meth:`from_json`."""
        return {
            "kind": self.kind,
            "url": self.url,
            "content": self.content,
            "attrs": self.attrs,
            "origin_class_id": self.origin_class_id,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Style:
        """Rebuild from :meth:`to_json` output."""
        return cls(
            kind=data["kind"],
            content=data["content"],
            url=data["url"],
            attrs=data["attrs"],
            origin_class_id=data["origin_class_id"],
        )

    def _render(self) -> tuple[str, dict[str, str | bool], str]:
        self._check_validity()
        if self.url:
            all_attrs: dict[str, str | bool] = {**self.attrs, "rel": "stylesheet", "href": self.url}
            tag_name = "link"
            content = ""  # <link> has no content
        else:
            all_attrs = self.attrs
            tag_name = "style"
            content = self.content or ""
        return (tag_name, all_attrs, content)

    def render(self) -> SafeString:
        tag_name, all_attrs, content = self._render()
        attrs_str = format_attrs(all_attrs)
        attrs_prefix = " " + attrs_str if attrs_str else ""

        # A url renders as a void <link/> tag (compact, per citry's HTML
        # rendering rules); inline content renders as <style>...</style>.
        if tag_name == "link":
            return SafeString(f"<link{attrs_prefix}/>")
        return SafeString(f"<style{attrs_prefix}>{content}</style>")
