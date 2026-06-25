"""
Short ids for rendered components (e.g. ``c1A2b3c``).

Every rendered component instance gets one. It scopes the component's CSS and JS
to its own elements on the page (through ``data-cid-<id>`` markers) and is used
as a lookup key by the browser-side code. The id is not a secret; it only has to
be unique among the components on a single rendered page.

An id is generated in two steps:

1. **Pick a number.** We keep a counter that goes 0, 1, 2, ... and start it at a
   random point, chosen once when this module is first loaded. Each id is the
   next number in that sequence. Counting upward means two ids in the same
   process are never equal (so two components on one page never collide), and
   the random starting point means two separate processes do not hand out the
   same sequence of ids.

2. **Turn the number into characters.** Ids are written with 62 possible
   characters (the digits, then lowercase, then uppercase letters). A 6-character
   id is therefore just a number written in base 62 (62 "digits" per position
   instead of the usual 10). Rather than work out one character at a time, we
   build a table of all 62 x 62 two-character pairs up front and split the number
   into three pairs, so producing an id is three quick table lookups.

The result is the same length and about the same chance of a clash as a fully
random id, but much cheaper to produce: one counter step and three lookups
instead of six random draws. See docs/design/performance.md section 8.
"""

from __future__ import annotations

import itertools
import random

from citry.constants import COMP_ID_PREFIX, UID_LENGTH

# The characters an id can be made of: digits, then lowercase, then uppercase.
_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ID_BASE = len(_ID_ALPHABET)  # 62 possible characters per position.

# How many different ids exist: UID_LENGTH characters, each one of 62 choices.
# An id is a number somewhere in 0 .. _ID_SPACE - 1.
_ID_SPACE = _ID_BASE**UID_LENGTH

# A table of every two-character pair, in order, so ``_ID_CHUNK[n]`` is the pair
# for the number n (where 0 <= n < 62 * 62). Looking pairs up is faster than
# building the id one character at a time.
_ID_CHUNK = [_ID_ALPHABET[i // _ID_BASE] + _ID_ALPHABET[i % _ID_BASE] for i in range(_ID_BASE * _ID_BASE)]

# The counter, and the random point it starts from. Both are set once, when the
# module is first imported.
_id_base = random.randrange(_ID_SPACE)  # noqa: S311 (a DOM id, not a secret)
_id_counter = itertools.count()


def gen_id() -> str:
    """Return the next 6-character id (e.g. ``1A2b3c``), unique within the process."""
    # The next number in the sequence, wrapped back to the start if the counter
    # ever runs past the last id.
    value = (_id_base + next(_id_counter)) % _ID_SPACE
    # Split that number into three two-character pairs and look each up. Six
    # characters are exactly three pairs because 62 ** 6 == (62 * 62) ** 3:
    # `low` is the last pair, `mid` the middle, `high` the first.
    value, low = divmod(value, _ID_BASE * _ID_BASE)
    high, mid = divmod(value, _ID_BASE * _ID_BASE)
    return _ID_CHUNK[high] + _ID_CHUNK[mid] + _ID_CHUNK[low]


def gen_render_id() -> str:
    """Return a component render id: the ``c`` prefix plus a generated id (e.g. ``c1A2b3c``)."""
    return COMP_ID_PREFIX + gen_id()
