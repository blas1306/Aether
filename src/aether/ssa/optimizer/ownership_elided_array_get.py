"""O2.9.5/O2.9.7 qualified borrowed Array<String> extraction."""
from __future__ import annotations

from dataclasses import fields, replace

from aether.ir.types import ArrayType, StringType
from aether.ssa.analysis import (
    BorrowInvalidationReason, CollectionExtractionBorrowAnalysis,
    ExtractionBorrowClassification,
)
from aether.ssa.analysis.alias_modref import SummaryAnalysis
from aether.ssa.analysis.consumer_ownership import (
    BorrowedArgumentAcceptance, consumer_accepts_borrowed_arg,
)
from aether.ssa.model import (
    SSAArrayGet, SSABasicBlock, SSACall, SSACompareOp, SSAFunction, SSAModule,
    SSAValue,
)

from .result import SSAOptimizationResult


def _operands(instruction) -> tuple[SSAValue, ...]:
    result: list[SSAValue] = []
    for field in fields(instruction):
        if field.name in {"result", "exception"}:
            continue
        item = getattr(instruction, field.name)
        if isinstance(item, SSAValue):
            result.append(item)
        elif isinstance(item, tuple):
            result.extend(value for value in item if isinstance(value, SSAValue))
    return tuple(result)


class OwnershipElidedArrayGet:
    """Borrow qualified direct projections and immediate String consumers."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        summaries = SummaryAnalysis().compute(module)
        stats = {name: 0 for name in (
            "array_string_gets_examined", "target_candidates_recognized",
            "qualified", "transformed", "retains_removed", "releases_removed",
            "blocked_escape", "blocked_call", "blocked_mutation", "blocked_alias",
            "blocked_array_lifetime", "blocked_exception", "blocked_backedge",
            "blocked_ownership_use", "blocked_other",
            "direct_projection_candidates", "direct_projection_transformed",
            "immediate_candidates_examined", "immediate_qualified",
            "immediate_transformed", "blocked_multiple_uses",
            "blocked_consumer_ownership", "blocked_unknown_consumer",
            "blocked_alias_mutation",
        )}
        functions: list[SSAFunction] = []
        log: list[dict[str, str]] = []
        for function in module.functions:
            analysis = CollectionExtractionBorrowAnalysis(
                function, structs=module.structs, summaries=summaries
            )
            uses: dict[SSAValue, list[tuple[str, int, object]]] = {}
            releases: dict[SSAValue, list[tuple[str, int]]] = {}
            for block in function.blocks:
                for index, instruction in enumerate(block.instructions):
                    for operand in _operands(instruction):
                        uses.setdefault(operand, []).append((block.name, index, instruction))
                    if self._is_release(instruction):
                        releases.setdefault(instruction.arguments[0], []).append((block.name, index))

            candidates: dict[SSAValue, str] = {}
            for block in function.blocks:
                for index, instruction in enumerate(block.instructions):
                    if not isinstance(instruction, SSAArrayGet) or instruction.borrowed:
                        continue
                    if not (
                        isinstance(instruction.result.type, StringType)
                        and isinstance(instruction.array.type, ArrayType)
                        and isinstance(instruction.array.type.element, StringType)
                    ):
                        continue
                    stats["array_string_gets_examined"] += 1
                    semantic = [use for use in uses.get(instruction.result, ())
                                if not self._is_arc(use[2])]
                    direct = len(semantic) == 1 and isinstance(semantic[0][2], SSACompareOp)
                    if direct:
                        stats["target_candidates_recognized"] += 1
                        stats["direct_projection_candidates"] += 1
                    immediate = self._immediate_consumer(block.name, index, instruction.result, semantic)
                    if immediate is not None and not direct:
                        stats["immediate_candidates_examined"] += 1
                    row = analysis._results[instruction.result]
                    blocker = self._blocker(
                        analysis, block.name, row, semantic,
                        releases.get(instruction.result, ()), direct, immediate,
                    )
                    if blocker:
                        stats[blocker] += 1
                        continue
                    mode = "direct_projection" if direct else "immediate_borrow"
                    candidates[instruction.result] = mode
                    stats["qualified"] += 1
                    if mode == "immediate_borrow":
                        stats["immediate_qualified"] += 1

            blocks: list[SSABasicBlock] = []
            for block in function.blocks:
                rewritten = []
                for instruction in block.instructions:
                    if isinstance(instruction, SSAArrayGet) and instruction.result in candidates:
                        instruction = replace(instruction, borrowed=True, borrow_scope=block.name)
                        stats["transformed"] += 1
                        mode = candidates[instruction.result]
                        stats[("direct_projection_transformed" if mode == "direct_projection"
                               else "immediate_transformed")] += 1
                        stats["retains_removed"] += 1  # retain is implicit in owned lowering
                        log.append({"function": function.name, "block": block.name,
                                    "result": instruction.result.name, "ownership": "borrowed"})
                    elif self._is_release(instruction) and instruction.arguments[0] in candidates:
                        stats["releases_removed"] += 1
                        continue
                    rewritten.append(instruction)
                blocks.append(SSABasicBlock(block.name, rewritten))
            functions.append(SSAFunction(
                function.name, list(function.parameters), function.return_type, blocks,
                function.entry_block, function.may_throw,
            ))
        optimized = SSAModule(functions, list(module.structs))
        if optimized == module:
            optimized = module
        return SSAOptimizationResult(
            optimized, optimized is not module, stats, tuple(log)
        )

    @staticmethod
    def _is_arc(instruction) -> bool:
        return isinstance(instruction, SSACall) and instruction.builtin in {
            "__aether_retain", "__aether_release"
        }

    @staticmethod
    def _is_release(instruction) -> bool:
        return (isinstance(instruction, SSACall)
                and instruction.builtin == "__aether_release"
                and len(instruction.arguments) == 1)

    @staticmethod
    def _immediate_consumer(block, get_index, result, semantic):
        if len(semantic) != 1:
            return None
        use_block, use_index, consumer = semantic[0]
        if use_block != block or use_index != get_index + 1:
            return None
        operands = _operands(consumer)
        positions = [index for index, operand in enumerate(operands) if operand == result]
        if len(positions) != 1:
            return None
        return consumer, positions[0]

    @staticmethod
    def _blocker(analysis, block, row, semantic, releases, direct, immediate):
        if not direct:
            if len(semantic) != 1:
                return "blocked_multiple_uses"
            if immediate is None:
                return "blocked_ownership_use"
            acceptance = consumer_accepts_borrowed_arg(*immediate)
            if acceptance is BorrowedArgumentAcceptance.UNKNOWN:
                return "blocked_unknown_consumer"
            if acceptance is not BorrowedArgumentAcceptance.YES:
                return "blocked_consumer_ownership"
        reasons = set(row.blocker_reasons)
        if row.classification is not ExtractionBorrowClassification.BORROWABLE_IMMEDIATE_USE:
            if reasons & {BorrowInvalidationReason.AGGREGATE_ESCAPE,
                          BorrowInvalidationReason.COMPONENT_ESCAPE}:
                return "blocked_escape"
            if BorrowInvalidationReason.EXCEPTION_REGION in reasons:
                return "blocked_exception"
            if BorrowInvalidationReason.COLLECTION_ALIAS_MUTATION in reasons:
                return "blocked_alias"
            if BorrowInvalidationReason.COLLECTION_MUTATION in reasons:
                return "blocked_mutation"
            if BorrowInvalidationReason.UNKNOWN_CALL in reasons:
                return "blocked_call"
            if BorrowInvalidationReason.BORROW_CROSSES_BACKEDGE in reasons:
                return "blocked_backedge"
            return "blocked_other"
        if analysis.loops.loop_for_block(block) is None:
            return "blocked_other"
        # Exactly one post-use lifecycle release proves the matching owned edge.
        if len(releases) != 1 or releases[0][0] != block or releases[0][1] <= semantic[0][1]:
            return "blocked_array_lifetime"
        return None
