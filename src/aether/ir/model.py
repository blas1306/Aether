from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import IRType


@dataclass(frozen=True)
class IRValue:
    name: str
    type: IRType


@dataclass(frozen=True)
class IRParameter(IRValue):
    pass


class IRInstruction:
    """Base class for instructions in the initial Aether IR."""


@dataclass(frozen=True)
class IRConst(IRInstruction):
    result: IRValue
    value: Any


@dataclass(frozen=True)
class IRLoad(IRInstruction):
    result: IRValue
    slot: IRValue


@dataclass(frozen=True)
class IRStore(IRInstruction):
    slot: IRValue
    value: IRValue


@dataclass(frozen=True)
class IRBinaryOp(IRInstruction):
    result: IRValue
    operator: str
    left: IRValue
    right: IRValue


@dataclass(frozen=True)
class IRCompareOp(IRInstruction):
    result: IRValue
    operator: str
    left: IRValue
    right: IRValue


@dataclass(frozen=True)
class IRCall(IRInstruction):
    function: str
    arguments: tuple[IRValue, ...] = ()
    result: IRValue | None = None


@dataclass(frozen=True)
class IRBranch(IRInstruction):
    condition: IRValue
    true_target: str
    false_target: str


@dataclass(frozen=True)
class IRJump(IRInstruction):
    target: str


@dataclass(frozen=True)
class IRReturn(IRInstruction):
    value: IRValue | None = None


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


@dataclass
class IRModule:
    functions: list[IRFunction] = field(default_factory=list)
