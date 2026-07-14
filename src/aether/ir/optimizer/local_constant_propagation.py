from __future__ import annotations

from dataclasses import replace
from typing import Any

from aether.ir.model import (
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInstruction,
    IRLoad,
    IRModule,
    IRStore,
    IRValue,
)

from .result import OptimizationResult


class LocalConstantPropagator:
    """Replace same-block loads from known constant slots with constants."""

    def run(self, module: IRModule) -> OptimizationResult:
        propagated = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized_function, function_propagated = self._propagate_function(function)
            functions.append(optimized_function)
            propagated += function_propagated
        optimized = IRModule(functions, list(module.structs))
        return OptimizationResult(
            optimized,
            changed=optimized != module,
            stats={"propagated": propagated},
        )

    def _propagate_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        propagated = 0
        blocks: list[IRBasicBlock] = []
        for block in function.blocks:
            optimized_block, block_propagated = self._propagate_block(block)
            blocks.append(optimized_block)
            propagated += block_propagated
        return (
            IRFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
            ),
            propagated,
        )

    def _propagate_block(self, block: IRBasicBlock) -> tuple[IRBasicBlock, int]:
        value_constants: dict[str, Any] = {}
        slot_constants: dict[str, Any] = {}
        instructions: list[IRInstruction] = []
        propagated_count = 0

        for instruction in block.instructions:
            propagated, did_propagate = self._propagate_instruction(
                instruction,
                value_constants,
                slot_constants,
            )
            instructions.append(propagated)
            if did_propagate:
                propagated_count += 1

        return IRBasicBlock(block.name, instructions), propagated_count

    def _propagate_instruction(
        self,
        instruction: IRInstruction,
        value_constants: dict[str, Any],
        slot_constants: dict[str, Any],
    ) -> tuple[IRInstruction, bool]:
        if isinstance(instruction, IRConst):
            value_constants[instruction.result.name] = instruction.value
            return replace(instruction), False

        if isinstance(instruction, IRStore):
            constant = value_constants.get(instruction.value.name, _UNKNOWN)
            if constant is _UNKNOWN:
                slot_constants.pop(instruction.slot.name, None)
            else:
                slot_constants[instruction.slot.name] = constant
            return instruction, False

        if isinstance(instruction, IRLoad):
            constant = slot_constants.get(instruction.slot.name, _UNKNOWN)
            if constant is _UNKNOWN:
                value_constants.pop(instruction.result.name, None)
                return instruction, False
            value_constants[instruction.result.name] = constant
            return IRConst(instruction.result, constant), True

        self._forget_defined_value(instruction, value_constants)
        return instruction, False

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
    result = getattr(instruction, "result", None)
    return result if isinstance(result, IRValue) else None
