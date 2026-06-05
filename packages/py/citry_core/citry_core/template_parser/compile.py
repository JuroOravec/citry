
from citry_core import _rust


def compile_template(
    template: _rust.template_parser.Template,
    lang: str | None = None,
) -> str:
    """
    Compile a parsed Template AST into host-language source code.

    For Python (the default), the output is a ``generate_template()`` function
    that returns a list of runtime node objects (``ExprNode``,
    ``ComponentNode``, ``IfNode``, etc.). The host-language runtime must
    provide implementations for those classes.

    Args:
        template: The parsed AST from ``parse_template``.
        lang: Target language. One of "python" (default), "js", "php",
            "go", "rust".

    Returns:
        The generated source code as a string.

    Raises:
        ValueError: If compilation fails or an unknown language is specified.

    Examples:
        Compile and inspect the generated source::

            from citry_core.template_parser import parse_template, compile_template

            t = parse_template('<p>{{ name }}</p>')
            code = compile_template(t)
            print(code)
            # def generate_template():
            #     body = [\"\"\"<p>\"\"\", ExprNode(source, (3, 13,), ...),  ...]
            #     return body

        Compile, then exec with stub node classes::

            from citry_core.template_parser import parse_template, compile_template
            from citry.nodes import (
                ExprNode, ComponentNode, IfNode, ForNode,
                SlotNode, FillNode, StaticHtmlAttr, ExprHtmlAttr,
                TemplateHtmlAttr, TemplateNode,
            )

            t = parse_template('<c-Card title="Hi">body</c-Card>')
            code = compile_template(t)

            ns = {
                "source": '<c-Card title="Hi">body</c-Card>',
                "ExprNode": ExprNode,
                "ComponentNode": ComponentNode,
                "IfNode": IfNode,
                "ForNode": ForNode,
                "SlotNode": SlotNode,
                "FillNode": FillNode,
                "StaticHtmlAttr": StaticHtmlAttr,
                "ExprHtmlAttr": ExprHtmlAttr,
                "TemplateHtmlAttr": TemplateHtmlAttr,
                "TemplateNode": TemplateNode,
            }
            exec(code, ns)
            body = ns["generate_template"]()
            print(body[0])  # ComponentNode(name='card', attrs=1, body=1 items)

    """
    return _rust.template_parser.compile_template(template, lang)
