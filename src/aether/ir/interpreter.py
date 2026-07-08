from __future__ import annotations

from dataclasses import dataclass, field
from math import trunc
from typing import Any, NoReturn, Sequence

from .model import (
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
    IRJump,
    IRLoad,
    IRMatrixGet,
    IRMatrixNew,
    IRModule,
    IRReturn,
    IRStore,
    IRValue,
    IRVectorGet,
    IRVectorNew,
)
from .types import BoolType, DoubleType, IntType, VoidType


class IRExecutionError(RuntimeError):
    """Raised when the minimal IR interpreter cannot execute validly."""


@dataclass
class _Frame:
    values: dict[IRValue, Any] = field(default_factory=dict)
    slots: dict[IRValue, Any] = field(default_factory=dict)


class IRInterpreter:
    """Execute the initial Aether IR control-flow subset."""

    def __init__(self, module: IRModule) -> None:
        self.module = module
        self._functions = {function.name: function for function in module.functions}

    def call(self, function_name: str, arguments: Sequence[Any] = ()) -> Any:
        """Call an IR function by name using raw Python scalar values."""
        function = self._functions.get(function_name)
        if function is None:
            raise IRExecutionError(f"IR function '{function_name}' does not exist")

        if len(arguments) != len(function.parameters):
            raise IRExecutionError(
                f"IR function '{function_name}' expects {len(function.parameters)} "
                f"arguments, got {len(arguments)}"
            )

        frame = _Frame(
            values=dict(zip(function.parameters, arguments)),
        )
        return self._execute(function, frame)

    def _execute(self, function: IRFunction, frame: _Frame) -> Any:
        blocks = {block.name: block for block in function.blocks}
        current = blocks.get("entry")
        if current is None:
            raise IRExecutionError(f"IR function '{function.name}' has no entry block")

        while True:
            for instruction in current.instructions:
                returned, value, target = self._execute_instruction(instruction, frame)
                if returned:
                    if value is None and not isinstance(function.return_type, VoidType):
                        raise IRExecutionError(
                            f"IR function '{function.name}' returned void but is non-void"
                        )
                    return value
                if target is not None:
                    current = self._target_block(function, blocks, target)
                    break
            else:
                if isinstance(function.return_type, VoidType):
                    return None
                raise IRExecutionError(
                    f"IR function '{function.name}' ended without return"
                )

    def _execute_instruction(
        self,
        instruction: IRInstruction,
        frame: _Frame,
    ) -> tuple[bool, Any, str | None]:
        if isinstance(instruction, IRConst):
            frame.values[instruction.result] = instruction.value
            return False, None, None

        if isinstance(instruction, IRLoad):
            if instruction.slot not in frame.slots:
                raise IRExecutionError(
                    f"IR slot '%{instruction.slot.name}' is not initialized"
                )
            frame.values[instruction.result] = frame.slots[instruction.slot]
            return False, None, None

        if isinstance(instruction, IRStore):
            frame.slots[instruction.slot] = self._value(instruction.value, frame)
            return False, None, None

        if isinstance(instruction, IRBinaryOp):
            left = self._value(instruction.left, frame)
            right = self._value(instruction.right, frame)
            frame.values[instruction.result] = self._binary(
                instruction.operator,
                left,
                right,
            )
            return False, None, None

        if isinstance(instruction, IRCompareOp):
            left = self._value(instruction.left, frame)
            right = self._value(instruction.right, frame)
            frame.values[instruction.result] = self._compare(
                instruction.operator,
                left,
                right,
            )
            return False, None, None

        if isinstance(instruction, IRCast):
            frame.values[instruction.result] = self._cast(
                self._value(instruction.value, frame),
                instruction.result.type,
            )
            return False, None, None

        if isinstance(instruction, IRCall):
            arguments = [
                self._value(argument, frame) for argument in instruction.arguments
            ]
            result = self.call(instruction.function, arguments)
            if instruction.result is not None:
                frame.values[instruction.result] = result
            return False, None, None

        if isinstance(instruction, IRArrayNew):
            frame.values[instruction.result] = [
                self._value(element, frame) for element in instruction.elements
            ]
            return False, None, None

        if isinstance(instruction, IRVectorNew):
            frame.values[instruction.result] = [
                self._value(element, frame) for element in instruction.elements
            ]
            return False, None, None

        if isinstance(instruction, IRMatrixNew):
            frame.values[instruction.result] = [
                self._value(element, frame) for element in instruction.elements
            ]
            return False, None, None

        if isinstance(instruction, IRArrayGet):
            array = self._value(instruction.array, frame)
            index = self._value(instruction.index, frame)
            self._check_array_index(array, index)
            frame.values[instruction.result] = array[index]
            return False, None, None

        if isinstance(instruction, IRVectorGet):
            vector = self._value(instruction.vector, frame)
            index = self._value(instruction.index, frame)
            self._check_array_index(vector, index)
            frame.values[instruction.result] = vector[index]
            return False, None, None

        if isinstance(instruction, IRMatrixGet):
            matrix = self._value(instruction.matrix, frame)
            row = self._value(instruction.row, frame)
            column = self._value(instruction.column, frame)
            if not isinstance(matrix, list):
                raise IRExecutionError("IR matrix get requires a matrix value")
            if type(row) is not int or type(column) is not int:
                raise IRExecutionError("IR matrix indices must be int")
            offset = row * instruction.cols + column
            self._check_array_index(matrix, offset)
            frame.values[instruction.result] = matrix[offset]
            return False, None, None

        if isinstance(instruction, IRArraySet):
            array = self._value(instruction.array, frame)
            index = self._value(instruction.index, frame)
            self._check_array_index(array, index)
            array[index] = self._value(instruction.value, frame)
            return False, None, None

        if isinstance(instruction, IRArrayLength):
            array = self._value(instruction.array, frame)
            if not isinstance(array, list):
                raise IRExecutionError("IR array length requires an array value")
            frame.values[instruction.result] = len(array)
            return False, None, None

        if isinstance(instruction, IRBranch):
            condition = self._value(instruction.condition, frame)
            if (
                not isinstance(instruction.condition.type, BoolType)
                or type(condition) is not bool
            ):
                raise IRExecutionError("IR branch condition must be bool")
            target = instruction.true_target if condition else instruction.false_target
            return False, None, target

        if isinstance(instruction, IRJump):
            return False, None, instruction.target

        if isinstance(instruction, IRReturn):
            value = (
                None
                if instruction.value is None
                else self._value(instruction.value, frame)
            )
            return True, value, None

        raise IRExecutionError(
            f"IR instruction '{type(instruction).__name__}' is not supported"
        )

    @staticmethod
    def _target_block(
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
        target: str,
    ) -> IRBasicBlock:
        block = blocks.get(target)
        if block is None:
            raise IRExecutionError(
                f"IR target block '{target}' does not exist in function '{function.name}'"
            )
        return block

    @staticmethod
    def _value(value: IRValue, frame: _Frame) -> Any:
        if value not in frame.values:
            raise IRExecutionError(f"IR value '%{value.name}' is not initialized")
        return frame.values[value]

    @staticmethod
    def _binary(operator: str, left: Any, right: Any) -> Any:
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mul":
            return left * right
        if operator == "div":
            if right == 0:
                raise IRExecutionError("IR division by zero")
            return left / right
        if operator in {"mod", "rem"}:
            if right == 0:
                raise IRExecutionError("IR division by zero")
            return left - trunc(left / right) * right
        IRInterpreter._unsupported_binary(operator)

    @staticmethod
    def _compare(operator: str, left: Any, right: Any) -> bool:
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
        IRInterpreter._unsupported_compare(operator)

    @staticmethod
    def _cast(value: Any, target_type: object) -> Any:
        if isinstance(target_type, DoubleType):
            return float(value)
        if isinstance(target_type, IntType):
            return trunc(value)
        raise IRExecutionError(f"IR cast to '{target_type}' is not supported")

    @staticmethod
    def _check_array_index(array: Any, index: Any) -> None:
        if not isinstance(array, list):
            raise IRExecutionError("IR array indexing requires an array value")
        if type(index) is not int:
            raise IRExecutionError("IR array index must be int")
        if index < 0 or index >= len(array):
            raise IRExecutionError(
                f"IR array index {index} out of bounds for length {len(array)}"
            )

    @staticmethod
    def _unsupported_binary(operator: str) -> NoReturn:
        raise IRExecutionError(f"IR binary operation '{operator}' is not supported")

    @staticmethod
    def _unsupported_compare(operator: str) -> NoReturn:
        raise IRExecutionError(f"IR compare operation '{operator}' is not supported")
