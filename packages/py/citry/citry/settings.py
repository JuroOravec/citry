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
    from collections.abc import Mapping

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

    """

    extensions: tuple[type[Extension] | Extension | str, ...] = ()
    extensions_defaults: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
