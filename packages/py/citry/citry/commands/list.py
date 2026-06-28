"""The ``citry list`` command: list the registered components."""

from __future__ import annotations

from typing import Any

from citry.command import format_as_ascii_table
from citry.extension import ExtensionCommand


class ListCommand(ExtensionCommand):
    """List the components registered on the engine."""

    name = "list"
    help = "List the registered components."

    def handle(self, **kwargs: Any) -> None:
        # Bound by the runner; absent only if invoked outside the CLI.
        if self.citry is None:
            return
        # Reading ``components`` runs autodiscovery first, so a project's
        # components are imported and registered before they are listed.
        rows = [{"name": name, "class": cls.__name__} for name, cls in self.citry.components.items()]
        print(format_as_ascii_table(rows, ("name", "class")))
