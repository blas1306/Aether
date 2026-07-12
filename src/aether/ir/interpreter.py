from __future__ import annotations

from dataclasses import dataclass, field
import math
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
    IRListGet,
    IRListCopy,
    IRListContains,
    IRListClear,
    IRListPop,
    IRListPush,
    IRListIndexOf,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListSet,
    IRListReverse,
    IRSequenceSort,
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
from .types import (
    ArrayType,
    ClassRefType,
    DoubleType,
    IntType,
    InterfaceType,
    ListType,
    MatrixType,
    StringType,
    VectorType,
    VoidType,
)


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

        if isinstance(instruction, IRListNew):
            frame.values[instruction.result] = [
                self._value(element, frame) for element in instruction.elements
            ]
            return False, None, None

        if isinstance(instruction, IRListCopy):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_copy requires a list value")
            frame.values[instruction.result] = list(list_value)
            return False, None, None

        if isinstance(instruction, IRListContains):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_contains requires a list value")
            value = self._value(instruction.value, frame)
            reference_type = isinstance(
                instruction.value.type,
                (ArrayType, ClassRefType, InterfaceType, ListType, MatrixType, VectorType),
            )
            frame.values[instruction.result] = self._list_index_of(list_value, value, reference_type) >= 0
            return False, None, None

        if isinstance(instruction, IRListIndexOf):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_index_of requires a list value")
            value = self._value(instruction.value, frame)
            reference_type = isinstance(
                instruction.value.type,
                (ArrayType, ClassRefType, InterfaceType, ListType, MatrixType, VectorType),
            )
            frame.values[instruction.result] = self._list_index_of(list_value, value, reference_type)
            return False, None, None

        if isinstance(instruction, IRListClear):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_clear requires a list value")
            list_value.clear()
            return False, None, None

        if isinstance(instruction, IRListPush):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_push requires a list value")
            list_value.append(self._value(instruction.value, frame))
            return False, None, None

        if isinstance(instruction, IRListPop):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_pop requires a list value")
            if not list_value:
                raise IRExecutionError("pop() cannot be used on an empty List")
            frame.values[instruction.result] = list_value.pop()
            return False, None, None

        if isinstance(instruction, IRListReverse):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_reverse requires a list value")
            left = 0
            right = len(list_value) - 1
            while left < right:
                list_value[left], list_value[right] = list_value[right], list_value[left]
                left += 1
                right -= 1
            return False, None, None

        if isinstance(instruction, IRSequenceSort):
            sequence = self._value(instruction.sequence, frame)
            if not isinstance(sequence, list):
                raise IRExecutionError("IR sequence_sort requires a sequence value")
            element_type = instruction.sequence.type.element
            if isinstance(element_type, DoubleType):
                sequence.sort(key=lambda value: (math.isnan(value), 0.0 if math.isnan(value) else value))
            elif isinstance(element_type, StringType):
                sequence.sort(key=lambda value: value.encode("utf-8"))
            elif isinstance(element_type, IntType):
                sequence.sort()
            else:
                raise IRExecutionError(f"IR sequence_sort does not support {element_type}")
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

        if isinstance(instruction, IRVectorAdd):
            self._execute_vector_binary(instruction, frame, "add")
            return False, None, None

        if isinstance(instruction, IRVectorSub):
            self._execute_vector_binary(instruction, frame, "sub")
            return False, None, None

        if isinstance(instruction, IRVectorScale):
            self._execute_vector_scale(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRVectorDot):
            self._execute_vector_dot(instruction, frame)
            return False, None, None

        if isinstance(instruction, IROuterProduct):
            self._execute_outer_product(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRMatrixAdd):
            self._execute_matrix_binary(instruction, frame, "add")
            return False, None, None

        if isinstance(instruction, IRMatrixSub):
            self._execute_matrix_binary(instruction, frame, "sub")
            return False, None, None

        if isinstance(instruction, IRMatrixScale):
            self._execute_matrix_scale(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRMatrixMatMul):
            self._execute_matrix_matmul(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRMatrixVectorMul):
            self._execute_matrix_vector_mul(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRVectorMatrixMul):
            self._execute_vector_matrix_mul(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRArrayGet):
            array = self._value(instruction.array, frame)
            index = self._value(instruction.index, frame)
            self._check_array_index(array, index)
            frame.values[instruction.result] = array[index]
            return False, None, None

        if isinstance(instruction, IRListGet):
            list_value = self._value(instruction.list_value, frame)
            index = self._value(instruction.index, frame)
            self._check_array_index(list_value, index)
            frame.values[instruction.result] = list_value[index]
            return False, None, None

        if isinstance(instruction, IRListSet):
            list_value = self._value(instruction.list_value, frame)
            index = self._value(instruction.index, frame)
            self._check_array_index(list_value, index)
            list_value[index] = self._value(instruction.value, frame)
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
            self._check_matrix_index(matrix, row, column, instruction.cols)
            frame.values[instruction.result] = matrix[row * instruction.cols + column]
            return False, None, None

        if isinstance(instruction, IRVectorLength):
            vector = self._value(instruction.vector, frame)
            if not isinstance(vector, list):
                raise IRExecutionError("IR vector_length requires a vector value")
            frame.values[instruction.result] = len(vector)
            return False, None, None

        if isinstance(instruction, IRMatrixRows):
            frame.values[instruction.result] = instruction.rows
            return False, None, None

        if isinstance(instruction, IRMatrixColumns):
            frame.values[instruction.result] = instruction.columns
            return False, None, None

        if isinstance(instruction, IRArraySet):
            array = self._value(instruction.array, frame)
            index = self._value(instruction.index, frame)
            value = self._value(instruction.value, frame)
            self._check_array_index(array, index)
            array[index] = value
            return False, None, None

        if isinstance(instruction, IRVectorSet):
            vector = self._value(instruction.vector, frame)
            index = self._value(instruction.index, frame)
            value = self._value(instruction.value, frame)
            self._check_array_index(vector, index)
            vector[index] = value
            return False, None, None

        if isinstance(instruction, IRMatrixSet):
            matrix = self._value(instruction.matrix, frame)
            row = self._value(instruction.row, frame)
            column = self._value(instruction.column, frame)
            value = self._value(instruction.value, frame)
            self._check_matrix_index(matrix, row, column, instruction.cols)
            matrix[row * instruction.cols + column] = value
            return False, None, None

        if isinstance(instruction, IRArrayLength):
            array = self._value(instruction.array, frame)
            if not isinstance(array, list):
                raise IRExecutionError("IR array_length requires an array value")
            frame.values[instruction.result] = len(array)
            return False, None, None

        if isinstance(instruction, IRListLength):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_length requires a list value")
            frame.values[instruction.result] = len(list_value)
            return False, None, None

        if isinstance(instruction, IRListIsEmpty):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_is_empty requires a list value")
            frame.values[instruction.result] = len(list_value) == 0
            return False, None, None

        if isinstance(instruction, IRBranch):
            condition = self._value(instruction.condition, frame)
            if not isinstance(condition, bool):
                raise IRExecutionError("IR branch condition must be bool")
            return False, None, instruction.true_target if condition else instruction.false_target

        if isinstance(instruction, IRJump):
            return False, None, instruction.target

        if isinstance(instruction, IRReturn):
            if instruction.value is None:
                return True, None, None
            return True, self._value(instruction.value, frame), None

        raise IRExecutionError(f"Unsupported IR instruction {type(instruction).__name__}")

    def _execute_vector_binary(
        self,
        instruction: IRVectorAdd | IRVectorSub,
        frame: _Frame,
        operator: str,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError(f"IR vector {operator} requires vector values")
        if len(left) != instruction.length or len(right) != instruction.length:
            raise IRExecutionError(f"IR vector {operator} operands must match instruction length")
        frame.values[instruction.result] = [
            self._binary(operator, left_value, right_value)
            for left_value, right_value in zip(left, right)
        ]

    def _execute_vector_scale(
        self,
        instruction: IRVectorScale,
        frame: _Frame,
    ) -> None:
        vector = self._value(instruction.vector, frame)
        scalar = self._value(instruction.scalar, frame)
        if not isinstance(vector, list):
            raise IRExecutionError("IR vector scale requires a vector value")
        if len(vector) != instruction.length:
            raise IRExecutionError("IR vector scale operand must match instruction length")
        frame.values[instruction.result] = [
            self._binary("mul", value, scalar)
            for value in vector
        ]

    def _execute_vector_dot(
        self,
        instruction: IRVectorDot,
        frame: _Frame,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError("IR vector dot requires vector values")
        if len(left) != instruction.length or len(right) != instruction.length:
            raise IRExecutionError("IR vector dot operands must match instruction length")
        total = 0.0 if isinstance(instruction.result.type, DoubleType) else 0
        for left_value, right_value in zip(left, right):
            total = self._binary("add", total, self._binary("mul", left_value, right_value))
        frame.values[instruction.result] = total

    def _execute_outer_product(
        self,
        instruction: IROuterProduct,
        frame: _Frame,
    ) -> None:
        column = self._value(instruction.column, frame)
        row = self._value(instruction.row, frame)
        if not isinstance(column, list) or not isinstance(row, list):
            raise IRExecutionError("IR outer product requires vector values")
        if len(column) != instruction.rows or len(row) != instruction.cols:
            raise IRExecutionError("IR outer product operands must match instruction dimensions")

        result: list[Any] = []
        for row_index in range(instruction.rows):
            for col_index in range(instruction.cols):
                result.append(self._binary("mul", column[row_index], row[col_index]))
        frame.values[instruction.result] = result

    def _execute_matrix_binary(
        self,
        instruction: IRMatrixAdd | IRMatrixSub,
        frame: _Frame,
        operator: str,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError(f"IR matrix {operator} requires matrix values")
        element_count = instruction.rows * instruction.cols
        if len(left) != element_count or len(right) != element_count:
            raise IRExecutionError(f"IR matrix {operator} operands must match instruction dimensions")
        frame.values[instruction.result] = [
            self._binary(operator, left_value, right_value)
            for left_value, right_value in zip(left, right)
        ]

    def _execute_matrix_scale(
        self,
        instruction: IRMatrixScale,
        frame: _Frame,
    ) -> None:
        matrix = self._value(instruction.matrix, frame)
        scalar = self._value(instruction.scalar, frame)
        if not isinstance(matrix, list):
            raise IRExecutionError("IR matrix scale requires a matrix value")
        element_count = instruction.rows * instruction.cols
        if len(matrix) != element_count:
            raise IRExecutionError("IR matrix scale operand must match instruction dimensions")
        frame.values[instruction.result] = [
            self._binary("mul", value, scalar)
            for value in matrix
        ]

    def _execute_matrix_matmul(
        self,
        instruction: IRMatrixMatMul,
        frame: _Frame,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError("IR matrix matmul requires matrix values")
        if len(left) != instruction.rows * instruction.inner:
            raise IRExecutionError("IR matrix matmul left operand must match instruction dimensions")
        if len(right) != instruction.inner * instruction.cols:
            raise IRExecutionError("IR matrix matmul right operand must match instruction dimensions")

        result: list[Any] = []
        for row in range(instruction.rows):
            for col in range(instruction.cols):
                total = 0.0 if isinstance(instruction.result.type, DoubleType) else 0
                for inner in range(instruction.inner):
                    left_value = left[row * instruction.inner + inner]
                    right_value = right[inner * instruction.cols + col]
                    total = self._binary("add", total, self._binary("mul", left_value, right_value))
                result.append(total)
        frame.values[instruction.result] = result

    def _execute_matrix_vector_mul(
        self,
        instruction: IRMatrixVectorMul,
        frame: _Frame,
    ) -> None:
        matrix = self._value(instruction.matrix, frame)
        vector = self._value(instruction.vector, frame)
        if not isinstance(matrix, list) or not isinstance(vector, list):
            raise IRExecutionError("IR matrix vector mul requires matrix and vector values")
        if len(matrix) != instruction.rows * instruction.inner:
            raise IRExecutionError("IR matrix vector mul matrix operand must match instruction dimensions")
        if len(vector) != instruction.inner:
            raise IRExecutionError("IR matrix vector mul vector operand must match instruction dimensions")

        result: list[Any] = []
        for row in range(instruction.rows):
            total = 0.0 if isinstance(instruction.result.type.element, DoubleType) else 0
            for inner in range(instruction.inner):
                matrix_value = matrix[row * instruction.inner + inner]
                vector_value = vector[inner]
                total = self._binary("add", total, self._binary("mul", matrix_value, vector_value))
            result.append(total)
        frame.values[instruction.result] = result

    def _execute_vector_matrix_mul(
        self,
        instruction: IRVectorMatrixMul,
        frame: _Frame,
    ) -> None:
        vector = self._value(instruction.vector, frame)
        matrix = self._value(instruction.matrix, frame)
        if not isinstance(vector, list) or not isinstance(matrix, list):
            raise IRExecutionError("IR vector matrix mul requires vector and matrix values")
        if len(vector) != instruction.rows:
            raise IRExecutionError("IR vector matrix mul vector operand must match instruction dimensions")
        if len(matrix) != instruction.rows * instruction.cols:
            raise IRExecutionError("IR vector matrix mul matrix operand must match instruction dimensions")

        result: list[Any] = []
        for col in range(instruction.cols):
            total = 0.0 if isinstance(instruction.result.type.element, DoubleType) else 0
            for row in range(instruction.rows):
                vector_value = vector[row]
                matrix_value = matrix[row * instruction.cols + col]
                total = self._binary("add", total, self._binary("mul", vector_value, matrix_value))
            result.append(total)
        frame.values[instruction.result] = result

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
    def _list_index_of(list_value: list[Any], value: Any, reference_type: bool) -> int:
        for index, element in enumerate(list_value):
            if (element is value) if reference_type else (element == value):
                return index
        return -1

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
    def _check_matrix_index(matrix: Any, row: Any, column: Any, cols: int) -> None:
        if not isinstance(matrix, list):
            raise IRExecutionError("IR matrix indexing requires a matrix value")
        if type(row) is not int or type(column) is not int:
            raise IRExecutionError("IR matrix indices must be int")
        offset = row * cols + column
        IRInterpreter._check_array_index(matrix, offset)

    @staticmethod
    def _unsupported_binary(operator: str) -> NoReturn:
        raise IRExecutionError(f"IR binary operation '{operator}' is not supported")

    @staticmethod
    def _unsupported_compare(operator: str) -> NoReturn:
        raise IRExecutionError(f"IR compare operation '{operator}' is not supported")
