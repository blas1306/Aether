from __future__ import annotations

import pytest

from aether import analyze_source, run_aether
from aether.ast import Assignment, BinaryExpression
from aether.errors import AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.types import MatrixType, VectorType


LINEAR_ALGEBRA_IMPORT = "import Math.LinearAlgebra\n"


def _matrix_values(result, name: str) -> list[list[float]]:
    value = result.env[name]
    assert isinstance(value.type_name, MatrixType)
    return [[element.value for element in row.value] for row in value.value]


def _assert_matrix_values(result, name: str, expected: list[list[float]]) -> None:
    actual = _matrix_values(result, name)
    assert len(actual) == len(expected)
    for actual_row, expected_row in zip(actual, expected):
        assert actual_row == pytest.approx(expected_row)


def _vector_values(result, name: str) -> list[float]:
    value = result.env[name]
    assert isinstance(value.type_name, VectorType)
    return [element.value for element in value.value]


def _assert_vector_values(result, name: str, expected: list[float]) -> None:
    assert _vector_values(result, name) == pytest.approx(expected)


def test_leftdivide_parses_as_binary_operator() -> None:
    program = Parser(lex("x = A \\ b;")).parse()

    statement = program.statements[0]
    assert isinstance(statement, Assignment)
    expression = statement.expression
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "\\"


def test_leftdivide_solves_square_system() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
Matrix<double> A = [2 1; 1 3];
Vector<double> b = [1; 2];
x = A \\ b;
"""
    )

    _assert_vector_values(result, "x", [0.2, 0.6])
    assert result.env["x"].type_name == VectorType("double", 2)


def test_linear_algebra_solve_builtin_matches_leftdivide() -> None:
    result = run_aether(
        """
Matrix<double> A = [2 1; 1 3];
Vector<double> b = [1; 2];
x = Math.LinearAlgebra.solve(A, b);
"""
    )

    _assert_vector_values(result, "x", [0.2, 0.6])


def test_leftdivide_returns_least_squares_solution_for_overdetermined_system() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
Matrix<double> A = [1 1; 1 1; 1 1];
Vector<double> b = [1; 2; 2];
x = A \\ b;
"""
    )

    _assert_vector_values(result, "x", [5 / 6, 5 / 6])


def test_leftdivide_returns_minimum_norm_solution_for_rank_deficient_system() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
Matrix<double> A = [1 1; 2 2];
Vector<double> b = [1; 2];
x = A \\ b;
"""
    )

    _assert_vector_values(result, "x", [0.5, 0.5])


def test_leftdivide_supports_multiple_right_hand_sides() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
Matrix<double> A = [2 0; 0 4];
Matrix<double> B = [2 4; 8 12];
X = A \\ B;
"""
    )

    _assert_matrix_values(result, "X", [[1.0, 2.0], [2.0, 3.0]])
    assert result.env["X"].type_name == MatrixType("double", 2, 2, False)


def test_leftdivide_solves_complex_square_system() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
Matrix<complex> A = [1 im; 2 3];
Vector<complex> b = [1 + im; 4];
Vector<complex, Column> x = A \\ b;
Vector<complex, Column> xc = [x[1]; x[2]];
r = Math.LinearAlgebra.matmul(A, xc);
"""
    )

    assert result.env["x"].type_name == VectorType("complex", 2)
    assert _vector_values(result, "r") == pytest.approx([1 + 1j, 4])


def test_solve_returns_complex_for_real_matrix_with_complex_rhs() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [2 0; 0 4];
b = [2 + 2im; 8];
x = solve(A, b);
"""
    )

    assert result.env["x"].type_name == VectorType("complex", 2)
    assert _vector_values(result, "x") == pytest.approx([1 + 1j, 2])


def test_leftdivide_returns_complex_least_squares_solution() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
Matrix<complex> A = [1 im; 1 im; 1 im];
Vector<complex, Column> b = [1; 2 + im; 2];
Vector<complex, Column> x = A \\ b;
Vector<complex, Column> xc = [x[1]; x[2]];
Ax = Math.LinearAlgebra.matmul(A, xc);
Vector<complex, Column> residual = [Ax[1] - b[1]; Ax[2] - b[2]; Ax[3] - b[3]];
normal_residual = Math.LinearAlgebra.matmul(A', residual);
"""
    )

    assert result.env["x"].type_name == VectorType("complex", 2)
    assert _vector_values(result, "normal_residual") == pytest.approx([0, 0])


def test_leftdivide_rejects_incompatible_dimensions() -> None:
    with pytest.raises(AetherTypeError, match=r"rows\(A\) == rows\(b\)"):
        run_aether(
            """
import Math.LinearAlgebra
Matrix<double> A = [1 2; 3 4];
Vector<double> b = [1; 2; 3];
x = A \\ b;
"""
        )


def test_leftdivide_requires_linear_algebra_import() -> None:
    with pytest.raises(AetherTypeError, match=r"requires import Math\.LinearAlgebra"):
        run_aether(
            """
Matrix<double> A = [2 1; 1 3];
Vector<double> b = [1; 2];
x = A \\ b;
"""
        )


def test_leftdivide_missing_import_diagnostic_points_to_operator() -> None:
    source = "Matrix<double> A = [2 1; 1 3];\nVector<double> b = [1; 2];\nx = A \\ b;\n"
    diagnostics = analyze_source(source)

    assert len(diagnostics) == 1
    assert "requires import Math.LinearAlgebra" in diagnostics[0].message
    assert diagnostics[0].line == 3
    assert diagnostics[0].column == 7


def test_leftdivide_valid_program_has_no_lsp_diagnostics() -> None:
    diagnostics = analyze_source(
        """
import Math.LinearAlgebra
Matrix<double> A = [2 1; 1 3];
Vector<double> b = [1; 2];
x = A \\ b;
"""
    )

    assert diagnostics == []


def test_leftdivide_reports_static_dimension_mismatch_when_shapes_are_known() -> None:
    diagnostics = analyze_source(LINEAR_ALGEBRA_IMPORT + "x = [1 2; 3 4] \\ [1; 2; 3];")

    assert len(diagnostics) == 1
    assert "rows(A) == rows(b)" in diagnostics[0].message
