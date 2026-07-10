from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import print_llvm
from aether.cli import EXIT_SUCCESS, main
from aether.errors import AetherTypeError
from aether.ir import IRInterpreter, IRLowerer, IRMatrixVectorMul, IRVerifier, IntType, VectorType
from aether.pipeline import parse_source
from aether.runner import run_aether
from aether.ssa import SSABuilder, SSAMatrixVectorMul, SSAVerifier, print_ssa
from aether.typechecker import TypeChecker
from aether.types import VectorType as RuntimeVectorType


def _typecheck(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return program


def _lower(source: str):
    return IRLowerer().lower(_typecheck(source))


def _emit_llvm(path: Path) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = main(["--emit-llvm", str(path)], stdout=stdout, stderr=stderr)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_matrix_column_product_typechecks_and_runs() -> None:
    _typecheck(
        """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    Vector<int, Column> c = [5; 6];
    Vector<int, Column> r = A * c;
    return r[0] + r[1];
}
"""
    )

    result = run_aether(
        """
Matrix<int> A = [1, 2; 3, 4];
Vector<int, Column> c = [5; 6];
Vector<int, Column> r = A * c;
"""
    )

    assert result.env["r"].type_name == RuntimeVectorType("int", 2, "column")
    assert [element.value for element in result.env["r"].value] == [17, 39]


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "Matrix<int> A = [1, 2; 3, 4]; Vector<int, Row> r = [5, 6]; y = A * r;",
            "Matrix \\* Vector<Row>",
        ),
        (
            "Vector<int, Column> c = [1; 2]; Matrix<int> A = [3, 4; 5, 6]; y = c * A;",
            "Column \\* Matrix",
        ),
        (
            "Vector<int, Row> r = [1, 2]; Matrix<int> A = [3, 4; 5, 6]; y = r * A;",
            "Row \\* Matrix",
        ),
        (
            "Matrix<int> A = [1, 2, 3; 4, 5, 6]; Vector<int, Column> c = [7; 8]; y = A * c;",
            "compatible shapes",
        ),
    ],
)
def test_matrix_column_product_rejects_invalid_operator_cases(source: str, message: str) -> None:
    with pytest.raises(AetherTypeError, match=message):
        run_aether(source)


def test_matrix_column_product_lowers_to_ir_instruction_and_interprets() -> None:
    module = _lower(
        """
int mul() {
    Matrix<int> A = [1, 2; 3, 4];
    Vector<int, Column> c = [5; 6];
    Vector<int, Column> r = A * c;
    return r[0] + r[1];
}
"""
    )

    assert IRVerifier(module).verify() is module
    instructions = module.functions[0].blocks[0].instructions
    mul = next(instruction for instruction in instructions if isinstance(instruction, IRMatrixVectorMul))

    assert mul.result.type == VectorType(IntType(), "column")
    assert mul.rows == 2
    assert mul.inner == 2
    assert IRInterpreter(module).call("mul", []) == 56


def test_matrix_column_product_builds_ssa_and_verifies() -> None:
    module = _lower(
        """
int mul() {
    Matrix<int> A = [1, 2; 3, 4];
    Vector<int, Column> c = [5; 6];
    Vector<int, Column> r = A * c;
    return r[0] + r[1];
}
"""
    )

    ssa_module = SSABuilder().build(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    mul = next(
        instruction
        for instruction in ssa_module.functions[0].blocks[0].instructions
        if isinstance(instruction, SSAMatrixVectorMul)
    )

    assert mul.result.type == VectorType(IntType(), "column")
    assert mul.rows == 2
    assert mul.inner == 2
    assert "matrix_vector_mul column" in print_ssa(ssa_module)


def test_matrix_column_product_llvm_text_uses_loops_over_contiguous_storage() -> None:
    module = _lower(
        """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    Vector<int, Column> c = [5; 6];
    Vector<int, Column> r = A * c;
    return r[0] + r[1];
}
"""
    )
    llvm = print_llvm(SSABuilder().build(module))

    assert "matrix.vector.outer.loop" in llvm
    assert "matrix.vector.inner.loop" in llvm
    assert "@aether_array_new(i64 4, i64 2)" in llvm
    assert "getelementptr i32" in llvm
    assert "load i32" in llvm
    assert "mul i32" in llvm
    assert "add i32" in llvm
    assert "ret i32" in llvm


def test_emit_llvm_prints_matrix_column_product(tmp_path: Path) -> None:
    program = tmp_path / "matrix_column_mul.ae"
    program.write_text(
        """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    Vector<int, Column> c = [5; 6];
    Vector<int, Column> r = A * c;
    return r[0] + r[1];
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _emit_llvm(program)

    assert exit_code == EXIT_SUCCESS
    assert "matrix.vector.outer.loop" in stdout
    assert "matrix.vector.inner.loop" in stdout
    assert "ret i32" in stdout
    assert stderr == ""


def test_build_run_smoke_for_matrix_column_product(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "matrix_column_mul.ae"
    output = tmp_path / "matrix_column_mul"
    program.write_text(
        """
int main() {
    Matrix<int> A = [1, 2; 3, 4];
    Vector<int, Column> c = [5; 6];
    Vector<int, Column> r = A * c;
    return r[0] + r[1];
}
""",
        encoding="utf-8",
    )
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(["build", str(program), "-o", str(output)], stdout=stdout, stderr=stderr)

    assert exit_code == EXIT_SUCCESS
    assert stderr.getvalue() == ""
    completed = subprocess.run([str(output)], check=False, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 56
    assert completed.stdout == ""
    assert completed.stderr == ""
