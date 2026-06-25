"""
A/B harness: Rust render-plan walk vs the Python ``_render_body`` walk.

Runs representative body shapes through both walks, asserts the output is
byte-identical, and reports best-of-N per-call wall-clock for each. The plan and
the node list are built once and held on both sides, so only the walk itself is
timed (the per-expression evaluator is the same compiled object on both paths).

This reproduces the methodology of the June throwaway prototype
(docs/design/performance.md section 6.7) and extends it across body shapes.

Run it with the release build for meaningful numbers::

    cd packages/py/citry_core && uv run maturin develop --release
    python -m citry._proto.ab_harness
"""

from __future__ import annotations

import math
import time
from functools import partial
from typing import TYPE_CHECKING

from markupsafe import Markup

from citry import Citry, Component
from citry._proto.render_plan_runtime import (
    compile_node_list,
    compile_plan,
    make_context,
    python_drive,
    python_render,
    real_render,
    rust_drive,
    rust_render,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

# A spread of scalar values that exercises every escaping/attribute branch:
# markup characters, an ampersand, both quote kinds, a plain string, a number,
# ``None`` (renders empty / omits the attribute), ``True``/``False`` (bare /
# omitted attribute), and a trusted ``Markup`` (passes through unescaped).
_VALUES: tuple[Any, ...] = (
    "<b>tag</b>",
    "a & b",
    "quote\"and'apostrophe",
    "plain text",
    42,
    None,
    True,
    False,
    Markup("<em>trusted</em>"),
)


def _interp(name: str) -> str:
    """A ``{{ name }}`` interpolation, built without f-string brace gymnastics."""
    return "{{ " + name + " }}"


def make_expr_heavy(count: int) -> tuple[str, dict[str, Any]]:
    """Many interpolations, little static text."""
    parts: list[str] = []
    variables: dict[str, Any] = {}
    for i in range(count):
        name = f"v{i}"
        parts.append("<span>" + _interp(name) + "</span>")
        variables[name] = _VALUES[i % len(_VALUES)]
    return "".join(parts), variables


def make_static_heavy(count: int) -> tuple[str, dict[str, Any]]:
    """Lots of static HTML, an interpolation only every eighth chunk."""
    chunk = '<div class="card"><p>Lorem ipsum dolor sit amet consectetur.</p></div>'
    parts: list[str] = []
    variables: dict[str, Any] = {}
    for i in range(count):
        parts.append(chunk)
        if i % 8 == 0:
            name = f"v{i}"
            parts.append(_interp(name))
            variables[name] = _VALUES[i % len(_VALUES)]
    return "".join(parts), variables


def make_mixed(count: int) -> tuple[str, dict[str, Any]]:
    """Static and interpolation in equal measure."""
    parts: list[str] = []
    variables: dict[str, Any] = {}
    for i in range(count):
        name = f"v{i}"
        parts.append("<li>item " + _interp(name) + "</li>")
        variables[name] = _VALUES[i % len(_VALUES)]
    return "".join(parts), variables


def make_attr_heavy(count: int) -> tuple[str, dict[str, Any]]:
    """Elements with several simple dynamic attributes (no class/style/bind)."""
    parts: list[str] = []
    variables: dict[str, Any] = {}
    for i in range(count):
        a, b, t = f"a{i}", f"b{i}", f"t{i}"
        parts.append('<div c-id="' + a + '" c-data-x="' + b + '" c-title="' + t + '" role="cell">x</div>')
        variables[a] = _VALUES[i % len(_VALUES)]
        variables[b] = _VALUES[(i + 1) % len(_VALUES)]
        variables[t] = _VALUES[(i + 2) % len(_VALUES)]
    return "".join(parts), variables


def make_button() -> tuple[str, dict[str, Any]]:
    """A small, realistic component body (static attrs, two interpolations)."""
    source = '<button class="btn" type="button">{{ label }}<span class="count">{{ count }}</span></button>'
    variables: dict[str, Any] = {"label": "Click <me>", "count": 3}
    return source, variables


def make_if_heavy(count: int) -> tuple[str, dict[str, Any]]:
    """Many ``<c-if>``/``<c-else>`` conditionals, alternating which branch wins."""
    parts: list[str] = []
    variables: dict[str, Any] = {}
    for i in range(count):
        flag, a, b = f"f{i}", f"a{i}", f"b{i}"
        parts.append('<c-if cond="' + flag + '">' + _interp(a) + "</c-if><c-else>" + _interp(b) + "</c-else>")
        variables[flag] = i % 2 == 0
        variables[a] = _VALUES[i % len(_VALUES)]
        variables[b] = _VALUES[(i + 1) % len(_VALUES)]
    return "".join(parts), variables


def make_for_heavy(count: int) -> tuple[str, dict[str, Any]]:
    """One ``<c-for>`` over many items, each rendering a small interpolated body."""
    source = '<ul><c-for each="item in items"><li>{{ item }}</li></c-for></ul>'
    variables: dict[str, Any] = {"items": [_VALUES[i % len(_VALUES)] for i in range(count)]}
    return source, variables


def make_nested(count: int) -> tuple[str, dict[str, Any]]:
    """
    A ``<c-for>`` whose body contains a ``<c-if>`` on the loop variable.

    Exercises recursion plus loop-variable scoping: the per-iteration ``item``
    must reach the nested ``cond`` and the interpolation.
    """
    source = '<c-for each="item in items"><c-if cond="item">{{ item }}</c-if><c-else>-</c-else></c-for>'
    variables: dict[str, Any] = {"items": [_VALUES[i % len(_VALUES)] for i in range(count)]}
    return source, variables


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
    """Run every case, check byte-identity, print timings. Return process exit code."""
    cases: list[tuple[str, str, dict[str, Any]]] = [
        ("expr-heavy", *make_expr_heavy(120)),
        ("static-heavy", *make_static_heavy(120)),
        ("mixed", *make_mixed(120)),
        ("attr-heavy", *make_attr_heavy(120)),
        ("if-heavy", *make_if_heavy(120)),
        ("for-heavy", *make_for_heavy(120)),
        ("nested", *make_nested(120)),
        ("button", *make_button()),
    ]

    print(f"{'case':<14}{'identical':<11}{'foreign':<9}{'py us':>10}{'rust us':>10}{'speedup':>9}")
    print("-" * 63)

    all_identical = True
    for name, source, variables in cases:
        node_list = compile_node_list(source)
        plan = compile_plan(source)
        context = make_context(variables)

        # Warm up: compiles each expression's evaluator once (shared by both walks).
        py_out = python_render(node_list, context)
        rust_out = rust_render(plan, node_list, context)
        identical = py_out == rust_out
        all_identical = all_identical and identical

        foreign = sum(1 for k in plan.kinds() if k.startswith("foreign:"))

        py_t = best_per_call(partial(python_render, node_list, context), batch=200, samples=50)
        rust_t = best_per_call(partial(rust_render, plan, node_list, context), batch=200, samples=50)
        speedup = py_t / rust_t if rust_t else float("inf")

        print(
            f"{name:<14}{'yes' if identical else 'NO':<11}{foreign:<9}"
            f"{py_t * 1e6:>10.2f}{rust_t * 1e6:>10.2f}{speedup:>8.2f}x"
        )

    print("-" * 63)
    if not all_identical:
        print("FAIL: at least one case was not byte-identical")
        return 1
    print("OK: all cases byte-identical")
    return 0


def make_comp_list(count: int) -> Any:
    """A root component that loops over data, rendering a child component each time."""
    c = Citry()

    class Item(Component):
        citry = c
        template = "<li>{{ label }}</li>"

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"label": kwargs["label"]}

    class ListComp(Component):
        citry = c
        template = '<ul><c-for each="x in items"><c-item c-label="x"/></c-for></ul>'

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"items": kwargs["items"]}

    return ListComp(items=[_VALUES[i % len(_VALUES)] for i in range(count)])


