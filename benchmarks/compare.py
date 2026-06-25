"""
Compare template-rendering performance across engines at the current checkout.

For every (engine, test type) cell this runner builds a small script from the
matching scenario file in ``packages/py/citry/tests/`` (see ``utils.py`` for
how the file is sliced), runs it in a fresh subprocess per round so no state
leaks between cells, and prints one table per scenario size with ratios
against the Django baseline.

Engines:

- ``django``           - vanilla Django templates (vendored DJC scenario)
- ``django-components``- the DJC component scenario (vendored)
- ``citry``            - the citry port, plain inputs
- ``citry-const``      - a separate scenario file that marks each component's
                         render-invariant literals Const (large scenario only)

Test types (mirroring upstream django-components PR #999):

- ``startup``    - run the whole scenario script: imports, class and template
                   definitions, but no render
- ``import``     - run only the scenario's import section
- ``first``      - one render, template parse/compile included
- ``subsequent`` - one render after a warmup render in the same process

Usage (from the repository root):

    .venv/bin/python benchmarks/compare.py [--size sm] [--rounds 5] [--quick]

IMPORTANT: build the Rust extension in release mode first
(`.venv/bin/maturin develop --release` in packages/py/citry_core). The default
debug build makes citry's Rust-backed paths ~12x slower and invalidates every
citry number. This runner cannot detect the build profile; see README.md.

Results are RELATIVE, not absolute: compare rows within a run, never numbers
across machines or runs. See docs/design/benchmarking.md and benchmarks/README.md.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from utils import get_benchmark_script

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIR = REPO_ROOT / "packages" / "py" / "citry" / "tests"

BASELINE_ENGINE = "django"


@dataclass(frozen=True)
class Engine:
    key: str
    file_stem: str


ENGINES = [
    Engine("django", "test_benchmark_django"),
    Engine("django-components", "test_benchmark_djc"),
    Engine("citry", "test_benchmark_citry"),
    # The Const variant is its own scenario file (per-component Const, not a
    # flag), so it only exists for the large scenario; the small scenario has
    # no render-invariant literals to mark, so its citry-const cell is skipped.
    Engine("citry-const", "test_benchmark_citry_const"),
]

TEST_TYPES = ["startup", "import", "first", "subsequent"]

# Wraps the cell's code so the subprocess reports a single number. The setup
# part runs untimed; only the payload sits between the timer reads.
_TIMING_TEMPLATE = """\
{setup}

import time as _bench_time

