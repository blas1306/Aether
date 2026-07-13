from __future__ import annotations

from math import trunc
from typing import Any

from aether.ir.types import DoubleType, IntType, StringType
from aether.integer_arithmetic import checked_int_binary
from aether.ssa.model import (
    SSABasicBlock,
    SSABinaryOp,
    SSACast,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAPhi,
    SSAValue,
)

from .result import SSAOptimizationResult


class _Unknown:
    pass


UNKNOWN = _Unknown()


class SSAGlobalConstantPropagator:
    """Conservatively discover global SSA constants within each function."""

    _BINARY_OPERATORS = {"add", "sub", "mul", "div", "mod", "rem"}
    _COMPARE_OPERATORS = {"lt", "le", "gt", "ge", "eq", "ne"}

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        propagated = 0

        for function in module.functions:
            updated_function, function_propagated = self._propagate_function(function)
            updated_functions.append(updated_function)
            propagated += function_propagated

        if propagated == 0:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"propagated": 0},
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats={"propagated": propagated},
        )

    def _propagate_function(self, function: SSAFunction) -> tuple[SSAFunction, int]:
        constants = self._collect_constants(function)
        blocks: list[SSABasicBlock] = []
        propagated = 0

        for block in function.blocks:
            instructions: list[SSAInstruction] = []
            block_propagated = 0

            for instruction in block.instructions:
                updated = self._constant_replacement(instruction, constants)
                if updated is not None:
                    instructions.append(updated)
                    block_propagated += 1
                    continue
                instructions.append(instruction)

            if block_propagated:
                blocks.append(SSABasicBlock(block.name, instructions))
                propagated += block_propagated
            else:
                blocks.append(block)

        if propagated == 0:
            return function, 0

        return (
            SSAFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
                function.entry_block,
            ),
            propagated,
        )

    def _collect_constants(self, function: SSAFunction) -> dict[SSAValue, Any]:
        constants: dict[SSAValue, Any] = {}

        changed = True
        while changed:
            changed = False
            for block in function.blocks:
                for instruction in block.instructions:
                    result = self._result_value(instruction)
                    if result is None or result in constants:
                        continue

                    constant = self._known_constant(instruction, constants)
                    if constant is UNKNOWN:
                        continue

                    constants[result] = constant
                    changed = True

        return constants

    def _constant_replacement(
        self,
        instruction: SSAInstruction,
        constants: dict[SSAValue, Any],
    ) -> SSAConst | None:
        if isinstance(instruction, SSAConst):
            return None

        result = self._result_value(instruction)
        if result is None or result not in constants:
            return None

        if isinstance(instruction, (SSAPhi, SSABinaryOp, SSACompareOp, SSACast)):
            return SSAConst(result, constants[result])

        return None

    def _known_constant(
        self,
        instruction: SSAInstruction,
        constants: dict[SSAValue, Any],
    ) -> Any | _Unknown:
        if isinstance(instruction, SSAConst):
            return instruction.value

        if isinstance(instruction, SSAPhi):
            return self._phi_constant(instruction, constants)

        if isinstance(instruction, SSABinaryOp):
            return self._binary_constant(instruction, constants)

        if isinstance(instruction, SSACompareOp):
            return self._compare_constant(instruction, constants)

        if isinstance(instruction, SSACast):
            return self._cast_constant(instruction, constants)

        return UNKNOWN

    def _phi_constant(
        self,
        instruction: SSAPhi,
        constants: dict[SSAValue, Any],
    ) -> Any | _Unknown:
        if not instruction.incoming:
            return UNKNOWN

        first_value = instruction.incoming[0][1]
        if first_value not in constants:
            return UNKNOWN

        first_constant = constants[first_value]
        for _block_name, value in instruction.incoming[1:]:
            if value not in constants:
                return UNKNOWN
            constant = constants[value]
            if type(constant) is not type(first_constant) or constant != first_constant:
                return UNKNOWN

        return first_constant

    def _binary_constant(
        self,
        instruction: SSABinaryOp,
        constants: dict[SSAValue, Any],
    ) -> Any | _Unknown:
        operator = instruction.operator
        if operator not in self._BINARY_OPERATORS:
            return UNKNOWN
        if isinstance(instruction.left.type, StringType) or isinstance(
            instruction.right.type,
            StringType,
        ):
            return UNKNOWN
        if instruction.left not in constants or instruction.right not in constants:
            return UNKNOWN

        left = constants[instruction.left]
        right = constants[instruction.right]
        try:
            if isinstance(instruction.left.type, IntType) and isinstance(instruction.right.type, IntType):
                return checked_int_binary(operator, left, right)
            if operator in {"div", "mod", "rem"} and right == 0:
                return UNKNOWN
            return self._evaluate_binary(operator, left, right)
        except (ArithmeticError, TypeError, ValueError):
            return UNKNOWN

    def _compare_constant(
        self,
        instruction: SSACompareOp,
        constants: dict[SSAValue, Any],
    ) -> Any | _Unknown:
        operator = instruction.operator
        if operator not in self._COMPARE_OPERATORS:
            return UNKNOWN
        if isinstance(instruction.left.type, StringType) or isinstance(
            instruction.right.type,
            StringType,
        ):
            return UNKNOWN
        if instruction.left not in constants or instruction.right not in constants:
            return UNKNOWN

        try:
            return self._evaluate_compare(
                operator,
                constants[instruction.left],
                constants[instruction.right],
            )
        except (ArithmeticError, TypeError, ValueError):
            return UNKNOWN

    def _cast_constant(
        self,
        instruction: SSACast,
        constants: dict[SSAValue, Any],
    ) -> Any | _Unknown:
        if instruction.value not in constants:
            return UNKNOWN

        try:
            if isinstance(instruction.result.type, DoubleType):
                return float(constants[instruction.value])
            if isinstance(instruction.result.type, IntType):
                return trunc(constants[instruction.value])
        except (ArithmeticError, TypeError, ValueError):
            return UNKNOWN
        return UNKNOWN

    @staticmethod
    def _result_value(instruction: SSAInstruction) -> SSAValue | None:
        if isinstance(instruction, SSAConst):
            return instruction.result
        if isinstance(instruction, SSAPhi):
            return instruction.result
        if isinstance(instruction, SSABinaryOp):
            return instruction.result
        if isinstance(instruction, SSACompareOp):
            return instruction.result
        if isinstance(instruction, SSACast):
            return instruction.result
        return None

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
