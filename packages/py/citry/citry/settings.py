"""
The Citry settings schema.

``CitrySettings`` is the typed, immutable configuration for a ``Citry`` instance.
It starts small and grows field-by-field as the engine does. Unknown settings
are rejected: ``Citry`` accepts only the fields defined here.

See ``docs/design/extensions.md`` section 5.2 for the rationale (a real schema
object, not a loose dict).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from citry.cache import CitryCache
    from citry.extension import Extension


@dataclass(frozen=True, slots=True)
class CitrySettings:
    """
    Immutable settings for a ``Citry`` instance.

    Attributes:
        extensions: The extension spec (classes, instances, or ``"path.Class"``
            import strings) the instance's ``ExtensionManager`` builds from.
            Stored as an immutable tuple; extensions are fixed at construction.
        extensions_defaults: Per-extension global default config, keyed by
            extension name. Merged between an extension's factory defaults and a
            component's own nested config class (see the extension system's
            three-level config precedence).
        dirs: Directories searched when resolving a component's asset files
            (``template_file``, ``js_file``, ``css_file``, and ``Dependencies``
            entries), after the directory of the component's own ``.py`` file.
            Entries must be absolute paths; ``Citry.__init__`` validates them.
        cache: The cache backend spec (a :class:`citry.cache.CitryCache`
            object or a ``"path.to.Cache"`` import string). ``None`` gives the
            instance its own in-memory cache. The live backend built from this
            spec is ``Citry.cache``.
        sandbox_expressions: Whether template expressions (``{{ ... }}`` and
            dynamic ``c-*`` attributes) are evaluated in the security sandbox.
            On by default. Turning it off evaluates expressions as plain Python,
            which is faster but removes security guardrails.
            Only do so when every template comes from a trusted source.
        autodiscover: Whether to import the component modules under ``dirs`` the
            first time a component is looked up, so their classes register
            themselves without being imported by hand. On by default; a no-op
            when no ``dirs`` are set (so the default instance does nothing). The
            directories must be importable (on ``sys.path``/``PYTHONPATH``). See
            ``Citry.autodiscover`` and ``citry.autodiscovery``.
        template_globals: Variables exposed to every component's template
            without being returned from each ``template_data()``. They are
            merged into every component's template variables on render, so a
            template can reference one directly (``{{ site_name }}``). A
            component's own ``template_data`` wins when it returns a key of the
            same name, so globals act as defaults. This field is the
            construction-time seed; the live, mutable copy is
            ``Citry.template_globals``, which is how you add or change a global
            after the instance exists (including the default instance, created
            at import before your code runs).
        id_generator: A function returning the per-render id stamped on each
            component instance (``component.id``, which drives the
            ``data-cid-<id>`` markers that scope a component's CSS and JS on the
            page). Given as a callable or a ``"path.to.func"`` import string; a
            class is called once to build the generator, which suits a stateful
            one (e.g. a counter). ``None`` uses the built-in generator. Override
            it for stable ids in snapshot tests. The generator must return ids
            that are unique among the components on one page. This does not touch
            ``class_id``, which stays a stable hash of the component's import
            path.

    """

    extensions: tuple[type[Extension] | Extension | str, ...] = ()
    extensions_defaults: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    dirs: tuple[Path, ...] = ()
    cache: CitryCache | str | None = None
    sandbox_expressions: bool = True
    autodiscover: bool = True
    id_generator: Callable[[], str] | str | None = None
    template_globals: Mapping[str, Any] = field(default_factory=dict)
