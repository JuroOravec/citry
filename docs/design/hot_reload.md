# Design: hot reload (the file watcher that drives invalidation)

**Status (2026-06-28): design agreed; built.** This document
specifies the file watcher that turns "a component file changed on disk" into
"the next render shows the new content". The cache-invalidation half already
exists in citry (the reverse index plus the `reset_template` / `reset_files`
methods, see [`asset_loading.md`](asset_loading.md) section 8); this document
covers the piece that calls it: a host-neutral, pluggable watcher, plus how it
is started under each host.

Built: the `Citry.invalidate_file` and `Citry.invalidate_all` primitives and the
index lock (section 4); the pluggable `citry.reload` watcher with the
`watchfiles` and `watchdog` backends and the dependency-free poller (section 5);
the `citry watch` command, the Django `enable_hot_reload` piggyback, and the
Starlette/FastAPI `reload_lifespan` helper (section 6); and the
`watcher-watchfiles` and `watcher-watchdog` extras (section 8). The open
questions in section 11 (a `restart` callback, the default watch roots) remain.

For the seam this drives see [`asset_loading.md`](asset_loading.md) section 8.
For the broader migration context see
[`citry_migration.md`](citry_migration.md) (the `reload_on_file_change` and
`apps.py` rows). For the extension system a watcher can use see
[`extensions.md`](extensions.md); for the contrib adapters that mount citry into
a host see [`dependencies.md`](dependencies.md) section 9. For operating rules
see [`/CLAUDE.md`](../../CLAUDE.md).

Upstream reference: django-components implements dev hot reload by subscribing
to Django's autoreload `file_changed` signal in
[`apps.py`](../../packages/py/citry/_djc_reference/apps.py)
(`_setup_component_file_reload`), with a `reload_on_file_change` setting and a
`ReloadMode` of `off` / `hot` / `restart`. It never runs its own watcher; it
borrows Django's. That asymmetry is the central reason citry needs its own
host-neutral watcher (sections 1 and 3).

