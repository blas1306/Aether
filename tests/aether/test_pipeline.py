from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, IRBackendUnsupportedFeatureError
from aether.interpreter import Interpreter
from aether.ir import IRBasicBlock, IRFunction, IRModule, IRReturn, IRValue, IntType
from aether.pipeline import (
    ASTBackend,
    IRBackend,
    IR_MAIN_RESULT_NAME,
    SSAPipeline,
    execute_pipeline,
    lower_to_verified_ssa,
    parse_source,
    prepare_typed_program,
    run_ast_backend,
    typecheck_program,
)
from aether.ssa import SSAPhi, print_ssa
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


def test_typed_ast_lowers_to_verified_ssa() -> None:
    typed_program = prepare_typed_program(
        """
int main() {
    return 42;
}
""",
        TypeChecker(),
    )

    ssa_module = lower_to_verified_ssa(typed_program)

    assert [function.name for function in ssa_module.functions] == ["main"]
    assert print_ssa(ssa_module) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 42\n"
        "    return %0\n"
        "}"
    )


def test_verified_ir_module_lowers_to_verified_linear_ssa() -> None:
    typed_program = prepare_typed_program(
        """
int add(int left, int right) {
    return left + right;
}
""",
        TypeChecker(),
    )
    ir_module = IRBackend().lower_verified(typed_program)

    ssa_module = lower_to_verified_ssa(ir_module)

    assert print_ssa(ssa_module) == (
        "func @add(%left: int, %right: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %left, %right\n"
        "    return %0\n"
        "}"
    )


def test_lower_to_verified_ssa_accepts_general_builder() -> None:
    typed_program = prepare_typed_program(
        """
int nested(int x, int y) {
    int z = 0;
    if (x > 0) {
        if (y > 0) {
            z = 1;
        } else {
            z = 2;
        }
    } else {
        z = 3;
    }
    return z;
}
""",
        TypeChecker(),
    )

    ssa_module = lower_to_verified_ssa(typed_program, builder="general")

    assert [function.name for function in ssa_module.functions] == ["nested"]
    assert "merge1.z.phi" in print_ssa(ssa_module)


def test_lower_to_verified_ssa_defaults_to_general_builder() -> None:
    typed_program = prepare_typed_program(
        """
int nested(int x, int y) {
    int z = 0;
    if (x > 0) {
        if (y > 0) {
            z = 1;
        } else {
            z = 2;
        }
    } else {
        z = 3;
    }
    return z;
}
""",
        TypeChecker(),
    )

    default_module = lower_to_verified_ssa(typed_program)
    explicit_general_module = lower_to_verified_ssa(
        typed_program,
        builder="general",
    )

    assert print_ssa(default_module) == print_ssa(explicit_general_module)
    assert "merge1.z.phi" in print_ssa(default_module)


def test_lower_to_verified_ssa_accepts_pattern_builder_fallback() -> None:
    typed_program = prepare_typed_program(
        """
int add(int left, int right) {
    return left + right;
}
""",
        TypeChecker(),
    )

    ssa_module = lower_to_verified_ssa(typed_program, builder="pattern")

    assert print_ssa(ssa_module) == (
        "func @add(%left: int, %right: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %left, %right\n"
        "    return %0\n"
        "}"
    )


def test_ssa_pipeline_builds_if_else_phi() -> None:
    typed_program = prepare_typed_program(
        """
int choose(int x) {
    int y = 0;
    if (x > 0) {
        y = 1;
    } else {
        y = 2;
    }
    return y;
}
""",
        TypeChecker(),
    )

    ssa_module = lower_to_verified_ssa(typed_program)
    phi_nodes = [
        instruction
        for function in ssa_module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAPhi)
    ]

    assert len(phi_nodes) == 1
    assert "phi(then0:" in print_ssa(ssa_module)


def test_ssa_pipeline_builds_simple_while_sum_to_phi() -> None:
    typed_program = prepare_typed_program(
        """
int sumTo(int n) {
    int i = 0;
    int sum = 0;
    while (i <= n) {
        sum = sum + i;
        i = i + 1;
    }
    return sum;
}
""",
        TypeChecker(),
    )

    ssa_module = lower_to_verified_ssa(typed_program)
    phi_nodes = [
        instruction
        for function in ssa_module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAPhi)
    ]

    assert len(phi_nodes) == 2
    assert "phi(entry:" in print_ssa(ssa_module)


def test_ssa_pipeline_lowers_break() -> None:
    typed_program = prepare_typed_program(
        """
int first(int n) {
    while (n > 0) {
        break;
    }
    return n;
}
""",
        TypeChecker(),
    )

    ssa_module = lower_to_verified_ssa(typed_program)

    assert "jump exit0" in print_ssa(ssa_module)


def test_ssa_pipeline_lowers_continue() -> None:
    typed_program = prepare_typed_program(
        """
int skip(int n) {
    while (n > 0) {
        n = n - 1;
        continue;
    }
    return n;
}
""",
        TypeChecker(),
    )

    ssa_module = lower_to_verified_ssa(typed_program)

    assert "jump cond0" in print_ssa(ssa_module)


def test_ssa_pipeline_does_not_change_ast_backend() -> None:
    ssa_program = prepare_typed_program(
        """
int main() {
    return 42;
}
""",
        TypeChecker(),
    )
    lower_to_verified_ssa(ssa_program)
    ast_program = prepare_typed_program(
        "value = 8 + 13; println(value);",
        TypeChecker(),
    )
    interpreter = Interpreter()

    env = ASTBackend(interpreter).run(ast_program)

    assert env.values["value"].value == 21
    assert interpreter.output == "21\n"


def test_ssa_pipeline_does_not_change_ir_backend() -> None:
    typed_program = prepare_typed_program(
        """
int main() {
    return 42;
}
""",
        TypeChecker(),
    )
    lower_to_verified_ssa(typed_program)

    env = IRBackend().run(typed_program)

    assert env.values[IR_MAIN_RESULT_NAME].value == 42


def test_ssa_verifier_runs_after_builder() -> None:
    typed_program = prepare_typed_program(
        """
int main() {
    return 42;
}
""",
        TypeChecker(),
    )
    calls = []

    class RecordingSSAPipeline(SSAPipeline):
        def build(self, module):
            calls.append("build")
            return super().build(module)

        def verify(self, module):
            calls.append("verify")
            return super().verify(module)

    result = RecordingSSAPipeline().run(typed_program)

    assert result.ssa_module.functions[0].name == "main"
    assert calls == ["build", "verify"]


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
    if (x < 0) {
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
    while (i <= n) {
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

    ast_result = run_aether(source)

    assert call == "main()"
    assert ir_env.values[IR_MAIN_RESULT_NAME].value == ast_result.exit_code


def test_ir_backend_executes_class_methods() -> None:
    typed_program = prepare_typed_program(
        "class Counter { int value; public int getValue() { return value; } } "
        "int main() { Counter value = Counter(7); return value.getValue(); }",
        TypeChecker(),
    )

    result = IRBackend().run(typed_program)
    assert result.values[IR_MAIN_RESULT_NAME].value == 7
