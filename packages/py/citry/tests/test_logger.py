"""Tests for citry.util.logger (the "citry" logger + TRACE level and helpers)."""

import logging

from citry import Citry, Component
from citry.util.logger import _ensure_trace_level, is_tracing, trace, trace_component_msg, trace_node_msg

TRACE = 5


def _citry_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "citry"]


def test_trace_level_is_registered():
    assert _ensure_trace_level() == TRACE
    assert logging.getLevelName(TRACE) == "TRACE"


def test_is_tracing_reflects_the_logger_level(caplog):
    with caplog.at_level(logging.INFO, logger="citry"):
        assert is_tracing() is False
    with caplog.at_level(TRACE, logger="citry"):
        assert is_tracing() is True


def test_trace_emits_at_trace_level_when_enabled(caplog):
    with caplog.at_level(TRACE, logger="citry"):
        trace("hello %s", "world")
    assert _citry_messages(caplog) == ["hello world"]
    assert caplog.records[0].levelno == TRACE


def test_trace_is_silent_when_disabled(caplog):
    with caplog.at_level(logging.INFO, logger="citry"):
        trace("nothing to see")
    assert _citry_messages(caplog) == []


def test_trace_component_msg_full_format(caplog):
    with caplog.at_level(TRACE, logger="citry"):
        trace_component_msg(
            "RENDER",
            "Card",
            component_id="c12",
            slot_name="body",
            component_path=["Root", "Card"],
            slot_fills=["body", "header"],
            extra="note",
        )
    assert _citry_messages(caplog) == [
        "RENDER COMPONENT: 'Card' ID c12 SLOT: 'body' PATH: Root > Card FILLS: body, header note",
    ]


def test_trace_component_msg_omits_empty_fields(caplog):
    with caplog.at_level(TRACE, logger="citry"):
        trace_component_msg("RENDER", "Card")
    assert _citry_messages(caplog) == ["RENDER COMPONENT: 'Card'"]


def test_trace_component_msg_is_silent_when_disabled(caplog):
    with caplog.at_level(logging.INFO, logger="citry"):
        trace_component_msg("RENDER", "Card", component_id="c1")
    assert _citry_messages(caplog) == []


def test_trace_node_msg_with_position(caplog):
    with caplog.at_level(TRACE, logger="citry"):
        trace_node_msg("RENDER", "ExprNode", (12, 20))
    assert _citry_messages(caplog) == ["RENDER NODE ExprNode @12:20"]


def test_trace_node_msg_without_position(caplog):
    with caplog.at_level(TRACE, logger="citry"):
        trace_node_msg("RENDER", "ComponentNode")
    assert _citry_messages(caplog) == ["RENDER NODE ComponentNode"]


def test_trace_node_msg_is_silent_when_disabled(caplog):
    with caplog.at_level(logging.INFO, logger="citry"):
        trace_node_msg("RENDER", "ExprNode", (1, 2))
    assert _citry_messages(caplog) == []


def _page_with_slot():
    c = Citry()

    class Card(Component):
        citry = c
        template = """
        <div>{{ title }}<c-slot name="body" /></div>
        """

        class Slots:
            body: "object | None" = None

        def template_data(self, kwargs, slots):
            return {"title": kwargs["title"]}

    class Page(Component):
        citry = c
        template = """
        <c-Card c-title="'Hi'"><c-fill name="body">X</c-fill></c-Card>
        """

        def template_data(self, kwargs, slots):
            return {}

    return Page


def test_render_emits_component_and_slot_traces(caplog):
    page = _page_with_slot()
    with caplog.at_level(TRACE, logger="citry"):
        page().render().serialize()
    msgs = _citry_messages(caplog)
    assert any(m.startswith("RENDER COMPONENT: 'Page'") for m in msgs)
    assert any(m.startswith("RENDER COMPONENT: 'Card'") and "PATH: Page > Card" in m for m in msgs)
    assert any(m.startswith("RENDER_SLOT COMPONENT: 'Card'") and "SLOT: 'body'" in m for m in msgs)
    assert any(m.startswith("RENDER NODE ") for m in msgs)


def test_render_emits_no_trace_records_when_disabled(caplog):
    page = _page_with_slot()
    with caplog.at_level(logging.INFO, logger="citry"):
        page().render().serialize()
    assert _citry_messages(caplog) == []


def test_asset_load_emits_a_debug_log(tmp_path, caplog):
    (tmp_path / "card.html").write_text("<p>Hi</p>")
    c = Citry(dirs=[tmp_path])

    class Card(Component):
        citry = c
        template_file = "card.html"

    with caplog.at_level(logging.DEBUG, logger="citry"):
        Card.get_template()
    prefix = "Loaded template_file for component Card"
    recs = [r for r in caplog.records if r.name == "citry" and r.getMessage().startswith(prefix)]
    assert len(recs) == 1
    assert recs[0].levelno == logging.DEBUG
    assert "card.html" in recs[0].getMessage()


def test_trace_component_msg_empty_fills_omits_the_label(caplog):
    with caplog.at_level(TRACE, logger="citry"):
        trace_component_msg("RENDER", "Card", slot_fills=[])
        trace_component_msg("RENDER", "Card", slot_fills={})
    assert _citry_messages(caplog) == ["RENDER COMPONENT: 'Card'", "RENDER COMPONENT: 'Card'"]


def test_trace_component_msg_mapping_fills_uses_keys(caplog):
    # The real call sites pass component.raw_slots (a dict); its keys are the fill names.
    with caplog.at_level(TRACE, logger="citry"):
        trace_component_msg("RENDER", "Card", slot_fills={"body": object(), "header": object()})
    assert _citry_messages(caplog) == ["RENDER COMPONENT: 'Card' FILLS: body, header"]


def test_component_path_is_not_built_when_tracing_off(caplog, monkeypatch):
    import citry.component_render as cr

    calls = []
    real_path = cr._component_path
    monkeypatch.setattr(cr, "_component_path", lambda component: calls.append(component) or real_path(component))

    page = _page_with_slot()
    with caplog.at_level(logging.INFO, logger="citry"):
        page().render().serialize()
    # A successful render with TRACE off never needs the O(depth) ancestor path.
    assert calls == []


def test_ensure_trace_level_reuses_an_existing_trace_level(monkeypatch):
    import citry.util.logger as lg

    monkeypatch.setattr(lg, "_trace_level", -1)
    original = logging.getLevelName
    monkeypatch.setattr(logging, "getLevelName", lambda name: 7 if name == "TRACE" else original(name))
    registered = []
    monkeypatch.setattr(logging, "addLevelName", lambda num, name: registered.append((num, name)))

    assert lg._ensure_trace_level() == 7
    assert registered == []  # reused the existing level, did not re-register


def test_ensure_trace_level_registers_when_absent(monkeypatch):
    import citry.util.logger as lg

    monkeypatch.setattr(lg, "_trace_level", -1)
    original = logging.getLevelName
    monkeypatch.setattr(logging, "getLevelName", lambda name: "Level TRACE" if name == "TRACE" else original(name))
    registered = []
    monkeypatch.setattr(logging, "addLevelName", lambda num, name: registered.append((num, name)))

    assert lg._ensure_trace_level() == 5
    assert registered == [(5, "TRACE")]
