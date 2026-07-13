from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner
from aether.errors import AetherRuntimeError
from aether.ir import IRExecutionError, IRInterpreter, IRMatrixGet, IRVectorGet
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSAMatrixGet, SSAVectorGet
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


VECTOR_PANIC = "Aether panic: Vector index out of bounds"
MATRIX_PANIC = "Aether panic: Matrix index out of bounds"


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _compiled(body: str) -> str:
    return f"int main() {{\n{body}\nreturn 0;\n}}"


def _assert_success_parity(body: str, expected_output: str) -> None:
    assert run_aether(body).output == expected_output

    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(_compiled(body))))
    assert interpreter.call("main") == 0
    assert interpreter.output == expected_output

    if shutil.which("clang") is None:
        return
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(_compiled(body)), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == expected_output
    assert stderr.getvalue() == ""


def _assert_panic_parity(body: str, message: str) -> None:
    with pytest.raises(AetherRuntimeError, match=message):
        run_aether(body)

    with pytest.raises(IRExecutionError, match=message):
        IRInterpreter(IRBackend().lower_verified(_typed(_compiled(body)))).call("main")

    if shutil.which("clang") is None:
        return
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(_compiled(body)), stdout=stdout, stderr=stderr) == 1
    assert stdout.getvalue() == message + "\n"
    assert stderr.getvalue() == ""


def test_valid_reads_writes_minimum_maximum_and_matrix_corners_match() -> None:
    _assert_success_parity(
        """
Vector<int, Row> vector = [10, 20, 30];
Matrix<int> matrix = [1, 2, 3; 4, 5, 6];
println(vector[1]);
println(vector[3]);
vector[1] = 11;
vector[3] = 33;
println(vector[1]);
println(vector[3]);
println(matrix[1, 1]);
println(matrix[1, 3]);
println(matrix[2, 1]);
println(matrix[2, 3]);
matrix[1, 1] = 10;
matrix[2, 3] = 60;
println(matrix[1, 1]);
println(matrix[2, 3]);
""",
        "10\n30\n11\n33\n1\n3\n4\n6\n10\n60\n",
    )


@pytest.mark.parametrize(
    "body",
    [
        "Vector<int, Row> v = [1, 2]; int ignored = v[0];",
        "Vector<int, Row> v = [1, 2]; int ignored = v[3];",
        "Vector<int, Row> v = [1, 2]; v[0] = 9;",
        "Vector<int, Row> v = [1, 2]; v[3] = 9;",
    ],
)
def test_invalid_vector_reads_and_writes_match(body: str) -> None:
    _assert_panic_parity(body, VECTOR_PANIC)


@pytest.mark.parametrize(
    "body",
    [
        "Matrix<int> A = [1, 2; 3, 4]; int ignored = A[0, 2];",
        "Matrix<int> A = [1, 2; 3, 4]; int ignored = A[1, 0];",
        "Matrix<int> A = [1, 2; 3, 4]; int ignored = A[1, 3];",
        "Matrix<int> A = [1, 2; 3, 4]; int ignored = A[3, 1];",
        "Matrix<int> A = [1, 2; 3, 4]; A[0, 2] = 9;",
        "Matrix<int> A = [1, 2; 3, 4]; A[1, 3] = 9;",
    ],
)
def test_invalid_matrix_coordinates_are_checked_before_flattening(body: str) -> None:
    _assert_panic_parity(body, MATRIX_PANIC)


def test_vector_matrix_equality_and_printing_match() -> None:
    _assert_success_parity(
        """
Vector<int, Row> row = [1, 2, 3];
Vector<int, Row> same_row = [1, 2, 3];
Vector<int, Column> column = [4; 5];
Matrix<int> matrix = [1, 2; 3, 4];
Matrix<int> same_matrix = [1, 2; 3, 4];
println(row);
println(column);
println(matrix);
println(row == same_row);
same_row[3] = 9;
println(row != same_row);
println(matrix == same_matrix);
same_matrix[2, 2] = 9;
println(matrix != same_matrix);
""",
        "[1 2 3]\n[4; 5]\n[1 2; 3 4]\ntrue\ntrue\ntrue\ntrue\n",
    )


@pytest.mark.parametrize(
    ("source", "ir_type", "ssa_type", "message"),
    [
        (
            "int main() { Vector<int, Row> v = [1, 2]; int ignored = v[0]; return 0; }",
            IRVectorGet,
            SSAVectorGet,
            VECTOR_PANIC,
        ),
        (
            "int main() { Matrix<int> A = [1, 2; 3, 4]; int ignored = A[0, 2]; return 0; }",
            IRMatrixGet,
            SSAMatrixGet,
            MATRIX_PANIC,
        ),
    ],
)
def test_optimizers_preserve_invalid_gets_that_may_panic(
    source: str,
    ir_type: type,
    ssa_type: type,
    message: str,
) -> None:
    ir = OptimizerPipeline(iterative=True).run(IRBackend().lower_verified(_typed(source)))
    assert any(
        isinstance(instruction, ir_type)
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
    )
    with pytest.raises(IRExecutionError, match=message):
        IRInterpreter(ir).call("main")

    ssa = SSAOptimizerPipeline().run(lower_to_verified_ssa(_typed(source)))
    assert any(
        isinstance(instruction, ssa_type)
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
    )
