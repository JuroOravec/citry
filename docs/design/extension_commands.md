# Design: extension commands (the CLI)

**Status (2026-06-28): the CLI is complete; the host bridge and MCP were
deliberately dropped.** This document is the design for citry's command-line
interface and the per-extension commands that feed it. Phases 1 to 4 of section
14 are done: the declarative command model and runner (`citry/command.py`), the
grown `ExtensionCommand`, the `ExtensionManager.commands` / `Citry.commands`
aggregation, the `citry` executable with `ext list` / `ext run`, `--app` engine
selection, and `--version`, and the core `list` / `create` commands
(`citry/commands/`, `citry/__main__.py`), all with tests. Phase 5 (a Django
management-command bridge and an MCP server) was considered and deliberately not
built; section 14 records why.

For the extension/hook system these commands plug into see
[`extensions.md`](extensions.md). For the route-aggregation pattern this design
deliberately copies see [`extensions.md`](extensions.md) section 11 and
[`dependencies.md`](dependencies.md) section 9. For the broader migration
context, and the status-table rows this design resolves, see
[`citry_migration.md`](citry_migration.md). For operating rules see
[`/CLAUDE.md`](../../CLAUDE.md).

Upstream references: django-components
[#1118](https://github.com/django-components/django-components/issues/1118)
(a standalone CLI and a Model Context Protocol (MCP) server for components). Prior art:
[`util/command.py`](../../packages/py/citry/_djc_reference/util/command.py),
the [`commands/`](../../packages/py/citry/_djc_reference/commands/) tree, and the
Django bridge
[`compat/django.py`](../../packages/py/citry/_djc_reference/compat/django.py).

---

## 1. Prior art (what was searched)

In `packages/py/citry/_djc_reference/`, django-components already ships a command
system that is mostly framework-neutral:

- **`util/command.py` is the whole declarative model.** `ComponentCommand`
  (`util/command.py:243-342`) is a class an extension subclasses to declare a
  command: `name`, `help`, `arguments`, `subcommands` (a sequence of command
  *types*, not instances), and a `handle()` method. Four dataclasses describe
  the arguments: `CommandArg` (`:52-106`), `CommandArgGroup` (`:109-132`),
  `CommandSubcommand` (`:135-189`), and `CommandParserInput` (`:192-230`). Their
  field names match Python's `argparse` one for one, because each dataclass's
  `asdict()` (with `None` values stripped) is splatted straight into the
  matching `argparse` call. `setup_parser_from_command()` (`:345-367`) walks a
  command class and builds an `argparse.ArgumentParser`, recursing into
  subcommands.
- **One trick carries the whole dispatch.** While building the parser,
  `_setup_parser_from_command` calls
  `parser.set_defaults(_command=command(), _parser=parser)`
  (`util/command.py:377`). After `parse_args()` runs, the caller reads back
  `_command` (the matched command instance) and `_parser` (its parser) to know
  which nested subcommand the user actually invoked.
- **The run loop is the one Django-coupled piece.** The parse-then-dispatch
  loop lives only inside the Django bridge:
  `compat/django.py:load_as_django_command` (`:73-124`) wraps a
  `ComponentCommand` as a Django `BaseCommand`, and its `handle()` reads
  `_command`/`_parser` and either calls `resolved_command.handle(...)`, prints
  the subcommand help, or prints the root help (`:107-120`). Everything else in
  that file is Django plumbing (the `DJANGO_COMMAND_ARGS` global at `:24-70`).
- **The command tree is plain composition.** `commands/components.py` defines
  the root `components` command with subcommands `create`, `upgrade`, `ext`,
  `list`. `commands/ext.py` defines `ext` with subcommands `list`, `run`.
  `commands/ext_run.py` defines `run`, whose subcommands are generated at access
  time by a descriptor: one synthetic routing command per extension, each
  carrying that extension's `commands` as its own subcommands. The descriptor
  exists so the tree always reflects the live extension set, which matters
  because django-components keeps extensions in a module global that tests
  mutate.
- **Presentation helpers travel with the model.** `style_success` /
  `style_warning` (ANSI color, `util/command.py:430-437`) and
  `format_as_ascii_table` (`util/misc.py`) are pure-Python helpers used by the
  `list`-style commands. They are internal (not re-exported from the package).

In citry today (`packages/py/citry/citry/`):

- **`ExtensionCommand` is a named stub.** `extension.py:268-285`: it has
  `name`, `help` (default `""`), and `handle(self, *args, **kwargs) -> None`,
  with a docstring saying there is no runner yet. It is exported from
  `citry/__init__.py`.
- **The per-extension surface already exists.**
  `Extension.commands: ClassVar[list[type[ExtensionCommand]]] = []`
  (`extension.py:361-362`), and the manager can resolve one:
  `ExtensionManager.get_extension_command(name, command_name)`
  (`extension.py:619-624`) scans one extension's `commands` and raises
  `ValueError` if the name is not found.
- **The aggregation pattern this design copies is the route table.**
  `Citry.urls` (`citry.py:256-265`) is a property delegating to
  `ExtensionManager.urls` (`extension.py:626-651`), which fans every
  extension's `urls` into one table: built-in extensions' routes sit at the
  root, user extensions' routes are namespaced under `ext/<name>/`, and built-in
  names are reserved so a user extension cannot shadow them
  (`extension.py:584-610`). The host adapters under
  [`contrib/`](../../packages/py/citry/citry/contrib/) translate that one
  neutral surface per framework.
- **No CLI exists yet.** There is no `[project.scripts]` entry in any
  `pyproject.toml`, no `__main__`, and no `argparse`/`sys.argv` use anywhere in
  `citry/`. Extensions are fixed at construction from
  `CitrySettings.extensions` (`settings.py:70`), which accepts classes,
  instances, or `"path.to.Class"` import strings; the default engine is the
  module global `citry = Citry()` (`citry.py:485`).

The conclusion: the declarative model and command tree port almost verbatim;
the missing pieces are the run loop (lift it out of the Django bridge), the
cross-extension aggregation (copy the route-table shape), and a `citry`
executable (new).

---

## 2. Scope: this is a Python-package feature, not a Rust contract

The cross-binding consistency audit (CLAUDE.md Mechanism 4) is short here, and
worth stating up front so nobody widens the change by reflex. Extensions are
Python objects, the commands they declare are Python classes, and the runner
that dispatches them is Python. None of citry's Rust contract is involved: no
grammar rule, no AST struct, no compiler output, no `LangImpl` method, and no
PyO3 glue. `ExtensionCommand` is a plain Python class, not a `#[pyclass]`, so
the `_rust.pyi` stub does not change either.

So this feature lives entirely under
[`packages/py/citry/citry/`](../../packages/py/citry/citry/). When other host
languages eventually grow an extension system, each will grow its own command
layer in its own idiom (a JS argument parser, a PHP one, and so on). Commands
are thin enough that duplicating the small declarative layer per language is
cheaper and clearer than defining a language-neutral command format in the Rust
core. If that trade ever flips (see section 11), this is the decision to
revisit.

---

## 3. The command model: declarative, lifted from the Django bridge

Port the django-components model into a new module
`packages/py/citry/citry/command.py`, the framework-neutral home for everything
the CLI needs.

### 3.1 Extend `ExtensionCommand` to the full declarative shape

Keep the existing base where it is (`extension.py`, still exported from
`citry/__init__.py`), and grow it from the stub to the full surface:

- `name: ClassVar[str]` - the invocation name (already present).
- `help: ClassVar[str]` - one-line description (already present).
- `arguments: ClassVar[Sequence[CommandArg | CommandArgGroup]]` - the
  command's positional arguments and options.
- `subcommands: ClassVar[Sequence[type[ExtensionCommand]]]` - nested commands.
- `handle(self, *args, **kwargs) -> None` - run the command; the parsed options
  arrive as keyword arguments. A command with no `handle` override prints its
  help (a command that exists only to group subcommands).

The argument dataclasses keep their argparse-aligned field names and concise
names (`CommandArg`, `CommandArgGroup`, `CommandSubcommand`), and live in
`command.py` alongside the base. A worked example:

```python
from citry import CommandArg, ExtensionCommand, Extension


class GreetCommand(ExtensionCommand):
    name = "greet"
    help = "Print a greeting."
    arguments = [
        CommandArg("name", help="Who to greet."),
        CommandArg(["--shout", "-s"], action="store_true", help="Upper-case it."),
    ]

    def handle(self, name, *args, **kwargs):
        message = f"Hello, {name}!"
        if kwargs.get("shout"):
            message = message.upper()
        print(message)


class GreeterExtension(Extension):
    name = "greeter"
    commands = [GreetCommand]
```

### 3.2 Add the two functions that were trapped in the Django bridge

`command.py` provides the framework-neutral pair that django-components only had
inside `compat/django.py`:

- `build_parser(command: type[ExtensionCommand]) -> ArgumentParser` - the
  recursive parser builder (django-components' `setup_parser_from_command`),
  including the `set_defaults(_command=..., _parser=...)` trick so the matched
  command can be recovered after parsing.
- `run(command: type[ExtensionCommand], argv: Sequence[str]) -> int` - parse
  `argv`, then dispatch with the same three cases the Django bridge used: if the
  matched command has a `handle`, call it; else if a parser matched, print its
  help; else print the root help. Returns a process exit code.

`argparse` is in the standard library, so this adds no runtime dependency. Keep
the import of `command.py` lazy from anything on the hot import path, so
`import citry` does not pull the CLI in.

---

## 4. Aggregating commands: mirror `Citry.urls`

Commands aggregate across extensions the way routes already do, so the two
surfaces share one mental model. The aggregation is simpler than the route
table, though: every extension's commands are reached uniformly through
`ext run <extension> <command>` (section 5), so there is no flat-versus-namespaced
split like the one `urls` applies to built-in versus user routes.

- Add `ExtensionManager.commands`, paralleling `ExtensionManager.urls`
  (`extension.py:656-680`). It returns a mapping of extension name to that
  extension's `commands`, with built-in extensions first (they are prepended at
  construction) and only extensions that actually declare commands included.
  Extension names are unique (enforced at construction), so the keys never
  collide.
- Add a thin `Citry.commands` property paralleling `Citry.urls`
  (`citry.py:256-265`) that delegates to `self.extensions.commands`.

Like `urls`, `Citry.commands` rebuilds on each access (cheap, and correct for
tests that swap the extension set between cases). The single-extension resolver
`get_extension_command` (`extension.py:635-640`) stays as the lookup primitive
underneath.

---

## 5. The CLI surface

Match the proven django-components layout, which keeps the namespace predictable
and collision-proof:

```
citry ext list                              # list installed extensions
citry ext run <extension> <command> [args]  # run any extension's command
citry list                                  # core: list registered components
citry create <name>                         # core: scaffold a new component
```

`ext run` is the single, uniform entry for every extension command, so a user
extension can never shadow a core command. Its per-extension subcommands are
built from `Citry.commands` for the resolved engine (section 6). Because the CLI
resolves one engine per invocation, it can build the tree eagerly; the lazy
descriptor django-components needs (`commands/ext_run.py`) is only there to cope
with a mutating module global, which citry does not have.

`create` scaffolds a V3 `<c-*>` component file (a Python class with a `Kwargs`
class, a `template_data` method, and a multiline `template` string, as components
are actually authored; `js` / `css` are left out by default, section 13), not a
Django-template component. The legacy django-components commands `upgrade`,
`upgradecomponent`, and `startcomponent` migrate old `{% component %}` template
syntax and are deliberately not carried over.

A possible later ergonomic refinement: promote a built-in extension's commands
to the top level (for example `citry deps ...`) to mirror the route table's
"built-ins at the root" rule even more closely. It is left out of the initial
surface because two ways to run one command is more confusing than it is worth;
revisit per extension if a built-in command is common enough to deserve a short
path.

---

## 6. Choosing the engine the CLI runs against

This is the one question django-components never had to answer: its extension
set is a single Django-configured global, so its CLI just uses it. citry lets a
project build its own `Citry(...)`, so the CLI has to decide which engine's
extensions and registry it operates on.

- **Default:** use the module global `citry` (`citry.py:485`), after triggering
  autodiscovery so the component registry is populated before `list` or `create`
  read it.
- **Override:** `citry --app <module>:<instance>` imports an explicit engine,
  the same `module:object` convention Python web servers (ASGI/WSGI) use to find an app,
  and the same explicit-instance idea the contrib adapters already take. A
  project with a custom engine points the CLI at it this way.

Django projects use the same `citry` binary directly: when django-components
runs on citry, citry is installed and so is its console script (section 14
records why a `manage.py` bridge was deliberately not added).

The ordering rule matters: whichever engine is chosen, autodiscovery must run
before any command reads the registry, or `list` and `create` will see an empty
project.

---

## 7. Entry point and packaging

- The first `[project.scripts]` entry in
  [`packages/py/citry/pyproject.toml`](../../packages/py/citry/pyproject.toml):
  `citry = "citry.__main__:main"`, so installing the package puts a `citry`
  command on the user's PATH.
- `citry/__main__.py` resolves the engine (section 6), builds the root command
  tree for it, and runs it. The standalone binary needs no host framework: build
  the parser, parse argv, dispatch. There is no per-framework bridge; every host
  (Django included) calls the same `citry` binary directly (section 10).

---

## 8. Naming

- **`ExtensionCommand`** - the base an extension subclasses (DJC:
  `ComponentCommand`). The name was already chosen in
  [`extensions.md`](extensions.md) section 4 and is kept.
- **`CommandArg` / `CommandArgGroup` / `CommandSubcommand`** - the argument
  dataclasses, kept at their concise django-components names because they read
  as a thin layer over `argparse` and that is exactly what they are.
- **`Citry.commands`** - the aggregated per-engine command surface, named to
  sit beside `Citry.urls`.
- **`citry`** - the executable, matching the package name.

---

## 9. Why keep the declarative model

The alternative to the dataclass model is to have each command build its
`argparse` parser by hand. Keeping the declarative layer costs one small module
and earns two things:

- **A single source of truth that more than one front end can read.** The
  `CommandArg` declarations are data, so the same command definition can drive an
  `argparse` parser today and, if one is ever wanted, a structured tool schema
  tomorrow (for example an MCP server, the second half of django-components
  [#1118](https://github.com/django-components/django-components/issues/1118)).
  Generating that schema from the declarations would be close to free.
- **Independence from the parser library.** Because the model is just data,
  swapping `argparse` for a richer CLI library later changes only
  `build_parser`, not any command definition.

No such alternate front end is planned: the MCP server is a deliberate non-goal
(section 14). The point is that the declarative model preserves the option at
almost no cost, which is exactly why dropping it now is safe and reversible.

---

## 10. Alternatives considered

- **Keep `ExtensionCommand` minimal (only `handle`) and build `argparse` by
  hand in each command.** Rejected: it loses the single-source-of-truth benefit
  in section 9, diverges from the contract extension authors already expect from
  django-components, and makes every command re-implement argument wiring.
- **Ship no executable; expose commands only through host CLIs (Django's
  `manage.py`, a Flask CLI, and so on).** Rejected: the core `create` and `list`
  commands must work outside any web framework, and one installed `citry` binary
  serves every host directly. A Django `manage.py` bridge specifically was
  considered and dropped (section 14).
- **Promote every extension's commands to the top level (perfect symmetry with
  the route table's "built-ins at the root" rule).** Rejected for the initial
  surface: a uniform `ext run` namespace is easier to reason about and rules out
  command-name collisions; targeted promotion can be added later (section 5).

---

## 11. What would falsify this design

The load-bearing assumption is that commands are a per-language concern. The
design breaks if citry ever needs the one `citry` executable to dispatch
commands that were *defined by a non-Python extension* (a JS, PHP, or Go
extension) through the shared Rust core. At that point a Python-only,
`argparse`-shaped model is the wrong layer, and commands would need a
language-neutral definition in the crates, surfaced to each binding. Today
extensions are Python-only, so the assumption holds; this is the single
condition to watch.

---

## 12. Files this touches (consistency checklist)

All Python, all under `packages/py/citry/`:

- `citry/command.py` (new): `CommandArg` / `CommandArgGroup` /
  `CommandSubcommand`, `build_parser`, `run`, and the table/style helpers.
- `citry/extension.py`: grow `ExtensionCommand` from the stub; add
  `ExtensionManager.commands`.
- `citry/citry.py`: add the `Citry.commands` property.
- `citry/commands/` (new): the core `list` and `create` commands and the
  `ext` / `ext list` / `ext run` routing commands.
- `citry/__main__.py` (new) and `pyproject.toml`: the `citry` entry point.
- `citry/__init__.py`: export the new public names (`CommandArg`, and friends).
- Tests: parser construction and dispatch, the command aggregation (mirroring
  the existing `urls` aggregation tests), and an end-to-end `run([...])` against
  a sample extension command.

Explicitly unchanged: the Rust crates, the grammar, the AST, the compiler
output, the `LangImpl` implementations, the PyO3 glue, and the `_rust.pyi` stub
(section 2).

---

## 13. Open questions

- **CLI dependency policy.** `argparse` (standard library) keeps the runtime
  dependency-free. If a richer library (for colored help, completion) is ever
  wanted, it must stay an optional extra so that `import citry` pulls in
  nothing; the declarative model already isolates that choice to `build_parser`
  (section 9).
- **`--app` discovery details.** The `module:attribute` form is built and is the
  recommended default; whether to also support discovery from a `pyproject.toml`
  `[tool.citry]` table or a `CITRY_APP` environment variable is a later
  ergonomics decision.
- **What `create` scaffolds (resolved for the MVP).** `create` writes a single
  file with a `Kwargs` class, a `template_data` method, and a multiline
  `template`, the smallest shape that teaches the data-to-template flow. `js` and
  `css` blocks are left out by default to keep the starting point lean; a flag to
  include them (and any multi-file layout) can follow if there is demand.

---

## 14. Suggested phasing

Each phase is independently shippable and lands with tests.

1. **The model. (Done.)** `citry/command.py`: the argument dataclasses, the
   grown `ExtensionCommand`, `build_parser`, and `run`. Tested in
   `tests/test_command.py` (building a parser, parsing argv, asserting the right
   `handle` ran, and the no-handle command printing help).
2. **Aggregation. (Done.)** `ExtensionManager.commands` and `Citry.commands`.
   Tested in `tests/test_extension.py` (`TestCommands`): keyed by extension name,
   built-ins first, extensions without commands omitted, and the
   `get_extension_command` resolver.
3. **The executable. (Done.)** `citry/__main__.py`, the `[project.scripts]`
   entry, `ext list` / `ext run`, and `--app` engine selection. The runner binds
   the chosen engine to each command instance (as `self.citry`, mirroring
   `Extension.citry`) so a command's `handle` can reach the registry and
   extensions; the per-extension `ext run` tree is built from `Citry.commands`.
   Tested in `tests/test_cli.py` (engine binding, the command tree, and `main`'s
   `--app` resolution).
4. **Core commands. (Done.)** `citry list` (reads `Citry.components`, which runs
   autodiscovery first) and `citry create <name>` (scaffolds a component file:
   the class name is the PascalCase of the given name, the file is its
   snake_case, and an existing file is never overwritten). Tested in
   `tests/test_cli.py` (listing registered components; scaffolding, name-case
   handling, and the no-overwrite guard).
5. **Host bridge and MCP. (Dropped, 2026-06-28.)** A Django management-command
   bridge and an MCP server were both considered and deliberately not built.

   - **Django bridge.** citry is framework-neutral: the engine is a `Citry(...)`
     configured through `CitrySettings`, components are plain Python, and `--app
     module:attribute` already targets the configured instance. When
     django-components runs on citry, citry (and its `citry` console script) is
     installed, so Django users call the same binary directly. A `manage.py`
     bridge would only add a second code path that tracks Django's command API,
     for no capability the standalone binary lacks. The one scenario it would
     serve (an engine whose import needs `django.setup()` first) contradicts the
     framework-neutral premise, and a user who has it can write a three-line
     management command themselves.
   - **MCP server.** A capable model with shell access can read the docs and
     `--help` and call the installed `citry` CLI directly, so wrapping it as MCP
     tools buys little here; MCP's durable value (permissioning, remote
     transport, non-shell hosts) is a product concern, not a templating
     library's. The declarative command model (section 9) keeps the option open
     at almost no cost, so this stays reversible if a future need appears.

   In place of these, the follow-up work is documentation: the `citry` CLI is
   covered in the README and the changelog so the "read the docs" path actually
   works. A `citry --version` flag is built; shell completion could follow as an
   optional extra.
