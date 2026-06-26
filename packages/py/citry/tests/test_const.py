"""
Tests for the Const optimization (citry/constness.py): the Const marker, the
cache key built from marked values, the precomputing step that pre-computes the
constant parts of a template, and the cache that stores the results.
"""

# ruff: noqa: ANN

import pytest

from citry import Citry, Component, Const
from citry.constness import (
    _MAX_UNROLL_ITERATIONS,
    _UNFREEZABLE,
    ConstBodyCache,
    const_value,
    extract_const_vars,
    freeze_const,
    is_const,
)
from citry.nodes import ComponentNode, ExprNode, IfNode, SlotNode


class _Unhashable:
    """Equality without hashability: no stable, value-based cache key."""

    def __init__(self, x):
        self.x = x

    def __eq__(self, other):
        return isinstance(other, _Unhashable) and self.x == other.x

    __hash__ = None


class TestConstMarker:
    def test_is_const(self):
        assert is_const(Const(3))
        assert not is_const(3)
        assert not is_const("x")

    def test_const_value_unwraps(self):
        assert const_value(Const(3)) == 3
        assert const_value(Const("hi")) == "hi"

    def test_const_value_passthrough_for_plain(self):
        assert const_value(3) == 3
        assert const_value("hi") == "hi"

    def test_repr_is_transparent(self):
        # repr forwards to the wrapped value: the engine marks template
        # literals without the user opting in, so a marked value inside a
        # container must repr exactly like the plain value.
        assert repr(Const(3)) == "3"
        assert repr(Const("hi")) == "'hi'"
        assert repr({"text": Const("hi")}) == "{'text': 'hi'}"


class TestFreezeConst:
    def test_equal_values_freeze_equal(self):
        assert freeze_const([1, 2]) == freeze_const([1, 2])
        assert freeze_const({"a": 1, "b": 2}) == freeze_const({"b": 2, "a": 1})
        assert freeze_const({1, 2}) == freeze_const({2, 1})
        assert freeze_const("hi") == freeze_const("hi")

    def test_distinct_values_freeze_distinct(self):
        assert freeze_const([1, 2]) != freeze_const([1, 3])
        assert freeze_const([1, 2]) != freeze_const((1, 2))
        assert freeze_const({"a": 1}) != freeze_const({"a": 2})

    def test_type_distinguishes_equal_values(self):
        # True == 1 and 1 == 1.0, but they render differently, so they must
        # not share a cache key.
        assert freeze_const(True) != freeze_const(1)  # noqa: FBT003
        assert freeze_const(1) != freeze_const(1.0)

    def test_nested_const_is_unwrapped(self):
        assert freeze_const(Const([Const(1), 2])) == freeze_const([1, 2])

    def test_frozen_form_is_hashable(self):
        hash(freeze_const([1, {"a": {2, 3}}, ("b",)]))

    def test_freeze_is_memoized_on_the_marker(self):
        # Const is a promise the value does not change, so the frozen key is
        # computed once per marker and reused; mutating the wrapped value
        # afterwards breaks the promise and does NOT change the key.
        marked = Const([1, 2])
        first = freeze_const(marked)
        assert freeze_const(marked) is first
        marked.append(3)
        assert freeze_const(marked) is first

    def test_unhashable_non_container_is_unfreezable(self):
        assert freeze_const(_Unhashable(1)) is _UNFREEZABLE
        # An unfreezable leaf poisons its containers.
        assert freeze_const([_Unhashable(1)]) is _UNFREEZABLE
        assert freeze_const({"k": _Unhashable(1)}) is _UNFREEZABLE


class TestExtractConstVars:
    def test_splits_const_from_dynamic(self):
        const_vars, signature = extract_const_vars({"a": Const(1), "b": 2})
        assert list(const_vars) == ["a"]
        assert const_vars["a"] == 1
        assert signature == frozenset({("a", freeze_const(1))})

    def test_unfreezable_const_is_demoted_everywhere(self):
        # The variable must drop out of BOTH the const set and the signature,
        # so precomputing and the cache key always agree.
        const_vars, signature = extract_const_vars({"a": Const(_Unhashable(1))})
        assert const_vars == {}
        assert signature == frozenset()


