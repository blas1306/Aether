from __future__ import annotations

from aether.ssa.model import (
    SSAArrayGet,
    SSAArrayLength,
    SSAArrayNew,
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
    SSAModule,
    SSAOuterProduct,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
    SSAVectorAdd,
    SSAVectorDot,
    SSAVectorMatrixMul,
    SSAVectorScale,
    SSAVectorSub,
    SSAVectorLength,
    SSAVectorNew,
)

from .result import SSAOptimizationResult


class TrivialPhiEliminator:
    """Remove phi nodes whose incoming values are all the same SSA value."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        removed_trivial_phis = 0
        rewritten_uses = 0

        for function in module.functions:
            replacements = self._collect_replacements(function)
            if not replacements:
                updated_functions.append(function)
                continue

            updated_blocks: list[SSABasicBlock] = []
            function_removed_phis = 0
            function_rewritten_uses = 0

            for block in function.blocks:
                instructions: list[SSAInstruction] = []
                block_changed = False

                for instruction in block.instructions:
                    if (
                        isinstance(instruction, SSAPhi)
                        and instruction.result in replacements
                    ):
                        function_removed_phis += 1
                        block_changed = True
                        continue

                    rewritten, instruction_rewritten_uses = self._rewrite_instruction(
                        instruction,
                        replacements,
                    )
                    function_rewritten_uses += instruction_rewritten_uses
                    if rewritten is not instruction:
                        block_changed = True
                    instructions.append(rewritten)

                if block_changed:
                    updated_blocks.append(SSABasicBlock(block.name, instructions))
                else:
                    updated_blocks.append(block)

            updated_functions.append(
                SSAFunction(
                    function.name,
                    list(function.parameters),
                    function.return_type,
                    updated_blocks,
                    function.entry_block,
                )
            )
            removed_trivial_phis += function_removed_phis
            rewritten_uses += function_rewritten_uses

        changed = removed_trivial_phis > 0 or rewritten_uses > 0
        if not changed:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={
                    "removed_trivial_phis": 0,
                    "rewritten_uses": 0,
                },
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats={
                "removed_trivial_phis": removed_trivial_phis,
                "rewritten_uses": rewritten_uses,
            },
        )

    def _collect_replacements(self, function: SSAFunction) -> dict[SSAValue, SSAValue]:
        candidates: dict[SSAValue, SSAValue] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if not isinstance(instruction, SSAPhi):
                    continue
                common_value = self._trivial_common_value(instruction)
                if common_value is not None:
                    candidates[instruction.result] = common_value

        replacements: dict[SSAValue, SSAValue] = {}
        for result, replacement in candidates.items():
            resolved = self._resolve_candidate_replacement(
                replacement,
                candidates,
                seen={result},
            )
            if resolved is not None and resolved != result:
                replacements[result] = resolved
        return replacements

    def _trivial_common_value(self, instruction: SSAPhi) -> SSAValue | None:
        if not instruction.incoming:
            return None

        first_value = instruction.incoming[0][1]
        if first_value == instruction.result:
            return None

        for _block_name, value in instruction.incoming[1:]:
            if value == instruction.result or value != first_value:
                return None

        return first_value

    def _resolve_candidate_replacement(
        self,
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

    def _rewrite_instruction(
        self,
        instruction: SSAInstruction,
        replacements: dict[SSAValue, SSAValue],
    ) -> tuple[SSAInstruction, int]:
        if isinstance(instruction, SSAConst):
            return instruction, 0

        if isinstance(instruction, SSABinaryOp):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSABinaryOp(instruction.result, instruction.operator, left, right),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSACompareOp):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSACompareOp(instruction.result, instruction.operator, left, right),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSACast):
            value, rewritten = self._rewrite_value(instruction.value, replacements)
            if not rewritten:
                return instruction, 0
            return SSACast(instruction.result, value), 1

        if isinstance(instruction, SSACall):
            arguments = []
            rewritten_uses = 0
            for argument in instruction.arguments:
                rewritten_argument, rewritten = self._rewrite_value(
                    argument,
                    replacements,
                )
                arguments.append(rewritten_argument)
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return (
                SSACall(
                    instruction.function,
                    tuple(arguments),
                    instruction.result,
                ),
                rewritten_uses,
            )

        if isinstance(instruction, SSAArrayNew):
            elements = []
            rewritten_uses = 0
            for element in instruction.elements:
                rewritten_element, rewritten = self._rewrite_value(element, replacements)
                elements.append(rewritten_element)
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return SSAArrayNew(instruction.result, tuple(elements)), rewritten_uses

        if isinstance(instruction, SSAListNew):
            elements = []
            rewritten_uses = 0
            for element in instruction.elements:
                rewritten_element, rewritten = self._rewrite_value(element, replacements)
                elements.append(rewritten_element)
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return SSAListNew(instruction.result, tuple(elements)), rewritten_uses

        if isinstance(instruction, SSAVectorNew):
            elements = []
            rewritten_uses = 0
            for element in instruction.elements:
                rewritten_element, rewritten = self._rewrite_value(element, replacements)
                elements.append(rewritten_element)
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return SSAVectorNew(instruction.result, tuple(elements)), rewritten_uses

        if isinstance(instruction, SSAMatrixNew):
            elements = []
            rewritten_uses = 0
            for element in instruction.elements:
                rewritten_element, rewritten = self._rewrite_value(element, replacements)
                elements.append(rewritten_element)
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return SSAMatrixNew(instruction.result, tuple(elements), instruction.rows, instruction.cols), rewritten_uses

        if isinstance(instruction, SSAVectorAdd):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSAVectorAdd(
                    instruction.result,
                    left,
                    right,
                    instruction.length,
                    instruction.orientation,
                ),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSAVectorSub):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSAVectorSub(
                    instruction.result,
                    left,
                    right,
                    instruction.length,
                    instruction.orientation,
                ),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSAVectorDot):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSAVectorDot(
                    instruction.result,
                    left,
                    right,
                    instruction.length,
                ),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSAOuterProduct):
            column, column_rewritten = self._rewrite_value(instruction.column, replacements)
            row, row_rewritten = self._rewrite_value(instruction.row, replacements)
            if not column_rewritten and not row_rewritten:
                return instruction, 0
            return (
                SSAOuterProduct(
                    instruction.result,
                    column,
                    row,
                    instruction.rows,
                    instruction.cols,
                ),
                int(column_rewritten) + int(row_rewritten),
            )

        if isinstance(instruction, SSAVectorScale):
            vector, vector_rewritten = self._rewrite_value(instruction.vector, replacements)
            scalar, scalar_rewritten = self._rewrite_value(instruction.scalar, replacements)
            if not vector_rewritten and not scalar_rewritten:
                return instruction, 0
            return (
                SSAVectorScale(
                    instruction.result,
                    vector,
                    scalar,
                    instruction.length,
                    instruction.orientation,
                ),
                int(vector_rewritten) + int(scalar_rewritten),
            )

        if isinstance(instruction, SSAMatrixAdd):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSAMatrixAdd(
                    instruction.result,
                    left,
                    right,
                    instruction.rows,
                    instruction.cols,
                ),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSAMatrixSub):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSAMatrixSub(
                    instruction.result,
                    left,
                    right,
                    instruction.rows,
                    instruction.cols,
                ),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSAMatrixMatMul):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSAMatrixMatMul(
                    instruction.result,
                    left,
                    right,
                    instruction.rows,
                    instruction.inner,
                    instruction.cols,
                ),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSAMatrixVectorMul):
            matrix, matrix_rewritten = self._rewrite_value(instruction.matrix, replacements)
            vector, vector_rewritten = self._rewrite_value(instruction.vector, replacements)
            if not matrix_rewritten and not vector_rewritten:
                return instruction, 0
            return (
                SSAMatrixVectorMul(
                    instruction.result,
                    matrix,
                    vector,
                    instruction.rows,
                    instruction.inner,
                ),
                int(matrix_rewritten) + int(vector_rewritten),
            )

        if isinstance(instruction, SSAVectorMatrixMul):
            vector, vector_rewritten = self._rewrite_value(instruction.vector, replacements)
            matrix, matrix_rewritten = self._rewrite_value(instruction.matrix, replacements)
            if not vector_rewritten and not matrix_rewritten:
                return instruction, 0
            return (
                SSAVectorMatrixMul(
                    instruction.result,
                    vector,
                    matrix,
                    instruction.rows,
                    instruction.cols,
                ),
                int(vector_rewritten) + int(matrix_rewritten),
            )

        if isinstance(instruction, SSAMatrixScale):
            matrix, matrix_rewritten = self._rewrite_value(instruction.matrix, replacements)
            scalar, scalar_rewritten = self._rewrite_value(instruction.scalar, replacements)
            if not matrix_rewritten and not scalar_rewritten:
                return instruction, 0
            return (
                SSAMatrixScale(
                    instruction.result,
                    matrix,
                    scalar,
                    instruction.rows,
                    instruction.cols,
                ),
                int(matrix_rewritten) + int(scalar_rewritten),
            )

        if isinstance(instruction, SSAArrayGet):
            array, array_rewritten = self._rewrite_value(instruction.array, replacements)
            index, index_rewritten = self._rewrite_value(instruction.index, replacements)
            if not array_rewritten and not index_rewritten:
                return instruction, 0
            return (
                SSAArrayGet(instruction.result, array, index),
                int(array_rewritten) + int(index_rewritten),
            )

        if isinstance(instruction, SSAListGet):
            list_value, list_rewritten = self._rewrite_value(instruction.list_value, replacements)
            index, index_rewritten = self._rewrite_value(instruction.index, replacements)
            if not list_rewritten and not index_rewritten:
                return instruction, 0
            return (
                SSAListGet(instruction.result, list_value, index),
                int(list_rewritten) + int(index_rewritten),
            )

        if isinstance(instruction, SSAVectorGet):
            vector, vector_rewritten = self._rewrite_value(instruction.vector, replacements)
            index, index_rewritten = self._rewrite_value(instruction.index, replacements)
            if not vector_rewritten and not index_rewritten:
                return instruction, 0
            return (
                SSAVectorGet(instruction.result, vector, index),
                int(vector_rewritten) + int(index_rewritten),
            )

        if isinstance(instruction, SSAMatrixGet):
            matrix, matrix_rewritten = self._rewrite_value(instruction.matrix, replacements)
            row, row_rewritten = self._rewrite_value(instruction.row, replacements)
            column, column_rewritten = self._rewrite_value(instruction.column, replacements)
            if not matrix_rewritten and not row_rewritten and not column_rewritten:
                return instruction, 0
            return (
                SSAMatrixGet(instruction.result, matrix, row, column, instruction.cols),
                int(matrix_rewritten) + int(row_rewritten) + int(column_rewritten),
            )

        if isinstance(instruction, SSAArraySet):
            array, array_rewritten = self._rewrite_value(instruction.array, replacements)
            index, index_rewritten = self._rewrite_value(instruction.index, replacements)
            value, value_rewritten = self._rewrite_value(instruction.value, replacements)
            if not array_rewritten and not index_rewritten and not value_rewritten:
                return instruction, 0
            return (
                SSAArraySet(array, index, value),
                int(array_rewritten) + int(index_rewritten) + int(value_rewritten),
            )

        if isinstance(instruction, SSAListSet):
            list_value, list_rewritten = self._rewrite_value(instruction.list_value, replacements)
            index, index_rewritten = self._rewrite_value(instruction.index, replacements)
            value, value_rewritten = self._rewrite_value(instruction.value, replacements)
            if not list_rewritten and not index_rewritten and not value_rewritten:
                return instruction, 0
            return (
                SSAListSet(list_value, index, value),
                int(list_rewritten) + int(index_rewritten) + int(value_rewritten),
            )

        if isinstance(instruction, SSAListCopy):
            list_value, rewritten = self._rewrite_value(instruction.list_value, replacements)
            return (SSAListCopy(instruction.result, list_value), 1) if rewritten else (instruction, 0)

        if isinstance(instruction, SSAListContains):
            list_value, list_rewritten = self._rewrite_value(instruction.list_value, replacements)
            value, value_rewritten = self._rewrite_value(instruction.value, replacements)
            count = int(list_rewritten) + int(value_rewritten)
            return (SSAListContains(instruction.result, list_value, value), count) if count else (instruction, 0)

        if isinstance(instruction, SSAListIndexOf):
            list_value, list_rewritten = self._rewrite_value(instruction.list_value, replacements)
            value, value_rewritten = self._rewrite_value(instruction.value, replacements)
            count = int(list_rewritten) + int(value_rewritten)
            return (SSAListIndexOf(instruction.result, list_value, value), count) if count else (instruction, 0)

        if isinstance(instruction, SSAListClear):
            list_value, rewritten = self._rewrite_value(instruction.list_value, replacements)
            return (SSAListClear(list_value), 1) if rewritten else (instruction, 0)

        if isinstance(instruction, SSAListReverse):
            list_value, rewritten = self._rewrite_value(instruction.list_value, replacements)
            return (SSAListReverse(list_value), 1) if rewritten else (instruction, 0)

        if isinstance(instruction, SSASequenceSort):
            sequence, rewritten = self._rewrite_value(instruction.sequence, replacements)
            return (SSASequenceSort(sequence), 1) if rewritten else (instruction, 0)

        if isinstance(instruction, SSAArrayLength):
            array, rewritten = self._rewrite_value(instruction.array, replacements)
            if not rewritten:
                return instruction, 0
            return SSAArrayLength(instruction.result, array), 1

        if isinstance(instruction, SSAListLength):
            list_value, rewritten = self._rewrite_value(instruction.list_value, replacements)
            if not rewritten:
                return instruction, 0
            return SSAListLength(instruction.result, list_value), 1

        if isinstance(instruction, SSAListIsEmpty):
            list_value, rewritten = self._rewrite_value(instruction.list_value, replacements)
            if not rewritten:
                return instruction, 0
            return SSAListIsEmpty(instruction.result, list_value), 1

        if isinstance(instruction, SSAVectorLength):
            vector, rewritten = self._rewrite_value(instruction.vector, replacements)
            if not rewritten:
                return instruction, 0
            return SSAVectorLength(instruction.result, vector), 1

        if isinstance(instruction, SSAMatrixRows):
            matrix, rewritten = self._rewrite_value(instruction.matrix, replacements)
            if not rewritten:
                return instruction, 0
            return SSAMatrixRows(instruction.result, matrix, instruction.rows), 1

        if isinstance(instruction, SSAMatrixColumns):
            matrix, rewritten = self._rewrite_value(instruction.matrix, replacements)
            if not rewritten:
                return instruction, 0
            return SSAMatrixColumns(instruction.result, matrix, instruction.columns), 1

        if isinstance(instruction, SSAPhi):
            incoming = []
            rewritten_uses = 0
            for block_name, value in instruction.incoming:
                rewritten_value, rewritten = self._rewrite_value(value, replacements)
                incoming.append((block_name, rewritten_value))
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return SSAPhi(instruction.result, tuple(incoming)), rewritten_uses

        if isinstance(instruction, SSABranch):
            condition, rewritten = self._rewrite_value(
                instruction.condition,
                replacements,
            )
            if not rewritten:
                return instruction, 0
            return (
                SSABranch(
                    condition,
                    instruction.true_target,
                    instruction.false_target,
                ),
                1,
            )

        if isinstance(instruction, SSAJump):
            return instruction, 0

        if isinstance(instruction, SSAReturn):
            if instruction.value is None:
                return instruction, 0
            value, rewritten = self._rewrite_value(instruction.value, replacements)
            if not rewritten:
                return instruction, 0
            return SSAReturn(value), 1

        return instruction, 0

    def _rewrite_value(
        self,
        value: SSAValue,
        replacements: dict[SSAValue, SSAValue],
    ) -> tuple[SSAValue, bool]:
        replacement = replacements.get(value)
        if replacement is None:
            return value, False
        return replacement, True
