from __future__ import annotations

from aether.ir.model import (
    IRBasicBlock,
    IRFunction,
    IRInstruction,
    IRModule,
    IRValue,
)
from aether.ir.operands import instruction_operands, instruction_result

from .result import OptimizationResult


class DeadCodeEliminator:
    """Remove pure IR instructions whose result is not transitively live."""

    def run(self, module: IRModule) -> OptimizationResult:
        removed = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized_function, function_removed = self._eliminate_function(function)
            functions.append(optimized_function)
            removed += function_removed
        optimized = IRModule(functions, list(module.structs))
        return OptimizationResult(
            optimized,
            changed=optimized != module,
            stats={"removed": removed},
        )

    def _eliminate_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        producers = {
            self._result(instruction).name: instruction
            for block in function.blocks
            for instruction in block.instructions
            if self._is_removable(instruction)
        }
        live_values = {
            operand.name
            for block in function.blocks
            for instruction in block.instructions
            if not self._is_removable(instruction)
            for operand in instruction_operands(instruction)
        }
        worklist = list(live_values)
        while worklist:
            producer = producers.get(worklist.pop())
            if producer is None:
                continue
            for operand in instruction_operands(producer):
                if operand.name not in live_values:
                    live_values.add(operand.name)
                    worklist.append(operand.name)

        removed = 0
        blocks: list[IRBasicBlock] = []
        for block in function.blocks:
            instructions: list[IRInstruction] = []
            for instruction in block.instructions:
                if (
                    self._is_removable(instruction)
                    and self._result(instruction).name not in live_values
                ):
                    removed += 1
                    continue
                instructions.append(instruction)
            blocks.append(IRBasicBlock(block.name, instructions))
        return (
            IRFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
                function.may_throw,
            ),
            removed,
        )

    @staticmethod
    def _is_removable(instruction: IRInstruction) -> bool:
        return (
            instruction_result(instruction) is not None
            and not instruction.must_preserve
        )

    @staticmethod
    def _result(instruction: IRInstruction) -> IRValue:
        result = instruction_result(instruction)
        if result is None:
            raise TypeError(
                f"Instruction has no removable result: {type(instruction).__name__}"
            )
        return result
