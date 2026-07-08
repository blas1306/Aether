from __future__ import annotations

from aether.ir.model import (
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRJump,
    IRLoad,
    IRModule,
    IRReturn,
    IRStore,
    IRValue,
)

from .result import OptimizationResult


class DeadCodeEliminator:
    """Remove pure IR instructions whose result is not used."""

    _PURE_INSTRUCTIONS = (IRConst, IRBinaryOp, IRCompareOp, IRCast, IRLoad)

    def run(self, module: IRModule) -> OptimizationResult:
        removed = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized_function, function_removed = self._eliminate_function(function)
            functions.append(optimized_function)
            removed += function_removed
        optimized = IRModule(functions)
        return OptimizationResult(
            optimized,
            changed=optimized != module,
            stats={"removed": removed},
        )

    def _eliminate_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        producers = self._collect_pure_producers(function)
        live_values = self._initial_live_values(function)
        worklist = list(live_values)

        while worklist:
            value_name = worklist.pop()
            producer = producers.get(value_name)
            if producer is None:
                continue

            for operand in self._operands(producer):
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
            ),
            removed,
        )

    def _collect_pure_producers(
        self,
        function: IRFunction,
    ) -> dict[str, IRInstruction]:
        producers: dict[str, IRInstruction] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if self._is_removable(instruction):
                    producers[self._result(instruction).name] = instruction
        return producers

    def _initial_live_values(self, function: IRFunction) -> set[str]:
        live_values: set[str] = set()
        for block in function.blocks:
            for instruction in block.instructions:
                if self._is_removable(instruction):
                    continue
                live_values.update(
                    operand.name for operand in self._operands(instruction)
                )
        return live_values

    @classmethod
    def _is_removable(cls, instruction: IRInstruction) -> bool:
        return isinstance(instruction, cls._PURE_INSTRUCTIONS)

    @staticmethod
    def _result(instruction: IRInstruction) -> IRValue:
        if isinstance(instruction, (IRConst, IRLoad, IRBinaryOp, IRCompareOp, IRCast, IRArrayGet, IRArrayLength)):
            return instruction.result
        raise TypeError(
            f"Instruction has no removable result: {type(instruction).__name__}"
        )

    @staticmethod
    def _operands(instruction: IRInstruction) -> tuple[IRValue, ...]:
        if isinstance(instruction, IRConst):
            return ()
        if isinstance(instruction, IRLoad):
            return ()
        if isinstance(instruction, IRStore):
            return (instruction.value,)
        if isinstance(instruction, (IRBinaryOp, IRCompareOp)):
            return (instruction.left, instruction.right)
        if isinstance(instruction, IRCast):
            return (instruction.value,)
        if isinstance(instruction, IRCall):
            return instruction.arguments
        if isinstance(instruction, IRArrayNew):
            return instruction.elements
        if isinstance(instruction, IRArrayGet):
            return (instruction.array, instruction.index)
        if isinstance(instruction, IRArraySet):
            return (instruction.array, instruction.index, instruction.value)
        if isinstance(instruction, IRArrayLength):
            return (instruction.array,)
        if isinstance(instruction, IRBranch):
            return (instruction.condition,)
        if isinstance(instruction, IRJump):
            return ()
        if isinstance(instruction, IRReturn):
            return () if instruction.value is None else (instruction.value,)
        raise TypeError(
            f"Unsupported IR instruction: {type(instruction).__name__}"
        )
