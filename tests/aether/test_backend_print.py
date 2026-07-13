from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner
from aether.errors import AetherTypeError, IRBackendUnsupportedFeatureError
from aether.ir import IRCall, IRInterpreter, IRPrint
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSACall, SSAPrint
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


SOURCE = """
boolean esMayor(int x) {
    if x >= 18 {
        return true;
    } else {
        return false;
    }
}

void emitPrefix() {
    print(12);
}

int effectWithValue() {
    print("!");
    return 7;
}

int main() {
    emitPrefix();
    effectWithValue();
    println(34);
    println(esMayor(19));
    println(esMayor(17));
    println("hola");
    println(2.5);
    return 0;
}
"""


AST_SOURCE = SOURCE.replace(
    """int main() {
    emitPrefix();
    effectWithValue();
    println(34);
    println(esMayor(19));
    println(esMayor(17));
    println("hola");
    println(2.5);
    return 0;
}
""",
    """emitPrefix();
effectWithValue();
println(34);
println(esMayor(19));
println(esMayor(17));
println("hola");
println(2.5);
""",
)


EXPECTED_OUTPUT = "12!34\ntrue\nfalse\nhola\n2.5\n"


def _typed(source: str = SOURCE):
    return prepare_typed_program(source, TypeChecker())


def test_print_and_call_statements_match_ast_and_ir_execution() -> None:
    assert run_aether(AST_SOURCE).output == EXPECTED_OUTPUT

    module = IRBackend().lower_verified(_typed())
    interpreter = IRInterpreter(module)

    assert interpreter.call("main") == 0
    assert interpreter.output == EXPECTED_OUTPUT

    main = next(function for function in module.functions if function.name == "main")
    calls = [
        instruction
        for block in main.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall)
    ]
    assert next(call for call in calls if call.function == "emitPrefix").result is None
    assert next(call for call in calls if call.function == "effectWithValue").result is not None
    assert any(
        isinstance(instruction, IRPrint)
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    )


def test_print_reaches_ssa_and_survives_optimization() -> None:
    module = lower_to_verified_ssa(_typed())
    optimized = SSAOptimizerPipeline().run(module)

    assert any(
        isinstance(instruction, SSAPrint)
        for function in optimized.functions
        for block in function.blocks
        for instruction in block.instructions
    )
    main = next(function for function in optimized.functions if function.name == "main")
    assert any(
        isinstance(instruction, SSACall)
        and instruction.function == "effectWithValue"
        for block in main.blocks
        for instruction in block.instructions
    )


def test_native_llvm_prints_scalars_and_booleans_as_text() -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    stdout = StringIO()
    stderr = StringIO()
    return_code = LLVMRunner().run(_typed(), stdout=stdout, stderr=stderr)

    assert return_code == 0
    assert stdout.getvalue() == EXPECTED_OUTPUT
    assert stderr.getvalue() == ""


def test_backend_rejects_print_of_aggregate_with_specific_diagnostic() -> None:
    typed = _typed(
        """
int main() {
    List<int> values = {1, 2};
    println(values);
    return 0;
}
"""
    )

    with pytest.raises(
        IRBackendUnsupportedFeatureError,
        match=r"println.*does not support values of type 'list<int>'",
    ):
        IRBackend().lower(typed)


def test_pure_expression_statement_is_rejected_by_frontend() -> None:
    source = """
int main() {
    1 + 2;
    return 0;
}
"""

    with pytest.raises(AetherTypeError, match="Only calls can be used as expression statements"):
        _typed(source)
