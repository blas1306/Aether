from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .string_value import StringValue


MAX_STRONG_COUNT = (1 << 63) - 1


@dataclass
class CollectionDebugCounters:
    objects_allocated: int = 0
    objects_freed: int = 0
    buffers_allocated: int = 0
    buffers_freed: int = 0
    elements_destroyed: int = 0


_DEBUG_COUNTERS = CollectionDebugCounters()


def collection_debug_counters() -> CollectionDebugCounters:
    """Return a snapshot used by runtime tests; this is not an Aether API."""

    return CollectionDebugCounters(**vars(_DEBUG_COUNTERS))


def reset_collection_debug_counters() -> None:
    for name in vars(_DEBUG_COUNTERS):
        setattr(_DEBUG_COUNTERS, name, 0)


class CollectionObject(list[Any]):
    """Interpreter model of a private mutable Array/List RC object.

    Subclassing ``list`` keeps legacy AST helpers working while identity,
    strong ownership and final element destruction are modeled explicitly.
    The public Aether value remains a handle to this object.
    """

    __slots__ = (
        "kind",
        "element_type",
        "strong_count",
        "capacity",
        "alive",
        "freed",
        "unclaimed_owners",
    )

    def __init__(
        self,
        kind: str,
        element_type: object,
        elements: Iterable[Any] = (),
        *,
        capacity: int | None = None,
    ) -> None:
        if kind not in {"Array", "List"}:
            raise ValueError(f"unknown Aether collection kind '{kind}'")
        list.__init__(self)
        self.kind = kind
        self.element_type = element_type
        self.strong_count = 1
        self.unclaimed_owners = 1
        self.capacity = 0
        self.alive = True
        self.freed = False
        _DEBUG_COUNTERS.objects_allocated += 1
        _DEBUG_COUNTERS.buffers_allocated += 1
        try:
            for element in elements:
                list.append(self, copy_init_value(element))
        except BaseException:
            # The destination is never published.  Roll back exactly the live
            # prefix, mirroring native lifecycle order for recoverable hosts.
            for copied in reversed(self):
                destroy_value(copied)
                _DEBUG_COUNTERS.elements_destroyed += 1
            list.clear(self)
            self.strong_count = 0
            self.unclaimed_owners = 0
            self.alive = False
            self.freed = True
            _DEBUG_COUNTERS.buffers_freed += 1
            _DEBUG_COUNTERS.objects_freed += 1
            raise
        self.capacity = len(self) if kind == "Array" else max(len(self), capacity or 0)

    @property
    def size(self) -> int:
        self._require_live()
        return len(self)

    @property
    def buffer(self) -> "CollectionObject":
        self._require_live()
        return self

    def retain(self) -> "CollectionObject":
        self._require_live()
        if self.strong_count >= MAX_STRONG_COUNT:
            raise OverflowError(f"Aether {self.kind} reference count overflow")
        self.strong_count += 1
        return self

    def claim_owner(self) -> "CollectionObject":
        """Move a pending temporary/return owner into an owning slot."""

        self._require_live()
        if self.unclaimed_owners:
            self.unclaimed_owners -= 1
            return self
        return self.retain()

    def offer_owner(self) -> "CollectionObject":
        """Produce an owned result token, retaining only borrowed storage."""

        self._require_live()
        if self.unclaimed_owners:
            return self
        self.retain()
        self.unclaimed_owners += 1
        return self

    def release(self) -> None:
        self._require_live()
        if self.strong_count <= 0:
            raise RuntimeError(f"Aether {self.kind} reference count underflow")
        self.strong_count -= 1
        if self.unclaimed_owners > self.strong_count:
            self.unclaimed_owners = self.strong_count
        if self.strong_count != 0:
            return
        for element in reversed(self):
            destroy_value(element)
            _DEBUG_COUNTERS.elements_destroyed += 1
        list.clear(self)
        self.alive = False
        self.freed = True
        _DEBUG_COUNTERS.buffers_freed += 1
        _DEBUG_COUNTERS.objects_freed += 1

    def logical_copy(self) -> "CollectionObject":
        self._require_live()
        return CollectionObject(
            self.kind,
            self.element_type,
            self,
            capacity=len(self) if self.kind == "List" else None,
        )

    def logical_slice(self, start: int, end: int) -> "CollectionObject":
        """Create an owned, outer-independent half-open slice."""

        self._require_live()
        if start < 0 or end < 0 or start > end or start > len(self) or end > len(self):
            raise IndexError(f"{self.kind} slice out of bounds")
        return CollectionObject(
            self.kind,
            self.element_type,
            (list.__getitem__(self, index) for index in range(start, end)),
            capacity=end - start if self.kind == "List" else None,
        )

    def __deepcopy__(self, memo: dict[int, Any]) -> "CollectionObject":
        """Host-only snapshot support for the transactional REPL/session.

        This deliberately bypasses Aether retain hooks: a session snapshot is
        a Python rollback image, not a source-language logical copy.
        """

        from copy import deepcopy

        existing = memo.get(id(self))
        if existing is not None:
            return existing
        clone = list.__new__(type(self))
        memo[id(self)] = clone
        list.__init__(clone)
        clone.kind = self.kind
        clone.element_type = deepcopy(self.element_type, memo)
        clone.strong_count = self.strong_count
        clone.unclaimed_owners = self.unclaimed_owners
        clone.capacity = self.capacity
        clone.alive = self.alive
        clone.freed = self.freed
        for element in self:
            list.append(clone, deepcopy(element, memo))
        return clone

    def append(self, value: Any) -> None:
        self._require_mutable_list()
        list.append(self, copy_init_value(value))
        self.capacity = max(self.capacity, len(self))

    def insert(self, index: int, value: Any) -> None:
        self._require_mutable_list()
        list.insert(self, index, copy_init_value(value))
        self.capacity = max(self.capacity, len(self))

    def extend(self, values: Iterable[Any]) -> None:
        self._require_mutable_list()
        copied = [copy_init_value(value) for value in values]
        list.extend(self, copied)
        self.capacity = max(self.capacity, len(self))

    def pop(self, index: int = -1) -> Any:
        self._require_mutable_list()
        # Ownership of the live element transfers to the result.
        return list.pop(self, index)

    def clear(self) -> None:
        self._require_live()
        if self.kind != "List":
            raise RuntimeError("Array length is fixed")
        for element in reversed(self):
            destroy_value(element)
            _DEBUG_COUNTERS.elements_destroyed += 1
        list.clear(self)

    def __setitem__(self, index: Any, value: Any) -> None:
        self._require_live()
        if isinstance(index, slice):
            if self.kind == "Array":
                raise RuntimeError("Array length is fixed")
            old = self[index]
            copied = [copy_init_value(element) for element in value]
            list.__setitem__(self, index, copied)
            for element in reversed(old):
                destroy_value(element)
                _DEBUG_COUNTERS.elements_destroyed += 1
            self.capacity = max(self.capacity, len(self))
            return
        copied = copy_init_value(value)
        old = list.__getitem__(self, index)
        list.__setitem__(self, index, copied)
        destroy_value(old)
        _DEBUG_COUNTERS.elements_destroyed += 1

    def __delitem__(self, index: Any) -> None:
        self._require_mutable_list()
        old = self[index]
        list.__delitem__(self, index)
        values = old if isinstance(index, slice) else [old]
        for element in reversed(values):
            destroy_value(element)
            _DEBUG_COUNTERS.elements_destroyed += 1

    def _require_live(self) -> None:
        if not self.alive or self.freed:
            raise RuntimeError(f"Aether {self.kind} object was already released")

    def _require_mutable_list(self) -> None:
        self._require_live()
        if self.kind != "List":
            raise RuntimeError("Array length is fixed")