def make_comp_nested(count: int) -> Any:
    """A three-level component tree (Grid -> Row -> Leaf), each level looping."""
    c = Citry()

    class Leaf(Component):
        citry = c
        template = "<span>{{ v }}</span>"

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"v": kwargs["v"]}

    class Row(Component):
        citry = c
        template = '<div class="row"><c-for each="v in vals"><c-leaf c-v="v"/></c-for></div>'

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"vals": kwargs["vals"]}

    class Grid(Component):
        citry = c
        template = '<section><c-for each="row in rows"><c-row c-vals="row"/></c-for></section>'

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"rows": kwargs["rows"]}

    rows = [[_VALUES[(i * 3 + j) % len(_VALUES)] for j in range(3)] for i in range(count)]
    return Grid(rows=rows)


def make_comp_rich(count: int) -> Any:
    """
    A loop of components whose bodies do substantial in-body work.

    Contrasts with the tiny-body cases: here each child has eight interpolations,
    so the body walk is a real fraction of the per-component cost (not swamped by
    construction), and the Rust walk has something to win.
    """
    c = Citry()
    fields = range(8)

    class Card(Component):
        citry = c
        template = (
            '<article class="card">' + "".join("<span>" + _interp(f"f{i}") + "</span>" for i in fields) + "</article>"
        )

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {f"f{i}": kwargs["v"] for i in fields}

    class Deck(Component):
        citry = c
        template = '<div><c-for each="v in items"><c-card c-v="v"/></c-for></div>'

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"items": kwargs["items"]}

    return Deck(items=[_VALUES[i % len(_VALUES)] for i in range(count)])


