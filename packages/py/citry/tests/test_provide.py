"""
Tests for provide/inject (docs/design/provide.md): the ``Component.provide``
/ ``Component.inject`` APIs, the ``<c-provide>`` built-in component, how
provided data crosses component and slot boundaries, and the built-in name
reservation.

The behavioral contract is ported from django-components
(``_djc_tests/test_templatetags_provide.py``), with the DJC global-cache
assertions dropped (citry keeps provided data on plain references, so there
is no cache to leak) and DJC's three skipped forloop tests active.
"""

import pytest

from citry import AlreadyRegistered, Citry, Component
from citry.provide import MISSING, make_provided, validate_provide_key


def _make_citry():
    return Citry()


def _make_injectee(c, key="my_provide", default=MISSING, name=None):
    """A component rendering ``{{ injected }}`` (the payload repr, or the default)."""

    class Injectee(Component):
        citry = c
        template = "<div>{{ injected }}</div>"

        def template_data(self, kwargs, slots=None):
            if default is MISSING:
                injected = self.inject(key)
            else:
                injected = self.inject(key, default)
            return {"injected": injected}

    if name is not None:
        Injectee.__name__ = name
    return Injectee


class TestProvideComponent:
    def test_basic(self):
        c = _make_citry()

        class Greeting(Component):
            citry = c
            template = "<div>{{ text }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"text": self.inject("my_provide").text}

        class Page(Component):
            citry = c
            template = '<main><c-provide key="my_provide" text="hi"><c-greeting /></c-provide></main>'

        # ids: Page c1, the (transparent) provide c2, Greeting c3.
        assert str(Page()) == '<main data-cid-c1=""><div data-cid-c3="">hi</div></main>'

    def test_payload_attribute_access(self):
        c = _make_citry()
        seen = {}

        class Reader(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                seen["payload"] = self.inject("my_provide")
                return {}

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" text="hi" c-num="1 + 1"><c-reader /></c-provide>'

        str(Page())
        payload = seen["payload"]
        # Static attributes resolve to strings, c-* attributes to their value.
        assert payload.text == "hi"
        assert payload.num == 2

    def test_payload_repr_renders_escaped(self):
        c = _make_citry()
        _make_injectee(c)

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" text="hi"><c-injectee /></c-provide>'

        assert str(Page()) == '<div data-cid-c3="" data-cid-c1="">Provided(text=&#39;hi&#39;)</div>'

    def test_self_closing_renders_empty(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = '<main><c-provide key="my_provide" text="hi" /></main>'

        assert str(Page()) == '<main data-cid-c1=""></main>'

    def test_not_visible_after_closing_tag(self):
        c = _make_citry()
        _make_injectee(c, default="NONE")

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" a="1"><c-injectee /></c-provide><c-injectee />'

        assert str(Page()) == (
            '<div data-cid-c3="" data-cid-c1="">Provided(a=&#39;1&#39;)</div>'
            '<div data-cid-c4="" data-cid-c1="">NONE</div>'
        )

    def test_empty_data_still_injectable(self):
        c = _make_citry()
        seen = {}

        class Reader(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                seen["payload"] = self.inject("my_provide")
                return {}

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide"><c-reader /></c-provide>'

        str(Page())
        assert seen["payload"] == ()

    def test_no_inject_is_fine(self):
        c = _make_citry()

        class Plain(Component):
            citry = c
            template = "<p>x</p>"

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" a="1"><c-plain /></c-provide>'

        assert str(Page()) == '<p data-cid-c3="" data-cid-c1="">x</p>'

    def test_dynamic_key(self):
        c = _make_citry()
        _make_injectee(c)

        class Page(Component):
            citry = c
            template = '<c-provide c-key="key_var" text="hi"><c-injectee /></c-provide>'

            def template_data(self, kwargs, slots=None):
                return {"key_var": "my_provide"}

        assert "Provided(text=&#39;hi&#39;)" in str(Page())

    def test_key_via_bind_spread(self):
        c = _make_citry()
        _make_injectee(c)

        class Page(Component):
            citry = c
            template = '<c-provide c-bind="props"><c-injectee /></c-provide>'

            def template_data(self, kwargs, slots=None):
                return {"props": {"key": "my_provide", "text": "hi"}}

        assert "Provided(text=&#39;hi&#39;)" in str(Page())

    def test_missing_key_raises(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = '<c-provide text="hi">x</c-provide>'

        with pytest.raises(ValueError, match="requires a 'key' attribute"):
            str(Page())

    def test_non_string_key_raises(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            # `key=""` normalizes to a boolean attribute (True), which is not
            # a usable key, same as any other non-string value.
            template = '<c-provide key="">x</c-provide>'

        with pytest.raises(ValueError, match="non-empty string"):
            str(Page())

    def test_non_identifier_key_raises(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = '<c-provide key="%heya%">x</c-provide>'

        with pytest.raises(ValueError, match="valid identifier"):
            str(Page())

    def test_data_does_not_enter_template_variables(self):
        c = _make_citry()

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" c-a="\'provided\'">{{ a }}</c-provide>'

            def template_data(self, kwargs, slots=None):
                return {"a": "outer"}

        # The provide body renders in the page's scope; the provided field
        # named `a` does not shadow the page's variable.
        assert "outer" in str(Page())
        assert "provided" not in str(Page())

    def test_nested_same_key_inner_shadows_wholesale(self):
        c = _make_citry()
        _make_injectee(c, default="NONE")

        class Page(Component):
            citry = c
            template = (
                '<c-provide key="my_provide" a="1" lost="0">'
                '<c-provide key="my_provide" a="2" new="3"><c-injectee /></c-provide>'
                "<c-injectee />"
                "</c-provide>"
                "<c-injectee />"
            )

        html = str(Page())
        # Inner provide replaces the outer payload entirely: `lost` is gone.
        assert "Provided(a=&#39;2&#39;, new=&#39;3&#39;)" in html
        assert "Provided(a=&#39;1&#39;, lost=&#39;0&#39;)" in html
        assert "NONE" in html

    def test_nested_different_keys_compose(self):
        c = _make_citry()
        seen = {}

        class Reader(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                seen["first"] = self.inject("first_provide")
                seen["second"] = self.inject("second_provide")
                return {}

        class Page(Component):
            citry = c
            template = (
                '<c-provide key="first_provide" a="1">'
                '<c-provide key="second_provide" b="2"><c-reader /></c-provide>'
                "</c-provide>"
            )

        str(Page())
        assert seen["first"].a == "1"
        assert seen["second"].b == "2"

    def test_provide_inside_for_loop(self):
        # Active in citry; the DJC equivalents are skipped upstream over
        # global-state cleanup (django-components #1413).
        c = _make_citry()

        class Item(Component):
            citry = c
            template = "<li>{{ v }}</li>"

            def template_data(self, kwargs, slots=None):
                return {"v": self.inject("loop_data").val}

        class Page(Component):
            citry = c
            template = (
                '<ul><c-for each="item in items">'
                '<c-provide key="loop_data" c-val="item"><c-item /></c-provide>'
                "</c-for></ul>"
            )

            def template_data(self, kwargs, slots=None):
                return {"items": [1, 2, 3]}

        html = str(Page())
        assert "<li" in html
        assert ">1</li>" in html
        assert ">2</li>" in html
        assert ">3</li>" in html

    def test_readme_example(self):
        c = _make_citry()

        class Themed(Component):
            citry = c
            template = "<span>{{ mode }}</span>"

            def template_data(self, kwargs, slots=None):
                return {"mode": self.inject("theme").mode}

        class Page(Component):
            citry = c
            template = '<c-provide key="theme" mode="dark"><c-themed /></c-provide>'

        assert "dark" in str(Page())


class TestComponentProvideApi:
    def test_provide_from_template_data(self):
        c = _make_citry()

        class Child(Component):
            citry = c
            template = "<span>{{ user }}</span>"

            def template_data(self, kwargs, slots=None):
                return {"user": self.inject("user_data").user}

        class Page(Component):
            citry = c
            template = "<c-child />"

            def template_data(self, kwargs, slots=None):
                self.provide("user_data", user="Jo")
                return {}

        assert str(Page()) == '<span data-cid-c2="" data-cid-c1="">Jo</span>'

    def test_key_is_positional_only(self):
        c = _make_citry()
        seen = {}

        class Child(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                seen["payload"] = self.inject("theme")
                return {}

        class Page(Component):
            citry = c
            template = "<c-child />"

            def template_data(self, kwargs, slots=None):
                # A provided field may itself be named `key`.
                self.provide("theme", key="x")
                return {}

        str(Page())
        assert seen["payload"].key == "x"

    def test_invalid_keys_raise(self):
        comp = Component.__new__(Component)
        comp._provides_inherited = {}
        comp._provides_own = {}
        with pytest.raises(ValueError, match="non-empty string"):
            comp.provide("")
        with pytest.raises(ValueError, match="non-empty string"):
            comp.provide(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="valid identifier"):
            comp.provide("not-an-identifier")

    def test_payload_is_immutable(self):
        payload = make_provided({"a": 1})
        assert isinstance(payload, tuple)
        with pytest.raises(AttributeError):
            payload.a = 2  # type: ignore[attr-defined]

    def test_own_provide_not_visible_to_own_inject(self):
        c = _make_citry()
        seen = {}

        class Page(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                self.provide("mine", a=1)
                seen["value"] = self.inject("mine", "NOT VISIBLE")
                return {}

        str(Page())
        assert seen["value"] == "NOT VISIBLE"


class TestInject:
    def test_missing_key_raises_keyerror(self):
        c = _make_citry()
        _make_injectee(c, key="abc")

        class Page(Component):
            citry = c
            template = "<c-injectee />"

        # KeyError str() shows the message repr, so match without the quotes.
        with pytest.raises(KeyError, match=r"Injectee.*tried to inject.*abc"):
            str(Page())

    def test_did_you_mean_hint(self):
        c = _make_citry()
        _make_injectee(c, key="my_provid")

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" a="1"><c-injectee /></c-provide>'

        with pytest.raises(KeyError, match=r"Did you mean.*my_provide"):
            str(Page())

    def test_default_returned_when_missing(self):
        c = _make_citry()
        _make_injectee(c, key="abc", default="default")

        class Page(Component):
            citry = c
            template = "<c-injectee />"

        assert "default" in str(Page())

    def test_explicit_none_default(self):
        c = _make_citry()
        seen = {}

        class Reader(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                seen["value"] = self.inject("abc", None)
                return {}

        str(Reader())
        assert seen["value"] is None

    def test_empty_string_key_raises(self):
        c = _make_citry()
        _make_injectee(c, key="")

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" a="1"><c-injectee /></c-provide>'

        with pytest.raises(KeyError):
            str(Page())

    def test_inject_after_render(self):
        c = _make_citry()
        captured = {}

        class Reader(Component):
            citry = c
            template = "<p>x</p>"

            def template_data(self, kwargs, slots=None):
                captured["self"] = self
                return {}

        class Page(Component):
            citry = c
            template = '<c-provide key="my_provide" text="hi"><c-reader /></c-provide>'

        str(Page())
        # The provided data stays reachable through the kept instance.
        payload = captured["self"].inject("my_provide")
        assert payload.text == "hi"


class TestProvideAcrossSlots:
    def test_slot_in_provide(self):
        # A provider component wraps a <c-slot>; content filled in from
        # outside the provider can inject what it provides. (DJC
        # test_slot_in_provide.)
        c = _make_citry()
        _make_injectee(c)

        class Parent(Component):
            citry = c
            template = '<c-provide key="my_provide" text="hi"><c-slot /></c-provide>'

        class Page(Component):
            citry = c
            template = "<c-parent><c-injectee /></c-parent>"

        # ids: Page c1, Parent c2, provide c3, Injectee c4. The injectee is
        # Parent's root content, which is Page's root content, so the
        # markers stack.
        assert str(Page()) == (
            '<div data-cid-c4="" data-cid-c2="" data-cid-c1="">Provided(text=&#39;hi&#39;)</div>'
        )

    def test_inject_in_fill(self):
        # DJC test_inject_in_fill (PR #778): the injectee is written in a
        # fill two components up; the provider provides around the slot
        # that renders it.
        c = _make_citry()

        class Provider(Component):
            citry = c
            template = '<c-provide key="my_provide" c-data="data"><c-slot /></c-provide>'

            def template_data(self, kwargs, slots=None):
                return {"data": kwargs["data"]}

        class Injectee(Component):
            citry = c
            template = "<div>{{ d }}</div><main><c-slot /></main>"

            def template_data(self, kwargs, slots=None):
                return {"d": self.inject("my_provide").data}

        class Parent(Component):
            citry = c
            template = '<c-provider c-data="data"><c-injectee><c-slot /></c-injectee></c-provider>'

            def template_data(self, kwargs, slots=None):
                return {"data": kwargs["data"]}

        class Page(Component):
            citry = c
            template = '<c-parent c-data="123">456</c-parent>'

        html = str(Page())
        assert ">123</div>" in html
        assert ">456</main>" in html

    def test_inject_in_slot_in_fill(self):
        # DJC test_inject_in_slot_in_fill (PR #786): the injectee passes
        # through two slot hops before rendering inside the provide.
        c = _make_citry()

        class Provider(Component):
            citry = c
            template = '<c-provide key="my_provide" c-data="data"><c-slot /></c-provide>'

            def template_data(self, kwargs, slots=None):
                return {"data": kwargs["data"]}

        class Injectee(Component):
            citry = c
            template = "<div>{{ d }}</div>"

            def template_data(self, kwargs, slots=None):
                return {"d": self.inject("my_provide").data}

        class Parent(Component):
            citry = c
            template = '<c-provider c-data="data"><c-slot /></c-provider>'

            def template_data(self, kwargs, slots=None):
                return {"data": kwargs["data"]}

        class Page(Component):
            citry = c
            template = '<c-parent c-data="123"><c-injectee /></c-parent>'

        assert ">123</div>" in str(Page())

    def test_provide_reaches_slot_fallback(self):
        c = _make_citry()
        _make_injectee(c)

        class Parent(Component):
            citry = c
            template = '<c-provide key="my_provide" text="hi"><c-slot><c-injectee /></c-slot></c-provide>'

        class Page(Component):
            citry = c
            template = "<c-parent />"

        assert "Provided(text=&#39;hi&#39;)" in str(Page())


class TestPythonChannel:
    def test_element_in_slots_kwarg_inherits_provides(self):
        c = _make_citry()
        injectee_cls = _make_injectee(c)
        provide_cls = c.get("provide")

        element = provide_cls(key="my_provide", text="hi", slots={"default": injectee_cls()})
        assert str(element) == '<div data-cid-c2="">Provided(text=&#39;hi&#39;)</div>'

    def test_slot_function_result_inherits_provides(self):
        c = _make_citry()
        injectee_cls = _make_injectee(c)
        provide_cls = c.get("provide")

        element = provide_cls(key="my_provide", text="hi", slots={"default": lambda _ctx: injectee_cls()})
        assert "Provided(text=&#39;hi&#39;)" in str(element)

    def test_expression_element_inherits_provides(self):
        c = _make_citry()
        injectee_cls = _make_injectee(c, key="user_data")

        class Page(Component):
            citry = c
            template = "<div>{{ el }}</div>"

            def template_data(self, kwargs, slots=None):
                self.provide("user_data", user="Jo")
                return {"el": injectee_cls()}

        assert "Provided(user=&#39;Jo&#39;)" in str(Page())

    def test_standalone_render_starts_empty(self):
        c = _make_citry()
        _make_injectee(c, default="NONE")

        # A plain user .render() call inherits nothing.
        injectee_cls = c.get("injectee")
        assert "NONE" in str(injectee_cls())


class TestTransparent:
    def test_provide_adds_no_marker(self):
        c = _make_citry()

        class Inner(Component):
            citry = c
            template = "<span>{{ v }}</span>"

            def template_data(self, kwargs, slots=None):
                return {"v": self.inject("x").a}

        class Page(Component):
            citry = c
            template = '<main><c-provide key="x" a="1"><c-inner /></c-provide></main>'

        html = str(Page())
        # Exactly two components leave markers: Page and Inner. The provide
        # consumed the id c2 but is transparent.
        assert html == '<main data-cid-c1=""><span data-cid-c3="">1</span></main>'

    def test_provide_as_serialize_root(self):
        c = _make_citry()
        provide_cls = c.get("provide")

        element = provide_cls(key="x", a="1", slots={"default": "hello"})
        assert str(element) == "hello"


class TestBuiltinReservedNames:
    def test_builtin_resolves_without_registration(self):
        c = _make_citry()
        assert c.has("provide")
        assert issubclass(c.get("provide"), Component)

    def test_class_named_provide_raises(self):
        c = _make_citry()
        with pytest.raises(AlreadyRegistered, match="built-in <c-provide>"):

            class Provide(Component):
                citry = c
                template = "<p>x</p>"

    def test_explicit_builtin_names_raise(self):
        c = _make_citry()

        class Mine(Component):
            citry = c
            template = "<p>x</p>"

        for reserved in ("provide", "js", "css"):
            with pytest.raises(AlreadyRegistered, match=f"built-in <c-{reserved}>"):
                c.register(Mine, name=reserved)

    def test_builtins_recreated_after_clear(self):
        c = _make_citry()
        assert c.has("provide")
        c.clear()
        assert c.has("provide")

    def test_direct_registry_register_is_guarded(self):
        # The reservation lives on the registry itself, so bypassing Citry
        # and registering on the registry directly is rejected too.
        c = _make_citry()

        class Mine(Component):
            citry = c
            template = "<p>x</p>"

        with pytest.raises(AlreadyRegistered, match="built-in <c-provide>"):
            c.registry.register(Mine, name="provide")


class TestDeepNesting:
    def test_provide_survives_deep_component_chains(self):
        c = _make_citry()

        class Leaf(Component):
            citry = c
            template = "<b>{{ v }}</b>"

            def template_data(self, kwargs, slots=None):
                return {"v": self.inject("deep").v}

        class Nested(Component):
            citry = c
            template = '<c-if cond="n > 0"><c-nested c-n="n - 1" /></c-if><c-else><c-leaf /></c-else>'

            def template_data(self, kwargs, slots=None):
                return {"n": kwargs["n"]}

        class Page(Component):
            citry = c
            template = '<c-provide key="deep" v="found"><c-nested c-n="300" /></c-provide>'

        # 300 component levels: well past Python's recursion limit for a
        # naive renderer; the provides ride the queue with the elements.
        assert ">found</b>" in str(Page())


class TestValidateKeyHelper:
    def test_valid_key_returned(self):
        assert validate_provide_key("my_key") == "my_key"

    def test_rejects_non_strings_and_non_identifiers(self):
        for bad in ("", None, 1, True, "with-dash", "with space", "1leading"):
            with pytest.raises(ValueError, match="Provide key"):
                validate_provide_key(bad)
