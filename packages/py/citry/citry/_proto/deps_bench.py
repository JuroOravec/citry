"""
Benchmark: dependency collection + merge (first-seen dedup) in Python vs Rust.

The dependencies extension reduces to one operation on the hot path: collapse the
collected ``DependencyRecord``s to their distinct set, keeping first-seen
(document) order. Python does this with a ``dict`` (``dict.fromkeys`` at resolve,
``dict.update`` at each merge), which is C-backed. This compares that against a
Rust reimplementation, two ways:

- ``dedup`` columns: the records are built in Python and handed to Rust, so Rust
  pays the cost of marshalling them across the boundary (which the in-process
  ``dict.fromkeys`` does not). This is "move only the dedup to Rust".
- ``native`` columns: the records are built AND deduped entirely in Rust, with no
  per-call marshalling. This is the speed the choreography would have if the
  records already lived in Rust (a full render-in-Rust port). Note the record
  fields themselves still come from Python data in reality, so this is an upper
  bound on the movable part, not a drop-in.

Run on the release build::

    cd packages/py/citry_core && uv run maturin develop --release
    python -m citry._proto.deps_bench
"""

from __future__ import annotations

import math
import time
from functools import partial
from typing import TYPE_CHECKING

from citry_core._rust import deps_proto

if TYPE_CHECKING:
    from collections.abc import Callable

# A representative record: (class_id, component_id, js_vars_hash, css_vars_hash).
_Record = tuple[str, str, None, None]


def _flattened(n_distinct: int, n_levels: int) -> list[_Record]:
    """A record per component, re-emitted across ``n_levels`` bubble-up levels."""
    base: list[_Record] = [(f"Cls{i}", f"c{i}", None, None) for i in range(n_distinct)]
    out: list[_Record] = []
    for _ in range(n_levels):
        out.extend(base)
    return out


def _py_native_collect(n_distinct: int, n_levels: int) -> int:
    """Build and dedup the records entirely in Python (the native comparison)."""
    seen: dict[_Record, None] = {}
    for _ in range(n_levels):
        for i in range(n_distinct):
            seen[(f"Cls{i}", f"c{i}", None, None)] = None
    return len(seen)


def best_per_call(fn: Callable[[], object], *, batch: int, samples: int) -> float:
    """Best-of-``samples`` per-call seconds, each sample timing ``batch`` calls."""
    best = math.inf
    for _ in range(samples):
        start = time.perf_counter()
        for _ in range(batch):
            fn()
        best = min(best, (time.perf_counter() - start) / batch)
    return best


def run() -> int:
    """Run every scenario, check correctness, print timings. Return an exit code."""
    scenarios: list[tuple[str, int, int]] = [
        ("realistic 71x40", 71, 40),
        ("deep 71x2000", 71, 2000),
        ("wide 1000x10", 1000, 10),
    ]

    print(f"{'scenario':<16}{'total':>9}{'distinct':>9}{'py dedup':>11}{'rust dedup':>12}{'speedup':>9}")
    print("-" * 66)
    all_ok = True
    native_rows: list[tuple[str, float, float]] = []
    for name, n_distinct, n_levels in scenarios:
        records = _flattened(n_distinct, n_levels)
        total = len(records)

        # Correctness: same distinct set, same order.
        py_out = list(dict.fromkeys(records))
        rust_out = deps_proto.dedup_first_seen(records)
        ok = py_out == rust_out
        all_ok = all_ok and ok

        batch = max(1, 400_000 // total)
        py_t = best_per_call(partial(lambda r: list(dict.fromkeys(r)), records), batch=batch, samples=20)
        rust_t = best_per_call(partial(deps_proto.dedup_first_seen, records), batch=batch, samples=20)
        speed = py_t / rust_t if rust_t else float("inf")
        flag = "" if ok else "  MISMATCH"
        print(f"{name:<16}{total:>9}{n_distinct:>9}{py_t * 1e6:>10.1f}u{rust_t * 1e6:>11.1f}u{speed:>8.2f}x{flag}")

        # Native: build + dedup, Python vs Rust, no marshalling either side.
        pn = best_per_call(partial(_py_native_collect, n_distinct, n_levels), batch=batch, samples=20)
        rn = best_per_call(partial(deps_proto.bench_native_collect, n_distinct, n_levels), batch=batch, samples=20)
        native_rows.append((name, pn, rn))

    print()
    print(f"{'native build+dedup':<16}{'':>18}{'py':>11}{'rust':>12}{'speedup':>9}")
    print("-" * 66)
    for name, pn, rn in native_rows:
        speed = pn / rn if rn else float("inf")
        print(f"{name:<16}{'':>18}{pn * 1e6:>10.1f}u{rn * 1e6:>11.1f}u{speed:>8.2f}x")

    print("-" * 66)
    if not all_ok:
        print("FAIL: a dedup result did not match Python")
        return 1
    print("OK: Rust dedup matches Python dict.fromkeys on every scenario")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
