from __future__ import annotations

from dataclasses import dataclass

from aether.integer_arithmetic import int_operator_may_trap
from aether.ir.types import DoubleType, IntType, StringType


@dataclass(frozen=True)
class InstructionEffects:
    """Semantic effects shared by equivalent IR and SSA instructions."""

    has_side_effects: bool = False
    may_trap: bool = False
    reads_memory: bool = False
    writes_memory: bool = False
    allocates: bool = False

    @property
    def must_preserve(self) -> bool:
        return (
            self.has_side_effects
            or self.may_trap
            or self.writes_memory
            or self.allocates
        )


PURE = InstructionEffects()
SIDE_EFFECT = InstructionEffects(has_side_effects=True)
MEMORY_READ = InstructionEffects(reads_memory=True)
MEMORY_READ_MAY_TRAP = InstructionEffects(may_trap=True, reads_memory=True)
MEMORY_WRITE_ONLY = InstructionEffects(writes_memory=True)
MEMORY_WRITE = InstructionEffects(reads_memory=True, writes_memory=True)
MEMORY_WRITE_MAY_TRAP = InstructionEffects(
    may_trap=True,
    reads_memory=True,
    writes_memory=True,
)
ALLOCATION = InstructionEffects(may_trap=True, allocates=True)
READING_ALLOCATION = InstructionEffects(
    may_trap=True,
    reads_memory=True,
    allocates=True,
)
MUTATING_ALLOCATION = InstructionEffects(
    may_trap=True,
    reads_memory=True,
    writes_memory=True,
    allocates=True,
)
UNKNOWN_CALL = InstructionEffects(
    has_side_effects=True,
    may_trap=True,
    reads_memory=True,
    writes_memory=True,
    allocates=True,
)


class EffectTrackedInstruction:
    """Uniform effect interface inherited by every IR and SSA instruction."""

    effects = PURE

    @property
    def has_side_effects(self) -> bool:
        return self.effects.has_side_effects

    @property
    def may_trap(self) -> bool:
        return self.effects.may_trap

    @property
    def reads_memory(self) -> bool:
        return self.effects.reads_memory

    @property
    def writes_memory(self) -> bool:
        return self.effects.writes_memory

    @property
    def allocates(self) -> bool:
        return self.effects.allocates

    @property
    def must_preserve(self) -> bool:
        return self.effects.must_preserve


class SideEffectMixin:
    effects = SIDE_EFFECT


class MemoryReadMixin:
    effects = MEMORY_READ


class MemoryReadMayTrapMixin:
    effects = MEMORY_READ_MAY_TRAP


class MemoryWriteMixin:
    effects = MEMORY_WRITE


class MemoryWriteOnlyMixin:
    effects = MEMORY_WRITE_ONLY


class MemoryWriteMayTrapMixin:
    effects = MEMORY_WRITE_MAY_TRAP


class AllocationMixin:
    effects = ALLOCATION


class ReadingAllocationMixin:
    effects = READING_ALLOCATION


class MutatingAllocationMixin:
    effects = MUTATING_ALLOCATION


class UnknownCallMixin:
    effects = UNKNOWN_CALL


class CheckedBinaryMixin:
    @property
    def effects(self) -> InstructionEffects:
        if (
            self.operator == "add"
            and isinstance(self.left.type, StringType)
            and isinstance(self.right.type, StringType)
        ):
            return READING_ALLOCATION
        if (
            isinstance(self.left.type, IntType)
            and isinstance(self.right.type, IntType)
            and int_operator_may_trap(self.operator)
        ):
            return InstructionEffects(may_trap=True)
        return PURE


class CheckedCastMixin:
    @property
    def effects(self) -> InstructionEffects:
        # The currently supported narrowing conversion uses truncation and can
        # reject non-finite values in the IR interpreter.
        if isinstance(self.value.type, DoubleType) and isinstance(
            self.result.type,
            IntType,
        ):
            return InstructionEffects(may_trap=True)
        return PURE
