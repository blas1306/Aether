from __future__ import annotations

from dataclasses import replace
from math import trunc
from typing import Any

from aether.ir.model import (
    IRBasicBlock,
    IRBinaryOp,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRModule,
    IRValue,
)


class ConstantFolder:
    """Fold simple IR operations whose operands are both known constants."""

    _BINARY_OPERATORS = {"add", "sub", "mul", "div", "mod", "rem"}
    _COMPARE_OPERATORS = {"lt", "le", "gt", "ge", "eq", "ne"}

    def run(self, module: IRModule) -> IRModule:
        functions = [self._fold_function(function) for function in module.functions]
        return IRModule(functions)

    def _fold_function(self, function: IRFunction) -> IRFunction:
        constants: dict[IRValue, Any] = {}
        blocks = [
            self._fold_block(block, constants)
            for block in function.blocks
        ]
        return IRFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            blocks,
        )

    def _fold_block(
        self,
        block: IRBasicBlock,
        constants: dict[IRValue, Any],
    ) -> IRBasicBlock:
        instructions = [
            self._fold_instruction(instruction, constants)
            for instruction in block.instructions
        ]
        return IRBasicBlock(block.name, instructions)

    def _fold_instruction(
        self,
        instruction: IRInstruction,
        constants: dict[IRValue, Any],
    ) -> IRInstruction:
        if isinstance(instruction, IRConst):
            constants[instruction.result] = instruction.value
            return replace(instruction)

        if isinstance(instruction, IRBinaryOp):
            folded = self._fold_binary(instruction, constants)
            if folded is not None:
                constants[instruction.result] = folded.value
                return folded
            return instruction

        if isinstance(instruction, IRCompareOp):
            folded = self._fold_compare(instruction, constants)
            if folded is not None:
                constants[instruction.result] = folded.value
                return folded
            return instruction

        return instruction

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
