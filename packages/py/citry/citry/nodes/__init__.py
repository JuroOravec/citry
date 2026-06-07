"""
Stub runtime node classes for the Citry template compiler output.

The V3 compiler generates Python source code that instantiates these classes.
Each class accepts the exact arguments the compiler emits and stores them as
attributes. The ``render`` method raises ``NotImplementedError`` - actual
rendering is a separate task.

These stubs are enough to ``exec()`` the generated code and inspect the
resulting node tree.

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

from typing import Any


class ExprNode:
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

    def render(self, context: Any) -> str:
        raise NotImplementedError("ExprNode.render")

    def __repr__(self) -> str:
        return f"ExprNode(position={self.position}, expr={self.expr!r}, used_vars={self.used_vars})"


class TemplateNode:
    """
    A nested template expression on an HTML tag's dynamic attribute.

    Generated as: ``TemplateNode(source, (start, end), "expr", ("var1", ...))``

    Example:
        Template ``<a c-href="url">`` compiles the ``c-href`` value to::

            TemplateNode(source, (11, 14,), "url", ("url",))

        (on regular HTML tags, dynamic attrs are split inline rather than
        wrapped in ``ExprHtmlAttr``.)

    """

    def __init__(self, source: Any, position: tuple[int, int], expr: str, used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.position = position
        self.expr = expr
        self.used_vars = used_vars

    def render(self, context: Any) -> str:
        raise NotImplementedError("TemplateNode.render")

    def __repr__(self) -> str:
        return f"TemplateNode(position={self.position}, expr={self.expr!r})"


class StaticHtmlAttr:
    """
    A static HTML attribute (``key="value"``).

    Generated as: ``StaticHtmlAttr(source, (start, end), "key", "value", ())``

    Example:
        Template ``<c-Card title="Hello" />`` produces::

            StaticHtmlAttr(source, (8, 21,), "title", "Hello", ())

    """

    def __init__(self, source: Any, position: tuple[int, int], key: str, value: str, used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.position = position
        self.key = key
        self.value = value
        self.used_vars = used_vars

    def __repr__(self) -> str:
        return f"StaticHtmlAttr(key={self.key!r}, value={self.value!r})"


class ExprHtmlAttr:
    """
    A dynamic expression attribute (``c-class="expr"``).

    Generated as: ``ExprHtmlAttr(source, (start, end), "c-class", "expr", ("var",))``

    Example:
        Template ``<c-Card c-title="t" />`` produces::

            ExprHtmlAttr(source, (8, 19,), "c-title", "t", ("t",))

    """

    def __init__(self, source: Any, position: tuple[int, int], key: str, expr: str, used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.position = position
        self.key = key
        self.expr = expr
        self.used_vars = used_vars

    def __repr__(self) -> str:
        return f"ExprHtmlAttr(key={self.key!r}, expr={self.expr!r})"


class TemplateHtmlAttr:
    """
    A nested template attribute (``c-body="<div>...</div>"``).

    Generated as: ``TemplateHtmlAttr(source, (start, end), "c-body", "<div>...</div>", ("var",))``

    Example:
        Template ``<c-Card c-body="<span>{{ x }}</span>" />`` produces::

            TemplateHtmlAttr(source, (8, 37,), "c-body", "<span>{{ x }}</span>", ("x",))

    """

    def __init__(self, source: Any, position: tuple[int, int], key: str, template: str, used_vars: tuple[str, ...]) -> None:
        self.source = source
        self.position = position
        self.key = key
        self.template = template
        self.used_vars = used_vars

    def __repr__(self) -> str:
        return f"TemplateHtmlAttr(key={self.key!r})"


class ComponentNode:
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
        attrs: tuple[Any, ...],
        body: list[Any],
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

    def render(self, context: Any) -> str:
        raise NotImplementedError("ComponentNode.render")

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

    @override
    def render(self, context: CitryContext) -> CitryRender:
        """
        Render the first branch whose ``cond`` is truthy.

        Branches are tried in source order (``c-if`` then each ``c-elif`` then
        ``c-else``). A branch's ``cond`` attribute is resolved against the
        context; the first truthy one wins. A branch with no ``cond`` (the
        ``c-else``) always matches. If none match, the render is empty.

        The body renders against the surrounding ``context`` unchanged: an
        ``<c-if>`` introduces no variables, so there is no new scope.
        """
        # Imported lazily: component_render imports the node classes, so importing
        # the body walker at module load would be circular.
        from citry.component_render import _render_body  # noqa: PLC0415

        for branch in self.branches:
            attrs: tuple[HtmlAttr, ...] = branch[1]
            body: list[BodyItem] = branch[2]
            cond_attr = _find_attr(attrs, "cond")
            if cond_attr is None or cond_attr.resolve(context):
                return CitryRender(parts=_render_body(body, context), context=context)
        return CitryRender(parts=[], context=context)

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

    @override
    def render(self, context: CitryContext) -> CitryRender:
        """
        Render the loop body once per item; the empty branch if there are none.

        The ``each`` clause is a Python comprehension clause, so the loop is
        evaluated by wrapping it in a generator expression that yields the loop
        targets as a tuple: ``each="x in xs if x > 0"`` becomes
        ``((x,) for x in xs if x > 0)``. This reuses Python's own comprehension
        semantics, so multi-target unpacking and ``if`` filters work for free.

        Each iteration renders the body against a child context whose
        ``variables`` are the surrounding ones overlaid with the loop bindings.
        The child shares the parent's ``component`` and ``extra`` bag, so the
        loop introduces a variable scope without crossing a component boundary
        (dependencies still bubble through the shared ``extra``).
        """
        from citry.component_render import _render_body  # noqa: PLC0415

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
            self._iter_eval = safe_eval(gen_src)

        parts: list[RenderPart] = []
        count = 0
        for values in self._iter_eval(context.variables):
            count += 1
            child = CitryContext(
                variables={**context.variables, **dict(zip(targets, values, strict=True))},
                extra=context.extra,
                component=context.component,
            )
            parts.extend(_render_body(body, child))

        # No iterations: render the optional <c-empty> branch (second branch).
        if count == 0 and len(self.branches) > 1:
            empty_branch = self.branches[1]
            parts.extend(_render_body(empty_branch[2], context))

        return CitryRender(parts=parts, context=context)

    def __repr__(self) -> str:
        return f"ForNode(branches={len(self.branches)})"


@final
class SlotNode(Node):
    """
    A slot definition (``<c-slot>``).

    Generated as::

        SlotNode(source, (start, end), (attrs,), [body], (used_vars,), (introduced_vars,))

    Example:
        Template ``<c-slot name="header" />`` produces::

            SlotNode(source, (0, 24,), (StaticHtmlAttr(...),), [], (), ())

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

    Rendering is not implemented yet; it inherits ``Node.render`` (raises
    ``NotImplementedError``) until the slots phase.

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

    def __repr__(self) -> str:
        return f"FillNode(attrs={len(self.attrs)})"
