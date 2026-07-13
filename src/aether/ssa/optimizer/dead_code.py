from __future__ import annotations

from aether.ssa.model import (
    SSAArrayGet,
    SSAArrayLength,
    SSAArrayNew,
    SSAArraySlice,
    SSAArraySet,
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACast,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAJump,
    SSAListGet,
    SSAListCopy,
    SSAListContains,
    SSAListClear,
    SSAListPop,
    SSAListPush,
    SSAListInsert,
    SSAListRemoveAt,
    SSAListIndexOf,
    SSAListIsEmpty,
    SSAListLength,
    SSAListNew,
    SSAListSet,
    SSAListReverse,
    SSASequenceSort,
    SSAMatrixColumns,
    SSAMatrixAdd,
    SSAMatrixMatMul,
    SSAMatrixVectorMul,
    SSAMatrixScale,
    SSAMatrixSub,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAMatrixRows,
    SSAMatrixSet,
    SSAModule,
    SSAOuterProduct,
    SSAPrint,
    SSAPhi,
    SSAReturn,
    SSAUnaryOp,
    SSAValue,
    SSAVectorGet,
    SSAVectorAdd,
    SSAVectorDot,
    SSAVectorMatrixMul,
    SSAVectorScale,
    SSAVectorSub,
    SSAVectorLength,
    SSAVectorNew,
    SSAVectorSet,
)

from .result import SSAOptimizationResult


class SSADeadCodeEliminator:
    """Remove unused pure SSA value producers."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        removed = 0

        for function in module.functions:
            used_values = self._collect_used_values(function)
            updated_blocks: list[SSABasicBlock] = []
            function_removed = 0

            for block in function.blocks:
                instructions: list[SSAInstruction] = []
                block_changed = False

                for instruction in block.instructions:
                    result = self._pure_result(instruction)
                    if result is not None and result not in used_values:
                        function_removed += 1
                        block_changed = True
                        continue
                    instructions.append(instruction)

                if block_changed:
                    updated_blocks.append(SSABasicBlock(block.name, instructions))
                else:
                    updated_blocks.append(block)

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

        if removed == 0:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"removed": 0},
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats={"removed": removed},
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

        if isinstance(instruction, SSAUnaryOp):
            used_values.add(instruction.operand)
            return

        if isinstance(instruction, SSACompareOp):
            used_values.add(instruction.left)
            used_values.add(instruction.right)
            return

        if isinstance(instruction, SSACast):
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSACall):
            used_values.update(instruction.arguments)
            return

        if isinstance(instruction, SSAPrint):
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAArrayNew):
            used_values.update(instruction.elements)
            return

        if isinstance(instruction, SSAListNew):
            used_values.update(instruction.elements)
            return

        if isinstance(instruction, SSAListCopy):
            used_values.add(instruction.list_value)
            return

        if isinstance(instruction, SSAListContains):
            used_values.add(instruction.list_value)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAListIndexOf):
            used_values.add(instruction.list_value)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAListClear):
            used_values.add(instruction.list_value)
            return

        if isinstance(instruction, SSAListPush):
            used_values.add(instruction.list_value)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAListInsert):
            used_values.add(instruction.list_value)
            used_values.add(instruction.index)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAListPop):
            used_values.add(instruction.list_value)
            return

        if isinstance(instruction, SSAListRemoveAt):
            used_values.add(instruction.list_value)
            used_values.add(instruction.index)
            return

        if isinstance(instruction, SSAListReverse):
            used_values.add(instruction.list_value)
            return

        if isinstance(instruction, SSASequenceSort):
            used_values.add(instruction.sequence)
            return

        if isinstance(instruction, SSAVectorNew):
            used_values.update(instruction.elements)
            return

        if isinstance(instruction, SSAMatrixNew):
            used_values.update(instruction.elements)
            return

        if isinstance(instruction, (SSAVectorAdd, SSAVectorDot, SSAMatrixAdd, SSAMatrixMatMul, SSAVectorSub, SSAMatrixSub)):
            used_values.add(instruction.left)
            used_values.add(instruction.right)
            return

        if isinstance(instruction, SSAOuterProduct):
            used_values.add(instruction.column)
            used_values.add(instruction.row)
            return

        if isinstance(instruction, SSAMatrixVectorMul):
            used_values.add(instruction.matrix)
            used_values.add(instruction.vector)
            return

        if isinstance(instruction, SSAVectorMatrixMul):
            used_values.add(instruction.vector)
            used_values.add(instruction.matrix)
            return

        if isinstance(instruction, SSAVectorScale):
            used_values.add(instruction.vector)
            used_values.add(instruction.scalar)
            return

        if isinstance(instruction, SSAMatrixScale):
            used_values.add(instruction.matrix)
            used_values.add(instruction.scalar)
            return

        if isinstance(instruction, SSAArrayGet):
            used_values.add(instruction.array)
            used_values.add(instruction.index)
            return

        if isinstance(instruction, SSAArraySlice):
            used_values.add(instruction.array)
            used_values.add(instruction.start)
            used_values.add(instruction.end)
            return

        if isinstance(instruction, SSAListGet):
            used_values.add(instruction.list_value)
            used_values.add(instruction.index)
            return

        if isinstance(instruction, SSAVectorGet):
            used_values.add(instruction.vector)
            used_values.add(instruction.index)
            return

        if isinstance(instruction, SSAMatrixGet):
            used_values.add(instruction.matrix)
            used_values.add(instruction.row)
            used_values.add(instruction.column)
            return

        if isinstance(instruction, SSAArraySet):
            used_values.add(instruction.array)
            used_values.add(instruction.index)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAListSet):
            used_values.add(instruction.list_value)
            used_values.add(instruction.index)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAVectorSet):
            used_values.add(instruction.vector)
            used_values.add(instruction.index)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAMatrixSet):
            used_values.add(instruction.matrix)
            used_values.add(instruction.row)
            used_values.add(instruction.column)
            used_values.add(instruction.value)
            return

        if isinstance(instruction, SSAArrayLength):
            used_values.add(instruction.array)
            return

        if isinstance(instruction, (SSAListLength, SSAListIsEmpty)):
            used_values.add(instruction.list_value)
            return

        if isinstance(instruction, SSAVectorLength):
            used_values.add(instruction.vector)
            return

        if isinstance(instruction, (SSAMatrixRows, SSAMatrixColumns)):
            used_values.add(instruction.matrix)
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

    def _pure_result(self, instruction: SSAInstruction) -> SSAValue | None:
        result = getattr(instruction, "result", None)
        if not isinstance(result, SSAValue) or instruction.must_preserve:
            return None
        return result
