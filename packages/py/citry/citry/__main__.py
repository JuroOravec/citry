"""
The ``citry`` command-line entry point.

Resolves which engine to run against, then builds and runs the command tree.
With no ``--app`` option the default global engine is used; a leading ``--app
module:attribute`` points the CLI at an explicitly constructed ``Citry`` (the
same ``module:object`` convention web-server entry points use). Registered as
the ``citry`` console script in ``pyproject.toml``.
"""

from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING, NoReturn

from citry.citry import Citry
from citry.citry import citry as default_engine
from citry.command import run
from citry.commands import build_cli

if TYPE_CHECKING:
    from collections.abc import Sequence


def _fail(message: str) -> NoReturn:
    """Print a usage error to stderr and exit with code 2 (argparse's convention)."""
    sys.stderr.write(f"citry: error: {message}\n")
    raise SystemExit(2)


def _import_engine(spec: str) -> Citry:
    """Resolve a ``module:attribute`` spec to the ``Citry`` engine it names."""
    module_path, separator, attribute = spec.partition(":")
    if not separator or not attribute:
        _fail("--app must be 'module:attribute', e.g. 'myproject.app:engine'")
    try:
        engine = getattr(import_module(module_path), attribute)
    except (ImportError, AttributeError) as exc:
        _fail(f"could not import --app target {spec!r}: {exc}")
    if not isinstance(engine, Citry):
        _fail(f"--app target {spec!r} is a {type(engine).__name__}, not a Citry instance")
    return engine


def _resolve_engine(argv: list[str]) -> tuple[Citry, list[str]]:
    """
    Pick the engine to run against, consuming a leading ``--app module:attribute``.

    ``--app`` is recognized only as the first argument (as ``--app VALUE`` or
    ``--app=VALUE``), so it cannot be mistaken for an option of a nested command
    further along the line. With no leading ``--app``, the default global engine
    is used and the arguments are passed through unchanged.
    """
    if argv and argv[0] == "--app":
        if len(argv) < 2:
            _fail("--app requires a value, e.g. --app myproject.app:engine")
        return _import_engine(argv[1]), argv[2:]
    if argv and argv[0].startswith("--app="):
        return _import_engine(argv[0][len("--app=") :]), argv[1:]
    return default_engine, argv


def main(argv: Sequence[str] | None = None) -> int:
    """Run the citry CLI. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    engine, rest = _resolve_engine(args)
    root = build_cli(engine)
    return run(root, rest, citry=engine)


if __name__ == "__main__":
    sys.exit(main())
