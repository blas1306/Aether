from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aether.instruction_effects import (
    AllocationMixin,
    CheckedBinaryMixin,
    CheckedCastMixin,
    EffectTrackedInstruction,
    MemoryReadMayTrapMixin,
    MemoryReadMixin,
    MemoryWriteMayTrapMixin,
    MemoryWriteMixin,
    MutatingAllocationMixin,
    ReadingAllocationMixin,
    SideEffectMixin,
    UnknownCallMixin,
    MEMORY_READ,
    MEMORY_READ_MAY_TRAP,
    MUTATING_ALLOCATION,
    READING_ALLOCATION,
    PURE,
    InstructionEffects,
)
from aether.scalar_math import scalar_math_may_trap
from aether.ir.types import ArrayType, IRType, ListType, MatrixType, StringType, StructType, VectorType


@dataclass(frozen=True)
class SSAValue:
    name: str
    type: IRType


@dataclass(frozen=True)
class SSAParameter(SSAValue):
    pass


class SSAInstruction(EffectTrackedInstruction):
    """Base class for value-based SSA instructions."""


@dataclass(frozen=True)
class SSAConst(SSAInstruction):
    result: SSAValue
    value: Any


@dataclass(frozen=True)
class SSABinaryOp(CheckedBinaryMixin, SSAInstruction):
    result: SSAValue
    operator: str
    left: SSAValue
    right: SSAValue
    source_location: Any | None = None


@dataclass(frozen=True)
class SSAUnaryOp(SSAInstruction):
    result: SSAValue
    operator: str
    operand: SSAValue


@dataclass(frozen=True)
class SSACompareOp(SSAInstruction):
    result: SSAValue
    operator: str
    left: SSAValue
    right: SSAValue
    aggregate_shape: tuple[int, ...] | None = None

    @property
    def effects(self):
        return (
            MEMORY_READ
            if self.aggregate_shape is not None
            or isinstance(self.left.type, (ArrayType, ListType, MatrixType, StringType, StructType, VectorType))
            else PURE
        )


@dataclass(frozen=True)
class SSACast(CheckedCastMixin, SSAInstruction):
    result: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSACall(SSAInstruction):
    function: str
    arguments: tuple[SSAValue, ...] = ()
    result: SSAValue | None = None
    builtin: str | None = None
    source_location: Any | None = None

    @property
    def effects(self):
        if self.builtin == "io.readText":
            return InstructionEffects(
                has_side_effects=True,
                may_trap=True,
                reads_memory=True,
                allocates=True,
            )
        if self.builtin in {"io.writeText", "io.writeTextAtomic", "io.appendText"}:
            return InstructionEffects(
                has_side_effects=True,
                reads_memory=True,
                writes_memory=True,
            )
        if self.builtin == "System.args":
            return READING_ALLOCATION
        if self.builtin == "__aether_string_byte_length":
            return MEMORY_READ_MAY_TRAP
        if self.builtin == "__aether_string_trim":
            return MUTATING_ALLOCATION
        if self.builtin == "__aether_string_split":
            return MUTATING_ALLOCATION
        if self.builtin in {"parseInt", "parseDouble"}:
            return MEMORY_READ
        if self.builtin in {"text.byteAt"}:
            return MEMORY_READ_MAY_TRAP
        if self.builtin in {
            "text.byteSlice", "text.formatInt", "text.formatDouble",
            "text.concatFragments",
        }:
            return READING_ALLOCATION
        if self.builtin in {"__aether_retain", "__aether_release"}:
            return InstructionEffects(
                has_side_effects=True,
                may_trap=True,
                reads_memory=True,
                writes_memory=True,
            )
        if self.builtin == "__aether_range_step_nonzero":
            return InstructionEffects(has_side_effects=True, may_trap=True)
        if self.builtin is None:
            return UnknownCallMixin.effects
        if scalar_math_may_trap(
            self.builtin,
            tuple(argument.type for argument in self.arguments),
        ):
            return InstructionEffects(may_trap=True)
        return PURE


@dataclass(frozen=True)
class SSAFunctionRef(SSAInstruction):
    result: SSAValue
    function: str


