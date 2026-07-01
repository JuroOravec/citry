"""
Stub runtime node classes for the Citry template compiler output.

The V3 compiler generates Python source code that instantiates these classes.
Each class accepts the exact arguments the compiler emits and stores them as
attributes.

The value nodes ``ExprNode`` and ``TemplateNode`` render against a
``CitryContext`` (see docs/design/rendering.md), and the attribute nodes
(``StaticHtmlAttr``, ``ExprHtmlAttr``, ``TemplateHtmlAttr``) ``resolve`` to
their values. ``ComponentNode`` renders a child component across a context
boundary: attributes become the child's kwargs, and its body content becomes
the child's slots (the implicit default slot, or the collected ``<c-fill>``
tags; see docs/design/slots.md section 4). The control-flow nodes (``IfNode``,
``ForNode``) render their matching branch / per-item body. ``SlotNode``
renders the fill given for the slot, or its own body as the fallback (see
docs/design/slots.md section 5). ``FillNode`` is consumed during fill
collection and is never rendered directly, so its inherited ``render``
raising is intentional.

See the compiler module docstring in
``crates/citry_template_parser/src/compiler.rs`` for the full node taxonomy
and constructor signatures.

Example:
    Parse a template, compile it, and exec the result::

        from citry_core.template_parser import parse_template, compile_template
        from citry_core.template_parser.nodes import (
            ExprNode, ComponentNode, IfNode, ForNode,
            SlotNode, FillNode, StaticHtmlAttr, ExprHtmlAttr,
            TemplateHtmlAttr, TemplateNode,
        )

        source = '<c-Card title="Hi">{{ body }}</c-Card>'
        t = parse_template(source)
        code = compile_template(t)

        ns = {
            "source": source,
            "ExprNode": ExprNode,
            "TemplateNode": TemplateNode,
            "ComponentNode": ComponentNode,
            "ElementAttrsNode": ElementAttrsNode,
            "IfNode": IfNode,
            "ForNode": ForNode,
            "SlotNode": SlotNode,
            "FillNode": FillNode,
            "StaticHtmlAttr": StaticHtmlAttr,
            "ExprHtmlAttr": ExprHtmlAttr,
            "TemplateHtmlAttr": TemplateHtmlAttr,
        }
        exec(code, ns)
        body = ns["generate_template"]()

        # body[0] is a ComponentNode with name="card"
        print(body[0].name)       # "card"
        print(body[0].attrs[0])   # StaticHtmlAttr(key='title', value='Hi')

"""

from __future__ import annotations

from collections.abc import Mapping
from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, TypeAlias, final

from typing_extensions import override

from citry.attrs import format_attrs, merge_attrs
from citry.citry_context import CitryContext
from citry.citry_element import CitryElement
from citry.citry_render import CitryRender, DeferredComponent, _render_value
from citry.constness import Const, const_value, is_const
from citry.slots import Slot
from citry.util.exception import add_slot_to_error_message
from citry.util.html import escape
from citry.util.logger import trace_component_msg
from citry_core.safe_eval import compile_expr

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from citry.citry_render import RenderPart


# NOTE: Not abstract on purpose: the compiler builds the whole node tree up front
# (including nodes inside branches that may never render), so a
# not-yet-implemented node must still be instantiable. The default ``render``
# therefore raises ``NotImplementedError`` only when the node is actually
# rendered, not when it is constructed.
class Node:
    """
    Base class for the runtime nodes the template compiler output instantiates.

    A node renders to a body part (a ``str`` or a nested ``CitryRender``) against
    the render-scoped ``CitryContext``. Concrete nodes override ``render``.

    A node sitting in a *fill group* (a component body that contains
    ``<c-fill>`` tags) takes part in fill collection through
    ``Node.collect_fills()`` instead of ``Node.render()``. The default says
    the node is not allowed there; nodes that are (``FillNode``, the control-flow nodes)
    override it.
    """

    def render(self, context: CitryContext) -> RenderPart:
        raise NotImplementedError(f"{type(self).__name__}.render is not implemented")

    # `context` is unused here (the base only raises) but is the documented
    # signature for overriding nodes, hence the noqa.
    def collect_fills(self, context: CitryContext, sink: FillSink) -> None:  # noqa: ARG002
        """
        Register this node's fills into ``sink``.

        Called instead of ``render`` when the node sits in a fill group. The
        base implementation rejects the node: when a component body contains
        ``<c-fill>`` tags, all other content must be inside the fills. A node
        kind that may sit beside fills (for example one injected by an
        extension via ``on_template_compiled``) overrides this to register its
        fills with ``sink.add(...)``, recursing into its own bodies with
        ``collect_fills_from_body``.
        """
        msg = (
            f"Tag ({type(self).__name__}) cannot appear next to '<c-fill>' tags in the body of "
            f"<c-{sink.component_name}>. All other content must be inside the fills."
        )
        raise RuntimeError(msg)


# One item in a compiled template body: a runtime Node or a static text run.
BodyItem: TypeAlias = "Node | str"


class HtmlAttr:
    """
    Base class for HTML attribute nodes (a component's or slot's inputs).

    An attribute resolves to a value (which becomes a component kwarg), not to a
    rendered body part. Concrete attributes override ``resolve``.
    """

    # Set by every concrete attribute's __init__; declared here so code iterating
    # a ``tuple[HtmlAttr, ...]`` can read ``.key``.
    key: str

    def resolve(self, context: CitryContext) -> Any:
        raise NotImplementedError(f"{type(self).__name__}.resolve is not implemented")


def _find_attr(attrs: tuple[HtmlAttr, ...], key: str) -> HtmlAttr | None:
    """Return the first attribute with the given key, or ``None``."""
    for attr in attrs:
        if attr.key == key:
            return attr
    return None


