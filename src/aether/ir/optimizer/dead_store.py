from __future__ import annotations

from aether.ir.model import (
    IRBasicBlock,
    IRBranch,
    IRFunction,
    IRInstruction,
    IRJump,
    IRLoad,
    IRModule,
    IRReturn,
    IRStore,
)

from .result import OptimizationResult


class DeadStoreEliminator:
    """Remove block-local stores whose written value is never loaded."""

    def run(self, module: IRModule) -> OptimizationResult:
        functions = [self._eliminate_function(function) for function in module.functions]
        optimized = IRModule(functions)
        return OptimizationResult(optimized, changed=optimized != module)

    def _eliminate_function(self, function: IRFunction) -> IRFunction:
        blocks = [self._eliminate_block(block) for block in function.blocks]
        return IRFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            blocks,
        )

    def _eliminate_block(self, block: IRBasicBlock) -> IRBasicBlock:
        instructions = [
            instruction
            for index, instruction in enumerate(block.instructions)
            if not isinstance(instruction, IRStore)
            or not self._is_dead_store(block.instructions, index, instruction)
        ]
        return IRBasicBlock(block.name, instructions)

    def _is_dead_store(
        self,
        instructions: list[IRInstruction],
        index: int,
        store: IRStore,
    ) -> bool:
        for later in instructions[index + 1 :]:
            if isinstance(later, IRLoad) and later.slot.name == store.slot.name:
                return False
            if isinstance(later, IRStore) and later.slot.name == store.slot.name:
                return True
            if isinstance(later, IRReturn):
                return True
            if isinstance(later, (IRBranch, IRJump)):
                return False

        return True
