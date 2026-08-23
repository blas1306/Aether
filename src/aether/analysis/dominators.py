from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import MutableMapping

from .cfg import CFG


@dataclass(frozen=True)
class DominatorResult:
    """Function-local dominance represented as compilation-local bit masks.

    Public queries continue to use block names. Integer indexes never escape
    this result and are derived solely from Python CFG source order.
    """

    _block_names: tuple[str, ...]
    _block_indexes: dict[str, int]
    _dominator_masks: tuple[int, ...]
    _immediate_dominators: dict[str, str | None]
    _dominator_tree_children: dict[str, frozenset[str]]
    _reachable_mask: int

    def dominators(self, block_name: str) -> set[str]:
        mask = self._dominator_masks[self._block_indexes[block_name]]
        return {
            name
            for index, name in enumerate(self._block_names)
            if mask & (1 << index)
        }

    def dominates(self, dominator: str, block_name: str) -> bool:
        """Return whether ``dominator`` dominates ``block_name``.

        Unreachable blocks are represented as isolated roots, so only an
        unreachable block itself dominates that block.
        """
        dominator_index = self._block_indexes[dominator]
        block_index = self._block_indexes[block_name]
        return bool(self._dominator_masks[block_index] & (1 << dominator_index))

    def strictly_dominates(self, dominator: str, block_name: str) -> bool:
        return dominator != block_name and self.dominates(dominator, block_name)

    def is_reachable(self, block_name: str) -> bool:
        return bool(self._reachable_mask & (1 << self._block_indexes[block_name]))

    def immediate_dominator(self, block_name: str) -> str | None:
        return self._immediate_dominators[block_name]

    def dominator_tree_children(self, block_name: str) -> set[str]:
        return set(self._dominator_tree_children[block_name])

    def dominator_tree_children_view(self, block_name: str) -> frozenset[str]:
        """Return an immutable internal view without cloning the child set."""
        return self._dominator_tree_children[block_name]


@dataclass(frozen=True)
class ReferenceDominatorResult:
    """Exact pre-RUST-3.11 result representation for qualification only."""

    _dominators: dict[str, frozenset[str]]
    _immediate_dominators: dict[str, str | None]
    _dominator_tree_children: dict[str, frozenset[str]]
    _reachable: frozenset[str]

    def dominators(self, block_name: str) -> set[str]:
        return set(self._dominators[block_name])

    def dominates(self, dominator: str, block_name: str) -> bool:
        return dominator in self._dominators[block_name]

    def strictly_dominates(self, dominator: str, block_name: str) -> bool:
        return dominator != block_name and self.dominates(dominator, block_name)

    def is_reachable(self, block_name: str) -> bool:
        return block_name in self._reachable

    def immediate_dominator(self, block_name: str) -> str | None:
        return self._immediate_dominators[block_name]

    def dominator_tree_children(self, block_name: str) -> set[str]:
        return set(self._dominator_tree_children[block_name])

    def dominator_tree_children_view(self, block_name: str) -> frozenset[str]:
        return self._dominator_tree_children[block_name]


