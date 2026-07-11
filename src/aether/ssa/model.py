from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aether.ir.types import IRType, VectorType


@dataclass(frozen=True)
class SSAValue:
    name: str
    type: IRType


@dataclass(frozen=True)
class SSAParameter(SSAValue):
    pass


class SSAInstruction:
    """Base class for value-based SSA instructions."""


@dataclass(frozen=True)
class SSAConst(SSAInstruction):
    result: SSAValue
    value: Any


@dataclass(frozen=True)
class SSABinaryOp(SSAInstruction):
    result: SSAValue
    operator: str
    left: SSAValue
    right: SSAValue


@dataclass(frozen=True)
class SSACompareOp(SSAInstruction):
    result: SSAValue
    operator: str
    left: SSAValue
    right: SSAValue


@dataclass(frozen=True)
class SSACast(SSAInstruction):
    result: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSACall(SSAInstruction):
    function: str
    arguments: tuple[SSAValue, ...] = ()
    result: SSAValue | None = None


@dataclass(frozen=True)
class SSAArrayNew(SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()


@dataclass(frozen=True)
class SSAListNew(SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()


@dataclass(frozen=True)
class SSAVectorNew(SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()
    orientation: str | None = None

    def __post_init__(self) -> None:
        if self.orientation is None and isinstance(self.result.type, VectorType):
            object.__setattr__(self, "orientation", self.result.type.orientation)


@dataclass(frozen=True)
class SSAMatrixNew(SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()
    rows: int = 0
    cols: int = 0


@dataclass(frozen=True)
class SSAVectorAdd(SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class SSAVectorSub(SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class SSAVectorScale(SSAInstruction):
    result: SSAValue
    vector: SSAValue
    scalar: SSAValue
    length: int
    orientation: str | None = None


@dataclass(frozen=True)
class SSAVectorDot(SSAInstruction):
    """Dot product for Vector<Row> * Vector<Column> only."""

    result: SSAValue
    left: SSAValue
    right: SSAValue
    length: int


@dataclass(frozen=True)
class SSAOuterProduct(SSAInstruction):
    """Outer product for Vector<Column> * Vector<Row>."""

    result: SSAValue
    column: SSAValue
    row: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixAdd(SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixSub(SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixScale(SSAInstruction):
    result: SSAValue
    matrix: SSAValue
    scalar: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixMatMul(SSAInstruction):
    result: SSAValue
    left: SSAValue
    right: SSAValue
    rows: int
    inner: int
    cols: int


@dataclass(frozen=True)
class SSAMatrixVectorMul(SSAInstruction):
    """Matrix * Vector product; currently only accepts Vector<Column>."""

    result: SSAValue
    matrix: SSAValue
    vector: SSAValue
    rows: int
    inner: int


@dataclass(frozen=True)
class SSAVectorMatrixMul(SSAInstruction):
    """Vector<Row> * Matrix product."""

    result: SSAValue
    vector: SSAValue
    matrix: SSAValue
    rows: int
    cols: int


@dataclass(frozen=True)
class SSAArrayGet(SSAInstruction):
    result: SSAValue
    array: SSAValue
    index: SSAValue


@dataclass(frozen=True)
class SSAListGet(SSAInstruction):
    result: SSAValue
    list_value: SSAValue
    index: SSAValue


@dataclass(frozen=True)
class SSAVectorGet(SSAInstruction):
    result: SSAValue
    vector: SSAValue
    index: SSAValue


@dataclass(frozen=True)
class SSAMatrixGet(SSAInstruction):
    result: SSAValue
    matrix: SSAValue
    row: SSAValue
    column: SSAValue
    cols: int


@dataclass(frozen=True)
class SSAVectorLength(SSAInstruction):
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
class SSAArraySet(SSAInstruction):
    array: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAListSet(SSAInstruction):
    list_value: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAVectorSet(SSAInstruction):
    vector: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAMatrixSet(SSAInstruction):
    matrix: SSAValue
    row: SSAValue
    column: SSAValue
    value: SSAValue
    cols: int


@dataclass(frozen=True)
class SSAArrayLength(SSAInstruction):
    result: SSAValue
    array: SSAValue


@dataclass(frozen=True)
class SSAListLength(SSAInstruction):
    result: SSAValue
    list_value: SSAValue


@dataclass(frozen=True)
class SSAListIsEmpty(SSAInstruction):
    result: SSAValue
    list_value: SSAValue


@dataclass(frozen=True)
class SSAPhi(SSAInstruction):
    result: SSAValue
    incoming: tuple[tuple[str, SSAValue], ...]


@dataclass(frozen=True)
class SSABranch(SSAInstruction):
    condition: SSAValue
    true_target: str
    false_target: str


@dataclass(frozen=True)
class SSAJump(SSAInstruction):
    target: str


@dataclass(frozen=True)
class SSAReturn(SSAInstruction):
    value: SSAValue | None = None


@dataclass
class SSABasicBlock:
    name: str
    instructions: list[SSAInstruction] = field(default_factory=list)


@dataclass
class SSAFunction:
    name: str
    parameters: list[SSAParameter]
    return_type: IRType
    blocks: list[SSABasicBlock] = field(default_factory=list)
    entry_block: str = "entry"


@dataclass
class SSAModule:
    functions: list[SSAFunction] = field(default_factory=list)
