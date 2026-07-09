from __future__ import annotations

import shutil

import pytest

from aether import ast
from aether.backend.llvm import LLVMBuilder, LLVMRunner, print_llvm
from aether.errors import AetherTypeError
from aether.ir import (
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInterpreter,
    IRLowerer,
    IRMatrixColumns,
    IRMatrixAdd,
    IRMatrixGet,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixSet,
    IRModule,
    IRReturn,
    IRValue,
    IRVectorGet,
    IRVectorAdd,
    IRVectorLength,
    IRVectorNew,
    IRVectorSet,
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
    SSABinaryOp,
    SSAConst,
    SSAFunction,
    SSAMatrixColumns,
    SSAMatrixAdd,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAMatrixRows,
    SSAMatrixSet,
    SSAModule,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
    SSAVectorAdd,
    SSAVectorLength,
    SSAVectorNew,
    SSAVectorSet,
    SSAVerificationError,
    SSAVerifier,
    print_ssa,
)
from aether.ir.optimizer import OptimizerPipeline
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


def test_parser_builds_add_binary_expression_for_aggregates() -> None:
    expression = _parse_expression("left + right")

    assert isinstance(expression, ast.BinaryExpression)
    assert expression.operator == "+"
    assert isinstance(expression.left, ast.Identifier)
    assert isinstance(expression.right, ast.Identifier)


@pytest.mark.parametrize(
    ("source", "property_name"),
    [("v.length", "length"), ("A.rows", "rows"), ("A.columns", "columns")],
)
def test_parser_builds_dimension_property_access(source: str, property_name: str) -> None:
    expression = _parse_expression(source)

    assert isinstance(expression, ast.FieldAccess)
    assert isinstance(expression.target, ast.Identifier)
    assert expression.field_name == property_name


def test_parser_builds_assignment_with_vector_index_target() -> None:
    program = Parser(lex("int main() { Vector<int, Row> v = [1, 2]; v[0] = 9; return v[0]; }")).parse()
    statement = program.statements[0].body[1]

    assert isinstance(statement, ast.Assignment)
    assert isinstance(statement.name, ast.IndexExpression)
    assert isinstance(statement.name.array, ast.Identifier)
    assert statement.name.array.name == "v"


def test_parser_builds_assignment_with_matrix_index_target() -> None:
    program = Parser(lex("int main() { Matrix<int> A = [1, 2; 3, 4]; A[1, 0] = 9; return A[1, 0]; }")).parse()
    statement = program.statements[0].body[1]

    assert isinstance(statement, ast.Assignment)
    assert isinstance(statement.name, ast.MatrixIndexExpression)
    assert isinstance(statement.name.matrix, ast.Identifier)
    assert statement.name.matrix.name == "A"


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


def test_typechecker_accepts_vector_and_matrix_index_writes() -> None:
    _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    v[1] = 9;
    A[1, 0] = v[1];
    return A[1, 0];
}
"""
    )


def test_typechecker_accepts_dimension_properties_as_int() -> None:
    _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    return v.length + A.rows + A.columns;
}
"""
    )


def test_typechecker_accepts_vector_and_matrix_addition() -> None:
    _typed(
        """
int main() {
    Vector<int, Row> a = [1, 2, 3];
    Vector<int, Row> b = [4, 5, 6];
    Vector<int, Row> c = a + b;
    Matrix<int> A = [1, 2; 3, 4];
    Matrix<int> B = [5, 6; 7, 8];
    Matrix<int> C = A + B;
    return c[0] + C[0, 0];
}
"""
    )


def test_lowering_preserves_column_vector_addition_orientation() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Column> a = [1; 2; 3];
    Vector<int, Column> b = [4; 5; 6];
    Vector<int, Column> c = a + b;
    return c[2];
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()

    vector_add = next(
        instruction
        for instruction in module.functions[0].blocks[0].instructions
        if isinstance(instruction, IRVectorAdd)
    )
    assert vector_add.orientation == "column"


