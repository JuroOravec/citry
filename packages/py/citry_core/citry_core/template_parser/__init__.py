"""
Citry template parser - parse and compile Citry templates.

This module exposes the V3 template parser (Rust-powered) to Python.
It provides two main functions and the AST types they produce.

Quick start::

    from citry_core.template_parser import parse_template, compile_template

    # Parse a template into an AST
    t = parse_template('<p>Hello {{ name }}!</p>')

    # Inspect the AST
    print(t.used_variables)   # [Token(content='name', ...)]
    print(len(t.elements))    # 1 (a <p> node containing text + expression)

    # Compile the AST into Python source code
    code = compile_template(t)
    print(code)
    # def generate_template():
    #     body = [...]
    #     return body

The generated code instantiates runtime node classes (``ExprNode``,
``ComponentNode``, etc.) defined in ``citry.nodes``.
See ``nodes.py`` for the full list and their constructor signatures.
"""

# ruff: noqa: RUF022
from typing import TypeAlias

from citry_core import _rust
from citry_core.template_parser.compile import compile_template
from citry_core.template_parser.parse import parse_template

# AST types (re-exported from Rust)
Token: TypeAlias = _rust.template_parser.Token
Comment: TypeAlias = _rust.template_parser.Comment
HtmlAttrKind: TypeAlias = _rust.template_parser.HtmlAttrKind
HtmlAttr: TypeAlias = _rust.template_parser.HtmlAttr
HtmlStartTag: TypeAlias = _rust.template_parser.HtmlStartTag
HtmlEndTag: TypeAlias = _rust.template_parser.HtmlEndTag
Expr: TypeAlias = _rust.template_parser.Expr
Text: TypeAlias = _rust.template_parser.Text
Node: TypeAlias = _rust.template_parser.Node
TemplateElement: TypeAlias = _rust.template_parser.TemplateElement
StaticNamedSlot: TypeAlias = _rust.template_parser.StaticNamedSlot
Template: TypeAlias = _rust.template_parser.Template

# Config types
TagRules: TypeAlias = _rust.template_parser.TagRules

__all__ = [
    # Functions
    "parse_template",
    "compile_template",
    # AST types
    "Token",
    "Comment",
    "HtmlAttrKind",
    "HtmlAttr",
    "HtmlStartTag",
    "HtmlEndTag",
    "Expr",
    "Text",
    "Node",
    "TemplateElement",
    "StaticNamedSlot",
    "Template",
    # Config types
    "TagRules",
]
