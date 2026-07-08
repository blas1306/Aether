from __future__ import annotations

from math import sqrt

import numpy as np
from scipy import linalg as scipy_linalg

from ...errors import AetherTypeError
from ...types import (
    AetherType,
    AetherValue,
    ArrayType,
    MatrixType,
    NUMERIC_TYPES,
    TransposeVectorType,
    TupleType,
    VectorType,
    type_to_string,
)
from ..registry import BuiltinDefinition, BuiltinFunction, RuntimeContext, RuntimeFactory


INNER_NAME = "Math.LinearAlgebra.inner"
NORM_NAME = "Math.LinearAlgebra.norm"
TRANSPOSE_NAME = "Math.LinearAlgebra.transpose"
CONJTRANSPOSE_NAME = "Math.LinearAlgebra.conjtranspose"
MATMUL_NAME = "Math.LinearAlgebra.matmul"
SOLVE_NAME = "Math.LinearAlgebra.solve"
EIG_NAME = "Math.LinearAlgebra.eig"
SVD_NAME = "Math.LinearAlgebra.SVD"
LU_NAME = "Math.LinearAlgebra.LU"
LDU_NAME = "Math.LinearAlgebra.LDU"
ZEROS_NAME = "Math.LinearAlgebra.zeros"
ONES_NAME = "Math.LinearAlgebra.ones"
NULL_SPACE_NAME = "Math.LinearAlgebra.N"
RANGE_NAME = "Math.LinearAlgebra.R"
RANK_NAME = "Math.LinearAlgebra.rank"


def builtin_definitions() -> list[BuiltinDefinition]:
    return [
        BuiltinDefinition(INNER_NAME, _constant_runtime(inner_builtin), _inner_type, _exactly_two(INNER_NAME)),
        BuiltinDefinition(NORM_NAME, _constant_runtime(norm_builtin), _norm_type, _exactly_one(NORM_NAME)),
        BuiltinDefinition(TRANSPOSE_NAME, _constant_runtime(transpose_builtin), _transpose_type, _exactly_one(TRANSPOSE_NAME)),
        BuiltinDefinition(
            CONJTRANSPOSE_NAME,
            _constant_runtime(conjtranspose_builtin),
            _conjtranspose_type,
            _exactly_one(CONJTRANSPOSE_NAME),
        ),
        BuiltinDefinition(MATMUL_NAME, _constant_runtime(matmul_builtin), _matmul_type, _exactly_two(MATMUL_NAME)),
        BuiltinDefinition(SOLVE_NAME, _constant_runtime(solve_builtin), _solve_type, _exactly_two(SOLVE_NAME)),
        BuiltinDefinition(EIG_NAME, _constant_runtime(eig_builtin), _eig_type, _exactly_one(EIG_NAME)),
        BuiltinDefinition(SVD_NAME, _constant_runtime(svd_builtin), _svd_type, _exactly_one(SVD_NAME)),
        BuiltinDefinition(LU_NAME, _constant_runtime(lu_builtin), _lu_type, _exactly_one(LU_NAME)),
        BuiltinDefinition(LDU_NAME, _constant_runtime(ldu_builtin), _ldu_type, _exactly_one(LDU_NAME)),
        BuiltinDefinition(ZEROS_NAME, _constant_runtime(zeros_builtin), _matrix_factory_type(ZEROS_NAME), _exactly_two(ZEROS_NAME)),
        BuiltinDefinition(ONES_NAME, _constant_runtime(ones_builtin), _matrix_factory_type(ONES_NAME), _exactly_two(ONES_NAME)),
        BuiltinDefinition(NULL_SPACE_NAME, _constant_runtime(null_space_builtin), _null_space_type, _exactly_one(NULL_SPACE_NAME)),
        BuiltinDefinition(RANGE_NAME, _constant_runtime(range_builtin), _range_type, _exactly_one(RANGE_NAME)),
        BuiltinDefinition(RANK_NAME, _constant_runtime(rank_builtin), _rank_type, _exactly_one(RANK_NAME)),
    ]


def _constant_runtime(function: BuiltinFunction) -> RuntimeFactory:
    def factory(_context: RuntimeContext) -> BuiltinFunction:
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
    total = sum(left.value.conjugate() * right.value if isinstance(left.value, complex) else left.value * right.value for left, right in zip(left_elements, right_elements))
    return _coerced_numeric_result(total, result_type)


