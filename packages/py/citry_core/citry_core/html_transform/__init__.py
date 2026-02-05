from typing import TypeAlias

from citry_core import _rust

transform_html: TypeAlias = _rust.html_transform.transform_html


__all__ = ["transform_html"]
