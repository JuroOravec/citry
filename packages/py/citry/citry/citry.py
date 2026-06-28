"""
The Citry global instance - scopes all component state.

A Citry instance owns a component registry, settings, and transient
rendering state. All Component classes are assigned to a Citry instance
(either explicitly via ``Component.citry = my_citry`` or implicitly to
the default instance).

Example:
    Using the default instance (most common)::

        from citry import Component

        class MyTable(Component):
            template = "<table>...</table>"

    Using a custom instance::

        from citry import Citry, Component

        my_citry = Citry()

        class MyTable(Component):
            citry = my_citry
            template = "<table>...</table>"

    Isolated instances for testing::

        def test_my_component():
            test_citry = Citry()
            # Components registered here don't leak to other tests
            class MyTable(Component):
                citry = test_citry
                template = "..."

"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary, ref

from citry.autodiscovery import import_component_modules
from citry.cache import CitryCache, InMemoryCache
from citry.component_registry import ComponentRegistry
from citry.constness import ConstBodyCache
from citry.extension import ExtensionManager
from citry.settings import CitrySettings
from citry.tag_rules import build_tag_rules

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from weakref import ReferenceType

    from citry.component import Component
    from citry.extension import Extension, ExtensionCommand
    from citry.util.routing import URLRoute
    from citry_core.template_parser import TagRules


class Citry:
    """
    Global instance that scopes all component state.

    A Citry instance owns:
    - A ``registry`` (``ComponentRegistry``) mapping names to classes
    - Settings (to be expanded as the engine grows)
    - Transient rendering state

    All Component classes are assigned to a Citry instance at class
    definition time. If no instance is specified, the default instance
    is used.

    Benefits over module-level globals:
    - All transient state has a maximum lifetime bound to the Citry
      instance. Deleting the instance cleans up everything.
    - Tests can use isolated instances for clean state.
    - Multiple independent component trees can coexist.
    """

    def __init__(
        self,
        extensions: Sequence[type[Extension] | Extension | str] = (),
        extensions_defaults: Mapping[str, Mapping[str, Any]] | None = None,
        dirs: Sequence[str | Path] = (),
        cache: CitryCache | str | None = None,
        sandbox_expressions: bool = True,
        autodiscover: bool = True,
        id_generator: Callable[[], str] | str | None = None,
    ) -> None:
        # Asset search dirs must be absolute (same contract as DJC's
        # COMPONENTS.dirs); relative-to-py-file resolution needs no dirs at all.
        dir_paths = tuple(Path(d) for d in dirs)
        for dir_path in dir_paths:
            if not dir_path.is_absolute():
                msg = f"Citry dirs must be absolute paths, got {str(dir_path)!r}"
                raise ValueError(msg)

        self.settings = CitrySettings(
            extensions=tuple(extensions),
            extensions_defaults=dict(extensions_defaults) if extensions_defaults is not None else {},
            dirs=dir_paths,
            cache=cache,
            sandbox_expressions=sandbox_expressions,
            autodiscover=autodiscover,
            id_generator=id_generator,
        )

        # The cache backend (docs/design/dependencies.md section 10): derived
        # content such as the dependencies extension's processed JS/CSS lives
        # here. Built from the settings spec; defaults to a per-instance
        # in-memory cache.
        self.cache: CitryCache = self._build_cache(cache)
        # The override for the per-render component id, resolved from the
        # settings spec to a live callable. None means "use the built-in
        # generator" (the fallback lives at the mint site in component.py).
        self.id_generator: Callable[[], str] | None = self._resolve_id_generator(id_generator)
        # The registry creates the built-in components (<c-provide>, ...) on
        # its first lookup, through this factory, so they exist in every
        # Citry instance. See ComponentRegistry._ensure_builtins.
        self.registry = ComponentRegistry(builtins_factory=self._create_builtin_components)

        # Autodiscovery (see autodiscover()). When the autodiscover setting is
        # on, the component modules under settings.dirs are imported the first
        # time a component is looked up, so their classes register themselves.
        # _discovered latches that the scan has run for the current registry;
        # clear() resets it so the next lookup rebuilds the registry (the scan
        # re-registers components from already-imported modules, see
        # citry.autodiscovery). _discovering guards the case where registering a
        # discovered component routes back through this instance (the guard makes
        # that re-entrant call a no-op, not a nested scan).
        self._discovered: bool = False
        self._discovering: bool = False

        # When a component is rendered and some of its template data is
        # wrapped in `Const()` ("this value is the same on every render"),
        # the parts of the template that depend only on those values are
        # computed once and stored here, so later renders reuse them instead
        # of re-computing. One entry per component class and combination of
        # Const values; old entries are dropped when the cache is full.
        # See citry/constness.py.
        self._const_body_cache = ConstBodyCache()

        # Parse-time validation rules derived from the registered components'
        # Kwargs/Slots declarations (see citry/tag_rules.py). Built on first
        # template parse; invalidated whenever the registry changes.
        self._tag_rules_cache: dict[str, TagRules] | None = None

        # File-to-component reverse index: absolute file path -> weakrefs to the
        # component classes whose assets resolved to that file. The hot-reload
        # seam: a watcher (or test) asks get_components_for_file() which classes
        # to reset when a file changes. See docs/design/asset_loading.md
        # section 8.
        self._file_index: dict[str, list[ReferenceType[type[Component]]]] = {}

        # class_id -> component class reverse index, maintained at registration.
        # This is how the script-serving endpoint finds the class a cached
        # JS/CSS script belongs to (docs/design/dependencies.md section 4.1).
        # Weak values, so unregistered classes can be garbage-collected.
        self._classes_by_id: WeakValueDictionary[str, type[Component]] = WeakValueDictionary()

        # Where this instance's routes are mounted in the host web app, e.g.
        # "/citry". Recorded by the web-integration adapters' mount() call
        # (docs/design/dependencies.md section 9.3); None means no
        # integration is mounted, and URL building raises with guidance.
        self._mounted_prefix: str | None = None

        # The extension/hook system, scoped to this Citry instance (DJC #1413).
        # Extensions are present from construction, so hooks fire immediately.
        self.extensions = ExtensionManager(self, self.settings.extensions)
        self.extensions.on_extension_created()

    def __repr__(self) -> str:
        return f"Citry(components={len(self.registry)})"

    # Convenience delegations so users can write citry.get("card")
    # instead of citry.registry.get("card").

    def register(self, comp_cls: type[Component], name: str | None = None) -> None:
        """
        Register a component. See ``ComponentRegistry.register``.

        Fires ``on_component_registered`` once per call, after the registry
        accepts the class.
        """
        self.registry.register(comp_cls, name)
        self._classes_by_id[comp_cls.class_id] = comp_cls
        self._tag_rules_cache = None
        registered_name = name or getattr(comp_cls, "name", None) or comp_cls.__name__
        self.extensions.on_component_registered(registered_name, comp_cls)

    def unregister(self, comp_cls_or_name: type[Component] | str) -> None:
        """
        Unregister a component. See ``ComponentRegistry.unregister``.

        Fires ``on_component_unregistered`` once per call, after the registry
        removes the class.
        """
        # Resolve the class (and a representative name) before removal, so the
        # hook context is populated whether called by class or by name.
        if isinstance(comp_cls_or_name, str):
            comp_cls = self.registry.get(comp_cls_or_name)
            removed_name = comp_cls_or_name
        else:
            comp_cls = comp_cls_or_name
            removed_name = getattr(comp_cls, "name", None) or comp_cls.__name__
        self.registry.unregister(comp_cls_or_name)
        self._tag_rules_cache = None
        self.extensions.on_component_unregistered(removed_name, comp_cls)

    def get(self, name: str) -> type[Component]:
        """Look up a component by name. See ``ComponentRegistry.get``."""
        self._ensure_discovered()
        return self.registry.get(name)

    def has(self, name: str) -> bool:
        """Check if a component is registered. See ``ComponentRegistry.has``."""
        self._ensure_discovered()
        return self.registry.has(name)

    @property
    def components(self) -> dict[str, type[Component]]:
        """All registered components as a name -> class mapping."""
        self._ensure_discovered()
        return self.registry.all()

    def autodiscover(self, dirs: Sequence[str | Path] | None = None) -> list[str]:
        """
        Import this instance's component modules so their classes register.

        With no argument, imports every component module under the instance's
        ``dirs`` - the same scan the ``autodiscover`` setting performs
        automatically on first use - and marks that automatic scan done, so it
        will not run again. Pass ``dirs`` to import an extra set of directories
        on demand without affecting the automatic scan.

        The directories must be importable: each one (or a parent of it) is on
        ``sys.path``/``PYTHONPATH``, which is how a component file is mapped to
        the import name Python uses for it. A directory that holds component
        modules but is not importable raises ``ValueError``.

        Returns the dotted import paths of the modules that were imported. Safe
        to call more than once: an already-imported module has its components
        re-registered directly, so a call after ``clear()`` rebuilds the
        registry and a call that changes nothing is a no-op.
        """
        if dirs is None:
            self._discovered = True
            search_dirs: tuple[Path, ...] = self.settings.dirs
        else:
            search_dirs = tuple(Path(d) for d in dirs)
        return self._run_discovery(search_dirs)

    @property
    def urls(self) -> tuple[URLRoute, ...]:
        """
        This instance's HTTP route table (framework-neutral ``URLRoute``s).

        The web-integration adapters (``citry.contrib.asgi`` and friends)
        mount these into the host application; the routes serve cached
        component JS/CSS, the client runtime, and extension endpoints.
        """
        return self.extensions.urls

    @property
    def commands(self) -> dict[str, tuple[type[ExtensionCommand], ...]]:
        """
        This instance's CLI commands, keyed by extension name.

        Each registered extension contributes the commands it declares in
        ``Extension.commands``; the ``citry`` command-line tool reaches one as
        ``citry ext run <extension name> <command name>``. See
        ``ExtensionManager.commands`` for ordering and the uniqueness guarantee.
        """
        return self.extensions.commands

    @property
    def mounted_prefix(self) -> str | None:
        """Where this instance's routes are mounted (e.g. ``"/citry"``), or ``None`` when nothing is mounted."""
        return self._mounted_prefix

    def set_mounted_prefix(self, prefix: str) -> None:
        """
        Record where this instance's routes are mounted in the host app.

        The adapters' ``mount()`` call this; call it directly only in a
        process that builds URLs without mounting the routes itself (for
        example a worker that renders fragments served by another process).
        ``prefix`` must start with ``/``; a trailing ``/`` is dropped.
        """
        if not prefix.startswith("/"):
            msg = f"Mount prefix must start with '/', got {prefix!r}"
            raise ValueError(msg)
        self._mounted_prefix = prefix.rstrip("/")

    def build_url(self, path: str) -> str:
        """
        An absolute URL path for one of this instance's routes.

        ``path`` is the route's full path (no leading slash), e.g.
        ``"cache/Table_a1b2c3.js"``. Raises ``RuntimeError`` when no web
        integration is mounted, since the URL would point nowhere.
        """
        if self._mounted_prefix is None:
            msg = (
                "Cannot build a citry URL: no web integration is mounted."
                " Mount one (e.g. citry.contrib.fastapi.mount(app, citry_instance))"
                " or call set_mounted_prefix() in processes that only build URLs."
            )
            raise RuntimeError(msg)
        return f"{self._mounted_prefix}/{path}"

    def get_component_by_class_id(self, class_id: str) -> type[Component]:
        """
        Look up a registered component class by its ``class_id``.

        ``class_id`` is the stable identifier (``MyComp.class_id``) used in
        cache keys and script URLs. Raises ``KeyError`` when no registered
        class has that id.
        """
        comp_cls = self._classes_by_id.get(class_id)
        if comp_cls is None:
            msg = f"No component class with class_id {class_id!r} is registered with this Citry instance"
            raise KeyError(msg)
        return comp_cls

    @staticmethod
    def _build_cache(spec: CitryCache | str | None) -> CitryCache:
        """
        Build the live cache backend from the settings spec.

        ``None`` gives a fresh in-memory cache. An import string is resolved
        like extension specs are: ``"path.to.Cache"`` names either a class
        (instantiated with no arguments) or a ready-made backend object.
        """
        if spec is None:
            return InMemoryCache()
        if isinstance(spec, str):
            module_path, _, attr_name = spec.rpartition(".")
            resolved = getattr(import_module(module_path), attr_name)
            spec = resolved() if isinstance(resolved, type) else resolved
        if not isinstance(spec, CitryCache):
            msg = (
                f"Citry cache must provide get/set/delete/has (see citry.cache.CitryCache), got {type(spec).__name__}"
            )
            raise TypeError(msg)
        return spec

    @staticmethod
    def _resolve_id_generator(spec: Callable[[], str] | str | None) -> Callable[[], str] | None:
        """
        Build the render-id generator override from the settings spec.

        ``None`` means no override (the built-in generator is used). An import
        string is resolved like the cache spec: ``"path.to.gen"`` names either a
        callable or a class, and a class is instantiated once into the generator
        (so a stateful one, such as a counter, keeps its state per instance).
        The result must be callable.
        """
        if spec is None:
            return None
        if isinstance(spec, str):
            module_path, _, attr_name = spec.rpartition(".")
            spec = getattr(import_module(module_path), attr_name)
        if isinstance(spec, type):
            spec = spec()
        if not callable(spec):
            msg = f"Citry id_generator must be callable (a function returning a str), got {type(spec).__name__}"
            raise TypeError(msg)
        return spec

    def _create_builtin_components(self) -> None:
        """
        Create this instance's built-in components (the registry's factory).

        Called by the registry on its first component lookup (see
        ``ComponentRegistry._ensure_builtins``). Defining the built-in
        classes registers them through the normal metaclass path.
        """
        # Imported here, not at module load: component.py (which the built-in
        # components are made of) imports this module.
        from citry.components import make_builtin_components  # noqa: PLC0415

        make_builtin_components(self)

    def _ensure_discovered(self) -> None:
        """
        Import the component modules under ``settings.dirs`` once, on first use.

        Driven by the ``autodiscover`` setting. Runs at the first component
        lookup (``get``/``has``/``components``) or template compile
        (``_tag_rules``), so every component defined under ``dirs`` is registered
        before any template that references it is parsed. A no-op when
        autodiscovery is off or no ``dirs`` are set. See ``Citry.autodiscover``.
        """
        if self._discovered or self._discovering or not self.settings.autodiscover:
            return
        # Latch before importing (as the registry's _ensure_builtins does): a
        # discovered module registers components, which routes back through this
        # instance; the latch makes that re-entrant call short-circuit here
        # instead of starting a second scan.
        self._discovered = True
        if self.settings.dirs:
            self._run_discovery(self.settings.dirs)

    def _run_discovery(self, dirs: tuple[Path, ...]) -> list[str]:
        """
        Scan ``dirs`` and import their component modules, under the re-entrancy
        guard. Returns the imported module names. The guard makes a lookup that
        fires while a discovered component is registering short-circuit (see
        ``_ensure_discovered``) rather than start a nested scan.
        """
        self._discovering = True
        try:
            return import_component_modules(dirs)
        finally:
            self._discovering = False

    def _tag_rules(self) -> dict[str, TagRules]:
        """
        Parse-time validation rules for templates parsed under this instance.

        Derived from the registered components' ``Kwargs``/``Slots``
        declarations (see ``citry/tag_rules.py``), so a template using a
        declared component fails at parse time on unknown or missing
        kwargs/fills. Cached; the cache resets whenever a component is
        registered or unregistered.
        """
        # Discovery must finish before the rules are built: build_tag_rules
        # reads the whole registry, so every discovered component has to be
        # registered first or the rules would be built from a partial set.
        self._ensure_discovered()
        if self._tag_rules_cache is None:
            self._tag_rules_cache = build_tag_rules(self)
        return self._tag_rules_cache

    def _evict_component_cache(self, comp_cls: type[Component]) -> None:
        """Forget one component class's cached template work (see ``_const_body_cache``)."""
        self._const_body_cache.evict_component(comp_cls)

    # ----- Asset file index (hot-reload seam) -----

    def _register_component_file(self, path: Path, comp_cls: type[Component]) -> None:
        """Record that ``comp_cls`` loaded an asset from ``path``."""
        key = str(Path(path).resolve())
        refs = self._file_index.setdefault(key, [])
        if not any(existing() is comp_cls for existing in refs):
            refs.append(ref(comp_cls))

    def get_components_for_file(self, path: str | Path) -> list[type[Component]]:
        """
        The component classes whose assets resolved to ``path``.

        This is what a hot-reload handler drives invalidation through: when a
        file changes, call ``reset_template()`` / ``reset_files()`` on each
        returned class. Dead weakrefs are pruned on read.
        """
        key = str(Path(path).resolve())
        refs = self._file_index.get(key)
        if not refs:
            return []

        alive: list[type[Component]] = []
        alive_refs: list[ReferenceType[type[Component]]] = []
        for comp_ref in refs:
            comp_cls = comp_ref()
            if comp_cls is not None:
                alive.append(comp_cls)
                alive_refs.append(comp_ref)
        self._file_index[key] = alive_refs
        return alive

    def clear(self) -> None:
        """Clear all state: registered components, caches, etc."""
        self.registry.clear()
        self._const_body_cache.clear()
        self._file_index.clear()
        self._classes_by_id.clear()
        self._tag_rules_cache = None
        # Re-arm autodiscovery: the next lookup re-runs the dirs scan and
        # rebuilds the registry. Even though the modules are already imported,
        # the scan re-registers their components (see citry.autodiscovery), so
        # the rebuilt registry matches the one clear() just wiped.
        self._discovered = False
        # The protocol does not require clear() (a shared backend may not want
        # a full wipe); the built-in in-memory cache supports it.
        cache_clear = getattr(self.cache, "clear", None)
        if callable(cache_clear):
            cache_clear()


# The default Citry instance, used when Component.citry is not set.
# Created eagerly at import time. If Citry.__init__ grows dependencies
# that import from this package, switch to __getattr__-based laziness.
citry = Citry()
