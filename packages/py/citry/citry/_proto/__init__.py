"""
Render-plan prototype harness (throwaway, visible-in-repo).

This package is the Python side of the render-plan prototype described in
``docs/design/render_plan_rust.md``. It is NOT part of the shipped runtime: it
exists so the Rust render-plan executor can be compared, byte-for-byte and on
wall-clock, against the existing Python body walk (``_render_body``).

- ``render_plan_runtime`` builds a template's node list and its render plan from
  the same source, and offers the two walks to compare.
- ``ab_harness`` runs representative bodies through both walks, asserts the
  output is identical, and reports the timing.
"""
