from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner
from aether.errors import AetherRuntimeError, IRBackendUnsupportedFeatureError
from aether.ir import IRExecutionError, IRInterpreter, IRVectorGet
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSAVectorGet
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _run_ir(source: str) -> tuple[object, str]:
    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(source)))
    result = interpreter.call("main")
    return result, interpreter.output


def _assert_ast_ir_native_output(
    ast_source: str,
    compiled_source: str,
    expected_output: str,
) -> None:
    assert run_aether(ast_source).output == expected_output
    result, output = _run_ir(compiled_source)
    assert result == 0
    assert output == expected_output

    if shutil.which("clang") is None:
        return
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(compiled_source), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == expected_output
    assert stderr.getvalue() == ""


def test_backend_parity_characterization_main_is_shared_entry_point() -> None:
    source = """
int add(int a, int b) {
    return a + b;
}

int main() {
    int x = add(2, 3);
    x = x + 1;
    if x == 6 {
        println("ok");
    }
    return 0;
}
"""

    assert run_aether(source).output == "ok\n"
    assert _run_ir(source) == (0, "ok\n")

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(source), stdout=stdout) == 0
        assert stdout.getvalue() == "ok\n"


def test_backend_parity_characterization_while_output_matches_when_entry_is_adapted() -> None:
    body = """
int i = 0;
while i < 3 {
    println(i);
    i = i + 1;
}
"""
    compiled = f"int main() {{\n{body}\nreturn 0;\n}}"

    _assert_ast_ir_native_output(body, compiled, "0\n1\n2\n")


def test_backend_parity_characterization_recursion_matches_with_adapted_entry() -> None:
    function = """
int factorial(int n) {
    if n <= 1 { return 1; }
    return n * factorial(n - 1);
}
"""
    ast_source = function + "\nprintln(factorial(5));"
    compiled_source = function + "\nint main() { println(factorial(5)); return 0; }"

    _assert_ast_ir_native_output(ast_source, compiled_source, "120\n")


def test_backend_parity_characterization_array_set_slice_and_output() -> None:
    body = """
Array<int> values = {1, 2, 3};
values[1] = 9;
Array<int> copy = values[0:2];
println(values[1]);
println(copy[0]);
"""
    compiled = f"int main() {{\n{body}\nreturn 0;\n}}"

    _assert_ast_ir_native_output(body, compiled, "9\n1\n")


def test_backend_parity_characterization_list_mutations_and_sort() -> None:
    body = """
List<int> values = {3, 1, 2};
values.push(4);
values.insert(1, 9);
int removed = values.removeAt(0);
values.sort();
println(values[0]);
println(values.contains(9));
println(removed);
"""
    compiled = f"int main() {{\n{body}\nreturn 0;\n}}"

    _assert_ast_ir_native_output(body, compiled, "1\ntrue\n3\n")


def test_backend_parity_vector_get_trap_is_preserved_by_dce() -> None:
    source = """
int main() {
    Vector<int, Row> values = [1, 2];
        int ignored = values[3];
    return 0;
}
"""
    ir = IRBackend().lower_verified(_typed(source))
    with pytest.raises(IRExecutionError, match="Aether panic: Vector index out of bounds"):
        IRInterpreter(ir).call("main")

    optimized_ir = OptimizerPipeline().run(ir)
    assert any(
        isinstance(instruction, IRVectorGet)
        for function in optimized_ir.functions
        for block in function.blocks
        for instruction in block.instructions
    )
    with pytest.raises(IRExecutionError, match="Aether panic: Vector index out of bounds"):
        IRInterpreter(optimized_ir).call("main")

    optimized_ssa = SSAOptimizerPipeline().run(lower_to_verified_ssa(_typed(source)))
    assert any(
        isinstance(instruction, SSAVectorGet)
        for function in optimized_ssa.functions
        for block in function.blocks
        for instruction in block.instructions
    )


def test_backend_parity_matrix_coordinates_are_one_based_and_checked_independently() -> None:
    ast_source = "Matrix<int> m = [1, 2; 3, 4]; int x = m[0, 2];"
    compiled_source = "int main() { Matrix<int> m = [1, 2; 3, 4]; return m[0, 2]; }"

    with pytest.raises(AetherRuntimeError, match="Aether panic: Matrix index out of bounds"):
        run_aether(ast_source)

    with pytest.raises(IRExecutionError, match="Aether panic: Matrix index out of bounds"):
        _run_ir(compiled_source)

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(compiled_source), stdout=stdout) == 1
        assert stdout.getvalue() == "Aether panic: Matrix index out of bounds\n"


def test_backend_parity_characterization_nested_function_is_ast_only() -> None:
    function = """
int outer() {
    int inner() { return 2; }
    return inner();
}
"""
    ast_source = function + "\nprintln(outer());"
    compiled_source = function + "\nint main() { return outer(); }"

    assert run_aether(ast_source).output == "2\n"
    with pytest.raises(IRBackendUnsupportedFeatureError, match="FunctionDeclaration"):
        IRBackend().lower(_typed(compiled_source))


@pytest.mark.parametrize(
    ("declaration", "expected_output", "unsupported"),
    [
        (
            """
struct Point {
    int x;
    int y;
}
Point p = Point(2, 3);
println(p.x + p.y);
""",
            "5\n",
            "struct declarations",
        ),
        (
            """
class Counter {
    int value;
    public int getValue() { return value; }
}
Counter c = Counter(7);
println(c.getValue());
""",
            "7\n",
            "class declarations",
        ),
    ],
    ids=("struct", "class"),
)
def test_backend_parity_characterization_user_types_are_ast_only(
    declaration: str,
    expected_output: str,
    unsupported: str,
) -> None:
    assert run_aether(declaration).output == expected_output

    with pytest.raises(IRBackendUnsupportedFeatureError, match=unsupported):
        IRBackend().lower(_typed(declaration))
