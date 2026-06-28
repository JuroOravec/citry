"""The ``citry create`` command: scaffold a new component file."""

from __future__ import annotations

import keyword
import re
from pathlib import Path
from typing import Any

from citry.command import CommandArg, style_success, style_warning
from citry.extension import ExtensionCommand
from citry.util.misc import snake_to_pascal

# The starting point a new component file is written from. The class name is
# derived from the command's ``name`` argument; the sentinel below is swapped for
# the real class name. Authored with the same multiline ``template`` string
# components use in practice.
_SCAFFOLD = '''\
"""A citry component."""

from citry import Component


class MyComponent(Component):
    class Kwargs:
        title: str

    def template_data(self, kwargs, slots):
        return {"title": kwargs.title}

    template = """
      <div>
        <h1>{{ title }}</h1>
      </div>
    """
'''


def _to_snake(name: str) -> str:
    """
    Convert a component name in any common case to snake_case (acronym-aware).

    ``MyButton`` and ``my-button`` both become ``my_button``; ``HTTPServer``
    becomes ``http_server`` (the same boundary rules the registry uses to derive
    a component's kebab name).
    """
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", spaced)
    return spaced.replace("-", "_").replace(" ", "_").lower()


class CreateCommand(ExtensionCommand):
    """Scaffold a new component file."""

    name = "create"
    help = "Scaffold a new component file."
    arguments = (
        CommandArg("name", help="The component name, e.g. MyButton."),
        CommandArg(
            ["--path", "-p"],
            default=".",
            help="Directory to create the file in (default: the current directory).",
        ),
    )

    def handle(self, **kwargs: Any) -> None:
        raw_name = kwargs["name"]
        file_stem = _to_snake(raw_name)
        # Keep an already-PascalCase name verbatim so acronyms like ``HTTPServer``
        # survive; otherwise build PascalCase from the snake/kebab form.
        class_name = raw_name if raw_name.isidentifier() and raw_name[:1].isupper() else snake_to_pascal(file_stem)

        if not class_name.isidentifier() or keyword.iskeyword(class_name):
            print(style_warning(f"{raw_name!r} is not a usable component name."))
            raise SystemExit(1)
        if file_stem.startswith("__"):
            # A dunder stem (e.g. from ``__init__``) would target a package's own
            # module; refuse rather than clobber it.
            print(style_warning(f"{raw_name!r} maps to the reserved module name {file_stem!r}."))
            raise SystemExit(1)

        directory = Path(kwargs["path"])
        file_path = directory / f"{file_stem}.py"
        if file_path.exists():
            print(style_warning(f"{file_path} already exists; not overwriting."))
            raise SystemExit(1)

        try:
            directory.mkdir(parents=True, exist_ok=True)
            file_path.write_text(_SCAFFOLD.replace("MyComponent", class_name))
        except OSError as exc:
            print(style_warning(f"Could not write {file_path}: {exc}"))
            raise SystemExit(1) from exc

        print(style_success(f"Created {file_path}"))