def copy_init_value(value: Any) -> Any:
    """Logical element copy used by collection storage hooks."""

    if isinstance(value, CollectionObject):
        return value.retain()
    if isinstance(value, StringValue):
        return value.retain()
    if isinstance(value, tuple):
        copied_items: list[Any] = []
        try:
            for item in value:
                copied_items.append(copy_init_value(item))
        except BaseException:
            for copied in reversed(copied_items):
                destroy_value(copied)
            raise
        return tuple(copied_items)

    from .types import AetherValue, NullableType, StructInstance, TupleType

    if not isinstance(value, AetherValue):
        return value
    if isinstance(value.value, CollectionObject):
        value.value.retain()
        return value
    if isinstance(value.value, StringValue):
        value.value.retain()
        return value
    if isinstance(value.value, StructInstance):
        copied_fields: dict[str, Any] = {}
        try:
            for name in value.value.field_order:
                copied_fields[name] = copy_init_value(value.value.fields[name])
        except BaseException:
            for name in reversed(tuple(copied_fields)):
                destroy_value(copied_fields[name])
            raise
        return AetherValue(
            value.type_name,
            StructInstance(
                value.value.type_name,
                copied_fields,
                value.value.field_order,
            ),
        )
    if isinstance(value.type_name, NullableType) and value.value is not None:
        copied = copy_init_value(AetherValue(value.type_name.base_type, value.value))
        return AetherValue(value.type_name, copied.value)
    if isinstance(value.type_name, TupleType):
        return AetherValue(value.type_name, tuple(copy_init_value(item) for item in value.value))
    return value


def destroy_value(value: Any) -> None:
    """Destroy an owned element recursively; trivial values are no-ops."""

    if isinstance(value, CollectionObject):
        value.release()
        return
    if isinstance(value, StringValue):
        value.release()
        return
    if isinstance(value, tuple):
        for item in reversed(value):
            destroy_value(item)
        return

    from .types import AetherValue, NullableType, StructInstance, TupleType

    if not isinstance(value, AetherValue):
        return
    if isinstance(value.value, CollectionObject):
        value.value.release()
        return
    if isinstance(value.value, StringValue):
        value.value.release()
        return
    if isinstance(value.value, StructInstance):
        for name in reversed(value.value.field_order):
            destroy_value(value.value.fields[name])
        return
    if isinstance(value.type_name, NullableType) and value.value is not None:
        destroy_value(AetherValue(value.type_name.base_type, value.value))
        return
    if isinstance(value.type_name, TupleType):
        for item in reversed(value.value):
            destroy_value(item)


def array_alloc(element_type: object, elements: Iterable[Any] = ()) -> CollectionObject:
    return CollectionObject("Array", element_type, elements)


def list_alloc(
    element_type: object,
    elements: Iterable[Any] = (),
    *,
    capacity: int | None = None,
) -> CollectionObject:
    return CollectionObject("List", element_type, elements, capacity=capacity)
