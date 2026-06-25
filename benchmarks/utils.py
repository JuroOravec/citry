"""
Helpers shared by the benchmark runners (docs/design/benchmarking.md).

The benchmark scenario files live in ``packages/py/citry/tests/`` as
``test_benchmark_*.py``. Each is a self-contained script with two section
markers (the same convention as upstream django-components, PR #999):

- ``IMPORTS END`` separates the imports from the rest, so the import cost can
  be measured on its own.
- ``TESTS START`` separates the benchmarked code from its pytest section,
  which must never run in a benchmark process.

The runners never import the scenario files; they read them as source strings
and slice at the markers. That keeps the benchmark process free of pytest and
of the caller's import state.
"""

from __future__ import annotations

from pathlib import Path

TESTS_START_MARKER = "# ----------- TESTS START ------------ #"
IMPORTS_END_MARKER = "# ----------- IMPORTS END ------------ #"


def get_benchmark_script(file_path: str | Path, *, imports_only: bool = False) -> str:
    """
    Read a benchmark scenario file and slice it into a runnable script.

    Args:
        file_path: Path to a ``test_benchmark_*.py`` scenario file.
        imports_only: Return only the import section (for measuring import
            cost). Everything after the ``IMPORTS END`` marker is dropped.

    Returns:
        The script source, with the pytest section always removed.

    """
    contents = Path(file_path).read_text(encoding="utf8")
    contents = contents.split(TESTS_START_MARKER)[0]

    if imports_only:
        contents = contents.split(IMPORTS_END_MARKER)[0]

    return contents
