"""
Find and import a project's component modules.

A component registers itself with its ``Citry`` instance when its class body
runs (the metaclass does it; see ``citry/component.py``). So the only thing
needed to "discover" components is to make sure their ``.py`` files get
imported. Autodiscovery does exactly that: it walks the directories you gave
``Citry(dirs=...)``, turns each ``.py`` file into an import path, and imports
it. Defining the classes is what registers them.

The directories must be importable, i.e. each one (or a parent of it) is on
Python's import path (``sys.path`` / ``PYTHONPATH``). That is how a file path
such as ``/proj/components/card.py`` is turned into the import name
``components.card`` that Python would use for it. Anchoring on the import path
(rather than importing a file by its location) keeps every component's identity
the one Python already knows, which the cache keys and script URLs built from it
rely on. A directory that holds component modules but is not importable raises a
clear error rather than guessing.

Triggered from ``Citry`` (the ``autodiscover`` setting runs it once on first
use, and ``Citry.autodiscover()`` runs it on demand); this module provides just
the discovery mechanics (its only citry dependency is the shared logger).
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from citry.util.logger import logger

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from types import ModuleType


def import_component_modules(dirs: Sequence[Path]) -> list[str]:
    """
    Import every component module under ``dirs`` and register its components.

    Returns the dotted import paths of the modules, in a stable order. Importing
    a module runs its code, and defining each component class registers it (the
    metaclass does that). Python imports a module only once per process, so a
    module that was already loaded is not re-run; for those, this re-registers
    the components directly (see ``_register_existing_components``). The end
    state is the same whether or not the modules were loaded beforehand, which is
    what lets a re-scan after ``Citry.clear()`` rebuild the registry. Safe to
    call more than once.

    Raises ``ValueError`` if a directory contains component modules but is not
    on the Python import path.
    """
    module_names = find_component_modules(dirs)
    logger.debug("Autodiscovery found %d component module(s) under %d dir(s)", len(module_names), len(dirs))
    for module_name in module_names:
        already_loaded = module_name in sys.modules
        logger.debug("Importing component module %s", module_name)
        module = import_module(module_name)
        if already_loaded:
            _register_existing_components(module)
    return module_names


def _register_existing_components(module: ModuleType) -> None:
    """
    Register the component classes defined in an already-imported module.

    On a module's first import, defining each component class registers it. But
    Python imports a module only once per process, so when discovery reaches one
    that is already loaded, that registration does not happen again. This walks
    the module's own component classes and registers any that its ``Citry``
    instance is missing, so a re-scan (for example after ``Citry.clear()``)
    rebuilds the registry exactly as the first scan did. A class that is still
    registered is skipped, so this is safe to run repeatedly.

    Only classes *defined* in this module are considered (a class imported from
    elsewhere is registered when its own module is scanned), and each is
    registered with the instance it is bound to.
    """
    from citry.component import Component  # noqa: PLC0415 - importing at module top would cycle

    for value in vars(module).values():
        if (
            isinstance(value, type)
            and value is not Component
            and issubclass(value, Component)
            and value.__module__ == module.__name__
            and not value.citry.registry._has_class(value)
        ):
            value.citry.register(value)


def find_component_modules(dirs: Sequence[Path]) -> list[str]:
    """
    The dotted import paths of every component module under ``dirs``.

    Finds the files (see ``_iter_py_files`` for which files count) and maps each
    to the import name Python would use for it. The result is de-duplicated and
    in a stable order, so the same project always discovers the same modules in
    the same sequence. Does not import anything.

    Raises ``ValueError`` if a discovered file is not on the Python import path.
    """
    module_names: list[str] = []
    seen: set[str] = set()
    for directory in dirs:
        for path in _iter_py_files(directory):
            module_name = _path_to_module(path)
            if module_name not in seen:
                seen.add(module_name)
                module_names.append(module_name)
    return module_names


def _iter_py_files(directory: Path) -> Iterator[Path]:
    """
    Yield the ``.py`` files under ``directory`` that count as component modules.

    Files and subdirectories whose name starts with an underscore are skipped
    (so private helpers and dunder-named caches are left alone), with the one
    exception of ``__init__.py`` (a package's init is part of its public path).
    A path that is not a directory yields nothing, so an asset-only ``dirs``
    entry simply contributes no modules. Results are sorted for a stable order.
    """
    if not directory.is_dir():
        return
    for path in sorted(directory.rglob("*.py")):
        rel_parts = path.relative_to(directory).parts
        # A leading underscore on any parent directory hides the whole subtree.
        if any(part.startswith("_") for part in rel_parts[:-1]):
            continue
        name = rel_parts[-1]
        if name.startswith("_") and name != "__init__.py":
            continue
        yield path


def _path_to_module(path: Path) -> str:
    """
    The dotted import name Python would use for the file at ``path``.

    The import name is the file's location relative to whichever import-path
    entry contains it. When more than one entry contains the file, the longest
    (most specific) one wins, which gives the shortest import name. A package's
    ``__init__.py`` maps to the package itself.

    Raises ``ValueError`` if no import-path entry contains the file, naming the
    fix (put the directory, or a parent, on ``sys.path``/``PYTHONPATH``).
    """
    resolved = path.resolve()

    anchor: Path | None = None
    for entry in sys.path:
        # An empty entry means "the current working directory".
        entry_path = Path(entry) if entry else Path.cwd()
        try:
            entry_path = entry_path.resolve()
        except OSError:
            continue
        # When several entries contain the file, the longest (most specific) one
        # wins, giving the shortest import name.
        contains_file = entry_path == resolved or entry_path in resolved.parents
        more_specific = anchor is None or len(entry_path.parts) > len(anchor.parts)
        if contains_file and more_specific:
            anchor = entry_path

    if anchor is None:
        msg = (
            f"Cannot import the component module {str(path)!r}: its directory is not on "
            f"the Python import path, so it has no import name. Add the directory (or a "
            f"parent of it) to sys.path / PYTHONPATH, or turn autodiscovery off "
            f"(Citry(autodiscover=False))."
        )
        raise ValueError(msg)

    parts = resolved.relative_to(anchor).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        # The anchor is the file's own package init at an import-path root; there
        # is no name to import beyond the root itself. Nothing to do.
        msg = (
            f"Cannot import the component module {str(path)!r}: it sits directly on an "
            f"import-path root and has no import name of its own."
        )
        raise ValueError(msg)
    return ".".join(parts)
