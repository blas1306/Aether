from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, IRBackendUnsupportedFeatureError
from aether.interpreter import Interpreter
from aether.ir import IRBasicBlock, IRFunction, IRModule, IRReturn, IRValue, IntType
from aether.pipeline import (
    ASTBackend,
    IRBackend,
    IR_MAIN_RESULT_NAME,
    execute_pipeline,
    parse_source,
    prepare_typed_program,
    run_ast_backend,
    typecheck_program,
)
from aether.runner import run_aether
from aether.typechecker import TypeChecker


def test_frontend_stages_can_feed_ast_backend() -> None:
    program = parse_source(
        """
int add(int left, int right) {
    return left + right;
}

answer = add(2, 3);
println(answer);
"""
    )
    checker = TypeChecker()
    checked_program = typecheck_program(program, checker)
    interpreter = Interpreter()

    env = run_ast_backend(checked_program, interpreter)

    assert env.values["answer"].value == 5
    assert interpreter.output == "5\n"


def test_execute_pipeline_still_uses_ast_backend_behavior() -> None:
    checker = TypeChecker()
    interpreter = Interpreter()

    env = execute_pipeline(
        "value = 21 * 2; println(value);",
        type_checker=checker,
        interpreter=interpreter,
    )

    assert env.values["value"].value == 42
    assert interpreter.output == "42\n"


def test_ast_backend_runs_prepared_typed_program() -> None:
    typed_program = prepare_typed_program(
        "value = 8 + 13; println(value);",
        TypeChecker(),
    )
    interpreter = Interpreter()

    env = ASTBackend(interpreter).run(typed_program)

    assert env.values["value"].value == 21
    assert interpreter.output == "21\n"


def test_ir_backend_runs_prepared_typed_program() -> None:
    typed_program = prepare_typed_program(
        """
int main() {
    return 42;
}
""",
        TypeChecker(),
    )
    backend = IRBackend()

    env = backend.run(typed_program)

    assert env.values[IR_MAIN_RESULT_NAME].value == 42


def test_ir_backend_verifies_before_interpreting() -> None:
    typed_program = prepare_typed_program(
        """
int main() {
    return 42;
}
""",
        TypeChecker(),
    )
    calls = []

    class RecordingIRBackend(IRBackend):
        def verify(self, module):
            calls.append([function.name for function in module.functions])
            return super().verify(module)

    RecordingIRBackend().run(typed_program)

    assert calls == [["main"]]


def test_ir_optimizer_flow_verifies_after_optimizing() -> None:
    typed_program = prepare_typed_program(
        """
int main() {
    return 42;
}
""",
        TypeChecker(),
    )
    backend = IRBackend()
    module = backend.lower_verified(typed_program)

    class InvalidOptimizer:
        def run(self, module):
            int_type = IntType()
            missing = IRValue("missing", int_type)
            return IRModule(
                [
                    IRFunction(
                        "main",
                        [],
                        int_type,
                        [IRBasicBlock("entry", [IRReturn(missing)])],
                    )
                ]
            )

    with pytest.raises(AetherRuntimeError, match="IR verifier rejected module"):
        backend.optimize_verified(module, InvalidOptimizer())


def test_ir_backend_does_not_change_ast_backend() -> None:
    typed_program = prepare_typed_program(
        "value = 8 + 13; println(value);",
        TypeChecker(),
    )
    interpreter = Interpreter()

    env = ASTBackend(interpreter).run(typed_program)

    assert env.values["value"].value == 21
    assert interpreter.output == "21\n"


@pytest.mark.parametrize(
    ("source", "call"),
    [
        (
            """
int add(int a, int b) {
    return a + b;
}
int main() {
    return add(2, 3);
}
""",
            "main()",
        ),
        (
            """
int main() {
    int x = 2;
    int y = 3;
    return x * y;
}
""",
            "main()",
        ),
        (
            """
int main() {
    int x = -4;
    if x < 0 {
        return 0 - x;
    } else {
        return x;
    }
}
""",
            "main()",
        ),
        (
            """
int sumTo(int n) {
    int i = 0;
    int sum = 0;
    while i <= n {
        sum = sum + i;
        i = i + 1;
    }
    return sum;
}
int main() {
    return sumTo(5);
}
""",
            "main()",
        ),
        (
            """
int increment(int value) {
    return value + 1;
}
int doubleIncrement(int value) {
    return increment(increment(value));
}
int main() {
    return doubleIncrement(10);
}
""",
            "main()",
        ),
    ],
)
def test_ir_backend_matches_ast_for_supported_subset(source: str, call: str) -> None:
    typed_program = prepare_typed_program(source, TypeChecker())
    ir_env = IRBackend().run(typed_program)

    ast_result = run_aether(f"{source}\nobserved = {call};")

    assert ir_env.values[IR_MAIN_RESULT_NAME].value == ast_result.env["observed"].value


def test_ir_backend_reports_unsupported_features_clearly() -> None:
    typed_program = prepare_typed_program(
        "class Counter { int value; }",
        TypeChecker(),
    )

    with pytest.raises(IRBackendUnsupportedFeatureError, match="class declarations"):
        IRBackend().run(typed_program)
