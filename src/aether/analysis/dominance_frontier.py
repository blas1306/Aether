from __future__ import annotations

from dataclasses import dataclass

from .cfg import CFG
from .dominators import DominatorResult


@dataclass(frozen=True)
class DominanceFrontierResult:
    _frontiers: dict[str, frozenset[str]]

    def frontier(self, block_name: str) -> set[str]:
        return set(self._frontiers[block_name])

    def frontier_view(self, block_name: str) -> frozenset[str]:
        """Return an immutable view for hot internal consumers."""
        return self._frontiers[block_name]


class DominanceFrontierAnalysis:
    """Compute function-local dominance frontiers for a block-level CFG."""

    def __init__(self, cfg: CFG, dominators: DominatorResult) -> None:
        self._cfg = cfg
        self._dominators = dominators

    def compute(self) -> DominanceFrontierResult:
        block_names = tuple(node.name for node in self._cfg.nodes)
        block_set = set(block_names)
        frontiers = {block_name: set() for block_name in block_names}

        if not block_names:
            return DominanceFrontierResult({})

        predecessors = self._predecessors(block_set)

        for block_name in block_names:
            if (
                not self._dominators.is_reachable(block_name)
                or len(predecessors[block_name]) < 2
            ):
                continue

            stop = self._dominators.immediate_dominator(block_name)
            if stop is None:
                continue

            for predecessor in predecessors[block_name]:
                if not self._dominators.is_reachable(predecessor):
                    continue

                runner: str | None = predecessor
                while runner is not None and runner != stop:
                    frontiers[runner].add(block_name)
                    runner = self._dominators.immediate_dominator(runner)

        return DominanceFrontierResult(
            {
                block_name: frozenset(frontiers[block_name])
                for block_name in block_names
            }
        )

    def _predecessors(self, block_set: set[str]) -> dict[str, set[str]]:
        predecessors = {block_name: set() for block_name in block_set}
        for edge in self._cfg.edges:
            if edge.source in block_set and edge.target in block_set:
                predecessors[edge.target].add(edge.source)
        return predecessors
