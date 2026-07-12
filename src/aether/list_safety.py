from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar


INT32_MAX = (1 << 31) - 1
UINT64_MAX = (1 << 64) - 1

ALLOCATION_OVERFLOW_MESSAGE = "Aether panic: allocation size overflow"
ALLOCATION_FAILURE_MESSAGE = "Aether panic: memory allocation failed"
LIST_LENGTH_OVERFLOW_MESSAGE = "Aether panic: List length does not fit in int"
LIST_INDEX_OVERFLOW_MESSAGE = "Aether panic: List index does not fit in int"


def checked_i64_multiply(left: int, right: int) -> int:
    """Multiply two allocation-size operands without unsigned i64 wraparound."""
    if left < 0 or right < 0 or left > UINT64_MAX or right > UINT64_MAX:
        raise OverflowError(ALLOCATION_OVERFLOW_MESSAGE)
    if left != 0 and right > UINT64_MAX // left:
        raise OverflowError(ALLOCATION_OVERFLOW_MESSAGE)
    return left * right


T = TypeVar("T")


def checked_allocation(size: int, allocator: Callable[[int], T | None]) -> T | None:
    """Model the native allocation contract with an injectable allocator."""
    if size < 0 or size > UINT64_MAX:
        raise OverflowError(ALLOCATION_OVERFLOW_MESSAGE)
    if size == 0:
        return None
    allocation = allocator(size)
    if allocation is None:
        raise MemoryError(ALLOCATION_FAILURE_MESSAGE)
    return allocation


def checked_list_length_to_int(length: int) -> int:
    if length < 0 or length > INT32_MAX:
        raise OverflowError(LIST_LENGTH_OVERFLOW_MESSAGE)
    return length


def checked_list_index_to_int(index: int) -> int:
    if index == -1:
        return -1
    if index < 0 or index > INT32_MAX:
        raise OverflowError(LIST_INDEX_OVERFLOW_MESSAGE)
    return index