def test_typechecker_rejects_vector_addition_orientation_mismatch() -> None:
    with pytest.raises(AetherTypeError, match="same orientation"):
        _typed(
            """
int main() {
    Vector<int, Row> a = [1, 2, 3];
    Vector<int, Column> b = [4; 5; 6];
    Vector<int> c = a + b;
    return c[0];
}
"""
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            """
int main() {
    Vector<int, Row> v = [1, 2, 3];
    v[1.5] = 9;
    return 0;
}
""",
            "Index must be int",
        ),
        (
            """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    A[0, 1.5] = 9;
    return 0;
}
""",
            "Matrix indices must be int",
        ),
        (
            """
int main() {
    Vector<int, Row> v = [1, 2, 3];
    v[0] = 1.5;
    return 0;
}
""",
            "Cannot implicitly convert",
        ),
    ],
)
def test_typechecker_reports_index_write_errors(source: str, message: str) -> None:
    with pytest.raises(AetherTypeError, match=message):
        _typed(source)


def test_typechecker_rejects_index_write_through_const_reference() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'v'"):
        _typed(
            """
int main() {
    const Vector<int, Row> v = [1, 2, 3];
    v[0] = 9;
    return 0;
}
"""
        )

    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'A'"):
        _typed(
            """
int main() {
    const Matrix<int> A = [1, 2; 3, 4];
    A[0, 0] = 9;
    return 0;
}
"""
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


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            """
int main() {
    Vector<int, Row> v = [1, 2, 3];
    return v.rows;
}
""",
            "has no native property 'rows'",
        ),
        (
            """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    return A.length;
}
""",
            "has no native property 'length'",
        ),
        (
            """
int main() {
    Vector<int, Row> v = [1, 2, 3];
    return v.length();
}
""",
            "length is a property, not a method",
        ),
    ],
)
def test_typechecker_reports_dimension_property_errors(source: str, message: str) -> None:
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


def test_lowering_and_ir_interpreter_execute_dimension_properties() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4; 5, 6];
    return v.length + A.rows + A.columns;
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()

    instructions = module.functions[0].blocks[0].instructions
    matrix_rows = next(instruction for instruction in instructions if isinstance(instruction, IRMatrixRows))
    matrix_columns = next(instruction for instruction in instructions if isinstance(instruction, IRMatrixColumns))
    assert any(isinstance(instruction, IRVectorLength) for instruction in instructions)
    assert matrix_rows.rows == 3
    assert matrix_columns.columns == 2
    assert "vector_length" in print_ir(module)
    assert "matrix_rows" in print_ir(module)
    assert "matrix_columns" in print_ir(module)
    assert IRInterpreter(module).call("main") == 8


def test_lowering_and_ir_interpreter_execute_vector_and_matrix_index_writes() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    v[1] = 9;
    A[1, 0] = v[1];
    return A[1, 0];
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()

    instructions = module.functions[0].blocks[0].instructions
    matrix_set = next(instruction for instruction in instructions if isinstance(instruction, IRMatrixSet))
    assert any(isinstance(instruction, IRVectorSet) for instruction in instructions)
    assert matrix_set.cols == 2
    assert "vector_set" in print_ir(module)
    assert "matrix_set" in print_ir(module)
    assert IRInterpreter(module).call("main") == 9


def test_lowering_and_ir_interpreter_execute_vector_addition() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> a = [1, 2, 3];
    Vector<int, Row> b = [4, 5, 6];
    Vector<int, Row> c = a + b;
    return c[0] + c[1] + c[2];
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()

    vector_add = next(
        instruction
        for instruction in module.functions[0].blocks[0].instructions
        if isinstance(instruction, IRVectorAdd)
    )
    assert vector_add.length == 3
    assert vector_add.orientation == "row"
    assert "vector_add row" in print_ir(module)
    assert IRInterpreter(module).call("main") == 21


def test_lowering_and_ir_interpreter_execute_matrix_addition() -> None:
    typed_program = _typed(
        """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    Matrix<int> B = [5, 6; 7, 8];
    Matrix<int> C = A + B;
    return C[0, 0] + C[0, 1] + C[1, 0] + C[1, 1];
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()

    matrix_add = next(
        instruction
        for instruction in module.functions[0].blocks[0].instructions
        if isinstance(instruction, IRMatrixAdd)
    )
    assert matrix_add.rows == 2
    assert matrix_add.cols == 2
    assert "matrix_add" in print_ir(module)
    assert IRInterpreter(module).call("main") == 36


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


def test_ssa_preserves_dimension_properties() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4; 5, 6];
    return v.length + A.rows + A.columns;
}
"""
    )

    ssa = lower_to_verified_ssa(typed_program)
    instructions = ssa.functions[0].blocks[0].instructions

    assert any(isinstance(instruction, SSAVectorLength) for instruction in instructions)
    assert any(isinstance(instruction, SSAMatrixRows) for instruction in instructions)
    assert any(isinstance(instruction, SSAMatrixColumns) for instruction in instructions)
    assert "vector_length" in print_ssa(ssa)
    assert "matrix_rows" in print_ssa(ssa)
    assert "matrix_columns" in print_ssa(ssa)


