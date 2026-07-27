from __future__ import annotations

from dataclasses import dataclass


MAX_STRONG_COUNT = (1 << 63) - 1


@dataclass
class ClassDebugCounters:
    objects_allocated: int = 0
    objects_freed: int = 0


_DEBUG_COUNTERS = ClassDebugCounters()


def class_debug_counters() -> ClassDebugCounters:
    """Return an instrumentation snapshot; this is not a source-level API."""

    return ClassDebugCounters(**vars(_DEBUG_COUNTERS))


def reset_class_debug_counters() -> None:
    _DEBUG_COUNTERS.objects_allocated = 0
    _DEBUG_COUNTERS.objects_freed = 0


class NativeClassObject:
    """Interpreter mirror of the Phase 5.3A native class handle.

    The object intentionally has no source-visible payload yet.  Its identity
    and intrusive strong count model the same ownership contract as the LLVM
    object header, which lets IR lifecycle tests prove aliasing and exact final
    destruction without enabling constructors, fields, or methods.
    """

    __slots__ = ("type_id", "strong_count", "alive")

    def __init__(self, type_id: str) -> None:
        if not type_id:
            raise ValueError("Aether class type identity must not be empty")
        self.type_id = type_id
        self.strong_count = 1
        self.alive = True
        _DEBUG_COUNTERS.objects_allocated += 1

    def retain(self) -> NativeClassObject:
        self._require_live()
        if self.strong_count >= MAX_STRONG_COUNT:
            raise OverflowError("Aether class reference count overflow")
        self.strong_count += 1
        return self

    def release(self) -> None:
        self._require_live()
        if self.strong_count <= 0:
            raise RuntimeError("Aether class reference count underflow")
        self.strong_count -= 1
        if self.strong_count == 0:
            self.alive = False
            _DEBUG_COUNTERS.objects_freed += 1

    def _require_live(self) -> None:
        if not self.alive:
            raise RuntimeError("Aether class object was already released")

