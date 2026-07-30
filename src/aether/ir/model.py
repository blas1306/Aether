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
    MemoryWriteOnlyMixin,
    MutatingAllocationMixin,
    ReadingAllocationMixin,
    SideEffectMixin,
    UnknownCallMixin,
    MEMORY_READ,
    MEMORY_READ_MAY_TRAP,
    MUTATING_ALLOCATION,
    NONTHROWING_UNKNOWN_CALL,
    READING_ALLOCATION,
    PURE,
    UNKNOWN_CALL,
    InstructionEffects,
)
from aether.scalar_math import scalar_math_may_trap

from .types import ArrayType, IRType, ListType, MatrixType, StringType, StructType, VectorType


@dataclass(frozen=True)
class IRValue:
    name: str
    type: IRType


@dataclass(frozen=True)
class IRStorage(IRValue):
    """An addressable owning location, distinct from an immutable IR value.

    The initial IR historically used ``IRValue`` for both SSA-like values and
    mutable slots.  Lifecycle instructions require that distinction to be
    explicit so the verifier cannot accidentally destroy a temporary or use a
    computed value as destination storage.
    """


@dataclass(frozen=True)
class IRSourceLocation:
    line: int
    column: int
    path: str | None = None


@dataclass(frozen=True)
class IRParameter(IRValue):
    pass


class IRInstruction(EffectTrackedInstruction):
    """Base class for instructions in the initial Aether IR."""


@dataclass(frozen=True)
class IREnumConstant:
    """Nominal enum constant retained until LLVM code generation."""

    enum_name: str
    member_name: str
    member_id: int
    discriminant: int


@dataclass(frozen=True)
class IRConst(IRInstruction):
    result: IRValue
    value: Any


@dataclass(frozen=True)
class IRLoad(MemoryReadMixin, IRInstruction):
    result: IRValue
    slot: IRValue


@dataclass(frozen=True)
class IRStore(MemoryWriteOnlyMixin, IRInstruction):
    slot: IRValue
    value: IRValue


@dataclass(frozen=True)
class IRInitDefault(SideEffectMixin, IRInstruction):
    destination: IRStorage
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRCopyInit(SideEffectMixin, IRInstruction):
    destination: IRStorage
    source: IRValue
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRMoveInit(SideEffectMixin, IRInstruction):
    destination: IRStorage
    source: IRStorage
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRAssign(SideEffectMixin, IRInstruction):
    destination: IRStorage
    source: IRValue
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRDestroy(SideEffectMixin, IRInstruction):
    value: IRStorage
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRRelocate(SideEffectMixin, IRInstruction):
    destination: IRStorage
    source: IRStorage
    count: int
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRBinaryOp(CheckedBinaryMixin, IRInstruction):
    result: IRValue
    operator: str
    left: IRValue
    right: IRValue
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRUnaryOp(IRInstruction):
    result: IRValue
    operator: str
    operand: IRValue


@dataclass(frozen=True)
class IRCompareOp(IRInstruction):
    result: IRValue
    operator: str
    left: IRValue
    right: IRValue
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
class IRCast(CheckedCastMixin, IRInstruction):
    result: IRValue
    value: IRValue


@dataclass(frozen=True)
class IRCall(IRInstruction):
    function: str
    arguments: tuple[IRValue, ...] = ()
    result: IRValue | None = None
    builtin: str | None = None
    source_location: IRSourceLocation | None = None
    may_throw_effect: bool = False

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
        if self.builtin == "__aether_interface_copy_owned":
            return InstructionEffects(
                has_side_effects=True,
                may_trap=True,
                reads_memory=True,
                allocates=True,
            )
        if self.builtin == "__aether_range_step_nonzero":
            return InstructionEffects(has_side_effects=True, may_trap=True)
        if self.builtin is None:
            return UNKNOWN_CALL if self.may_throw_effect else NONTHROWING_UNKNOWN_CALL
        if scalar_math_may_trap(
            self.builtin,
            tuple(argument.type for argument in self.arguments),
        ):
            return InstructionEffects(may_trap=True)
        return PURE


