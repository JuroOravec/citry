"""
Compiling a component body must produce the same output as walking it.

citry turns each component's body into a Python function that produces the
output directly (citry/body_compile.py), rather than walking the body's node
list on every render. That is always on. These tests render a range of template
constructs two ways, by compiling the body and by walking it (the reference
path), and assert byte-identical output, plus that a template error still raises
with its position. The walk path is reached here by swapping in a stand-in that
walks instead of compiling.
"""

import re

import pytest

from citry import Citry, Component
from citry.component_render import _render_body


def _norm(html: object) -> str:
    # Per-render data-cid ids continue counting across the two renders in one
    # test, so blank them to compare structure.
    return re.sub(r'data-cid-\w+=""', 'data-cid=""', str(html))


def _data_fn(data):
    def template_data(self, kwargs, slots):  # noqa: ARG001
        return data

    return template_data


def _walk_instead_of_compiling(body, **_compile_kwargs):
    # A stand-in for body_compile.compile_body: instead of compiling the body
    # into a function, return one that walks the body's node list. Lets a test
    # render the same body both ways and compare.
    def render(context):
        return _render_body(body, context)

    return render


def _both(build):
    """Render ``build()`` twice, by walking the body and by compiling it; return (walk, compiled)."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("citry.body_compile.compile_body", _walk_instead_of_compiling)
        walk = _norm(build())
    compiled = _norm(build())
    return walk, compiled


def _render_both(template, data, *, child_template=None):
    def build():
        app = Citry()
        if child_template is not None:
            type(
                "Leaf",
                (Component,),
                {"citry": app, "name": "Leaf", "template": child_template, "template_data": _data_fn({"x": "leaf"})},
            )
        return type("Root", (Component,), {"citry": app, "template": template, "template_data": _data_fn(data)})()

    return _both(build)


_LOOP = "<ul><c-for each='i in items'><li>{{ i }}</li></c-for><c-empty>none</c-empty></ul>"
CASES = [
    ("static-only", "<div class='a'><span>hi</span></div>", {}),
    ("interpolation", "<p>{{ name }} - {{ n }}</p>", {"name": "Al", "n": 3}),
    (
        "if-elif-else-match",
        "<c-if cond='k == 1'>one</c-if><c-elif cond='k == 2'>two</c-elif><c-else>other</c-else>",
        {"k": 2},
    ),
    ("if-no-match", "<div><c-if cond='k == 1'>one</c-if></div>", {"k": 9}),
    ("for-with-items", _LOOP, {"items": [1, 2, 3]}),
    ("for-empty-branch", _LOOP, {"items": []}),
    (
        "nested-for",
        "<div><c-for each='r in rows'><c-for each='c in r'>{{ c }},</c-for>|</c-for></div>",
        {"rows": [[1, 2], [3]]},
    ),
    ("for-with-unpacking", "<c-for each='k, v in pairs'>{{ k }}={{ v }};</c-for>", {"pairs": [("a", 1), ("b", 2)]}),
    ("dynamic-attrs", "<div c-bind='attrs' c-class='cls' id='z'>x</div>", {"attrs": {"data-k": "v"}, "cls": "c1"}),
    ("if-inside-for", "<c-for each='i in items'><c-if cond='i > 1'>{{ i }}</c-if></c-for>", {"items": [1, 2, 3]}),
    ("nested-template-attr", '<div c-body="<span>{{ x }}</span>">end</div>', {"x": "hi"}),
]


@pytest.mark.parametrize(("template", "data"), [(t, d) for _, t, d in CASES], ids=[c[0] for c in CASES])
def test_compiled_body_matches_walk(template, data):
    walk, compiled = _render_both(template, data)
    assert walk == compiled


def test_nested_components_match():
    # Two child components: exercises the deferred-component path (the compiled
    # function appends DeferredComponent parts, render_impl renders them).
    walk, compiled = _render_both("<div><c-Leaf /><c-Leaf /></div>", {}, child_template="<span>{{ x }}</span>")
    assert walk == compiled
    assert walk.count("leaf") == 2  # sanity: both children rendered


def test_slot_and_fill_match():
    def build():
        app = Citry()
        type(
            "Card",
            (Component,),
            {"citry": app, "name": "Card", "template": "<div><c-slot name='body'>fallback</c-slot></div>",
             "template_data": _data_fn({})},
        )
        return type(
            "Root",
            (Component,),
            {"citry": app, "template": "<c-Card><c-fill name='body'>filled {{ v }}</c-fill></c-Card>",
             "template_data": _data_fn({"v": 7})},
        )()

    walk, compiled = _both(build)
    assert walk == compiled


def test_slot_fallback_matches():
    def build():
        app = Citry()
        type(
            "Card",
            (Component,),
            {"citry": app, "name": "Card", "template": "<div><c-slot name='body'>fallback {{ d }}</c-slot></div>",
             "template_data": _data_fn({"d": 9})},
        )
        return type("Root", (Component,), {"citry": app, "template": "<c-Card />", "template_data": _data_fn({})})()

    walk, compiled = _both(build)
    assert walk == compiled


def _boom():
    msg = "kaboom"
    raise ValueError(msg)


def test_error_keeps_template_position_both_ways():
    # A failing expression must raise the same error (message + template
    # position snippet) whether the body is walked or compiled.
    def build():
        app = Citry()
        return str(
            type(
                "Root",
                (Component,),
                {"citry": app, "template": "<p>{{ boom() }}</p>", "template_data": _data_fn({"boom": _boom})},
            )()
        )

    messages = {}
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("citry.body_compile.compile_body", _walk_instead_of_compiling)
        with pytest.raises(ValueError, match="kaboom") as excinfo:
            build()
        messages["walk"] = str(excinfo.value)
    with pytest.raises(ValueError, match="kaboom") as excinfo:
        build()
    messages["compiled"] = str(excinfo.value)
    assert messages["walk"] == messages["compiled"]
