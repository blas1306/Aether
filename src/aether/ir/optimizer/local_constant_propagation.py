from __future__ import annotations

from dataclasses import replace
from typing import Any

from aether.ir.model import (
    IRBasicBlock,
    IRBinaryOp,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRLoad,
    IRModule,
    IRStore,
    IRValue,
)


class LocalConstantPropagator:
    """Replace same-block loads from known constant slots with constants."""

    def run(self, module: IRModule) -> IRModule:
        functions = [self._propagate_function(function) for function in module.functions]
        return IRModule(functions)

    def _propagate_function(self, function: IRFunction) -> IRFunction:
        blocks = [self._propagate_block(block) for block in function.blocks]
        return IRFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            blocks,
        )

    def _propagate_block(self, block: IRBasicBlock) -> IRBasicBlock:
        value_constants: dict[str, Any] = {}
        slot_constants: dict[str, Any] = {}
        instructions: list[IRInstruction] = []

        for instruction in block.instructions:
            propagated = self._propagate_instruction(
                instruction,
                value_constants,
                slot_constants,
            )
            instructions.append(propagated)

        return IRBasicBlock(block.name, instructions)

    def _propagate_instruction(
        self,
        instruction: IRInstruction,
        value_constants: dict[str, Any],
        slot_constants: dict[str, Any],
    ) -> IRInstruction:
        if isinstance(instruction, IRConst):
            value_constants[instruction.result.name] = instruction.value
            return replace(instruction)

        if isinstance(instruction, IRStore):
            constant = value_constants.get(instruction.value.name, _UNKNOWN)
            if constant is _UNKNOWN:
                slot_constants.pop(instruction.slot.name, None)
            else:
                slot_constants[instruction.slot.name] = constant
            return instruction

        if isinstance(instruction, IRLoad):
            constant = slot_constants.get(instruction.slot.name, _UNKNOWN)
            if constant is _UNKNOWN:
                value_constants.pop(instruction.result.name, None)
                return instruction
            value_constants[instruction.result.name] = constant
            return IRConst(instruction.result, constant)

        self._forget_defined_value(instruction, value_constants)
        return instruction

    @staticmethod
    def _forget_defined_value(
        instruction: IRInstruction,
        value_constants: dict[str, Any],
    ) -> None:
        result = _instruction_result(instruction)
        if result is not None:
            value_constants.pop(result.name, None)


_UNKNOWN = object()


def _instruction_result(instruction: IRInstruction) -> IRValue | None:
    if isinstance(instruction, (IRBinaryOp, IRCompareOp)):
        return instruction.result
    if isinstance(instruction, IRCall):
        return instruction.result
    return None
