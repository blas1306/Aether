from __future__ import annotations

import shutil

import pytest

from aether import ast
from aether.backend.llvm import LLVMRunner, print_llvm
from aether.errors import AetherTypeError
from aether.ir import (
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInterpreter,
    IRLowerer,
    IRMatrixGet,
    IRMatrixNew,
    IRModule,
    IRReturn,
    IRValue,
    IRVectorGet,
    IRVectorNew,
    IRVerificationError,
    IRVerifier,
    IntType,
    MatrixType,
    VectorType,
    print_ir,
)
from aether.lexer import lex
from aether.parser import Parser
from aether.pipeline import lower_to_verified_ssa, prepare_typed_program
from aether.ssa import (
    SSABasicBlock,
    SSAConst,
    SSAFunction,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAModule,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
    SSAVectorNew,
    SSAVerificationError,
    SSAVerifier,
    print_ssa,
)
from aether.typechecker import TypeChecker


def _parse_expression(source: str) -> ast.Expression:
    return Parser(lex(source)).parse_expression()


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def test_parser_builds_vector_index_expression() -> None:
    expression = _parse_expression("v[i + 1]")

    assert isinstance(expression, ast.IndexExpression)
    assert isinstance(expression.array, ast.Identifier)
    assert expression.array.name == "v"
    assert isinstance(expression.index, ast.BinaryExpression)


def test_parser_builds_matrix_index_expression() -> None:
    expression = _parse_expression("A[i, j + 1]")

    assert isinstance(expression, ast.MatrixIndexExpression)
    assert isinstance(expression.matrix, ast.Identifier)
    assert expression.matrix.name == "A"
    assert isinstance(expression.row, ast.Identifier)
    assert isinstance(expression.column, ast.BinaryExpression)


def test_typechecker_accepts_vector_and_matrix_scalar_index_reads() -> None:
    TypeChecker().check(
        Parser(
            lex(
                """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    return v[1] + A[1, 0];
}
"""
            )
        ).parse()
    )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            """
int main() {
    Vector<int, Row> v = [1, 2, 3];
    return v[1.5];
}
""",
            "Index must be int",
        ),
        (
            """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    return A[0.5, 1];
}
""",
            "Matrix indices must be int",
        ),
        (
            """
int main() {
    Vector<int, Row> v = [1, 2, 3];
    return v[0, 1];
}
""",
            "Two-dimensional indexing expects a matrix",
        ),
        (
            """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    return A[0];
}
""",
            "Matrix values require two-dimensional indexing",
        ),
    ],
)
def test_typechecker_reports_index_errors(source: str, message: str) -> None:
    with pytest.raises(AetherTypeError, match=message):
        _typed(source)


def test_lowering_and_ir_interpreter_execute_vector_index_read() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    return v[2];
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()

    instructions = module.functions[0].blocks[0].instructions
    assert any(isinstance(instruction, IRVectorGet) for instruction in instructions)
    assert "vector_get" in print_ir(module)
    assert IRInterpreter(module).call("main") == 6


def test_lowering_and_ir_interpreter_execute_matrix_index_read() -> None:
    typed_program = _typed(
        """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    return A[1, 0];
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()

    matrix_get = next(
        instruction
        for instruction in module.functions[0].blocks[0].instructions
        if isinstance(instruction, IRMatrixGet)
    )
    assert matrix_get.cols == 2
    assert "matrix_get" in print_ir(module)
    assert IRInterpreter(module).call("main") == 3


def test_ssa_preserves_vector_and_matrix_index_reads() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    return v[1] + A[0, 1];
}
"""
    )

    ssa = lower_to_verified_ssa(typed_program)
    instructions = ssa.functions[0].blocks[0].instructions

    assert any(isinstance(instruction, SSAVectorGet) for instruction in instructions)
    assert any(isinstance(instruction, SSAMatrixGet) for instruction in instructions)
    assert "vector_get" in print_ssa(ssa)
    assert "matrix_get" in print_ssa(ssa)


def test_ir_verifier_rejects_bad_vector_get_index_type() -> None:
    int_type = IntType()
    vector = IRValue("v", VectorType(int_type, "row"))
    bad_index = IRValue("i", VectorType(int_type, "row"))
    result = IRValue("r", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRVectorNew(vector, (), "row"),
                            IRVectorNew(bad_index, (), "row"),
                            IRVectorGet(result, vector, bad_index),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(IRVerificationError, match="Vector get index must be int"):
        IRVerifier(module).verify()


def test_ssa_verifier_rejects_bad_matrix_get_result_type() -> None:
    int_type = IntType()
    matrix = SSAValue("m", MatrixType(int_type))
    row = SSAValue("row", int_type)
    column = SSAValue("column", int_type)
    result = SSAValue("r", MatrixType(int_type))
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(row, 0),
                            SSAConst(column, 0),
                            SSAMatrixNew(matrix, (row,), 1, 1),
                            SSAMatrixGet(result, matrix, row, column, 1),
                            SSAReturn(row),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(SSAVerificationError, match="Matrix get result type mismatch"):
        SSAVerifier(module).verify()


def test_llvm_emits_vector_and_matrix_get_loads() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    vector = SSAValue("2", VectorType(int_type, "row"))
    index = SSAValue("3", int_type)
    vector_value = SSAValue("4", int_type)
    matrix = SSAValue("5", MatrixType(int_type))
    row = SSAValue("6", int_type)
    column = SSAValue("7", int_type)
    matrix_value = SSAValue("8", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(first, 10),
                            SSAConst(second, 20),
                            SSAVectorNew(vector, (first, second), "row"),
                            SSAConst(index, 1),
                            SSAVectorGet(vector_value, vector, index),
                            SSAMatrixNew(matrix, (first, second, second, first), 2, 2),
                            SSAConst(row, 1),
                            SSAConst(column, 0),
                            SSAMatrixGet(matrix_value, matrix, row, column, 2),
                            SSAReturn(matrix_value),
                        ],
                    )
                ],
            )
        ]
    )

    llvm = print_llvm(module)

    assert "load i32" in llvm
    assert "mul i64 %matrix.row64" in llvm
    assert ", 2" in llvm
    assert "add i64" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is not available")
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    return v[1];
}
""",
            5,
        ),
        (
            """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    return A[1, 1];
}
""",
            4,
        ),
    ],
)
def test_llvm_runner_executes_index_reads(source: str, expected: int) -> None:
    assert LLVMRunner().run(_typed(source)) == expected
