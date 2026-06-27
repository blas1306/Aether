from __future__ import annotations

import pytest

from aether.interpreter import Interpreter
from aether.pipeline import (
    ASTBackend,
    IRBackend,
    execute_pipeline,
    parse_source,
    prepare_typed_program,
    run_ast_backend,
    typecheck_program,
)
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


def test_ir_backend_is_lowering_only_and_not_public_execution() -> None:
    typed_program = prepare_typed_program(
        """
int answer() {
    return 42;
}
""",
        TypeChecker(),
    )
    backend = IRBackend()

    module = backend.lower(typed_program)

    assert module.functions[0].name == "answer"
    with pytest.raises(NotImplementedError, match="experimental"):
        backend.run(typed_program)
