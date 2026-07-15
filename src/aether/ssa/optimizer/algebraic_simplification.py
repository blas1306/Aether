from __future__ import annotations

from typing import Any

from aether.ir.types import IntType
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


class SSAAlgebraicSimplifier:
    """Apply local integer algebraic identities to SSA binary operations."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        simplified = 0

        for function in module.functions:
            updated_function, function_simplified = self._simplify_function(function)
            updated_functions.append(updated_function)
            simplified += function_simplified

        if simplified == 0:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"simplified": 0},
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions, list(module.structs)),
            changed=True,
            stats={"simplified": simplified},
        )

    def _simplify_function(self, function: SSAFunction) -> tuple[SSAFunction, int]:
        constants = self._collect_constants(function)
        replacements: dict[SSAValue, SSAValue] = {}
        blocks: list[SSABasicBlock] = []
        simplified = 0

        for block in function.blocks:
            instructions: list[SSAInstruction] = []
            for instruction in block.instructions:
                rewritten = self._rewrite_instruction(instruction, replacements)
                updated, was_simplified = self._simplify_instruction(
                    rewritten,
                    constants,
                    replacements,
                )
                if was_simplified:
                    simplified += 1
                if updated is None:
                    continue
                if isinstance(updated, SSAConst):
                    constants[updated.result] = updated.value
                instructions.append(updated)
            blocks.append(SSABasicBlock(block.name, instructions))

        if simplified == 0:
            return function, 0

        blocks = [
            SSABasicBlock(
                block.name,
                [
                    self._rewrite_instruction(instruction, replacements)
                    for instruction in block.instructions
                ],
            )
            for block in blocks
        ]

        return (
            SSAFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
                function.entry_block,
            ),
            simplified,
        )

    @staticmethod
    def _collect_constants(function: SSAFunction) -> dict[SSAValue, Any]:
        constants: dict[SSAValue, Any] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, SSAConst):
                    constants[instruction.result] = instruction.value
        return constants

    def _simplify_instruction(
        self,
        instruction: SSAInstruction,
        constants: dict[SSAValue, Any],
        replacements: dict[SSAValue, SSAValue],
    ) -> tuple[SSAInstruction | None, bool]:
        if not isinstance(instruction, SSABinaryOp):
            return instruction, False
        if not self._is_integer_operation(instruction):
            return instruction, False

        operator = instruction.operator
        left = instruction.left
        right = instruction.right

        if operator == "add":
            if self._is_zero(right, constants, replacements):
                replacements[instruction.result] = left
                return None, True
            if self._is_zero(left, constants, replacements):
                replacements[instruction.result] = right
                return None, True

        if operator == "sub":
            if self._is_zero(right, constants, replacements):
                replacements[instruction.result] = left
                return None, True

        if operator == "mul":
            if self._is_zero(left, constants, replacements) or self._is_zero(
                right,
                constants,
                replacements,
            ):
                return SSAConst(instruction.result, 0), True
            if self._is_one(right, constants, replacements):
                replacements[instruction.result] = left
                return None, True
            if self._is_one(left, constants, replacements):
                replacements[instruction.result] = right
                return None, True

        if operator == "div":
            if (
                instruction.result.type == left.type
                and self._is_one(right, constants, replacements)
            ):
                replacements[instruction.result] = left
                return None, True

        if operator in {"mod", "rem"}:
            if self._is_one(right, constants, replacements):
                return SSAConst(instruction.result, 0), True

        return instruction, False

    @staticmethod
    def _is_integer_operation(instruction: SSABinaryOp) -> bool:
        return (
            isinstance(instruction.result.type, IntType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        )

    def _is_zero(
        self,
        value: SSAValue,
        constants: dict[SSAValue, Any],
        replacements: dict[SSAValue, SSAValue],
    ) -> bool:
        return self._integer_constant(value, constants, replacements) == 0

    def _is_one(
        self,
        value: SSAValue,
        constants: dict[SSAValue, Any],
        replacements: dict[SSAValue, SSAValue],
    ) -> bool:
        return self._integer_constant(value, constants, replacements) == 1

    def _integer_constant(
        self,
        value: SSAValue,
        constants: dict[SSAValue, Any],
        replacements: dict[SSAValue, SSAValue],
    ) -> int | None:
        resolved = self._resolve(value, replacements)
        if not isinstance(resolved.type, IntType):
            return None
        constant = constants.get(resolved)
        if type(constant) is int:
            return constant
        return None

    def _rewrite_instruction(
        self,
        instruction: SSAInstruction,
        replacements: dict[SSAValue, SSAValue],
    ) -> SSAInstruction:
        if isinstance(instruction, SSAConst):
            return instruction

        if isinstance(instruction, SSABinaryOp):
            return SSABinaryOp(
                instruction.result,
                instruction.operator,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
            )

        if isinstance(instruction, SSAUnaryOp):
            return SSAUnaryOp(
                instruction.result,
                instruction.operator,
                self._resolve(instruction.operand, replacements),
            )

        if isinstance(instruction, SSACompareOp):
            return SSACompareOp(
                instruction.result,
                instruction.operator,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
                instruction.aggregate_shape,
            )

        if isinstance(instruction, SSACast):
            return SSACast(
                instruction.result,
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSACall):
            return SSACall(
                instruction.function,
                tuple(
                    self._resolve(argument, replacements)
                    for argument in instruction.arguments
                ),
                instruction.result,
                instruction.builtin,
            )

        if isinstance(instruction, SSAPrint):
            return SSAPrint(
                self._resolve(instruction.value, replacements),
                instruction.newline,
                instruction.aggregate_shape,
            )

        if isinstance(instruction, SSAArrayNew):
            return SSAArrayNew(
                instruction.result,
                tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
            )
        if isinstance(instruction, SSAListNew):
            return SSAListNew(
                instruction.result,
                tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
            )
        if isinstance(instruction, SSAVectorNew):
            return SSAVectorNew(
                instruction.result,
                tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
            )
        if isinstance(instruction, SSAMatrixNew):
            return SSAMatrixNew(
                instruction.result,
                tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
                instruction.rows,
                instruction.cols,
            )

        if isinstance(instruction, SSAVectorAdd):
            return SSAVectorAdd(
                instruction.result,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
                instruction.length,
                instruction.orientation,
            )

        if isinstance(instruction, SSAVectorSub):
            return SSAVectorSub(
                instruction.result,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
                instruction.length,
                instruction.orientation,
            )

        if isinstance(instruction, SSAVectorDot):
            return SSAVectorDot(
                instruction.result,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
                instruction.length,
            )

        if isinstance(instruction, SSAOuterProduct):
            return SSAOuterProduct(
                instruction.result,
                self._resolve(instruction.column, replacements),
                self._resolve(instruction.row, replacements),
                instruction.rows,
                instruction.cols,
            )

        if isinstance(instruction, SSAVectorScale):
            return SSAVectorScale(
                instruction.result,
                self._resolve(instruction.vector, replacements),
                self._resolve(instruction.scalar, replacements),
                instruction.length,
                instruction.orientation,
            )

        if isinstance(instruction, SSAMatrixAdd):
            return SSAMatrixAdd(
                instruction.result,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
                instruction.rows,
                instruction.cols,
            )

        if isinstance(instruction, SSAMatrixSub):
            return SSAMatrixSub(
                instruction.result,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
                instruction.rows,
                instruction.cols,
            )

        if isinstance(instruction, SSAMatrixMatMul):
            return SSAMatrixMatMul(
                instruction.result,
                self._resolve(instruction.left, replacements),
                self._resolve(instruction.right, replacements),
                instruction.rows,
                instruction.inner,
                instruction.cols,
            )

        if isinstance(instruction, SSAMatrixVectorMul):
            return SSAMatrixVectorMul(
                instruction.result,
                self._resolve(instruction.matrix, replacements),
                self._resolve(instruction.vector, replacements),
                instruction.rows,
                instruction.inner,
            )

        if isinstance(instruction, SSAVectorMatrixMul):
            return SSAVectorMatrixMul(
                instruction.result,
                self._resolve(instruction.vector, replacements),
                self._resolve(instruction.matrix, replacements),
                instruction.rows,
                instruction.cols,
            )

        if isinstance(instruction, SSAMatrixScale):
            return SSAMatrixScale(
                instruction.result,
                self._resolve(instruction.matrix, replacements),
                self._resolve(instruction.scalar, replacements),
                instruction.rows,
                instruction.cols,
            )

        if isinstance(instruction, SSAArrayGet):
            return SSAArrayGet(
                instruction.result,
                self._resolve(instruction.array, replacements),
                self._resolve(instruction.index, replacements),
            )

        if isinstance(instruction, SSAArraySlice):
            return SSAArraySlice(
                instruction.result,
                self._resolve(instruction.array, replacements),
                self._resolve(instruction.start, replacements),
                self._resolve(instruction.end, replacements),
            )

        if isinstance(instruction, SSAListGet):
            return SSAListGet(
                instruction.result,
                self._resolve(instruction.list_value, replacements),
                self._resolve(instruction.index, replacements),
            )

        if isinstance(instruction, SSAVectorGet):
            return SSAVectorGet(
                instruction.result,
                self._resolve(instruction.vector, replacements),
                self._resolve(instruction.index, replacements),
            )

        if isinstance(instruction, SSAMatrixGet):
            return SSAMatrixGet(
                instruction.result,
                self._resolve(instruction.matrix, replacements),
                self._resolve(instruction.row, replacements),
                self._resolve(instruction.column, replacements),
                instruction.cols,
            )

        if isinstance(instruction, SSAArraySet):
            return SSAArraySet(
                self._resolve(instruction.array, replacements),
                self._resolve(instruction.index, replacements),
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSAListSet):
            return SSAListSet(
                self._resolve(instruction.list_value, replacements),
                self._resolve(instruction.index, replacements),
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSAListCopy):
            return SSAListCopy(instruction.result, self._resolve(instruction.list_value, replacements))

        if isinstance(instruction, SSAListContains):
            return SSAListContains(
                instruction.result,
                self._resolve(instruction.list_value, replacements),
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSAListIndexOf):
            return SSAListIndexOf(
                instruction.result,
                self._resolve(instruction.list_value, replacements),
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSAListClear):
            return SSAListClear(self._resolve(instruction.list_value, replacements))

        if isinstance(instruction, SSAListPush):
            return SSAListPush(
                self._resolve(instruction.list_value, replacements),
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSAListInsert):
            return SSAListInsert(
                self._resolve(instruction.list_value, replacements),
                self._resolve(instruction.index, replacements),
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSAListPop):
            return SSAListPop(
                instruction.result,
                self._resolve(instruction.list_value, replacements),
            )

        if isinstance(instruction, SSAListRemoveAt):
            return SSAListRemoveAt(
                instruction.result,
                self._resolve(instruction.list_value, replacements),
                self._resolve(instruction.index, replacements),
            )

        if isinstance(instruction, SSAListReverse):
            return SSAListReverse(self._resolve(instruction.list_value, replacements))

        if isinstance(instruction, SSASequenceSort):
            return SSASequenceSort(self._resolve(instruction.sequence, replacements))

        if isinstance(instruction, SSAVectorSet):
            return SSAVectorSet(
                self._resolve(instruction.vector, replacements),
                self._resolve(instruction.index, replacements),
                self._resolve(instruction.value, replacements),
            )

        if isinstance(instruction, SSAMatrixSet):
            return SSAMatrixSet(
                self._resolve(instruction.matrix, replacements),
                self._resolve(instruction.row, replacements),
                self._resolve(instruction.column, replacements),
                self._resolve(instruction.value, replacements),
                instruction.cols,
            )

        if isinstance(instruction, SSAArrayLength):
            return SSAArrayLength(
                instruction.result,
                self._resolve(instruction.array, replacements),
            )

        if isinstance(instruction, SSAListLength):
            return SSAListLength(
                instruction.result,
                self._resolve(instruction.list_value, replacements),
            )

        if isinstance(instruction, SSAListIsEmpty):
            return SSAListIsEmpty(
                instruction.result,
                self._resolve(instruction.list_value, replacements),
            )

        if isinstance(instruction, SSAVectorLength):
            return SSAVectorLength(
                instruction.result,
                self._resolve(instruction.vector, replacements),
            )

        if isinstance(instruction, SSAMatrixRows):
            return SSAMatrixRows(
                instruction.result,
                self._resolve(instruction.matrix, replacements),
                instruction.rows,
            )

        if isinstance(instruction, SSAMatrixColumns):
            return SSAMatrixColumns(
                instruction.result,
                self._resolve(instruction.matrix, replacements),
                instruction.columns,
            )

        if isinstance(instruction, SSAPhi):
            return SSAPhi(
                instruction.result,
                tuple(
                    (block_name, self._resolve(value, replacements))
                    for block_name, value in instruction.incoming
                ),
            )

        if isinstance(instruction, SSABranch):
            return SSABranch(
                self._resolve(instruction.condition, replacements),
                instruction.true_target,
                instruction.false_target,
            )

        if isinstance(instruction, SSAJump):
            return instruction

        if isinstance(instruction, SSAReturn):
            if instruction.value is None:
                return instruction
            return SSAReturn(self._resolve(instruction.value, replacements))

        return instruction

    def _resolve(
        self,
        value: SSAValue,
        replacements: dict[SSAValue, SSAValue],
    ) -> SSAValue:
        resolved = value
        seen: set[SSAValue] = set()
        while resolved in replacements and resolved not in seen:
            seen.add(resolved)
            resolved = replacements[resolved]
        return resolved
