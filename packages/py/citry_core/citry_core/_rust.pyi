# This file adds typing for the API exposed from Rust via maturin.
#
# IMPORTANT: The filename `_rust.pyi` matches the `<rust_module_name>` part of
# the `module-name` setting in `pyproject.toml` (`tool.maturin.module-name = "citry_core._rust"`).
# This ensures type checkers can find the type stubs for the Rust extension module.
#
# Since the Rust code exposed to Python is scoped under modules, we need to define
# the API as class attributes, e.g.
#
# ```py
# class template_parser:
#     class Tag:
#         ...
# ```
#
# So that in Python we can access it as:
#
# ```py
# from citry_core import _rust
# _rust.template_parser.Tag(...)
# ```
#
# Notes:
# - Functions without `self` are treated as module-level functions.
#   This matches how typeshed defines modules.

from typing import Any, Literal

########################################################
# HTML transform
########################################################

class html_transform:
    def mark_html(
        html: str,
        root_attributes: list[str],
        placeholder_attr: str,
    ) -> tuple[list[str], list[tuple[str, str, list[str]]]]:
        """
        Splice attributes onto root-level tags and split the HTML around child
        placeholder elements, in a single scan.

        This is the serializer's fast path. Each attribute in `root_attributes`
        is added (as `attr=""`) to every root-level (depth 0) tag. A placeholder
        is a `<template>` element carrying `placeholder_attr` with a
        whitespace-only body; the output is split around placeholders so the
        caller can join in each child's finished HTML without scanning again.

        Unlike `transform_html`, bytes outside root-level tags are copied
        through verbatim (no re-serialization or normalization), and malformed
        markup is treated as text rather than raising.

        **Arguments**

        - `html` (str): The HTML string to mark. Can be a fragment or full document.
        - `root_attributes` (List[str]): Attribute names to add to root-level tags.
        - `placeholder_attr` (str): The attribute that identifies placeholder elements.

        **Returns**

        A tuple `(segments, placeholders)`:
            - `segments` (List[str]): the marked HTML split around placeholders;
                always exactly `len(placeholders) + 1` entries.
            - `placeholders` (List[Tuple[str, str, List[str]]]): one entry per
                placeholder, in document order: `(id, placeholder_html, added_attributes)`
                where `id` is the placeholder attribute's value, `placeholder_html`
                is the placeholder element's text (with any spliced attributes,
                for callers that leave unknown ids in place), and
                `added_attributes` lists the attributes spliced into it
                (non-empty only for root-level placeholders).

        The marked HTML is `segments[0] + placeholders[0][1] + segments[1] + ...`.

        **Example**

        ```python
        >>> segments, placeholders = mark_html(
        ...     '<div><template c-render-id="c2"></template></div>',
        ...     ['data-cid-c1'],
        ...     'c-render-id',
        ... )
        >>> segments
        ['<div data-cid-c1="">', '</div>']
        >>> placeholders
        [('c2', '<template c-render-id="c2"></template>', [])]
        ```
        """

    def transform_html(
        html: str,
        root_attributes: list[str],
        all_attributes: list[str],
        check_end_names: bool | None = None,
        track_added_attributes_for_tags_with_this_attribute: str | None = None,
    ) -> tuple[str, dict[str, list[str]]]:
        """
        Transform given HTML string.

        This function performs the following transformations:

        1. **Add root attributes**: Attributes specified in `root_attributes` are added
        only to root-level elements (elements at depth 0).

        2. **Add attributes to all elements**: Attributes specified in `all_attributes`
        are added to every element in the HTML.

        In addition, this transformer also:

        1. **Tracks added attributes**: If `track_added_attributes_for_tags_with_this_attribute`
        is set, captures which attributes were added to elements that have the specified
        attribute, returning a dictionary mapping attribute values to lists of attributes added to tag.

        2. **Validates end tags**: If `check_end_names` is enabled, validates that
        closing tags match their corresponding opening tags.

        **Arguments**

        - `html` (str): The HTML string to transform. Can be a fragment or full document.
        - `root_attributes` (List[str]): List of attribute names to add to root elements only.
        - `all_attributes` (List[str]): List of attribute names to add to all elements.
        - `check_end_names` (Optional[bool]): Whether to validate matching of end tags. Defaults to False.
        - `track_added_attributes_for_tags_with_this_attribute` (Optional[str]): If set, captures which attributes were added to elements with this attribute.

        **Returns**

        A tuple containing:
            - The transformed HTML string
            - A dictionary mapping captured attribute values to lists of attributes that were added
                to those elements. Only populated if `track_added_attributes_for_tags_with_this_attribute` is set, otherwise empty dict.

        **Example**

        ```python
        >>> html = '<div data-id="123"><p>Hello</p></div>'
        >>> html, captured = transform_html(html, ['data-root-id'], ['data-v-123'], track_added_attributes_for_tags_with_this_attribute='data-id')
        >>> print(captured)
        {'123': ['data-root-id', 'data-v-123']}
        ```

        **Raises**

        ValueError: If the HTML is malformed or cannot be parsed.
        """

