"""
Regenerate the README performance chart (``docs/assets/benchmark.png``).

The numbers below are the published large-scenario results from
``benchmarks/README.md`` (its "Results (large scenario)" table). They are not
measured here: ``compare.py`` produces them in a controlled run, that table is
the source of truth, and this script only draws it. When the table is
re-measured, update ``SERIES`` and ``CAPTION`` below to match, then re-run.

Requires matplotlib, which is not part of the dev install. Run from the
repository root in an ephemeral environment so the project venv is untouched::

    uv run --no-project --with matplotlib python benchmarks/plot.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# Source: benchmarks/README.md "Results (large scenario)", measured 2026-06-26
# (Apple M4, Python 3.13.12, median of 5 fresh-process runs). Times in
# milliseconds, lower is better. Keep SERIES and CAPTION in step with the table.
CAPTION = (
    "Apple M4, Python 3.13.12, median of 5 fresh-process runs.  "
    "django 6.0.6, django-components 0.151.0, jinja2 3.1.6, citry 0.1.0."
)
METRICS = ["Startup", "Import", "First render", "Repeat render"]
# Each row: engine label, [startup, import, first render, repeat render], bar color.
SERIES = [
    ("Django", [82.31, 76.87, 17.72, 10.95], "#64748b"),
    ("django-components", [82.08, 77.33, 65.08, 45.92], "#f97316"),
    ("jinja2", [18.38, 14.79, 58.14, 6.27], "#3b82f6"),
    ("Citry", [37.72, 28.63, 37.65, 14.17], "#10b981"),
]
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "assets" / "benchmark.png"
BAR_WIDTH = 0.20


def main() -> None:
    """Draw the grouped bar chart and write it to ``OUT_PATH``."""
    x = np.arange(len(METRICS))
    fig, ax = plt.subplots(figsize=(10.5, 5.5), dpi=200)

    for i, (label, values, color) in enumerate(SERIES):
        offset = (i - (len(SERIES) - 1) / 2) * BAR_WIDTH
        bars = ax.bar(x + offset, values, BAR_WIDTH, label=label, color=color,
                      edgecolor="white", linewidth=0.6, zorder=3)
        ax.bar_label(bars, labels=[f"{v:.0f}" for v in values], padding=2,
                     fontsize=7.5, color="#334155")

    ax.set_xticks(x)
    ax.set_xticklabels(METRICS, fontsize=10.5)
    ax.set_ylabel("Time in milliseconds (lower is better)", fontsize=10)
    ax.set_title("Rendering a large page (~325 components)", fontsize=13,
                 pad=10, fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.spines["top"].set(visible=False)
    ax.spines["right"].set(visible=False)
    ax.yaxis.grid(visible=True, color="#e8edf2", linewidth=0.9, zorder=0)
    ax.set(axisbelow=True)
    ax.margins(y=0.16)
    ax.tick_params(length=0)

    fig.text(0.5, 0.015, CAPTION, ha="center", fontsize=7.5, color="#94a3b8")
    fig.tight_layout(rect=(0, 0.04, 1, 1))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=200, bbox_inches="tight", facecolor="white")
    print(f"saved {OUT_PATH}")


if __name__ == "__main__":
    main()
