"""Tests for the citry CLI wiring: engine binding, the command tree, and the entry point."""

# ruff: noqa: ANN, D101, D102, D106, ARG002, PLC0415

import pytest

from citry import Citry as _Citry
from citry import CommandArg, Component, Extension, ExtensionCommand
from citry.__main__ import main
from citry.command import run
from citry.commands import build_cli


def _engine_with_command(captured):
    """A Citry whose 'greeter' extension provides a 'greet' command that records its inputs."""

    class Greet(ExtensionCommand):
        name = "greet"
        help = "Greet someone."
        arguments = [CommandArg("who")]

        def handle(self, **kwargs):
            captured["who"] = kwargs["who"]
            captured["citry"] = self.citry

    class Greeter(Extension):
        name = "greeter"
        commands = [Greet]

    return _Citry(extensions=[Greeter]), Greet


class TestEngineBinding:
    def test_handle_receives_bound_engine(self):
        captured: dict = {}
        engine, greet = _engine_with_command(captured)
        run(greet, ["world"], citry=engine)
        assert captured["who"] == "world"
        assert captured["citry"] is engine

    def test_engine_is_none_without_binding(self):
        seen: dict = {}

        class Cmd(ExtensionCommand):
            name = "cmd"

            def handle(self, **kwargs):
                seen["citry"] = self.citry

        run(Cmd, [])
        assert seen["citry"] is None


class TestCommandTree:
    def test_ext_run_dispatches_to_extension_command(self):
        captured: dict = {}
        engine, _ = _engine_with_command(captured)
        code = run(build_cli(engine), ["ext", "run", "greeter", "greet", "world"], citry=engine)
        assert code == 0
        assert captured["who"] == "world"
        assert captured["citry"] is engine

    def test_ext_run_unknown_extension_raises(self):
        engine, _ = _engine_with_command({})
        # 'nope' is not a routing node, so argparse rejects it.
        with pytest.raises(SystemExit):
            run(build_cli(engine), ["ext", "run", "nope", "greet"], citry=engine)

    def test_ext_run_extension_without_command_lists_its_commands(self, capsys):
        engine, _ = _engine_with_command({})
        run(build_cli(engine), ["ext", "run", "greeter"], citry=engine)
        # The routing node has no handle, so it prints help listing its commands.
        assert "greet" in capsys.readouterr().out

    def test_ext_list_lists_extensions(self, capsys):
        engine, _ = _engine_with_command({})
        run(build_cli(engine), ["ext", "list"], citry=engine)
        out = capsys.readouterr().out
        assert "greeter" in out
        assert "dependencies" in out  # the built-in extension


class TestMain:
    def test_default_engine(self, capsys):
        # No --app: the default global engine, which carries only the built-ins.
        assert main(["ext", "list"]) == 0
        assert "dependencies" in capsys.readouterr().out

    def test_app_option_resolves_engine(self, capsys):
        assert main(["--app", "citry.citry:citry", "ext", "list"]) == 0
        assert "dependencies" in capsys.readouterr().out

    def test_app_option_must_be_module_colon_attribute(self):
        with pytest.raises(SystemExit):
            main(["--app", "no-colon-here", "ext", "list"])

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert "citry" in capsys.readouterr().out


class TestListComponents:
    def test_lists_registered_components(self, capsys):
        engine = _Citry()

        class MyButton(Component):
            citry = engine
            template = "<button></button>"

        run(build_cli(engine), ["list"], citry=engine)
        out = capsys.readouterr().out
        assert "my-button" in out  # the kebab-case registered name
        assert "MyButton" in out  # the class column


class TestCreateComponent:
    def test_writes_component_file(self, tmp_path):
        engine = _Citry()
        code = run(build_cli(engine), ["create", "MyButton", "--path", str(tmp_path)], citry=engine)
        assert code == 0
        created = tmp_path / "my_button.py"
        assert created.exists()
        text = created.read_text()
        assert "class MyButton(Component):" in text
        # The scaffold must be valid Python.
        compile(text, str(created), "exec")

    def test_name_in_any_case_yields_pascal_class_and_snake_file(self, tmp_path):
        engine = _Citry()
        run(build_cli(engine), ["create", "my-fancy-card", "--path", str(tmp_path)], citry=engine)
        created = tmp_path / "my_fancy_card.py"
        assert created.exists()
        assert "class MyFancyCard(Component):" in created.read_text()

    def test_refuses_to_overwrite(self, tmp_path):
        engine = _Citry()
        existing = tmp_path / "my_button.py"
        existing.write_text("# existing\n")
        with pytest.raises(SystemExit):
            run(build_cli(engine), ["create", "MyButton", "--path", str(tmp_path)], citry=engine)
        assert existing.read_text() == "# existing\n"  # left untouched

    def test_preserves_pascalcase_acronym(self, tmp_path):
        engine = _Citry()
        run(build_cli(engine), ["create", "HTTPServer", "--path", str(tmp_path)], citry=engine)
        created = tmp_path / "http_server.py"
        assert created.exists()
        # The user's acronym casing is kept on the class; the file is snake_case.
        assert "class HTTPServer(Component):" in created.read_text()

    def test_rejects_python_keyword_name(self, tmp_path):
        engine = _Citry()
        with pytest.raises(SystemExit):
            run(build_cli(engine), ["create", "True", "--path", str(tmp_path)], citry=engine)
        assert list(tmp_path.iterdir()) == []  # nothing written

    def test_rejects_dunder_module_name(self, tmp_path):
        engine = _Citry()
        with pytest.raises(SystemExit):
            run(build_cli(engine), ["create", "__init__", "--path", str(tmp_path)], citry=engine)
        assert not (tmp_path / "__init__.py").exists()

    def test_path_that_is_a_file_fails_cleanly(self, tmp_path):
        engine = _Citry()
        blocker = tmp_path / "blocker"
        blocker.write_text("x")  # a file where the command expects a directory
        with pytest.raises(SystemExit):
            run(build_cli(engine), ["create", "MyButton", "--path", str(blocker)], citry=engine)


class TestAppHardening:
    def test_app_equals_form(self, capsys):
        assert main(["--app=citry.citry:citry", "ext", "list"]) == 0
        assert "dependencies" in capsys.readouterr().out

    def test_unresolvable_module_fails_cleanly(self, capsys):
        with pytest.raises(SystemExit):
            main(["--app", "no.such.module:engine", "ext", "list"])
        assert "could not import" in capsys.readouterr().err

    def test_non_citry_target_fails_cleanly(self, capsys):
        # The Citry *class*, not an instance.
        with pytest.raises(SystemExit):
            main(["--app", "citry.citry:Citry", "ext", "list"])
        assert "not a Citry instance" in capsys.readouterr().err

    def test_app_after_subcommand_is_not_hijacked(self):
        # A non-leading --app must reach the real parser (which rejects it here),
        # not be swallowed as engine selection.
        with pytest.raises(SystemExit):
            main(["ext", "list", "--app", "citry.citry:citry"])
