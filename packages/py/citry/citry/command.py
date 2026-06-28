"""
The command-line interface: declarative commands and the runner that dispatches them.

An extension declares CLI commands by listing
:class:`~citry.extension.ExtensionCommand` subclasses in ``Extension.commands``.
This module turns those declarations into a runnable :mod:`argparse` parser
(:func:`build_parser`) and dispatches the parsed arguments to the matching
command's ``handle`` method (:func:`run`).

The declarations are plain data: a command's arguments are described by the
:class:`CommandArg` and :class:`CommandArgGroup` dataclasses, whose field names
match ``argparse.ArgumentParser.add_argument`` so they can be handed straight to
argparse. Keeping the model as data (rather than imperative parser-building code)
means one command definition can feed more than one front end later, for example
a Model Context Protocol tool schema. The full design is in
``docs/design/extension_commands.md``.

This module uses only the standard library (``argparse`` and ``dataclasses``);
importing it pulls in no third-party code.
"""

from __future__ import annotations

import os
import sys
from argparse import Action, ArgumentParser
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from argparse import _ArgumentGroup
    from collections.abc import Callable, Sequence

    from citry.citry import Citry
    from citry.extension import ExtensionCommand


# The ``argparse`` ``action`` values a command argument may use (the common subset).
CommandAction = Literal[
    "append",
    "append_const",
    "count",
    "extend",
    "store",
    "store_const",
    "store_true",
    "store_false",
    "version",
]


class CommandHandler(Protocol):
    """The shape of a command's ``handle``: called with the parsed options as keywords."""

    def __call__(self, *args: Any, **kwargs: Any) -> None: ...


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    """
    Return ``values`` without the keys whose value is ``None``.

    A :class:`CommandArg` leaves every unset field as ``None``; dropping those
    keeps them out of the argparse call so argparse applies its own defaults.
    """
    return {key: value for key, value in values.items() if value is not None}


@dataclass
class CommandArg:
    """
    One positional argument or option, mirroring ``ArgumentParser.add_argument``.

    Every field maps to the matching ``add_argument`` keyword, and
    :func:`build_parser` passes them through unchanged, so the field names must
    stay aligned with argparse.
    """

    name_or_flags: str | Sequence[str]
    """A positional name (``"path"``) or a list of option flags (``["--shout", "-s"]``)."""
    action: CommandAction | Action | None = None
    nargs: int | Literal["*", "+", "?"] | None = None
    const: Any = None
    default: Any = None
    type: Callable[[str], Any] | None = None
    choices: Sequence[Any] | None = None
    required: bool | None = None
    help: str | None = None
    metavar: str | None = None
    dest: str | None = None
    version: str | None = None

    def to_add_argument_kwargs(self) -> dict[str, Any]:
        """
        The ``add_argument`` keywords for this argument, minus ``name_or_flags``.

        ``name_or_flags`` is passed positionally by :func:`build_parser`, so it is
        not included here; unset (``None``) fields are dropped.
        """
        return _drop_none(
            {
                "action": self.action,
                "nargs": self.nargs,
                "const": self.const,
                "default": self.default,
                "type": self.type,
                "choices": self.choices,
                "required": self.required,
                "help": self.help,
                "metavar": self.metavar,
                "dest": self.dest,
                "version": self.version,
            },
        )


@dataclass
class CommandArgGroup:
    """
    A titled group of arguments, mirroring ``ArgumentParser.add_argument_group``.

    Place one in a command's ``arguments`` list to group related options together
    in the ``--help`` output.
    """

    title: str | None = None
    description: str | None = None
    arguments: Sequence[CommandArg] = ()


@dataclass
class CommandSubcommand:
    """
    How a command appears when nested under a parent, mirroring ``add_subparsers().add_parser``.

    A command sets this as its ``subparser_input`` to customize its entry in the
    parent's subcommand list (for example a different help line or program name).
    """

    prog: str | None = None
    help: str | None = None
    description: str | None = None
    metavar: str | None = None

    def to_add_parser_kwargs(self) -> dict[str, Any]:
        """The ``add_parser`` keywords for this subcommand entry (unset fields dropped)."""
        return _drop_none(
            {
                "prog": self.prog,
                "help": self.help,
                "description": self.description,
                "metavar": self.metavar,
            },
        )


def _add_argument(parser: ArgumentParser | _ArgumentGroup, arg: CommandArg) -> None:
    flags = [arg.name_or_flags] if isinstance(arg.name_or_flags, str) else list(arg.name_or_flags)
    parser.add_argument(*flags, **arg.to_add_argument_kwargs())


def build_parser(command: type[ExtensionCommand], *, citry: Citry | None = None) -> ArgumentParser:
    """
    Build an ``ArgumentParser`` for ``command`` and its subcommands.

    The parser carries enough state to dispatch after parsing: each (sub)parser
    stores the command instance it stands for, so :func:`run` can tell which
    nested command the user actually invoked. When ``citry`` is given, it is bound
    to every command instance as ``self.citry`` so a command's ``handle`` can
    reach the engine's registry and extensions.
    """
    parser = ArgumentParser(prog=command.name, description=command.help or None)
    _populate_parser(parser, command, citry)
    return parser