def norm_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{NORM_NAME}(...) expects exactly one argument.")
    elements, _element_type = _vector_elements(args[0], NORM_NAME)
    norm_squared = sum(abs(element.value) ** 2 for element in elements)
    return AetherValue("double", sqrt(norm_squared))


def transpose_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{TRANSPOSE_NAME}(...) expects exactly one argument.")
    return _transpose_value(args[0], TRANSPOSE_NAME, conjugate=False)


def conjtranspose_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{CONJTRANSPOSE_NAME}(...) expects exactly one argument.")
    return _transpose_value(args[0], CONJTRANSPOSE_NAME, conjugate=True)


def _transpose_value(value: AetherValue, label: str, *, conjugate: bool) -> AetherValue:
    if isinstance(value.type_name, TransposeVectorType):
        raise AetherTypeError(
            f"{label}(...) no longer accepts legacy TransposeVector values; "
            "use oriented Vector values instead."
        )
    if isinstance(value.type_name, VectorType):
        if value.type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects a vector with numeric elements.")
        result_orientation = _flipped_vector_orientation(value.type_name.orientation, label)
        elements = list(value.value)
        if conjugate:
            elements = [_conjugate_scalar(element) for element in elements]
        return AetherValue(
            VectorType(value.type_name.element_type, len(elements), result_orientation),
            elements,
        )
    matrix_type = _require_numeric_matrix_type(value.type_name, label)
    rows = len(value.value)
    cols = len(value.value[0].value) if value.value else 0
    result_row_type = ArrayType(matrix_type.element_type)
    transposed_rows = [
        AetherValue(
            result_row_type,
            [
                _conjugate_scalar(value.value[row_index].value[col_index])
                if conjugate
                else value.value[row_index].value[col_index]
                for row_index in range(rows)
            ],
        )
        for col_index in range(cols)
    ]
    return AetherValue(MatrixType(matrix_type.element_type, cols, rows), transposed_rows)


def matmul_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 2:
        raise AetherTypeError(f"{MATMUL_NAME}(...) expects exactly two arguments.")
    left = args[0]
    right = args[1]
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, VectorType):
        return _matrix_vector_multiply(left, right, MATMUL_NAME)
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
            result_elements.append(_coerced_numeric_result(total, result_element_type))
        result_rows.append(AetherValue(result_row_type, result_elements))
    return AetherValue(MatrixType(result_element_type, left_rows, right_cols), result_rows)


def solve_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 2:
        raise AetherTypeError(f"{SOLVE_NAME}(...) expects exactly two arguments.")
    left = args[0]
    right = args[1]
    left_matrix_type = _require_numeric_matrix_type(left.type_name, SOLVE_NAME)
    if isinstance(right.type_name, VectorType):
        if right.type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{SOLVE_NAME}(...) expects a vector with numeric elements.")
        right_element_type = right.type_name.element_type
    else:
        right_element_type = _require_numeric_matrix_type(right.type_name, SOLVE_NAME).element_type
    left_rows, left_cols = _runtime_shape(left)
    normalized_right = _vector_to_column_matrix(right) if isinstance(right.type_name, VectorType) else right
    right_rows, right_cols = _runtime_shape(normalized_right)
    if left_rows == 0 or left_cols == 0:
        raise AetherTypeError(f"{SOLVE_NAME}(...) does not accept an empty coefficient matrix.")
    if right_rows == 0 or right_cols == 0:
        raise AetherTypeError(f"{SOLVE_NAME}(...) does not accept an empty right-hand side.")

    rhs_is_vector = isinstance(right.type_name, VectorType) or _is_runtime_vector_like(right)
    if right_rows == 1 and right_cols == left_rows and left_rows != 1:
        normalized_right = transpose_builtin([right])
        right_rows, right_cols = _runtime_shape(normalized_right)
        rhs_is_vector = True

    if right_rows != left_rows:
        raise AetherTypeError(
            f"{SOLVE_NAME}(...) requires rows(A) == rows(b), got {left_rows} and {right_rows}."
        )

    left_array = _matrix_to_numeric_array(left)
    right_array = _matrix_to_numeric_array(normalized_right)
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

    solution = np.atleast_2d(np.asarray(solution))
    if solution.shape[0] != left_cols and solution.shape[1] == left_cols:
        solution = solution.T
    result_element_type = _promote_numeric_types(left_matrix_type.element_type, right_element_type)
    if rhs_is_vector and solution.shape[1] == 1:
        return _numeric_array_to_vector_value(solution[:, 0], element_type=result_element_type)
    return _numeric_array_to_matrix_value(solution, element_type=result_element_type)


