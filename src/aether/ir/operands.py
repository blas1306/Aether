from __future__ import annotations

from collections.abc import Callable

from aether._operand_traversal import (
    assert_complete_instruction_hierarchy,
    instruction_operands as _instruction_operands,
    instruction_result as _instruction_result,
    rewrite_instruction_operands as _rewrite_instruction_operands,
)

from .model import IRInstruction, IRValue


def instruction_operands(instruction: IRInstruction) -> tuple[IRValue, ...]:
    return _instruction_operands(instruction, IRValue)


def rewrite_instruction_operands(
    instruction: IRInstruction,
    rewrite_value: Callable[[IRValue], IRValue],
) -> tuple[IRInstruction, int]:
    return _rewrite_instruction_operands(instruction, IRValue, rewrite_value)


def instruction_result(instruction: IRInstruction) -> IRValue | None:
    return _instruction_result(instruction, IRValue)


def validate_operand_coverage() -> None:
    assert_complete_instruction_hierarchy(IRInstruction)
