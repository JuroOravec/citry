"""Tests for the declarative command model and the runner (``citry/command.py``)."""

# ruff: noqa: ANN, D101, D102, D106, ARG002, PLC0415

import pytest

from citry import CommandArg, CommandArgGroup, ExtensionCommand
from citry.command import build_parser, format_as_ascii_table, run


class TestBuildParser:
    def test_positional_and_flag(self):
        class Greet(ExtensionCommand):
            name = "greet"
            arguments = [
                CommandArg("name"),
                CommandArg(["--shout", "-s"], action="store_true"),
            ]

            def handle(self, **kwargs): ...

        parser = build_parser(Greet)
        ns = parser.parse_args(["world", "--shout"])
        assert ns.name == "world"
        assert ns.shout is True

    def test_typed_option(self):
        class Cmd(ExtensionCommand):
            name = "cmd"
            arguments = [CommandArg(["--count"], type=int, default=1)]

            def handle(self, **kwargs): ...

        ns = build_parser(Cmd).parse_args(["--count", "5"])
        assert ns.count == 5

    def test_group_arguments_parsed(self):
        class Cmd(ExtensionCommand):
            name = "cmd"
            arguments = [
                CommandArgGroup(title="opts", arguments=[CommandArg(["--x"], type=int)]),
            ]

            def handle(self, **kwargs): ...

        ns = build_parser(Cmd).parse_args(["--x", "3"])
        assert ns.x == 3


class TestRun:
    def test_dispatches_handle_with_options(self):
        captured: dict = {}

        class Greet(ExtensionCommand):
            name = "greet"
            arguments = [
                CommandArg("name"),
                CommandArg(["--shout"], action="store_true"),
            ]

            def handle(self, **kwargs):
                captured.update(kwargs)

        code = run(Greet, ["world", "--shout"])
        assert code == 0
        assert captured["name"] == "world"
        assert captured["shout"] is True

    def test_subcommand_dispatch(self):
        seen: list[str] = []

        class Hello(ExtensionCommand):
            name = "hello"

            def handle(self, **kwargs):
                seen.append("hello")

        class Root(ExtensionCommand):
            name = "root"
            subcommands = [Hello]

        run(Root, ["hello"])
        assert seen == ["hello"]

    def test_grouping_command_without_subcommand_prints_help(self, capsys):
        class Leaf(ExtensionCommand):
            name = "leaf"

            def handle(self, **kwargs): ...

        class Group(ExtensionCommand):
            name = "group"
            help = "A grouping command."
            subcommands = [Leaf]

        code = run(Group, [])
        assert code == 0
        # A command with no handle of its own falls back to printing its help,
        # which lists the available subcommands.
        assert "leaf" in capsys.readouterr().out


class TestCommandArg:
    def test_unset_fields_are_dropped(self):
        # Only fields the author set should reach argparse; everything else is
        # left to argparse's own defaults.
        assert CommandArg("name").to_add_argument_kwargs() == {}
        assert CommandArg(["--x"], action="store_true").to_add_argument_kwargs() == {"action": "store_true"}

    def test_invalid_input_exits(self):
        class Cmd(ExtensionCommand):
            name = "cmd"
            arguments = [CommandArg(["--count"], type=int)]

            def handle(self, **kwargs): ...

        # argparse reports a usage error by exiting; the runner does not swallow it.
        with pytest.raises(SystemExit):
            run(Cmd, ["--count", "not-an-int"])


class TestDuplicateCommandNames:
    def test_duplicate_subcommand_names_raise_a_clear_error(self):
        class A(ExtensionCommand):
            name = "dup"

            def handle(self, **kwargs): ...

        class B(ExtensionCommand):
            name = "dup"

            def handle(self, **kwargs): ...

        class Root(ExtensionCommand):
            name = "root"
            subcommands = [A, B]

        # A clear error naming the command, instead of argparse's cryptic
        # "conflicting subparser" raised at build time.
        with pytest.raises(ValueError, match="Duplicate command name 'dup'"):
            run(Root, [])


class TestAsciiTable:
    def test_no_trailing_whitespace(self):
        out = format_as_ascii_table(
            [{"name": "a", "note": "a long value"}, {"name": "bb", "note": "x"}],
            ("name", "note"),
        )
        for line in out.splitlines():
            assert line == line.rstrip()

    def test_data_only_omits_header(self):
        out = format_as_ascii_table([{"name": "a"}], ("name",), include_headers=False)
        assert out == "a"
