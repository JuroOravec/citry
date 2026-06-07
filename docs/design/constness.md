# Design: const-ness and render-body caching

**Status (2026-06-05): skeleton built; folding and taint parked.** The const
*flow* is wired: a transparent `Const` marker (a `wrapt.ObjectProxy` subclass,
`citry/constness.py`) that flows down the tree without being unwrapped,
detection on the `template_data` output, a const signature, and a
`Citry`-scoped body cache keyed by `(component class, signature)` in
`render_impl`. What is NOT built: the fold pass (so the cached body is not yet
specialized per signature, every signature maps to an equivalent node list) and
phase-2 taint. This document is the target to build toward.

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
const inputs is computed on the first render, folded into the body, and reused
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
  already folded.

The cache is a memoization keyed by "which inputs are const, and to what
values," scoped so it can be cleared and bounded.

---

## 3. Architecture

### 3.1 Layering

Three layers, from most-shared to least:

1. **Class: the body-generating function.** Parsing + compiling + exec of the
   template, cached once per component class (this exists today, see
   `_get_body_generator` in
   [`packages/py/citry/citry/component_render.py`](../../packages/py/citry/citry/component_render.py)).
   Calling it yields a fresh, unoptimized node list.
2. **Const cache: the optimized body.** Keyed by `(component class, const
   signature)`. The value is a specialized node list where all-const nodes
   have been folded and dead control-flow branches pruned. Scoped to the
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
- **Cache hit:** render the already-folded list directly; do not re-fold.

---

## 4. The `template_data` boundary (the crux)

This is the part that decides whether partial-const folding is sound.

The body does not consume kwargs; it consumes the **template variables**
returned by `template_data(kwargs, slots)`. Citry's base `template_data`
returns nothing, so template variables always come from an explicit, opaque
Python function of the inputs. Therefore "const kwarg" does not imply "const
template variable":

```python
def template_data(self, kwargs):
    return {"label": fetch_from_db(kwargs.title)}   # title const, label NOT const
```

To fold a node you must know its used template variables are const, which
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
  enables folding for the common pass-through case, and can land long before
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

### 4.2 The "all const" criterion is really "uses only const vars"

A natural first cut is "if all inputs are const, the whole output is static."
That criterion does not survive a planned feature: a special `self` template
variable that points at the current component instance. With `self` available,
no render is ever literally "all inputs const."

The correct criterion is therefore **"the template (or a node) uses only const
variables,"** evaluated per node against the variables that node actually uses,
not "all inputs are const." A node that touches `self` (or any non-const var)
is not foldable; a node that touches only const vars is.

---

## 5. The folded body is heterogeneous

Folding does not collapse a subtree to a single string. A folded body is a
list whose items are one of:

- `str`: static text, passes through unchanged.
- a **child placeholder** (see section 6): a recipe that, each render, produces a
  child `CitryRender` (with a fresh render id and re-merged deps) from a nested
  component node whose inputs are const.
- a dynamic node: a non-const node that re-evaluates against the live context
  each render.

### 5.1 Why a component boundary cannot fold to text

A nested `<c-Inner>` with const inputs still cannot become frozen text,
because every time the outer component renders:

- `Inner` must mint a **fresh render ID** (the same element rendered twice
  yields two identities, per #1650), and
- `Inner`'s JS/CSS must be (re)registered for this render.

So folding a component boundary yields a placeholder that has done the expensive
work once (parse, compile, fold of `Inner`'s body) but still re-emits cheaply
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

The folded placeholders of section 5 are recipes that produce a child
`CitryRender` each render (fresh id, re-merged deps), which is why a component
boundary cannot fold to frozen text.

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
plain data containers; else treat as non-const (refuse to fold) rather than
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

- A node is foldable iff **all** of its used variables are const in the node's
  scope. One non-const variable poisons the node.
- **Scope and shadowing:** `<c-for each="x in items">` introduces `x`; inside
  the loop `x` is not const even if an outer variable of the same name is.
  `<c-fill>` introduces its data/default variables similarly. Use the AST's
  `used_variables` and `introduced_variables` to mask correctly.
- **Control-flow pruning:** `<c-if cond="cols > 2">` with `cols` const can be
  evaluated at fold time and the dead branch dropped (a large part of the
  win). With `cols` non-const, keep both branches.

The inputs to this analysis (`used_variables`, `introduced_variables`) are
already tracked in the AST.

---

## 9. Invariants

- **Per-render state is never folded.** The render ID, component id, and any
  scoped CSS/JS hashes derived from it must be injected fresh on every render,
  never baked into the cached body. This is the same reason #1650 caches the
  element rather than the string.
- **`Const` is a user promise, not verified.** If a user marks a value const
  and then mutates it, output goes stale. That is acceptable and must be
  documented.
- **Folding assumes pure, deterministic expressions.** Citry expressions are
  sandboxed (see `safe_eval`), which mostly guarantees this, but folding does
  change when a const expression is evaluated (once, at first render).

---

## 10. Interactions and non-goals

- **Expression caching (#1473) is a separate concern.** That is a per-value
  memo of expression results while inputs are unchanged. It is unrelated to
  const folding and must not be entangled with it. In particular, because
  folded bodies are shared across elements with the same const signature but
  different dynamic inputs, the non-const nodes in a shared body must be
  stateless re-evaluators; any expression cache is a separate, value-keyed
  layer that only applies to truly-unshared nodes.
- **Slots and fills are non-const by default.** Slot content is usually
  dynamic child render content, so a component with a dynamically-filled slot
  is not fully foldable. Treat slots as non-const for now and exclude them from
  the const signature. Later they could become `Const`-compatible: when a slot
  comes from a `<c-fill>`, the possible states of the slot output depend on the
  inputs to the nodes inside the fill body, so const-ness could be derived from
  those inputs. That is a later phase.
- **Defaults as implicit const (with a caveat).** A kwarg with a constant
  default that is not passed is effectively const, so `MyCard(title=Const("hi"))`
  with `cols: int = 3` could fold `cols` too. The caveat is that defaults can be
  **dynamic**: a `default_factory` may produce a fresh value each call (for
  example a random uuid), which is not const. So defaults cannot be marked const
  blindly. Because const-ness is observed on the `template_data` output (section
  4), a stable default value can flow through and be detected naturally; the
  genuinely problematic case is a user who intends a dynamic default factory,
  whose output must not be treated as const. Concretely: a constant (literal)
  default is safe to treat as const; a factory default is not, since the engine
  cannot tell a pure factory from `uuid4`.
- **Typing ergonomics.** `title=Const("hi")` should still type-check against
  `title: str`. That usually means typing `Const` as `def Const(x: T) -> T`
  (transparent to the checker, wraps at runtime) or having `Kwargs` accept
  `T | Const[T]`. Prototype this early; it shapes the API surface.
- **Thread-safety.** The shared cache is read and written during render;
  concurrent renders need a lock or a concurrent map. First-render folding
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
- Fold-time errors: if a const node raises while folding, does the error
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
3. A `fold(body, const_vars, scope)` pass over the existing node list using
   `used_variables` / `introduced_variables`, with `c-if` branch pruning
   (section 8), producing the heterogeneous body of section 5.
4. The child-element struct (a `CitryElement`) that re-emits with a fresh
   render ID and re-registers JS/CSS (sections 5, 6).
5. Typing ergonomics, constant-default detection, invalidation, thread-safety.
6. **Phase 2 taint (section 4.1):** propagate the const flag through operations,
   so a transforming `template_data` still yields detectably-const variables.

Defer phase 2 taint and slot const-ness until the phase 1 pieces are in place
and measured.
