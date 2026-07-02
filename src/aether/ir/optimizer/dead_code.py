from __future__ import annotations

from aether.ir.model import (
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
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

    _PURE_INSTRUCTIONS = (IRConst, IRBinaryOp, IRCompareOp, IRLoad)

    def run(self, module: IRModule) -> OptimizationResult:
        functions = [self._eliminate_function(function) for function in module.functions]
        optimized = IRModule(functions)
        return OptimizationResult(optimized, changed=optimized != module)

    def _eliminate_function(self, function: IRFunction) -> IRFunction:
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

        blocks = [
            IRBasicBlock(
                block.name,
                [
                    instruction
                    for instruction in block.instructions
                    if not self._is_removable(instruction)
                    or self._result(instruction).name in live_values
                ],
            )
            for block in function.blocks
        ]

        return IRFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            blocks,
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
        if isinstance(instruction, (IRConst, IRLoad, IRBinaryOp, IRCompareOp)):
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
        if isinstance(instruction, IRCall):
            return instruction.arguments
        if isinstance(instruction, IRBranch):
            return (instruction.condition,)
        if isinstance(instruction, IRJump):
            return ()
        if isinstance(instruction, IRReturn):
            return () if instruction.value is None else (instruction.value,)
        raise TypeError(
            f"Unsupported IR instruction: {type(instruction).__name__}"
        )
