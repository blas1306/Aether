"""O2.9 Phase-1 elimination of strictly local, proven ARC pairs."""
from __future__ import annotations

from collections import Counter

from aether.analysis.dominators import DominatorAnalysis
from aether.ssa import model as m
from aether.ssa.cfg import SSACFGBuilder, predecessors, successor_edges
from aether.ssa.analysis import (
    ArcPairClassification, ArcPairSemanticReason, OwnershipEscapeAnalysis,
    OwnershipUnknownReason, PostDominatorAnalysis,
    has_unsupported_nested_owned_payload,
)

from .result import SSAOptimizationResult


_CALLS = (
    m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
    m.SSAInterfaceCall, m.SSAInvokeInterface,
)
_EXCEPTION_OPERATIONS = (
    m.SSAInvoke, m.SSAInvokeIndirect, m.SSAInvokeInterface,
    m.SSAPackException, m.SSACatchEntry, m.SSAExceptionDestroy,
    m.SSAThrow, m.SSARethrow, m.SSAPropagate,
)
_STORES = (
    m.SSAClassSet, m.SSAArraySet, m.SSAListSet, m.SSAListPush,
    m.SSAListInsert, m.SSAStructSet,
)
_METHOD_RESULT = (
    m.SSAMethodResultNew, m.SSAMethodResultReceiver, m.SSAMethodResultValue,
)


