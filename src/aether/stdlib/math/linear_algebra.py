from __future__ import annotations

from math import sqrt

import numpy as np
from scipy import linalg as scipy_linalg

from ...errors import AetherTypeError
from ...types import AetherType, AetherValue, ArrayType, MatrixType, NUMERIC_TYPES, type_to_string
from ..registry import BuiltinDefinition, BuiltinFunction, OutputWriter, RuntimeFactory


INNER_NAME = "Math.LinearAlgebra.inner"
NORM_NAME = "Math.LinearAlgebra.norm"
TRANSPOSE_NAME = "Math.LinearAlgebra.transpose"
MATMUL_NAME = "Math.LinearAlgebra.matmul"
SOLVE_NAME = "Math.LinearAlgebra.solve"


def builtin_definitions() -> list[BuiltinDefinition]:
    return [
        BuiltinDefinition(INNER_NAME, _constant_runtime(inner_builtin), _inner_type, _exactly_two(INNER_NAME)),
        BuiltinDefinition(NORM_NAME, _constant_runtime(norm_builtin), _norm_type, _exactly_one(NORM_NAME)),
        BuiltinDefinition(TRANSPOSE_NAME, _constant_runtime(transpose_builtin), _transpose_type, _exactly_one(TRANSPOSE_NAME)),
        BuiltinDefinition(MATMUL_NAME, _constant_runtime(matmul_builtin), _matmul_type, _exactly_two(MATMUL_NAME)),
        BuiltinDefinition(SOLVE_NAME, _constant_runtime(solve_builtin), _solve_type, _exactly_two(SOLVE_NAME)),
    ]


def _constant_runtime(function: BuiltinFunction) -> RuntimeFactory:
    def factory(_write_output: OutputWriter) -> BuiltinFunction:
        return function

    return factory


