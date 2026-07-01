"""Tests for component-module autodiscovery."""

import importlib
import logging
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from citry import Citry, Component
from citry.autodiscovery import find_component_modules


@pytest.fixture
def project(tmp_path, monkeypatch):
    """
    Build an importable project tree under ``tmp_path`` and put it on sys.path.

    Returns a ``write(relpath, content)`` helper. ``tmp_path`` is prepended to
    ``sys.path`` so the tree's packages import by their real dotted names (the
    same condition autodiscovery requires of real projects). Every module the
    test imports - directly or through autodiscovery - is removed from
    ``sys.modules`` on teardown, so package names do not leak between tests.
    """
    before = set(sys.modules)
    monkeypatch.syspath_prepend(str(tmp_path))

    def write(relpath: str, content: str = "") -> Path:
        path = tmp_path / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    yield write

    for name in set(sys.modules) - before:
        sys.modules.pop(name, None)


def _build_app(write, pkg: str, *, autodiscover: bool = True) -> None:
    """Write a package whose ``app`` module holds a Citry bound to ``components/``."""
    write(f"{pkg}/__init__.py")
    write(f"{pkg}/components/__init__.py")
    write(
        f"{pkg}/app.py",
        dedent(f"""
            from pathlib import Path
            from citry import Citry

            app = Citry(dirs=[Path(__file__).parent / "components"], autodiscover={autodiscover})
        """),
    )


def _component(pkg: str, class_name: str, *, template: str = "<div>x</div>") -> str:
    """Source for a component module that binds to ``pkg.app.app``."""
    return dedent(f'''
        from citry import Component
        from {pkg}.app import app


        class {class_name}(Component):
            citry = app
            template = """
            {template}
            """
    ''')


def _load_app(pkg: str):
    """Import the package's app module and return its Citry instance."""
    return importlib.import_module(f"{pkg}.app").app


# ----- find_component_modules (the path -> import-name mechanics) -----


class TestFindComponentModules:
    def test_maps_files_to_import_names(self, project):
        project("pkga/__init__.py")
        project("pkga/comps/__init__.py")
        card = project("pkga/comps/card.py", "x = 1")

        mods = find_component_modules([card.parent])

        assert mods == ["pkga.comps", "pkga.comps.card"]

    def test_skips_underscore_files_and_dirs(self, project):
        project("pkgb/__init__.py")
        project("pkgb/comps/__init__.py")
        card = project("pkgb/comps/card.py", "x = 1")
        project("pkgb/comps/_hidden.py", "raise RuntimeError('must not import')")
        project("pkgb/comps/_priv/__init__.py")
        project("pkgb/comps/_priv/inner.py", "raise RuntimeError('must not import')")

        mods = find_component_modules([card.parent])

        assert mods == ["pkgb.comps", "pkgb.comps.card"]

    def test_nonexistent_dir_contributes_nothing(self, tmp_path):
        # A dir with no .py files (or that does not exist) is simply empty, not
        # an error: an asset-only dirs entry contributes no modules.
        assert find_component_modules([tmp_path / "missing"]) == []

    def test_raises_when_dir_not_on_import_path(self, tmp_path):
        # tmp_path is NOT on sys.path here, so a .py file under it has no import
        # name and discovery must say so loudly rather than guess.
        (tmp_path / "loose.py").write_text("x = 1")

        with pytest.raises(ValueError, match="not on the Python import path"):
            find_component_modules([tmp_path])

    def test_dedupes_across_dirs(self, project):
        project("pkgc/__init__.py")
        project("pkgc/comps/__init__.py")
        card = project("pkgc/comps/card.py", "x = 1")
        comps = card.parent

        # The same directory twice yields each module once.
        assert find_component_modules([comps, comps]) == ["pkgc.comps", "pkgc.comps.card"]


# ----- the lazy trigger and the autodiscover() method -----


class TestLazyDiscovery:
    def test_first_lookup_triggers_discovery(self, project):
        _build_app(project, "lazy1")
        project("lazy1/components/card.py", _component("lazy1", "Card"))
        app = _load_app("lazy1")

        # Nothing imported the card module yet; the latch is unset.
        assert app._discovered is False
        # The lookup itself imports it and registers Card.
        assert app.has("card") is True
        assert app._discovered is True
        assert "card" in app.components

    def test_tag_rules_path_triggers_discovery(self, project):
        # _tag_rules() reads the whole registry, so discovery must run before it.
        _build_app(project, "lazy2")
        project("lazy2/components/card.py", _component("lazy2", "Card"))
        app = _load_app("lazy2")

        assert app._discovered is False
        app._tag_rules()
        assert app._discovered is True
        assert app.has("card")

    def test_runs_only_once(self, project):
        _build_app(project, "lazy3")
        project("lazy3/components/card.py", _component("lazy3", "Card"))
        app = _load_app("lazy3")

        app.has("card")  # first lookup discovers

        # A module added after the first scan is NOT picked up: discovery is a
        # one-time bootstrap, not a watcher.
        project("lazy3/components/late.py", _component("lazy3", "Late"))
        assert app.has("late") is False

    def test_off_skips_discovery(self, project):
        _build_app(project, "off1", autodiscover=False)
        project("off1/components/card.py", _component("off1", "Card"))
        app = _load_app("off1")

        assert app.has("card") is False  # never imported
        # ...but the explicit method still works on demand.
        imported = app.autodiscover()
        assert "off1.components.card" in imported
        assert app.has("card") is True

    def test_no_dirs_is_a_noop(self):
        # The default-instance condition: autodiscover on, but no dirs to scan.
        c = Citry()  # autodiscover defaults to True
        assert c.has("provide") is True  # built-ins still work
        assert c._discovered is True  # latch set, nothing imported