class TestConstFlow:
    def test_const_input_renders(self):
        # A Const input passed through template_data must not break rendering.
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        assert Card(cols=Const(3)).render().serialize() == '<p data-cid-c1="">hi</p>'

    def test_const_signature_keys_the_cache(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ cols }}</p>"

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        # Different const values -> different signatures -> two cache entries.
        Card(cols=Const(3)).render()
        Card(cols=Const(5)).render()
        assert len(c._const_body_cache) == 2

        # Same signature again -> cache hit, no new entry.
        Card(cols=Const(3)).render()
        assert len(c._const_body_cache) == 2

    def test_unused_const_var_does_not_split_the_cache(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"  # uses no variables

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        # The template never reads `cols`, so its const values cannot affect
        # the body: both renders share one cache entry (the empty signature).
        Card(cols=Const(3)).render()
        Card(cols=Const(5)).render()
        assert len(c._const_body_cache) == 1

    def test_non_const_var_not_in_signature(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        # Plain (non-Const) values do not enter the signature, so both renders
        # share the empty signature and a single cache entry.
        Card(cols=3).render()
        Card(cols=5).render()
        assert len(c._const_body_cache) == 1

    def test_container_const_value_keys_by_value(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ rows }}</p>"

            def template_data(self, kwargs, slots):
                return {"rows": kwargs["rows"]}

        # Equal lists (distinct objects) share one canonical key.
        Card(rows=Const([1, 2, 3])).render()
        Card(rows=Const([1, 2, 3])).render()
        assert len(c._const_body_cache) == 1
        Card(rows=Const([1, 2, 4])).render()
        assert len(c._const_body_cache) == 2

    def test_unfreezable_const_value_renders_as_dynamic(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ obj.x }}</p>"

            def template_data(self, kwargs, slots):
                return {"obj": kwargs["obj"]}

        # The value cannot be keyed, so it is demoted to dynamic: both renders
        # share the empty signature, and the expression re-evaluates each time.
        assert Card(obj=Const(_Unhashable(1))).render().serialize() == '<p data-cid-c1="">1</p>'
        assert Card(obj=Const(_Unhashable(2))).render().serialize() == '<p data-cid-c2="">2</p>'
        assert len(c._const_body_cache) == 1

    def test_bool_and_int_const_do_not_share_a_body(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ v }}</p>"

            def template_data(self, kwargs, slots):
                return {"v": kwargs["v"]}

        assert Card(v=Const(True)).render().serialize() == '<p data-cid-c1="">True</p>'  # noqa: FBT003
        assert Card(v=Const(1)).render().serialize() == '<p data-cid-c2="">1</p>'
        assert len(c._const_body_cache) == 2

    def test_clear_empties_the_cache(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>hi</p>"

        Card().render()
        assert len(c._const_body_cache) >= 1
        c.clear()
        assert len(c._const_body_cache) == 0


class TestConstPrecompute:
    def test_const_expr_precomputes_to_static_text(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ cols }}</p>"

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        assert Card(cols=Const(3)).render().serialize() == '<p data-cid-c1="">3</p>'
        (body,) = c._const_body_cache.values()
        assert body == ["<p>3</p>"]

    def test_dynamic_expr_stays_dynamic_in_shared_body(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ cols }} and {{ other }}</p>"

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"], "other": kwargs["other"]}

        # Two renders share the const signature but differ in the dynamic input.
        assert Card(cols=Const(3), other="x").render().serialize() == '<p data-cid-c1="">3 and x</p>'
        assert Card(cols=Const(3), other="y").render().serialize() == '<p data-cid-c2="">3 and y</p>'
        assert len(c._const_body_cache) == 1

        (body,) = c._const_body_cache.values()
        first, node, last = body
        assert first == "<p>3 and "
        assert isinstance(node, ExprNode)
        assert last == "</p>"

    def test_precomputed_value_is_escaped(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ v }}</p>"

            def template_data(self, kwargs, slots):
                return {"v": kwargs["v"]}

        assert Card(v=Const("<b>")).render().serialize() == '<p data-cid-c1="">&lt;b&gt;</p>'

    def test_const_none_precomputes_to_empty(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ v }}</p>"

            def template_data(self, kwargs, slots):
                return {"v": kwargs["v"]}

        assert Card(v=Const(None)).render().serialize() == '<p data-cid-c1=""></p>'
        assert Card(v=None).render().serialize() == '<p data-cid-c2=""></p>'

    def test_const_if_branch_is_pruned(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="cols > 2">big</c-if><c-else>small</c-else>'

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        assert Card(cols=Const(3)).render().serialize() == "big"
        assert Card(cols=Const(1)).render().serialize() == "small"
        big_body, small_body = c._const_body_cache.values()
        assert big_body == ["big"]
        assert small_body == ["small"]

    def test_const_if_with_no_match_precomputes_to_nothing(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="cols > 2">big</c-if>'

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        assert Card(cols=Const(1)).render().serialize() == ""
        (body,) = c._const_body_cache.values()
        assert body == []

    def test_dynamic_if_keeps_the_node(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="cols > 2">big</c-if><c-else>small</c-else>'

            def template_data(self, kwargs, slots):
                return {"cols": kwargs["cols"]}

        assert Card(cols=3).render().serialize() == "big"
        assert Card(cols=1).render().serialize() == "small"
        (body,) = c._const_body_cache.values()
        (node,) = body
        assert isinstance(node, IfNode)

    def test_pruned_branch_is_precomputed_recursively(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="show">{{ label }}: {{ count }}</c-if>'

            def template_data(self, kwargs, slots):
                return {"show": kwargs["show"], "label": kwargs["label"], "count": kwargs["count"]}

        out = Card(show=Const(True), label=Const("n"), count=7).render().serialize()  # noqa: FBT003
        assert out == "n: 7"
        (body,) = c._const_body_cache.values()
        first, node = body
        assert first == "n: "
        assert isinstance(node, ExprNode)

    def test_zero_variable_expr_precomputes_without_const_inputs(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ 1 + 1 }}</p>"

        assert Card().render().serialize() == '<p data-cid-c1="">2</p>'
        (body,) = c._const_body_cache.values()
        assert body == ["<p>2</p>"]

    def test_slot_node_never_precomputes(self):
        c = Citry()

        class Box(Component):
            citry = c
            template = '<div><c-slot name="s">fb</c-slot></div>'

        class Page(Component):
            citry = c
            template = '<c-Box><c-fill name="s">{{ msg }}</c-fill></c-Box>'

            def template_data(self, kwargs, slots):
                return {"msg": kwargs["msg"], "k": kwargs["k"]}

        # Same const signature, different fills: the cached Box body must keep
        # the SlotNode so each render picks up its own fill.
        assert "one" in Page(msg="one", k=Const(1)).render().serialize()
        assert "two" in Page(msg="two", k=Const(1)).render().serialize()

        box_bodies = [
            body
            for body in c._const_body_cache.values()
            if any(isinstance(item, SlotNode) for item in body if not isinstance(item, str))
        ]
        assert len(box_bodies) == 1

    def test_const_element_value_is_not_precomputed(self):
        c = Citry()

        class Inner(Component):
            citry = c
            template = "<span>inner</span>"

        class Holder(Component):
            citry = c
            template = "<div>{{ content }}</div>"

            def template_data(self, kwargs, slots):
                return {"content": kwargs["content"]}

        # Rendering an element mints per-render state (a fresh component id),
        # so the expression must stay dynamic even though its input is const.
        element = Inner()
        first = Holder(content=Const(element)).render().serialize()
        second = Holder(content=Const(element)).render().serialize()
        assert "inner" in first
        assert "inner" in second

        # Two entries: Inner's own body, and Holder's body for the const
        # signature. Holder's must have kept the expression dynamic.
        holder_bodies = [
            body
            for body in c._const_body_cache.values()
            if any(isinstance(item, ExprNode) for item in body)
        ]
        assert len(holder_bodies) == 1


class TestTemplateLiteralConst:
    """
    A literal attribute in a template is implicitly const: it is written in
    the template, so it cannot change between renders of that template.
    """

    def test_static_attr_is_const_in_the_child(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ age }}</p>"

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-Card age="30" />'

        assert Page().render().serialize() == '<p data-cid-c2="" data-cid-c1="">30</p>'
        card_bodies = [b for b in c._const_body_cache.values() if b == ["<p>30</p>"]]
        assert len(card_bodies) == 1

    def test_unquoted_static_attr_is_const(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ age }}</p>"

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = "<c-Card age=30 />"

        Page().render()
        assert ["<p>30</p>"] in c._const_body_cache.values()

    def test_boolean_attr_is_const_true(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ compact }}</p>"

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-Card compact="" />'

        Page().render()
        assert ["<p>True</p>"] in c._const_body_cache.values()

    def test_zero_variable_expression_attr_is_typed_const(self):
        # c-age="30" evaluates to the int 30 (not the string "30") and is a
        # template literal, so it is marked const and the child precomputes on it.
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="age > 18">adult</c-if><c-else>minor</c-else>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-Card c-age="30" />'

        assert Page().render().serialize() == "adult"
        assert ["adult"] in c._const_body_cache.values()

    def test_zero_variable_container_literal_unrolls_child_loop(self):
        c = Citry()

        class Items(Component):
            citry = c
            template = '<c-for each="i in items">[{{ i * mult }}]</c-for>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-Items c-items="[1, 2, 3]" c-mult="10" />'

        assert Page().render().serialize() == "[10][20][30]"
        assert ["[10][20][30]"] in c._const_body_cache.values()

        # Repeated renders hit the same signature: the per-render marker wraps
        # a fresh equal list, and the canonical key makes it the same entry.
        Page().render()
        Page().render()
        assert len(c._const_body_cache) == 2  # Page's body + Items' precomputed body

    def test_dynamic_expression_attr_is_not_marked(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ age }}</p>"

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-Card c-age="n" />'

            def template_data(self, kwargs, slots):
                return {"n": kwargs["n"]}

        assert Page(n=1).render().serialize() == '<p data-cid-c2="" data-cid-c1="">1</p>'
        assert Page(n=2).render().serialize() == '<p data-cid-c4="" data-cid-c3="">2</p>'
        # The child renders dynamic: one shared (empty-signature) entry whose
        # body keeps the expression node.
        card_bodies = [
            b for b in c._const_body_cache.values() if any(isinstance(item, ExprNode) for item in b)
        ]
        assert len(card_bodies) == 1


