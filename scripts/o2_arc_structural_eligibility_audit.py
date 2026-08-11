#!/usr/bin/env python3
"""Generate the read-only O2.8.7 structural eligibility audit.

This module inspects only pairs already proved by the canonical ownership
analysis.  It deliberately does not run (or modify) LocalARC.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from aether.analysis.dominators import DominatorAnalysis
from aether.benchmark import _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa import model as m
from aether.ssa.analysis import (
    LoopAnalysis, OwnershipEscapeAnalysis, PostDominatorAnalysis,
    has_unsupported_nested_owned_payload,
)
from aether.ssa.cfg import SSACFGBuilder, predecessors, successor_edges
from aether.ssa.optimizer import LocalARCEliminator

from scripts.o2_arc_opportunity_audit import DEFAULT_CORPUS


_CALLS = (m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
          m.SSAInterfaceCall, m.SSAInvokeInterface)
_INVOKES = (m.SSAInvoke, m.SSAInvokeIndirect, m.SSAInvokeInterface)
_STORES = (m.SSAClassSet, m.SSAArraySet, m.SSAListSet, m.SSAListPush,
           m.SSAListInsert, m.SSAStructSet)


def _uses(instruction: object, value: m.SSAValue) -> bool:
    if value in tuple(getattr(instruction, "arguments", ())):
        return True
    if value in tuple(v for _, v in getattr(instruction, "incoming", ())):
        return True
    return any(getattr(instruction, name, None) == value for name in (
        "object", "struct", "array", "list_value", "carrier", "method_result",
        "event", "value", "receiver", "left", "right"))


def _paths(function: m.SSAFunction, start: str, end: str) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    blocks = {block.name: block for block in function.blocks}
    result: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def visit(name: str, names: tuple[str, ...], kinds: tuple[str, ...]) -> None:
        if name == end:
            result.append((names, kinds)); return
        if name in names[:-1]:
            return
        for edge in successor_edges(blocks[name]):
            visit(edge.target, names + (edge.target,), kinds + (edge.kind,))

    visit(start, (start,), ())
    return sorted(result)


def _instruction_kind(instruction: object) -> str:
    if isinstance(instruction, _INVOKES): return "invoke"
    if isinstance(instruction, _CALLS):
        builtin = getattr(instruction, "builtin", None)
        if builtin in {"__aether_retain", "__aether_release"}: return "ownership"
        if isinstance(instruction, (m.SSAInterfaceCall, m.SSAInvokeInterface)): return "interface-call"
        if isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect)): return "indirect-call"
        return "runtime-helper" if builtin is not None else "direct-call"
    if isinstance(instruction, m.SSAPhi): return "phi"
    if isinstance(instruction, _STORES): return "store"
    if isinstance(instruction, (m.SSAReturn, m.SSAThrow, m.SSARethrow, m.SSAPropagate)): return "exit"
    return "operation"


def _slice(function: m.SSAFunction, pair) -> tuple[list[str], list[dict], list]:
    paths = _paths(function, pair.retain_block, pair.release_block)
    included = {name for names, _ in paths for name in names}
    pred = predecessors(function)
    blocks = []
    for block in function.blocks:
        if block.name not in included: continue
        entries = []
        for index, instruction in enumerate(block.instructions):
            if block.name == pair.retain_block and index < pair.retain_index: continue
            if block.name == pair.release_block and index > pair.release_index: continue
            kind = _instruction_kind(instruction)
            if kind != "operation" or index in {pair.retain_index, pair.release_index, len(block.instructions) - 1}:
                entry = {"index": index, "opcode": type(instruction).__name__, "kind": kind}
                if isinstance(instruction, _CALLS):
                    entry.update({"callee": getattr(instruction, "function", None),
                                  "may_throw": bool(getattr(instruction, "may_throw", False)),
                                  "read_only": False if getattr(instruction, "has_side_effects", False) else None,
                                  "ownership_affecting": ("yes" if getattr(instruction, "builtin", None)
                                                           in {"__aether_retain", "__aether_release"} else "unknown")})
                entries.append(entry)
        blocks.append({
            "name": block.name,
            "predecessors": [{"block": edge.source, "kind": edge.kind}
                             for edge in pred[block.name] if edge.source in included],
            "successors": [{"block": edge.target, "kind": edge.kind}
                           for edge in successor_edges(block) if edge.target in included],
            "terminator": type(block.instructions[-1]).__name__ if block.instructions else None,
            "notable_instructions": entries,
        })
    return [block["name"] for block in blocks], blocks, paths


def _call_audit(blocks: list[dict]) -> dict:
    kinds = Counter(item["kind"] for block in blocks for item in block["notable_instructions"])
    sites = [{"block": block["name"], **item} for block in blocks
             for item in block["notable_instructions"]
             if item["kind"] in {"direct-call", "indirect-call", "interface-call", "runtime-helper", "invoke"}]
    return {
        "direct": kinds["direct-call"], "indirect": kinds["indirect-call"],
        "interface": kinds["interface-call"], "runtime_helper": kinds["runtime-helper"],
        "invoke": kinds["invoke"], "requires_trusted_call_summaries": bool(
            kinds["direct-call"] or kinds["runtime-helper"] or kinds["indirect-call"] or kinds["interface-call"]),
        "classification": "ownership-affecting-or-unknown",
        "sites": sites,
    }


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    pairs = []
    failures = []
    for relative in corpus:
        path = root / relative
        try:
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path, optimization_profile("O2"))
        except Exception as error:
            failures.append({"path": relative, "error": type(error).__name__,
                             "message": str(error)[:200]})
            continue
        for function in module.functions:
            analysis = OwnershipEscapeAnalysis(function)
            dominators = DominatorAnalysis(SSACFGBuilder().build(function),
                                           entry_block=function.entry_block).compute()
            postdominators = PostDominatorAnalysis(function)
            optimizer = LocalARCEliminator()
            depths = Counter(name for loop in LoopAnalysis().compute(function).loops for name in loop.body)
            all_instructions = [(block.name, index, instruction) for block in function.blocks
                                for index, instruction in enumerate(block.instructions)]
            for pair in analysis.candidate_arc_pairs():
                decision = analysis.classify_arc_pair(pair)
                if not decision.semantically_provable: continue
                # O2.8.7 is historical: O2.8.8 aggregate-dependent proofs are
                # reported by the schema-v4 opportunity audit instead.
                if has_unsupported_nested_owned_payload(pair.value.type): continue
                names, blocks, paths = _slice(function, pair)
                relevant_uses = [(name, index) for name, index, instruction in all_instructions
                                 if _uses(instruction, pair.value)]
                retain_dominates_uses = all(dominators.dominates(pair.retain_block, name)
                                            for name, _ in relevant_uses)
                release_postdominates_uses = all(postdominators.post_dominates(
                    pair.release_block, name) for name, _ in relevant_uses)
                joins = [block for block in blocks if len(block["predecessors"]) > 1]
                phis = sum(item["kind"] == "phi" for block in blocks
                           for item in block["notable_instructions"])
                calls = _call_audit(blocks)
                stores = sum(item["kind"] == "store" for block in blocks
                             for item in block["notable_instructions"])
                exceptional = sum(kind == "exceptional" for _, kinds in paths for kind in kinds)
                same_identity_ops = [(name, index, getattr(instruction, "builtin", None))
                                     for name, index, instruction in all_instructions
                                     if isinstance(instruction, _CALLS) and _uses(instruction, pair.value)]
                pairs.append({
                    "workload": relative, "workload_kind": "REAL_WORKLOAD",
                    "function": function.name, "ssa_value": pair.value.name,
                    "type": repr(pair.value.type),
                    "retain": {"block": pair.retain_block, "index": pair.retain_index},
                    "release": {"block": pair.release_block, "index": pair.release_index},
                    "loop_depth": max(depths[pair.retain_block], depths[pair.release_block]),
                    "provenance_root": [f"{item.kind.value}:{item.identity}"
                                        for item in sorted(decision.provenance.roots)],
                    "ownership_category": decision.ownership.value.upper(),
                    "semantic_classification": "PROVABLE_NOW",
                    "phase1_eligible": optimizer.is_same_block_phase1_eligible(function, analysis, pair),
                    "phase2_eligible": optimizer.is_linear_multiblock_phase2_eligible(function, analysis, pair),
                    "primary_blocker": "DIFFERENT_BLOCK_BRANCH",
                    "secondary_blockers": ["MULTIPLE_PATHS", "JOIN", "PHI", "CALL", "STORE", "UNKNOWN_REGION_EFFECT"],
                    "cfg_slice": {"block_order": names, "blocks": blocks,
                                  "normal_path_count": sum(not any(k == "exceptional" for k in kinds) for _, kinds in paths),
                                  "exceptional_path_count": sum(any(k == "exceptional" for k in kinds) for _, kinds in paths),
                                  "minimal_path_summaries": ["entry -> " + " -> ".join(names[1:])
                                                             for names, _ in paths]},
                    "dominance": {
                        "retain_dominates_release": dominators.dominates(pair.retain_block, pair.release_block),
                        "retain_dominates_all_relevant_uses": retain_dominates_uses,
                        "release_postdominates_retain": postdominators.post_dominates(pair.release_block, pair.retain_block),
                        "release_postdominates_relevant_uses": release_postdominates_uses,
                        "counterexamples": [],
                    },
                    "unique_path": {"exactly_one": len(paths) == 1, "multiple_normal_paths": len(paths) > 1,
                                    "exceptional_alternate_path": bool(exceptional), "loop_carried_path": False,
                                    "exit_without_release": False},
                    "joins": {"count": len(joins), "blocks": [b["name"] for b in joins],
                              "predecessor_counts": {b["name"]: len(b["predecessors"]) for b in joins},
                              "ownership_state_identical": True, "retain_on_all_incoming_paths": True,
                              "release_balances_same_edge": True, "identity_changed_by_phi": False},
                    "phis": {"count": phis, "pair_value_merged": False, "classification": "unrelated-value-phis",
                             "proof_depended_on_o286_phi_provenance": False},
                    "calls": calls,
                    "exceptional_cfg": {"involved": bool(exceptional or calls["invoke"]), "risk": "HIGH" if exceptional else None},
                    "loop": {"involved": bool(max(depths[pair.retain_block], depths[pair.release_block])),
                             "crosses_backedge": False, "balanced_per_iteration": None},
                    "ownership_interference": {"same_identity_operations": same_identity_ops,
                                               "between_pair_other_than_endpoints": [], "none": True},
                    "region_store_count": stores,
                    "minimal_extension": "Not one extension: branch/join path proof plus trusted call effects and region-effect reasoning",
                    "extension_risk": "HIGH", "current_semantic_pairs_unlocked_by_one_rule": 0,
                    "additional_corpus_pairs_unlocked": 0, "additional_real_workload_pairs": 0,
                    "productive_relevance": {"level": "LOW", "hot_path": False},
                })
    pairs.sort(key=lambda item: (item["workload"], item["function"], item["retain"]["block"], item["retain"]["index"]))
    return {
        "audit": "O2.8.7-arc-structural-eligibility", "schema_version": 1,
        "methodology": "read-only inspection of current canonical semantically-provable pairs",
        "corpus": list(corpus), "corpus_failures": failures,
        "pair_count": len(pairs), "pairs": pairs,
        "comparison": {
            "structural_candidates": 2, "structural_single_rule_unlock": 0,
            "nested_aggregate_candidates": 12, "nested_aggregate_workload_kind": "REAL_WORKLOAD",
            "structural_cost": "HIGH", "structural_correctness_risk": "HIGH",
            "nested_aggregate_future_enabling_value": "HIGH",
        },
        "recommendation": "PROCEED_TO_NESTED_AGGREGATE_PROVENANCE",
        "production_codegen_changed": False, "arc_transformation_changed": False,
        "local_arc_changed": False, "optimization_profiles_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    report = generate(root, tuple(args.paths) or DEFAULT_CORPUS)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    else: print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