def test_ssa_preserves_vector_and_matrix_index_writes() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    v[1] = 9;
    A[1, 0] = v[1];
    return A[1, 0];
}
"""
    )

    ssa = lower_to_verified_ssa(typed_program)
    instructions = ssa.functions[0].blocks[0].instructions

    assert any(isinstance(instruction, SSAVectorSet) for instruction in instructions)
    assert any(isinstance(instruction, SSAMatrixSet) for instruction in instructions)
    assert "vector_set" in print_ssa(ssa)
    assert "matrix_set" in print_ssa(ssa)


def test_ssa_preserves_vector_and_matrix_addition() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> a = [1, 2, 3];
    Vector<int, Row> b = [4, 5, 6];
    Vector<int, Row> c = a + b;
    Matrix<int> A = [1, 2; 3, 4];
    Matrix<int> B = [5, 6; 7, 8];
    Matrix<int> C = A + B;
    return c[1] + C[1, 0];
}
"""
    )

    ssa = lower_to_verified_ssa(typed_program)
    instructions = ssa.functions[0].blocks[0].instructions

    assert any(isinstance(instruction, SSAVectorAdd) for instruction in instructions)
    assert any(isinstance(instruction, SSAMatrixAdd) for instruction in instructions)
    assert "vector_add row" in print_ssa(ssa)
    assert "matrix_add" in print_ssa(ssa)


def test_emit_llvm_includes_vector_and_matrix_addition_storage() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> a = [1, 2, 3];
    Vector<int, Row> b = [4, 5, 6];
    Vector<int, Row> c = a + b;
    Matrix<int> A = [1, 2; 3, 4];
    Matrix<int> B = [5, 6; 7, 8];
    Matrix<int> C = A + B;
    return c[2] + C[1, 1];
}
"""
    )

    llvm = LLVMBuilder().emit_llvm(typed_program)

    assert "@aether_array_new(i64 4, i64 3)" in llvm
    assert "@aether_array_new(i64 4, i64 4)" in llvm
    assert " = add i32 " in llvm
    assert "add.left.data" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is not available")
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
int main() {
    Vector<int, Row> a = [1, 2, 3];
    Vector<int, Row> b = [4, 5, 6];
    Vector<int, Row> c = a + b;
    return c[0] + c[1] + c[2];
}
""",
            21,
        ),
        (
            """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    Matrix<int> B = [5, 6; 7, 8];
    Matrix<int> C = A + B;
    return C[0, 0] + C[0, 1] + C[1, 0] + C[1, 1];
}
""",
            36,
        ),
    ],
)
def test_llvm_runner_builds_and_executes_vector_and_matrix_addition(source: str, expected: int) -> None:
    assert LLVMRunner().run(_typed(source)) == expected


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


def test_ir_verifier_rejects_bad_vector_set_value_type() -> None:
    int_type = IntType()
    vector = IRValue("v", VectorType(int_type, "row"))
    index = IRValue("i", int_type)
    value = IRValue("bad", VectorType(int_type, "row"))
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
                            IRVectorNew(vector, ()),
                            IRConst(index, 0),
                            IRVectorNew(value, (), "row"),
                            IRVectorSet(vector, index, value),
                            IRReturn(index),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(IRVerificationError, match="Vector set value type mismatch"):
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


def test_ssa_verifier_rejects_bad_matrix_set_column_type() -> None:
    int_type = IntType()
    matrix = SSAValue("m", MatrixType(int_type))
    row = SSAValue("row", int_type)
    column = SSAValue("column", MatrixType(int_type))
    value = SSAValue("value", int_type)
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
                            SSAMatrixNew(matrix, (row,), 1, 1),
                            SSAMatrixNew(column, (row,), 1, 1),
                            SSAConst(value, 9),
                            SSAMatrixSet(matrix, row, column, value, 1),
                            SSAReturn(row),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(SSAVerificationError, match="Matrix set column index must be int"):
        SSAVerifier(module).verify()