@dataclass(frozen=True)
class SSACallIndirect(UnknownCallMixin, SSAInstruction):
    callee: SSAValue
    arguments: tuple[SSAValue, ...] = ()
    result: SSAValue | None = None


@dataclass(frozen=True)
class SSAPrint(SideEffectMixin, SSAInstruction):
    value: SSAValue
    newline: bool = False
    aggregate_shape: tuple[int, ...] | None = None


@dataclass(frozen=True)
class SSAStructNew(SSAInstruction):
    result: SSAValue
    fields: tuple[SSAValue, ...] = ()


@dataclass(frozen=True)
class SSAClassNew(AllocationMixin, SSAInstruction):
    """Allocate one nominal Phase 5.3A class object."""

    result: SSAValue


@dataclass(frozen=True)
class SSAStructGet(SSAInstruction):
    result: SSAValue
    struct: SSAValue
    field_index: int
    field_name: str


@dataclass(frozen=True)
class SSAStructSet(SSAInstruction):
    result: SSAValue
    struct: SSAValue
    field_index: int
    field_name: str
    value: SSAValue


@dataclass(frozen=True)
class SSAMethodResultNew(SSAInstruction):
    result: SSAValue
    receiver: SSAValue
    value: SSAValue | None = None


@dataclass(frozen=True)
class SSAMethodResultReceiver(SSAInstruction):
    result: SSAValue
    method_result: SSAValue


@dataclass(frozen=True)
class SSAMethodResultValue(SSAInstruction):
    result: SSAValue
    method_result: SSAValue