def eig_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{EIG_NAME}(...) expects exactly one argument.")
    matrix_type = _require_numeric_matrix_type(args[0].type_name, EIG_NAME)
    rows, cols = _runtime_shape(args[0])
    if rows == 0 or cols == 0:
        raise AetherTypeError(f"{EIG_NAME}(...) does not accept an empty matrix.")
    if rows != cols:
        raise AetherTypeError(f"{EIG_NAME}(...) expects a square matrix, got {rows}x{cols}.")

    matrix = _matrix_to_numeric_array(args[0])
    try:
        eigenvalues, eigenvectors = scipy_linalg.eig(matrix)
    except Exception as exc:
        raise AetherTypeError(f"{EIG_NAME}(...) could not compute the diagonalization: {exc}") from exc

    if np.linalg.matrix_rank(eigenvectors, tol=1e-10) < rows:
        raise AetherTypeError(f"{EIG_NAME}(...) could not diagonalize the matrix; it is not diagonalizable.")

    diagonal = np.diag(eigenvalues)
    result_element_type = _decomposition_result_element_type(eigenvectors, diagonal, prefer_complex=matrix_type.element_type == "complex")
    s_value = _numeric_array_to_matrix_value(eigenvectors, element_type=result_element_type)
    d_value = _numeric_array_to_matrix_value(diagonal, element_type=result_element_type)
    return AetherValue(TupleType((s_value.type_name, d_value.type_name)), (s_value, d_value))


def svd_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{SVD_NAME}(...) expects exactly one argument.")
    matrix_type = _require_numeric_matrix_type(args[0].type_name, SVD_NAME)
    rows, cols = _runtime_shape(args[0])
    if rows == 0 or cols == 0:
        raise AetherTypeError(f"{SVD_NAME}(...) does not accept an empty matrix.")

    matrix = _matrix_to_numeric_array(args[0])
    try:
        u_matrix, singular_values, vh_matrix = scipy_linalg.svd(matrix, full_matrices=True)
    except Exception as exc:
        raise AetherTypeError(f"{SVD_NAME}(...) could not compute the decomposition: {exc}") from exc

    sigma_matrix = np.zeros((rows, cols), dtype=float)
    for index, singular_value in enumerate(singular_values):
        sigma_matrix[index, index] = singular_value

    unitary_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    u_value = _numeric_array_to_matrix_value(u_matrix, element_type=unitary_element_type)
    sigma_value = _numeric_array_to_matrix_value(sigma_matrix, element_type="double")
    v_value = _numeric_array_to_matrix_value(vh_matrix.conjugate().T, element_type=unitary_element_type)
    return AetherValue(
        TupleType((u_value.type_name, sigma_value.type_name, v_value.type_name)),
        (u_value, sigma_value, v_value),
    )


def lu_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{LU_NAME}(...) expects exactly one argument.")
    p_matrix, l_matrix, u_matrix, factor_element_type = _lu_factor_arrays(args[0], LU_NAME)
    p_value = _numeric_array_to_matrix_value(p_matrix, element_type="double")
    l_value = _numeric_array_to_matrix_value(l_matrix, element_type=factor_element_type)
    u_value = _numeric_array_to_matrix_value(u_matrix, element_type=factor_element_type)
    return AetherValue(TupleType((p_value.type_name, l_value.type_name, u_value.type_name)), (p_value, l_value, u_value))


