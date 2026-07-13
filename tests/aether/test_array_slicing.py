from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether import ast
from aether.backend.llvm import LLVMRunner, print_llvm
from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.ir import IRArraySlice, IRExecutionError, IRInterpreter, IRLowerer, IRVerifier, print_ir
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import lower_to_verified_ssa, parse_source, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSAArraySlice, print_ssa
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


PANIC = "Aether panic: Array slice out of bounds"


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _lower(source: str):
    typed = _typed(source)
    return IRVerifier(IRLowerer().lower(typed.program)).verify()


def _ssa(source: str):
    return lower_to_verified_ssa(_typed(source))


def _instructions(module):
    return [item for function in module.functions for block in function.blocks for item in block.instructions]


def test_parser_uses_a_specific_slice_expression() -> None:
    program = parse_source("int main() { Array<int> a = {1}; Array<int> b = a[0:1]; return 0; }")
    initializer = program.statements[0].body[1].initializer

    assert isinstance(initializer, ast.SliceExpression)
    assert isinstance(initializer.collection, ast.Identifier)
    assert isinstance(initializer.start, ast.Literal)
    assert isinstance(initializer.end, ast.Literal)


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [("1:4", [2, 3, 4]), ("0:5", [1, 2, 3, 4, 5]), ("2:2", [])],
)
def test_array_slice_semantics(bounds: str, expected: list[int]) -> None:
    values = ", ".join(str(value) for value in expected)
    source = f"Array<int> a = {{1, 2, 3, 4, 5}}; Array<int> actual = a[{bounds}]; Array<int> expected = {{{values}}}; println(actual == expected);"

    assert run_aether(source).output == "true\n"


def test_array_slice_is_an_independent_copy() -> None:
    result = run_aether(
        "Array<int> a = {1, 2, 3}; Array<int> b = a[0:2]; b[0] = 99; println(a); println(b);"
    )

    assert result.output.splitlines() == ["{1, 2, 3}", "{99, 2}"]


@pytest.mark.parametrize("bounds", ["2:1", "0:4", "-1:2", "0:-1"])
def test_array_slice_bounds_panic_in_language_interpreter(bounds: str) -> None:
    with pytest.raises(AetherRuntimeError, match=PANIC):
        run_aether(f"Array<int> a = {{1, 2, 3}}; a[{bounds}];")


def test_array_slice_requires_array_and_int_bounds() -> None:
    with pytest.raises(AetherTypeError, match="slice start must be int"):
        _typed("int main() { Array<int> a = {1}; Array<int> b = a[true:1]; return 0; }")
    with pytest.raises(AetherTypeError, match="slice end must be int"):
        _typed("int main() { Array<int> a = {1}; Array<int> b = a[0:false]; return 0; }")


@pytest.mark.parametrize("slice_expression", ["a[:]", "a[0:]", "a[:1]", "a[0:1:2]"])
def test_other_array_slice_forms_remain_unsupported(slice_expression: str) -> None:
    with pytest.raises((AetherSyntaxError, AetherTypeError)):
        _typed(f"int main() {{ Array<int> a = {{1}}; {slice_expression}; return 0; }}")


def test_array_slice_assignment_remains_unsupported() -> None:
    with pytest.raises(AetherTypeError, match="Slice assignment is not supported"):
        _typed("int main() { Array<int> a = {1, 2}; a[0:1] = {9}; return 0; }")


def test_ir_and_ssa_have_specific_array_slice_instructions() -> None:
    source = "int main() { Array<int> a = {1, 2, 3}; Array<int> b = a[1:3]; return b.length; }"
    ir = _lower(source)
    ssa = _ssa(source)
    ir_slice = next(item for item in _instructions(ir) if isinstance(item, IRArraySlice))
    ssa_slice = next(item for item in _instructions(ssa) if isinstance(item, SSAArraySlice))

    assert (ir_slice.allocates, ir_slice.reads_memory, ir_slice.may_trap) == (True, True, True)
    assert (ssa_slice.allocates, ssa_slice.reads_memory, ssa_slice.may_trap) == (True, True, True)
    assert "array_slice" in print_ir(ir)
    assert "array_slice" in print_ssa(ssa)


@pytest.mark.parametrize("bounds", ["2:1", "0:4", "-1:2", "0:-1"])
def test_ir_interpreter_checks_array_slice_bounds(bounds: str) -> None:
    module = _lower(f"int main() {{ Array<int> a = {{1, 2, 3}}; Array<int> b = a[{bounds}]; return 0; }}")

    with pytest.raises(IRExecutionError, match=PANIC):
        IRInterpreter(module).call("main")


def test_dce_preserves_unused_array_slice_because_it_may_trap() -> None:
    source = "int main() { Array<int> a = {1}; Array<int> ignored = a[1:0]; return 0; }"

    assert any(isinstance(item, IRArraySlice) for item in _instructions(OptimizerPipeline().run(_lower(source))))
    assert any(isinstance(item, SSAArraySlice) for item in _instructions(SSAOptimizerPipeline().run(_ssa(source))))


def test_llvm_calls_array_slice_runtime_helper() -> None:
    llvm = print_llvm(_ssa("int main() { Array<int> a = {1, 2, 3}; Array<int> b = a[0:2]; return b[1]; }"))
    main = llvm[llvm.index("define i32 @main") :]

    assert "define private ptr @aether_array_slice" in llvm
    assert PANIC in llvm
    assert "call ptr @aether_array_slice" in main
    assert "llvm.memcpy" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_array_slice_is_independent() -> None:
    source = "int main() { Array<int> a = {1, 2, 3}; Array<int> b = a[0:2]; b[0] = 99; return a[0] + b[0]; }"

    assert LLVMRunner().run(_typed(source)) == 100


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_array_slice_bounds_panic() -> None:
    output = StringIO()
    source = "int main() { Array<int> a = {1, 2, 3}; Array<int> b = a[-1:2]; return 0; }"

    assert LLVMRunner().run(_typed(source), stdout=output) == 1
    assert output.getvalue() == f"{PANIC}\n"
