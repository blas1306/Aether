"""Read-only coverage audit for runtime bounds and shape checks.

This module is deliberately not an optimizer pass.  It discovers checks already
represented by SSA and asks the O2.1 analyses what they can prove; it never
rewrites the supplied module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
from typing import Any, Iterable

from aether.ssa.cfg import predecessors
from aether.ssa.model import (
    SSAArrayGet, SSAArraySet, SSAArraySlice, SSACall, SSACallIndirect,
    SSAFunction, SSAInterfaceCall, SSAInvoke, SSAInvokeIndirect,
    SSAInvokeInterface, SSAListGet, SSAListSet, SSAListSlice, SSAMatrixGet,
    SSAListClear, SSAListInsert, SSAListPop, SSAListPush, SSAListRemoveAt,
    SSAMatrixSet, SSAModule, SSAValue, SSAVectorGet, SSAVectorSet,
)
from .loops import LoopAnalysis
from .ranges import ProofResult, RangeAnalysis
from .shapes import LengthFact, ShapeAnalysis


class CheckKind(str, Enum):
    ARRAY_INDEX = "array_index"
    LIST_INDEX = "list_index"
    LIST_INSERT_INDEX = "list_insert_index"
    LIST_REMOVE_INDEX = "list_remove_index"
    LIST_POP_NONEMPTY = "list_pop_nonempty"
    VECTOR_INDEX = "vector_index"
    MATRIX_ROW = "matrix_row"
    MATRIX_COLUMN = "matrix_column"
    ARRAY_SLICE = "array_slice"
    LIST_SLICE = "list_slice"


class CheckProof(str, Enum):
    PROVEN_SAFE = "PROVEN_SAFE"
    PROVEN_UNSAFE = "PROVEN_UNSAFE"
    UNKNOWN = "UNKNOWN"


class UnknownReason(str, Enum):
    UNKNOWN_RANGE = "UNKNOWN_RANGE"
    UNKNOWN_LENGTH = "UNKNOWN_LENGTH"
    UNKNOWN_SHAPE = "UNKNOWN_SHAPE"
    MUTATION_INVALIDATION = "MUTATION_INVALIDATION"
    CALL_INVALIDATION = "CALL_INVALIDATION"
    ALIAS_UNCERTAINTY = "ALIAS_UNCERTAINTY"
    NONCANONICAL_LOOP = "NONCANONICAL_LOOP"
    NONCONSTANT_STEP = "NONCONSTANT_STEP"
    IRREDUCIBLE_CFG = "IRREDUCIBLE_CFG"
    JOIN_LOSS = "JOIN_LOSS"
    EXCEPTION_EDGE = "EXCEPTION_EDGE"
    UNSUPPORTED_ARITHMETIC = "UNSUPPORTED_ARITHMETIC"
    MISSING_RELATION_BETWEEN_VALUES = "MISSING_RELATION_BETWEEN_VALUES"
    OTHER = "OTHER"


@dataclass(frozen=True)
class CheckRecord:
    kind: str
    domain: str
    function: str
    block: str
    instruction_index: int
    instruction: str
    panic_behavior: str
    operands: tuple[str, ...]
    source_location: str | None
    visible_at_ssa: bool
    proof_queryable: bool
    proof: str
    unknown_reason: str | None
    loop_context: str


@dataclass(frozen=True)
class CoverageReport:
    schema_version: int
    checks: tuple[CheckRecord, ...]

    def summary(self) -> dict[str, Any]:
        domains: dict[str, dict[str, Any]] = {}
        contexts: dict[str, dict[str, int]] = {}
        for record in self.checks:
            bucket = domains.setdefault(record.domain, _empty_metrics())
            bucket[record.proof] += 1
            bucket["total"] += 1
            if record.unknown_reason:
                reasons = bucket.setdefault("unknown_reasons", {})
                reasons[record.unknown_reason] = reasons.get(record.unknown_reason, 0) + 1
            context = contexts.setdefault(record.loop_context, _empty_counts())
            context[record.proof] += 1; context["total"] += 1
        for bucket in domains.values():
            bucket["safe_percentage"] = round(
                100.0 * bucket[CheckProof.PROVEN_SAFE.value] / bucket["total"], 2
            ) if bucket["total"] else 0.0
            bucket["unknown_reasons"] = dict(sorted(bucket.get("unknown_reasons", {}).items()))
        return {"domains": dict(sorted(domains.items())), "loop_contexts": dict(sorted(contexts.items()))}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "summary": self.summary(),
            "checks": [asdict(check) for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class ProofCoverageAudit:
    """Inventory and classify SSA-visible runtime checks without mutation."""

    def audit(self, module: SSAModule | Iterable[SSAFunction]) -> CoverageReport:
        functions = module.functions if isinstance(module, SSAModule) else module
        records: list[CheckRecord] = []
        for function in sorted(functions, key=lambda item: item.name):
            records.extend(self._function(function))
        records.sort(key=lambda item: (item.function, item.block, item.instruction_index, item.kind))
        return CoverageReport(1, tuple(records))

    def _function(self, function: SSAFunction) -> list[CheckRecord]:
        ranges = RangeAnalysis().compute(function)
        shapes = ShapeAnalysis().compute(function)
        loops = LoopAnalysis().compute(function)
        result: list[CheckRecord] = []
        for block in function.blocks:
            context = _loop_context(function, block.name, loops)
            for position, instruction in enumerate(block.instructions):
                specs = _check_specs(instruction)
                for kind, collection, values, base in specs:
                    fact = _length_fact(shapes, collection, block.name, kind, instruction)
                    proof, reason = _classify(
                        values, base, fact, ranges, block.name,
                        is_slice=kind in {CheckKind.ARRAY_SLICE, CheckKind.LIST_SLICE},
                        allow_end=kind is CheckKind.LIST_INSERT_INDEX,
                    )
                    if proof is CheckProof.UNKNOWN:
                        reason = _refine_reason(reason, function, block.name, position, collection, loops)
                    result.append(CheckRecord(
                        kind.value, _domain(kind), function.name, block.name, position,
                        type(instruction).__name__, _panic(kind),
                        tuple(value.name for value in (collection, *values)),
                        _source_location(getattr(instruction, "source_location", None)),
                        True, fact is not None, proof.value,
                        reason.value if reason else None, context,
                    ))
        return result


def _empty_counts() -> dict[str, int]:
    return {"total": 0, CheckProof.PROVEN_SAFE.value: 0, CheckProof.PROVEN_UNSAFE.value: 0, CheckProof.UNKNOWN.value: 0}


def _empty_metrics() -> dict[str, Any]:
    return {**_empty_counts(), "unknown_reasons": {}}


def _check_specs(instruction):
    if isinstance(instruction, (SSAArrayGet, SSAArraySet)):
        return [(CheckKind.ARRAY_INDEX, instruction.array, (instruction.index,), 0)]
    if isinstance(instruction, (SSAListGet, SSAListSet)):
        return [(CheckKind.LIST_INDEX, instruction.list_value, (instruction.index,), 0)]
    if isinstance(instruction, SSAListInsert):
        return [(CheckKind.LIST_INSERT_INDEX, instruction.list_value, (instruction.index,), 0)]
    if isinstance(instruction, SSAListRemoveAt):
        return [(CheckKind.LIST_REMOVE_INDEX, instruction.list_value, (instruction.index,), 0)]
    if isinstance(instruction, SSAListPop):
        return [(CheckKind.LIST_POP_NONEMPTY, instruction.list_value, (), 0)]
    if isinstance(instruction, (SSAVectorGet, SSAVectorSet)):
        return [(CheckKind.VECTOR_INDEX, instruction.vector, (instruction.index,), 1)]
    if isinstance(instruction, (SSAMatrixGet, SSAMatrixSet)):
        return [
            (CheckKind.MATRIX_ROW, instruction.matrix, (instruction.row,), 1),
            (CheckKind.MATRIX_COLUMN, instruction.matrix, (instruction.column,), 1),
        ]
    if isinstance(instruction, SSAArraySlice):
        return [(CheckKind.ARRAY_SLICE, instruction.array, (instruction.start, instruction.end), 0)]
    if isinstance(instruction, SSAListSlice):
        return [(CheckKind.LIST_SLICE, instruction.list_value, (instruction.start, instruction.end), 0)]
    return []


def _length_fact(shapes, collection, block, kind, instruction):
    if kind is CheckKind.MATRIX_ROW:
        fact = shapes.matrix_shape_of(collection, block)
        return None if fact is None else LengthFact(collection, constant=fact.rows, provenance=fact.provenance, stable=fact.stable)
    if kind is CheckKind.MATRIX_COLUMN:
        fact = shapes.matrix_shape_of(collection, block)
        columns = fact.columns if fact else getattr(instruction, "cols", None)
        return None if columns is None else LengthFact(collection, constant=columns, provenance=fact.provenance if fact else "instruction-metadata", stable=True)
    return shapes.length_of(collection, block)


def _bound(value, base, fact, ranges, block, *, inclusive_high=False):
    value_range = ranges.range_of(value, block)
    lower = value_range.lower
    low_true = lower is not None and lower.value is None and lower.offset >= base
    upper = value_range.upper
    if fact.constant is not None:
        high_true = upper is not None and upper.value is None and (
            upper.offset <= fact.constant if inclusive_high else upper.offset < fact.constant + base
        )
        low_false = upper is not None and upper.value is None and upper.offset < base
        high_false = lower is not None and lower.value is None and (
            lower.offset > fact.constant if inclusive_high else lower.offset >= fact.constant + base
        )
    elif fact.value is not None:
        high = ranges.prove_less_than(value, fact.value, block)
        high_true, high_false = high is ProofResult.PROVEN_TRUE, high is ProofResult.PROVEN_FALSE
        low_false = upper is not None and upper.value is None and upper.offset < base
    else:
        return CheckProof.UNKNOWN, UnknownReason.UNKNOWN_LENGTH
    if low_false or high_false: return CheckProof.PROVEN_UNSAFE, None
    if low_true and high_true: return CheckProof.PROVEN_SAFE, None
    return CheckProof.UNKNOWN, UnknownReason.UNKNOWN_RANGE if not low_true else UnknownReason.MISSING_RELATION_BETWEEN_VALUES


def _classify(values, base, fact, ranges, block, *, is_slice=False, allow_end=False):
    if fact is None: return CheckProof.UNKNOWN, UnknownReason.UNKNOWN_SHAPE if base == 1 else UnknownReason.UNKNOWN_LENGTH
    if not values:
        if fact.constant is None: return CheckProof.UNKNOWN, UnknownReason.UNKNOWN_LENGTH
        return (CheckProof.PROVEN_SAFE, None) if fact.constant > 0 else (CheckProof.PROVEN_UNSAFE, None)
    proofs = [_bound(value, base, fact, ranges, block, inclusive_high=is_slice or allow_end) for value in values]
    if any(proof is CheckProof.PROVEN_UNSAFE for proof, _ in proofs): return CheckProof.PROVEN_UNSAFE, None
    if len(values) == 2:  # half-open slice additionally requires start <= end
        ordering = ranges.prove_less_equal(values[0], values[1], block)
        if ordering is ProofResult.PROVEN_FALSE: return CheckProof.PROVEN_UNSAFE, None
        if ordering is not ProofResult.PROVEN_TRUE:
            return CheckProof.UNKNOWN, UnknownReason.MISSING_RELATION_BETWEEN_VALUES
    if all(proof is CheckProof.PROVEN_SAFE for proof, _ in proofs): return CheckProof.PROVEN_SAFE, None
    return next((item for item in proofs if item[0] is CheckProof.UNKNOWN), (CheckProof.UNKNOWN, UnknownReason.OTHER))


def _refine_reason(reason, function, block, position, collection, loops):
    if any(block in region.blocks for region in loops.irreducible_regions): return UnknownReason.IRREDUCIBLE_CFG
    current = next(item for item in function.blocks if item.name == block)
    before = current.instructions[:position]
    mutations = (SSAListClear, SSAListPush, SSAListInsert, SSAListRemoveAt, SSAListPop)
    if any(isinstance(item, mutations) and item.list_value == collection for item in before):
        return UnknownReason.MUTATION_INVALIDATION
    if any(isinstance(item, (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface)) for item in before): return UnknownReason.EXCEPTION_EDGE
    calls = (SSACall, SSACallIndirect, SSAInterfaceCall, SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface)
    if any(isinstance(item, calls) and item.writes_memory for item in before): return UnknownReason.CALL_INVALIDATION
    by_name = {item.name: item for item in function.blocks}
    for edge in predecessors(function).get(block, ()):
        terminator = by_name[edge.source].instructions[-1]
        if isinstance(terminator, (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface)):
            return UnknownReason.EXCEPTION_EDGE if edge.kind == "exceptional" else UnknownReason.CALL_INVALIDATION
    return reason


def _loop_context(function, block, loops):
    loop = loops.loop_for_block(block)
    if loop is None: return "outside_loops"
    instructions = [i for b in function.blocks if b.name in loop.body for i in b.instructions]
    if any(isinstance(i, (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface)) for i in instructions): return "exceptional_cfg"
    if any(isinstance(i, (SSACall, SSACallIndirect, SSAInterfaceCall)) for i in instructions): return "loop_with_calls"
    if any(i.writes_memory for i in instructions): return "loop_with_mutation"
    return "nested_loop" if loop.depth > 1 else "simple_natural_loop"


def _domain(kind):
    if kind in {CheckKind.ARRAY_INDEX}: return "Array"
    if kind in {CheckKind.LIST_INDEX, CheckKind.LIST_INSERT_INDEX, CheckKind.LIST_REMOVE_INDEX, CheckKind.LIST_POP_NONEMPTY}: return "List"
    if kind is CheckKind.VECTOR_INDEX: return "Vector"
    if kind in {CheckKind.MATRIX_ROW, CheckKind.MATRIX_COLUMN}: return "Matrix"
    return "slicing"


def _panic(kind):
    return {
        CheckKind.ARRAY_INDEX: "Aether panic: Array index out of bounds",
        CheckKind.LIST_INDEX: "Aether panic: List index out of bounds",
        CheckKind.LIST_INSERT_INDEX: "Aether panic: insert() index is out of bounds",
        CheckKind.LIST_REMOVE_INDEX: "Aether panic: removeAt() index is out of bounds",
        CheckKind.LIST_POP_NONEMPTY: "Aether panic: pop() called on empty List",
        CheckKind.VECTOR_INDEX: "Aether panic: Vector index out of bounds",
        CheckKind.MATRIX_ROW: "Aether panic: Matrix index out of bounds",
        CheckKind.MATRIX_COLUMN: "Aether panic: Matrix index out of bounds",
        CheckKind.ARRAY_SLICE: "Aether panic: Array slice index out of bounds",
        CheckKind.LIST_SLICE: "Aether panic: List slice index out of bounds",
    }[kind]


def _source_location(location):
    if location is None: return None
    return str(location)