class FillSink:
    """
    Where ``collect_fills`` registers the fills of one component tag.

    Created by ``ComponentNode`` when it collects its body's fills, and passed
    down through ``Node.collect_fills``. Carries the name of the component
    receiving the fills (for error messages and slot metadata) and enforces
    that each materialized slot name appears only once.
    """

    __slots__ = ("component_name", "fills")

    def __init__(self, component_name: str) -> None:
        self.component_name = component_name
        self.fills: dict[str, Slot] = {}

    def add(self, name: str, slot: Slot) -> None:
        """Register one fill. Raises if the slot name is already taken."""
        if name in self.fills:
            msg = f"Multiple fills target the same slot name {name!r} in the body of <c-{self.component_name}>."
            raise RuntimeError(msg)
        self.fills[name] = slot


def collect_fills_from_body(body: list[BodyItem], context: CitryContext, sink: FillSink) -> None:
    """
    Walk one level of a fill-group body, collecting fills into ``sink``.

    Whitespace strings between fills are formatting only: neither captured
    into a slot nor rendered. Non-whitespace text is rejected (when a
    component body contains ``<c-fill>`` tags, all other content must be
    inside the fills). Each node dispatches through its own
    ``collect_fills``, so what a node contributes (a fill, a taken branch,
    one pass per loop iteration, or an error) is the node's own business.

    The parser already rejects most content beside fills; the checks on this
    path are the runtime half of that contract (dynamic fill names make some
    shapes undecidable statically), so the errors mirror the parser's.
    """
    for item in body:
        if isinstance(item, str):
            if item.strip():
                msg = (
                    f"Text cannot appear next to '<c-fill>' tags in the body of "
                    f"<c-{sink.component_name}>. All other content must be inside the fills."
                )
                raise RuntimeError(msg)
        else:
            item.collect_fills(context, sink)


def _make_body_slot(
    body: list[BodyItem],
    context: CitryContext,
    component_name: str,
    slot_name: str,
    data_var: str | None,
    fallback_var: str | None,
    position: tuple[int, int] | None,
) -> Slot:
    """
    Wrap a fill body (or a component's implicit default body) as a ``Slot``.

    The Slot closes over ``context``, the scope where the fill was written,
    so the body renders against the writer's variables no matter when or
    how often the child invokes it. When the child passes slot data or the
    fallback handle, they are overlaid under the fill's ``data``/
    ``fallback`` variable names; the overlay context shares the captured
    ``extra`` bag, so dependencies collected while the fill renders reach
    the fill's lexical owner.

    Provide/inject entries are the one part of the scope that does NOT come
    from the capture alone: when the body renders at a ``<c-slot>`` site, the
    provides active at that site extend (and on a key collision win over) the
    captured ones, so a component inside the body can inject what the slot's
    owner provides around the slot. Invoked standalone (no slot site), the
    body keeps the captured provides. See docs/design/provide.md section 4.3.
    """
    # Imported lazily: component_render imports the node classes, so importing
    # the body walker at module load would be circular.
    from citry.component_render import _render_body  # noqa: PLC0415

    def content_func(ctx: Any) -> CitryRender:
        provides = context.provides
        if ctx.provides is not None and ctx.provides is not provides:
            provides = {**provides, **ctx.provides} if provides else ctx.provides

        if data_var is not None or fallback_var is not None or provides is not context.provides:
            overlay: dict[str, Any] = {}
            if data_var is not None:
                overlay[data_var] = ctx.data
            if fallback_var is not None:
                overlay[fallback_var] = ctx.fallback
            render_context = CitryContext(
                variables={**context.variables, **overlay},
                extra=context.extra,
                component=context.component,
                provides=provides,
                sandboxed=context.sandboxed,
            )
        else:
            render_context = context
        return CitryRender(parts=_render_body(body, render_context), context=render_context)

    return Slot(
        body,
        content_func=content_func,
        component_name=component_name,
        slot_name=slot_name,
        source_position=position,
    )


