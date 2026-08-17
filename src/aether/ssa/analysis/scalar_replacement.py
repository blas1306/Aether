"""Read-only scalar-replacement readiness analysis.

This module describes aggregate SSA values; it deliberately contains no
rewriter and is not consumed by any optimization profile.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from aether.ir.types import MethodResultType, StructType
from aether.ssa import model as m
from aether.ssa.analysis.aggregate_lifetime import AggregateLifetimeAnalysis
from aether.ssa.analysis.ownership_escape import is_reference_like


class FieldUseKind(Enum):
    FIELD_READ = "FIELD_READ"
    FIELD_WRITE = "FIELD_WRITE"
    WHOLE_AGGREGATE_COPY = "WHOLE_AGGREGATE_COPY"
    WHOLE_AGGREGATE_COMPARE = "WHOLE_AGGREGATE_COMPARE"
    CALL_ARGUMENT = "CALL_ARGUMENT"
    RETURN = "RETURN"
    STORE = "STORE"
    METHOD_RECEIVER = "METHOD_RECEIVER"
    PHI = "PHI"
    DESTRUCTION = "DESTRUCTION"
    OTHER = "OTHER"


@dataclass(frozen=True)
class AggregateUse:
    block: str
    instruction_index: int
    kind: FieldUseKind
    instruction: str
    field_index: int | None = None
    field_name: str | None = None


def _operands(instruction) -> tuple[m.SSAValue, ...]:
    values: list[m.SSAValue] = []
    for item in fields(instruction):
        if item.name in {"result", "exception"}:
            continue
        value = getattr(instruction, item.name)
        if isinstance(value, m.SSAValue):
            values.append(value)
        elif isinstance(value, tuple):
            for nested in value:
                if isinstance(nested, m.SSAValue):
                    values.append(nested)
                elif isinstance(nested, tuple):
                    values.extend(x for x in nested if isinstance(x, m.SSAValue))
    return tuple(values)


def aggregate_field_uses(function: m.SSAFunction, value: m.SSAValue) -> tuple[AggregateUse, ...]:
    result: list[AggregateUse] = []
    calls = (m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
             m.SSAInterfaceCall, m.SSAInvokeInterface)
    stores = (m.SSAClassSet, m.SSAArraySet, m.SSAListSet, m.SSAListPush, m.SSAListInsert)
    for block in function.blocks:
        for index, instruction in enumerate(block.instructions):
            if value not in _operands(instruction):
                continue
            field_index = field_name = None
            if isinstance(instruction, m.SSAStructGet) and instruction.struct == value:
                kind = FieldUseKind.FIELD_READ
                field_index, field_name = instruction.field_index, instruction.field_name
            elif isinstance(instruction, m.SSAStructSet) and instruction.struct == value:
                kind = FieldUseKind.FIELD_WRITE
                field_index, field_name = instruction.field_index, instruction.field_name
            elif isinstance(instruction, m.SSAPhi): kind = FieldUseKind.PHI
            elif isinstance(instruction, m.SSAReturn): kind = FieldUseKind.RETURN
            elif isinstance(instruction, stores): kind = FieldUseKind.STORE
            elif isinstance(instruction, (m.SSAMethodResultNew, m.SSAMethodResultReceiver)):
                kind = FieldUseKind.METHOD_RECEIVER
            elif isinstance(instruction, calls):
                kind = (FieldUseKind.DESTRUCTION if getattr(instruction, "builtin", None) == "__aether_release"
                        else FieldUseKind.CALL_ARGUMENT)
            elif isinstance(instruction, (m.SSACompareOp,)):
                kind = FieldUseKind.WHOLE_AGGREGATE_COMPARE
            elif isinstance(instruction, (m.SSAStructNew, m.SSAStructSet)):
                kind = FieldUseKind.WHOLE_AGGREGATE_COPY
            else: kind = FieldUseKind.OTHER
            result.append(AggregateUse(block.name, index, kind, type(instruction).__name__, field_index, field_name))
    return tuple(result)


def aggregate_reconstruction_boundaries(function: m.SSAFunction, value: m.SSAValue) -> tuple[AggregateUse, ...]:
    boundary = {FieldUseKind.CALL_ARGUMENT, FieldUseKind.RETURN, FieldUseKind.STORE,
                FieldUseKind.METHOD_RECEIVER, FieldUseKind.WHOLE_AGGREGATE_COMPARE,
                FieldUseKind.PHI, FieldUseKind.OTHER}
    return tuple(use for use in aggregate_field_uses(function, value) if use.kind in boundary)


def scalar_replacement_region(function: m.SSAFunction, value: m.SSAValue) -> str:
    uses = aggregate_field_uses(function, value)
    blocks = {use.block for use in uses if use.kind is not FieldUseKind.DESTRUCTION}
    if len(blocks) <= 1: return "SAME_BLOCK"
    if any(use.kind is FieldUseKind.PHI for use in uses): return "PHI_SPANNING"
    return "BRANCH_SPANNING"


def classify_scalar_replacement(function: m.SSAFunction, value: m.SSAValue, structs=()) -> str:
    definition = next((item for item in structs if getattr(item, "name", None) == getattr(value.type, "name", None)), None)
    field_types = tuple(type_ for _, type_ in getattr(definition, "fields", ()))
    uses = aggregate_field_uses(function, value)
    forbidden = {FieldUseKind.CALL_ARGUMENT, FieldUseKind.RETURN, FieldUseKind.STORE,
                 FieldUseKind.METHOD_RECEIVER, FieldUseKind.WHOLE_AGGREGATE_COMPARE,
                 FieldUseKind.PHI, FieldUseKind.OTHER}
    if not isinstance(value.type, StructType) or definition is None: return "UNKNOWN"
    if any(is_reference_like(type_) for type_ in field_types): return "OWNERSHIP_AWARE_REQUIRED"
    if any(use.kind in forbidden for use in uses): return "SAFE_WITH_RECONSTRUCTION_BOUNDARY"
    return "SAFE_SCALAR_ONLY"


def scalar_replacement_profitability(function: m.SSAFunction, value: m.SSAValue) -> dict[str, int]:
    uses = aggregate_field_uses(function, value)
    counts = {kind.value.lower(): sum(use.kind is kind for use in uses) for kind in FieldUseKind}
    counts["reconstruction_boundaries"] = len(aggregate_reconstruction_boundaries(function, value))
    return counts


def aggregate_lifetime(function: m.SSAFunction, value: m.SSAValue, structs=()):
    return AggregateLifetimeAnalysis(function, structs).aggregate_lifetime(value)
