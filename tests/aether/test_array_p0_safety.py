from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.array_safety import (
    ARRAY_LENGTH_OVERFLOW_MESSAGE,
    checked_array_length_to_int,
)
from aether.backend.llvm import LLVMRunner, print_llvm
from aether.errors import AetherRuntimeError
from aether.interpreter import Interpreter
from aether.ir import (
    IRArrayGet,
    IRArrayLength,
    IRArraySet,
    IRExecutionError,
    IRInterpreter,
    IRLowerer,
    IRVerifier,
)
from aether.ir.optimizer import OptimizerPipeline
from aether.list_safety import INT32_MAX
from aether.pipeline import (
    execute_pipeline,
    lower_to_verified_ssa,
    prepare_typed_program,
)
from aether.runner import run_aether
from aether.ssa import SSAArrayGet, SSAArrayLength, SSAArraySet
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


PANIC = "Aether panic: Array index out of bounds\n"


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _lower(source: str):
    typed = _typed(source)
    return IRVerifier(IRLowerer().lower(typed.program)).verify()


def _ssa(source: str):
    return lower_to_verified_ssa(_typed(source))


def _instructions(module):
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]


def test_array_get_and_set_valid_indices_match_ast_ir_and_native() -> None:
    ast_result = run_aether("Array<int> xs = {3, 4}; xs[1] = 7; int result = xs[1];")
    source = "int main() { Array<int> xs = {3, 4}; xs[1] = 7; return xs[1]; }"

    assert ast_result.env["result"].value == 7
    assert IRInterpreter(_lower(source)).call("main") == 7
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(_typed(source)) == 7


@pytest.mark.parametrize(
    ("operation", "values", "index", "length"),
    [
        ("get", "1, 2, 3", -1, 3),
        ("get", "1, 2, 3", 3, 3),
        ("get", "1, 2, 3", 4, 3),
        ("set", "1, 2, 3", -1, 3),
        ("set", "1, 2, 3", 3, 3),
        ("set", "1, 2, 3", 4, 3),
        ("get", "", 0, 0),
        ("set", "", 0, 0),
    ],
)
def test_invalid_array_indices_panic_in_ast_ir_and_native(
    operation: str,
    values: str,
    index: int,
    length: int,
) -> None:
    statement = f"int ignored = xs[{index}];" if operation == "get" else f"xs[{index}] = 9;"
    ast_source = f"Array<int> xs = {{{values}}}; {statement}"
    native_source = f"int main() {{ Array<int> xs = {{{values}}}; {statement} return 0; }}"

    with pytest.raises(AetherRuntimeError, match="Aether panic: Array index out of bounds"):
        run_aether(ast_source)
    with pytest.raises(IRExecutionError, match="Aether panic: Array index out of bounds"):
        IRInterpreter(_lower(native_source)).call("main")

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(native_source), stdout=stdout) == 1
        assert stdout.getvalue() == PANIC


def test_invalid_array_set_does_not_modify_ast_or_ir_storage() -> None:
    checker = TypeChecker()
    interpreter = Interpreter()
    execute_pipeline(
        "Array<int> xs = {1, 2, 3};",
        type_checker=checker,
        interpreter=interpreter,
    )
    with pytest.raises(AetherRuntimeError, match="Aether panic: Array index out of bounds"):
        execute_pipeline("xs[3] = 9;", type_checker=checker, interpreter=interpreter)
    assert [element.value for element in interpreter.global_env.get("xs").value] == [1, 2, 3]

    module = _lower("int set(Array<int> xs) { xs[3] = 9; return 0; }")
    values = [1, 2, 3]
    with pytest.raises(IRExecutionError, match="Aether panic: Array index out of bounds"):
        IRInterpreter(module).call("set", [values])
    assert values == [1, 2, 3]


def test_llvm_array_check_precedes_data_load_gep_and_access() -> None:
    llvm = print_llvm(_ssa("int main() { Array<int> xs = {1, 2}; xs[1] = 9; return xs[1]; }"))

    assert "define private void @aether_array_index_bounds_panic() noreturn" in llvm
    assert 'c"Aether panic: Array index out of bounds\\00"' in llvm
    main = llvm[llvm.index("define i32 @main") :]
    cursor = 0
    for _ in range(2):
        check = main.index("call void @aether_array_check_index", cursor)
        data_field = main.index("getelementptr %AetherArray", check)
        data_load = main.index("load ptr", data_field)
        element_gep = main.index("getelementptr i32", data_load)
        access = min(
            position
            for token in ("store i32", "load i32")
            if (position := main.find(token, element_gep)) != -1
        )
        assert check < data_field < data_load < element_gep < access
        cursor = access + 1


def test_array_new_checks_bytes_before_allocations_and_stores() -> None:
    llvm = print_llvm(_ssa("int main() { Array<int> xs = {1, 2, 3}; return xs.length; }"))
    start = llvm.index("define private ptr @aether_array_new")
    end = llvm.index("\n}", start)
    helper = llvm.index("call i64 @aether_checked_allocation_bytes", start, end)
    header = llvm.index(
        "call ptr @aether_alloc(i64 ptrtoint (ptr getelementptr (%AetherArray",
        start,
        end,
    )
    length_store = llvm.index("store i64 %length", start, end)
    data = llvm.index("call ptr @aether_alloc(i64 %data_size)", start, end)
    data_store = llvm.index("store ptr %data", start, end)

    assert helper < header < length_store < data < data_store
    assert "%data_size = mul i64" not in llvm[start:end]
    assert "@llvm.umul.with.overflow.i64" in llvm


def test_array_length_conversion_is_checked_without_allocating_huge_arrays() -> None:
    assert checked_array_length_to_int(0) == 0
    assert checked_array_length_to_int(INT32_MAX) == INT32_MAX
    with pytest.raises(OverflowError, match=ARRAY_LENGTH_OVERFLOW_MESSAGE):
        checked_array_length_to_int(INT32_MAX + 1)
    with pytest.raises(OverflowError, match=ARRAY_LENGTH_OVERFLOW_MESSAGE):
        checked_array_length_to_int(-1)

    llvm = print_llvm(_ssa("int main() { Array<int> xs = {1, 2}; return xs.length; }"))
    assert "define private i32 @aether_array_length_to_int" in llvm
    assert "call i32 @aether_array_length_to_int" in llvm
    assert "Aether panic: Array length does not fit in int" in llvm
    main = llvm[llvm.index("define i32 @main") :]
    assert "trunc i64" not in main


def test_dce_preserves_array_operations_that_may_trap_or_have_effects() -> None:
    source = "int main() { Array<int> xs = {1}; int ignored = xs[1]; int n = xs.length; xs[0] = 9; return 0; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRArrayGet) for item in _instructions(optimized_ir))
    assert any(isinstance(item, IRArrayLength) for item in _instructions(optimized_ir))
    assert any(isinstance(item, IRArraySet) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAArrayGet) for item in _instructions(optimized_ssa))
    assert any(isinstance(item, SSAArrayLength) for item in _instructions(optimized_ssa))
    assert any(isinstance(item, SSAArraySet) for item in _instructions(optimized_ssa))


def test_array_alias_observes_set_after_optimization() -> None:
    source = "int main() { Array<int> a = {1}; Array<int> b = a; int before = a[0]; b[0] = 9; return before + a[0]; }"

    assert IRInterpreter(OptimizerPipeline().run(_lower(source))).call("main") == 10
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(_typed(source)) == 10
