from __future__ import annotations

from aether.ssa.model import (
    SSABasicBlock,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAValue,
)
from aether.ssa.operands import instruction_operands, instruction_result

from .result import SSAOptimizationResult


class SSADeadCodeEliminator:
    """Remove unused pure SSA value producers."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        removed = 0

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
                instructions: list[SSAInstruction] = []
                for instruction in block.instructions:
                    result = self._pure_result(instruction)
                    if result is not None and result not in used_values:
                        function_removed += 1
                        continue
                    instructions.append(instruction)
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
                    )
                )
                removed += function_removed
            else:
                updated_functions.append(function)

        if not removed:
            return SSAOptimizationResult(module, changed=False, stats={"removed": 0})
        return SSAOptimizationResult(
            SSAModule(updated_functions, list(module.structs)),
            changed=True,
            stats={"removed": removed},
        )

    @staticmethod
    def _pure_result(instruction: SSAInstruction) -> SSAValue | None:
        result = instruction_result(instruction)
        return None if result is None or instruction.must_preserve else result
