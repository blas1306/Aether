from __future__ import annotations

from collections.abc import Callable

from aether._operand_traversal import (
    assert_complete_instruction_hierarchy,
    instruction_operands as _instruction_operands,
    instruction_result as _instruction_result,
    rewrite_instruction_operands as _rewrite_instruction_operands,
)

from .model import SSAInstruction, SSAValue


def instruction_operands(instruction: SSAInstruction) -> tuple[SSAValue, ...]:
    return _instruction_operands(instruction, SSAValue)


def rewrite_instruction_operands(
    instruction: SSAInstruction,
    rewrite_value: Callable[[SSAValue], SSAValue],
) -> tuple[SSAInstruction, int]:
    return _rewrite_instruction_operands(instruction, SSAValue, rewrite_value)


def instruction_result(instruction: SSAInstruction) -> SSAValue | None:
    return _instruction_result(instruction, SSAValue)


def validate_operand_coverage() -> None:
    assert_complete_instruction_hierarchy(SSAInstruction)