def ldu_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{LDU_NAME}(...) expects exactly one argument.")
    p_matrix, l_matrix, u_matrix, factor_element_type = _lu_factor_arrays(args[0], LDU_NAME)
    size = u_matrix.shape[0]
    d_matrix = np.zeros_like(u_matrix)
    unit_u = np.zeros_like(u_matrix)
    for row_index in range(size):
        pivot = u_matrix[row_index, row_index]
        d_matrix[row_index, row_index] = pivot
        if abs(pivot) <= 1e-12:
            if np.any(np.abs(u_matrix[row_index, row_index + 1 :]) > 1e-12):
                raise AetherTypeError(f"{LDU_NAME}(...) requires nonzero pivots for LDU factorization.")
            unit_u[row_index, row_index] = 1.0
            continue
        unit_u[row_index, row_index:] = u_matrix[row_index, row_index:] / pivot
    p_value = _numeric_array_to_matrix_value(p_matrix, element_type="double")
    l_value = _numeric_array_to_matrix_value(l_matrix, element_type=factor_element_type)
    d_value = _numeric_array_to_matrix_value(d_matrix, element_type=factor_element_type)
    u_value = _numeric_array_to_matrix_value(unit_u, element_type=factor_element_type)
    return AetherValue(
        TupleType((p_value.type_name, l_value.type_name, d_value.type_name, u_value.type_name)),
        (p_value, l_value, d_value, u_value),
    )


def zeros_builtin(args: list[AetherValue]) -> AetherValue:
    rows, cols = _matrix_factory_dimensions(args, ZEROS_NAME)
    return _filled_double_matrix(rows, cols, 0.0)


def ones_builtin(args: list[AetherValue]) -> AetherValue:
    rows, cols = _matrix_factory_dimensions(args, ONES_NAME)
    return _filled_double_matrix(rows, cols, 1.0)


def null_space_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{NULL_SPACE_NAME}(...) expects exactly one argument.")
    matrix_type = _require_numeric_matrix_type(args[0].type_name, NULL_SPACE_NAME)
    basis = scipy_linalg.null_space(_matrix_to_numeric_array(args[0]))
    result_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    return _numeric_array_to_matrix_value(basis, element_type=result_element_type)


def range_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{RANGE_NAME}(...) expects exactly one argument.")
    matrix_type = _require_numeric_matrix_type(args[0].type_name, RANGE_NAME)
    basis = scipy_linalg.orth(_matrix_to_numeric_array(args[0]))
    result_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    return _numeric_array_to_matrix_value(basis, element_type=result_element_type)


def rank_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{RANK_NAME}(...) expects exactly one argument.")
    _require_numeric_matrix_type(args[0].type_name, RANK_NAME)
    rank = int(np.linalg.matrix_rank(_matrix_to_numeric_array(args[0])))
    return AetherValue("int", rank)


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
    return _transpose_like_type(arg_types, TRANSPOSE_NAME)


def _conjtranspose_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _transpose_like_type(arg_types, CONJTRANSPOSE_NAME)


def _transpose_like_type(arg_types: list[AetherType | None], label: str) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if isinstance(argument_type, TransposeVectorType):
        raise AetherTypeError(
            f"{label}(...) no longer accepts legacy TransposeVector values; "
            "use oriented Vector values instead."
        )
    if isinstance(argument_type, VectorType):
        if argument_type.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects a vector with numeric elements.")
        return VectorType(
            argument_type.element_type,
            argument_type.length,
            _flipped_vector_orientation(argument_type.orientation, label),
        )
    matrix_type = _require_numeric_matrix_type(argument_type, label)
    rows = matrix_type.rows
    cols = matrix_type.cols
    return MatrixType(matrix_type.element_type, cols, rows)


def _flipped_vector_orientation(orientation: str | None, label: str) -> str:
    if orientation == "row":
        return "column"
    if orientation == "column":
        return "row"
    raise AetherTypeError(f"{label}(...) expects a vector with row or column orientation.")