def _populate_parser(parser: ArgumentParser, command: type[ExtensionCommand], citry: Citry | None) -> None:
    instance = command()
    # Bind the engine to the command instance so its handle can reach the
    # registry and extensions (mirrors how ``Extension.citry`` is bound).
    instance.citry = citry
    # Stash the matched command instance and its parser into the parse result, so
    # the runner can recover which (sub)command was invoked after parse_args().
    parser.set_defaults(_command=instance, _parser=parser)

    for arg in command.arguments:
        if isinstance(arg, CommandArgGroup):
            group = parser.add_argument_group(**_drop_none({"title": arg.title, "description": arg.description}))
            for grouped in arg.arguments:
                _add_argument(group, grouped)
        else:
            _add_argument(parser, arg)

    if command.subcommands:
        subparsers = parser.add_subparsers(title="subcommands")
        seen: set[str] = set()
        for subcommand in command.subcommands:
            # Two subcommands sharing a name would make argparse raise a cryptic
            # "conflicting subparser" error; catch it here with a clear message
            # that names the offending command.
            if subcommand.name in seen:
                msg = f"Duplicate command name {subcommand.name!r} under {command.name!r}"
                raise ValueError(msg)
            seen.add(subcommand.name)
            add_parser_kwargs: dict[str, Any] = {}
            if subcommand.subparser_input is not None:
                add_parser_kwargs = subcommand.subparser_input.to_add_parser_kwargs()
            # The command's own help doubles as the subcommand's help line and
            # the nested parser's description, unless subparser_input overrode them.
            add_parser_kwargs.setdefault("help", subcommand.help or None)
            add_parser_kwargs.setdefault("description", subcommand.help or None)
            subparser = subparsers.add_parser(subcommand.name, **_drop_none(add_parser_kwargs))
            _populate_parser(subparser, subcommand, citry)


def run(command: type[ExtensionCommand], argv: Sequence[str], *, citry: Citry | None = None) -> int:
    """
    Build ``command``'s parser, parse ``argv``, and dispatch to the matched command.

    A command that defines ``handle`` runs it with the parsed options as keyword
    arguments; a command that only groups subcommands (no ``handle``) prints its
    help instead. ``citry`` is bound to each command instance as ``self.citry``.
    Returns a process exit code (``0`` on success). Invalid input is handled by
    argparse, which prints a usage error and exits.

    ``handle`` receives every parsed option, including any declared on parent
    commands, so it should accept ``**kwargs`` (as the base signature and the
    scaffolded commands do) rather than a fixed parameter list.
    """
    parser = build_parser(command, citry=citry)
    options = vars(parser.parse_args(list(argv)))
    matched: ExtensionCommand | None = options.pop("_command", None)
    matched_parser: ArgumentParser = options.pop("_parser", parser)

    handler = getattr(matched, "handle", None)
    if handler is not None:
        handler(**options)
        return 0
    matched_parser.print_help()
    return 0


def format_as_ascii_table(
    rows: list[dict[str, Any]],
    headers: Sequence[str],
    *,
    include_headers: bool = True,
) -> str:
    """
    Render ``rows`` as a left-aligned ASCII table with the given ``headers``.

    Each row is a dict keyed by header name; a missing key renders as an empty
    cell. With ``include_headers=False`` only the data rows are returned, which
    suits output meant to be piped into another tool.
    """
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(str(row.get(header, ""))))

    # The separator spans the full table width; the printed header and data rows
    # are right-stripped so they carry no trailing pad (awkward to diff or copy).
    full_width = len("  ".join(f"{header:<{widths[header]}}" for header in headers))
    header_line = "  ".join(f"{header:<{widths[header]}}" for header in headers).rstrip()
    separator = "=" * full_width
    data_lines = [
        "  ".join(f"{row.get(header, '')!s:<{widths[header]}}" for header in headers).rstrip() for row in rows
    ]
    if include_headers:
        return "\n".join([header_line, separator, *data_lines])
    return "\n".join(data_lines)


def _color_enabled() -> bool:
    """Whether to emit ANSI color: only on a real terminal, and never under ``NO_COLOR``."""
    # https://no-color.org/ : any non-empty NO_COLOR disables color.
    return not os.environ.get("NO_COLOR") and sys.stdout.isatty()


def style_success(message: str) -> str:
    """Wrap ``message`` in ANSI green when writing to a color terminal, else return it plain."""
    return f"\033[92m{message}\033[0m" if _color_enabled() else message


def style_warning(message: str) -> str:
    """Wrap ``message`` in ANSI yellow when writing to a color terminal, else return it plain."""
    return f"\033[93m{message}\033[0m" if _color_enabled() else message