@final
class ExprNode(Node):
    """
    A ``{{ expr }}`` expression node.

    Generated as: ``ExprNode(source, (start, end), "expr", ("var1", ...))``

    Example:
        Template ``{{ name }}`` compiles to::

            ExprNode(source, (0, 10,), "name ", ("name",))

    """

    def __init__(self, source: Any, position: tuple[int, int], expr: str, used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.position = position
        self.expr = expr
        self.used_vars = used_vars
        # The safe-eval function for `expr`, compiled lazily on first render and
        # reused afterwards (the node is cached across renders, so this compiles
        # once). Compiling lazily avoids paying for nodes that are never
        # rendered, e.g. an expression in an `<c-if>` branch that is never taken.
        self._eval: Callable[[Any], Any] | None = None

    def evaluate(self, variables: Mapping[str, Any], *, sandboxed: bool = True) -> Any:
        """
        Evaluate the expression against ``variables`` and return the raw value.

        The compiled evaluator is built on first use and reused (the node is
        cached across renders, so the expression compiles once). ``sandboxed``
        chooses the security sandbox or plain evaluation; it is read only on the
        first call, when the evaluator is compiled, and ignored afterwards (the
        instance's setting is fixed, so every call passes the same value).
        Called by ``render``, and by the ``Const`` optimization
        (``citry/constness.py``), which evaluates an expression ahead of time
        when all of its variables are marked constant.
        """
        if self._eval is None:
            self._eval = compile_expr(self.expr, sandboxed=sandboxed)
        return self._eval(variables)

    @override
    def render(self, context: CitryContext) -> RenderPart:
        value = self.evaluate(context.variables, sandboxed=context.sandboxed)
        # An element or Slot found in the expression renders with the
        # provide/inject entries active here, so it can inject what this
        # render site provides (docs/design/provide.md section 4.4).
        return _render_value(value, provides=context.provides)

    @override
    def collect_fills(self, context: CitryContext, sink: FillSink) -> None:
        # Same rule as the base, with a friendlier name for what the user wrote.
        msg = (
            f"Expression cannot appear next to '<c-fill>' tags in the body of "
            f"<c-{sink.component_name}>. All other content must be inside the fills."
        )
        raise RuntimeError(msg)

    def __repr__(self) -> str:
        return f"ExprNode(position={self.position}, expr={self.expr!r}, used_vars={self.used_vars})"


@final
class TemplateNode(Node):
    """
    A nested template value on an HTML tag's dynamic attribute.

    Emitted when a ``c-*`` attribute value is itself a template (starts with a
    tag and ends with a closing tag), as opposed to a plain expression (which
    becomes an ``ExprNode``). The ``expr`` field holds the nested template
    source string.

    Generated as: ``TemplateNode(source, (start, end), "template", ("var1", ...))``

    Example:
        Template ``<div c-body="<span>{{ x }}</span>">`` compiles the
        ``c-body`` value to::

            TemplateNode(source, (13, 33,), "<span>{{ x }}</span>", ("x",))

    """

    def __init__(self, source: Any, position: tuple[int, int], expr: str, used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.position = position
        # `expr` is the nested template SOURCE STRING (for example
        # "<span>{{ x }}</span>"), not a Python expression.
        self.expr = expr
        self.used_vars = used_vars
        # The body-generating function for the nested template, compiled lazily
        # on first render and reused afterwards (compile once per node).
        self._generator: Callable[[], list[Any]] | None = None

    @override
    def render(self, context: CitryContext) -> CitryRender:
        # A nested template is not a component boundary: it shares the
        # surrounding component's context, so it renders against the same
        # variables and writes any dependencies into the same context.
        #
        # Imported lazily because component_render imports the node classes:
        # importing the body pipeline at module load would be circular.
        from citry.component_render import _compile_nested_template, _render_body  # noqa: PLC0415

        if self._generator is None:
            # The nested template is validated like any other: the parse gets
            # the rules derived from the registered components' declarations.
            component = context.component
            user_rules = component.citry._tag_rules() if component is not None else None
            self._generator = _compile_nested_template(self.expr, user_rules)
        parts = _render_body(self._generator(), context)
        return CitryRender(parts=parts, context=context)

    def __repr__(self) -> str:
        return f"TemplateNode(position={self.position}, expr={self.expr!r})"


@final
class StaticHtmlAttr(HtmlAttr):
    """
    A static HTML attribute (``key="value"``).

    Generated as: ``StaticHtmlAttr(source, (start, end), "key", "value", ())``

    Example:
        Template ``<c-Card title="Hello" />`` produces::

            StaticHtmlAttr(source, (8, 21,), "title", "Hello", ())

    """

    def __init__(
        self, source: Any, position: tuple[int, int], key: str, value: str, used_vars: tuple[str, ...]
    ) -> None:
        self.source = source
        self.position = position
        self.key = key
        self.value = value
        self.used_vars = used_vars

    @override
    def resolve(self, context: CitryContext) -> Any:
        """
        Return the static value (a string, or ``True`` for a boolean attribute).

        The value is returned as-is, without the ``Const`` marker ("this is
        the same on every render"). Attribute values serve double duty: they
        can be slot and fill names, provide keys, or component inputs, and
        only the component-input use benefits from the marker. So the marking
        happens in ``ComponentNode._resolve_kwargs``, where the value becomes
        a component input, not here.
        """
        return self.value

    def __repr__(self) -> str:
        return f"StaticHtmlAttr(key={self.key!r}, value={self.value!r})"


@final
class ExprHtmlAttr(HtmlAttr):
    """
    A dynamic expression attribute (``c-class="expr"``).

    Generated as: ``ExprHtmlAttr(source, (start, end), "c-class", "expr", ("var",))``

    Example:
        Template ``<c-Card c-title="t" />`` produces::

            ExprHtmlAttr(source, (8, 19,), "c-title", "t", ("t",))

    """

    def __init__(
        self, source: Any, position: tuple[int, int], key: str, expr: str | bool, used_vars: tuple[str, ...]
    ) -> None:
        self.source = source
        self.position = position
        self.key = key
        # The expression string, or `True` for a value-less attribute (`c-foo`).
        self.expr = expr
        self.used_vars = used_vars
        # The safe-eval function for `expr`, compiled lazily on first resolve and
        # reused afterwards (the node is cached across renders, so this compiles
        # once).
        self._eval: Callable[[Any], Any] | None = None

    @override
    def resolve(self, context: CitryContext) -> Any:
        """
        Evaluate the expression and return the raw value.

        The value is NOT escaped or stringified: it becomes a component kwarg (a
        Python object). Escaping happens later, when the child component renders
        the value through an ``ExprNode``. The value is returned without the
        ``Const`` marker; for an expression that uses no variables (a literal
        written in the template), ``ComponentNode._resolve_kwargs`` adds the
        marker where the value becomes a component input.
        """
        # The parser rejects a value-less `c-*` attribute, but node classes
        # are public API: an extension building an ExprHtmlAttr by hand (via
        # on_template_compiled) may pass `True` as the boolean form. There is
        # nothing to evaluate then; the attribute is simply on.
        if not isinstance(self.expr, str):
            return True
        if self._eval is None:
            self._eval = compile_expr(self.expr, sandboxed=context.sandboxed)
        return self._eval(context.variables)

    def __repr__(self) -> str:
        return f"ExprHtmlAttr(key={self.key!r}, expr={self.expr!r})"


@final
class TemplateHtmlAttr(HtmlAttr):
    """
    A nested template attribute (``c-body="<div>...</div>"``).

    Generated as: ``TemplateHtmlAttr(source, (start, end), "c-body", "<div>...</div>", ("var",))``

    Example:
        Template ``<c-Card c-body="<span>{{ x }}</span>" />`` produces::

            TemplateHtmlAttr(source, (8, 37,), "c-body", "<span>{{ x }}</span>", ("x",))

    """

    def __init__(
        self, source: Any, position: tuple[int, int], key: str, template: str, used_vars: tuple[str, ...]
    ) -> None:
        self.source = source
        self.position = position
        self.key = key
        self.template = template
        self.used_vars = used_vars
        # The body-generating function for the nested template, compiled lazily
        # on first resolve and reused afterwards (compile once per node).
        self._generator: Callable[[], list[Any]] | None = None

    @override
    def resolve(self, context: CitryContext) -> CitryRender:
        """
        Render the nested template and return it as a ``CitryRender`` kwarg value.

        The template is defined in the parent's scope, so it renders against the
        surrounding component's context (the same rule as ``TemplateNode``).
        """
        from citry.component_render import _compile_nested_template, _render_body  # noqa: PLC0415

        if self._generator is None:
            # The nested template is validated like any other: the parse gets
            # the rules derived from the registered components' declarations.
            component = context.component
            user_rules = component.citry._tag_rules() if component is not None else None
            self._generator = _compile_nested_template(self.template, user_rules)
        parts = _render_body(self._generator(), context)
        return CitryRender(parts=parts, context=context)

    def __repr__(self) -> str:
        return f"TemplateHtmlAttr(key={self.key!r})"


@final
class ElementAttrsNode(Node):
    """
    The attribute region of a plain HTML start tag with dynamic attributes.

    Generated as: ``ElementAttrsNode(source, (start, end), (attrs...), ("var1", ...))``

    Emitted when an HTML element (not a component) has at least one dynamic
    attribute: a ``c-*`` value or a ``c-bind`` spread. The node covers ALL of
    the tag's attributes, static ones included, because the set resolves as
    one unit:

    - Contributions collect left to right in source order; ``c-bind``
      contributes each entry of its mapping (which must be a ``Mapping``).
    - ``class`` and ``style`` merge across contributions and accept the
      structured value forms (string / dict / nested list); every other key
      resolves last-one-wins.
    - ``True`` renders the bare attribute, ``False`` and ``None`` omit it,
      everything else renders escaped (``__html__`` values pass through).

    Renders to one string like ``' class="btn" disabled'`` (leading space
    included) or ``""`` when every attribute resolved away.

    Example:
        Template ``<div id="x" c-class="cls">hi</div>`` produces::

            ElementAttrsNode(source, (0, 26,), (StaticHtmlAttr(...), ExprHtmlAttr(...),), ("cls",))

    """

    def __init__(
        self, source: Any, position: tuple[int, int], attrs: tuple[HtmlAttr, ...], used_vars: tuple[str, ...]
    ) -> None:
        self.source = source
        self.position = position
        self.attrs = attrs
        self.used_vars = used_vars
        # The tag name, read lazily from the template source on first use
        # (the compiler emits the tag name as a separate static chunk, so the
        # node itself does not receive it).
        self._tag_name: str | None = None

    @property
    def tag_name(self) -> str:
        """The element's tag name (e.g. ``"div"``), read from the source slice."""
        if self._tag_name is None:
            # The position spans the start tag, e.g. `<div c-class="cls">`.
            name = str(self.source)[self.position[0] + 1 : self.position[1]]
            for index, char in enumerate(name):
                if char.isspace() or char in "/>":
                    name = name[:index]
                    break
            self._tag_name = name
        return self._tag_name

    @override
    def render(self, context: CitryContext) -> RenderPart:
        resolved = self._resolve(context)

        # Let extensions rewrite the resolved dict (e.g. class dedup). Fires
        # only when an installed extension implements the hook; the manager
        # short-cuts otherwise (docs/design/html_attrs.md section 5.5).
        component = context.component
        if component is not None:
            resolved = component.citry.extensions.on_attrs_resolved(
                component=component,
                tag_name=self.tag_name,
                attrs=resolved,
            )

        return self._format(resolved, context)

    def _resolve(self, context: CitryContext) -> dict[str, Any]:
        """
        Collect the attribute contributions and merge them into one dict.

        ``False`` and ``None`` values are dropped here, so the merged dict
        holds only the attributes that will appear in the output (the
        ``on_attrs_resolved`` hook sees them already gone). A ``Const``
        marker is unwrapped so the normalizers see the real value.
        """
        contributions: list[Mapping[str, Any]] = []
        for attr in self.attrs:
            if attr.key == "c-bind":
                value = const_value(attr.resolve(context))
                # A c-bind of None contributes nothing, so an optional
                # attribute dict (a common case) needs no guard at the call
                # site. This matches Vue's `v-bind="null"`. A non-None,
                # non-mapping value is still a mistake and is rejected.
                if value is None:
                    continue
                if not isinstance(value, Mapping):
                    msg = (
                        f"c-bind on <{self.tag_name}> must resolve to a mapping of attributes, "
                        f"got {type(value).__name__}"
                    )
                    raise TypeError(msg)
                contributions.append({key: const_value(item) for key, item in value.items()})
            else:
                contributions.append({attr.key.removeprefix("c-"): const_value(attr.resolve(context))})
        merged = merge_attrs(*contributions)
        return {key: value for key, value in merged.items() if value is not None and value is not False}

    def _format(self, resolved: Mapping[str, Any], context: CitryContext) -> RenderPart:
        """Format the merged dict into the output part(s)."""
        # Common case: no attribute value is a nested-template render, so the
        # whole dict formats in a single pass. Doing it per key (the mixed-case
        # path below) would escape, join, and concatenate once per attribute,
        # which is the dominant per-element cost on a big page.
        if not any(isinstance(value, CitryRender) for value in resolved.values()):
            chunk = format_attrs(resolved)
            return (" " + chunk) if chunk else ""

        # Mixed: a nested-template value (`c-foo="<div>...</div>"`) keeps its
        # parts so components inside it stay deferred and render through the
        # queue. Format the runs of plain attributes around it in one call each.
        parts: list[RenderPart] = []
        plain: dict[str, Any] = {}

        def flush_plain() -> None:
            if plain:
                chunk = format_attrs(plain)
                if chunk:
                    parts.append(" " + chunk)
                plain.clear()

        for key, value in resolved.items():
            if isinstance(value, CitryRender):
                flush_plain()
                parts.append(f' {escape(key)}="')
                parts.append(value)
                parts.append('"')
            else:
                plain[key] = value
        flush_plain()

        if not parts:
            return ""
        if all(isinstance(part, str) for part in parts):
            return "".join(str(part) for part in parts)
        return CitryRender(parts=parts, context=context)

    def __repr__(self) -> str:
        return f"ElementAttrsNode(attrs={len(self.attrs)}, used_vars={self.used_vars})"


def _kwarg_is_const(attr: HtmlAttr, context: CitryContext) -> bool:
    """
    Whether a resolved component-input value is the same on every render.

    A static attribute (``age="30"``) is always the same. An expression
    attribute (``c-age="..."``) is the same on every render when every variable
    it reads is itself constant. Two cases follow from that one rule:

    - An expression that reads no variables at all (``c-items="[1, 2]"``,
      ``c-age="30"``) is constant: nothing in it can change. (This is why
      ``all()`` of an empty list of variables is true.)
    - An expression that reads only constant variables (``c-age="base + 1"``
      when ``base`` is constant) is constant too: a template expression only
      depends on its inputs, so if none of the inputs can change, neither can
      the result. Marking it lets the child component reuse the work it already
      did for that input.

    A ``TemplateHtmlAttr`` renders fresh output every time, and an attribute kind
    an extension added is unknown to us, so neither is treated as constant.
    """
    if isinstance(attr, StaticHtmlAttr):
        return True
    if isinstance(attr, ExprHtmlAttr):
        return all(is_const(context.variables.get(name)) for name in attr.used_vars)
    return False


@final
class ComponentNode(Node):
    """
    A component node (``<c-Card>``, ``<c-component>``, any ``<c-*>``).

    Generated as::

        ComponentNode(source, (start, end), (attrs,...), [body], (used_vars,), "name", contains_fills)

    Example:
        Template ``<c-Card title="Hi">body</c-Card>`` produces::

            ComponentNode(
                source, (0, 21,),
                (StaticHtmlAttr(source, (8, 18,), "title", "Hi", ()),),
                ["body"],
                (), "card", False,
            )

        Component names are lowercased (``Card`` -> ``card``); kebab names
        are preserved (``my-card`` stays ``my-card``).

    """

    def __init__(
        self,
        source: Any,
        position: tuple[int, int],
        attrs: tuple[HtmlAttr, ...],
        body: list[BodyItem],
        used_vars: tuple[str, ...],
        name: str,
        contains_fills: bool,
    ) -> None:
        self.source = source
        self.position = position
        self.attrs = attrs
        self.body = body
        self.used_vars = used_vars
        self.name = name
        self.contains_fills = contains_fills

    @override
    def render(self, context: CitryContext) -> DeferredComponent:
        """
        Work out the child's inputs, but don't render the child yet.

        This turns the tag's attributes into the child's kwargs, collects the
        body into the child's slots, and returns a ``DeferredComponent``. It
        does not render the child here: doing so would make one component
        render the next and so on, hitting Python's recursion limit on deeply
        nested pages. ``render_impl`` renders the child later, with its own
        ``CitryContext``, and copies its dependencies into the parent.

        The attributes and fill structure are read now, while this component is
        still rendering, so a loop variable from an enclosing ``<c-for>`` has
        the right value. Fill *bodies* stay lazy: each becomes a ``Slot`` that
        closes over the current scope and renders only when the child invokes
        it.
        """
        component = context.component
        if component is None:
            msg = "ComponentNode.render requires a component context bound to a Citry instance."
            raise RuntimeError(msg)

        kwargs = self._resolve_kwargs(context)
        slots = self._collect_slots(context)
        child_cls = component.citry.get(self.name)
        element = CitryElement(child_cls, kwargs, slots)
        # The active provide/inject entries are captured now, like the kwargs:
        # the child renders later (through the queue), when this context is
        # gone, but must still inherit what was provided around its tag.
        return DeferredComponent(element, component, context.provides)

    def _resolve_kwargs(self, context: CitryContext) -> dict[str, Any]:
        """
        Turn the attribute nodes into the child component's kwargs.

        - ``c-bind="expr"`` is a spread: its evaluated mapping is merged in,
          rather than producing a ``bind`` kwarg.
        - Other dynamic attrs carry a leading ``c-`` (``c-foo`` -> ``foo``);
          static attrs have a plain key. ``removeprefix`` handles both.

        A value that is the same on every render is marked ``Const`` here, so
        the child component can reuse the work it already did for that input,
        with no opt-in needed (see docs/design/constness.md). That covers a
        literal (``age="30"``, ``c-items="[1, 2]"``) and also an expression
        whose variables are all constant at render time (``c-age="base + 1"``
        when ``base`` is constant): the result of such an expression cannot
        change either, so it is constant too. ``_kwarg_is_const`` is the single
        rule that decides this. The marking happens here, where a value becomes
        a component input, and nowhere else, so values used as names or keys
        (slot/fill names, provide keys) stay plain. The marker is applied fresh
        on each render, so a mutable literal (a list) is still a new object
        every render; equal values still land on the same cache entry.
        """
        kwargs: dict[str, Any] = {}
        for attr in self.attrs:
            key: str = attr.key
            if key == "c-bind":
                bound = attr.resolve(context)
                # A c-bind of None contributes nothing (an optional kwargs dict
                # needs no `or {}` guard at the call site), matching Vue's
                # `v-bind="null"` and the same rule on plain elements. A
                # non-None, non-mapping value is still a mistake.
                if bound is None:
                    continue
                if not isinstance(bound, Mapping):
                    msg = f"c-bind on <{self.name}> must resolve to a mapping of kwargs, got {type(bound).__name__}"
                    raise TypeError(msg)
                kwargs.update(bound)
                continue
            value = attr.resolve(context)
            if _kwarg_is_const(attr, context):
                value = Const(value)
            kwargs[key.removeprefix("c-")] = value
        return kwargs

    def _collect_slots(self, context: CitryContext) -> dict[str, Slot]:
        """
        Turn the tag's body into the child component's slots.

        Two body modes, split by the compiler's ``contains_fills`` flag (see
        docs/design/slots.md section 4):

        - No fills: the whole body is the implicit default slot, registered
          under ``"default"``. A whitespace-only body is formatting, not
          content, and produces no slot.
        - Fills: the body is a fill group. Each ``<c-fill>`` becomes one slot;
          control flow between fills is evaluated now, against the live
          context, to decide which fills exist.
        """
        if not self.body:
            return {}

        if not self.contains_fills:
            if all(isinstance(item, str) and not item.strip() for item in self.body):
                return {}
            return {"default": _make_body_slot(self.body, context, self.name, "default", None, None, self.position)}

        sink = FillSink(self.name)
        collect_fills_from_body(self.body, context, sink)
        return sink.fills

    def __repr__(self) -> str:
        return f"ComponentNode(name={self.name!r}, attrs={len(self.attrs)}, body={len(self.body)} items)"


@final
class IfNode(Node):
    """
    A conditional node (``<c-if>``/``<c-elif>``/``<c-else>``).

    Generated as: ``IfNode(source, (branch1, branch2, ...), (used_vars,))``

    Each branch is a tuple: ``((start, end), (attrs,), [body], (introduced_vars,))``

    Example:
        Template ``<c-if cond="x">yes</c-if><c-else>no</c-else>`` produces
        an ``IfNode`` with two branches - one for the if-body and one for
        the else-body.

    Each branch is ``((start, end), (attrs,), [body], (introduced_vars,))``.
    The ``c-if``/``c-elif`` branches carry a ``cond`` attribute (an
    ``ExprHtmlAttr``); the ``c-else`` branch has none and always matches.

    """

    def __init__(self, source: Any, branches: tuple[Any, ...], used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.branches = branches
        self.used_vars = used_vars

    def active_branch_body(self, context: CitryContext) -> list[BodyItem] | None:
        """
        Return the body of the first branch that matches, or ``None``.

        Branches are tried in source order (``c-if`` then each ``c-elif`` then
        ``c-else``). A branch's ``cond`` attribute is resolved against the
        context; the first truthy one wins. A branch with no ``cond`` (the
        ``c-else``) always matches.

        Shared by ``render`` and by fill collection (``ComponentNode`` walks
        the matching branch when gathering ``<c-fill>`` tags).
        """
        for branch in self.branches:
            attrs: tuple[HtmlAttr, ...] = branch[1]
            body: list[BodyItem] = branch[2]
            cond_attr = _find_attr(attrs, "cond")
            if cond_attr is None or cond_attr.resolve(context):
                return body
        return None

    @override
    def render(self, context: CitryContext) -> CitryRender:
        """
        Render the first branch whose ``cond`` is truthy.

        If no branch matches, the render is empty. The body renders against the
        surrounding ``context`` unchanged: an ``<c-if>`` introduces no
        variables, so there is no new scope.
        """
        # Imported lazily: component_render imports the node classes, so importing
        # the body walker at module load would be circular.
        from citry.component_render import _render_body  # noqa: PLC0415

        body = self.active_branch_body(context)
        if body is None:
            return CitryRender(parts=[], context=context)
        return CitryRender(parts=_render_body(body, context), context=context)

    @override
    def collect_fills(self, context: CitryContext, sink: FillSink) -> None:
        """In a fill group, an ``<c-if>`` contributes the fills of its matching branch."""
        body = self.active_branch_body(context)
        if body is not None:
            collect_fills_from_body(body, context, sink)

    def __repr__(self) -> str:
        return f"IfNode(branches={len(self.branches)})"


@final
class ForNode(Node):
    """
    A loop node (``<c-for>``/``<c-empty>``).

    Generated as: ``ForNode(source, (for_branch, empty_branch?), (used_vars,))``

    Each branch is a tuple: ``((start, end), (attrs,), [body], (introduced_vars,))``

    Example:
        Template ``<c-for each="item in items">{{ item }}</c-for>`` produces
        a ``ForNode`` with one branch. Adding ``<c-empty>none</c-empty>``
        after it adds a second branch for the empty state.

    Each branch is ``((start, end), (attrs,), [body], (introduced_vars,))``.
    The loop branch carries an ``each`` attribute holding a Python comprehension
    clause (``"item in items"``, or the full ``"x in xs for y in ys if ..."``);
    ``introduced_vars`` are the loop targets it binds.

    """

    def __init__(self, source: Any, branches: tuple[Any, ...], used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.branches = branches
        self.used_vars = used_vars
        # The generator-expression evaluator for the `each` clause, compiled
        # lazily on first render and reused afterwards (the node is cached across
        # renders, so this compiles once).
        self._iter_eval: Callable[[Any], Any] | None = None

    def iter_bodies(self, context: CitryContext) -> Iterator[tuple[list[BodyItem], CitryContext]]:
        """
        Yield ``(body, context)`` once per loop iteration.

        The ``each`` clause is a Python comprehension clause, so the loop is
        evaluated by wrapping it in a generator expression that yields the loop
        targets as a tuple: ``each="x in xs if x > 0"`` becomes
        ``((x,) for x in xs if x > 0)``. This reuses Python's own comprehension
        semantics, so multi-target unpacking and ``if`` filters work for free.

        Each iteration's context overlays the loop bindings on the surrounding
        ``variables``; it shares the parent's ``component`` and ``extra`` bag,
        so the loop introduces a variable scope without crossing a component
        boundary. With no iterations, the optional ``<c-empty>`` branch's body
        is yielded once, with the surrounding context.

        Shared by ``render`` and by fill collection (``ComponentNode`` walks
        the iterations when gathering ``<c-fill>`` tags, so each collected fill
        closes over its own iteration's bindings).
        """
        for_branch = self.branches[0]
        targets: tuple[str, ...] = for_branch[3]
        body: list[BodyItem] = for_branch[2]

        if self._iter_eval is None:
            each_attr = _find_attr(for_branch[1], "each")
            if not isinstance(each_attr, ExprHtmlAttr):
                msg = "ForNode loop branch is missing a usable 'each' expression."
                raise RuntimeError(msg)
            # `each_attr.expr` is the raw clause, e.g. "item in items". Wrapping
            # the targets in a 1-tuple keeps single- and multi-target binding
            # uniform: `(x,)` for one target, `(k, v,)` for several.
            clause = each_attr.expr
            gen_src = f"(({', '.join(targets)},) for {clause})"
            self._iter_eval = compile_expr(gen_src, sandboxed=context.sandboxed)

        count = 0
        for values in self._iter_eval(context.variables):
            count += 1
            child = CitryContext(
                variables={**context.variables, **dict(zip(targets, values, strict=True))},
                extra=context.extra,
                component=context.component,
                provides=context.provides,
                sandboxed=context.sandboxed,
            )
            yield body, child

        # No iterations: the optional <c-empty> branch (second branch).
        if count == 0 and len(self.branches) > 1:
            yield self.branches[1][2], context

    @override
    def render(self, context: CitryContext) -> CitryRender:
        """
        Render the loop body once per item; the empty branch if there are none.

        See ``iter_bodies`` for the loop evaluation and scoping rules.
        """
        from citry.component_render import _render_body  # noqa: PLC0415

        parts: list[RenderPart] = []
        for body, body_context in self.iter_bodies(context):
            parts.extend(_render_body(body, body_context))
        return CitryRender(parts=parts, context=context)

    @override
    def collect_fills(self, context: CitryContext, sink: FillSink) -> None:
        """
        In a fill group, a ``<c-for>`` contributes its fills once per iteration.

        Each iteration's fills close over that iteration's loop bindings, so a
        fill body using the loop variable keeps the right value no matter when
        the child invokes it.
        """
        for body, body_context in self.iter_bodies(context):
            collect_fills_from_body(body, body_context, sink)

    def __repr__(self) -> str:
        return f"ForNode(branches={len(self.branches)})"


@final
class SlotNode(Node):
    """
    A slot definition (``<c-slot>``): the insertion point for slot content.

    Generated as::

        SlotNode(source, (start, end), (attrs,), [body], (used_vars,), (introduced_vars,))

    Example:
        Template ``<c-slot name="header" />`` produces::

            SlotNode(source, (0, 24,), (StaticHtmlAttr(...),), [], (), ())

    Rendering resolves the slot name, looks up the fill the component
    received, and invokes it with the slot data; with no fill, the slot's own
    body renders as the fallback.

    """

    def __init__(
        self,
        source: Any,
        position: tuple[int, int],
        attrs: tuple[HtmlAttr, ...],
        body: list[BodyItem],
        used_vars: tuple[str, ...],
        introduced_vars: tuple[str, ...],
    ) -> None:
        self.source = source
        self.position = position
        self.attrs = attrs
        self.body = body
        self.used_vars = used_vars
        self.introduced_vars = introduced_vars

    @override
    def render(self, context: CitryContext) -> RenderPart:
        """
        Render the fill given for this slot, or the slot's own body as fallback.

        The slot data (the tag's extra attributes) resolves against the current
        context per render of this site, so a slot inside a loop passes
        per-iteration data. The fill and the fallback render through the same
        path: both are Slots, invoked with ``(data, fallback)``. A fill renders
        against the scope where it was written (it closed over it at
        collection); the fallback body renders against the current context, as
        if the ``<c-slot>`` tags were not there.

        A required slot with no fill raises, with a "did you mean" hint over
        the fills the component received.
        """
        component = context.component
        if component is None:
            msg = "SlotNode.render requires a component context bound to a Citry instance."
            raise RuntimeError(msg)

        name, required, data = self._resolve_props(context)
        fills = component.raw_slots
        fill = fills.get(name)

        # Trace the slot render. All args are cheap, so call directly; the
        # helper itself skips the work when TRACE is off.
        trace_component_msg(
            "RENDER_SLOT",
            type(component).__name__,
            component.id,
            slot_name=name,
            slot_fills=fills,
        )

        # The slot's own body, as a Slot: the fallback handle when a fill
        # exists, the rendered content when none does.
        body_slot = _make_body_slot(self.body, context, type(component).__name__, name, None, None, self.position)

        if fill is not None:
            slot_used = fill
            # The provides active at this slot site travel into the fill, so
            # components inside the fill body can inject what this component
            # provides around the slot (docs/design/provide.md section 4.3).
            # An error raised by the slot content gets this slot as a path
            # frame ("Card(slot:body)") in its message.
            with add_slot_to_error_message(type(component).__name__, name):
                part = fill(data, fallback=body_slot, provides=context.provides)
        else:
            if required:
                msg = (
                    f"Slot {name!r} of component {type(component).__name__!r} is marked as "
                    "required, but no fill was provided."
                )
                close = get_close_matches(name, list(fills), n=1, cutoff=0.7)
                if close:
                    msg += f" Did you mean {close[0]!r}?"
                raise RuntimeError(msg)
            slot_used = body_slot
            with add_slot_to_error_message(type(component).__name__, name):
                part = body_slot(data, provides=context.provides)

        return component.citry.extensions.on_slot_rendered(
            component=component,
            slot=slot_used,
            slot_name=name,
            slot_node=self,
            slot_is_required=required,
            result=part,
        )

    def _resolve_props(self, context: CitryContext) -> tuple[str, bool, dict[str, Any]]:
        """
        Resolve the slot's attributes to ``(name, required, data)``.

        Attributes are applied left to right, so the rightmost write wins:
        ``name``/``required`` are static, ``c-name``/``c-required`` are
        evaluated, and ``c-bind`` spreads a mapping (its ``name`` and
        ``required`` keys land on the slot; everything else is slot data).
        Every remaining attribute is slot data, with the ``c-`` prefix dropped
        from evaluated keys, the same rule as component kwargs.
        """
        name: Any = "default"
        required: Any = False
        data: dict[str, Any] = {}
        for attr in self.attrs:
            key = attr.key
            if key == "c-bind":
                spread = attr.resolve(context)
                if not isinstance(spread, Mapping):
                    msg = f"'c-bind' on <c-slot> must resolve to a mapping, got {type(spread).__name__}."
                    raise RuntimeError(msg)
                for spread_key, spread_value in spread.items():
                    if spread_key == "name":
                        name = spread_value
                    elif spread_key == "required":
                        required = spread_value
                    else:
                        data[spread_key] = spread_value
            elif key in ("name", "c-name"):
                name = attr.resolve(context)
            elif key in ("required", "c-required"):
                required = attr.resolve(context)
            else:
                data[key.removeprefix("c-")] = attr.resolve(context)

        if not isinstance(name, str) or not name:
            msg = f"<c-slot> 'name' must resolve to a non-empty string, got {name!r}."
            raise RuntimeError(msg)

        return name, bool(required), data

    def __repr__(self) -> str:
        return f"SlotNode(attrs={len(self.attrs)})"


@final
class FillNode(Node):
    """
    A slot fill (``<c-fill>``).

    Generated as::

        FillNode(source, (start, end), (attrs,), [body], (used_vars,), (introduced_vars,))

    Example:
        Template ``<c-fill name="header">content</c-fill>`` produces::

            FillNode(source, (0, 40,), (StaticHtmlAttr(...),), ["content"], (), ())

    A fill is consumed during fill collection (``collect_fills`` wraps its body
    as a ``Slot`` and registers it), so it is never rendered as output; it
    inherits ``Node.render`` raising, and reaching it would mean a
    parser/runtime bug.

    """

    def __init__(
        self,
        source: Any,
        position: tuple[int, int],
        attrs: tuple[HtmlAttr, ...],
        body: list[BodyItem],
        used_vars: tuple[str, ...],
        introduced_vars: tuple[str, ...],
    ) -> None:
        self.source = source
        self.position = position
        self.attrs = attrs
        self.body = body
        self.used_vars = used_vars
        self.introduced_vars = introduced_vars

    @override
    def collect_fills(self, context: CitryContext, sink: FillSink) -> None:
        """
        Resolve this fill's attributes and register its body as a ``Slot``.

        The Slot closes over ``context``, the scope where the fill was written
        (including any loop bindings from an enclosing ``<c-for>``); the body
        stays unrendered until the child component invokes the slot.
        """
        name, data_var, fallback_var = self._resolve_props(context)
        slot = _make_body_slot(self.body, context, sink.component_name, name, data_var, fallback_var, self.position)
        sink.add(name, slot)

    def _resolve_props(self, context: CitryContext) -> tuple[str, str | None, str | None]:
        """
        Resolve the fill's attributes to ``(slot_name, data_var, fallback_var)``.

        Attributes are applied left to right, so the rightmost write wins
        (matching the parser's identity rules): ``name`` and ``data``/
        ``fallback`` are static values, ``c-name`` is evaluated, and ``c-bind``
        spreads a mapping whose recognized keys are ``name``, ``data``, and
        ``fallback``.
        """
        props: dict[str, Any] = {}
        for attr in self.attrs:
            key = attr.key
            if key == "c-bind":
                spread = attr.resolve(context)
                if not isinstance(spread, Mapping):
                    msg = f"'c-bind' on <c-fill> must resolve to a mapping, got {type(spread).__name__}."
                    raise RuntimeError(msg)
                for spread_key, spread_value in spread.items():
                    if spread_key not in ("name", "data", "fallback"):
                        msg = (
                            f"'c-bind' on <c-fill> got an unsupported key {spread_key!r}. "
                            "Allowed keys: 'name', 'data', 'fallback'."
                        )
                        raise RuntimeError(msg)
                    props[spread_key] = spread_value
            elif key == "c-name":
                props["name"] = attr.resolve(context)
            else:
                # The parser only lets "name", "data", and "fallback" through.
                props[key] = attr.resolve(context)

        name = props.get("name")
        if not isinstance(name, str) or not name:
            msg = f"<c-fill> 'name' must resolve to a non-empty string, got {name!r}."
            raise RuntimeError(msg)

        data_var = props.get("data")
        fallback_var = props.get("fallback")
        for label, var in (("data", data_var), ("fallback", fallback_var)):
            if var is not None and (not isinstance(var, str) or not var.isidentifier()):
                msg = f"<c-fill> {label!r} must be a valid Python identifier, got {var!r}."
                raise RuntimeError(msg)
        if data_var is not None and data_var == fallback_var:
            msg = f"<c-fill name=\"{name}\"> binds 'data' and 'fallback' to the same variable {data_var!r}."
            raise RuntimeError(msg)

        return name, data_var, fallback_var

    def __repr__(self) -> str:
        return f"FillNode(attrs={len(self.attrs)})"
