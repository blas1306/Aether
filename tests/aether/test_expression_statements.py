from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherTypeError
from aether.integer_arithmetic import DIVISION_BY_ZERO_MESSAGE
from aether.pipeline import prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


@pytest.mark.parametrize(
    "body",
    [
        "1 + 2;",
        "int x = 10; x + 1;",
        "5 / 0;",
        "2147483647 + 1;",
    ],
)
def test_pure_expression_cannot_be_used_as_statement(body: str) -> None:
    source = f"int main() {{ {body} return 0; }}"

    with pytest.raises(AetherTypeError, match="Only calls can be used as expression statements"):
        prepare_typed_program(source, TypeChecker())


def test_call_remains_a_valid_expression_statement() -> None:
    result = run_aether('println("hola");')

    assert result.output == "hola\n"


def test_checked_operation_in_valid_computation_is_accepted_and_panics_at_runtime() -> None:
    source = "double x = 5 / 0;"

    prepare_typed_program(source, TypeChecker())

    with pytest.raises(AetherRuntimeError, match=DIVISION_BY_ZERO_MESSAGE):
        run_aether(source)