@dataclass(frozen=True)
class IRInvoke(IRInstruction):
    """Direct call with explicit, mutually exclusive CFG successors."""

    function: str
    arguments: tuple[IRValue, ...]
    result: IRValue | None
    exception: IRValue = field(metadata={"ir_definition": True})
    normal_target: str
    exceptional_target: str
    exceptional_target_event: IRValue
    builtin: str | None = None
    source_location: IRSourceLocation | None = None

    effects = UnknownCallMixin.effects


@dataclass(frozen=True)
class IRFunctionRef(IRInstruction):
    result: IRValue
    function: str


@dataclass(frozen=True)
class IRCallIndirect(UnknownCallMixin, IRInstruction):
    callee: IRValue
    arguments: tuple[IRValue, ...] = ()
    result: IRValue | None = None

    effects = NONTHROWING_UNKNOWN_CALL


@dataclass(frozen=True)
class IRInvokeIndirect(IRInstruction):
    """Indirect call with explicit normal and exceptional successors."""

    callee: IRValue
    arguments: tuple[IRValue, ...]
    result: IRValue | None
    exception: IRValue = field(metadata={"ir_definition": True})
    normal_target: str
    exceptional_target: str
    exceptional_target_event: IRValue

    effects = UnknownCallMixin.effects


@dataclass(frozen=True)
class IRPrint(SideEffectMixin, IRInstruction):
    value: IRValue
    newline: bool = False
    aggregate_shape: tuple[int, ...] | None = None


@dataclass(frozen=True)
class IRStructNew(IRInstruction):
    result: IRValue
    fields: tuple[IRValue, ...] = ()


@dataclass(frozen=True)
class IRClassNew(AllocationMixin, IRInstruction):
    """Allocate one nominal class object with uninitialized field payload."""

    result: IRValue


@dataclass(frozen=True)
class IRClassGet(MemoryReadMixin, IRInstruction):
    """Read a statically resolved field through a class handle."""

    result: IRValue
    object: IRValue
    field_index: int
    field_name: str


@dataclass(frozen=True)
class IRClassSet(MemoryWriteMixin, IRInstruction):
    """Initialize or assign a statically resolved class field.

    ``initialize`` is true only while lowering a constructor path on which the
    field is not live yet.  Normal assignments use lifecycle-safe replacement.
    """

    object: IRValue
    field_index: int
    field_name: str
    value: IRValue
    initialize: bool = False


@dataclass(frozen=True)
class IRWitnessMethodSlot:
    """Immutable metadata for one erased interface-dispatch slot."""

    index: int
    method_id: str
    parameter_types: tuple[IRType, ...]
    return_type: IRType
    thunk_symbol: str = ""
    receiver_ownership: str = "borrowed"


@dataclass(frozen=True)
class IRErasedBoxLayout:
    """Target-independent LP64 facts used to validate a private erased box."""

    payload_size: int
    payload_alignment: int
    payload_offset: int
    ownership: str
    copy_owned_symbol: str
    drop_owned_symbol: str


@dataclass(frozen=True)
class IRWitnessTable:
    """Canonical witness metadata embedded in an interface construction."""

    symbol: str
    interface_id: str
    concrete_type_id: str
    carrier_kind: str
    method_slots: tuple[IRWitnessMethodSlot, ...]
    abi_version: int = 1
    box_layout: IRErasedBoxLayout | None = None


@dataclass(frozen=True)
class IRInterfaceConstruct(SideEffectMixin, IRInstruction):
    """Construct the native ``{carrier, witness}`` owner.

    Ownership transfer makes construction non-removable even though assembling
    the two machine words does not itself write memory.
    """

    result: IRValue
    carrier: IRValue
    witness: IRWitnessTable


@dataclass(frozen=True)
class IRInterfaceCall(UnknownCallMixin, IRInstruction):
    """Witness-driven call through a declaration-ordered interface slot."""

    receiver: IRValue
    arguments: tuple[IRValue, ...]
    slot: IRWitnessMethodSlot
    result: IRValue | None = None

    effects = NONTHROWING_UNKNOWN_CALL