def _matmul_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 2:
        raise AetherTypeError(f"{MATMUL_NAME}(...) expects exactly two arguments.")
    left_type, right_type = arg_types
    if left_type is None or right_type is None:
        return None
    left_matrix_type = _require_numeric_matrix_type(left_type, MATMUL_NAME)
    if isinstance(right_type, VectorType):
        if (
            left_matrix_type.cols is not None
            and right_type.length is not None
            and left_matrix_type.cols != right_type.length
        ):
            raise AetherTypeError(
                f"{MATMUL_NAME}(...) requires compatible shapes, got "
                f"{left_matrix_type.rows}x{left_matrix_type.cols} and {right_type.length}."
            )
        return VectorType(_promote_numeric_types(left_matrix_type.element_type, right_type.element_type), left_matrix_type.rows)
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
    if isinstance(right_type, VectorType):
        if right_type.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{SOLVE_NAME}(...) expects a vector with numeric elements.")
        if left_matrix_type.rows is not None and right_type.length is not None and left_matrix_type.rows != right_type.length:
            raise AetherTypeError(
                f"{SOLVE_NAME}(...) requires rows(A) == rows(b), got {left_matrix_type.rows} and {right_type.length}."
            )
        return VectorType(_promote_numeric_types(left_matrix_type.element_type, right_type.element_type), left_matrix_type.cols)
    right_matrix_type = _require_numeric_matrix_type(right_type, SOLVE_NAME)
    right_rows, right_cols, result_is_vector = _normalized_rhs_type_shape(left_matrix_type, right_matrix_type)
    if left_matrix_type.rows is not None and right_rows is not None and left_matrix_type.rows != right_rows:
        raise AetherTypeError(
            f"{SOLVE_NAME}(...) requires rows(A) == rows(b), got {left_matrix_type.rows} and {right_rows}."
        )
    return MatrixType(
        _promote_numeric_types(left_matrix_type.element_type, right_matrix_type.element_type),
        left_matrix_type.cols,
        right_cols,
        result_is_vector,
    )


def _eig_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{EIG_NAME}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    matrix_type = _require_numeric_matrix_type(argument_type, EIG_NAME)
    if (
        matrix_type.rows is not None
        and matrix_type.cols is not None
        and matrix_type.rows != matrix_type.cols
    ):
        raise AetherTypeError(f"{EIG_NAME}(...) expects a square matrix, got {matrix_type.rows}x{matrix_type.cols}.")
    result_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    return TupleType(
        (
            MatrixType(result_element_type, matrix_type.rows, matrix_type.cols),
            MatrixType(result_element_type, matrix_type.rows, matrix_type.cols),
        )
    )


def _svd_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{SVD_NAME}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    matrix_type = _require_numeric_matrix_type(argument_type, SVD_NAME)
    unitary_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    return TupleType(
        (
            MatrixType(unitary_element_type, matrix_type.rows, matrix_type.rows),
            MatrixType("double", matrix_type.rows, matrix_type.cols),
            MatrixType(unitary_element_type, matrix_type.cols, matrix_type.cols),
        )
    )


def _lu_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _lu_like_type(arg_types, LU_NAME, 3)


def _ldu_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _lu_like_type(arg_types, LDU_NAME, 4)


def _lu_like_type(arg_types: list[AetherType | None], label: str, result_count: int) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    matrix_type = _require_numeric_matrix_type(argument_type, label)
    if (
        matrix_type.rows is not None
        and matrix_type.cols is not None
        and matrix_type.rows != matrix_type.cols
    ):
        raise AetherTypeError(f"{label}(...) expects a square matrix, got {matrix_type.rows}x{matrix_type.cols}.")
    factor_type = MatrixType(
        "complex" if matrix_type.element_type == "complex" else "double",
        matrix_type.rows,
        matrix_type.cols,
    )
    if result_count == 3:
        return TupleType((MatrixType("double", matrix_type.rows, matrix_type.cols), factor_type, factor_type))
    return TupleType((MatrixType("double", matrix_type.rows, matrix_type.cols), factor_type, factor_type, factor_type))


