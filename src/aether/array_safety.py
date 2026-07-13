from __future__ import annotations

from .list_safety import INT32_MAX


ARRAY_LENGTH_OVERFLOW_MESSAGE = "Aether panic: Array length does not fit in int"


def checked_array_length_to_int(length: int) -> int:
    """Convert the native i64 Array length to the public Aether int safely."""
    if length < 0 or length > INT32_MAX:
        raise OverflowError(ARRAY_LENGTH_OVERFLOW_MESSAGE)
    return length
