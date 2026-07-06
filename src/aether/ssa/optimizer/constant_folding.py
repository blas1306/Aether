from __future__ import annotations

from math import trunc
from typing import Any

from aether.ir.types import DoubleType, IntType
from aether.ssa.model import (
    SSABasicBlock,
    SSABinaryOp,
    SSACast,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAValue,
)

from .result import SSAOptimizationResult


class SSAConstantFolder:
    """Fold SSA operations whose operands are both known constants."""

    _BINARY_OPERATORS = {"add", "sub", "mul", "div", "mod", "rem"}
    _COMPARE_OPERATORS = {"lt", "le", "gt", "ge", "eq", "ne"}

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        folded = 0

        for function in module.functions:
            updated_function, function_folded = self._fold_function(function)
            updated_functions.append(updated_function)
            folded += function_folded

        if folded == 0:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"folded": 0},
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats={"folded": folded},
        )

    def _fold_function(self, function: SSAFunction) -> tuple[SSAFunction, int]:
        constants: dict[SSAValue, Any] = {}
        updated_blocks: list[SSABasicBlock] = []
        folded = 0

        for block in function.blocks:
            updated_block, block_folded = self._fold_block(block, constants)
            updated_blocks.append(updated_block)
            folded += block_folded

        if folded == 0:
            return function, 0

        return (
            SSAFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                updated_blocks,
                function.entry_block,
            ),
            folded,
        )

    def _fold_block(
        self,
        block: SSABasicBlock,
        constants: dict[SSAValue, Any],
    ) -> tuple[SSABasicBlock, int]:
        instructions: list[SSAInstruction] = []
        folded = 0

        for instruction in block.instructions:
            updated_instruction, instruction_folded = self._fold_instruction(
                instruction,
                constants,
            )
            instructions.append(updated_instruction)
            folded += instruction_folded

        if folded == 0:
            return block, 0

        return SSABasicBlock(block.name, instructions), folded

    def _fold_instruction(
        self,
        instruction: SSAInstruction,
        constants: dict[SSAValue, Any],
    ) -> tuple[SSAInstruction, int]:
        if isinstance(instruction, SSAConst):
            constants[instruction.result] = instruction.value
            return instruction, 0

        if isinstance(instruction, SSABinaryOp):
            folded = self._fold_binary(instruction, constants)
            if folded is None:
                return instruction, 0
            constants[folded.result] = folded.value
            return folded, 1

        if isinstance(instruction, SSACompareOp):
            folded = self._fold_compare(instruction, constants)
            if folded is None:
                return instruction, 0
            constants[folded.result] = folded.value
            return folded, 1

        if isinstance(instruction, SSACast):
            folded = self._fold_cast(instruction, constants)
            if folded is None:
                return instruction, 0
            constants[folded.result] = folded.value
            return folded, 1

        return instruction, 0

    def _fold_binary(
        self,
        instruction: SSABinaryOp,
        constants: dict[SSAValue, Any],
    ) -> SSAConst | None:
        operator = instruction.operator
        if operator not in self._BINARY_OPERATORS:
            return None
        if instruction.left not in constants or instruction.right not in constants:
            return None

        left = constants[instruction.left]
        right = constants[instruction.right]
        if operator in {"div", "mod", "rem"} and right == 0:
            return None

        return SSAConst(
            instruction.result,
            self._evaluate_binary(operator, left, right),
        )

    def _fold_compare(
        self,
        instruction: SSACompareOp,
        constants: dict[SSAValue, Any],
    ) -> SSAConst | None:
        operator = instruction.operator
        if operator not in self._COMPARE_OPERATORS:
            return None
        if instruction.left not in constants or instruction.right not in constants:
            return None

        return SSAConst(
            instruction.result,
            self._evaluate_compare(
                operator,
                constants[instruction.left],
                constants[instruction.right],
            ),
        )

    def _fold_cast(
        self,
        instruction: SSACast,
        constants: dict[SSAValue, Any],
    ) -> SSAConst | None:
        if instruction.value not in constants:
            return None
        return SSAConst(
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
        raise AssertionError(f"Unsupported foldable SSA binary operator: {operator}")

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
        raise AssertionError(f"Unsupported foldable SSA compare operator: {operator}")

    @staticmethod
    def _evaluate_cast(value: Any, target_type: object) -> Any:
        if isinstance(target_type, DoubleType):
            return float(value)
        if isinstance(target_type, IntType):
            return trunc(value)
        raise AssertionError(f"Unsupported foldable SSA cast target: {target_type}")
