from __future__ import annotations

from aether.ir.model import (
    IRAssign,
    IRCopyInit,
    IRDestroy,
    IRInitDefault,
    IRBasicBlock,
    IRBranch,
    IRFunction,
    IRInstruction,
    IRJump,
    IRLoad,
    IRModule,
    IRReturn,
    IRStore,
    IRMoveInit,
    IRRelocate,
)

from .result import OptimizationResult


class DeadStoreEliminator:
    """Remove block-local stores whose written value is never loaded."""

    def run(self, module: IRModule) -> OptimizationResult:
        removed_stores = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized_function, function_removed = self._eliminate_function(function)
            functions.append(optimized_function)
            removed_stores += function_removed
        optimized = IRModule(functions, list(module.structs))
        return OptimizationResult(
            optimized,
            changed=optimized != module,
            stats={"removed_stores": removed_stores},
        )

    def _eliminate_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        if function.may_throw:
            return function, 0
        removed_stores = 0
        blocks: list[IRBasicBlock] = []
        for block in function.blocks:
            optimized_block, block_removed = self._eliminate_block(block)
            blocks.append(optimized_block)
            removed_stores += block_removed
        return (
            IRFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
                function.may_throw,
            ),
            removed_stores,
        )

    def _eliminate_block(self, block: IRBasicBlock) -> tuple[IRBasicBlock, int]:
        instructions: list[IRInstruction] = []
        removed_stores = 0
        for index, instruction in enumerate(block.instructions):
            if isinstance(instruction, IRStore) and self._is_dead_store(
                block.instructions,
                index,
                instruction,
            ):
                removed_stores += 1
                continue
            instructions.append(instruction)
        return IRBasicBlock(block.name, instructions), removed_stores

    def _is_dead_store(
        self,
        instructions: list[IRInstruction],
        index: int,
        store: IRStore,
    ) -> bool:
        for later in instructions[index + 1 :]:
            if isinstance(
                later,
                (IRInitDefault, IRCopyInit, IRMoveInit, IRAssign, IRDestroy, IRRelocate),
            ):
                return False
            if isinstance(later, IRLoad) and later.slot.name == store.slot.name:
                return False
            if isinstance(later, IRStore) and later.slot.name == store.slot.name:
                return True
            if isinstance(later, IRReturn):
                return True
            if isinstance(later, (IRBranch, IRJump)):
                return False

        return True
