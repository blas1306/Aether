from __future__ import annotations

from dataclasses import dataclass


MAX_STRONG_COUNT = (1 << 63) - 1


@dataclass
class ClassDebugCounters:
    objects_allocated: int = 0
    objects_freed: int = 0
    fields_destroyed: int = 0


_DEBUG_COUNTERS = ClassDebugCounters()


def class_debug_counters() -> ClassDebugCounters:
    """Return an instrumentation snapshot; this is not a source-level API."""

    return ClassDebugCounters(**vars(_DEBUG_COUNTERS))


def reset_class_debug_counters() -> None:
    _DEBUG_COUNTERS.objects_allocated = 0
    _DEBUG_COUNTERS.objects_freed = 0
    _DEBUG_COUNTERS.fields_destroyed = 0


class NativeClassObject:
    """Interpreter mirror of a native class handle and its inline payload."""

    __slots__ = ("type_id", "strong_count", "alive", "fields", "initialized")

    def __init__(self, type_id: str, field_count: int = 0) -> None:
        if not type_id:
            raise ValueError("Aether class type identity must not be empty")
        if field_count < 0:
            raise ValueError("Aether class field count must not be negative")
        self.type_id = type_id
        self.strong_count = 1
        self.alive = True
        self.fields = [None] * field_count
        self.initialized: set[int] = set()
        _DEBUG_COUNTERS.objects_allocated += 1

    def get_field(self, index: int) -> object:
        self._require_live()
        if index not in self.initialized:
            raise RuntimeError("Aether class field read before initialization")
        return self.fields[index]

    def set_field(self, index: int, value: object, *, initialize: bool) -> None:
        from .collection_value import copy_init_value, destroy_value

        self._require_live()
        if not 0 <= index < len(self.fields):
            raise IndexError("Aether class field index out of bounds")
        if initialize and index in self.initialized:
            raise RuntimeError("Aether class field initialized more than once")
        if not initialize and index not in self.initialized:
            raise RuntimeError("Aether class field assigned before initialization")

        # Protect the incoming value before releasing the old slot.  This is
        # what makes `object.field = object.field` safe for owning values.
        copied = copy_init_value(value)
        old = self.fields[index] if index in self.initialized else None
        self.fields[index] = copied
        self.initialized.add(index)
        if old is not None:
            destroy_value(old)

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
            from .collection_value import destroy_value

            for index in sorted(self.initialized, reverse=True):
                destroy_value(self.fields[index])
                self.fields[index] = None
                _DEBUG_COUNTERS.fields_destroyed += 1
            self.initialized.clear()
            self.alive = False
            _DEBUG_COUNTERS.objects_freed += 1

    def _require_live(self) -> None:
        if not self.alive:
            raise RuntimeError("Aether class object was already released")