class TestExpressionConstPropagation:
    """
    An expression attribute whose variables are all const at render time
    produces a const result (``c-age="base + 1"`` when ``base`` is const), so
    the child reuses its pre-computed work for that input as well. A single
    non-const variable in the expression breaks it, exactly like a dynamic
    attribute.
    """

    def test_all_const_expression_attr_is_const_in_the_child(self):
        # base is const, so base + 1 (= 30) is const, so the child's c-if
        # precomputes on `age`. If propagation failed, `age` would be plain and the
        # IfNode would stay live.
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="age > 18">adult</c-if><c-else>minor</c-else>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-Card c-age="base + 1" />'

            def template_data(self, kwargs, slots):
                return {"base": Const(29)}

        assert Page().render().serialize() == "adult"
        assert ["adult"] in c._const_body_cache.values()

    def test_expression_mixing_const_and_dynamic_is_not_marked(self):
        # base is const but n is not, so base + n is not const: the child must
        # stay dynamic (one shared empty-signature entry keeping the IfNode).
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="age > 18">adult</c-if><c-else>minor</c-else>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-Card c-age="base + n" />'

            def template_data(self, kwargs, slots):
                return {"base": Const(29), "n": kwargs["n"]}

        assert Page(n=1).render().serialize() == "adult"
        assert Page(n=-100).render().serialize() == "minor"
        assert ["adult"] not in c._const_body_cache.values()
        live = [b for b in c._const_body_cache.values() if any(isinstance(item, IfNode) for item in b)]
        assert len(live) == 1

    def test_propagated_const_dedups_across_a_loop(self):
        # The win: a loop hands every child an all-const computed label, so all
        # the children share ONE precomputed cache entry (the loop var `i` is not in
        # the kwarg, so the kwarg is const every iteration and equal-valued).
        c = Citry()

        class Card(Component):
            citry = c
            template = "<span>{{ label }}</span>"

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        class Page(Component):
            citry = c
            template = '<c-for each="i in items"><c-Card c-label="prefix + \'!\'" /></c-for>'

            def template_data(self, kwargs, slots):
                return {"items": Const([1, 2, 3]), "prefix": Const("hi")}

        out = Page().render().serialize()
        assert out.count("<span") == 3
        assert "hi!" in out
        card_bodies = [b for b in c._const_body_cache.values() if b == ["<span>hi!</span>"]]
        assert len(card_bodies) == 1


