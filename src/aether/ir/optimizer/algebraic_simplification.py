from __future__ import annotations

from dataclasses import replace
from typing import Any

from aether.ir.model import (
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRListGet,
    IRListCopy,
    IRListContains,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListSet,
    IRListReverse,
    IRLoad,
    IRMatrixColumns,
    IRMatrixAdd,
    IRMatrixMatMul,
    IRMatrixVectorMul,
    IRMatrixScale,
    IRMatrixSub,
    IRMatrixGet,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixSet,
    IRModule,
    IROuterProduct,
    IRReturn,
    IRStore,
    IRValue,
    IRVectorGet,
    IRVectorAdd,
    IRVectorDot,
    IRVectorMatrixMul,
    IRVectorScale,
    IRVectorSub,
    IRVectorLength,
    IRVectorNew,
    IRVectorSet,
)
from aether.ir.types import IntType

from .result import OptimizationResult


class AlgebraicSimplifier:
    """Apply local integer algebraic identities to IR binary operations."""

    def run(self, module: IRModule) -> OptimizationResult:
        simplified = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized_function, function_simplified = self._simplify_function(function)
            functions.append(optimized_function)
            simplified += function_simplified
        optimized = IRModule(functions)
        return OptimizationResult(
            optimized,
            changed=optimized != module,
            stats={"simplified": simplified},
        )

    def _simplify_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        constants = self._collect_constants(function)
        replacements: dict[str, IRValue] = {}
        blocks: list[IRBasicBlock] = []
        simplified_count = 0

        for block in function.blocks:
            instructions: list[IRInstruction] = []
            for instruction in block.instructions:
                rewritten = self._rewrite_instruction(instruction, replacements)
                simplified, was_simplified = self._simplify_instruction(
                    rewritten,
                    constants,
                    replacements,
                )
                if was_simplified:
                    simplified_count += 1
                if simplified is None:
                    continue
                if isinstance(simplified, IRConst):
                    constants[simplified.result.name] = simplified.value
                instructions.append(simplified)
            blocks.append(IRBasicBlock(block.name, instructions))

        blocks = [
            IRBasicBlock(
                block.name,
                [
                    self._rewrite_instruction(instruction, replacements)
                    for instruction in block.instructions
                ],
            )
            for block in blocks
        ]

        return (
            IRFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
            ),
            simplified_count,
        )

    @staticmethod
    def _collect_constants(function: IRFunction) -> dict[str, Any]:
        constants: dict[str, Any] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, IRConst):
                    constants[instruction.result.name] = instruction.value
        return constants

    def _simplify_instruction(
        self,
        instruction: IRInstruction,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> tuple[IRInstruction | None, bool]:
        if not isinstance(instruction, IRBinaryOp):
            return instruction, False
        if not self._is_integer_operation(instruction):
            return instruction, False

        operator = instruction.operator
        left = instruction.left
        right = instruction.right

        if operator == "add":
            if self._is_zero(right, constants, replacements):
                replacements[instruction.result.name] = left
                return None, True
            if self._is_zero(left, constants, replacements):
                replacements[instruction.result.name] = right
                return None, True

        if operator == "sub":
            if self._is_zero(right, constants, replacements):
                replacements[instruction.result.name] = left
                return None, True

        if operator == "mul":
            if self._is_zero(left, constants, replacements) or self._is_zero(
                right,
                constants,
                replacements,
            ):
                return IRConst(instruction.result, 0), True
            if self._is_one(right, constants, replacements):
                replacements[instruction.result.name] = left
                return None, True
            if self._is_one(left, constants, replacements):
                replacements[instruction.result.name] = right
                return None, True

        if operator == "div":
            if (
                instruction.result.type == left.type
                and self._is_one(right, constants, replacements)
            ):
                replacements[instruction.result.name] = left
                return None, True

        if operator in {"mod", "rem"}:
            if self._is_one(right, constants, replacements):
                return IRConst(instruction.result, 0), True

        return instruction, False

    @staticmethod
    def _is_integer_operation(instruction: IRBinaryOp) -> bool:
        return (
            isinstance(instruction.result.type, IntType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        )

    def _is_zero(
        self,
        value: IRValue,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> bool:
        return self._integer_constant(value, constants, replacements) == 0

    def _is_one(
        self,
        value: IRValue,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> bool:
        return self._integer_constant(value, constants, replacements) == 1

    def _integer_constant(
        self,
        value: IRValue,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> int | None:
        resolved = self._resolve(value, replacements)
        if not isinstance(resolved.type, IntType):
            return None
        constant = constants.get(resolved.name)
        if type(constant) is int:
            return constant
        return None

    def _rewrite_instruction(
        self,
        instruction: IRInstruction,
        replacements: dict[str, IRValue],
    ) -> IRInstruction:
        if isinstance(instruction, (IRConst, IRLoad)):
            return instruction
        if isinstance(instruction, IRStore):
            return replace(instruction, value=self._resolve(instruction.value, replacements))
        if isinstance(instruction, IRBinaryOp):
            return replace(
                instruction,
                left=self._resolve(instruction.left, replacements),
                right=self._resolve(instruction.right, replacements),
            )
        if isinstance(instruction, IRCompareOp):
            return replace(
                instruction,
                left=self._resolve(instruction.left, replacements),
                right=self._resolve(instruction.right, replacements),
            )
        if isinstance(instruction, IRCast):
            return replace(
                instruction,
                value=self._resolve(instruction.value, replacements),
            )
        if isinstance(instruction, IRCall):
            return replace(
                instruction,
                arguments=tuple(
                    self._resolve(argument, replacements)
                    for argument in instruction.arguments
                ),
            )
        if isinstance(instruction, IRArrayNew):
            return replace(
                instruction,
                elements=tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
            )
        if isinstance(instruction, IRListNew):
            return replace(
                instruction,
                elements=tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
            )
        if isinstance(instruction, IRVectorNew):
            return replace(
                instruction,
                elements=tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
            )
        if isinstance(instruction, IRMatrixNew):
            return replace(
                instruction,
                elements=tuple(
                    self._resolve(element, replacements)
                    for element in instruction.elements
                ),
            )
        if isinstance(instruction, (IRVectorAdd, IRVectorDot, IRMatrixAdd, IRMatrixMatMul, IRVectorSub, IRMatrixSub)):
            return replace(
                instruction,
                left=self._resolve(instruction.left, replacements),
                right=self._resolve(instruction.right, replacements),
            )
        if isinstance(instruction, IROuterProduct):
            return replace(
                instruction,
                column=self._resolve(instruction.column, replacements),
                row=self._resolve(instruction.row, replacements),
            )
        if isinstance(instruction, IRMatrixVectorMul):
            return replace(
                instruction,
                matrix=self._resolve(instruction.matrix, replacements),
                vector=self._resolve(instruction.vector, replacements),
            )
        if isinstance(instruction, IRVectorMatrixMul):
            return replace(
                instruction,
                vector=self._resolve(instruction.vector, replacements),
                matrix=self._resolve(instruction.matrix, replacements),
            )
        if isinstance(instruction, IRVectorScale):
            return replace(
                instruction,
                vector=self._resolve(instruction.vector, replacements),
                scalar=self._resolve(instruction.scalar, replacements),
            )
        if isinstance(instruction, IRMatrixScale):
            return replace(
                instruction,
                matrix=self._resolve(instruction.matrix, replacements),
                scalar=self._resolve(instruction.scalar, replacements),
            )
        if isinstance(instruction, IRArrayGet):
            return replace(
                instruction,
                array=self._resolve(instruction.array, replacements),
                index=self._resolve(instruction.index, replacements),
            )
        if isinstance(instruction, IRListGet):
            return replace(
                instruction,
                list_value=self._resolve(instruction.list_value, replacements),
                index=self._resolve(instruction.index, replacements),
            )
        if isinstance(instruction, IRVectorGet):
            return replace(
                instruction,
                vector=self._resolve(instruction.vector, replacements),
                index=self._resolve(instruction.index, replacements),
            )
        if isinstance(instruction, IRMatrixGet):
            return replace(
                instruction,
                matrix=self._resolve(instruction.matrix, replacements),
                row=self._resolve(instruction.row, replacements),
                column=self._resolve(instruction.column, replacements),
            )
        if isinstance(instruction, IRArraySet):
            return replace(
                instruction,
                array=self._resolve(instruction.array, replacements),
                index=self._resolve(instruction.index, replacements),
                value=self._resolve(instruction.value, replacements),
            )
        if isinstance(instruction, IRListSet):
            return replace(
                instruction,
                list_value=self._resolve(instruction.list_value, replacements),
                index=self._resolve(instruction.index, replacements),
                value=self._resolve(instruction.value, replacements),
            )
        if isinstance(instruction, IRListCopy):
            return replace(instruction, list_value=self._resolve(instruction.list_value, replacements))
        if isinstance(instruction, IRListContains):
            return replace(
                instruction,
                list_value=self._resolve(instruction.list_value, replacements),
                value=self._resolve(instruction.value, replacements),
            )
        if isinstance(instruction, IRListReverse):
            return replace(instruction, list_value=self._resolve(instruction.list_value, replacements))
        if isinstance(instruction, IRVectorSet):
            return replace(
                instruction,
                vector=self._resolve(instruction.vector, replacements),
                index=self._resolve(instruction.index, replacements),
                value=self._resolve(instruction.value, replacements),
            )
        if isinstance(instruction, IRMatrixSet):
            return replace(
                instruction,
                matrix=self._resolve(instruction.matrix, replacements),
                row=self._resolve(instruction.row, replacements),
                column=self._resolve(instruction.column, replacements),
                value=self._resolve(instruction.value, replacements),
            )
        if isinstance(instruction, IRArrayLength):
            return replace(
                instruction,
                array=self._resolve(instruction.array, replacements),
            )
        if isinstance(instruction, (IRListLength, IRListIsEmpty)):
            return replace(
                instruction,
                list_value=self._resolve(instruction.list_value, replacements),
            )
        if isinstance(instruction, IRVectorLength):
            return replace(
                instruction,
                vector=self._resolve(instruction.vector, replacements),
            )
        if isinstance(instruction, (IRMatrixRows, IRMatrixColumns)):
            return replace(
                instruction,
                matrix=self._resolve(instruction.matrix, replacements),
            )
        if isinstance(instruction, IRBranch):
            return replace(
                instruction,
                condition=self._resolve(instruction.condition, replacements),
            )
        if isinstance(instruction, IRReturn):
            if instruction.value is None:
                return instruction
            return replace(
                instruction,
                value=self._resolve(instruction.value, replacements),
            )
        return instruction

    def _resolve(
        self,
        value: IRValue,
        replacements: dict[str, IRValue],
    ) -> IRValue:
        resolved = value
        seen: set[str] = set()
        while resolved.name in replacements and resolved.name not in seen:
            seen.add(resolved.name)
            resolved = replacements[resolved.name]
        return resolved