def test_ir_verifier_rejects_bad_vector_length_source() -> None:
    int_type = IntType()
    not_vector = IRValue("x", int_type)
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
                            IRConst(not_vector, 0),
                            IRVectorLength(result, not_vector),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(IRVerificationError, match="Vector length expects vector value"):
        IRVerifier(module).verify()


def test_ssa_verifier_rejects_bad_matrix_rows_result_type() -> None:
    int_type = IntType()
    matrix = SSAValue("m", MatrixType(int_type))
    element = SSAValue("x", int_type)
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
                            SSAConst(element, 1),
                            SSAMatrixNew(matrix, (element,), 1, 1),
                            SSAMatrixRows(result, matrix, 1),
                            SSAReturn(element),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(SSAVerificationError, match="Matrix rows result must be int"):
        SSAVerifier(module).verify()


def test_ir_optimizer_preserves_vector_and_matrix_sets() -> None:
    typed_program = _typed(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    v[1] = 9;
    A[1, 0] = 8;
    return 0;
}
"""
    )
    module = IRVerifier(IRLowerer().lower(typed_program.program)).verify()
    optimized = OptimizerPipeline(iterative=True).run(module)
    instructions = [
        instruction
        for block in optimized.functions[0].blocks
        for instruction in block.instructions
    ]

    assert any(isinstance(instruction, IRVectorSet) for instruction in instructions)
    assert any(isinstance(instruction, IRMatrixSet) for instruction in instructions)


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


def test_llvm_emits_dimension_properties() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    vector = SSAValue("2", VectorType(int_type, "row"))
    vector_length = SSAValue("3", int_type)
    matrix = SSAValue("4", MatrixType(int_type))
    matrix_rows = SSAValue("5", int_type)
    matrix_columns = SSAValue("6", int_type)
    total = SSAValue("7", int_type)
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
                            SSAVectorLength(vector_length, vector),
                            SSAMatrixNew(matrix, (first, second, second, first), 2, 2),
                            SSAMatrixRows(matrix_rows, matrix, 2),
                            SSAMatrixColumns(matrix_columns, matrix, 2),
                            SSABinaryOp(total, "add", vector_length, matrix_rows),
                            SSAReturn(total),
                        ],
                    )
                ],
            )
        ]
    )

    llvm = print_llvm(SSAVerifier(module).verify())

    assert "vector.len64" in llvm
    assert "trunc i64" in llvm
    assert "add i32 0, 2" in llvm


def test_llvm_emits_vector_and_matrix_set_stores() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    vector = SSAValue("2", VectorType(int_type, "row"))
    index = SSAValue("3", int_type)
    value = SSAValue("4", int_type)
    matrix = SSAValue("5", MatrixType(int_type))
    row = SSAValue("6", int_type)
    column = SSAValue("7", int_type)
    return_value = SSAValue("8", int_type)
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
                            SSAConst(value, 99),
                            SSAVectorSet(vector, index, value),
                            SSAMatrixNew(matrix, (first, second, second, first), 2, 2),
                            SSAConst(row, 1),
                            SSAConst(column, 0),
                            SSAMatrixSet(matrix, row, column, value, 2),
                            SSAConst(return_value, 0),
                            SSAReturn(return_value),
                        ],
                    )
                ],
            )
        ]
    )

    llvm = print_llvm(SSAVerifier(module).verify())

    assert "store i32 99" in llvm
    assert "mul i64 %matrix.row64" in llvm
    assert ", 2" in llvm


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
        (
            """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    v[1] = 9;
    return v[1];
}
""",
            9,
        ),
        (
            """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    A[1, 0] = 9;
    return A[1, 0];
}
""",
            9,
        ),
        (
            """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4; 5, 6];
    return v.length + A.rows + A.columns;
}
""",
            8,
        ),
    ],
)
def test_llvm_runner_executes_index_reads(source: str, expected: int) -> None:
    assert LLVMRunner().run(_typed(source)) == expected
