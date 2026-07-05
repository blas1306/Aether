from __future__ import annotations

from aether.ssa.model import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAJump,
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAValue,
)

from .result import SSAOptimizationResult


class DeadPhiEliminator:
    """Remove phi nodes whose result has no uses in their function."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        removed_phis = 0

        for function in module.functions:
            used_values = self._collect_used_values(function)
            updated_blocks: list[SSABasicBlock] = []
            function_removed_phis = 0

            for block in function.blocks:
                instructions: list[SSAInstruction] = []
                block_changed = False

                for instruction in block.instructions:
                    if (
                        isinstance(instruction, SSAPhi)
                        and instruction.result not in used_values
                    ):
                        function_removed_phis += 1
                        block_changed = True
                        continue
                    instructions.append(instruction)

                if block_changed:
                    updated_blocks.append(SSABasicBlock(block.name, instructions))
                else:
                    updated_blocks.append(block)

            if function_removed_phis:
                updated_functions.append(
                    SSAFunction(
                        function.name,
                        list(function.parameters),
                        function.return_type,
                        updated_blocks,
                        function.entry_block,
                    )
                )
                removed_phis += function_removed_phis
            else:
                updated_functions.append(function)

        if removed_phis == 0:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"removed_phis": 0},
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats={"removed_phis": removed_phis},
        )

    def _collect_used_values(self, function: SSAFunction) -> set[SSAValue]:
        used_values: set[SSAValue] = set()

        for block in function.blocks:
            for instruction in block.instructions:
                self._add_instruction_uses(instruction, used_values)

        return used_values

    def _add_instruction_uses(
        self,
        instruction: SSAInstruction,
        used_values: set[SSAValue],
    ) -> None:
        if isinstance(instruction, SSAConst):
            return

        if isinstance(instruction, SSABinaryOp):
            used_values.add(instruction.left)
            used_values.add(instruction.right)
            return

        if isinstance(instruction, SSACompareOp):
            used_values.add(instruction.left)
            used_values.add(instruction.right)
            return

        if isinstance(instruction, SSACall):
            used_values.update(instruction.arguments)
            return

        if isinstance(instruction, SSAPhi):
            for _block_name, value in instruction.incoming:
                used_values.add(value)
            return

        if isinstance(instruction, SSABranch):
            used_values.add(instruction.condition)
            return

        if isinstance(instruction, SSAJump):
            return

        if isinstance(instruction, SSAReturn):
            if instruction.value is not None:
                used_values.add(instruction.value)
            return
