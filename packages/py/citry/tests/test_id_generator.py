"""Tests for the ``id_generator`` setting (per-render component id override)."""

import re

import pytest

from citry import Citry, Component


class TestIdGeneratorOverride:
    def test_callable_overrides_the_render_id(self):
        app = Citry(id_generator=lambda: "fixed")

        class Card(Component):
            citry = app
            template = """
            <p>hi</p>
            """

        assert Card._create_instance().id == "fixed"

    def test_override_drives_the_serialized_marker(self):
        app = Citry(id_generator=lambda: "fixed")

        class Card(Component):
            citry = app
            template = """
            <p>hi</p>
            """

        html = Card().render().serialize()

        assert "data-cid-fixed" in html

    def test_class_spec_is_instantiated_once_for_state(self):
        # A class is built once into the generator, so a counter keeps its state
        # across renders on the same instance.
        class Counter:
            def __init__(self) -> None:
                self.n = 0

            def __call__(self) -> str:
                self.n += 1
                return f"k{self.n}"

        app = Citry(id_generator=Counter)

        class Card(Component):
            citry = app
            template = """
            <p>hi</p>
            """

        ids = [Card._create_instance().id for _ in range(3)]

        assert ids == ["k1", "k2", "k3"]

    def test_import_string_spec_resolves(self):
        app = Citry(id_generator="citry.util.id.gen_render_id")

        class Card(Component):
            citry = app
            template = """
            <p>hi</p>
            """

        assert callable(app.id_generator)
        assert re.fullmatch(r"c[0-9A-Za-z]{6}", Card._create_instance().id)


class TestIdGeneratorDefaults:
    def test_default_is_none(self):
        # None means "use the built-in generator"; the fallback lives at the
        # mint site, not as a stored default.
        assert Citry().id_generator is None

    def test_class_id_is_untouched_by_the_override(self):
        app = Citry(id_generator=lambda: "fixed")

        class Card(Component):
            citry = app
            template = """
            <p>hi</p>
            """

        # The render id is the override; the class id stays a stable hash of the
        # import path and is unrelated.
        assert Card._create_instance().id == "fixed"
        assert Card.class_id.startswith("Card_")


class TestIdGeneratorValidation:
    def test_non_callable_spec_raises(self):
        with pytest.raises(TypeError, match="id_generator must be callable"):
            Citry(id_generator=123)  # type: ignore[arg-type]

    def test_missing_import_target_raises(self):
        with pytest.raises((AttributeError, ModuleNotFoundError)):
            Citry(id_generator="citry.util.id.does_not_exist")