class DominatorAnalysis:
    """Compute dominators with independent full-set dataflow over bit masks.

    Rust uses Cooper-Harvey-Kennedy immediate dominators. This Python oracle
    deliberately retains the original iterative full-dominator-set equations;
    only the set representation and immediate-dominator lookup are compacted.
    """

    def __init__(
        self,
        cfg: CFG,
        *,
        entry_block: str | None = None,
        performance_timings: MutableMapping[str, float] | None = None,
    ) -> None:
        self._cfg = cfg
        self._entry_block = entry_block
        self._performance_timings = performance_timings

    def compute(self) -> DominatorResult:
        block_names = tuple(node.name for node in self._cfg.nodes)
        block_indexes = {
            block_name: index for index, block_name in enumerate(block_names)
        }
        if not block_names:
            return DominatorResult((), {}, (), {}, {}, 0)

        entry = self._entry_block or block_names[0]
        if entry not in block_indexes:
            raise ValueError(
                f"Dominator entry block '{entry}' is not present in the CFG"
            )

        started = perf_counter() if self._performance_timings is not None else 0.0
        predecessors, successors = self._indexed_edges(block_indexes)
        self._record("python_cfg_indexing", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
        reachable_mask = self._reachable_mask(block_indexes[entry], successors)
        self._record("python_reachability", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
        dominator_masks = self._compute_dominator_masks(
            block_indexes[entry], predecessors, reachable_mask
        )
        self._record("python_dominator_computation", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
        immediate_dominators = self._compute_immediate_dominators(
            block_names,
            block_indexes[entry],
            dominator_masks,
            reachable_mask,
        )
        self._record("python_immediate_dominator_derivation", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
        tree_children = self._compute_tree_children(block_names, immediate_dominators)
        self._record("python_dominator_tree", started)

        return DominatorResult(
            block_names,
            block_indexes,
            tuple(dominator_masks),
            immediate_dominators,
            tree_children,
            reachable_mask,
        )

    def _indexed_edges(
        self, block_indexes: dict[str, int]
    ) -> tuple[list[list[int]], list[list[int]]]:
        predecessors = [[] for _ in block_indexes]
        successors = [[] for _ in block_indexes]
        for edge in self._cfg.edges:
            source = block_indexes.get(edge.source)
            target = block_indexes.get(edge.target)
            if source is not None and target is not None:
                predecessors[target].append(source)
                successors[source].append(target)
        return predecessors, successors

    @staticmethod
    def _reachable_mask(entry_index: int, successors: list[list[int]]) -> int:
        reachable_mask = 0
        worklist = [entry_index]
        while worklist:
            block_index = worklist.pop()
            block_bit = 1 << block_index
            if reachable_mask & block_bit:
                continue
            reachable_mask |= block_bit
            worklist.extend(successors[block_index])
        return reachable_mask

    @staticmethod
    def _compute_dominator_masks(
        entry_index: int,
        predecessors: list[list[int]],
        reachable_mask: int,
    ) -> list[int]:
        dominators = [
            (1 << index)
            if index == entry_index or not reachable_mask & (1 << index)
            else reachable_mask
            for index in range(len(predecessors))
        ]

        changed = True
        while changed:
            changed = False
            for block_index, block_predecessors in enumerate(predecessors):
                block_bit = 1 << block_index
                if block_index == entry_index or not reachable_mask & block_bit:
                    continue

                new_dominators = reachable_mask
                has_reachable_predecessor = False
                for predecessor in block_predecessors:
                    if reachable_mask & (1 << predecessor):
                        has_reachable_predecessor = True
                        new_dominators &= dominators[predecessor]
                if not has_reachable_predecessor:
                    new_dominators = 0
                new_dominators |= block_bit

                if new_dominators != dominators[block_index]:
                    dominators[block_index] = new_dominators
                    changed = True
        return dominators

    @staticmethod
    def _compute_immediate_dominators(
        block_names: tuple[str, ...],
        entry_index: int,
        dominators: list[int],
        reachable_mask: int,
    ) -> dict[str, str | None]:
        # In a dominator tree, a node with d dominators has an immediate
        # dominator with d-1 dominators. Bucket nodes by that depth, then use
        # one bit intersection per block instead of enumerating every strict
        # dominator. Highest source index preserves the old deterministic
        # tie-break if malformed input ever presents more than one candidate.
        depth_masks: dict[int, int] = {}
        for index, mask in enumerate(dominators):
            if reachable_mask & (1 << index):
                depth = mask.bit_count()
                depth_masks[depth] = depth_masks.get(depth, 0) | (1 << index)

        immediate_dominators: dict[str, str | None] = {}
        for index, block_name in enumerate(block_names):
            block_bit = 1 << index
            if index == entry_index or not reachable_mask & block_bit:
                immediate_dominators[block_name] = None
                continue

            mask = dominators[index]
            candidates = (mask ^ block_bit) & depth_masks.get(mask.bit_count() - 1, 0)
            if not candidates:
                immediate_dominators[block_name] = None
                continue
            candidate_index = candidates.bit_length() - 1
            immediate_dominators[block_name] = block_names[candidate_index]
        return immediate_dominators

    @staticmethod
    def _compute_tree_children(
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

    def _record(self, phase: str, started: float) -> None:
        if self._performance_timings is not None:
            self._performance_timings[phase] = (
                self._performance_timings.get(phase, 0.0)
                + perf_counter()
                - started
            )


class ReferenceDominatorAnalysis:
    """Frozen pre-RUST-3.11 set implementation for differential qualification."""

    def __init__(
        self,
        cfg: CFG,
        *,
        entry_block: str | None = None,
        performance_timings: MutableMapping[str, float] | None = None,
    ) -> None:
        self._cfg = cfg
        self._entry_block = entry_block
        self._performance_timings = performance_timings

    def compute(self) -> DominatorResult | ReferenceDominatorResult:
        block_names = tuple(node.name for node in self._cfg.nodes)
        block_indexes = {
            block_name: index for index, block_name in enumerate(block_names)
        }
        if not block_names:
            return ReferenceDominatorResult({}, {}, {}, frozenset())

        entry = self._entry_block or block_names[0]
        if entry not in block_indexes:
            raise ValueError(
                f"Dominator entry block '{entry}' is not present in the CFG"
            )
        started = perf_counter() if self._performance_timings is not None else 0.0
        block_set = set(block_names)
        predecessors = {block_name: set() for block_name in block_set}
        successors = {block_name: set() for block_name in block_set}
        for edge in self._cfg.edges:
            if edge.source in block_set and edge.target in block_set:
                predecessors[edge.target].add(edge.source)
                successors[edge.source].add(edge.target)
        self._record("python_cfg_indexing", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
        reachable: set[str] = set()
        worklist = [entry]
        while worklist:
            block_name = worklist.pop()
            if block_name in reachable:
                continue
            reachable.add(block_name)
            worklist.extend(successors[block_name] - reachable)
        self._record("python_reachability", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
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
                new_dominators = (
                    set.intersection(*predecessor_dominators)
                    if predecessor_dominators
                    else set()
                )
                new_dominators.add(block_name)
                if new_dominators != dominators[block_name]:
                    dominators[block_name] = new_dominators
                    changed = True
        self._record("python_dominator_computation", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
        immediate_dominators: dict[str, str | None] = {}
        for block_name in block_names:
            if block_name == entry or block_name not in reachable:
                immediate_dominators[block_name] = None
                continue
            strict = dominators[block_name] - {block_name}
            immediate_dominators[block_name] = max(
                strict,
                key=lambda candidate: (
                    len(dominators[candidate]), block_indexes[candidate]
                ),
                default=None,
            )
        self._record("python_immediate_dominator_derivation", started)

        started = perf_counter() if self._performance_timings is not None else 0.0
        tree_children = DominatorAnalysis._compute_tree_children(
            block_names, immediate_dominators
        )
        self._record("python_dominator_tree", started)
        return ReferenceDominatorResult(
            {
                block_name: frozenset(dominators[block_name])
                for block_name in block_names
            },
            immediate_dominators,
            tree_children,
            frozenset(reachable),
        )

    def _record(self, phase: str, started: float) -> None:
        if self._performance_timings is not None:
            self._performance_timings[phase] = (
                self._performance_timings.get(phase, 0.0)
                + perf_counter()
                - started
            )
