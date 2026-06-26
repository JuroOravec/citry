# Design: const-ness and render-body caching

**Status (2026-06-11): phases 1 and 2 built; taint parked.** In plain terms,
the feature is: mark a component input as "this never changes between
renders" (`Const(value)`), and the engine computes the parts of the template
that depend only on such inputs once, caches the result, and reuses it on
every later render with the same values. That pre-computing step is called
**precomputing** throughout this doc and the code.

What exists (all in `citry/constness.py`):

- The `Const` marker: a transparent wrapper that behaves exactly like the
  value inside, detected on the `template_data` output, and carried into
  child components so they get the optimization too.
- The cache key (`freeze_const` / `extract_const_vars`): built from the
  const variables' names and values, value-based (equal values share an
  entry; computed once per marker and remembered). A value that cannot be
  keyed safely is simply treated as not const. Only variables the template
  actually uses go into the key.
- The cache (`ConstBodyCache`): one pre-computed template per component
  class per combination of const values, scoped to the `Citry` instance,
  capped in size (the least recently used entry drops first), guarded by a
  lock.
- Precomputing itself (`precompute_const_parts`): const expressions become escaped text; a
  const `<c-if>` keeps only its winning branch; an `<c-if>`/`<c-for>` that
  must stay still gets its insides precomputed; an all-const `<c-for>` runs once
  and its text is baked in (capped); slot content precomputes inside (fill bodies,
  default-slot bodies, slot fallbacks render against the writer's variables,
  so const expressions in them precompute even though the slot machinery itself
  stays per-render); neighboring static strings join. Precomputing never raises:
  anything that fails just stays un-optimized and errors (if any) surface at
  render, as they would have anyway.
- Values written literally in the template (`age="30"`, `c-age="30"`) are
  marked const automatically when they become a component input.
- Ergonomics: `Const(x)` has `x`'s type for type checkers;
  `cols: int = Const(3)` on a typed `Kwargs` makes a default const; Pydantic
  `Kwargs`/`Slots` models work, but their validation strips the marker (the
  value then safely renders without the optimization).

