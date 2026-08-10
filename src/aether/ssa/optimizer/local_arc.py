"""O2.9 Phase-1 elimination of strictly local, proven ARC pairs."""
from __future__ import annotations

from collections import Counter

from aether.ir.types import (
    ArrayType, InterfaceType, ListType, MethodResultType, NullableType,
    StructType,
)
from aether.ssa import model as m
from aether.ssa.analysis import (
    ArcPairClassification, OwnershipEscapeAnalysis, is_reference_like,
)

from .result import SSAOptimizationResult


_CALLS = (
    m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
    m.SSAInterfaceCall, m.SSAInvokeInterface,
)
_EXCEPTION_OPERATIONS = (
    m.SSAInvoke, m.SSAInvokeIndirect, m.SSAInvokeInterface,
    m.SSAPackException, m.SSACatchEntry, m.SSAExceptionDestroy,
    m.SSAThrow, m.SSARethrow, m.SSAPropagate,
)
_STORES = (
    m.SSAClassSet, m.SSAArraySet, m.SSAListSet, m.SSAListPush,
    m.SSAListInsert, m.SSAStructSet,
)
_METHOD_RESULT = (
    m.SSAMethodResultNew, m.SSAMethodResultReceiver, m.SSAMethodResultValue,
)


def _has_nested_owned_payload(type_) -> bool:
    if isinstance(type_, NullableType):
        return _has_nested_owned_payload(type_.inner)
    if isinstance(type_, (ArrayType, ListType)):
        element = type_.element
        return is_reference_like(element) or isinstance(
            element, (StructType, MethodResultType)
        ) or _has_nested_owned_payload(element)
    return False


class LocalARCEliminator:
    """Remove only same-block retain/release pairs authorized by O2.8."""

    _STAT_KEYS = (
        "retain_instructions_examined", "candidate_pairs",
        "phase1_eligible_pairs", "pairs_eliminated",
        "blocked_by_different_identity", "blocked_by_call",
        "blocked_by_escape", "blocked_by_ownership_operation",
        "blocked_by_exception", "blocked_by_aggregate",
        "blocked_by_methodresult_constructor", "blocked_by_interface",
        "blocked_by_unsupported_structure",
    )

    def run(self, module: m.SSAModule) -> SSAOptimizationResult:
        stats: Counter[str] = Counter({key: 0 for key in self._STAT_KEYS})
        functions: list[m.SSAFunction] = []
        changed = False
        for function in module.functions:
            rewritten, removed = self._run_function(function, stats)
            functions.append(rewritten)
            changed |= bool(removed)
        optimized = m.SSAModule(functions, list(module.structs)) if changed else module
        return SSAOptimizationResult(optimized, changed, dict(stats))

    def _run_function(self, function: m.SSAFunction, stats: Counter[str]):
        analysis = OwnershipEscapeAnalysis(function)
        analysis.verify()
        stats["retain_instructions_examined"] += sum(
            isinstance(i, (m.SSACall, m.SSAInvoke))
            and i.builtin == "__aether_retain"
            for block in function.blocks for i in block.instructions
        )
        pairs = analysis.candidate_arc_pairs()
        stats["candidate_pairs"] += len(pairs)
        blocks = {block.name: block for block in function.blocks}
        removals: dict[str, set[int]] = {}
        for pair in pairs:
            reason = self._blocked_reason(function, blocks, analysis, pair)
            if reason is not None:
                stats[reason] += 1
                continue
            stats["phase1_eligible_pairs"] += 1
            # Assertions make the proof boundary explicit in debug/test runs.
            assert analysis.classify_pair(pair) is ArcPairClassification.LOCALLY_PROVABLE
            assert pair.retain_block == pair.release_block
            assert pair.retain_index < pair.release_index
            selected = removals.setdefault(pair.retain_block, set())
            if pair.retain_index in selected or pair.release_index in selected:
                stats["blocked_by_ownership_operation"] += 1
                stats["phase1_eligible_pairs"] -= 1
                continue
            selected.update((pair.retain_index, pair.release_index))
            stats["pairs_eliminated"] += 1

        if not removals:
            return function, 0
        new_blocks = [m.SSABasicBlock(
            block.name,
            [instruction for index, instruction in enumerate(block.instructions)
             if index not in removals.get(block.name, set())],
        ) for block in function.blocks]
        rewritten = m.SSAFunction(
            function.name, list(function.parameters), function.return_type,
            new_blocks, function.entry_block, function.may_throw,
        )
        return rewritten, sum(len(indexes) // 2 for indexes in removals.values())

    def _blocked_reason(self, function, blocks, analysis, pair) -> str | None:
        if pair.retain_block != pair.release_block or pair.retain_index >= pair.release_index:
            return "blocked_by_unsupported_structure"
        provenance = analysis.provenance(pair.value)
        if not provenance.exact:
            return "blocked_by_different_identity"
        type_ = pair.value.type
        if isinstance(type_, InterfaceType):
            return "blocked_by_interface"
        if isinstance(type_, MethodResultType):
            return "blocked_by_methodresult_constructor"
        if isinstance(type_, StructType) or _has_nested_owned_payload(type_):
            return "blocked_by_aggregate"
        lowered_name = function.name.lower()
        if "constructor" in lowered_name or lowered_name.endswith(".__init__"):
            return "blocked_by_methodresult_constructor"

        block = blocks[pair.retain_block]
        region = block.instructions[pair.retain_index + 1:pair.release_index]
        for instruction in region:
            if isinstance(instruction, _EXCEPTION_OPERATIONS):
                return "blocked_by_exception"
            if isinstance(instruction, _CALLS):
                return "blocked_by_call"
            if getattr(instruction, "may_throw", False):
                return "blocked_by_exception"
            if isinstance(instruction, _METHOD_RESULT):
                return "blocked_by_methodresult_constructor"
            if isinstance(instruction, m.SSAInterfaceConstruct):
                return "blocked_by_interface"
            if isinstance(instruction, _STORES) or isinstance(instruction, m.SSAReturn):
                return "blocked_by_escape"
            if instruction.has_side_effects or instruction.writes_memory:
                return "blocked_by_ownership_operation"
            if instruction.may_trap:
                return "blocked_by_exception"
        if analysis.classify_pair(pair) is not ArcPairClassification.LOCALLY_PROVABLE:
            return "blocked_by_escape" if analysis.may_escape(pair.value) else "blocked_by_unsupported_structure"
        return None
