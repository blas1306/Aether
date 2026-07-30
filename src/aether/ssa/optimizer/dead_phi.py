from __future__ import annotations

from aether.ssa.model import (
    SSABasicBlock,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAPhi,
    SSAValue,
)
from aether.ssa.operands import instruction_operands

from .result import SSAOptimizationResult


class DeadPhiEliminator:
    """Remove phi nodes whose result has no uses in their function."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        removed_phis = 0

        for function in module.functions:
            used_values = {
                operand
                for block in function.blocks
                for instruction in block.instructions
                for operand in instruction_operands(instruction)
            }
            updated_blocks: list[SSABasicBlock] = []
            function_removed = 0
            for block in function.blocks:
                instructions = [
                    instruction
                    for instruction in block.instructions
                    if not (
                        isinstance(instruction, SSAPhi)
                        and instruction.result not in used_values
                    )
                ]
                function_removed += len(block.instructions) - len(instructions)
                updated_blocks.append(
                    block
                    if len(instructions) == len(block.instructions)
                    else SSABasicBlock(block.name, instructions)
                )

            if function_removed:
                updated_functions.append(
                    SSAFunction(
                        function.name,
                        list(function.parameters),
                        function.return_type,
                        updated_blocks,
                        function.entry_block,
                        function.may_throw,
                    )
                )
                removed_phis += function_removed
            else:
                updated_functions.append(function)

        if not removed_phis:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"removed_phis": 0},
            )
        return SSAOptimizationResult(
            SSAModule(updated_functions, list(module.structs)),
            changed=True,
            stats={"removed_phis": removed_phis},
        )
