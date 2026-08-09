"""Conservative, non-speculative loop-invariant code motion for O2.

This first version deliberately moves only scalar SSA operations whose effect
metadata says that evaluation is pure, nonthrowing, nontrapping, and does not
touch memory.  A source block must dominate every loop exit and latch; this
keeps instructions from conditional paths in place.  Zero-iteration motion is
safe for this closed instruction set because evaluating these operations has
no observable effect or failure mode.
"""
from __future__ import annotations

from collections import Counter

from aether.analysis.dominators import DominatorAnalysis
from aether.ir.types import (
    ArrayType,
    ListType,
    MatrixType,
    StringType,
    StructType,
    VectorType,
)
from aether.ssa.analysis import LoopAnalysis
from aether.ssa.cfg import SSACFGBuilder
from aether.ssa.model import (
    SSABasicBlock,
    SSABinaryOp,
    SSACast,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAUnaryOp,
)
from aether.ssa.operands import instruction_operands, instruction_result

from .result import SSAOptimizationResult


_AGGREGATE_TYPES = (
    ArrayType,
    ListType,
    MatrixType,
    StringType,
    StructType,
    VectorType,
)
_SUPPORTED = (SSAConst, SSABinaryOp, SSAUnaryOp, SSACompareOp, SSACast)


class LoopInvariantCodeMotion:
    """Hoist the initial, scalar-only LICM eligibility class to preheaders."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        stats: Counter[str] = Counter(
            {
                "loops_examined": 0,
                "loops_skipped_irreducible": 0,
                "loops_without_preheader": 0,
                "candidate_instructions": 0,
                "instructions_hoisted": 0,
                "blocked_by_may_trap": 0,
                "blocked_by_may_throw": 0,
                "blocked_by_control_speculation": 0,
                "blocked_by_variant_operand": 0,
                "blocked_by_memory_modref": 0,
                "blocked_by_ownership": 0,
                "blocked_by_unsupported_instruction_kind": 0,
            }
        )
        functions = [self._run_function(function, stats) for function in module.functions]
        changed = stats["instructions_hoisted"] != 0
        optimized = SSAModule(functions, list(module.structs)) if changed else module
        return SSAOptimizationResult(optimized, changed, dict(stats))

    def _run_function(self, function: SSAFunction, stats: Counter[str]) -> SSAFunction:
        analysis = LoopAnalysis().compute(function)
        stats["loops_skipped_irreducible"] += len(analysis.irreducible_regions)
        if not analysis.loops:
            return function

        blocks = {
            block.name: SSABasicBlock(block.name, list(block.instructions))
            for block in function.blocks
        }
        order = {block.name: index for index, block in enumerate(function.blocks)}
        dom = DominatorAnalysis(
            SSACFGBuilder().build(function), entry_block=function.entry_block
        ).compute()

        # Inner-to-outer lets an inner invariant subsequently become an outer
        # candidate, while each instruction is always moved only one loop at a time.
        for loop in sorted(
            analysis.loops, key=lambda item: (-item.depth, order[item.header])
        ):
            stats["loops_examined"] += 1
            if loop.preheader is None:
                stats["loops_without_preheader"] += 1
                continue
            definitions = self._definitions(blocks)
            invariant = {
                name
                for name, (owner, _instruction) in definitions.items()
                if owner not in loop.body
            }
            invariant.update(parameter.name for parameter in function.parameters)
            selected: list[tuple[str, SSAInstruction]] = []
            seen: set[int] = set()
            counted: set[int] = set()
            blocked: dict[int, str] = {}
            progress = True
            while progress:
                progress = False
                for block_name in sorted(loop.body, key=order.get):
                    for instruction in blocks[block_name].instructions:
                        identity = id(instruction)
                        if identity in seen:
                            continue
                        result = instruction_result(instruction)
                        if result is None:
                            continue
                        if identity not in counted:
                            stats["candidate_instructions"] += 1
                            counted.add(identity)
                        seen.add(identity)
                        reason = self._blocked_reason(instruction, block_name, loop, dom, invariant)
                        if reason is not None:
                            blocked[identity] = reason
                            # Variant operands can become invariant at the next fixed-point step.
                            if reason == "blocked_by_variant_operand":
                                seen.remove(identity)
                            continue
                        selected.append((block_name, instruction))
                        blocked.pop(identity, None)
                        invariant.add(result.name)
                        stats["instructions_hoisted"] += 1
                        stats[f"hoisted_{type(instruction).__name__}"] += 1
                        progress = True

            stats.update(blocked.values())

            if selected:
                moved = {id(instruction) for _, instruction in selected}
                for block_name in loop.body:
                    blocks[block_name].instructions = [
                        instruction for instruction in blocks[block_name].instructions
                        if id(instruction) not in moved
                    ]
                preheader = blocks[loop.preheader]
                insertion = len(preheader.instructions)
                if insertion and instruction_result(preheader.instructions[-1]) is None:
                    insertion -= 1
                preheader.instructions[insertion:insertion] = [item for _, item in selected]

        if not any(
            blocks[name].instructions != function.blocks[index].instructions
            for name, index in order.items()
        ):
            return function
        return SSAFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            [blocks[block.name] for block in function.blocks],
            function.entry_block,
            function.may_throw,
        )

    @staticmethod
    def _definitions(
        blocks: dict[str, SSABasicBlock],
    ) -> dict[str, tuple[str, SSAInstruction]]:
        result = {}
        for block in blocks.values():
            for instruction in block.instructions:
                value = instruction_result(instruction)
                if value is not None:
                    result[value.name] = (block.name, instruction)
        return result

    @staticmethod
    def _blocked_reason(
        instruction, block_name, loop, dom, invariant: set[str]
    ) -> str | None:
        effects = instruction.effects
        if effects.may_throw:
            return "blocked_by_may_throw"
        if effects.may_trap:
            return "blocked_by_may_trap"
        if effects.reads_memory or effects.writes_memory:
            return "blocked_by_memory_modref"
        if effects.allocates or effects.has_side_effects:
            return "blocked_by_ownership"
        if not isinstance(instruction, _SUPPORTED):
            return "blocked_by_unsupported_instruction_kind"
        result = instruction_result(instruction)
        if result is None or isinstance(result.type, _AGGREGATE_TYPES):
            return "blocked_by_unsupported_instruction_kind"
        required = set(loop.exiting_blocks) | set(loop.latches)
        if any(not dom.dominates(block_name, target) for target in required):
            return "blocked_by_control_speculation"
        if any(operand.name not in invariant for operand in instruction_operands(instruction)):
            return "blocked_by_variant_operand"
        return None