class TestAutodiscoverMethod:
    def test_returns_imported_module_names(self, project):
        _build_app(project, "m1", autodiscover=False)
        project("m1/components/card.py", _component("m1", "Card"))
        project("m1/components/badge.py", _component("m1", "Badge"))
        app = _load_app("m1")

        imported = app.autodiscover()

        assert set(imported) >= {"m1.components.card", "m1.components.badge"}
        assert app.has("card")
        assert app.has("badge")

    def test_is_idempotent(self, project):
        _build_app(project, "m2", autodiscover=False)
        project("m2/components/card.py", _component("m2", "Card"))
        app = _load_app("m2")

        app.autodiscover()
        # A second call re-imports nothing new and does not raise
        # (re-registering the same class is a no-op).
        app.autodiscover()
        assert app.has("card")

    def test_emits_debug_logs(self, project, caplog):
        _build_app(project, "m_log", autodiscover=False)
        project("m_log/components/card.py", _component("m_log", "Card"))
        app = _load_app("m_log")

        with caplog.at_level(logging.DEBUG, logger="citry"):
            app.autodiscover()

        msgs = [r.getMessage() for r in caplog.records if r.name == "citry"]
        assert any(m.startswith("Autodiscovery found") for m in msgs)
        assert any(m.startswith("Importing component module") and "m_log.components.card" in m for m in msgs)

    def test_explicit_dirs_argument(self, project):
        # autodiscover(dirs=...) imports an extra location without disabling the
        # automatic scan of settings.dirs.
        _build_app(project, "m3")
        project("m3/extra/__init__.py")
        widget = project("m3/extra/widget.py", _component("m3", "Widget"))
        app = _load_app("m3")

        imported = app.autodiscover(dirs=[widget.parent])

        assert "m3.extra.widget" in imported
        # The explicit-dirs call did not consume the one-time settings.dirs scan.
        assert app._discovered is False
        assert app.has("widget")


class TestEndToEnd:
    def test_component_referenced_in_template_is_discovered(self, project):
        # A root component renders <c-card>; Card lives in a sibling module that
        # only autodiscovery imports. Rendering must find it.
        _build_app(project, "e2e")
        project("e2e/components/card.py", _component("e2e", "Card", template="<span>card</span>"))
        app = _load_app("e2e")

        class Page(Component):
            citry = app
            template = """
            <div><c-card /></div>
            """

        html = Page().render().serialize()

        assert ">card</span>" in html
        assert app.has("card")

    def test_clear_then_lookup_rebuilds_the_registry(self, project):
        # clear() re-arms discovery; the next lookup re-runs the scan and
        # rebuilds the registry. The module is already imported, so this works
        # only because the scan re-registers its components by walking it.
        _build_app(project, "clr")
        project("clr/components/card.py", _component("clr", "Card"))
        app = _load_app("clr")

        assert app.has("card")
        app.clear()
        assert app._discovered is False  # re-armed

        # The very next lookup rediscovers and the component is back, identical
        # to before the clear().
        assert app.has("card") is True
        assert app._discovered is True

    def test_explicit_autodiscover_repopulates_after_clear(self, project):
        # The same rebuild via the explicit method rather than a lazy lookup.
        _build_app(project, "clr2", autodiscover=False)
        project("clr2/components/card.py", _component("clr2", "Card"))
        app = _load_app("clr2")

        app.autodiscover()
        assert app.has("card")

        app.clear()
        assert app.has("card") is False  # cleared

        app.autodiscover()  # walks the already-imported module and re-registers
        assert app.has("card") is True

    def test_walk_registers_a_pre_imported_module(self, project):
        # If a component module is imported before discovery runs (so the
        # metaclass already registered it), discovery still ends in the same
        # place: the walk finds it already registered and leaves it be.
        _build_app(project, "pre")
        project("pre/components/card.py", _component("pre", "Card"))
        app = _load_app("pre")
        importlib.import_module("pre.components.card")  # pre-import before any lookup

        assert app.has("card") is True
        assert sorted(app.components).count("card") == 1  # not double-registered
