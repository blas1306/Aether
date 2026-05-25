from __future__ import annotations

import pytest

from aether import analyze_source, run_aether
from aether.ast import Assignment, UnaryExpression
from aether.errors import AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.types import MatrixType, TransposeVectorType


def _matrix_values(result, name: str) -> list[list[float]]:
    value = result.env[name]
    assert isinstance(value.type_name, MatrixType)
    return [[element.value for element in row.value] for row in value.value]


def test_conjtranspose_builtin_returns_conjugate_transpose_for_real_matrix() -> None:
    result = run_aether(
        """
A = [1 2 3; 4 5 6];
B = Math.LinearAlgebra.conjtranspose(A);
println(B);
"""
    )

    assert result.env["B"].type_name == MatrixType("int", 3, 2)
    assert _matrix_values(result, "B") == [[1, 4], [2, 5], [3, 6]]
    assert result.output == "[1 4; 2 5; 3 6]\n"


def test_conjtranspose_import_exposes_unqualified_function() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2; 3 4];
B = conjtranspose(A);
"""
    )

    assert _matrix_values(result, "B") == [[1, 3], [2, 4]]


def test_apostrophe_operator_parses_as_postfix_conjtranspose() -> None:
    program = Parser(lex("B = A';")).parse()

    statement = program.statements[0]
    assert isinstance(statement, Assignment)
    assert isinstance(statement.expression, UnaryExpression)
    assert statement.expression.operator == "'"


def test_apostrophe_operator_calls_conjtranspose() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2 3; 4 5 6];
B = A';
C = B';
G = A' * A;
println(B);
println(C);
println(G);
"""
    )

    assert result.env["B"].type_name == MatrixType("int", 3, 2)
    assert _matrix_values(result, "B") == [[1, 4], [2, 5], [3, 6]]
    assert _matrix_values(result, "C") == [[1, 2, 3], [4, 5, 6]]
    assert _matrix_values(result, "G") == [[17, 22, 27], [22, 29, 36], [27, 36, 45]]
    assert result.output == "[1 4; 2 5; 3 6]\n[1 2 3; 4 5 6]\n[17 22 27; 22 29 36; 27 36 45]\n"


def test_apostrophe_operator_supports_vectors() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
v = [1, 2, 3];
t = v';
println(t);
"""
    )

    assert result.env["t"].type_name == TransposeVectorType("int", 3)
    assert result.output == "[1 2 3]\n"


def test_apostrophe_operator_requires_linear_algebra_import() -> None:
    with pytest.raises(AetherTypeError, match="requires import Math\\.LinearAlgebra"):
        run_aether("A = [1 2; 3 4]; B = A';")


def test_apostrophe_missing_import_diagnostic_points_to_operator() -> None:
    diagnostics = analyze_source("A = [1 2; 3 4];\nB = A';\n")

    assert len(diagnostics) == 1
    assert "requires import Math.LinearAlgebra" in diagnostics[0].message
    assert diagnostics[0].line == 2
    assert diagnostics[0].column == 6
