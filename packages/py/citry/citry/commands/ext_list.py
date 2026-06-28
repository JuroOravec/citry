"""The ``citry ext list`` command: list the installed extensions."""

from __future__ import annotations

from typing import Any

from citry.command import format_as_ascii_table
from citry.extension import ExtensionCommand


class ExtListCommand(ExtensionCommand):
    """List the extensions installed on the engine."""

    name = "list"
    help = "List the installed extensions."

    def handle(self, **kwargs: Any) -> None:
        # Bound by the runner; absent only if invoked outside the CLI.
        if self.citry is None:
            return
        rows = [{"name": extension.name} for extension in self.citry.extensions._extensions]
        print(format_as_ascii_table(rows, ("name",)))