def _exactly_one(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")

    return validate


def _exactly_two(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 2:
            raise AetherTypeError(f"{label}(...) expects exactly two arguments.")

    return validate


def inner_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 2:
        raise AetherTypeError(f"{INNER_NAME}(...) expects exactly two arguments.")
    left_elements, left_type = _vector_elements(args[0], INNER_NAME)
    right_elements, right_type = _vector_elements(args[1], INNER_NAME)
    if len(left_elements) != len(right_elements):
        raise AetherTypeError(
            f"{INNER_NAME}(...) expects vectors with the same length, "
            f"got {len(left_elements)} and {len(right_elements)}."
        )
    result_type = _promote_numeric_types(left_type, right_type)
    total = sum(left.value * right.value for left, right in zip(left_elements, right_elements))
    if result_type == "int":
        total = int(total)
    else:
        total = float(total)
    return AetherValue(result_type, total)


def norm_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{NORM_NAME}(...) expects exactly one argument.")
    elements, _element_type = _vector_elements(args[0], NORM_NAME)
    norm_squared = sum(element.value * element.value for element in elements)
    return AetherValue("double", sqrt(norm_squared))


def transpose_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{TRANSPOSE_NAME}(...) expects exactly one argument.")
    value = args[0]
    matrix_type = _require_numeric_matrix_type(value.type_name, TRANSPOSE_NAME)
    rows = len(value.value)
    cols = len(value.value[0].value) if value.value else 0
    result_row_type = ArrayType(matrix_type.element_type)
    transposed_rows = [
        AetherValue(result_row_type, [value.value[row_index].value[col_index] for row_index in range(rows)])
        for col_index in range(cols)
    ]
    return AetherValue(MatrixType(matrix_type.element_type, cols, rows), transposed_rows)


def matmul_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 2:
        raise AetherTypeError(f"{MATMUL_NAME}(...) expects exactly two arguments.")
    left = args[0]
    right = args[1]
    left_type = _require_numeric_matrix_type(left.type_name, MATMUL_NAME)
    right_type = _require_numeric_matrix_type(right.type_name, MATMUL_NAME)
    left_rows, left_cols = _runtime_shape(left)
    right_rows, right_cols = _runtime_shape(right)
    if left_cols != right_rows:
        raise AetherTypeError(
            f"{MATMUL_NAME}(...) requires compatible shapes, got {left_rows}x{left_cols} and {right_rows}x{right_cols}."
        )
    result_element_type = _promote_numeric_types(left_type.element_type, right_type.element_type)
    result_row_type = ArrayType(result_element_type)
    result_rows: list[AetherValue] = []
    for row_index in range(left_rows):
        result_elements: list[AetherValue] = []
        for col_index in range(right_cols):
            total = 0
            for inner_index in range(left_cols):
                total += left.value[row_index].value[inner_index].value * right.value[inner_index].value[col_index].value
            if result_element_type == "int":
                total = int(total)
            else:
                total = float(total)
            result_elements.append(AetherValue(result_element_type, total))
        result_rows.append(AetherValue(result_row_type, result_elements))
    return AetherValue(MatrixType(result_element_type, left_rows, right_cols), result_rows)


def solve_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 2:
        raise AetherTypeError(f"{SOLVE_NAME}(...) expects exactly two arguments.")
    left = args[0]
    right = args[1]
    _require_numeric_matrix_type(left.type_name, SOLVE_NAME)
    _require_numeric_matrix_type(right.type_name, SOLVE_NAME)
    left_rows, left_cols = _runtime_shape(left)
    right_rows, right_cols = _runtime_shape(right)
    if left_rows == 0 or left_cols == 0:
        raise AetherTypeError(f"{SOLVE_NAME}(...) does not accept an empty coefficient matrix.")
    if right_rows == 0 or right_cols == 0:
        raise AetherTypeError(f"{SOLVE_NAME}(...) does not accept an empty right-hand side.")

    rhs_is_vector = _is_runtime_vector_like(right)
    normalized_right = right
    if right_rows == 1 and right_cols == left_rows and left_rows != 1:
        normalized_right = transpose_builtin([right])
        right_rows, right_cols = _runtime_shape(normalized_right)
        rhs_is_vector = True

    if right_rows != left_rows:
        raise AetherTypeError(
            f"{SOLVE_NAME}(...) requires rows(A) == rows(b), got {left_rows} and {right_rows}."
        )

    left_array = _matrix_to_float_array(left)
    right_array = _matrix_to_float_array(normalized_right)
    try:
        if left_rows == left_cols:
            if np.linalg.matrix_rank(left_array) == left_cols:
                solution = scipy_linalg.solve(left_array, right_array)
            else:
                solution = scipy_linalg.lstsq(left_array, right_array)[0]
        else:
            solution = scipy_linalg.lstsq(left_array, right_array)[0]
    except Exception as exc:
        raise AetherTypeError(f"{SOLVE_NAME}(...) could not solve the linear system: {exc}") from exc

    solution = np.atleast_2d(np.asarray(solution, dtype=float))
    if solution.shape[0] != left_cols and solution.shape[1] == left_cols:
        solution = solution.T
    solution[np.abs(solution) < 1e-12] = 0.0
    return _float_array_to_matrix_value(solution, vector=rhs_is_vector and solution.shape[1] == 1)


def _inner_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 2:
        raise AetherTypeError(f"{INNER_NAME}(...) expects exactly two arguments.")
    left_type, right_type = arg_types
    if left_type is None or right_type is None:
        return None
    left_length = _require_numeric_vector_type(left_type, INNER_NAME)
    right_length = _require_numeric_vector_type(right_type, INNER_NAME)
    if left_length is not None and right_length is not None and left_length != right_length:
        raise AetherTypeError(
            f"{INNER_NAME}(...) expects vectors with the same length, got {left_length} and {right_length}."
        )
    return _promote_numeric_types(left_type.element_type, right_type.element_type)


def _norm_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{NORM_NAME}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    _require_numeric_vector_type(argument_type, NORM_NAME)
    return "double"


def _transpose_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{TRANSPOSE_NAME}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    matrix_type = _require_numeric_matrix_type(argument_type, TRANSPOSE_NAME)
    rows = matrix_type.rows
    cols = matrix_type.cols
    return MatrixType(matrix_type.element_type, cols, rows)


def _matmul_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 2:
        raise AetherTypeError(f"{MATMUL_NAME}(...) expects exactly two arguments.")
    left_type, right_type = arg_types
    if left_type is None or right_type is None:
        return None
    left_matrix_type = _require_numeric_matrix_type(left_type, MATMUL_NAME)
    right_matrix_type = _require_numeric_matrix_type(right_type, MATMUL_NAME)
    if (
        left_matrix_type.cols is not None
        and right_matrix_type.rows is not None
        and left_matrix_type.cols != right_matrix_type.rows
    ):
        raise AetherTypeError(
            f"{MATMUL_NAME}(...) requires compatible shapes, got "
            f"{left_matrix_type.rows}x{left_matrix_type.cols} and {right_matrix_type.rows}x{right_matrix_type.cols}."
        )
    result_element_type = _promote_numeric_types(left_matrix_type.element_type, right_matrix_type.element_type)
    return MatrixType(result_element_type, left_matrix_type.rows, right_matrix_type.cols)


def _solve_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 2:
        raise AetherTypeError(f"{SOLVE_NAME}(...) expects exactly two arguments.")
    left_type, right_type = arg_types
    if left_type is None or right_type is None:
        return None
    left_matrix_type = _require_numeric_matrix_type(left_type, SOLVE_NAME)
    right_matrix_type = _require_numeric_matrix_type(right_type, SOLVE_NAME)
    right_rows, right_cols, result_is_vector = _normalized_rhs_type_shape(left_matrix_type, right_matrix_type)
    if left_matrix_type.rows is not None and right_rows is not None and left_matrix_type.rows != right_rows:
        raise AetherTypeError(
            f"{SOLVE_NAME}(...) requires rows(A) == rows(b), got {left_matrix_type.rows} and {right_rows}."
        )
    return MatrixType("double", left_matrix_type.cols, right_cols, result_is_vector)


def _vector_elements(value: AetherValue, label: str) -> tuple[list[AetherValue], str]:
    if not isinstance(value.type_name, MatrixType):
        raise AetherTypeError(f"{label}(...) expects mathematical vector arguments, got '{type_to_string(value.type_name)}'.")
    element_type = value.type_name.element_type
    if element_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects vectors with numeric elements.")
    rows = len(value.value)
    cols = len(value.value[0].value) if value.value else 0
    if rows == 0 or cols == 0 or (rows > 1 and cols > 1):
        raise AetherTypeError(f"{label}(...) expects a row or column vector, got {rows}x{cols}.")
    if rows == 1:
        return list(value.value[0].value), element_type
    return [row.value[0] for row in value.value], element_type


def _runtime_shape(value: AetherValue) -> tuple[int, int]:
    rows = len(value.value)
    cols = len(value.value[0].value) if value.value else 0
    return rows, cols


def _is_runtime_vector_like(value: AetherValue) -> bool:
    if not isinstance(value.type_name, MatrixType):
        return False
    rows, cols = _runtime_shape(value)
    return value.type_name.vector or rows == 1 or cols == 1


def _matrix_to_float_array(value: AetherValue) -> np.ndarray:
    return np.array([[float(element.value) for element in row.value] for row in value.value], dtype=float)


def _float_array_to_matrix_value(values: np.ndarray, *, vector: bool = False) -> AetherValue:
    rows, cols = values.shape
    row_type = ArrayType("double")
    result_rows = [
        AetherValue(row_type, [AetherValue("double", float(values[row_index, col_index])) for col_index in range(cols)])
        for row_index in range(rows)
    ]
    return AetherValue(MatrixType("double", rows, cols, vector), result_rows)


def _require_numeric_matrix_type(type_name: AetherType, label: str) -> MatrixType:
    if not isinstance(type_name, MatrixType):
        raise AetherTypeError(f"{label}(...) expects a mathematical matrix argument, got '{type_to_string(type_name)}'.")
    if type_name.element_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects a matrix with numeric elements.")
    return type_name


def _require_numeric_vector_type(type_name: AetherType, label: str) -> int | None:
    if not isinstance(type_name, MatrixType):
        raise AetherTypeError(f"{label}(...) expects mathematical vector arguments, got '{type_to_string(type_name)}'.")
    if type_name.element_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects vectors with numeric elements.")
    if type_name.rows is None or type_name.cols is None:
        return None
    if type_name.rows <= 0 or type_name.cols <= 0 or (type_name.rows > 1 and type_name.cols > 1):
        raise AetherTypeError(f"{label}(...) expects a row or column vector, got {type_name.rows}x{type_name.cols}.")
    return type_name.cols if type_name.rows == 1 else type_name.rows


def _normalized_rhs_type_shape(
    left_type: MatrixType,
    right_type: MatrixType,
) -> tuple[int | None, int | None, bool]:
    if right_type.vector:
        return _vector_length(right_type), 1, True
    if right_type.rows == 1 and left_type.rows is not None and right_type.cols == left_type.rows and left_type.rows != 1:
        return right_type.cols, 1, True
    if right_type.cols == 1:
        return right_type.rows, 1, True
    return right_type.rows, right_type.cols, False


def _vector_length(type_name: MatrixType) -> int | None:
    if type_name.rows is None or type_name.cols is None:
        return None
    if type_name.rows == 1:
        return type_name.cols
    if type_name.cols == 1:
        return type_name.rows
    return type_name.rows


def _promote_numeric_types(left_type: str, right_type: str) -> str:
    if "double" in {left_type, right_type}:
        return "double"
    if "float" in {left_type, right_type}:
        return "float"
    return "int"
