"""Tests for the extension (plugin) system skeleton (phase 1)."""

# ruff: noqa: ANN, D101, D102, D106, ARG002, PLC0415

import pytest

from citry import Citry as _Citry
from citry import (
    CitryRender,
    Component,
    Extension,
    ExtensionCommand,
)


class _StringPathExt(Extension):
    name = "strext"


class TestExtensionDefinition:
    def test_class_name_derived_from_name(self):
        class MyExt(Extension):
            name = "my_extension"

        assert MyExt.class_name == "MyExtension"

    def test_explicit_class_name_kept(self):
        class MyExt(Extension):
            name = "my_extension"
            class_name = "Custom"

        assert MyExt.class_name == "Custom"

    def test_name_must_be_lowercase(self):
        with pytest.raises(ValueError, match="lowercase"):

            class Bad(Extension):
                name = "Bad"

    def test_name_must_be_identifier(self):
        with pytest.raises(ValueError, match="identifier"):

            class Bad(Extension):
                name = "not-an-identifier"


class TestManagerConstruction:
    def test_default_citry_has_only_builtins(self):
        c = _Citry()
        # Every instance carries the built-in extensions (prepended by the
        # manager); with no user extensions, that is all there is.
        assert [ext.name for ext in c.extensions._extensions] == ["dependencies"]

    def test_accepts_class_and_instance(self):
        class E1(Extension):
            name = "e1"

        class E2(Extension):
            name = "e2"

        c = _Citry(extensions=[E1, E2()])
        # Built-ins come first, then the user's extensions in spec order.
        assert [ext.name for ext in c.extensions._extensions] == ["dependencies", "e1", "e2"]

    def test_accepts_string_path(self):
        spec = f"{_StringPathExt.__module__}.{_StringPathExt.__qualname__}"
        c = _Citry(extensions=[spec])
        assert c.extensions.get_extension("strext") is not None

    def test_extension_created_fires(self):
        seen = []

        class E(Extension):
            name = "e"

            def on_extension_created(self, ctx):
                seen.append(ctx.extension)

        c = _Citry(extensions=[E])
        assert seen == [c.extensions.get_extension("e")]

    def test_duplicate_names_rejected(self):
        class A(Extension):
            name = "dup"

        class B(Extension):
            name = "dup"

        with pytest.raises(ValueError, match="share the name"):
            _Citry(extensions=[A, B])

    def test_name_clashing_with_component_api_rejected(self):
        class Tmpl(Extension):
            name = "template"  # Component.template exists

        with pytest.raises(ValueError, match="conflicts"):
            _Citry(extensions=[Tmpl])


class TestClassAndRegistrationHooks:
    def test_class_created_and_registered(self):
        events = []

        class E(Extension):
            name = "e"

            def on_component_class_created(self, ctx):
                events.append(("created", ctx.component_class.__name__))

            def on_component_registered(self, ctx):
                events.append(("registered", ctx.name, ctx.component_class.__name__))

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app

        assert ("created", "Card") in events
        assert ("registered", "Card", "Card") in events
        # created fires before registered
        assert events.index(("created", "Card")) < events.index(("registered", "Card", "Card"))

    def test_unregistered_fires(self):
        names = []

        class E(Extension):
            name = "e"

            def on_component_unregistered(self, ctx):
                names.append(ctx.name)

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app

        app.unregister(Card)
        assert names == ["Card"]

    def test_ctx_carries_citry(self):
        captured = {}

        class E(Extension):
            name = "e"

            def on_component_registered(self, ctx):
                captured["citry"] = ctx.citry

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app

        assert captured["citry"] is app


class TestRenderHooks:
    def test_input_mutation_lands_on_raw_kwargs(self):
        captured = {}

        class E(Extension):
            name = "e"

            def on_component_input(self, ctx):
                ctx.kwargs["injected"] = 42

            def on_component_data(self, ctx):
                captured["raw"] = dict(ctx.component.raw_kwargs)

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app
            template = "<p>hi</p>"

        str(Card(title="x"))
        assert captured["raw"]["injected"] == 42

    def test_data_mutation_visible_in_render(self):
        class E(Extension):
            name = "e"

            def on_component_data(self, ctx):
                ctx.template_data["who"] = "world"

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app
            template = "<p>Hello {{ who }}</p>"

        assert str(Card()) == '<p data-cid-c1="">Hello world</p>'

    def test_rendered_replace_with_string(self):
        class E(Extension):
            name = "e"

            def on_component_rendered(self, ctx):
                return "<wrapped/>"

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app
            template = "<p>hi</p>"

        assert str(Card()) == '<wrapped data-cid-c1=""/>'

    def test_rendered_receives_citryrender(self):
        captured = {}

        class E(Extension):
            name = "e"

            def on_component_rendered(self, ctx):
                captured["render"] = ctx.render

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app
            template = "<p>hi</p>"

        str(Card())
        assert isinstance(captured["render"], CitryRender)

    def test_rendered_raise_propagates(self):
        class E(Extension):
            name = "e"

            def on_component_rendered(self, ctx):
                raise ValueError("boom")

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app
            template = "<p>hi</p>"

        with pytest.raises(ValueError, match="boom"):
            str(Card())