The browser half is tracked separately in
[#9](https://github.com/citry-dev/citry/issues/9) (browser live-reload).

---

## 1. Prior art (what was searched)

### The invalidation seam in citry (done)

- `Citry.get_components_for_file(path) -> list[type[Component]]`
  ([`citry.py:462-483`](../../packages/py/citry/citry/citry.py#L462)) resolves
  the path with `Path(path).resolve()`, looks it up in the reverse index
  `_file_index` ([`citry.py:161-166`](../../packages/py/citry/citry/citry.py#L161)),
  prunes dead weakrefs on read, and returns the live component classes that
  loaded an asset from that file. Empty list when the file backs no loaded
  component.
- `_register_component_file(path, comp_cls)`
  ([`citry.py:455-460`](../../packages/py/citry/citry/citry.py#L455)) populates
  the index, keyed by `str(Path(path).resolve())`. It is called lazily, as a
  class first resolves an asset, from the loader
  ([`assets.py:194`](../../packages/py/citry/citry/assets.py#L194)) and from the
  dependencies extension
  ([`extensions/dependencies/__init__.py:453,461`](../../packages/py/citry/citry/extensions/dependencies/__init__.py#L453)).
- `Component.reset_template()` and `Component.reset_files()` (classmethods, no
  args, [`component.py:793-811`](../../packages/py/citry/citry/component.py#L793))
  delegate into [`assets.py:289-322`](../../packages/py/citry/citry/assets.py#L289):
  `reset_template` drops the cached `CitryTemplate` (source and compiled form,
  one object) and evicts the class's const-body cache entries; `reset_files`
  drops the cached JS/CSS and fires the `on_files_reset` hook so extensions
  evict their own per-class state. Invalidation is lazy: nothing re-reads
  eagerly, the next render re-resolves and re-compiles.

### The django-components watcher (the whole mechanism, host-specific)

- [`_djc_reference/apps.py:78-121`](../../packages/py/citry/_djc_reference/apps.py#L78):
  `_setup_component_file_reload` connects one receiver to Django's
  `file_changed` signal. The receiver resolves the changed path, looks up the
  components, calls `reset_template()` + `reset_files()` on each, then returns
  `True` for `hot` (tells Django's autoreloader the change was handled, so no
  process restart) or `None` for `restart` (Django's `notify_file_changed`
  treats that as unhandled and calls `trigger_reload()`, which is `sys.exit(3)`
  caught by the parent reloader process).
- [`_djc_reference/app_settings.py:128-162`](../../packages/py/citry/_djc_reference/app_settings.py#L128):
  `ReloadMode` is `off` / `hot` / `restart`, default `hot`; `restart` is
  deprecated upstream (it clears the same caches as `hot` and additionally
  restarts).
- The actual file watching is Django's `StatReloader` (mtime polling) or
  `WatchmanReloader`, started by Django's runserver, not by django-components.
  django-components registers no directories of its own; component dirs get
  watched only because they are also Django template or static dirs.

### Host integration in citry today

- Every contrib adapter is mount-only: FastAPI/Starlette `mount`
  ([`contrib/fastapi.py`](../../packages/py/citry/citry/contrib/fastapi.py)),
  Flask `mount` ([`contrib/flask.py`](../../packages/py/citry/citry/contrib/flask.py)),
  Django `urlpatterns` ([`contrib/django.py:64`](../../packages/py/citry/citry/contrib/django.py#L64)),
  and the generic ASGI/WSGI apps. None owns process startup or a dev-vs-prod
  switch.
- The one existing startup hook is the ASGI `lifespan` scope, currently a
  no-op ack ([`contrib/asgi.py:50-57`](../../packages/py/citry/citry/contrib/asgi.py#L50)).
  WSGI has no lifespan; the Django adapter has no `AppConfig.ready()`.
- `Citry(...)` builds a frozen `CitrySettings`
  ([`settings.py:25`](../../packages/py/citry/citry/settings.py#L25)); the
  default global instance is built at import time
  ([`citry.py:507`](../../packages/py/citry/citry/citry.py#L507)), before user
  code runs. `template_globals` is the precedent for a mutable
  post-construction attribute ([`citry.py:119`](../../packages/py/citry/citry/citry.py#L119)).
- The CLI resolves a target engine from `--app module:attribute`
  ([`__main__.py:32-60`](../../packages/py/citry/citry/__main__.py#L32)) and
  dispatches into commands aggregated by `Citry.commands`
  ([`extension_commands.md`](extension_commands.md)).
- Extensions are per-instance, fire `on_extension_created` at construction
  ([`citry.py:183`](../../packages/py/citry/citry/citry.py#L183)), and can
  expose `urls` and `commands`. There is no shutdown or teardown hook.
- No `[project.optional-dependencies]` table exists yet
  ([`packages/py/citry/pyproject.toml`](../../packages/py/citry/pyproject.toml)),
  so the watcher extras (section 8) are the first runtime extras.

### Design intent already recorded

- [`citry_migration.md`](citry_migration.md) `reload_on_file_change` row: the
  invalidation seam is done in citry; "the file watcher and the hot/restart
  policy are host-specific". `apps.py` row: "Any future citry watcher (e.g. for
  a dev server) would be a separate, host-neutral design."
- [`asset_loading.md`](asset_loading.md) section 8 and the DJC surface table:
  the watcher is deferred, "likely an extension, using `get_components_for_file`".
  This document revisits the "extension" guess (section 6).

### Watcher library landscape (2026)

- `watchfiles` is Rust/`notify`-backed, the watcher uvicorn[standard],
  Starlette, and `django-watchfiles` use; prebuilt wheels for Linux/macOS/
  Windows, an async `awatch` over anyio, a `force_polling` fallback for network
  and Docker mounts, MIT licensed, actively maintained.
- `watchdog` is mature and Apache-2.0, but threading-only (no async) and ships
  a C extension on macOS.
- Django's `StatReloader` (mtime polling) is the zero-dependency baseline;
  `WatchmanReloader` depends on the now effectively unmaintained `pywatchman`,
  which is why the Django community has moved to `django-watchfiles`.
- The Rust `notify` crate is what `watchfiles` wraps. Building a native watcher
  into citry's PyO3 core would duplicate `watchfiles` and is rejected (section 9).

---

## 2. Scope and the decisions that shaped it

1. **Host-neutral by design.** The watcher and its invalidation primitive live
   in the pure-Python `citry` package, not in the Rust core. Other host
   languages grow their own watcher over their own binding of the same seam;
   there is no watcher abstraction in the crates (section 10).
2. **Pluggable, not single-vendor.** A small `FileWatcher` protocol with
   several implementations (section 5): `watchfiles` as the default,
   a zero-dependency stdlib poller as the always-available fallback, optional
   `watchdog`, and "bring your own / feed host events" as a first-class path.
   This is what lets the same code serve a host that already runs a watcher
   (Django, uvicorn) and a host that does not.
3. **Invalidation is a core primitive; the watcher is optional.** The one
   host-neutral contract, `Citry.invalidate_file` (section 4), is plain Python
   with no watcher dependency. The watcher (section 5) sits behind an optional
   extra (section 8) and is started explicitly (section 6).
4. **Default to `hot`, keep `restart` host-owned.** citry never calls
   `sys.exit`. Whether an unhandled change should restart the process is the
   host's decision, expressed through the primitive's return value and a
   host-provided restart callback (section 7).
5. **Started explicitly, never auto-started.** Watching is a development
   concern. It is not a frozen constructor flag and not a forced built-in
   extension (section 6 explains why). You turn it on with a CLI command, a
   one-line host helper, or an explicit `watch()` call.
6. **Browser refresh is out of scope here.** No client live-reload channel
   exists today, and pushing a page refresh needs net-new design (a dev-only
   WebSocket or SSE endpoint plus an injected script). It is tracked in
   [#9](https://github.com/citry-dev/citry/issues/9). Section 9 records the
   seam it would build on.
7. **Extras are namespaced** (`watcher-<backend>`), so the optional-dependency
   namespace stays collision-free and leaves room for extension extras
   (`ext-<name>`). Section 8 and
   [`codebase.md`](../codebase.md) ("Runtime optional-dependency extras").

---

## 3. The gap: what sits between a file change and the seam

Three pieces are missing between an on-disk change and the existing seam:

1. **An invalidation primitive** that does the seam dance for one path: resolve,
   `get_components_for_file`, then `reset_template()` + `reset_files()` on each.
   Today a caller would inline it, the way django-components' handler does.
2. **A watcher** for hosts that do not already run one. Django gets file events
   from its own dev server; FastAPI, Flask, and standalone scripts do not.
3. **Host wiring** to start and stop the watcher and to choose hot vs restart.

The design is four layers; only the bottom two are required, and only the very
bottom one ships in the core package.

---

## 4. Layer 0: the invalidation primitive (core, no new dependency)

A small public method on `Citry`, the one host-neutral call everything else
goes through:

```python
def invalidate_file(self, path: str | Path) -> list[type[Component]]:
    """
    Drop cached template/JS/CSS for every component that loaded an asset from
    ``path``, so the next render re-reads it from disk. Returns the classes it
    reset; an empty list means the file backs no loaded component (a host can
    read that as "not mine", e.g. fall through to a restart).
    """
    classes = self.get_components_for_file(path)   # locks the index internally
    for cls in classes:
        cls.reset_template()
        cls.reset_files()
    return classes
```

Notes:

- **Both resets, always.** A file backs only one asset kind, but the watcher
  cannot cheaply tell which, and each reset is a no-op when its cache is unset
  ([`assets.py:289-322`](../../packages/py/citry/citry/assets.py#L289)). Calling
  both is the simplest correct behaviour, matching the django-components handler.
- **Returns the classes, not `None`.** This is what lets a caller implement the
  hot-vs-restart decision (section 7): empty means "unknown file, restart if you
  want"; non-empty means "handled in place".
- **Lives on `Citry`, not in an extension.** It is the reusable seam glue, it is
  pure Python with no watcher dependency, and the Django path (section 6) must
  call it with no watcher installed.
- **Subclasses are covered.** `get_components_for_file` returns every class
  registered against the file, parent and subclasses, so iterating and resetting
  each handles inheritance (subclass asset caches are independent, see
  [`asset_loading.md`](asset_loading.md) section 11). Always go through the file
  index, never reset a single parent and expect children to follow.

A companion `invalidate_all()` (reset every registered component's template and
files without wiping the registry) is a possible convenience for the "something
changed that I cannot map to a path" case. It is lighter than `Citry.clear()`,
which also re-arms autodiscovery ([`citry.py:485-496`](../../packages/py/citry/citry/citry.py#L485)).
Left as an open question (section 11) rather than built speculatively.

### Thread-safety: a lock on the reverse index

The reverse index had no lock: `get_components_for_file` rewrites
`_file_index[key]` with the pruned list while the render path may call
`_register_component_file` on the same key
([`citry.py:455-483`](../../packages/py/citry/citry/citry.py#L455)). A watcher
running on its own thread (the threaded WSGI and Django cases) races the request
threads. The fix is one `threading.Lock` on the `Citry` instance (`_index_lock`),
taken inside `get_components_for_file` and `_register_component_file`; so
`invalidate_file` just calls the already-locked lookup and resets outside the
lock (the resets touch only per-class caches, not the index). The downstream
cascades are already safe: the const-body cache is `RLock`-guarded
([`constness.py:361-366`](../../packages/py/citry/citry/constness.py#L361)). In a
pure-async host there is no race, but the lock makes the primitive correct under
every host.

---

## 5. Layer 1: the pluggable watcher (optional, `citry.reload`)

A new module `citry/reload.py`. Its watcher library is imported lazily inside
the module (the same pattern the contrib adapters and the docs-site CLI already
use, [`docs_site/cli.py:53`](../../docs_site/cli.py#L53)), so plain
`import citry` never needs it.

### 5.1 The `FileWatcher` protocol (the "bring your own" seam)

```python
class FileWatcher(Protocol):
    """A source of file-change events. ``run`` blocks, calling ``on_change``
    with a batch of changed paths for each event, until ``stop`` is called."""

    def run(self, roots: list[Path], on_change: Callable[[set[Path]], None]) -> None: ...
    def stop(self) -> None: ...
```

Any of "manual", "third-party", and "host-provided" satisfies this one
interface:

- `WatchfilesWatcher` (default): wraps `watchfiles.watch` / `awatch`. Native
  inotify/FSEvents/ReadDirectoryChangesW, with `force_polling` for network and
  Docker mounts.
- `PollingWatcher` (fallback, no extra): a stdlib `os.stat` mtime loop, the same
  approach as Django's `StatReloader`. Always available, documented as the slow
  path.
- `WatchdogWatcher` (optional): wraps `watchdog` for users already on it.
- A host adapter that does not watch at all but forwards events the host's own
  reloader already produces (section 6, Django).

### 5.2 The `watch` orchestrator

```python
def watch(
    engine: Citry,
    *,
    roots: list[Path] | None = None,      # defaults to engine.settings.dirs
    watcher: FileWatcher | None = None,   # defaults to watchfiles, else polling
    on_reload: Callable[[set[Path], list[type[Component]]], None] | None = None,
) -> WatchHandle:                         # .stop() tears it down
    ...
```

Responsibilities:

- **Debounce.** A single editor save emits several raw events on every platform.
  `watchfiles` batches already; the poller and `watchdog` need an explicit
  coalescing window before invalidating.
- **Resolve to match the index key.** Each changed path is resolved with
  `Path.resolve()` so it matches the `str(Path(path).resolve())` keys exactly.
  Symlinks, macOS case-insensitivity, and relative event paths all cause a miss
  otherwise.
- **Invalidate.** Call `engine.invalidate_file(p)` per changed path.
- **Notify.** Invoke the optional `on_reload(paths, reset_classes)` callback,
  the hook a logger or the future browser-refresh feature
  ([#9](https://github.com/citry-dev/citry/issues/9)) consumes.

### 5.3 Why the lazy index is fine for invalidation

A file that has never been rendered is absent from the index, so
`invalidate_file` is a no-op for it. That is correct: there is nothing cached to
invalidate. The only genuinely "restart-class" events are a brand-new component
file and a Python source edit, both of which the host's own reloader owns
(section 7). Watching `engine.settings.dirs` (rather than only the indexed
paths) means new files still reach the host's restart path.

---

## 6. Layer 2: host entry points

The watcher is started explicitly. The natural place differs per host:

| Host | How it starts | Mechanism |
|---|---|---|
| Standalone / any | `citry watch --app myproj:engine` | new CLI subcommand via `build_cli` + the existing `--app` resolution ([`__main__.py:32`](../../packages/py/citry/citry/__main__.py#L32)) |
| FastAPI / Starlette / ASGI | `reload_lifespan(engine)` started on `lifespan.startup`, stopped on `lifespan.shutdown` | the lifespan path already exists ([`contrib/asgi.py:50`](../../packages/py/citry/citry/contrib/asgi.py#L50)); async `awatch` runs in the loop |
| Django | `citry.contrib.django.enable_hot_reload(engine)` connects to `file_changed` | piggyback Django's reloader, no second watcher; mirrors [`_djc_reference/apps.py:94`](../../packages/py/citry/_djc_reference/apps.py#L94) |
| Flask / WSGI | `citry watch` alongside the dev server, or the host's own reloader | WSGI has no startup hook; the CLI covers it |

The Django path is the important asymmetry: it installs **no** `FileWatcher`. It
registers a `file_changed` receiver that calls `engine.invalidate_file(path)`
and returns `True` (hot) or `None` (restart), exactly the django-components
shape, so Django's existing reloader does the watching and citry only invalidates.

### Why not a constructor argument or a built-in extension

The design docs earmarked the watcher as "likely an extension". On reading the
extension system, a watcher as the primary extension has three problems, so this
design keeps the primitive on `Citry` and the watcher explicit:

- A frozen-`CitrySettings` constructor flag cannot reach the import-time default
  `citry` instance (built before user code runs), and it bakes a dev-only
  concern into the production config surface.
- A built-in extension would force a background watcher onto every engine,
  including production (built-ins cannot be disabled in the first version), and
  `on_extension_created` fires at construction, the wrong time to spawn a thread.
- Extensions have no shutdown hook, so a long-lived watcher thread would leak.

A `ReloadExtension` that you opt into
(`Citry(extensions=[ReloadExtension()])`) is reasonable convenience sugar that
wires the ASGI lifespan, but it is not the primitive and not a built-in. If that
sugar later needs real teardown, adding an `on_extension_destroyed` hook to the
Extension protocol is a cross-language contract change and would go through the
plan-mode and five-language-audit mechanisms; this design avoids it by tying the
watcher's lifetime to the explicit `WatchHandle` and the ASGI lifespan instead.

---

## 7. Hot vs restart policy (host-owned)

citry models the two useful modes but owns neither the watching nor the restart:

- **hot** (default, and usually all you need): invalidate in place, keep the
  process alive. Fast, and it preserves server state.
- **restart**: invalidate, then call a host-provided `request_restart()`
  callback. citry never calls `sys.exit`. For Django this means the receiver
  returns `None` and Django restarts; for `uvicorn --reload` the process reload
  already handles `.py` edits.

The honest division of labour:

- **File-backed asset edits (template, JS, CSS): citry's hot reload.** These are
  what the index tracks and what `reset_template` / `reset_files` clear.
- **New component files and Python logic edits: the host's reloader.** These are
  restart-class. This is why the Django path is a piggyback (you get hot asset
  reload and Django's `.py` restart in one), and why citry's watcher is
  complementary to `uvicorn --reload` rather than a replacement: it gives
  in-process asset reload that is faster than a full respawn and that covers the
  template and asset dirs `--reload` ignores by default.

Multi-worker boundary: an in-process invalidation resets one worker's caches
only. Across workers or processes, the host's restart policy (or a shared-cache
invalidation) covers the rest. Worth stating in user docs so nobody expects
single-process reset to be cluster-wide.

---

## 8. Packaging: the extras naming convention

The watcher backends are optional dependencies, namespaced so the
`citry[...]` namespace stays collision-free and leaves room for other kinds of
optional dependency (extensions). The general convention,
`citry[<category>-<name>]`, is documented in
[`codebase.md`](../codebase.md) ("Runtime optional-dependency extras"). For the
watcher the category is `watcher`:

```toml
# packages/py/citry/pyproject.toml
[project.optional-dependencies]
watcher-watchfiles = ["watchfiles>=1.0"]   # recommended native backend
watcher-watchdog   = ["watchdog>=4.0"]     # alternate native backend
```

- `pip install citry[watcher-watchfiles]` is the recommended install.
- The stdlib `PollingWatcher` needs no extra; plain `citry` can watch (slowly).
- No bare `citry[watcher]` extra: it would reintroduce an unprefixed token and
  read ambiguously as a backend named "watcher". The category prefix is always
  explicit.
- Extension extras follow the sibling convention `ext-<name>` (for example a
  future `citry[ext-storybook]`), which is why the watcher does not claim the
  bare namespace.

Per the repo's mirrored-dependency gotcha, a new pin is added in both the
package `pyproject.toml` and the mirrored root extras, and the name is grepped
across `pyproject.toml` files and CI first. (The mirroring goes away with the uv
workspace conversion, [#8](https://github.com/citry-dev/citry/issues/8).)

---

## 9. What stays out of scope

- **Browser live-reload** (push a page refresh or asset swap to the browser):
  [#9](https://github.com/citry-dev/citry/issues/9). No client channel exists
  today (the client `MutationObserver` only ingests dependency manifests,
  [`client/citry.js`](../../packages/py/citry/citry/extensions/dependencies/client/citry.js)),
  and asset URLs are content-hashed for caching, not live push. The seam it
  would build on already exists: an extension mounts a dev-only SSE or WebSocket
  endpoint via `Extension.urls`, the watcher's `on_reload` callback (section 5)
  is the trigger, and a small injected script reloads on message (`arel` is the
  reference implementation for ASGI hosts). That is its own design.
- **A native `notify` watcher in the Rust core.** Although citry already ships a
  PyO3 extension and `notify` (plus a debouncer crate) would fit, doing so
  duplicates `watchfiles`, adds cross-platform maintenance (event coalescing,
  rename semantics, network-mount quirks `watchfiles` already solved), and
  couples watcher releases to core rebuilds. Reserved as a future option only if
  removing the Python watcher dependency ever becomes a hard requirement.

---

## 10. Cross-binding scope

This is a Python-package feature. It touches no Rust grammar, AST, compiler,
PyO3 surface, or `LangImpl`, so the cross-language contract is unaffected. The
two additive Python pieces (`Citry.invalidate_file` and the `citry.reload`
module) get normal review with tests. The only change that would cross the
contract is the optional `on_extension_destroyed` hook discussed in section 6,
which this design deliberately does not require for the first version.

---

## 11. Open questions

- **`restart` mode surface**: is a first-party `request_restart` callback worth
  shipping for the standalone `citry watch` case, given that the host dev runner
  (`uvicorn --reload`, Django) already restarts on `.py` edits?
- **Naming** (decided): the module is `citry.reload`, the primitive is
  `Citry.invalidate_file`, the command is `citry watch`. Open to revisiting
  before the API is considered stable.
- **Default `roots`**: `engine.settings.dirs` is the obvious default, but should
  the watcher also watch the dirs of py-file-relative assets resolved outside
  `dirs` (section 5 of [`asset_loading.md`](asset_loading.md) covers the lookup
  chain)?

---

## 12. Layout

- `citry/citry.py`: `invalidate_file` and `invalidate_all`, the `_index_lock`,
  and the locked `get_components_for_file` / `_register_component_file`.
- `citry/reload.py`: the `FileWatcher` protocol, `WatchfilesWatcher`,
  `WatchdogWatcher`, `PollingWatcher` (the dependency-free fallback),
  `default_watcher` (watchfiles, then watchdog, then polling), the `watch`
  orchestrator, and `WatchHandle`; the watcher library is imported lazily.
- `citry/commands/watch.py`: the `citry watch` subcommand, added to the root
  command tree in `citry/commands/__init__.py`.
- `citry/contrib/django.py`: `enable_hot_reload(engine)`, the `file_changed`
  receiver (no `FileWatcher`).
- `citry/contrib/asgi.py`: `reload_lifespan(engine)`, a Starlette/FastAPI
  lifespan that runs the watcher for the life of the app.
- `packages/py/citry/pyproject.toml`: the `watcher-watchfiles` and
  `watcher-watchdog` extras (runtime-only; not mirrored into the root, see
  section 8).