########################################################
# Safe eval
########################################################

class safe_eval:
    def safe_eval(source: str) -> str:
        """
        Transform a Python expression string to make it safe for evaluation.

        This function takes a Python expression string and transforms it into safe code
        by wrapping potentially unsafe operations (like variable access, function calls,
        attribute access, etc.) with sandboxed function calls.

        **Args:**

        - source (str): The Python expression string to transform.

        **Returns:**

        - str: The transformed Python expression as a string.

        **Raises:**

        - SyntaxError: If the input is not valid Python syntax or contains forbidden constructs.

        **Examples:**

        ```python
        >>> safe_eval("my_var + 1")
        'variable("my_var") + 1'

        >>> safe_eval("lambda x: x + my_var")
        'lambda x: x + variable("my_var")'
        ```

        **Transformations:**

        The following transformations are applied to make expressions safe for evaluation:

        1. **Variable access** - `my_var` → `variable("my_var")`
        2. **Function calls** - `foo(1, 2, a=3, *args, **kwargs)` → `call(foo, 1, 2, a=x, *args, **kwargs)`
        3. **Attribute access** - `obj.attr` → `attribute(obj, "attr")`
        4. **Subscript access** - `obj[key]` → `subscript(obj, key)`
        5. **Walrus operator** - `(x := value)` → `assign("x", value)`

        Because of the changes above, we also need to transform:

        6. **Slice notation** - `obj[1:10:2]` → `subscript(obj, slice(1, 10, 2))`
           - Because slice syntax is valid only inside square brackets.
        7. **F-strings** - `f"Hello {price!r:.2f}"` → `format("Hello {}", (variable("price"), "r", ".2f"))`
           - To avoid issues with quote escaping and enable error reporting
        8. **T-strings** - `t"Hello {name!r:>10}"` → `template("Hello ", interpolation(variable("name"), "expr", "r", ">10"))`
           - To avoid issues with quote escaping
        """

########################################################
# Template parser (V3)
########################################################

class template_parser:
    # Functions
    def parse_template(
        input: str,
        lang: str | None = None,
        user_rules: dict[str, template_parser.TagRules] | None = None,
    ) -> template_parser.Template: ...
    def compile_template(
        template: template_parser.Template,
        lang: str | None = None,
    ) -> str: ...

    # AST types

    class Token:
        """A span in the template source with position information."""
        def __init__(
            self,
            content: str,
            start_index: int,
            end_index: int,
            line_col: tuple[int, int],
        ) -> None: ...
        content: str
        start_index: int
        end_index: int
        line_col: tuple[int, int]

    class Comment:
        """A template comment `{# ... #}` or HTML comment `<!-- ... -->`."""
        def __init__(self, token: template_parser.Token, value: template_parser.Token) -> None: ...
        token: template_parser.Token
        value: template_parser.Token

    class HtmlAttrKind:
        """Enum: Static, Expression, or Template."""
        Static: template_parser.HtmlAttrKind
        Expression: template_parser.HtmlAttrKind
        Template: template_parser.HtmlAttrKind

    class HtmlAttr:
        """An HTML attribute (static, dynamic expression, or nested template)."""
        token: template_parser.Token
        key: template_parser.Token
        value: template_parser.Token | None
        inner_value: template_parser.Token | None
        quote_char: str | None
        used_variables: list[template_parser.Token]
        comments: list[template_parser.Comment]

    class HtmlStartTag:
        """An HTML opening tag with its attributes."""
        token: template_parser.Token
        name: template_parser.Token
        attrs: list[template_parser.HtmlAttr]
        is_self_closing: bool
        comments: list[template_parser.Comment]

    class HtmlEndTag:
        """An HTML closing tag."""
        token: template_parser.Token
        name: template_parser.Token
        comments: list[template_parser.Comment]

    class Expr:
        """A template expression `{{ ... }}`."""
        token: template_parser.Token
        value: template_parser.Token
        used_variables: list[template_parser.Token]
        comments: list[template_parser.Comment]

    class Text:
        """Plain text content."""
        token: template_parser.Token

    class Node_SelfClosing:
        """A self-closing HTML/component tag."""
        start_tag: template_parser.HtmlStartTag
        used_variables: list[template_parser.Token]
        introduced_variables: list[template_parser.Token]
        comments: list[template_parser.Comment]
        contains_fills: bool
        name: str

    class Node_WithBody:
        """An HTML/component tag with a body."""
        start_tag: template_parser.HtmlStartTag
        end_tag: template_parser.HtmlEndTag
        body: template_parser.Template
        used_variables: list[template_parser.Token]
        introduced_variables: list[template_parser.Token]
        comments: list[template_parser.Comment]
        contains_fills: bool
        name: str

    class Node:
        """Enum: SelfClosing or WithBody. Access the variant via `._0`."""
        SelfClosing: type[template_parser.Node_SelfClosing]
        WithBody: type[template_parser.Node_WithBody]
        name: str

    class TemplateElement_Text:
        """A TemplateElement variant wrapping Text. Access via `._0`."""
        _0: template_parser.Text

    class TemplateElement_Expr:
        """A TemplateElement variant wrapping Expr. Access via `._0`."""
        _0: template_parser.Expr

    class TemplateElement_Node:
        """A TemplateElement variant wrapping Node. Access via `._0`."""
        _0: template_parser.Node_SelfClosing | template_parser.Node_WithBody

    class TemplateElement:
        """Enum: Text, Expr, or Node. The concrete variant type is one of
        TemplateElement_Text, TemplateElement_Expr, TemplateElement_Node."""
        Text: type[template_parser.TemplateElement_Text]
        Expr: type[template_parser.TemplateElement_Expr]
        Node: type[template_parser.TemplateElement_Node]

    class StaticNamedSlot:
        """A slot with a statically-known name."""
        token: template_parser.Token
        required: bool | None

    class Template:
        """The parsed template AST."""
        elements: list[template_parser.TemplateElement_Text | template_parser.TemplateElement_Expr | template_parser.TemplateElement_Node]
        comments: list[template_parser.Comment]
        used_variables: list[template_parser.Token]
        slots: list[template_parser.StaticNamedSlot]

    # Config types

    class TagRules:
        """Validation rules for custom component tags."""
        def __init__(
            self,
            allowed_attrs: list[list[str]] | None = None,
            required_attrs: list[list[str]] | None = None,
            allowed_slots: list[str] | None = None,
            required_slots: list[str] | None = None,
        ) -> None: ...
        allowed_attrs: list[list[str]] | None
        required_attrs: list[list[str]]
        allowed_slots: list[str] | None
        required_slots: list[str]

    # Constants

    HTML_VOID_ELEMENTS: frozenset[str]
    """HTML void elements (elements that cannot have children, e.g. ``<br/>``)."""