def _matrix_factory_type(label: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 2:
            raise AetherTypeError(f"{label}(...) expects exactly two arguments.")
        row_type, col_type = arg_types
        if row_type is None or col_type is None:
            return None
        if row_type != "int" or col_type != "int":
            raise AetherTypeError(
                f"{label}(...) expects integer dimensions, got "
                f"'{type_to_string(row_type)}' and '{type_to_string(col_type)}'."
            )
        return MatrixType("double")

    return infer


def _null_space_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{NULL_SPACE_NAME}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    matrix_type = _require_numeric_matrix_type(argument_type, NULL_SPACE_NAME)
    result_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    return MatrixType(result_element_type, matrix_type.cols, None)


def _range_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{RANGE_NAME}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    matrix_type = _require_numeric_matrix_type(argument_type, RANGE_NAME)
    result_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    return MatrixType(result_element_type, matrix_type.rows, None)


def _rank_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{RANK_NAME}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    _require_numeric_matrix_type(argument_type, RANK_NAME)
    return "int"


def _matrix_factory_dimensions(args: list[AetherValue], label: str) -> tuple[int, int]:
    if len(args) != 2:
        raise AetherTypeError(f"{label}(...) expects exactly two arguments.")
    rows_arg, cols_arg = args
    if rows_arg.type_name != "int" or cols_arg.type_name != "int":
        raise AetherTypeError(
            f"{label}(...) expects integer dimensions, got "
            f"'{type_to_string(rows_arg.type_name)}' and '{type_to_string(cols_arg.type_name)}'."
        )
    rows = int(rows_arg.value)
    cols = int(cols_arg.value)
    if rows <= 0 or cols <= 0:
        raise AetherTypeError(f"{label}(...) expects positive dimensions, got {rows}x{cols}.")
    return rows, cols


def _filled_double_matrix(rows: int, cols: int, fill: float) -> AetherValue:
    row_type = ArrayType("double")
    matrix_rows = [
        AetherValue(row_type, [AetherValue("double", fill) for _col_index in range(cols)])
        for _row_index in range(rows)
    ]
    return AetherValue(MatrixType("double", rows, cols), matrix_rows)


def _matrix_vector_multiply(matrix: AetherValue, vector: AetherValue, label: str) -> AetherValue:
    matrix_type = _require_numeric_matrix_type(matrix.type_name, label)
    if not isinstance(vector.type_name, VectorType):
        raise AetherTypeError(f"{label}(...) expects a Vector right operand.")
    if vector.type_name.element_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects vectors with numeric elements.")
    rows, cols = _runtime_shape(matrix)
    if cols != len(vector.value):
        raise AetherTypeError(f"{label}(...) requires compatible shapes, got {rows}x{cols} and {len(vector.value)}.")
    result_element_type = _promote_numeric_types(matrix_type.element_type, vector.type_name.element_type)
    result: list[AetherValue] = []
    for row_index in range(rows):
        total = 0
        for col_index in range(cols):
            total += matrix.value[row_index].value[col_index].value * vector.value[col_index].value
        result.append(_coerced_numeric_result(total, result_element_type))
    return AetherValue(VectorType(result_element_type, len(result)), result)


def _vector_to_column_matrix(value: AetherValue) -> AetherValue:
    if not isinstance(value.type_name, VectorType):
        raise AetherTypeError(f"Expected vector type, got '{type_to_string(value.type_name)}'.")
    row_type = ArrayType(value.type_name.element_type)
    rows = [AetherValue(row_type, [element]) for element in value.value]
    return AetherValue(MatrixType(value.type_name.element_type, len(rows), 1), rows)


def _conjugate_scalar(value: AetherValue) -> AetherValue:
    conjugated = np.conjugate(value.value)
    if isinstance(conjugated, np.generic):
        conjugated = conjugated.item()
    return AetherValue(value.type_name, conjugated)


def _vector_elements(value: AetherValue, label: str) -> tuple[list[AetherValue], str]:
    if isinstance(value.type_name, VectorType):
        if value.type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects vectors with numeric elements.")
        return list(value.value), value.type_name.element_type
    if isinstance(value.type_name, TransposeVectorType):
        if value.type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects vectors with numeric elements.")
        return list(value.value.value), value.type_name.element_type
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


def _matrix_to_numeric_array(value: AetherValue) -> np.ndarray:
    matrix_type = _require_numeric_matrix_type(value.type_name, "matrix conversion")
    if matrix_type.element_type == "complex":
        return np.array([[complex(element.value) for element in row.value] for row in value.value], dtype=complex)
    return _matrix_to_float_array(value)


def _lu_factor_arrays(value: AetherValue, label: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    matrix_type = _require_numeric_matrix_type(value.type_name, label)
    rows, cols = _runtime_shape(value)
    if rows == 0 or cols == 0:
        raise AetherTypeError(f"{label}(...) does not accept an empty matrix.")
    if rows != cols:
        raise AetherTypeError(f"{label}(...) expects a square matrix, got {rows}x{cols}.")

    scipy_p, lower, upper = scipy_linalg.lu(_matrix_to_numeric_array(value))
    factor_element_type = "complex" if matrix_type.element_type == "complex" else "double"
    return scipy_p.T, lower, upper, factor_element_type


def _float_array_to_matrix_value(values: np.ndarray, *, vector: bool = False) -> AetherValue:
    return _numeric_array_to_matrix_value(values, element_type="double", vector=vector)


def _numeric_array_to_matrix_value(
    values: np.ndarray,
    *,
    element_type: str | None = None,
    vector: bool = False,
) -> AetherValue:
    cleaned = _clean_numeric_array(values)
    if element_type is None:
        element_type = _array_element_type(cleaned)
    if element_type == "complex":
        converted = np.asarray(cleaned, dtype=complex)
    else:
        converted = np.real(np.asarray(cleaned, dtype=complex)).astype(float)
    rows, cols = converted.shape
    row_type = ArrayType(element_type)
    result_rows = [
        AetherValue(
            row_type,
            [
                AetherValue(
                    element_type,
                    complex(converted[row_index, col_index])
                    if element_type == "complex"
                    else float(converted[row_index, col_index]),
                )
                for col_index in range(cols)
            ],
        )
        for row_index in range(rows)
    ]
    return AetherValue(MatrixType(element_type, rows, cols, vector), result_rows)


def _clean_float_array(values: np.ndarray) -> np.ndarray:
    return np.asarray(_clean_numeric_array(values), dtype=float)


def _clean_numeric_array(values: np.ndarray) -> np.ndarray:
    cleaned = np.asarray(values).copy()
    if np.iscomplexobj(cleaned):
        cleaned = cleaned.astype(complex)
        real = cleaned.real
        imag = cleaned.imag
        real[np.abs(real) < 1e-12] = 0.0
        imag[np.abs(imag) < 1e-12] = 0.0
        return real + 1j * imag
    cleaned = cleaned.astype(float)
    cleaned[np.abs(cleaned) < 1e-12] = 0.0
    return cleaned


def _array_element_type(values: np.ndarray) -> str:
    if values.size == 0:
        return "double"
    if np.iscomplexobj(values) and np.max(np.abs(np.imag(values))) > 1e-10:
        return "complex"
    return "double"


def _decomposition_result_element_type(*values: np.ndarray, prefer_complex: bool = False) -> str:
    if prefer_complex:
        return "complex"
    for value in values:
        if np.iscomplexobj(value) and np.max(np.abs(np.imag(value))) > 1e-10:
            return "complex"
    return "double"


def _float_array_to_vector_value(values: np.ndarray) -> AetherValue:
    return _numeric_array_to_vector_value(values, element_type="double")


def _numeric_array_to_vector_value(values: np.ndarray, *, element_type: str | None = None) -> AetherValue:
    cleaned = _clean_numeric_array(np.asarray(values))
    if element_type is None:
        element_type = _array_element_type(cleaned)
    if element_type == "complex":
        converted = np.asarray(cleaned, dtype=complex)
    else:
        converted = np.real(np.asarray(cleaned, dtype=complex)).astype(float)
    return AetherValue(
        VectorType(element_type, int(converted.shape[0])),
        [
            AetherValue(element_type, complex(value) if element_type == "complex" else float(value))
            for value in converted
        ],
    )


def _require_numeric_matrix_type(type_name: AetherType, label: str) -> MatrixType:
    if not isinstance(type_name, MatrixType):
        raise AetherTypeError(f"{label}(...) expects a mathematical matrix argument, got '{type_to_string(type_name)}'.")
    if type_name.element_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects a matrix with numeric elements.")
    return type_name


def _require_numeric_vector_type(type_name: AetherType, label: str) -> int | None:
    if isinstance(type_name, (VectorType, TransposeVectorType)):
        if type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects vectors with numeric elements.")
        return type_name.length
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
    if "complex" in {left_type, right_type}:
        return "complex"
    if "double" in {left_type, right_type}:
        return "double"
    if "float" in {left_type, right_type}:
        return "float"
    return "int"


def _coerced_numeric_result(value: object, result_type: str) -> AetherValue:
    if result_type == "int":
        return AetherValue("int", int(value))  # type: ignore[arg-type]
    if result_type == "complex":
        return AetherValue("complex", complex(value))  # type: ignore[arg-type]
    return AetherValue(result_type, float(value))  # type: ignore[arg-type]
