"""O2.9 Phase-1 elimination of strictly local, proven ARC pairs."""
from __future__ import annotations

from collections import Counter
import hashlib

from aether.analysis.dominators import DominatorAnalysis
from aether.ssa import model as m
from aether.ssa.cfg import SSACFGBuilder, predecessors, successor_edges
from aether.ssa.analysis import (
    ArcPairClassification, ArcPairSemanticReason, OwnershipEscapeAnalysis,
    OwnershipUnknownReason, PostDominatorAnalysis,
    has_unsupported_nested_owned_payload,
)
from aether.ir.types import ArrayType, ListType, StructType

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
        "nested_aggregate_candidates", "nested_aggregate_qualified",
        "nested_aggregate_phase1", "nested_aggregate_phase2",
        "nested_aggregate_extension",
    )

    def run(self, module: m.SSAModule) -> SSAOptimizationResult:
        stats: Counter[str] = Counter({key: 0 for key in self._STAT_KEYS})
        functions: list[m.SSAFunction] = []
        transformation_log: list[dict[str, str]] = []
        changed = False
        for function in module.functions:
            rewritten, removed = self._run_function(
                function, module.structs, stats, transformation_log,
            )
            functions.append(rewritten)
            changed |= bool(removed)
        optimized = m.SSAModule(functions, list(module.structs)) if changed else module
        return SSAOptimizationResult(
            optimized, changed, dict(stats), tuple(transformation_log),
        )

    def _run_function(self, function: m.SSAFunction, structs, stats: Counter[str],
                      transformation_log: list[dict[str, str]]):
        analysis = OwnershipEscapeAnalysis(function, structs=structs)
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
            nested_qualification = self._nested_component_arc_pair_qualification(
                function, blocks, analysis, pair,
            )
            if has_unsupported_nested_owned_payload(pair.value.type):
                stats["nested_aggregate_candidates"] += 1
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
            if nested_qualification is not None:
                stats["nested_aggregate_qualified"] += 1
                stats[f"nested_aggregate_{nested_qualification['route']}"] += 1
            if not multi_block:
                stats["phase1_eligible_pairs"] += 1
            # Assertions make the proof boundary explicit in debug/test runs.
            assert (analysis.classify_pair(pair) is ArcPairClassification.LOCALLY_PROVABLE
                    or nested_qualification is not None)
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
            if nested_qualification is not None:
                transformation_log.append(self._transformation_record(
                    function, pair, nested_qualification,
                ))

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
        nested_qualification = self._nested_component_arc_pair_qualification(
            function, blocks, analysis, pair,
        )
        if (has_unsupported_nested_owned_payload(pair.value.type)
                and nested_qualification is None):
            return "blocked_by_aggregate"
        if not semantic.semantically_provable and nested_qualification is None:
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
            if nested_qualification is not None:
                if isinstance(instruction, m.SSAStructNew):
                    continue
                if (isinstance(instruction, m.SSACall)
                        and instruction.builtin == "__aether_release"
                        and instruction.arguments
                        and instruction.arguments[0] != pair.value):
                    continue
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
        if (nested_qualification is None
                and analysis.classify_pair(pair) is not ArcPairClassification.LOCALLY_PROVABLE):
            return "blocked_by_escape" if analysis.may_escape(pair.value) else "blocked_by_unsupported_structure"
        return None

    def nested_component_arc_pair_is_qualified(
        self, function: m.SSAFunction, analysis: OwnershipEscapeAnalysis, pair,
    ) -> bool:
        """Whether the O2.8.9 aggregate-transfer rule proves this exact pair."""
        blocks = {block.name: block for block in function.blocks}
        return self._nested_component_arc_pair_qualification(
            function, blocks, analysis, pair,
        ) is not None

    @staticmethod
    def _nested_component_arc_pair_qualification(function, blocks, analysis, pair):
        """Qualify only a dead source owner transferred into one struct field.

        A ``List<Struct>``/``Array<Struct>`` is still a reference-like collection
        object.  This rule reasons about that object's exact root and the one
        aggregate field ownership edge; it never assigns provenance to an
        element of the collection.
        """
        type_ = pair.value.type
        if not (isinstance(type_, (ListType, ArrayType))
                and isinstance(type_.element, StructType)):
            return None
        if pair.retain_block != pair.release_block or pair.retain_index >= pair.release_index:
            return None
        provenance = analysis.provenance(pair.value)
        if (not provenance.exact or len(provenance.roots) != 1
                or not analysis.is_fresh(pair.value)
                or analysis.ownership_state_before(
                    pair.value, pair.retain_block, pair.retain_index,
                ).value != "owned"):
            return None
        block = blocks[pair.retain_block]
        # A backedge would make "dead after release" iteration-sensitive.
        work = [edge.target for edge in successor_edges(block)]
        seen = set()
        while work:
            name = work.pop()
            if name == block.name:
                return None
            if name in seen:
                continue
            seen.add(name)
            work.extend(edge.target for edge in successor_edges(blocks[name]))
        region = block.instructions[pair.retain_index + 1:pair.release_index]
        constructions = [item for item in region
                         if isinstance(item, m.SSAStructNew)
                         and item.fields.count(pair.value) == 1]
        if len(constructions) != 1:
            return None
        construction = constructions[0]
        # The interval may contain only the construction and releases of
        # independent exact roots.  Calls, stores, traps and aggregate updates
        # remain rejected by the ordinary LocalARC barrier below.
        for instruction in region:
            if instruction is construction:
                continue
            if not (isinstance(instruction, m.SSACall)
                    and instruction.builtin == "__aether_release"
                    and instruction.arguments
                    and instruction.arguments[0] != pair.value):
                return None
            other = analysis.provenance(instruction.arguments[0])
            if not other.exact or provenance.roots & other.roots:
                return None
        field_index = construction.fields.index(pair.value)
        components = analysis.aggregate_provenance(construction.result).components
        matches = [(path, fact) for path, fact in components
                   if len(path.fields) == 1
                   and path.fields[0].index == field_index]
        if (len(matches) != 1 or matches[0][1].provenance != provenance
                or matches[0][1].ownership.value != "owned"):
            return None
        # No direct use of the source owner may follow the balancing release.
        # Aggregate uses are intentionally not source uses: they consume the
        # single transferred field edge whose identity was checked above.
        for instruction in block.instructions[pair.release_index + 1:]:
            if pair.value in tuple(getattr(instruction, "arguments", ())):
                return None
        for name in seen:
            for instruction in blocks[name].instructions:
                if pair.value in tuple(getattr(instruction, "arguments", ())):
                    return None
                if any(getattr(instruction, attr, None) == pair.value for attr in (
                    "value", "object", "struct", "array", "list_value", "carrier",
                    "receiver", "method_result", "event",
                )):
                    return None
            if any(getattr(instruction, name, None) == pair.value for name in (
                "value", "object", "struct", "array", "list_value", "carrier",
                "receiver", "method_result", "event",
            )):
                return None
        return {
            "route": "extension" if len(region) > 1 else "phase1",
            "component_path": str(matches[0][0]),
            "root": next(iter(provenance.roots)).identity,
            "proof": "exact owned collection root transferred to one struct field; source dead after release",
        }

    @staticmethod
    def _transformation_record(function, pair, qualification):
        material = "|".join((function.name, pair.retain_block,
                             str(pair.retain_index), pair.release_block,
                             str(pair.release_index), qualification["component_path"],
                             qualification["root"]))
        candidate_id = "O2.8.9-" + hashlib.sha256(material.encode()).hexdigest()[:16]
        return {
            "candidate_id": candidate_id,
            "function": function.name,
            "component_path": qualification["component_path"],
            "exact_root": qualification["root"],
            "retain": f"{pair.retain_block}:{pair.retain_index}",
            "release": f"{pair.release_block}:{pair.release_index}",
            "route": qualification["route"],
            "ownership_proof": qualification["proof"],
        }

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