########################################################
# Render plan (prototype)
########################################################

class render_plan:
    # Functions
    def compile_render_plan(
        template: template_parser.Template,
        lang: str | None = None,
    ) -> render_plan.RenderPlan: ...

    class RenderPlan:
        """A compiled render plan: a flat body walked by the Rust executor."""

        def render(
            self,
            body: list[Any],
            variables: dict[str, Any],
            context: Any,
            if_select: Any,
            for_iter: Any,
            prepare: Any,
            render_foreign: Any,
        ) -> str:
            """Walk the plan and return the assembled HTML string.

            ``body`` is the live Python node list from ``generate_template()``;
            its items line up one-to-one with the plan by position. ``variables``
            is the per-component scope passed to ``{{ expr }}`` evaluation, and
            ``context`` is the ``CitryContext`` used to render any node kind the
            plan does not model in Rust. ``if_select``, ``for_iter``, ``prepare``,
            and ``render_foreign`` are the Python helpers the walk calls for
            ``<c-if>`` branch selection, ``<c-for>`` iteration, child-component
            preparation, and rendering an unmodelled node (a ``<c-slot>``, ...).
            """

        @property
        def node_count(self) -> int:
            """Number of plan entries (static-text and node entries)."""

        def kinds(self) -> list[str]:
            """A coarse label for each entry: ``"text"``, ``"expr"``,
            ``"element_attrs"``, or ``"foreign:<NodeName>"``."""

    # A const-folded body lowered for the Rust body executor: built once by
    # BodyEngine.lower and cached per component + const signature.
    class FoldedPlan: ...

    # Walks a lowered body in Rust into a list[RenderPart]; static text, simple
    # attribute regions, and scalar interpolation run in Rust, every other node
    # and any non-scalar expression value is handed to a Python callback.
    class BodyEngine:
        def __init__(
            self,
            expr_type: Any,
            attrs_type: Any,
            template_attr_type: Any,
            const_proxy: Any,
            special_types: Any,
            render_value: Any,
            render_node: Any,
            attach_position: Any,
        ) -> None: ...
        def lower(self, body: list[Any], attrs_fast_path: bool) -> render_plan.FoldedPlan: ...
        def render(
            self,
            plan: render_plan.FoldedPlan,
            variables: dict[str, Any],
            context: Any,
            sandboxed: bool,
        ) -> list[Any]: ...


########################################################
# Dependency collection + merge (prototype)
########################################################

class deps_proto:
    # A record is (class_id, component_id, js_vars_hash, css_vars_hash).
    def dedup_first_seen(
        records: list[tuple[str, str, str | None, str | None]],
    ) -> list[tuple[str, str, str | None, str | None]]:
        """First-seen-order dedup of dependency records handed in from Python."""

    def bench_native_collect(n_distinct: int, n_levels: int) -> int:
        """Build and dedup records entirely in Rust (no marshalling); return the
        distinct count. The in-process speed if records already lived in Rust."""