class TestConstThroughTypedKwargs:
    def test_marker_survives_the_typed_kwargs_view(self):
        # The auto-converted dataclass Kwargs stores values as-is, so the
        # marker flows whether template_data reads the typed view or the raw
        # dict. (A typed-Kwargs implementation that copies or coerces values,
        # for example a user-supplied Pydantic model, may strip the marker;
        # the value then safely renders as dynamic.)
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ cols }}</p>"

            class Kwargs:
                cols: int

            def template_data(self, kwargs, slots):
                return {"cols": kwargs.cols}

        assert Card(cols=Const(3)).render().serialize() == '<p data-cid-c1="">3</p>'
        (body,) = c._const_body_cache.values()
        assert body == ["<p>3</p>"]

    def test_const_default_on_typed_kwargs_field(self):
        # A `Const(...)` default is the explicit way to mark a default value
        # constant: when the kwarg is omitted, the marked default flows
        # through template_data and precomputes; when it is passed, the live value
        # renders as usual (dynamic unless the caller marked it).
        c = Citry()

        class Card(Component):
            citry = c
            template = "<p>{{ cols }}</p>"

            class Kwargs:
                cols: int = Const(3)

            def template_data(self, kwargs, slots):
                return {"cols": kwargs.cols}

        assert Card().render().serialize() == '<p data-cid-c1="">3</p>'
        assert Card(cols=5).render().serialize() == '<p data-cid-c2="">5</p>'

        precomputed = [body for body in c._const_body_cache.values() if body == ["<p>3</p>"]]
        dynamic = [body for body in c._const_body_cache.values() if any(isinstance(i, ExprNode) for i in body)]
        assert len(precomputed) == 1
        assert len(dynamic) == 1


