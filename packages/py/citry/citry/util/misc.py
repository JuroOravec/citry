"""Small, dependency-free helpers shared across the citry engine."""

from __future__ import annotations

import re
import sys
from dataclasses import MISSING, fields, is_dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, NamedTuple

from typing_extensions import TypeIs

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import ModuleType


# TypeIs (not TypeGuard) so type checkers also narrow the negative branch:
# "not a generator" rules the generator type out of a union.
def is_generator(obj: Any) -> TypeIs[Generator[Any, Any, Any]]:
    """Check if an object is a generator (anything with a ``send`` method)."""
    return hasattr(obj, "send")


def to_dict(data: Any) -> dict[str, Any]:
    """
    Convert an object to a plain dict.

    Handles ``dict``, ``NamedTuple``, ``dataclass``, and Pydantic model
    instances. This lets callers accept a typed ``Kwargs``/``Slots``/
    ``TemplateData`` instance interchangeably with a plain mapping. Pydantic
    is recognized by its attribute protocol (``model_fields`` for v2,
    ``__fields__`` for v1), not imported, so it stays out of citry's
    dependencies.

    The conversion is shallow on purpose: it does not recurse into nested
    dataclasses/models (unlike ``dataclasses.asdict`` or ``model_dump``),
    since the values are kept as-is for rendering.
    """
    if isinstance(data, dict):
        return data
    if hasattr(data, "_asdict"):  # NamedTuple
        return data._asdict()
    if is_dataclass(data) and not isinstance(data, type):  # dataclass instance
        return {f.name: getattr(data, f.name) for f in fields(data)}

    # Pydantic model instance (v2 `model_fields` first; v1 `__fields__`).
    model_fields = getattr(type(data), "model_fields", None)
    if not isinstance(model_fields, dict):
        model_fields = getattr(type(data), "__fields__", None)
    if isinstance(model_fields, dict):
        return {name: getattr(data, name) for name in model_fields}

    return dict(data)


class FieldSpec(NamedTuple):
    """One declared input field: its name, and whether a value must be given."""

    name: str
    required: bool


def get_fields(cls: Any) -> list[FieldSpec] | None:
    """
    Read the declared fields of a typed-input class (``Kwargs``/``Slots``).

    Returns one ``FieldSpec`` per field, or ``None`` when ``cls`` is not a
    recognized declaration style. Recognized styles, in the order checked:

    - dataclasses (what the Component metaclass produces from plain inner
      classes): required when the field has neither a default nor a default
      factory.
    - Pydantic v2 models, recognized by ``model_fields`` mapping field names
      to infos with ``is_required()``.
    - Pydantic v1 models, recognized by ``__fields__`` mapping field names to
      infos with a ``required`` flag.
    - NamedTuples (``_fields`` / ``_field_defaults``): required when the
      field has no default.

    Pydantic is recognized by its attribute protocol without being imported,
    so it stays out of citry's dependencies; any class following the same
    protocol works.
    """
    if not isinstance(cls, type):
        return None

    if is_dataclass(cls):
        return [FieldSpec(f.name, f.default is MISSING and f.default_factory is MISSING) for f in fields(cls)]

    # Pydantic v2. Checked before v1: v2 classes also expose a deprecated
    # `__fields__` alias, and reading it would warn.
    model_fields = getattr(cls, "model_fields", None)
    if isinstance(model_fields, dict):
        return [FieldSpec(name, bool(info.is_required())) for name, info in model_fields.items()]

    # Pydantic v1.
    v1_fields = getattr(cls, "__fields__", None)
    if isinstance(v1_fields, dict):
        return [FieldSpec(name, bool(getattr(info, "required", False))) for name, info in v1_fields.items()]

    # NamedTuple.
    if issubclass(cls, tuple) and hasattr(cls, "_fields"):
        defaults: dict[str, Any] = getattr(cls, "_field_defaults", {})
        return [FieldSpec(name, name not in defaults) for name in cls._fields]

    return None


def get_module_info(cls_or_fn: type | Any) -> tuple[ModuleType | None, str | None, str | None]:
    """
    Return the module, module name, and module file path where a class or
    function is defined.

    Any of the three may be ``None``: a class defined in the REPL or via
    ``exec`` has no module file, and a synthetic class may have no module at
    all. Callers treat a missing file path as "no module directory" and skip
    module-relative file resolution.
    """
    module_name: str | None = getattr(cls_or_fn, "__module__", None)

    module: ModuleType | None = None
    if module_name:
        if module_name in sys.modules:
            module = sys.modules[module_name]
        else:
            try:
                module = import_module(module_name)
            except Exception:  # noqa: BLE001 - any import failure means "no module info"
                module = None

    module_file_path: str | None = getattr(module, "__file__", None) if module else None

    return module, module_name, module_file_path


# A string is a glob if it contains at least one of `?`, `*`, or `[`.
_GLOB_RE = re.compile(r"[?*[]")


def is_glob(filepath: str) -> bool:
    """Return whether ``filepath`` contains glob characters (``?``, ``*``, ``[``)."""
    return _GLOB_RE.search(filepath) is not None


def snake_to_pascal(name: str) -> str:
    """
    Convert a snake_case name to PascalCase.

    ``my_extension`` -> ``MyExtension``. Used to derive an extension's
    ``class_name`` (the nested config class users define on a component) from
    its ``name``.
    """
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))
