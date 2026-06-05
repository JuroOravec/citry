"""
Nanoid-based ID generation.

Based on nanoid implementation from
https://github.com/puyuan/py-nanoid/tree/99e5b478c450f42d713b6111175886dccf16f156/nanoid
"""

from math import ceil, log
from os import urandom


def generate(alphabet: str, size: int) -> str:
    """Generate a random string of given size from the given alphabet."""
    alphabet_len = len(alphabet)

    mask = 1
    if alphabet_len > 1:
        mask = (2 << int(log(alphabet_len - 1) / log(2))) - 1
    step = int(ceil(1.6 * mask * size / alphabet_len))  # noqa: RUF046

    id_str = ""
    while True:
        random_bytes = bytearray(urandom(step))

        for i in range(step):
            random_byte = random_bytes[i] & mask
            if random_byte < alphabet_len and alphabet[random_byte]:
                id_str += alphabet[random_byte]

                if len(id_str) == size:
                    return id_str