class TestTemplateHooks:
    def test_template_loaded_modifies_string(self):
        class E(Extension):
            name = "e"

            def on_template_loaded(self, ctx):
                return ctx.content.replace("Hello", "Hi")

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app
            template = "<p>Hello</p>"

        assert str(Card()) == '<p data-cid-c1="">Hi</p>'

    def test_template_loaded_threads_in_order(self):
        class E1(Extension):
            name = "e1"

            def on_template_loaded(self, ctx):
                return ctx.content + "1"

        class E2(Extension):
            name = "e2"

            def on_template_loaded(self, ctx):
                return ctx.content + "2"

        app = _Citry(extensions=[E1, E2])

        class Card(Component):
            citry = app
            template = "x"

        assert str(Card()) == "x12"

    def test_template_compiled_receives_node_list(self):
        captured = {}

        class E(Extension):
            name = "e"

            def on_template_compiled(self, ctx):
                captured["nodes"] = list(ctx.nodes)
                captured["cls"] = ctx.component_class.__name__

        app = _Citry(extensions=[E])

        class Card(Component):
            citry = app
            template = "<p>{{ x }}</p>"

            def template_data(self, kwargs, slots):
                return {"x": "hi"}

        str(Card())
        assert isinstance(captured["nodes"], list)
        assert captured["cls"] == "Card"


class TestSmartDispatch:
    def test_only_overriding_extensions_define_the_hook(self):
        # Uses hooks the built-in dependencies extension does not implement,
        # so the expected lists are exact.
        class Partial(Extension):
            name = "partial"

            def on_component_input(self, ctx):
                pass

        app = _Citry(extensions=[Partial])
        mgr = app.extensions
        inst = mgr.get_extension("partial")
        assert mgr._extensions_with_hook("on_component_input") == (inst,)
        assert mgr._extensions_with_hook("on_component_rendered") == ()

    def test_hook_extension_list_is_cached(self):
        class E(Extension):
            name = "e"

            def on_component_data(self, ctx):
                pass

        app = _Citry(extensions=[E])
        mgr = app.extensions
        first = mgr._extensions_with_hook("on_component_data")
        assert mgr._extensions_with_hook("on_component_data") is first


class TestComponentConfig:
    def test_config_attached_to_instance(self):
        captured = {}

        class ViewExt(Extension):
            name = "view"

        app = _Citry(extensions=[ViewExt])

        class Page(Component):
            citry = app
            template = "<p>hi</p>"

            class View:
                greeting = "hello"

        # nested class rebuilt as a subclass of the extension's Config base
        assert issubclass(Page.View, ViewExt.Config)

        class Probe(Extension):
            name = "probe"

            def on_component_data(self, ctx):
                captured["view"] = ctx.component.view

        app2 = _Citry(extensions=[ViewExt, Probe])

        class Page2(Component):
            citry = app2
            template = "<p>hi</p>"

            class View:
                greeting = "hello"

        str(Page2())
        assert captured["view"].greeting == "hello"
        assert captured["view"].component_class is Page2

    def test_config_component_backref(self):
        captured = {}

        class ViewExt(Extension):
            name = "view"

            class Config(Extension.Config):
                def title(self):
                    return type(self.component).__name__

        app = _Citry(extensions=[ViewExt])

        class Page(Component):
            citry = app
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots):
                captured["title"] = self.view.title()
                return {}

        str(Page())
        assert captured["title"] == "Page"

    def test_config_out_of_lifecycle_raises(self):
        class E(Extension):
            name = "e"

        cfg = E.Config(None)
        with pytest.raises(RuntimeError, match="outside a component lifecycle"):
            _ = cfg.component

    def test_defaults_precedence(self):
        # factory < global defaults < component-level
        class CfgExt(Extension):
            name = "cfg"

            class Config(Extension.Config):
                ttl = 1

        # factory only
        app_factory = _Citry(extensions=[CfgExt])

        class A(Component):
            citry = app_factory

        assert A.Cfg.ttl == 1

        # global defaults override factory
        app_global = _Citry(extensions=[CfgExt], extensions_defaults={"cfg": {"ttl": 2}})

        class B(Component):
            citry = app_global

        assert B.Cfg.ttl == 2

        # component-level overrides global
        app_comp = _Citry(extensions=[CfgExt], extensions_defaults={"cfg": {"ttl": 2}})

        class C(Component):
            citry = app_comp

            class Cfg:
                ttl = 3

        assert C.Cfg.ttl == 3


class TestCommands:
    def test_no_commands_by_default(self):
        # The default instance carries only built-in extensions, none of which
        # declare commands.
        assert _Citry().commands == {}

    def test_commands_keyed_by_extension(self):
        class Hello(ExtensionCommand):
            name = "hello"

            def handle(self, **kwargs): ...

        class Greeter(Extension):
            name = "greeter"
            commands = [Hello]

        assert _Citry(extensions=[Greeter]).commands == {"greeter": (Hello,)}

    def test_extensions_without_commands_are_omitted(self):
        class Hello(ExtensionCommand):
            name = "hello"

            def handle(self, **kwargs): ...

        class WithCmd(Extension):
            name = "withcmd"
            commands = [Hello]

        class WithoutCmd(Extension):
            name = "withoutcmd"

        # Built-ins come first; only extensions that declare commands appear.
        assert list(_Citry(extensions=[WithCmd, WithoutCmd]).commands) == ["withcmd"]

    def test_get_extension_command_resolves(self):
        class Hello(ExtensionCommand):
            name = "hello"

            def handle(self, **kwargs): ...

        class Greeter(Extension):
            name = "greeter"
            commands = [Hello]

        manager = _Citry(extensions=[Greeter]).extensions
        assert manager.get_extension_command("greeter", "hello") is Hello

    def test_get_extension_command_missing_raises(self):
        class Greeter(Extension):
            name = "greeter"

        manager = _Citry(extensions=[Greeter]).extensions
        with pytest.raises(ValueError, match="not found"):
            manager.get_extension_command("greeter", "nope")
