"""
Tests for the component-path error helpers (``citry/util/exception.py``,
docs/design/on_render.md section 6): path accumulation on the exception,
idempotent message-prefix rewriting, slot frames, and the args-less /
non-string-args edge cases.

The behavioral contract is ported from django-components
(``util/exception.py``), minus the stdout print for args-less exceptions.
"""

import pytest

from citry.util.exception import (
    add_slot_to_error_message,
    set_component_error_message,
    with_component_error_message,
)

PREFIX_MARKER = "An error occurred while rendering components"


class TestSetComponentErrorMessage:
    def test_prefixes_message_and_records_path(self):
        err = ValueError("boom")
        set_component_error_message(err, ["Page", "Card"])

        assert err._components == ["Page", "Card"]
        assert err.args[0] == f"{PREFIX_MARKER} Page > Card:\nboom"
        assert str(err) == err.args[0]

    def test_outer_frames_go_in_front(self):
        # As the error bubbles up, each level prepends its components.
        err = ValueError("boom")
        set_component_error_message(err, ["Child"])
        set_component_error_message(err, ["Root", "Middle"])

        assert err._components == ["Root", "Middle", "Child"]
        assert "Root > Middle > Child" in err.args[0]

    def test_prefix_rewrite_is_idempotent(self):
        # Adding more frames replaces the old prefix line, it does not stack.
        err = ValueError("boom")
        set_component_error_message(err, ["Child"])
        set_component_error_message(err, ["Root"])

        assert err.args[0].count(PREFIX_MARKER) == 1
        assert err.args[0].count("boom") == 1
        assert err.args[0] == f"{PREFIX_MARKER} Root > Child:\nboom"

    def test_multiline_original_message_is_kept(self):
        # The rewrite drops only the old prefix line (the first line), so a
        # multi-line original message survives intact.
        err = ValueError("line one\nline two")
        set_component_error_message(err, ["Child"])
        set_component_error_message(err, ["Root"])

        assert err.args[0] == f"{PREFIX_MARKER} Root > Child:\nline one\nline two"

    def test_exception_without_args(self):
        err = ValueError()
        set_component_error_message(err, ["Page"])

        assert err._components == ["Page"]
        assert err.args[0] == f"{PREFIX_MARKER} Page:\n"

    def test_exception_with_none_arg(self):
        err = ValueError(None)
        set_component_error_message(err, ["Page"])

        # A ``None`` first arg falls back to str(err) as the message body.
        assert err.args[0] == f"{PREFIX_MARKER} Page:\nNone"

    def test_exception_with_nonstring_arg(self):
        err = KeyError(5)
        set_component_error_message(err, ["Page"])

        assert err.args[0] == f"{PREFIX_MARKER} Page:\n5"


class TestWithComponentErrorMessage:
    def test_reraises_the_same_exception_with_path(self):
        original = ValueError("boom")
        with pytest.raises(ValueError, match="boom") as exc_info:
            with with_component_error_message(["Page"]):
                raise original

        assert exc_info.value is original
        assert exc_info.value.args[0] == f"{PREFIX_MARKER} Page:\nboom"

    def test_no_error_passes_through(self):
        with with_component_error_message(["Page"]):
            pass

    def test_nested_blocks_build_the_path_outward(self):
        def render():
            with with_component_error_message(["Root"]):
                with with_component_error_message(["Child"]):
                    raise ValueError("boom")

        with pytest.raises(ValueError, match="boom") as exc_info:
            render()

        assert exc_info.value._components == ["Root", "Child"]
        assert exc_info.value.args[0] == f"{PREFIX_MARKER} Root > Child:\nboom"


class TestAddSlotToErrorMessage:
    def test_slot_frame_lands_between_components(self):
        # The layering mirrors the render flow: the outer component renders a
        # slot, whose fill content renders an inner component that fails.
        def render():
            with with_component_error_message(["Outer"]):
                with add_slot_to_error_message("Card", "body"):
                    with with_component_error_message(["Inner"]):
                        raise ValueError("boom")

        with pytest.raises(ValueError, match="boom") as exc_info:
            render()

        assert exc_info.value._components == ["Outer", "Card(slot:body)", "Inner"]
        assert exc_info.value.args[0] == f"{PREFIX_MARKER} Outer > Card(slot:body) > Inner:\nboom"

    def test_slot_frame_alone_does_not_rewrite_message(self):
        # The slot helper only records the frame; the message is rewritten by
        # the next with_component_error_message further up.
        with pytest.raises(ValueError, match="boom") as exc_info:
            with add_slot_to_error_message("Card", "body"):
                raise ValueError("boom")

        assert exc_info.value._components == ["Card(slot:body)"]
        assert exc_info.value.args[0] == "boom"

    def test_no_error_passes_through(self):
        with add_slot_to_error_message("Card", "body"):
            pass
