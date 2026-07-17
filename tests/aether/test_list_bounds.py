from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner, print_llvm
from aether.errors import AetherRuntimeError
from aether.interpreter import Interpreter
from aether.ir import IRExecutionError, IRInterpreter, IRListGet, IRListSet, IRLowerer, IRVerifier
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import execute_pipeline, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSAListGet, SSAListSet
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


PANIC = "Aether panic: List index out of bounds\n"


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


def test_list_get_and_set_valid_indices_match_ast_ir_and_native() -> None:
    ast_result = run_aether("List<int> xs = {3, 4}; xs[1] = 7; int result = xs[1];")
    source = "int main() { List<int> xs = {3, 4}; xs[1] = 7; return xs[1]; }"

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
def test_invalid_list_indices_panic_in_ast_ir_and_native(
    operation: str,
    values: str,
    index: int,
    length: int,
) -> None:
    statement = f"int ignored = xs[{index}];" if operation == "get" else f"xs[{index}] = 9;"
    ast_source = f"List<int> xs = {{{values}}}; {statement}"
    native_source = f"int main() {{ List<int> xs = {{{values}}}; {statement} return 0; }}"
    expected = "Aether panic: List index out of bounds"

    with pytest.raises(AetherRuntimeError, match=expected):
        run_aether(ast_source)
    with pytest.raises(IRExecutionError, match=expected):
        IRInterpreter(_lower(native_source)).call("main")

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(native_source), stdout=stdout) == 1
        assert stdout.getvalue() == PANIC


def test_invalid_ast_list_set_does_not_modify_the_list() -> None:
    checker = TypeChecker()
    interpreter = Interpreter()
    execute_pipeline(
        "List<int> xs = {1, 2, 3};",
        type_checker=checker,
        interpreter=interpreter,
    )

    with pytest.raises(AetherRuntimeError, match="Aether panic: List index out of bounds"):
        execute_pipeline(
            "xs[3] = 9;",
            type_checker=checker,
            interpreter=interpreter,
        )

    assert [element.value for element in interpreter.global_env.get("xs").value] == [1, 2, 3]


def test_invalid_ir_list_set_does_not_modify_the_list() -> None:
    module = _lower("int set(List<int> xs) { xs[3] = 9; return 0; }")
    values = [1, 2, 3]

    with pytest.raises(IRExecutionError, match="Aether panic: List index out of bounds"):
        IRInterpreter(module).call("set", [values])

    assert values == [1, 2, 3]


def test_llvm_list_index_helper_checks_before_data_gep_load_or_store() -> None:
    llvm = print_llvm(
        _ssa("int main() { List<int> xs = {1, 2}; xs[1] = 9; return xs[1]; }")
    )

    helper = llvm[llvm.index("define private void @aether_list_check_index") :]
    assert helper.index("%length = load i64") < helper.index("%nonnegative = icmp sge i64")
    assert helper.index("%nonnegative = icmp sge i64") < helper.index("%within_length = icmp ult i64")
    assert "define private void @aether_list_index_bounds_panic() noreturn" in llvm
    assert 'c"Aether panic: List index out of bounds\\00"' in llvm

    main = llvm[llvm.index("define i32 @main") :]
    cursor = 0
    for _ in range(2):
        check = main.index("call void @aether_list_check_index", cursor)
        data_field = main.index("getelementptr %AetherList", check)
        data_load = main.index("load ptr", data_field)
        element_gep = main.index("getelementptr i32", data_load)
        access = min(
            position
            for token in ("store i32", "load i32")
            if (position := main.find(token, element_gep)) != -1
        )
        assert check < data_field < data_load < element_gep < access
        cursor = access + 1


def test_dce_preserves_unused_list_get_because_it_may_trap() -> None:
    source = "int main() { List<int> xs = {1}; int ignored = xs[1]; return 0; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRListGet) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListGet) for item in _instructions(optimized_ssa))
    with pytest.raises(IRExecutionError, match="Aether panic: List index out of bounds"):
        IRInterpreter(optimized_ir).call("main")


def test_list_set_remains_side_effecting_in_ir_and_ssa_optimizers() -> None:
    source = "int main() { List<int> xs = {1}; xs[0] = 9; return 0; }"

    assert any(
        isinstance(item, IRListSet)
        for item in _instructions(OptimizerPipeline().run(_lower(source)))
    )
    assert any(
        isinstance(item, SSAListSet)
        for item in _instructions(SSAOptimizerPipeline().run(_ssa(source)))
    )