class LocalARCEliminator:
    """Remove proven same-block and straight-line multi-block ARC pairs."""

    _STAT_KEYS = (
        "retain_instructions_examined", "candidate_pairs",
        "phase1_eligible_pairs", "pairs_eliminated",
        "same_block_candidates", "same_block_eliminated",
        "multi_block_candidates", "multi_block_eliminated",
        "blocked_by_nonunique_path", "blocked_by_branch", "blocked_by_join",
        "blocked_by_missing_dominance", "blocked_by_missing_post_dominance",
        "blocked_by_loop_backedge",
        "blocked_by_ownership_interference",
        "blocked_by_unsupported_ownership_category",
        "blocked_by_different_identity", "blocked_by_call",
        "blocked_by_escape", "blocked_by_ownership_operation",
        "blocked_by_exception", "blocked_by_aggregate",
        "blocked_by_methodresult_constructor", "blocked_by_interface",
        "blocked_by_unsupported_structure",
    )

    def run(self, module: m.SSAModule) -> SSAOptimizationResult:
        stats: Counter[str] = Counter({key: 0 for key in self._STAT_KEYS})
        functions: list[m.SSAFunction] = []
        changed = False
        for function in module.functions:
            rewritten, removed = self._run_function(function, stats)
            functions.append(rewritten)
            changed |= bool(removed)
        optimized = m.SSAModule(functions, list(module.structs)) if changed else module
        return SSAOptimizationResult(optimized, changed, dict(stats))

    def _run_function(self, function: m.SSAFunction, stats: Counter[str]):
        analysis = OwnershipEscapeAnalysis(function)
        analysis.verify()
        dominators = DominatorAnalysis(
            SSACFGBuilder().build(function), entry_block=function.entry_block,
        ).compute()
        postdominators = PostDominatorAnalysis(function)
        stats["retain_instructions_examined"] += sum(
            isinstance(i, (m.SSACall, m.SSAInvoke))
            and i.builtin == "__aether_retain"
            for block in function.blocks for i in block.instructions
        )
        pairs = analysis.candidate_arc_pairs()
        stats["candidate_pairs"] += len(pairs)
        blocks = {block.name: block for block in function.blocks}
        removals: dict[str, set[int]] = {}
        for pair in pairs:
            multi_block = pair.retain_block != pair.release_block
            stats["multi_block_candidates" if multi_block else "same_block_candidates"] += 1
            reason = self._blocked_reason(
                function, blocks, analysis, pair, dominators, postdominators,
            )
            if reason is not None:
                stats[reason] += 1
                if reason == "blocked_by_ownership_operation":
                    stats["blocked_by_ownership_interference"] += 1
                if reason in {
                    "blocked_by_aggregate", "blocked_by_methodresult_constructor",
                    "blocked_by_interface",
                }:
                    stats["blocked_by_unsupported_ownership_category"] += 1
                continue
            if not multi_block:
                stats["phase1_eligible_pairs"] += 1
            # Assertions make the proof boundary explicit in debug/test runs.
            assert analysis.classify_pair(pair) is ArcPairClassification.LOCALLY_PROVABLE
            assert (pair.retain_block != pair.release_block
                    or pair.retain_index < pair.release_index)
            retain_selected = removals.setdefault(pair.retain_block, set())
            release_selected = removals.setdefault(pair.release_block, set())
            if (pair.retain_index in retain_selected
                    or pair.release_index in release_selected):
                stats["blocked_by_ownership_operation"] += 1
                stats["blocked_by_ownership_interference"] += 1
                if not multi_block:
                    stats["phase1_eligible_pairs"] -= 1
                continue
            retain_selected.add(pair.retain_index)
            release_selected.add(pair.release_index)
            stats["pairs_eliminated"] += 1
            stats["multi_block_eliminated" if multi_block else "same_block_eliminated"] += 1

        if not removals:
            return function, 0
        new_blocks = [m.SSABasicBlock(
            block.name,
            [instruction for index, instruction in enumerate(block.instructions)
             if index not in removals.get(block.name, set())],
        ) for block in function.blocks]
        rewritten = m.SSAFunction(
            function.name, list(function.parameters), function.return_type,
            new_blocks, function.entry_block, function.may_throw,
        )
        return rewritten, sum(map(len, removals.values())) // 2

    def classify_candidate(self, function: m.SSAFunction,
                           analysis: OwnershipEscapeAnalysis, pair) -> str | None:
        """Return the productive pass rejection reason, or ``None``."""
        blocks = {block.name: block for block in function.blocks}
        dominators = DominatorAnalysis(
            SSACFGBuilder().build(function), entry_block=function.entry_block,
        ).compute()
        postdominators = PostDominatorAnalysis(function)
        return self._blocked_reason(function, blocks, analysis, pair,
                                    dominators, postdominators)

    def is_same_block_phase1_eligible(self, function, analysis, pair) -> bool:
        return (pair.retain_block == pair.release_block
                and self.classify_candidate(function, analysis, pair) is None)

    def is_linear_multiblock_phase2_eligible(self, function, analysis, pair) -> bool:
        return (pair.retain_block != pair.release_block
                and self.classify_candidate(function, analysis, pair) is None)

    def _blocked_reason(self, function, blocks, analysis, pair,
                        dominators, postdominators) -> str | None:
        if pair.retain_block == pair.release_block and pair.retain_index >= pair.release_index:
            return "blocked_by_unsupported_structure"
        semantic = analysis.classify_arc_pair(pair)
        # O2.8.8 is an analysis-only qualification milestone.  Keep every
        # candidate whose new proof depends on aggregate precision frozen until
        # a later production-activation milestone audits it explicitly.
        if has_unsupported_nested_owned_payload(pair.value.type):
            return "blocked_by_aggregate"
        if not semantic.semantically_provable:
            reasons = semantic.reasons
            if ArcPairSemanticReason.PROVENANCE_UNKNOWN in reasons:
                return "blocked_by_different_identity"
            if ArcPairSemanticReason.INTERFACE in reasons:
                return "blocked_by_interface"
            if ArcPairSemanticReason.NESTED_AGGREGATE in reasons:
                return "blocked_by_aggregate"
            if reasons & {ArcPairSemanticReason.METHODRESULT,
                          ArcPairSemanticReason.CONSTRUCTOR_LIFECYCLE}:
                return "blocked_by_methodresult_constructor"
            if ArcPairSemanticReason.EXCEPTION_LIFETIME in reasons:
                return "blocked_by_exception"
            if ArcPairSemanticReason.ESCAPE in reasons:
                if semantic.escape and semantic.escape.reasons & {
                    OwnershipUnknownReason.UNKNOWN_CALL_ESCAPE,
                    OwnershipUnknownReason.INDIRECT_CALL_ESCAPE,
                }:
                    return "blocked_by_call"
                return "blocked_by_escape"
            if ArcPairSemanticReason.OWNERSHIP_CONFLICT in reasons:
                return "blocked_by_ownership_operation"
            return "blocked_by_unsupported_structure"

        if pair.retain_block == pair.release_block:
            region = blocks[pair.retain_block].instructions[
                pair.retain_index + 1:pair.release_index
            ]
        else:
            if not dominators.dominates(pair.retain_block, pair.release_block):
                return "blocked_by_missing_dominance"
            if not postdominators.post_dominates(pair.release_block, pair.retain_block):
                return "blocked_by_missing_post_dominance"
            path, reason = self._straight_line_path(function, blocks, pair)
            if reason is not None:
                return reason
            assert path is not None
            region = []
            for index, name in enumerate(path):
                instructions = blocks[name].instructions
                start = pair.retain_index + 1 if index == 0 else 0
                stop = pair.release_index if index == len(path) - 1 else len(instructions) - 1
                region.extend(instructions[start:stop])
        for instruction in region:
            if isinstance(instruction, m.SSAPhi):
                return "blocked_by_nonunique_path"
            if isinstance(instruction, _EXCEPTION_OPERATIONS):
                return "blocked_by_exception"
            if isinstance(instruction, _CALLS):
                return "blocked_by_call"
            if getattr(instruction, "may_throw", False):
                return "blocked_by_exception"
            if isinstance(instruction, _METHOD_RESULT):
                return "blocked_by_methodresult_constructor"
            if isinstance(instruction, m.SSAInterfaceConstruct):
                return "blocked_by_interface"
            if isinstance(instruction, _STORES) or isinstance(instruction, m.SSAReturn):
                return "blocked_by_escape"
            if instruction.has_side_effects or instruction.writes_memory:
                return "blocked_by_ownership_operation"
            if instruction.may_trap:
                return "blocked_by_exception"
        if analysis.classify_pair(pair) is not ArcPairClassification.LOCALLY_PROVABLE:
            return "blocked_by_escape" if analysis.may_escape(pair.value) else "blocked_by_unsupported_structure"
        return None

    @staticmethod
    def _straight_line_path(function, blocks, pair):
        """Prove one acyclic chain of unconditional normal CFG edges."""
        pred = predecessors(function)
        current = pair.retain_block
        path = []
        seen = set()
        while True:
            if current in seen:
                return None, "blocked_by_loop_backedge"
            seen.add(current)
            path.append(current)
            if current == pair.release_block:
                return tuple(path), None
            block = blocks[current]
            edges = successor_edges(block)
            if any(edge.kind != "normal" for edge in edges):
                return None, "blocked_by_exception"
            if not block.instructions or not isinstance(block.instructions[-1], m.SSAJump):
                return None, "blocked_by_branch" if len(edges) > 1 else "blocked_by_nonunique_path"
            if len(edges) != 1:
                return None, "blocked_by_nonunique_path"
            target = edges[0].target
            if target in seen:
                return None, "blocked_by_loop_backedge"
            if len(pred.get(target, ())) != 1:
                return None, "blocked_by_join"
            current = target