_bench_t0 = _bench_time.perf_counter_ns()
{payload}
_bench_t1 = _bench_time.perf_counter_ns()
print("BENCH_NS:", _bench_t1 - _bench_t0)
"""


def scenario_path(engine: Engine, size: str) -> Path:
    suffix = "_small" if size == "sm" else ""
    return SCENARIO_DIR / f"{engine.file_stem}{suffix}.py"


def build_cell_script(engine: Engine, size: str, test_type: str) -> str:
    """Compose the timed script for one (engine, size, test type) cell."""
    path = scenario_path(engine, size)

    if test_type == "import":
        setup = ""
        payload = get_benchmark_script(path, imports_only=True)
    elif test_type == "startup":
        setup = ""
        payload = get_benchmark_script(path)
    else:
        setup = get_benchmark_script(path)
        setup += "\n\nrender_data = gen_render_data()\n"
        if test_type == "subsequent":
            setup += "render(render_data)\n"
        payload = "render(render_data)"

    return _hoist_future_imports(_TIMING_TEMPLATE.format(setup=setup, payload=payload))


def _hoist_future_imports(script: str) -> str:
    """
    Move any ``from __future__ import ...`` lines to the top of the script.

    A scenario file may start with a ``__future__`` import (citry uses one for
    lazy annotations), but the timing wrapper prepends code before the sliced
    payload, which would leave the future import past the first statement (a
    SyntaxError). Hoisting keeps it legal.
    """
    future_lines = []
    other_lines = []
    for line in script.splitlines():
        (future_lines if line.startswith("from __future__ import ") else other_lines).append(line)
    if not future_lines:
        return script
    return "\n".join([*future_lines, *other_lines])


def time_cell(script: str, rounds: int) -> list[int]:
    """Run the cell script in a fresh subprocess per round; return ns timings."""
    times: list[int] = []
    # The scenario files read Path(__file__) (Django's BASE_DIR setting), so
    # they must run from a real file, not `python -c`.
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf8") as handle:
        handle.write(script)
        tmp_path = Path(handle.name)
    try:
        for _ in range(rounds):
            result = subprocess.run(
                [sys.executable, str(tmp_path)],
                check=True,
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
            for line in result.stdout.splitlines():
                if line.startswith("BENCH_NS:"):
                    times.append(int(line.removeprefix("BENCH_NS:")))
                    break
            else:
                msg = f"benchmark subprocess produced no timing line; stdout: {result.stdout!r}"
                raise RuntimeError(msg)
    finally:
        tmp_path.unlink()
    return times


def format_ns(value: float) -> str:
    if value < 1_000_000:
        return f"{value / 1_000:.1f} us"
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.2f} ms"
    return f"{value / 1_000_000_000:.2f} s"


def print_table(size: str, test_types: list[str], results: dict[str, dict[str, float]], rounds: int) -> None:
    """Print one engines-by-test-types table, with ratios against the baseline."""
    name_width = max(len(engine.key) for engine in ENGINES)
    col_width = 22

    print(f"\nScenario '{size}' - median of {rounds} round(s), fresh process per round")
    header = "engine".ljust(name_width) + "".join(t.rjust(col_width) for t in test_types)
    print(header)
    print("-" * len(header))

    for engine in ENGINES:
        cells = results.get(engine.key)
        if cells is None:
            print(engine.key.ljust(name_width) + "  (scenario file missing, skipped)")
            continue
        row = engine.key.ljust(name_width)
        for test_type in test_types:
            value = cells[test_type]
            baseline = results[BASELINE_ENGINE][test_type]
            cell = f"{format_ns(value)} ({value / baseline:.2f}x)"
            row += cell.rjust(col_width)
        print(row)
    print(f"\nRatios are vs the '{BASELINE_ENGINE}' row. Results are relative; never compare across machines or runs.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--size", choices=["sm", "lg"], default="sm", help="scenario size (lg lands in phase 3)")
    parser.add_argument("--rounds", type=int, default=5, help="fresh-process rounds per cell (default 5)")
    parser.add_argument("--quick", action="store_true", help="2 rounds, skip the import column")
    args = parser.parse_args()

    rounds = 2 if args.quick else args.rounds
    test_types = [t for t in TEST_TYPES if not (args.quick and t == "import")]

    print(
        "NOTE: citry numbers are only meaningful with a RELEASE build of citry_core\n"
        "(`.venv/bin/maturin develop --release` in packages/py/citry_core). The default\n"
        "debug build is many times slower on the Rust-backed paths, and this runner\n"
        "cannot detect which build is installed.",
    )

    results: dict[str, dict[str, float]] = {}
    for engine in ENGINES:
        if not scenario_path(engine, args.size).exists():
            continue
        cells: dict[str, float] = {}
        for test_type in test_types:
            script = build_cell_script(engine, args.size, test_type)
            times = time_cell(script, rounds)
            cells[test_type] = statistics.median(times)
            print(f"  measured {engine.key} / {test_type}: {format_ns(cells[test_type])}")
        results[engine.key] = cells

    if BASELINE_ENGINE not in results:
        print(f"Baseline engine '{BASELINE_ENGINE}' has no scenario file for size '{args.size}'; cannot build table.")
        return

    print_table(args.size, test_types, results, rounds)


if __name__ == "__main__":
    main()