def make_slot_tree(count: int) -> Any:
    """
    A layout with named slots, filled with a header and a looped component body.

    Exercises slots/fills end to end: the fill bodies render in the writer scope
    (Python), and a fill that contains a loop of child components drives those
    components back through the Rust walk.
    """
    c = Citry()

    class Item(Component):
        citry = c
        template = "<li>{{ x }}</li>"

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"x": kwargs["x"]}

    class Layout(Component):
        citry = c
        template = '<section><header><c-slot name="head"/></header><main><c-slot name="body"/></main></section>'

    class Page(Component):
        citry = c
        template = (
            "<c-layout>"
            '<c-fill name="head">{{ title }}</c-fill>'
            '<c-fill name="body"><c-for each="x in items"><c-item c-x="x"/></c-for></c-fill>'
            "</c-layout>"
        )

        def template_data(self, kwargs: Any, slots: Any = None) -> dict[str, Any]:
            return {"title": kwargs["title"], "items": kwargs["items"]}

    return Page(title="Hello <world>", items=[_VALUES[i % len(_VALUES)] for i in range(count)])


def run_component_cases() -> int:
    """
    Drive whole component trees in Rust vs the Python mirror, checked against
    the real engine. Returns a process exit code.
    """
    cases: list[tuple[str, Any]] = [
        ("comp-list", make_comp_list(120)),
        ("comp-nested", make_comp_nested(40)),
        ("comp-rich", make_comp_rich(60)),
        ("slot-tree", make_slot_tree(60)),
    ]

    print()
    print(f"{'component case':<16}{'identical':<11}{'py us':>12}{'rust us':>12}{'speedup':>9}")
    print("-" * 60)

    all_identical = True
    for name, element in cases:
        # The reference is the real engine's resolved tree, flattened (no markers).
        reference = real_render(element)
        rust_out = rust_drive(element)
        py_out = python_drive(element)
        identical = rust_out == reference == py_out
        all_identical = all_identical and identical

        py_t = best_per_call(partial(python_drive, element), batch=50, samples=30)
        rust_t = best_per_call(partial(rust_drive, element), batch=50, samples=30)
        speedup = py_t / rust_t if rust_t else float("inf")

        print(f"{name:<16}{'yes' if identical else 'NO':<11}{py_t * 1e6:>12.2f}{rust_t * 1e6:>12.2f}{speedup:>8.2f}x")

    print("-" * 60)
    if not all_identical:
        print("FAIL: a component case was not byte-identical")
        return 1
    print("OK: component cases byte-identical (Rust-driven == Python-driven == real engine)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run() or run_component_cases())
