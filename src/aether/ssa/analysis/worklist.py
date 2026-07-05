from __future__ import annotations

from collections import deque
from collections.abc import Hashable
from typing import Generic, TypeVar


T = TypeVar("T", bound=Hashable)


class Worklist(Generic[T]):
    """FIFO worklist with duplicate suppression for iterative analyses."""

    def __init__(self) -> None:
        self._items: deque[T] = deque()
        self._queued: set[T] = set()

    def push(self, item: T) -> None:
        if item in self._queued:
            return
        self._items.append(item)
        self._queued.add(item)

    def pop(self) -> T:
        item = self._items.popleft()
        self._queued.remove(item)
        return item

    def empty(self) -> bool:
        return not self._items

    def clear(self) -> None:
        self._items.clear()
        self._queued.clear()
