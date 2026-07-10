from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether import ast
from aether.backend.llvm import print_llvm
from aether.cli import EXIT_SUCCESS, main
from aether.errors import AetherTypeError
from aether.ir import IRInterpreter, IRLowerer, IROuterProduct, IRVerifier, IntType, MatrixType
from aether.pipeline import parse_source
from aether.runner import run_aether
from aether.ssa import SSAOuterProduct, SSABuilder, SSAVerifier, print_ssa
from aether.typechecker import TypeChecker
from aether.types import MatrixType as RuntimeMatrixType


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


def test_outer_product_parser_accepts_column_row_operator_shape() -> None:
    program = parse_source("Vector<int, Column> c = [1; 2]; Vector<int, Row> r = [3, 4]; M = c * r;")

    assignment = program.statements[-1]
    assert isinstance(assignment, ast.Assignment)
    assert isinstance(assignment.expression, ast.BinaryExpression)
    assert assignment.expression.operator == "*"


def test_outer_product_typechecks_and_runtime_delegates_to_matmul_semantics() -> None:
    _typecheck(
        """
int main() {
    Vector<int, Column> c = [1; 2; 3];
    Vector<int, Row> r = [4, 5];
    Matrix<int> M = c * r;
    return M[0, 0] + M[2, 1];
}
"""
    )

    result = run_aether(
        """
Vector<int, Column> c = [1; 2; 3];
Vector<int, Row> r = [4, 5];
Matrix<int> M = c * r;
"""
    )

    assert result.env["M"].type_name == RuntimeMatrixType("int", 3, 2)
    assert [[element.value for element in row.value] for row in result.env["M"].value] == [
        [4, 5],
        [8, 10],
        [12, 15],
    ]


@pytest.mark.parametrize(
    "source",
    [
        "Vector<int, Row> a = [1, 2]; Vector<int, Row> b = [3, 4]; x = a * b;",
        "Vector<int, Column> a = [1; 2]; Vector<int, Column> b = [3; 4]; x = a * b;",
        "Matrix<int> A = [1, 2; 3, 4]; Vector<int, Row> r = [5, 6]; y = A * r;",
        "Vector<int, Column> c = [1; 2]; Matrix<int> A = [3, 4; 5, 6]; y = c * A;",
    ],
)
def test_outer_product_keeps_other_invalid_star_combinations_rejected(source: str) -> None:
    with pytest.raises(AetherTypeError):
        run_aether(source)


def test_outer_product_lowers_to_ir_instruction_and_interprets() -> None:
    module = _lower(
        """
int outer() {
    Vector<int, Column> c = [1; 2; 3];
    Vector<int, Row> r = [4, 5];
    Matrix<int> M = c * r;
    return M[0, 0] + M[0, 1] + M[1, 0] + M[1, 1] + M[2, 0] + M[2, 1];
}
"""
    )

    assert IRVerifier(module).verify() is module
    instructions = module.functions[0].blocks[0].instructions
    outer = next(instruction for instruction in instructions if isinstance(instruction, IROuterProduct))

    assert outer.result.type == MatrixType(IntType())
    assert outer.rows == 3
    assert outer.cols == 2
    assert IRInterpreter(module).call("outer", []) == 54


def test_outer_product_builds_ssa_and_verifies() -> None:
    module = _lower(
        """
int outer() {
    Vector<int, Column> c = [1; 2; 3];
    Vector<int, Row> r = [4, 5];
    Matrix<int> M = c * r;
    return M[2, 1];
}
"""
    )

    ssa_module = SSABuilder().build(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    outer = next(
        instruction
        for instruction in ssa_module.functions[0].blocks[0].instructions
        if isinstance(instruction, SSAOuterProduct)
    )

    assert outer.result.type == MatrixType(IntType())
    assert outer.rows == 3
    assert outer.cols == 2
    assert "outer_product column_row" in print_ssa(ssa_module)


def test_outer_product_llvm_text_uses_nested_loops_and_array_allocation() -> None:
    module = _lower(
        """
int main() {
    Vector<int, Column> c = [1; 2; 3];
    Vector<int, Row> r = [4, 5];
    Matrix<int> M = c * r;
    return M[0, 0] + M[0, 1] + M[1, 0] + M[1, 1] + M[2, 0] + M[2, 1];
}
"""
    )
    llvm = print_llvm(SSABuilder().build(module))

    assert "outer.product.outer.loop" in llvm
    assert "outer.product.inner.loop" in llvm
    assert "@aether_array_new(i64 4, i64 6)" in llvm
    assert "getelementptr i32" in llvm
    assert "load i32" in llvm
    assert "mul i32" in llvm
    assert "store i32" in llvm
    assert "ret i32" in llvm


def test_emit_llvm_prints_outer_product(tmp_path: Path) -> None:
    program = tmp_path / "outer_product.ae"
    program.write_text(
        """
int main() {
    Vector<int, Column> c = [1; 2; 3];
    Vector<int, Row> r = [4, 5];
    Matrix<int> M = c * r;
    return M[0, 0] + M[0, 1] + M[1, 0] + M[1, 1] + M[2, 0] + M[2, 1];
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _emit_llvm(program)

    assert exit_code == EXIT_SUCCESS
    assert "outer.product.outer.loop" in stdout
    assert "outer.product.inner.loop" in stdout
    assert "ret i32" in stdout
    assert stderr == ""


def test_build_run_smoke_for_outer_product(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "outer_product.ae"
    output = tmp_path / "outer_product"
    program.write_text(
        """
int main() {
    Vector<int, Column> c = [1; 2; 3];
    Vector<int, Row> r = [4, 5];
    Matrix<int> M = c * r;
    return M[0, 0] + M[0, 1] + M[1, 0] + M[1, 1] + M[2, 0] + M[2, 1];
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
    assert completed.returncode == 54
    assert completed.stdout == ""
    assert completed.stderr == ""
