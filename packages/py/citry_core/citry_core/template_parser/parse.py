
from citry_core import _rust


def parse_template(
    input: str,
    lang: str | None = None,
    user_rules: dict[str, _rust.template_parser.TagRules] | None = None,
) -> _rust.template_parser.Template:
    """
    Parse a Citry template string into a Template AST.

    Args:
        input: The template string to parse.
        lang: Expression language. One of "python" (default), "js", "php",
            "go", "rust".
        user_rules: Optional dict mapping tag names to TagRules for custom
            attribute/slot validation. Keys must be lowercase tag names
            (e.g. ``"c-my-card"``); tags in the template match the rules
            case-insensitively.

    Returns:
        The parsed Template AST.

    Raises:
        SyntaxError: If the template has invalid syntax.
        ValueError: If an unknown language is specified.

    Examples:
        Basic parsing::

            from citry_core.template_parser import parse_template

            t = parse_template('<p>{{ name }}</p>')
            print(t.used_variables)  # [Token(content='name', ...)]

        With custom tag validation rules::

            from citry_core.template_parser import parse_template, TagRules

            rules = {
                "c-card": TagRules(
                    allowed_attrs=[["title", "c-title"]],
                    required_attrs=[["title", "c-title"]],
                ),
            }
            t = parse_template('<c-card title="Hello"></c-card>', user_rules=rules)

    """
    return _rust.template_parser.parse_template(input, lang, user_rules)