@dataclass(frozen=True)
class IRInvokeInterface(IRInstruction):
    """Interface call with explicit normal and exceptional successors."""

    receiver: IRValue
    arguments: tuple[IRValue, ...]
    slot: IRWitnessMethodSlot
    result: IRValue | None
    exception: IRValue = field(metadata={"ir_definition": True})
    normal_target: str
    exceptional_target: str
    exceptional_target_event: IRValue

    effects = UnknownCallMixin.effects


@dataclass(frozen=True)
class IRStructGet(IRInstruction):
    result: IRValue
    struct: IRValue
    field_index: int
    field_name: str


@dataclass(frozen=True)
class IRStructSet(IRInstruction):
    result: IRValue
    struct: IRValue
    field_index: int
    field_name: str
    value: IRValue


@dataclass(frozen=True)
class IRMethodResultNew(IRInstruction):
    result: IRValue
    receiver: IRValue
    value: IRValue | None = None


@dataclass(frozen=True)
class IRMethodResultReceiver(IRInstruction):
    result: IRValue
    method_result: IRValue


@dataclass(frozen=True)
class IRMethodResultValue(IRInstruction):
    result: IRValue
    method_result: IRValue


@dataclass(frozen=True)
class IRArrayNew(AllocationMixin, IRInstruction):
    result: IRValue
    elements: tuple[IRValue, ...] = ()

    element_lifecycle = "copy_init"


@dataclass(frozen=True)
class IRListNew(AllocationMixin, IRInstruction):
    result: IRValue
    elements: tuple[IRValue, ...] = ()

    element_lifecycle = "copy_init"


