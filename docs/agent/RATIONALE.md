# RATIONALE.md - why these rules exist

This document explains why the [`docs/agent/`](.) directory and the
rules in [`/CLAUDE.md`](../../CLAUDE.md) exist. Optional reading. It is kept so
future agents (and humans) understand the reasoning and do not silently relax
the constraints.

---

## The shape of this project

Citry is a Rust-first templating engine with thin per-language bindings. The
central artifact, the template parser and compiler, is a **contract that spans
five host languages plus the Python bindings**. The grammar feeds the AST, the
AST feeds the compiler, the compiler output feeds runtime node classes in each
host language, and the AST types are also exposed directly to Python and
mirrored in a hand-written stub. A change at any layer can ripple through all
of them.

That fan-out is the root reason for the rules. A change that looks local (one
grammar rule, one AST field, one line of codegen) is frequently not local, and
the failure mode is silent: the code reads correctly, the crate compiles, and
the drift only surfaces later in a different language binding or at runtime.

## Incidents that shaped the rules

### Trusting the grammar over running the parser

A whitespace bug (a space after a closing tag being dropped) was diagnosable
only by running the parser on representative inputs and reading the actual
output, not by reading the grammar. The grammar looked correct; the behavior
came from Pest's implicit-whitespace insertion, which is invisible in the rule
text. This is why parser/compiler tests are authored observe-then-lock, and why
the prior-art rule says to confirm against the running implementation rather
than the docs or the rule text.

### A local-looking change with non-local effects

Fixing that whitespace bug required changing one rule's atomicity. Because Pest
atomicity cascades to called rules, the one-line change altered comment and raw
parsing too. The change was correct (it exposed two latent issues that were
themselves bugs), but it confirmed that grammar atomicity is never a local
decision. This is the origin of the cross-binding consistency audit (Mechanism
4) and the high-risk gate on the grammar.

### Non-determinism hiding in plain sight

The compiler emitted a node's used-variable names by iterating a `HashSet`,
producing output that varied run to run. Generated code is a contract and may
be cache-keyed, so non-determinism is a correctness bug, not a cosmetic one. It
was found only because exact-string compiler tests flaked. This is why
determinism is called out as a gotcha and why the "fix the whole class"
mechanism exists: the hash-set-into-output pattern is greppable, and a fix
should sweep for siblings.

### Updating tests instead of working around the fix

When the whitespace fix made HTML-comment values symmetric and made `<c-raw>`
attribute rejection explicit, the right move was to update the tests that had
encoded the old behavior, not to special-case the code to keep them green. A
failing test under a deliberate, more-correct change is usually evidence the
test captured the old bug. The rule is to update such tests and call the
contract change out explicitly.

### Trusting an in-process timer that keeps the fastest warm run over the fresh-process benchmark

A render change measured as a few-percent speed-up by an in-process A/B that
keeps the fastest warm run. It was built, made always-on, and nearly kept. The
cross-engine benchmark (fresh subprocess per cell, median of 5) then showed the
opposite: a large first-render regression and a flat warm render. The best-of-N
timer hid both failure modes by construction. It never renders the first,
uncompiled pass, so a one-time compile cost is invisible to it; and keeping the
best run samples out the steady per-render overhead the change adds. Comparing
the new path against the old with both carrying the new machinery also hid that
machinery's own cost. This is why the in-process timer is for finding and sizing
a change while the keep-or-drop decision is the fresh-process median
(`performance.md` section 1). The change is recoverable in git if the cost model
ever shifts.

## What the industry has observed

Recent writing on AI coding agent failure modes converges on a few points that
match the incidents above:

- **Codebase exploration is the dominant failure mode.** Agents stop at the
  first plausible conclusion and design before fully verifying, especially near
  module or package boundaries. The prior-art header and plan-mode mechanisms
  exist to force falsification before code lands.
- **Agents reinvent conventions that are not written down.** When naming,
  layout, or contract rules live only in a maintainer's head, agents invent
  parallel vocabulary. Writing the conventions down (here and in
  [`docs/codebase.md`](../codebase.md)) is the mitigation.
- **A source-controlled project-knowledge index is the emerging best practice.**
  Durable facts belong in version control, visible in `git status`, not in a
  machine-local agent memory store that no teammate or future session can see.
  That is why these docs exist and why CLAUDE.md forbids putting architectural
  knowledge in the memory store.

## What these rules do not solve

They do not replace running the code. The recurring lesson is that the
implementation is authoritative: when a stub, a docstring, or even the grammar
text seems to answer a question, the answer is to run the parser or compiler
and read what actually comes out.

---

For the operating rules themselves, see [`/CLAUDE.md`](../../CLAUDE.md). For the
architectural facts, see [`INDEX.md`](INDEX.md).