class TestConstPrecomputeInsideKeptNodes:
    def test_precomputes_inside_dynamic_if_branches(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="show">{{ label }}: {{ n }}</c-if><c-else>{{ label }} off</c-else>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        # `show` and `n` are dynamic, `label` is const: the IfNode stays, but
        # the const expression inside each branch precomputes to text.
        assert Card(show=True, label=Const("x"), n=7).render().serialize() == "x: 7"
        assert Card(show=False, label=Const("x"), n=7).render().serialize() == "x off"
        assert len(c._const_body_cache) == 1

        (body,) = c._const_body_cache.values()
        (node,) = body
        assert isinstance(node, IfNode)
        if_body = node.branches[0][2]
        assert if_body[0] == "x: "
        assert isinstance(if_body[1], ExprNode)
        else_body = node.branches[1][2]
        assert else_body == ["x off"]

    def test_const_if_nested_in_dynamic_branch_is_pruned(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="show"><c-if cond="big">L</c-if><c-else>S</c-else>{{ n }}</c-if>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        # The outer condition is dynamic; the inner one is const, so inside
        # the rebuilt outer branch the inner if is decided and inlined.
        assert Card(show=True, big=Const(True), n=1).render().serialize() == "L1"  # noqa: FBT003
        (body,) = c._const_body_cache.values()
        (node,) = body
        branch_body = node.branches[0][2]
        assert branch_body[0] == "L"
        assert isinstance(branch_body[1], ExprNode)

    def test_precomputes_inside_kept_for_body(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-for each="i in items">[{{ prefix }}{{ i }}]</c-for>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        # `items` is dynamic, so the loop stays; the const `prefix` inside the
        # body precomputes (it is the same on every iteration), while the loop
        # variable expression stays dynamic.
        assert Card(items=[1, 2], prefix=Const("p")).render().serialize() == "[p1][p2]"
        (body,) = c._const_body_cache.values()
        (node,) = body
        loop_body = node.branches[0][2]
        assert loop_body[0] == "[p"
        assert isinstance(loop_body[1], ExprNode)
        assert loop_body[1].used_vars == ("i",)
        assert loop_body[2] == "]"


class TestConstPrecomputeInsideSlotContent:
    """
    Precomputing descends into slot content: fill bodies, the implicit default
    slot body, and slot fallback bodies all render against the variables of
    the component whose template wrote them, so const expressions inside
    them precompute like any other.
    """

    def test_const_expr_in_fill_body_precomputes(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<div><c-slot name="title" /><c-slot name="body" /></div>'

        class Page(Component):
            citry = c
            template = (
                "<c-Card>"
                '<c-fill name="title">{{ heading }}!</c-fill>'
                '<c-fill name="body"><p>{{ greeting }}</p></c-fill>'
                "</c-Card>"
            )

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        out1 = Page(heading=Const("Dash"), greeting="hi").render().serialize()
        out2 = Page(heading=Const("Dash"), greeting="yo").render().serialize()
        assert "<p>hi</p>" in out1
        assert "<p>yo</p>" in out2
        assert "Dash!" in out1

        # In Page's cached body, the title fill precomputed to text while the
        # body fill kept its dynamic expression.
        (page_body,) = [b for b in c._const_body_cache.values() if not isinstance(b[0], str)]
        (component_node,) = page_body
        title_fill, body_fill = component_node.body
        assert title_fill.body == ["Dash!"]
        assert body_fill.body[0] == "<p>"
        assert isinstance(body_fill.body[1], ExprNode)

    def test_const_if_inside_fill_body_prunes(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="body" />'

        class Page(Component):
            citry = c
            template = '<c-Card><c-fill name="body">x<c-if cond="wide">WIDE</c-if></c-fill></c-Card>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        assert Page(wide=Const(True)).render().serialize() == "xWIDE"  # noqa: FBT003
        (page_body,) = [b for b in c._const_body_cache.values() if isinstance(b[0], ComponentNode)]
        (fill,) = page_body[0].body
        assert fill.body == ["xWIDE"]

    def test_fill_data_var_stays_dynamic(self):
        c = Citry()

        class Box(Component):
            citry = c
            template = '<c-slot name="s" c-x="1" />'

        class Page(Component):
            citry = c
            template = '<c-Box><c-fill name="s" data="d">{{ d["x"] }}-{{ k }}</c-fill></c-Box>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        # The fill's own `d` variable is per-invocation slot data, so the
        # expression using it stays live; the const `k` precomputes and merges.
        assert Page(k=Const("K")).render().serialize() == "1-K"
        (page_body,) = [b for b in c._const_body_cache.values() if isinstance(b[0], ComponentNode)]
        (fill,) = page_body[0].body
        assert isinstance(fill.body[0], ExprNode)
        assert fill.body[0].used_vars == ("d",)
        assert fill.body[1] == "-K"

    def test_default_slot_body_precomputes(self):
        c = Citry()

        class Box(Component):
            citry = c
            template = '<b><c-slot name="default" /></b>'

        class Page(Component):
            citry = c
            template = "<c-Box>{{ k }}</c-Box>"

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        assert Page(k=Const("K")).render().serialize() == '<b data-cid-c2="" data-cid-c1="">K</b>'
        (page_body,) = [b for b in c._const_body_cache.values() if not isinstance(b[0], str)]
        assert page_body[0].body == ["K"]

    def test_slot_fallback_body_precomputes(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-slot name="title">{{ label }}</c-slot>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        # Unfilled: the fallback renders, and with `label` const its
        # expression precomputed inside the kept SlotNode.
        assert Card(label=Const("untitled")).render().serialize() == "untitled"
        (body,) = c._const_body_cache.values()
        (slot_node,) = body
        assert isinstance(slot_node, SlotNode)
        assert slot_node.body == ["untitled"]

        # Filled: the fill wins over the precomputed fallback, same as ever.
        assert Card(label=Const("untitled"), slots={"title": "Hello"}).render().serialize() == "Hello"


class TestConstPrecomputeUnroll:
    def test_const_loop_unrolls_to_text(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<ul><c-for each="i in items">{{ i }},</c-for></ul>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        assert Card(items=Const([1, 2, 3])).render().serialize() == '<ul data-cid-c1="">1,2,3,</ul>'
        (body,) = c._const_body_cache.values()
        assert body == ["<ul>1,2,3,</ul>"]

    def test_unroll_precomputes_ifs_and_uses_empty_branch(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-for each="i in items"><c-if cond="i > 1">{{ i }}!</c-if></c-for><c-empty>none</c-empty>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        assert Card(items=Const([1, 2, 3])).render().serialize() == "2!3!"
        assert Card(items=Const([])).render().serialize() == "none"
        bodies = c._const_body_cache.values()
        assert sorted(map(tuple, bodies)) == [("2!3!",), ("none",)]

    def test_unroll_backs_out_past_the_iteration_cap(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-for each="i in items">.</c-for>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        n = _MAX_UNROLL_ITERATIONS + 1
        out = Card(items=Const(range(n))).render().serialize()
        assert out == "." * n
        (body,) = c._const_body_cache.values()
        (node,) = body
        assert not isinstance(node, str)  # the loop stayed dynamic

    def test_unroll_backs_out_on_element_value(self):
        c = Citry()

        class Inner(Component):
            citry = c
            template = "<i>x</i>"

        class Card(Component):
            citry = c
            template = '<c-for each="i in items">{{ i }}</c-for>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        # The loop body is statically precomputable, but the value is an element,
        # which must render fresh per render: the unroll backs out and the
        # loop stays dynamic.
        element = Inner()
        first = Card(items=Const([element])).render().serialize()
        second = Card(items=Const([element])).render().serialize()
        assert "<i" in first
        assert "<i" in second
        card_body = next(b for b in c._const_body_cache.values() if b and not isinstance(b[0], str))
        assert len(card_body) == 1

    def test_dynamic_loop_does_not_unroll(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-for each="i in items">{{ i }}</c-for>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        assert Card(items=[1, 2]).render().serialize() == "12"
        (body,) = c._const_body_cache.values()
        assert not isinstance(body[0], str)


class TestConstPrecomputeErrors:
    def test_failing_const_expr_stays_dynamic_and_raises_at_render(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<p>{{ cfg["missing"] }}</p>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        # Precomputing must not raise: the failing expression stays a dynamic node
        # and the error surfaces through the normal render path, every render.
        with pytest.raises(KeyError):
            Card(cfg=Const({"a": 1})).render().serialize()
        (body,) = c._const_body_cache.values()
        assert any(isinstance(item, ExprNode) for item in body)
        with pytest.raises(KeyError):
            Card(cfg=Const({"a": 1})).render().serialize()

    def test_failing_const_cond_keeps_the_if_dynamic(self):
        c = Citry()

        class Card(Component):
            citry = c
            template = '<c-if cond="cfg[\'missing\']">a</c-if>'

            def template_data(self, kwargs, slots):
                return dict(kwargs)

        with pytest.raises(KeyError):
            Card(cfg=Const({"a": 1})).render().serialize()
        (body,) = c._const_body_cache.values()
        (node,) = body
        assert isinstance(node, IfNode)


class TestConstBodyCache:
    def test_builds_once_per_key(self):
        cache = ConstBodyCache()
        calls = []

        def build():
            calls.append(1)
            return ["body"]

        assert cache.get_or_build(int, frozenset(), build) == ["body"]
        assert cache.get_or_build(int, frozenset(), build) == ["body"]
        assert len(calls) == 1

    def test_distinct_keys_build_separately(self):
        cache = ConstBodyCache()
        cache.get_or_build(int, frozenset(), lambda: ["a"])
        assert cache.get_or_build(int, frozenset({("x", 1)}), lambda: ["b"]) == ["b"]
        assert cache.get_or_build(str, frozenset(), lambda: ["c"]) == ["c"]
        assert len(cache) == 3

    def test_lru_evicts_oldest(self):
        cache = ConstBodyCache(max_entries=2)
        cache.get_or_build(int, frozenset({("x", 1)}), lambda: ["a"])
        cache.get_or_build(int, frozenset({("x", 2)}), lambda: ["b"])
        cache.get_or_build(int, frozenset({("x", 3)}), lambda: ["c"])
        assert len(cache) == 2
        # The oldest entry ("a") was evicted, so it rebuilds.
        rebuilt = []
        cache.get_or_build(int, frozenset({("x", 1)}), lambda: rebuilt.append(1) or ["a"])
        assert rebuilt == [1]

    def test_hit_refreshes_recency(self):
        cache = ConstBodyCache(max_entries=2)
        cache.get_or_build(int, frozenset({("x", 1)}), lambda: ["a"])
        cache.get_or_build(int, frozenset({("x", 2)}), lambda: ["b"])
        # Touch "a" so "b" is now the least recently used.
        cache.get_or_build(int, frozenset({("x", 1)}), lambda: ["a2"])
        cache.get_or_build(int, frozenset({("x", 3)}), lambda: ["c"])
        # "a" survived the eviction; "b" did not.
        survived = []
        cache.get_or_build(int, frozenset({("x", 1)}), lambda: survived.append(1) or ["a3"])
        assert survived == []

    def test_failed_build_caches_nothing(self):
        cache = ConstBodyCache()

        def boom():
            msg = "build failed"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="build failed"):
            cache.get_or_build(int, frozenset(), boom)
        assert len(cache) == 0
        # The next attempt retries and can succeed.
        assert cache.get_or_build(int, frozenset(), lambda: ["ok"]) == ["ok"]

    def test_evict_component(self):
        cache = ConstBodyCache()
        cache.get_or_build(int, frozenset(), lambda: ["a"])
        cache.get_or_build(int, frozenset({("x", 1)}), lambda: ["b"])
        cache.get_or_build(str, frozenset(), lambda: ["c"])
        cache.evict_component(int)
        assert len(cache) == 1

    def test_clear(self):
        cache = ConstBodyCache()
        cache.get_or_build(int, frozenset(), lambda: ["a"])
        cache.clear()
        assert len(cache) == 0
