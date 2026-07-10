from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from aether.analysis.cfg import CFG
from aether.analysis.dominance_frontier import DominanceFrontierResult
from aether.analysis.dominators import DominatorResult
from aether.ir.model import IRFunction, IRLoad, IRStore


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
        live_in = self._live_in_slots()
        initialized_in = self._initialized_in_slots()
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
                    if (
                        slot_name not in live_in.get(frontier_block, set())
                        and slot_name not in initialized_in.get(frontier_block, set())
                    ):
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

    def _live_in_slots(self) -> dict[str, set[str]]:
        blocks = {block.name: block for block in self.function.blocks}
        cfg_blocks = {node.name for node in self.cfg.nodes}
        successors: dict[str, set[str]] = {block_name: set() for block_name in cfg_blocks}
        for edge in self.cfg.edges:
            successors.setdefault(edge.source, set()).add(edge.target)

        uses_before_def: dict[str, set[str]] = {}
        definitions: dict[str, set[str]] = {}
        for block_name in cfg_blocks:
            block = blocks[block_name]
            block_uses: set[str] = set()
            block_defs: set[str] = set()
            for instruction in block.instructions:
                if isinstance(instruction, IRLoad) and instruction.slot.name not in block_defs:
                    block_uses.add(instruction.slot.name)
                elif isinstance(instruction, IRStore):
                    block_defs.add(instruction.slot.name)
            uses_before_def[block_name] = block_uses
            definitions[block_name] = block_defs

        live_in: dict[str, set[str]] = {block_name: set() for block_name in cfg_blocks}
        live_out: dict[str, set[str]] = {block_name: set() for block_name in cfg_blocks}

        changed = True
        while changed:
            changed = False
            for block_name in reversed(tuple(cfg_blocks)):
                new_out: set[str] = set()
                for successor in successors.get(block_name, set()):
                    new_out.update(live_in.get(successor, set()))
                new_in = uses_before_def[block_name] | (new_out - definitions[block_name])
                if new_out != live_out[block_name] or new_in != live_in[block_name]:
                    live_out[block_name] = new_out
                    live_in[block_name] = new_in
                    changed = True

        return live_in

    def _initialized_in_slots(self) -> dict[str, set[str]]:
        cfg_blocks = {node.name for node in self.cfg.nodes}
        predecessors: dict[str, set[str]] = {block_name: set() for block_name in cfg_blocks}
        for edge in self.cfg.edges:
            predecessors.setdefault(edge.target, set()).add(edge.source)

        definitions = self._block_definitions(cfg_blocks)
        all_slots = set().union(*definitions.values()) if definitions else set()
        initialized_in: dict[str, set[str]] = {}
        initialized_out: dict[str, set[str]] = {}
        for block_name in cfg_blocks:
            initialized_in[block_name] = set()
            initialized_out[block_name] = set(definitions.get(block_name, set()))

        changed = True
        while changed:
            changed = False
            for block_name in reversed(tuple(cfg_blocks)):
                preds = predecessors.get(block_name, set())
                if not preds:
                    new_in: set[str] = set()
                else:
                    new_in = set(all_slots)
                    for predecessor in preds:
                        new_in &= initialized_out.get(predecessor, set())
                new_out = new_in | definitions.get(block_name, set())
                if new_in != initialized_in[block_name] or new_out != initialized_out[block_name]:
                    initialized_in[block_name] = new_in
                    initialized_out[block_name] = new_out
                    changed = True

        return initialized_in

    def _block_definitions(self, cfg_blocks: set[str]) -> dict[str, set[str]]:
        blocks = {block.name: block for block in self.function.blocks}
        definitions: dict[str, set[str]] = {}
        for block_name in cfg_blocks:
            block_defs: set[str] = set()
            for instruction in blocks[block_name].instructions:
                if isinstance(instruction, IRStore):
                    block_defs.add(instruction.slot.name)
            definitions[block_name] = block_defs
        return definitions