@dataclass(frozen=True)
class SSAArrayNew(AllocationMixin, SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()


@dataclass(frozen=True)
class SSAListNew(AllocationMixin, SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()


@dataclass(frozen=True)
class SSAArrayCopy(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    array: SSAValue


@dataclass(frozen=True)
class SSAListCopy(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue


@dataclass(frozen=True)
class SSAListContains(MemoryReadMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAListIndexOf(MemoryReadMayTrapMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAListClear(MemoryWriteMixin, SSAInstruction):
    list_value: SSAValue


@dataclass(frozen=True)
class SSAListPush(MutatingAllocationMixin, SSAInstruction):
    list_value: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAListInsert(MutatingAllocationMixin, SSAInstruction):
    list_value: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAListRemoveAt(MemoryWriteMayTrapMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue
    index: SSAValue


@dataclass(frozen=True)
class SSAListPop(MemoryWriteMayTrapMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue


@dataclass(frozen=True)
class SSAListReverse(MemoryWriteMixin, SSAInstruction):
    list_value: SSAValue


@dataclass(frozen=True)
class SSASequenceSort(MutatingAllocationMixin, SSAInstruction):
    sequence: SSAValue


@dataclass(frozen=True)
class SSAVectorNew(AllocationMixin, SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()
    orientation: str | None = None

    def __post_init__(self) -> None:
        if self.orientation is None and isinstance(self.result.type, VectorType):
            object.__setattr__(self, "orientation", self.result.type.orientation)


@dataclass(frozen=True)
class SSAMatrixNew(AllocationMixin, SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()
    rows: int = 0
    cols: int = 0


@dataclass(frozen=True)
class SSAVectorAdd(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class SSAVectorSub(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class SSAVectorScale(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    vector: SSAValue
    scalar: SSAValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class SSAVectorDot(MemoryReadMayTrapMixin, SSAInstruction):
    """Dot product for Vector<Row> * Vector<Column> only."""

    result: SSAValue
    left: SSAValue
    right: SSAValue
    length: int


@dataclass(frozen=True)
class SSAOuterProduct(ReadingAllocationMixin, SSAInstruction):
    """Outer product for Vector<Column> * Vector<Row>."""

    result: SSAValue
    column: SSAValue
    row: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixAdd(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixSub(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixScale(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    matrix: SSAValue
    scalar: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixMatMul(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    rows: int
    inner: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixVectorMul(ReadingAllocationMixin, SSAInstruction):
    """Matrix * Vector product; currently only accepts Vector<Column>."""

    result: SSAValue
    matrix: SSAValue
    vector: SSAValue
    rows: int
    inner: int


@dataclass(frozen=True)
class SSAVectorMatrixMul(ReadingAllocationMixin, SSAInstruction):
    """Vector<Row> * Matrix product."""

    result: SSAValue
    vector: SSAValue
    matrix: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAArrayGet(MemoryReadMayTrapMixin, SSAInstruction):
    result: SSAValue
    array: SSAValue
    index: SSAValue
    borrowed: bool = False
    borrow_scope: str | None = None


@dataclass(frozen=True)
class SSAArraySlice(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    array: SSAValue
    start: SSAValue
    end: SSAValue


@dataclass(frozen=True)
class SSAListSlice(ReadingAllocationMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue
    start: SSAValue
    end: SSAValue

@dataclass(frozen=True)
class SSAListGet(MemoryReadMayTrapMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue
    index: SSAValue
    borrowed: bool = False
    borrow_scope: str | None = None


@dataclass(frozen=True)
class SSAVectorGet(MemoryReadMayTrapMixin, SSAInstruction):
    result: SSAValue
    vector: SSAValue
    index: SSAValue


@dataclass(frozen=True)
class SSAMatrixGet(MemoryReadMayTrapMixin, SSAInstruction):
    result: SSAValue
    matrix: SSAValue
    row: SSAValue
    column: SSAValue
    cols: int


@dataclass(frozen=True)
class SSAVectorLength(MemoryReadMixin, SSAInstruction):
    result: SSAValue
    vector: SSAValue


@dataclass(frozen=True)
class SSAMatrixRows(SSAInstruction):
    result: SSAValue
    matrix: SSAValue
    rows: int


@dataclass(frozen=True)
class SSAMatrixColumns(SSAInstruction):
    result: SSAValue
    matrix: SSAValue
    columns: int


@dataclass(frozen=True)
class SSAArraySet(MemoryWriteMayTrapMixin, SSAInstruction):
    array: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAListSet(MemoryWriteMayTrapMixin, SSAInstruction):
    list_value: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAVectorSet(MemoryWriteMayTrapMixin, SSAInstruction):
    vector: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAMatrixSet(MemoryWriteMayTrapMixin, SSAInstruction):
    matrix: SSAValue
    row: SSAValue
    column: SSAValue
    value: SSAValue
    cols: int


@dataclass(frozen=True)
class SSAArrayLength(MemoryReadMayTrapMixin, SSAInstruction):
    result: SSAValue
    array: SSAValue


@dataclass(frozen=True)
class SSAListLength(MemoryReadMayTrapMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue


@dataclass(frozen=True)
class SSAListIsEmpty(MemoryReadMixin, SSAInstruction):
    result: SSAValue
    list_value: SSAValue


@dataclass(frozen=True)
class SSAPhi(SSAInstruction):
    """Select one value for each distinct CFG predecessor block.

    ``incoming`` is an ordered serialization of a predecessor map. The SSA
    verifier requires each real predecessor exactly once; parallel CFG edges
    are not represented by this model.
    """

    result: SSAValue
    incoming: tuple[tuple[str, SSAValue], ...]


@dataclass(frozen=True)
class SSABranch(SideEffectMixin, SSAInstruction):
    condition: SSAValue
    true_target: str
    false_target: str


@dataclass(frozen=True)
class SSAJump(SideEffectMixin, SSAInstruction):
    target: str


@dataclass(frozen=True)
class SSAReturn(SideEffectMixin, SSAInstruction):
    value: SSAValue | None = None


@dataclass
class SSABasicBlock:
    name: str
    instructions: list[SSAInstruction] = field(default_factory=list)


@dataclass
class SSAFunction:
    """Function-local SSA graph rooted at ``entry_block``."""

    name: str
    parameters: list[SSAParameter]
    return_type: IRType
    blocks: list[SSABasicBlock] = field(default_factory=list)
    entry_block: str = "entry"


@dataclass
class SSAModule:
    functions: list[SSAFunction] = field(default_factory=list)
    structs: list[object] = field(default_factory=list)
