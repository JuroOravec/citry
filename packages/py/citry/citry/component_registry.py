"""
Component registry - maps component names to component classes.

Each ``Citry`` instance owns a ``ComponentRegistry``. Components are
registered automatically at class definition time (via the metaclass),
or manually via ``citry.registry.register()``.

Name normalization follows Vue's convention: a PascalCase class name
is registered under both the lowercased form (``mycard``) and the
kebab-case form (``my-card``). Lookups are case-insensitive, matching
how the Rust compiler lowercases tag names.

Example::

    from citry import Citry, Component

    c = Citry()

    class MyCard(Component):
        citry = c

    # Both forms work
    assert c.registry.get("mycard") is MyCard
    assert c.registry.get("my-card") is MyCard
    assert c.registry.get("MyCard") is MyCard

"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from citry.component import Component


class AlreadyRegistered(Exception):
    """Raised when registering a component under a name that is already taken."""


class NotRegistered(Exception):
    """Raised when looking up a component name that is not registered."""


def _pascal_to_kebab(name: str) -> str:
    """
    Convert a PascalCase name to kebab-case.

    ``MyCard`` -> ``my-card``, ``HTMLParser`` -> ``html-parser``
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", s)
    return s.lower()


def _normalize_name(name: str) -> str:
    """Normalize a component name for registry lookup (lowercased)."""
    return name.lower()


# Tag names must start with an ASCII letter, then letters, digits,
# hyphens, underscores, or dots. Matches the grammar's html_tag_name
# rule (minus the c- prefix).
_VALID_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9\-_.]*$")


def _validate_component_name(name: str) -> None:
    """Validate that a name is usable as an HTML tag name (after the c- prefix)."""
    if not _VALID_NAME_RE.match(name):
        msg = (
            f"Invalid component name: {name!r}. "
            f"Must start with a letter and contain only "
            f"letters, digits, hyphens, underscores, or dots."
        )
        raise ValueError(msg)


class ComponentRegistry:
    """
    Maps component names to component classes.

    A single component class may be registered under multiple names
    (e.g. ``mycard`` and ``my-card``). The registry maintains a reverse
    map so unregister-by-class is O(1).
    """

    def __init__(self) -> None:
        # name -> component class (all names normalized/lowercased)
        self._name_to_cls: dict[str, type[Component]] = {}
        # class id -> set of registered names (reverse map)
        self._cls_to_names: dict[int, set[str]] = {}

    def register(self, comp_cls: type[Component], name: str | None = None) -> None:
        """
        Register a component class.

        By default, the class name (or ``Component.name`` override) is
        used to derive one or two normalized names:

        - Lowercased: ``MyCard`` -> ``mycard``
        - Kebab-case: ``MyCard`` -> ``my-card`` (if different from lowered)

        If ``name`` is provided explicitly, only that single name is used.

        Re-registering the same class under the same name is a no-op.

        Args:
            comp_cls: The Component subclass to register.
            name: Explicit name. If not given, derived from class name.

        Raises:
            AlreadyRegistered: If the name is taken by a different class.
            ValueError: If the name is not a valid component name.

        """
        if name is not None:
            _validate_component_name(name)
            names = [_normalize_name(name)]
        else:
            raw_name = getattr(comp_cls, "name", None) or comp_cls.__name__
            _validate_component_name(raw_name)
            lowered = _normalize_name(raw_name)
            kebab = _pascal_to_kebab(raw_name)
            names = list(dict.fromkeys([lowered, kebab]))

        cls_id = id(comp_cls)
        for n in names:
            existing = self._name_to_cls.get(n)
            if existing is not None:
                if existing is comp_cls:
                    continue
                raise AlreadyRegistered(
                    f"Cannot register {comp_cls.__name__!r} as {n!r}: "
                    f"already taken by {existing.__name__!r}."
                )
            self._name_to_cls[n] = comp_cls
            if cls_id not in self._cls_to_names:
                self._cls_to_names[cls_id] = set()
            self._cls_to_names[cls_id].add(n)

    def unregister(self, comp_cls_or_name: type[Component] | str) -> None:
        """
        Remove a component from the registry.

        Accepts a class (removes all names for that class) or a single
        name string (removes just that name).

        Raises:
            NotRegistered: If the class or name is not in the registry.

        """
        # Case: unregister by name
        if isinstance(comp_cls_or_name, str):
            name = _normalize_name(comp_cls_or_name)
            if name not in self._name_to_cls:
                raise NotRegistered(f"No component registered as {name!r}.")
            comp_cls = self._name_to_cls.pop(name)
            cls_names = self._cls_to_names.get(id(comp_cls))
            if cls_names is not None:
                cls_names.discard(name)
                if not cls_names:
                    del self._cls_to_names[id(comp_cls)]
            return

        # Case: unregister by class
        comp_cls = comp_cls_or_name
        cls_id = id(comp_cls)
        names_to_remove = self._cls_to_names.pop(cls_id, None)
        if not names_to_remove:
            raise NotRegistered(
                f"Component {comp_cls.__name__!r} is not registered."
            )
        for n in names_to_remove:
            self._name_to_cls.pop(n, None)

    def get(self, name: str) -> type[Component]:
        """
        Look up a component class by name (case-insensitive).

        Raises:
            NotRegistered: If no component is registered under that name.

        """
        normalized = _normalize_name(name)
        if normalized not in self._name_to_cls:
            raise NotRegistered(f"No component registered as {normalized!r}.")
        return self._name_to_cls[normalized]

    def has(self, name: str) -> bool:
        """Check if a component is registered under the given name."""
        return _normalize_name(name) in self._name_to_cls

    def all(self) -> dict[str, type[Component]]:
        """All registered components as a name -> class dict."""
        return dict(self._name_to_cls)

    def clear(self) -> None:
        """Remove all registrations."""
        self._name_to_cls.clear()
        self._cls_to_names.clear()

    def __len__(self) -> int:
        """Number of unique component classes registered."""
        return len(set(id(c) for c in self._name_to_cls.values()))

    def __repr__(self) -> str:
        return f"ComponentRegistry({len(self)} components)"