Sections 3-5 and 7-9 describe what is built; measured results are in
section 13. What is NOT built: precomputing across the slot boundary (a constant
fill precomputing the child's `<c-slot>` away) was designed, falsified, and
parked, see section 14; the component-boundary placeholder (section 5.1)
stays parked (low value for now, the child takes its own cache hit since
the marker flows down); phase-2 taint (section 4.1) stays parked.

This document captures the design for the `Const()` optimization and the
render-body caching it enables. It records the reasoning and the (many) edge
cases.

For the broader migration context see
[`citry_migration.md`](citry_migration.md). For operating rules see
[`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: django-components
[#1083](https://github.com/django-components/django-components/issues/1083)
(`Const()` / ~50% perf), 
[#1473](https://github.com/django-components/django-components/issues/1473)
(expression caching),
[#1650](https://github.com/django-components/django-components/issues/1650)
(cache the render object, not the string),
[#1326](https://github.com/django-components/django-components/issues/1326)
(avoid double-parsing). The variable-provenance notes in
[`TODO/v2_TODO.md`](../../TODO/v2_TODO.md) (the "Expression caching" section)
are closely related.

---

## 1. Goal

Let a template author mark inputs as constant across renders:

```python
MyCard(title="hi", cols=Const(3))
```

`Const(x)` is a promise: "this input does not change between renders of this
usage." The engine uses that promise to do work once instead of on every
render. Concretely, any part of the template whose value depends only on
const inputs is computed on the first render, precomputed into the body, and reused
on later renders. The non-const parts are re-evaluated every render as usual.

From the user's side nothing changes: they call `MyCard(title=Const("hi"))`
every render. Behind the scenes the engine recognizes a previously-seen const
signature and reuses the optimized body.

This is the Citry form of django-components #1083.

---

## 2. Mental model

- Composition (`MyCard(...)`) produces an element describing what to render.
- Some inputs are marked `Const`; the rest are dynamic.
- The optimized body for a given const signature is built once and cached.
- On every render, the dynamic inputs are applied fresh; the const parts are
  already precomputed.

The cache is a memoization keyed by "which inputs are const, and to what
values," scoped so it can be cleared and bounded.

---

## 3. Architecture

### 3.1 Layering

Three layers, from most-shared to least:

1. **Class: the body-generating function.** Parsing + compiling + exec of the
   template, cached once per component class (this exists today, see
   `_get_compiled_template` in
   [`packages/py/citry/citry/component_render.py`](../../packages/py/citry/citry/component_render.py)).
   Calling it yields a fresh, unoptimized node list.
2. **Const cache: the optimized body.** Keyed by `(component class, const
   signature)`. The value is a specialized node list where all-const nodes
   have been precomputed and dead control-flow branches pruned. Scoped to the
   `Citry` instance and bounded (see 7.2).
3. **Per render: dynamic evaluation.** The non-const nodes in the optimized
   body evaluate against the live context each render.

### 3.2 What gets cached: the optimized body, not the element

The `CitryElement` also carries the per-call inputs. Two calls
with the same const signature but different dynamic inputs, for example
`MyCard(title="hi", cols=Const(3))` then `MyCard(title="bye", cols=Const(3))`,
must not share an element, or the stored `title` would be wrong for the second
call. What is genuinely invariant across those two calls is the **optimized
node list**, so that is what the cache stores. Each call still mints a cheap
element carrying that call's inputs plus a reference to the shared optimized
body.

### 3.3 Where the lookup happens

At render time, inside `render_impl` (not at composition). When resolving the
template to render, the engine determines which context values are const,
builds the const signature, and fetches (or builds and caches) the optimized
body. The body therefore lives in the const cache, keyed by signature, not on
the element. (Today `render_impl` just calls the class-level generator each
render; there is no per-element or per-signature body cache yet.)

### 3.4 First render vs cache hit

- **First render (cache miss):** start from the unoptimized node list (layer
  1). For each node, if all of the node's used variables are const in scope,
  evaluate it and replace it in the list with its result (text or a child
  element, see section 5). Prune dead branches. Store the specialized list in
  the const cache.
- **Cache hit:** render the already-precomputed list directly; do not re-precompute.

---

## 4. The `template_data` boundary (the crux)

This is the part that decides whether partial-const precomputing is sound.

The body does not consume kwargs; it consumes the **template variables**
returned by `template_data(kwargs, slots)`. Citry's base `template_data`
returns nothing, so template variables always come from an explicit, opaque
Python function of the inputs. Therefore "const kwarg" does not imply "const
template variable":

```python
def template_data(self, kwargs, slots):
    return {"label": fetch_from_db(kwargs.title)}   # title const, label NOT const
```

To precompute a node you must know its used template variables are const, which
means relating const kwargs to const template variables through
`template_data`. There is no general static answer (it is arbitrary Python).

The resolution is to **observe** const-ness on the `template_data` output, not
to assume it from the kwargs. The `Const` marker is set at compose and **flows
down** the component tree (it is not unwrapped at the boundary): the kwargs
stay marked inside the component, `template_data` uses them normally, and at
render time the engine inspects the `template_data` output to see which context
variables are still const. So `MyCard(title=Const("hi"))` works because the
marker on `title` survives into the context, not because the engine assumes a
wiring from kwarg to variable. (An earlier draft proposed assuming pass-through
and keying on kwargs; that is rejected. The interface that matters is the
`template_data` output.)

### 4.1 Carrying the marker: implementation and phases

For the marker to flow, a value must carry "I am const" while still behaving
like its underlying value, so user code can compare it, add to it, call its
methods, and so on. Two mechanisms are plausible:

- **Wrapper / transparent proxy (option a).** A class that wraps the value,
  forwards every operation to it, and carries a const flag. Works for
  everything, including scalars.
- **Dunder-attribute tag (option b).** Set a flag in place (for example
  `obj.__citry_const__ = True`) without wrapping. Only usable in a hybrid:
  wrapper for scalars and immutables, tag for mutable objects (since scalars
  and immutables have no writable `__dict__` to tag).

**Decision: use the proxy alone (a), not the wrapper-plus-tag hybrid (b).**
The hybrid was tested empirically (CPython 3.13) and fails on three counts:

- **Tagging does not work for the common mutable types.** Setting an attribute
  raises `AttributeError` on every builtin container (`list`, `dict`, `set`,
  `bytearray`) and on any `__slots__` class without a declared slot for the
  flag. Only a plain custom object (one with a `__dict__`) is taggable. So the
  "tag mutables" branch does not actually cover mutables: lists, dicts, and
  sets would still need the wrapper. The hybrid does not reduce wrapping where
  it matters, it just adds a second mechanism for a narrow case.
- **A tag is object-scoped, not usage-scoped.** Const is a per-usage promise,
  but a flag set on an object marks it const for every other reference to that
  same object, and it mutates the user's object (the flag shows up in
  `__dict__`, `vars()`, serialization, repr). The wrapper is correctly
  per-usage: it wraps at the call site and leaves the underlying object
  untouched.
- **A tag cannot carry phase-2 taint.** Any operation yields a new, untagged
  object, so a tag cannot propagate through expressions. The proxy can, by
  intercepting operations, so it is the natural home for taint anyway.

The proxy's known weakness, transparency leaks, is manageable:

- Special (dunder) methods resolve on the type, not the instance, so a
  `__getattr__`-only proxy does not forward `len()`, `[]`, `iter()`, `+`, and
  so on (all confirmed to raise `TypeError`). A full proxy must define them all
  explicitly. **Decision: `Const` subclasses `wrapt.ObjectProxy`**, which
  already defines the full dunder set and forwards `__class__` (see below).
  This adds `wrapt` as a runtime dependency of the `citry` package. Do not
  hand-roll the proxy.
- `isinstance` is rescued by forwarding `__class__`: with that,
  `isinstance(proxy, str)` returns `True` (the kind of check user code in
  `template_data` is likely to do). wrapt forwards `__class__`.
- The accepted residual leaks are `type(x)` (returns the proxy class, since
  `type()` ignores `__class__`) and identity (`x is original` is `False`).
  Const values should not be identity-compared, and `type()` is rarely relied
  on where `isinstance` would do, so these are acceptable. The remaining cost
  is a small per-value wrapping overhead, paid only for const values, which are
  by definition few and stable.

**Object identity (`id()`) was considered and rejected outright.** An id-keyed
side-table is unsound: CPython reuses an `id()` (the memory address) after the
object is collected, so a stale id matches an unrelated new object; pinning
objects to avoid that leaks. It also cannot mark scalars (interned singletons
share one id; equal-but-distinct values have different ids) and cannot carry
taint (a new object has a new id). It is not used.

The proxy splits into two phases of very different difficulty:

- **Phase 1 (achievable early): wrap, pass down, detect.** Values can be
  wrapped at compose, passed down the tree, and detected as const. A value
  passed through unchanged (`template_data` returns `kwargs.title` directly)
  stays const; a value that is transformed loses the marker. This alone
  enables precomputing for the common pass-through case, and can land long before
  phase 2.
- **Phase 2 (hard): taint propagation.** `Const("title").upper()` should stay
  `Const(str)`: an operation over const operands yields a const result, while
  mixing const and non-const yields non-const. This requires intercepting
  operations (the proxy route) or otherwise propagating the flag through
  arbitrary Python expressions, and is the genuinely hard part. It is what lets
  a transforming `template_data` still produce detectably-const variables.

Phase 2 is more powerful and more dangerous (identity, `isinstance`, hashing,
and C-level operations are all sharp edges). Phase 1 is the early, useful
foothold.

A narrow, static slice of Phase 2 shipped later, without the general taint
machinery: **expression propagation** at the kwarg boundary (section 15.3) marks
an expression's result `Const` when every variable it reads is already `Const`.
The fuller forms (a `Computed` value, deep const for nested literals) were explored
and parked; see section 15.

### 4.2 The "all const" criterion is really "uses only const vars"

A natural first cut is "if all inputs are const, the whole output is static."
That criterion does not survive a planned feature: a special `self` template
variable that points at the current component instance. With `self` available,
no render is ever literally "all inputs const."

The correct criterion is therefore **"the template (or a node) uses only const
variables,"** evaluated per node against the variables that node actually uses,
not "all inputs are const." A node that touches `self` (or any non-const var)
is not precomputable; a node that touches only const vars is.

---

## 5. The precomputed body is heterogeneous

Precomputing does not collapse a subtree to a single string. A precomputed body is a
list whose items are one of:

- `str`: static text, passes through unchanged.
- a **child placeholder** (see section 6): a recipe that, each render, produces a
  child `CitryRender` (with a fresh render id and re-merged deps) from a nested
  component node whose inputs are const.
- a dynamic node: a non-const node that re-evaluates against the live context
  each render.

### 5.1 Why a component boundary cannot precompute to text

A nested `<c-Inner>` with const inputs still cannot become frozen text,
because every time the outer component renders:

- `Inner` must mint a **fresh render ID** (the same element rendered twice
  yields two identities, per #1650), and
- `Inner`'s JS/CSS must be (re)registered for this render.

So precomputing a component boundary yields a placeholder that has done the expensive
work once (parse, compile, precompute of `Inner`'s body) but still re-emits cheaply
with a fresh ID and re-merges assets on each render. The per-render output of
that placeholder is a `CitryRender` (see section 6).

---

## 6. The composition and render structs

Two distinct structs sit on either side of `.render()` (full design in
[`rendering.md`](rendering.md)):

- **`CitryElement`** (inspired by React's `ReactElement`) is what calling a
  component produces: the description of a component invocation (class plus
  kwargs/slots). `Component()` returns a `CitryElement`.
- **`CitryRender`** is what `.render()` produces: the render-phase output
  carrying the rendered parts plus collected metadata (JS/CSS deps).
  `CitryRender.serialize()` produces the HTML string.

The precomputed placeholders of section 5 are recipes that produce a child
`CitryRender` each render (fresh id, re-merged deps), which is why a component
boundary cannot precompute to frozen text.

---

## 7. Cache key and lifetime

### 7.1 Key construction

The key is built from the **`template_data` output** (the context variables
that are still const after the marker has flowed through, see section 4), not
from the raw kwargs.

Key = `(component class identity, frozenset of (const context variable name,
const value))`. Order-independent (frozenset). The const VALUES participate, so
differing const values miss; the const VARIABLE SET participates, so a
different set of const variables misses. Dynamic variables do not participate
(they are re-rendered each call), which is correct because foldability depends
only on which variables are const, not on the dynamic ones.

### 7.2 Hashing strategy

Const values must produce a stable key.

- If the value is hashable, hash it.
- If it is not hashable (common Python structures like `list` and `dict`),
  fall back to a canonical serialization rather than blocking the user.

Caveats to design carefully (do not just call `repr`):

- `repr` of an arbitrary object includes its `id()` (memory address), which is
  unstable across instances and runs, so the cache would never hit and would
  grow without bound. A canonical serialization must be value-based.
- Sets and other unordered containers need a canonical ordering.
- Two distinct values must not serialize to the same key.

A reasonable rule: hashable then hash; else a value-based canonical form for
plain data containers; else treat as non-const (refuse to precompute) rather than
risk a wrong or unstable key.

### 7.3 Bounding and scoping

The cache is unbounded by default and will leak if const values are
high-cardinality. It must be a bounded LRU scoped to the `Citry` instance and
cleared by `Citry.clear()`, consistent with why the `Citry` instance exists
(all transient state bound to a lifetime, no module globals).

`Const(user.id)` and similar high-cardinality "const per render" values are an
**anti-pattern**. Document this as guidance: `Const` is for values that are
stable across many renders (layout constants, fixed labels), not for values
that are merely fixed within a single render.

---

## 8. Constness analysis

Foldability is per node and per scope.

- A node is precomputable iff **all** of its used variables are const in the node's
  scope. One non-const variable poisons the node.
- **Scope and shadowing:** `<c-for each="x in items">` introduces `x`; inside
  the loop `x` is not const even if an outer variable of the same name is.
  `<c-fill>` introduces its data/default variables similarly. Use the AST's
  `used_variables` and `introduced_variables` to mask correctly.
- **Control-flow pruning:** `<c-if cond="cols > 2">` with `cols` const can be
  evaluated at precompute time and the dead branch dropped (a large part of the
  win). With `cols` non-const, keep both branches.

The inputs to this analysis (`used_variables`, `introduced_variables`) are
already tracked in the AST.

---

## 9. Invariants

- **Per-render state is never precomputed.** The render ID, component id, and any
  scoped CSS/JS hashes derived from it must be injected fresh on every render,
  never baked into the cached body. This is the same reason #1650 caches the
  element rather than the string.
- **`Const` is a user promise, not verified.** If a user marks a value const
  and then mutates it, output goes stale. That is acceptable and must be
  documented.
- **Precomputing assumes pure, deterministic expressions.** Citry expressions are
  sandboxed by default (see `safe_eval`), which mostly guarantees this, but
  precomputing does change when a const expression is evaluated (once, at first
  render). (Turning the sandbox off does not change this assumption: a template
  expression is still expected to be a pure function of its inputs.)

---

## 10. Interactions and non-goals

- **Expression caching (#1473) is a separate concern.** That is a per-value
  memo of expression results while inputs are unchanged. It is unrelated to
  const precomputing and must not be entangled with it. In particular, because
  precomputed bodies are shared across elements with the same const signature but
  different dynamic inputs, the non-const nodes in a shared body must be
  stateless re-evaluators; any expression cache is a separate, value-keyed
  layer that only applies to truly-unshared nodes.
- **Slot content precomputes inside; the slot boundary stays dynamic.** Precomputing
  descends into fill bodies, the implicit default-slot body, and slot
  fallback bodies: they render against the variables of the component whose
  template wrote them, so const expressions inside them are pre-computed
  like any other. The slot boundary itself (which fill a `<c-slot>` renders,
  the per-render fill collection) is per-render state and is excluded from
  the cache key. Crossing that boundary, so that a constant fill precomputes the
  child's `<c-slot>` away entirely, was designed, checked, and parked: see
  section 14 for the design and the reasons it lost.
- **Template literals are implicitly const (built).** A static attribute
  (`age="30"`, unquoted `age=30`, boolean `compact=""`) and a zero-variable
  expression attribute (`c-age="30"`, `c-items="[1, 2]"`) are written in the
  template, so they cannot change between renders: `ComponentNode` marks them
  `Const` when building the child's kwargs. The marking happens at the
  component-input boundary only (the level where const-ness is consumed, see
  section 11), so values that become engine identifiers elsewhere (slot and
  fill names, provide keys) stay plain. This gives every static component
  usage body-cache precomputing with no opt-in, and it composes: a const container
  literal can unroll a `<c-for>` in the child. Because these markers are
  engine-injected, the proxy's `repr` forwards to the wrapped value, so a
  marked value inside a container reprs identically to the plain one.
- **Validating Kwargs models strip the marker (safe).** A Pydantic `Kwargs`
  model accepts a `Const`-marked input, but validation produces a new
  (coerced) value, so the typed view holds a plain value and it renders as
  dynamic. To keep const-ness with a validating model, read the marked value
  from `raw_kwargs`. The auto-converted dataclass `Kwargs` stores values
  as-is, so it preserves the marker.
- **Defaults are const by explicit marking (resolved).** Auto-marking
  defaults was rejected: defaults can be **dynamic** (a `default_factory` may
  produce a fresh value each call, for example a random uuid), and the engine
  cannot tell a pure factory from `uuid4`, so a blanket rule would be
  unsound. Instead a default is made const the same way any value is, by
  marking it: `cols: int = Const(3)` on the typed `Kwargs`. The dataclass
  stores the marker as-is, so an omitted kwarg flows the marked default
  through `template_data` and precomputes, while a passed kwarg renders with the
  caller's (marked or unmarked) value.
- **Typing ergonomics (resolved).** `title=Const("hi")` type-checks against
  `title: str`: to checkers, `Const` is `def Const(x: T) -> T` (transparent
  to the checker, wraps at runtime). Annotating the class itself does not
  work, because wrapt ships no stubs (so the proxy base is `Any` to checkers)
  and mypy does not honor a `__new__` returning a bare TypeVar.
  `is_const`/`const_value` are the sanctioned detection points.
- **Thread-safety.** The shared cache is read and written during render;
  concurrent renders need a lock or a concurrent map. First-render precomputing
  under a lock.
- **Hot reload / invalidation.** If a template changes (hot reload) the cached
  optimized bodies are stale. Invalidate on class redefinition and on
  `Citry.clear()`.

---

## 11. Open questions and edge cases

- Recursive / self-referential components: a component that renders itself
  could recurse through the const cache; needs cycle handling.
- Nested `Const` does not make its container const. `items=[Const(1), x]` means
  `items` itself MAY change (it contains a non-const `x`), so `items` is not
  const and is not optimized out at the parent or at a `<c-for>` over it.
  However, the inner `Const(1)` is still meaningful deeper down: if that element
  is passed to an inner component (`<c-inner value=Const(1)>` inside the loop),
  the **inner** component can take a cache hit on `value`. So const-ness is
  consumed at the level where a value becomes a component input, not at the
  container level.
- Precompute-time errors: if a const node raises while precomputing, does the error
  surface at compose or at render? Prefer render semantics.
- How does `Const` survive (or not) through `template_data`? Phase 1 carries it
  only through pass-through; phase 2 (taint) carries it through transforms (see
  section 4.1).
- How does the special `self` variable interact with foldability of nodes that
  reference it (always non-const, see 4.2)?
- Interaction with extensions/hooks that may inject context.

---

## 12. Suggested phasing

1. **Phase 1 marker (section 4.1):** a `Const` transparent proxy (a
   `wrapt.ObjectProxy` subclass) that carries the flag, behaves like the
   wrapped value, and flows down the tree (not unwrapped at the boundary). At
   render, read the const-marked variables off the `template_data` output. This
   already covers pass-through const variables.
2. The const-keyed, `Citry`-scoped, bounded body cache, keyed on the const
   context variables and values (sections 3, 7).
3. A `precompute(body, const_vars, scope)` pass over the existing node list using
   `used_variables` / `introduced_variables`, with `c-if` branch pruning
   (section 8), producing the heterogeneous body of section 5.
4. The child-element struct (a `CitryElement`) that re-emits with a fresh
   render ID and re-registers JS/CSS (sections 5, 6).
5. Typing ergonomics, constant-default detection, invalidation, thread-safety.
6. **Phase 2 taint (section 4.1):** propagate the const flag through operations,
   so a transforming `template_data` still yields detectably-const variables.

Defer phase 2 taint and slot const-ness until the phase 1 pieces are in place
and measured.

---

## 13. Measured results (2026-06-10, slot row 2026-06-11)

Measured on an M-series Mac, CPython 3.13, **release** build of the Rust
extension (`maturin develop --release`; the default debug build skews any
benchmark that touches `transform_html` by ~12x). Each case compares the
same component called with `Const(...)`-marked inputs vs plain inputs, after
warmup (cache hits, not first-render precomputing). The scenarios are
reproducible:

```bash
.venv/bin/python packages/py/citry/tests/benchmark_const.py            # the table below
.venv/bin/python packages/py/citry/tests/benchmark_const.py --profile  # plus the section 14.5 breakdown
```

| Template | Render only | Render + serialize |
|---|---|---|
| Expression-heavy (35 const exprs, 5 const ifs, 1 dynamic expr) | **2.38x** (27.5 -> 11.6 us) | **1.98x** (36.1 -> 18.3 us) |
| Small card (4 const exprs, 1 const if, 1 dynamic expr) | **1.48x** (8.7 -> 5.9 us) | **1.37x** (11.6 -> 8.5 us) |
| Nav with const 20-link loop, precompute v2 unroll (1 dynamic expr) | - | **2.83x** (44.1 -> 15.5 us) |
| Slot-heavy layout (layout + card, 4 slot sites, const fills precomputing inside) | **1.56x** (47.5 -> 30.5 us) | **1.64x** (68.8 -> 42.0 us) |

The render-phase number matches the ~50% upstream claim (django-components
#1083). Two findings from profiling:

- Per-render signature freezing grows with the number of const variables; the
  frozen key is therefore memoized on the `Const` proxy itself (sound because
  `Const` is a promise the value does not change). Without the memo, 35
  markers ate roughly half the precomputing win.
- After precomputing, serialization (the marker pass) was the largest single
  remaining cost, ~37% of end-to-end; addressed in
  [#7](https://github.com/JuroOravec/citry/issues/7) by `mark_html`, a
  single-pass root scan in `citry_html_transform`.

---

## 14. Const slots: precomputing across the slot boundary (considered, parked)

**Verdict (2026-06-11): parked.** The falsifier checks in 14.5 were carried
out and the design lost on all three counts; the measured results are
recorded there. The deciding argument is behavioral, not just numbers:
precomputing away `<c-slot>` tags makes core slot machinery (fill invocation,
the `on_slot_rendered` hook) conditional on an optimization, and an
extension implementing that hook (likely, possibly a built-in) would
disable the feature wholesale anyway. What slot-heavy pages actually
needed, precomputing INSIDE slot content, is built and unaffected (14.1).
The design below is kept as the record of what was considered and why it
was rejected.

Real pages are slot-heavy: a layout component exposes sidebar and main
slots, the main slot holds a card with title and body slots, the body holds
a button with a content slot. If the optimization stops at slot boundaries,
it misses most of such a page. This section designs the crossing.

### 14.1 What is already built

Precomputing descends INTO slot content (fill bodies, the implicit default-slot
body, slot fallback bodies), because that content renders against the
variables of the component whose template wrote it, and those are fixed per
cache entry. So a fill like `<c-fill name="title">{{ heading }}</c-fill>`
with `heading` const already precomputes to plain text inside the parent's cached
body. What does NOT yet happen: the child component still renders its
`<c-slot name="title">` dynamically on every render, looking up and
invoking the fill, even though the fill's output is a fixed string.

### 14.2 The key insight: a const slot is a fill that precomputed to pure text

There is no need for separate "is this slot const" reasoning (tracking the
fill's used variables, for example): after the parent's body is precomputed, a
constant fill is simply one whose body list contains nothing but strings.
That test is more precise than any static analysis (it benefits from
`<c-if>` pruning inside the fill) and the constant VALUE (the text) falls
out for free. A fill containing a nested component can never be const: the
child mints fresh render ids every render.

### 14.3 Design

1. **Detect at fill collection.** When `ComponentNode` collects fills, a
   fill whose (already-precomputed) body is all strings produces a `Slot` tagged
   with its constant text (e.g. a `const_text: str | None` field). The same
   tag applies to plain-string fills from the Python API
   (`slots={"title": "Hello"}`): a string fill is inherently constant, the
   slot counterpart of the template-literal rule of section 10.
2. **Let const slots into the child's cache key.** `_CompiledTemplate`
   additionally captures the template's statically declared slot names (the
   parsed AST already exposes `Template.slots`). The child's key then
   records, for each declared slot: the constant text when the fill is
   const, an explicit ABSENT marker when no fill was given, and NOTHING when
   the fill is dynamic.
3. **Why absent and dynamic must be distinct keys.** Precomputing the fallback
   body into place is only sound for renders that have NO fill for that
   slot. If "absent" and "dynamic fill" shared a cache entry, a render that
   passes a dynamic fill would be served the baked fallback. With distinct
   keys, the ABSENT entry can inline the (already precomputed) fallback, and
   dynamic-fill renders keep a live `<c-slot>`.
4. **Precompute the child's `<c-slot>`.** During the child's precompute, a slot node
   whose name is static and maps to a const-text entry is replaced by that
   text; one that maps to ABSENT is replaced by its precomputed fallback body.
   Slots with dynamic names (`c-name`) never precompute.
5. **Hook gate.** `on_slot_rendered` fires once per slot render today;
   precomputing the slot away would skip it. Only precompute slot nodes when no
   registered extension implements `on_slot_rendered` (the extension
   manager knows). This keeps the extension contract intact at the cost of
   the optimization, which is the right default.

In the layout scenario this bakes: the card's title ("Dashboard"), a pure
static sidebar nav, a button whose content slot is plain text (the button's
whole body becomes static). What stays live, correctly: any fill containing
a component or a dynamic expression, and all per-render component machinery
(instances, fill collection, the render queue, serialization), which is the
component-boundary placeholder's territory (section 5.1, still parked).

### 14.4 Alternatives considered

- **Expose `used_vars` on `Slot` and reason from them.** Subsumed by 14.2:
  template fills already carry parser-computed used variables internally,
  but "try precomputing and check the result" is strictly more precise, and for
  Python-API slots there is no template scope for `used_vars` to refer to.
- **A generic `Const(slot)` wrapper as the user API.** Works as a promise
  for values whose output can be keyed (strings, which are auto-marked
  instead), but an arbitrary slot function's output cannot become a stable
  cache key without calling it, and function objects are typically
  recreated per render, so identity keying would never hit (the same
  reasoning that rejected `id()` keys in section 4.1). A
  const-promised slot *function* API is deferred until someone needs it.
- **Keying the child's cache on `Slot` object identity.** Rejected: fill
  collection builds fresh `Slot` closures every render, so identity is
  never stable.

### 14.5 The falsifier checks (carried out 2026-06-11; all three fired)

- **Fill-collection cost dominates.** Checked by profiling a representative
  layout page (layout + card, four slot sites, const sidebar links and
  title, dynamic body; reproducible with
  `packages/py/citry/tests/benchmark_const.py --profile`).
  `SlotNode` rendering was 32.7% of render time, but
  only two of the four slots would precompute, so the realistic ceiling was
  roughly 10-16%. Fill collection (~12%) is paid regardless: fills must be
  collected as long as any slot stays dynamic. The remaining per-render
  costs (instances, queue, serialize) are the component-boundary
  placeholder's territory, not this design's.
- **Low hit rate in real templates.** Worse than the raw rate suggests: the
  slots that CAN precompute are systematically the cheap ones (titles, labels,
  short static fills), while the expensive slots (main/body content) are
  exactly the ones that contain components and can never precompute. The win
  concentrates where there is least to win.
- **`on_slot_rendered` becomes ubiquitous.** Confirmed as likely: a built-in
  extension (the dependency extension is the natural candidate) is expected
  to implement the hook, which would trip the gate in 14.3 everywhere and
  leave the feature as dead complexity.

### 14.6 Open points

- Const slot texts live inside cache keys; a large static fill (a whole
  sidebar) makes a large key. The bounded cache contains the memory cost,
  but it is worth a note in the guidance.
- Cardinality guidance is the same as for const kwargs: a slot whose text
  differs on every render should not be const (and won't be detected as
  such unless its inputs are wrongly marked).
- A child using the same slot name in several `<c-slot>` tags bakes the
  text in each place; that is correct and needs no special handling.

## 15. Precomputing more: deep-const, Computed, and expression propagation

Evaluating expressions is about 8% of a repeat render, and working out element
attributes about 10% (the large benchmark). Precomputing already removes some of that
for all-constant expressions (sections 3-4), but on a real page it barely moves
render time, because most of a page loops over data that changes every render
(see [benchmarking.md](benchmarking.md)). Three ideas were explored to precompute more.

They all run into one wall, the same one section 4.1 calls "a value that is
transformed loses the marker":

- **The read-and-compute barrier.** `Const` is a see-through wrapper, so
  `Const(d)['k']`, `Const(o).attr`, and `Const(5) + 1` all hand back the plain,
  unwrapped value. Looping over a constant list gives non-constant items, and
  deriving anything from a constant input drops the marker. That is why marking
  things constant helps a loop-over-data page so little, and all three ideas below
  are really about getting past this barrier.

The benchmark's expression mix shows the ceiling: of 364 dynamic `c-*` attributes,
248 are bare variables (mostly loop/data reads), ~36 are pure literals, and only 8
compute over a constant; of 47 `{{ }}` expressions, none compute over constants at
all. The page reads per-render data; it does not compute over constants.

The three ideas:

1. **Deep const for literal collections** - mark nested literals inside a literal
   dict/list, not just the container (15.1).
2. **`Computed(lambda: ...)`** - a Vue-`computed`-style value returned from
   `template_data` that stays constant even after you compute something from a
   constant, by tracking which `Const` inputs the computation read. This is an
   opt-in form of the Phase 2 taint that section 4.1 parked (15.2).
3. **Expression propagation** - if every variable an expression reads is `Const`,
   mark its result `Const` too. **This one shipped** (15.3).

### 15.1 Deep const for literal collections (assessed, not built)

**How it would work.** At the single marking site (4.1), when the attribute is a
literal (reads no variables) and the value is a dict/list/tuple/set, recurse and
wrap each nested literal, mirroring `freeze_const`'s container walk. No compiler
change.

**What it actually changes.** Less than it looks. The cache key is *unaffected*,
because `freeze_const` already recurses and unwraps for keying (so
`freeze_const(Const([Const(1), 2]))` already equals `freeze_const([1, 2])`). The
only new behavior is that a nested element stays `Const` if a child later forwards
it to a *grandchild* as a kwarg (for example `c-x="js_props['attachments']"` inside
the child). That is the sole payoff.

**Applicability.** Small. The benchmark has 2 literal dicts and 8 literal lists,
most of them *mixed* with a variable (`['border-b-2', styling['tab']]`), and mixed
collections are correctly never marked at all (a variable means the expression is
not a pure literal). The fully-literal ones are passed wholesale to a child via
`c-bind`, not subscripted into a grandchild, so deep marking buys nothing for them.

**Verdict.** Mostly redundant with the existing freeze recursion. Worth doing only
if a real workload forwards inner literals down two component levels. One hazard:
wrapping dict *keys* in a proxy can break C-level APIs (`getattr`, `json.dumps`)
that reject markers (section 4.1).

### 15.2 `Computed(lambda: ...)` (assessed, not built)

**How it would work.** A new class. Because the wrapper unwraps on access, deriving
a value from a `Const` (`"/" + Const(base)`, or `theme.sidebar_link` with `theme`
const) loses the marker, so `template_data` returns a plain field that
`extract_const_vars` ignores. A `Computed(lambda)` would run its lambda under a
tracker that records which `Const` objects had their value read, then key the
result on exactly those. `freeze_const` already gives each `Const` a stable key to
contribute. The open question is how the read set maps onto the cache signature (a
set of `(name, frozen value)` pairs): contribute each read `Const`'s own pair, or
one synthetic pair under the computed field's name. The result is a fresh object
each render, so the key must be the stable *inputs*, never the output.

**Why it is the hard one.** `template_data` is arbitrary Python, so you cannot know
its inputs without running it; you must observe them at run time. The wrapper has
no hook to observe an access today, so this needs a tracking-wrapper variant or
instrumented interceptors. This is exactly the Phase 2 taint propagation that
section 4.1 designed and parked; `Computed` is an opt-in alternative to full
automatic taint.

**Applicability.** About zero on the benchmark, for an instructive reason: the
derivations that lose const-ness (for example `TabsManual` building
`"border-b-2 " + theme.tab_active`) are built **inside Python loops over dynamic
data**, so the result legitimately depends on a non-constant loop value and stays
non-constant even with perfect tracking. `Computed` pays off for **config-heavy
components that derive from a constant theme outside any loop** (a sidebar shell, a
static button variant), which a data-heavy page is not.

**Verdict.** The most powerful and general of the three (it is the direct answer to
"a value stops being constant the moment you compute"), but the most complex and
the one with the least benchmark impact. Pursue it only with a config-heavy target
in hand.

### 15.3 Expression propagation (shipped)

This is the third idea, and the one that shipped, because it is the most surgical:
a focused change at the kwarg marking gate, no new types, no access tracking.

**The gap it closes.** The *body* half was already done: an `{{ expr }}` (or
attribute region) whose variables are all const already precomputes to text (4.2). The
new piece is the *child-kwarg* half. A child kwarg is marked at a separate place
(`ComponentNode._resolve_kwargs`), which used to mark `Const` only when the
expression read no variables. So `c-x="a + 3"` with `a` const was resolved live,
the result came back plain (the wrapper unwrapped during eval), and the child got a
plain kwarg that defeated its cache.

**The change.** `_kwarg_is_const` broadens the gate from "reads no variables" to
"every variable it reads is `Const` in the current scope", and the result is
wrapped `Const`. No access tracking is needed: template expressions are sandboxed
and pure, and their inputs are known up front, so the check is a static
`is_const(context.variables[name])` for each variable. (This is the key difference
from `Computed`, whose inputs are not knowable without running arbitrary code.) The
literal case is the no-variable special case of the same rule, so it is unchanged.

**What it measured** (eval count = calls to the compiled `safe_eval` callable;
output compared byte-for-byte; A/B against the old no-variable-only rule):

| page shape | output identical | eval count off -> on | repeat render off -> on |
|---|---|---|---|
| large benchmark (data-heavy) | yes | 2577 -> 2577 (0%) | 12.28 -> 12.43 ms |
| config nav, rich child (6 const exprs x 200) | yes | 1601 -> 401 (**-75%**) | 2.55 -> 2.46 ms (**-3.8%**) |
| config nav, lean child (1 const expr x 200) | yes | 601 -> 401 (-33%) | 1.99 -> 2.23 ms (**+12%**) |

What the numbers settle:

- **Correct everywhere.** Output is byte-identical on every shape: `Const` is
  transparent, so propagating it changes only what precomputes, not what renders.
- **Zero on the common case.** A data-heavy page gets no eval reduction (its child
  kwargs are per-render data) and pays only a tiny cost: one `is_const` lookup per
  variable of each expression attribute. On the benchmark that is within noise.
- **A real but conditional win on config-heavy pages, because it trades
  expression-eval for cache-key work.** When a child is fed kwargs computed
  entirely from constant inputs, those kwargs now propagate `Const`, the child
  precomputes its body on them, and many identical children collapse onto one cache
  entry. The eval count drops 33-75%. But each child now pays to *freeze* its const
  kwargs into a cache key, so the wall-clock only improves when the eval work saved
  outweighs that freeze cost: the rich child speeds up, the lean child slows down.
  This is the same trade const already makes for literal const kwargs; expression
  propagation just extends it to computed ones.

So it is worth keeping for what it unlocks (automatic precompute reuse for design-system
and app-shell components whose children derive from a constant theme), with the
honest caveat that it is not a free win and does **not** move the data-heavy
benchmark.

**Correctness** (four adversarial passes, each with a runnable reproducer; no new
wrong output or crash):

- It does **not** inherit the body precompute's staleness. The body precompute bakes an
  all-const `{{ expr }}` once, so an *impure* const expression in a body goes stale
  (`"1"`, `"1"`, `"1"`). Expression propagation recomputes the expression live in
  `_resolve_kwargs` every render and wraps only the fresh result, so its output is
  always current (`"1"`, `"2"`, `"3"`). It is strictly more correct here.
- One caveat: because the marking is automatic, an *impure* expression over const
  inputs (one whose result changes between renders even though its inputs are
  marked const, e.g. reading a mutable const object's changing field) mints a fresh
  cache signature each render, churning the child's body cache. Output stays
  correct and the cache is bounded by its LRU (512 entries), so this is a "your
  component will not cache" cost, not a bug - the same trap section 9 documents for
  marking an ever-changing value `Const`. The rule stands: an expression's const
  inputs should be genuine constants.

### 15.4 If you pick the unbuilt ideas up again

The honest test for deep const and `Computed` is narrow: *do they precompute a meaningful
fraction of a config-heavy component's body, even though they do nothing for a
data-heavy one?* Two cheap instruments answer it without fighting timing noise:
count how many `precompute_const_parts` nodes become precomputable with vs without the feature, and
count `safe_eval` evaluations per render; then confirm with a config-heavy
microbenchmark (a nav whose body is a literal item list and whose classes derive
from a `Const(theme)` outside any loop). Build `Computed` only if those numbers
justify the much larger machinery; deep const can wait for a concrete two-level
forwarding case, since it adds nothing to the cache key it was assumed to help.
