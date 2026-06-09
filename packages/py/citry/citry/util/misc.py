"""Small, dependency-free helpers shared across the citry engine."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any


def to_dict(data: Any) -> dict[str, Any]:
    """
    Convert an object to a plain dict.

    Handles ``dict``, ``NamedTuple``, and ``dataclass`` instances. This lets
    callers accept a typed ``Kwargs``/``Slots`` instance (a dataclass or
    NamedTuple) interchangeably with a plain mapping.

    The dataclass conversion is shallow: it does not recurse into nested
    dataclasses (unlike ``dataclasses.asdict``), since the values are kept
    as-is for rendering.
    """
    if isinstance(data, dict):
        return data
    if hasattr(data, "_asdict"):  # NamedTuple
        return data._asdict()
    if is_dataclass(data) and not isinstance(data, type):  # dataclass instance
        return {f.name: getattr(data, f.name) for f in fields(data)}

    return dict(data)


def snake_to_pascal(name: str) -> str:
    """
    Convert a snake_case name to PascalCase.

    ``my_extension`` -> ``MyExtension``. Used to derive an extension's
    ``class_name`` (the nested config class users define on a component) from
    its ``name``.
    """
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))
