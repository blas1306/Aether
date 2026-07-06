from __future__ import annotations

from dataclasses import replace
from math import trunc
from typing import Any

from aether.ir.types import DoubleType, IntType
from aether.ir.model import (
    IRBasicBlock,
    IRBinaryOp,
    IRCast,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRModule,
    IRValue,
)

from .result import OptimizationResult


class ConstantFolder:
    """Fold simple IR operations whose operands are both known constants."""

    _BINARY_OPERATORS = {"add", "sub", "mul", "div", "mod", "rem"}
    _COMPARE_OPERATORS = {"lt", "le", "gt", "ge", "eq", "ne"}

    def run(self, module: IRModule) -> OptimizationResult:
        folded = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized_function, function_folded = self._fold_function(function)
            functions.append(optimized_function)
            folded += function_folded
        optimized = IRModule(functions)
        return OptimizationResult(
            optimized,
            changed=optimized != module,
            stats={"folded": folded},
        )

    def _fold_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        constants: dict[IRValue, Any] = {}
        folded = 0
        blocks: list[IRBasicBlock] = []
        for block in function.blocks:
            optimized_block, block_folded = self._fold_block(block, constants)
            blocks.append(optimized_block)
            folded += block_folded
        return (
            IRFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
            ),
            folded,
        )

    def _fold_block(
        self,
        block: IRBasicBlock,
        constants: dict[IRValue, Any],
    ) -> tuple[IRBasicBlock, int]:
        folded = 0
        instructions: list[IRInstruction] = []
        for instruction in block.instructions:
            optimized_instruction, instruction_folded = self._fold_instruction(
                instruction,
                constants,
            )
            instructions.append(optimized_instruction)
            folded += instruction_folded
        return IRBasicBlock(block.name, instructions), folded

    def _fold_instruction(
        self,
        instruction: IRInstruction,
        constants: dict[IRValue, Any],
    ) -> tuple[IRInstruction, int]:
        if isinstance(instruction, IRConst):
            constants[instruction.result] = instruction.value
            return replace(instruction), 0

        if isinstance(instruction, IRBinaryOp):
            folded = self._fold_binary(instruction, constants)
            if folded is not None:
                constants[instruction.result] = folded.value
                return folded, 1
            return instruction, 0

        if isinstance(instruction, IRCompareOp):
            folded = self._fold_compare(instruction, constants)
            if folded is not None:
                constants[instruction.result] = folded.value
                return folded, 1
            return instruction, 0

        if isinstance(instruction, IRCast):
            folded = self._fold_cast(instruction, constants)
            if folded is not None:
                constants[instruction.result] = folded.value
                return folded, 1
            return instruction, 0

        return instruction, 0

    def _fold_binary(
        self,
        instruction: IRBinaryOp,
        constants: dict[IRValue, Any],
    ) -> IRConst | None:
        operator = instruction.operator
        if operator not in self._BINARY_OPERATORS:
            return None
        if instruction.left not in constants or instruction.right not in constants:
            return None

        left = constants[instruction.left]
        right = constants[instruction.right]
        if operator in {"div", "mod", "rem"} and right == 0:
            return None

        value = self._evaluate_binary(operator, left, right)
        return IRConst(instruction.result, value)

    def _fold_compare(
        self,
        instruction: IRCompareOp,
        constants: dict[IRValue, Any],
    ) -> IRConst | None:
        operator = instruction.operator
        if operator not in self._COMPARE_OPERATORS:
            return None
        if instruction.left not in constants or instruction.right not in constants:
            return None

        left = constants[instruction.left]
        right = constants[instruction.right]
        value = self._evaluate_compare(operator, left, right)
        return IRConst(instruction.result, value)

    def _fold_cast(
        self,
        instruction: IRCast,
        constants: dict[IRValue, Any],
    ) -> IRConst | None:
        if instruction.value not in constants:
            return None
        return IRConst(
            instruction.result,
            self._evaluate_cast(constants[instruction.value], instruction.result.type),
        )

    @staticmethod
    def _evaluate_binary(operator: str, left: Any, right: Any) -> Any:
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mul":
            return left * right
        if operator == "div":
            return left / right
        if operator in {"mod", "rem"}:
            return left - trunc(left / right) * right
        raise AssertionError(f"Unsupported foldable binary operator: {operator}")

    @staticmethod
    def _evaluate_compare(operator: str, left: Any, right: Any) -> bool:
        if operator == "lt":
            return left < right
        if operator == "le":
            return left <= right
        if operator == "gt":
            return left > right
        if operator == "ge":
            return left >= right
        if operator == "eq":
            return left == right
        if operator == "ne":
            return left != right
        raise AssertionError(f"Unsupported foldable compare operator: {operator}")

    @staticmethod
    def _evaluate_cast(value: Any, target_type: object) -> Any:
        if isinstance(target_type, DoubleType):
            return float(value)
        if isinstance(target_type, IntType):
            return trunc(value)
        raise AssertionError(f"Unsupported foldable cast target: {target_type}")