@dataclass(frozen=True)
class IRArrayCopy(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    array: IRValue
    source_location: IRSourceLocation | None = None

    element_lifecycle = "copy_init"


@dataclass(frozen=True)
class IRListCopy(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    list_value: IRValue
    source_location: IRSourceLocation | None = None

    element_lifecycle = "copy_init"


@dataclass(frozen=True)
class IRListContains(MemoryReadMixin, IRInstruction):
    result: IRValue
    list_value: IRValue
    value: IRValue


@dataclass(frozen=True)
class IRListIndexOf(MemoryReadMayTrapMixin, IRInstruction):
    result: IRValue
    list_value: IRValue
    value: IRValue


@dataclass(frozen=True)
class IRListClear(MemoryWriteMixin, IRInstruction):
    list_value: IRValue

    element_lifecycle = "destroy"


@dataclass(frozen=True)
class IRListPush(MutatingAllocationMixin, IRInstruction):
    list_value: IRValue
    value: IRValue

    element_lifecycle = "copy_init"
    growth_lifecycle = "relocate"


@dataclass(frozen=True)
class IRListInsert(MutatingAllocationMixin, IRInstruction):
    list_value: IRValue
    index: IRValue
    value: IRValue

    element_lifecycle = "copy_init"
    shift_lifecycle = "relocate"


@dataclass(frozen=True)
class IRListRemoveAt(MemoryWriteMayTrapMixin, IRInstruction):
    result: IRValue
    list_value: IRValue
    index: IRValue

    result_lifecycle = "move_init"
    shift_lifecycle = "relocate"


@dataclass(frozen=True)
class IRListPop(MemoryWriteMayTrapMixin, IRInstruction):
    result: IRValue
    list_value: IRValue

    result_lifecycle = "move_init"


@dataclass(frozen=True)
class IRListReverse(MemoryWriteMixin, IRInstruction):
    list_value: IRValue


@dataclass(frozen=True)
class IRSequenceSort(MutatingAllocationMixin, IRInstruction):
    sequence: IRValue


@dataclass(frozen=True)
class IRVectorNew(AllocationMixin, IRInstruction):
    result: IRValue
    elements: tuple[IRValue, ...] = ()
    orientation: str | None = None

    def __post_init__(self) -> None:
        if self.orientation is None and isinstance(self.result.type, VectorType):
            object.__setattr__(self, "orientation", self.result.type.orientation)


@dataclass(frozen=True)
class IRMatrixNew(AllocationMixin, IRInstruction):
    result: IRValue
    elements: tuple[IRValue, ...] = ()
    rows: int = 0
    cols: int = 0


@dataclass(frozen=True)
class IRVectorAdd(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    left: IRValue
    right: IRValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class IRVectorSub(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    left: IRValue
    right: IRValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class IRVectorScale(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    vector: IRValue
    scalar: IRValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class IRVectorDot(MemoryReadMayTrapMixin, IRInstruction):
    """Dot product for Vector<Row> * Vector<Column> only."""

    result: IRValue
    left: IRValue
    right: IRValue
    length: int


@dataclass(frozen=True)
class IROuterProduct(ReadingAllocationMixin, IRInstruction):
    """Outer product for Vector<Column> * Vector<Row>."""

    result: IRValue
    column: IRValue
    row: IRValue
    rows: int
    cols: int


@dataclass(frozen=True)
class IRMatrixAdd(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    left: IRValue
    right: IRValue
    rows: int
    cols: int


@dataclass(frozen=True)
class IRMatrixSub(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    left: IRValue
    right: IRValue
    rows: int
    cols: int


@dataclass(frozen=True)
class IRMatrixScale(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    matrix: IRValue
    scalar: IRValue
    rows: int
    cols: int


@dataclass(frozen=True)
class IRMatrixMatMul(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    left: IRValue
    right: IRValue
    rows: int
    inner: int
    cols: int


@dataclass(frozen=True)
class IRMatrixVectorMul(ReadingAllocationMixin, IRInstruction):
    """Matrix * Vector product; currently only accepts Vector<Column>."""

    result: IRValue
    matrix: IRValue
    vector: IRValue
    rows: int
    inner: int


@dataclass(frozen=True)
class IRVectorMatrixMul(ReadingAllocationMixin, IRInstruction):
    """Vector<Row> * Matrix product."""

    result: IRValue
    vector: IRValue
    matrix: IRValue
    rows: int
    cols: int


@dataclass(frozen=True)
class IRArrayGet(MemoryReadMayTrapMixin, IRInstruction):
    result: IRValue
    array: IRValue
    index: IRValue
    borrowed: bool = False
    borrow_scope: str | None = None
    source_location: IRSourceLocation | None = None

    element_lifecycle = "copy_init"


@dataclass(frozen=True)
class IRArraySlice(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    array: IRValue
    start: IRValue
    end: IRValue
    source_location: IRSourceLocation | None = None

    element_lifecycle = "copy_init"


@dataclass(frozen=True)
class IRListSlice(ReadingAllocationMixin, IRInstruction):
    result: IRValue
    list_value: IRValue
    start: IRValue
    end: IRValue
    source_location: IRSourceLocation | None = None

    element_lifecycle = "copy_init"

@dataclass(frozen=True)
class IRListGet(MemoryReadMayTrapMixin, IRInstruction):
    result: IRValue
    list_value: IRValue
    index: IRValue
    borrowed: bool = False
    borrow_scope: str | None = None
    source_location: IRSourceLocation | None = None

    element_lifecycle = "copy_init"


@dataclass(frozen=True)
class IRVectorGet(MemoryReadMayTrapMixin, IRInstruction):
    result: IRValue
    vector: IRValue
    index: IRValue


@dataclass(frozen=True)
class IRMatrixGet(MemoryReadMayTrapMixin, IRInstruction):
    result: IRValue
    matrix: IRValue
    row: IRValue
    column: IRValue
    cols: int


@dataclass(frozen=True)
class IRVectorLength(MemoryReadMixin, IRInstruction):
    result: IRValue
    vector: IRValue


@dataclass(frozen=True)
class IRMatrixRows(IRInstruction):
    result: IRValue
    matrix: IRValue
    rows: int


@dataclass(frozen=True)
class IRMatrixColumns(IRInstruction):
    result: IRValue
    matrix: IRValue
    columns: int


@dataclass(frozen=True)
class IRArraySet(MemoryWriteMayTrapMixin, IRInstruction):
    array: IRValue
    index: IRValue
    value: IRValue

    element_lifecycle = "assign"


@dataclass(frozen=True)
class IRListSet(MemoryWriteMayTrapMixin, IRInstruction):
    list_value: IRValue
    index: IRValue
    value: IRValue

    element_lifecycle = "assign"


@dataclass(frozen=True)
class IRVectorSet(MemoryWriteMayTrapMixin, IRInstruction):
    vector: IRValue
    index: IRValue
    value: IRValue


@dataclass(frozen=True)
class IRMatrixSet(MemoryWriteMayTrapMixin, IRInstruction):
    matrix: IRValue
    row: IRValue
    column: IRValue
    value: IRValue
    cols: int


@dataclass(frozen=True)
class IRArrayLength(MemoryReadMayTrapMixin, IRInstruction):
    result: IRValue
    array: IRValue


@dataclass(frozen=True)
class IRListLength(MemoryReadMayTrapMixin, IRInstruction):
    result: IRValue
    list_value: IRValue


@dataclass(frozen=True)
class IRListIsEmpty(MemoryReadMixin, IRInstruction):
    result: IRValue
    list_value: IRValue


@dataclass(frozen=True)
class IRPackException(SideEffectMixin, IRInstruction):
    """Create an opaque event which owns a validated Error payload."""

    result: IRValue
    payload: IRValue
    dynamic_type: str | None
    source_location: IRSourceLocation | None = None


@dataclass(frozen=True)
class IRCatchEntry(SideEffectMixin, IRInstruction):
    """Handler entry plus its source-ordered catch metadata."""

    event: IRValue = field(metadata={"ir_definition": True})
    handler_id: str
    catch_types: tuple[str, ...]


@dataclass(frozen=True)
class IRExceptionMatch(IRInstruction):
    """Exact nominal descriptor match, or the explicit Error catch-all."""

    result: IRValue
    event: IRValue
    catch_type: str
    catch_all: bool = False


@dataclass(frozen=True)
class IRExceptionPayload(MemoryReadMixin, IRInstruction):
    """Borrow the payload while the owning event remains live."""

    result: IRValue
    event: IRValue
    catch_type: str


@dataclass(frozen=True)
class IRExceptionDestroy(SideEffectMixin, IRInstruction):
    """Consume a handled event exactly once."""

    event: IRValue


@dataclass(frozen=True)
class IRThrow(SideEffectMixin, IRInstruction):
    """Transfer a newly packed event to a handler or function boundary."""

    event: IRValue
    target: str | None = None
    target_event: IRValue | None = None


@dataclass(frozen=True)
class IRRethrow(SideEffectMixin, IRInstruction):
    """Transfer the active event to the next outer handler."""

    event: IRValue
    target: str | None = None
    target_event: IRValue | None = None


@dataclass(frozen=True)
class IRPropagate(SideEffectMixin, IRInstruction):
    """Transfer an unmatched or call-produced event outward."""

    event: IRValue
    target: str | None = None
    target_event: IRValue | None = None


@dataclass(frozen=True)
class IRBranch(SideEffectMixin, IRInstruction):
    condition: IRValue
    true_target: str
    false_target: str


@dataclass(frozen=True)
class IRJump(SideEffectMixin, IRInstruction):
    target: str


@dataclass(frozen=True)
class IRReturn(SideEffectMixin, IRInstruction):
    value: IRValue | None = None
    transferred_storage: IRStorage | None = None


@dataclass
class IRBasicBlock:
    name: str
    instructions: list[IRInstruction] = field(default_factory=list)


@dataclass
class IRFunction:
    name: str
    parameters: list[IRParameter]
    return_type: IRType
    blocks: list[IRBasicBlock] = field(default_factory=list)
    may_throw: bool = False


@dataclass(frozen=True)
class IRStructDefinition:
    name: str
    fields: tuple[tuple[str, IRType], ...]


@dataclass
class IRModule:
    functions: list[IRFunction] = field(default_factory=list)
    structs: list[IRStructDefinition] = field(default_factory=list)
