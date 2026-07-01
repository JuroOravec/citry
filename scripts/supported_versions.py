# ruff: noqa: T201
"""
Keep citry's declared Python-version support honest against reality.

citry states which Python versions it supports in a few places:

- ``requires-python`` and the ``Programming Language :: Python :: 3.x``
  classifiers in ``packages/py/citry/pyproject.toml`` and
  ``packages/py/citry_core/pyproject.toml``
- the test matrix in ``.github/workflows/py--tests.yml``

This script compares those against the Python versions that are still supported
upstream, read from https://endoflife.date/api/python.json (a stable JSON feed
of release and end-of-life dates), so there is no fragile HTML scraping.

Commands:
    check     Report where the declared versions drift from the versions still
              supported upstream. Exits 0 in sync, 1 on drift, 2 on a fetch
              error. The scheduled workflow opens a tracking issue on drift.
    generate  Print the current recommended version list and the exact snippets
              to paste into each file above.

Usage:
    python scripts/supported_versions.py check
    python scripts/supported_versions.py generate
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
ENDOFLIFE_URL = "https://endoflife.date/api/python.json"

PyVersion = tuple[int, int]

# Where citry encodes its supported Python versions.
PYPROJECTS = [
    REPO_ROOT / "packages" / "py" / "citry" / "pyproject.toml",
    REPO_ROOT / "packages" / "py" / "citry_core" / "pyproject.toml",
]
TESTS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "py--tests.yml"

_CLASSIFIER_RE = re.compile(r"Programming Language :: Python :: (\d+)\.(\d+)")
_MATRIX_RE = re.compile(r"python-version:\s*\[([^\]]*)\]")
_QUOTED_VERSION_RE = re.compile(r'"(\d+)\.(\d+)"')


def _fmt(versions: set[PyVersion]) -> str:
    return ", ".join(f"{major}.{minor}" for major, minor in sorted(versions))


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _is_past(iso_date: object, today: date) -> bool:
    return isinstance(iso_date, str) and date.fromisoformat(iso_date) <= today


def fetch_supported_python() -> set[PyVersion]:
    """The (major, minor) Python versions that are released and not yet end-of-life."""
    # The URL is a fixed https literal, not user input, so the opens are safe.
    req = Request(ENDOFLIFE_URL, headers={"User-Agent": "citry-supported-versions"})  # noqa: S310
    with urlopen(req) as response:  # noqa: S310
        cycles = json.loads(response.read())
    today = datetime.now(tz=timezone.utc).date()
    supported: set[PyVersion] = set()
    for cycle in cycles:
        parts = str(cycle.get("cycle", "")).split(".")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            continue
        eol = cycle.get("eol")
        not_eol = eol is False or (isinstance(eol, str) and date.fromisoformat(eol) > today)
        if _is_past(cycle.get("releaseDate"), today) and not_eol:
            supported.add((int(parts[0]), int(parts[1])))
    return supported


def declared_classifiers(pyproject: Path) -> set[PyVersion]:
    return {(int(a), int(b)) for a, b in _CLASSIFIER_RE.findall(pyproject.read_text())}


def matrix_versions(workflow: Path) -> set[PyVersion]:
    match = _MATRIX_RE.search(workflow.read_text())
    if not match:
        return set()
    return {(int(a), int(b)) for a, b in _QUOTED_VERSION_RE.findall(match.group(1))}


def _diff_lines(label: str, declared: set[PyVersion], supported: set[PyVersion]) -> list[str]:
    lines = []
    if stale := declared - supported:
        lines.append(f"- {label}: drop {_fmt(stale)} (no longer supported upstream)")
    if missing := supported - declared:
        lines.append(f"- {label}: add {_fmt(missing)} (now supported upstream)")
    return lines


def cmd_check() -> int:
    try:
        supported = fetch_supported_python()
    except (URLError, ValueError) as exc:
        print(f"error: could not fetch Python version data: {exc}")
        return 2
    if not supported:
        print("error: upstream returned no supported Python versions")
        return 2

    problems: list[str] = []
    for pyproject in PYPROJECTS:
        problems += _diff_lines(f"{_rel(pyproject)} classifiers", declared_classifiers(pyproject), supported)
    problems += _diff_lines(f"{_rel(TESTS_WORKFLOW)} matrix", matrix_versions(TESTS_WORKFLOW), supported)

    if not problems:
        print(f"In sync: citry supports the current Python versions ({_fmt(supported)}).")
        return 0

    print("Supported Python versions have drifted from what citry declares.\n")
    print(f"Supported upstream today: {_fmt(supported)}\n")
    print("\n".join(problems))
    print("\nRun `python scripts/supported_versions.py generate` for the exact edits.")
    return 1


def cmd_generate() -> int:
    try:
        supported = sorted(fetch_supported_python())
    except (URLError, ValueError) as exc:
        print(f"error: could not fetch Python version data: {exc}")
        return 2
    versions = [f"{major}.{minor}" for major, minor in supported]
    floor = versions[0]

    print(f"Recommended supported Python versions: {', '.join(versions)}\n")
    print("requires-python (both pyproject.toml files):")
    print(f'    requires-python = ">={floor}, <4.0"\n')
    print("classifiers (both pyproject.toml files):")
    for version in versions:
        print(f'    "Programming Language :: Python :: {version}",')
    matrix = ", ".join(f'"{version}"' for version in versions)
    print("\n.github/workflows/py--tests.yml matrix:")
    print(f"    python-version: [{matrix}]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Track citry's supported Python versions.")
    parser.add_argument("command", choices=["check", "generate"])
    args = parser.parse_args()
    return cmd_check() if args.command == "check" else cmd_generate()


if __name__ == "__main__":
    raise SystemExit(main())
