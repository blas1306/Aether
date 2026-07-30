from __future__ import annotations

from aether.ssa.model import (
    SSABasicBlock,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAPhi,
    SSAValue,
)
from aether.ssa.operands import rewrite_instruction_operands

from .result import SSAOptimizationResult


class TrivialPhiEliminator:
    """Remove phis whose incoming values are the same SSA value."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        removed_phis = 0
        rewritten_uses = 0

        for function in module.functions:
            replacements = self._collect_replacements(function)
            if not replacements:
                updated_functions.append(function)
                continue

            blocks: list[SSABasicBlock] = []
            function_removed = 0
            function_rewritten = 0
            for block in function.blocks:
                instructions: list[SSAInstruction] = []
                for instruction in block.instructions:
                    if (
                        isinstance(instruction, SSAPhi)
                        and instruction.result in replacements
                    ):
                        function_removed += 1
                        continue
                    rewritten, count = rewrite_instruction_operands(
                        instruction,
                        lambda value: replacements.get(value, value),
                    )
                    instructions.append(rewritten)
                    function_rewritten += count
                blocks.append(
                    block
                    if (
                        function_removed == 0
                        and function_rewritten == 0
                        and len(instructions) == len(block.instructions)
                    )
                    else SSABasicBlock(block.name, instructions)
                )
            updated_functions.append(
                SSAFunction(
                    function.name,
                    list(function.parameters),
                    function.return_type,
                    blocks,
                    function.entry_block,
                    function.may_throw,
                )
            )
            removed_phis += function_removed
            rewritten_uses += function_rewritten

        if not removed_phis and not rewritten_uses:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"removed_trivial_phis": 0, "rewritten_uses": 0},
            )
        return SSAOptimizationResult(
            SSAModule(updated_functions, list(module.structs)),
            changed=True,
            stats={
                "removed_trivial_phis": removed_phis,
                "rewritten_uses": rewritten_uses,
            },
        )

    def _collect_replacements(self, function: SSAFunction) -> dict[SSAValue, SSAValue]:
        candidates: dict[SSAValue, SSAValue] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if not isinstance(instruction, SSAPhi):
                    continue
                common = self._trivial_common_value(instruction)
                if common is not None:
                    candidates[instruction.result] = common

        replacements: dict[SSAValue, SSAValue] = {}
        for result, replacement in candidates.items():
            resolved = self._resolve_candidate(
                replacement,
                candidates,
                seen={result},
            )
            if resolved is not None and resolved != result:
                replacements[result] = resolved
        return replacements

    @staticmethod
    def _trivial_common_value(instruction: SSAPhi) -> SSAValue | None:
        if not instruction.incoming:
            return None
        first = instruction.incoming[0][1]
        if first == instruction.result:
            return None
        if any(
            value == instruction.result or value != first
            for _block_name, value in instruction.incoming[1:]
        ):
            return None
        return first

    @staticmethod
    def _resolve_candidate(
        value: SSAValue,
        candidates: dict[SSAValue, SSAValue],
        *,
        seen: set[SSAValue],
    ) -> SSAValue | None:
        current = value
        while current in candidates:
            if current in seen:
                return None
            seen.add(current)
            current = candidates[current]
        return current
