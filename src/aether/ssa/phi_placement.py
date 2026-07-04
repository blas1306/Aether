from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from aether.analysis.cfg import CFG
from aether.analysis.dominance_frontier import DominanceFrontierResult
from aether.analysis.dominators import DominatorResult
from aether.ir.model import IRFunction, IRStore


@dataclass(frozen=True)
class PhiPlacement:
    """Compute Cytron-style phi insertion points for mutable IR slots.

    This phase only records where phi placeholders are needed. It does not
    create SSA instructions and does not perform variable renaming.
    """

    function: IRFunction
    cfg: CFG
    dominators: DominatorResult
    dominance_frontier: DominanceFrontierResult

    def place(self) -> dict[str, set[str]]:
        definition_blocks = self._definition_blocks()
        placements: dict[str, set[str]] = {}

        for slot_name, initial_blocks in definition_blocks.items():
            placed_blocks: set[str] = set()
            seen_definitions = set(initial_blocks)
            worklist = deque(initial_blocks)

            while worklist:
                block_name = worklist.popleft()

                for frontier_block in self.dominance_frontier.frontier(block_name):
                    if frontier_block in placed_blocks:
                        continue

                    placed_blocks.add(frontier_block)

                    if frontier_block not in seen_definitions:
                        seen_definitions.add(frontier_block)
                        worklist.append(frontier_block)

            if placed_blocks:
                placements[slot_name] = placed_blocks

        return placements

    def _definition_blocks(self) -> dict[str, set[str]]:
        cfg_blocks = {node.name for node in self.cfg.nodes}
        definitions: dict[str, set[str]] = {}

        for block in self.function.blocks:
            if block.name not in cfg_blocks:
                continue

            for instruction in block.instructions:
                if isinstance(instruction, IRStore):
                    definitions.setdefault(instruction.slot.name, set()).add(block.name)

        return definitions
