from __future__ import annotations

from dataclasses import dataclass

from .cfg import CFG


@dataclass(frozen=True)
class DominatorResult:
    _dominators: dict[str, frozenset[str]]
    _immediate_dominators: dict[str, str | None]
    _dominator_tree_children: dict[str, frozenset[str]]
    _reachable: frozenset[str]

    def dominators(self, block_name: str) -> set[str]:
        return set(self._dominators[block_name])

    def dominates(self, dominator: str, block_name: str) -> bool:
        """Return whether ``dominator`` dominates ``block_name``.

        Unreachable blocks are represented as isolated roots, so only an
        unreachable block itself dominates that block.
        """
        return dominator in self._dominators[block_name]

    def strictly_dominates(self, dominator: str, block_name: str) -> bool:
        return dominator != block_name and self.dominates(dominator, block_name)

    def is_reachable(self, block_name: str) -> bool:
        return block_name in self._reachable

    def immediate_dominator(self, block_name: str) -> str | None:
        return self._immediate_dominators[block_name]

    def dominator_tree_children(self, block_name: str) -> set[str]:
        return set(self._dominator_tree_children[block_name])


class DominatorAnalysis:
    """Compute function-local dominators for a block-level CFG."""

    def __init__(self, cfg: CFG, *, entry_block: str | None = None) -> None:
        self._cfg = cfg
        self._entry_block = entry_block

    def compute(self) -> DominatorResult:
        block_names = tuple(node.name for node in self._cfg.nodes)
        if not block_names:
            return DominatorResult({}, {}, {}, frozenset())

        entry = self._entry_block or block_names[0]
        block_set = set(block_names)
        if entry not in block_set:
            raise ValueError(
                f"Dominator entry block '{entry}' is not present in the CFG"
            )
        predecessors = self._predecessors(block_set)
        reachable = self._reachable(entry, block_set)

        dominators = self._compute_dominators(
            block_names, predecessors, reachable
        )
        block_indexes = {
            block_name: index for index, block_name in enumerate(block_names)
        }
        immediate_dominators = self._compute_immediate_dominators(
            block_names, block_indexes, dominators, reachable
        )
        tree_children = self._compute_tree_children(block_names, immediate_dominators)

        return DominatorResult(
            dominators,
            immediate_dominators,
            tree_children,
            frozenset(reachable),
        )

    def _predecessors(self, block_set: set[str]) -> dict[str, set[str]]:
        predecessors = {block_name: set() for block_name in block_set}
        for edge in self._cfg.edges:
            if edge.source in block_set and edge.target in block_set:
                predecessors[edge.target].add(edge.source)
        return predecessors

    def _reachable(self, entry: str, block_set: set[str]) -> set[str]:
        successors = {block_name: set() for block_name in block_set}
        for edge in self._cfg.edges:
            if edge.source in block_set and edge.target in block_set:
                successors[edge.source].add(edge.target)

        reachable: set[str] = set()
        worklist = [entry]
        while worklist:
            block_name = worklist.pop()
            if block_name in reachable:
                continue
            reachable.add(block_name)
            worklist.extend(successors[block_name] - reachable)
        return reachable

    def _compute_dominators(
        self,
        block_names: tuple[str, ...],
        predecessors: dict[str, set[str]],
        reachable: set[str],
    ) -> dict[str, frozenset[str]]:
        entry = self._entry_block or block_names[0]
        dominators: dict[str, set[str]] = {}
        for block_name in block_names:
            if block_name == entry:
                dominators[block_name] = {block_name}
            elif block_name in reachable:
                dominators[block_name] = set(reachable)
            else:
                dominators[block_name] = {block_name}

        changed = True
        while changed:
            changed = False

            for block_name in block_names:
                if block_name == entry or block_name not in reachable:
                    continue

                predecessor_dominators = [
                    dominators[predecessor]
                    for predecessor in predecessors[block_name]
                    if predecessor in reachable
                ]
                if predecessor_dominators:
                    new_dominators = set.intersection(*predecessor_dominators)
                else:
                    new_dominators = set()
                new_dominators.add(block_name)

                if new_dominators != dominators[block_name]:
                    dominators[block_name] = new_dominators
                    changed = True

        return {
            block_name: frozenset(dominators[block_name]) for block_name in block_names
        }

    def _compute_immediate_dominators(
        self,
        block_names: tuple[str, ...],
        block_indexes: dict[str, int],
        dominators: dict[str, frozenset[str]],
        reachable: set[str],
    ) -> dict[str, str | None]:
        entry = self._entry_block or block_names[0]
        immediate_dominators: dict[str, str | None] = {}

        for block_name in block_names:
            if block_name == entry or block_name not in reachable:
                immediate_dominators[block_name] = None
                continue

            strict_dominators = dominators[block_name] - {block_name}
            immediate_dominators[block_name] = max(
                strict_dominators,
                key=lambda dominator: (
                    len(dominators[dominator]),
                    block_indexes[dominator],
                ),
                default=None,
            )

        return immediate_dominators

    def _compute_tree_children(
        self,
        block_names: tuple[str, ...],
        immediate_dominators: dict[str, str | None],
    ) -> dict[str, frozenset[str]]:
        tree_children = {block_name: set() for block_name in block_names}
        for block_name in block_names:
            immediate_dominator = immediate_dominators[block_name]
            if immediate_dominator is not None:
                tree_children[immediate_dominator].add(block_name)

        return {
            block_name: frozenset(children)
            for block_name, children in tree_children.items()
        }
