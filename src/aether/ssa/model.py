from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aether.ir.types import IRType


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
class SSAVectorNew(SSAInstruction):
    result: SSAValue
    elements: tuple[SSAValue, ...] = ()


@dataclass(frozen=True)
class SSAArrayGet(SSAInstruction):
    result: SSAValue
    array: SSAValue
    index: SSAValue


@dataclass(frozen=True)
class SSAArraySet(SSAInstruction):
    array: SSAValue
    index: SSAValue
    value: SSAValue


@dataclass(frozen=True)
class SSAArrayLength(SSAInstruction):
    result: SSAValue
    array: SSAValue


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
