#!/usr/bin/env python3
"""Read-only O2.9.1 census of structurally hot ARC operations.

This module deliberately observes the production O2 pipeline.  It never runs
an ARC transform and contains no compiler hooks or profiling instrumentation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess

from aether.benchmark import _optimized_ssa
from aether.optimization import optimization_profile
from aether.ir.types import ArrayType, InterfaceType, ListType, MethodResultType, StringType, StructType
from aether.analysis.dominators import DominatorAnalysis
from aether.ssa import model as m
from aether.ssa.analysis import LoopAnalysis, OwnershipEscapeAnalysis, PostDominatorAnalysis
from aether.ssa.cfg import SSACFGBuilder
try:  # module import under pytest versus direct script execution
    from scripts.o2_arc_opportunity_audit import DEFAULT_CORPUS, _classification
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI
    from o2_arc_opportunity_audit import DEFAULT_CORPUS, _classification


SCHEMA_VERSION = 1
ARC_BUILTINS = {"__aether_retain": "retain", "__aether_release": "release"}


def workload_kind(path: str) -> str:
    if path.startswith(("benchmarks/", "examples/")):
        return "REAL_WORKLOAD"
    if path.startswith("tests/"):
        return "TEST_ONLY"
    return "SYNTHETIC_PROBE"


def type_category(type_) -> str:
    if isinstance(type_, StringType): return "STRING"
    if isinstance(type_, ListType): return "LIST"
    if isinstance(type_, ArrayType): return "ARRAY"
    if isinstance(type_, InterfaceType): return "INTERFACE"
    if isinstance(type_, MethodResultType): return "METHOD_RESULT"
    if isinstance(type_, StructType):
        name = repr(type_).lower()
        if "vector" in name: return "VECTOR"
        if "matrix" in name: return "MATRIX"
        return "STRUCT"
    name = repr(type_).lower()
    return "CLASS" if "class" in name else "OTHER_REFERENCE"


def structural_hotness(depth: int, conditional: bool, kind: str) -> int:
    """Deterministic estimate, not runtime profiling.

    Base 1 + 2 per natural-loop depth; an operation in a conditional block
    loses one point (never below one).  Real workload sites gain one point,
    test-only sites lose one.  The deliberately small weights prevent nested
    synthetic probes from overwhelming real programs.
    """
    score = 1 + 2 * depth - int(conditional)
    score += 1 if kind == "REAL_WORKLOAD" else -1 if kind == "TEST_ONLY" else 0
    return max(1, score)


def release_category(definition, value, in_loop: bool, paired: bool) -> str:
    if paired: return "MATCHING_EXPLICIT_RETAIN"
    if definition is None: return "PARAMETER_CLEANUP"
    name = type(definition).__name__
    if "MethodResult" in name: return "RETURN_CLEANUP"
    if "Get" in name and isinstance(value.type, StructType): return "AGGREGATE_FIELD_DESTRUCTION"
    if isinstance(definition, (m.SSAArrayGet, m.SSAListGet)): return "COLLECTION_ELEMENT_DESTRUCTION"
    if isinstance(definition, (m.SSACall, m.SSAInvoke)):
        return "LIFECYCLE_GENERATED_RELEASE"
    if in_loop: return "TEMPORARY_DESTRUCTION"
    return "INITIAL_OWNER_DESTRUCTION"


def loop_role(kind: str, category: str, definition, invariant: bool, fresh: bool) -> str:
    if kind == "release" and fresh: return "DESTRUCTION_ONLY"
    if category in {"LIST", "ARRAY"} or isinstance(definition, (m.SSAArrayGet, m.SSAListGet)):
        return "CONTAINER_ELEMENT_OWNERSHIP"
    if category in {"STRUCT", "METHOD_RESULT"}: return "AGGREGATE_TEMPORARY"
    if isinstance(definition, (m.SSACall, m.SSAInvoke)): return "CALL_BOUNDARY_OWNERSHIP"
    if invariant: return "LOOP_INVARIANT_IDENTITY"
    if definition is None: return "LOOP_CARRIED_OWNER"
    return "PER_ITERATION_LOCAL" if fresh else "LOOP_VARIANT_IDENTITY"


def balance(pair: dict) -> str:
    if not pair["same_loop"]: return "BALANCED_ONLY_AT_LOOP_EXIT"
    if pair["crosses_backedge"]: return "BALANCED_ACROSS_MULTIPLE_ITERATIONS"
    if not pair["release_postdominates_retain"]: return "PATH_DEPENDENT_BALANCE"
    if pair["retain_dominates_release"]: return "BALANCED_PER_ITERATION"
    return "UNKNOWN_BALANCE"


def _conditional(loop, block: str) -> bool:
    # Header and latch are the only conservatively known every-iteration sites.
    return block != loop.header and block not in loop.latches


def _primary_blocker(candidate: dict | None, kind: str) -> str:
    if candidate is None:
        return "INITIAL_OWNERSHIP_DESTRUCTION" if kind == "release" else "NO_CANONICAL_PAIR"
    return candidate["semantic_classification"]


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    operations: list[dict] = []
    pairs: list[dict] = []
    failures: list[dict] = []
    workload_rows: list[dict] = []
    types: Counter[str] = Counter(); releases: Counter[str] = Counter()
    blockers: Counter[str] = Counter(); escape_blockers: Counter[str] = Counter()
    provenance_blockers: Counter[str] = Counter(); roles: Counter[str] = Counter()

    for relative in corpus:
        path = root / relative
        kind_of_workload = workload_kind(relative)
        local = Counter()
        try:
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path, optimization_profile("O2"))
            for function in module.functions:
                loop_result = LoopAnalysis().compute(function)
                analysis = OwnershipEscapeAnalysis(function, structs=module.structs)
                dominators = DominatorAnalysis(
                    SSACFGBuilder().build(function), entry_block=function.entry_block,
                ).compute()
                postdominators = PostDominatorAnalysis(function)
                definitions = {getattr(i, "result", None): (b.name, i)
                               for b in function.blocks for i in b.instructions
                               if getattr(i, "result", None) is not None}
                candidate_by_location = {}
                for candidate in analysis.candidate_arc_pairs():
                    decision = analysis.classify_arc_pair(candidate)
                    retain_loop = loop_result.loop_for_block(candidate.retain_block)
                    release_loop = loop_result.loop_for_block(candidate.release_block)
                    same_loop = bool(retain_loop and release_loop and retain_loop.header == release_loop.header)
                    crosses_backedge = bool(same_loop and candidate.retain_block in retain_loop.body
                                             and candidate.release_block in retain_loop.body
                                             and candidate.release_block in retain_loop.latches
                                             and candidate.retain_block != candidate.release_block)
                    blocks = {block.name: block for block in function.blocks}
                    if candidate.retain_block == candidate.release_block:
                        crossed = blocks[candidate.retain_block].instructions[
                            candidate.retain_index + 1:candidate.release_index
                        ]
                    else:
                        # Conservative for a multi-block region: inspect the two
                        # endpoints and every block in their common natural loop.
                        names = (retain_loop.body if same_loop else blocks.keys())
                        crossed = [i for name in names for i in blocks[name].instructions]
                    crosses_call = any(isinstance(i, (m.SSACall, m.SSAInvoke,
                        m.SSACallIndirect, m.SSAInvokeIndirect, m.SSAInterfaceCall,
                        m.SSAInvokeInterface)) and getattr(i, "builtin", None) not in ARC_BUILTINS
                        for i in crossed)
                    crosses_store = any(getattr(i, "writes_memory", False) for i in crossed)
                    row = {
                        "workload": relative, "workload_kind": kind_of_workload,
                        "function": function.name, "ssa_value": candidate.value.name,
                        "type": repr(candidate.value.type), "type_category": type_category(candidate.value.type),
                        "retain": f"{candidate.retain_block}:{candidate.retain_index}",
                        "release": f"{candidate.release_block}:{candidate.release_index}",
                        "same_loop": same_loop, "same_iteration": same_loop and not crosses_backedge,
                        "retain_dominates_release": dominators.dominates(candidate.retain_block, candidate.release_block),
                        "release_postdominates_retain": postdominators.post_dominates(candidate.release_block, candidate.retain_block),
                        "crosses_latch": crosses_backedge, "crosses_backedge": crosses_backedge,
                        "crosses_loop_exit": bool(retain_loop and not same_loop),
                        "crosses_continue_like_edge": crosses_backedge,
                        "crosses_branch": candidate.retain_block != candidate.release_block,
                        "crosses_join": "normal-join" in {r.value for r in decision.reasons},
                        "crosses_call": crosses_call, "crosses_store": crosses_store,
                        "crosses_exceptional_edge": "exception-lifetime" in {r.value for r in decision.reasons},
                        "exact_same_ownership_edge_provable": decision.provenance.exact and len(decision.provenance.roots) == 1,
                        "semantic_eligibility": decision.status.value,
                        "structural_eligibility": "CURRENTLY_ELIGIBLE" if decision.semantically_provable else "INELIGIBLE",
                        "semantic_classification": _classification(decision),
                    }
                    row["per_iteration_balance"] = balance(row)
                    pairs.append(row)
                    candidate_by_location[(candidate.retain_block, candidate.retain_index)] = (candidate, decision, row)
                    candidate_by_location[(candidate.release_block, candidate.release_index)] = (candidate, decision, row)

                for block in function.blocks:
                    loop = loop_result.loop_for_block(block.name)
                    enclosing = sorted((x.header for x in loop_result.loops if block.name in x.body),
                                       key=lambda header: loop_result.loop_with_header(header).depth)
                    for index, instruction in enumerate(block.instructions):
                        if not isinstance(instruction, (m.SSACall, m.SSAInvoke)) or instruction.builtin not in ARC_BUILTINS:
                            continue
                        arc_kind = ARC_BUILTINS[instruction.builtin]
                        value = instruction.arguments[0]
                        definition_entry = definitions.get(value)
                        definition = definition_entry[1] if definition_entry else None
                        matched = candidate_by_location.get((block.name, index))
                        decision = matched[1] if matched else None
                        provenance = analysis.provenance(value); escape = analysis.escape_fact(value)
                        invariant = bool(loop and (definition_entry is None or definition_entry[0] not in loop.body))
                        fresh = analysis.is_fresh(value)
                        category = type_category(value.type)
                        role = loop_role(arc_kind, category, definition, invariant, fresh) if loop else "OUTSIDE_LOOP"
                        primary = _primary_blocker(matched[2] if matched else None, arc_kind)
                        secondary = sorted(r.value for r in decision.reasons) if decision else []
                        release_class = release_category(definition, value, bool(loop), bool(matched)) if arc_kind == "release" else None
                        site = {
                            "workload": relative, "workload_kind": kind_of_workload,
                            "function": function.name, "ssa_value": value.name, "type": repr(value.type),
                            "type_category": category, "block": block.name, "instruction_index": index,
                            "arc_kind": arc_kind, "loop_depth": loop.depth if loop else 0,
                            "innermost_loop_id": loop.header if loop else None, "enclosing_loop_ids": enclosing,
                            "provenance_root": [f"{r.kind.value}:{r.identity}" for r in sorted(provenance.roots)],
                            "provenance_exact": provenance.exact,
                            "ownership_role": analysis.ownership_state_before(value, block.name, index).value,
                            "escape_state": {"may_escape": escape.may_escape, "normal": escape.normal,
                                             "exceptional": escape.exceptional,
                                             "reasons": sorted(r.value for r in escape.reasons)},
                            "defining_instruction": type(definition).__name__ if definition else "PARAMETER",
                            "matching_pair_known": matched is not None,
                            "semantic_pair_classification": matched[2]["semantic_classification"] if matched else "NO_PAIR",
                            "structural_pair_classification": matched[2]["structural_eligibility"] if matched else "NO_PAIR",
                            "primary_blocker": primary, "secondary_blockers": secondary,
                            "loop_role": role, "ssa_operand_loop_invariant": invariant,
                            "provenance_root_loop_invariant": invariant,
                            "ownership_role_invariant": invariant and not escape.may_escape,
                            "object_escapes_during_loop": bool(loop and escape.may_escape),
                            "calls_may_mutate_or_consume": "call" in " ".join(secondary),
                            "fresh_per_iteration_owner": bool(loop and fresh and not invariant),
                            "release_category": release_class,
                            "structural_hotness": structural_hotness(loop.depth if loop else 0,
                                                                      bool(loop and _conditional(loop, block.name)),
                                                                      kind_of_workload),
                            "measured_dynamic_count": None,
                        }
                        operations.append(site); types[category] += 1; local[arc_kind] += 1
                        blockers[primary] += 1; roles[role] += 1
                        if release_class: releases[release_class] += 1
                        for reason in escape.reasons: escape_blockers[reason.value] += 1
                        if not provenance.exact:
                            provenance_blockers[(provenance.reason.value if provenance.reason else "other")] += 1
            workload_rows.append({"path": relative, "kind": kind_of_workload, **dict(sorted(local.items()))})
        except Exception as error:
            failures.append({"path": relative, "error": type(error).__name__, "message": str(error)[:200]})

    operations.sort(key=lambda x: (x["workload"], x["function"], x["block"], x["instruction_index"], x["arc_kind"]))
    pairs.sort(key=lambda x: (x["workload"], x["function"], x["retain"], x["release"]))
    loop_sites = [x for x in operations if x["loop_depth"]]
    ranked = sorted(loop_sites, key=lambda x: (-x["structural_hotness"], x["workload_kind"] != "REAL_WORKLOAD",
                                               x["workload"], x["function"], x["block"], x["instruction_index"]))
    total = Counter(x["arc_kind"] for x in operations); loop_total = Counter(x["arc_kind"] for x in loop_sites)
    hotness_by_family = defaultdict(lambda: {"static_operations": 0, "loop_operations": 0, "structural_hotness_coverage": 0})
    for item in operations:
        family = ("AGGREGATE_LIFETIME_IMPROVEMENT" if item["loop_role"] in {"AGGREGATE_TEMPORARY", "CONTAINER_ELEMENT_OWNERSHIP"}
                  else "ESCAPE_ANALYSIS_IMPROVEMENT" if item["escape_state"]["may_escape"]
                  else "PROVENANCE_IMPROVEMENT" if not item["provenance_exact"]
                  else "LOCAL_PAIR_ELIMINATION" if item["matching_pair_known"]
                  else "NO_SAFE_ARC_OPTIMIZATION")
        item["likely_optimization_family"] = family
        stats = hotness_by_family[family]; stats["static_operations"] += 1
        stats["loop_operations"] += int(bool(item["loop_depth"])); stats["structural_hotness_coverage"] += item["structural_hotness"]
    matrix = []
    for family, stats in sorted(hotness_by_family.items()):
        matrix.append({"family": family, **stats,
                       "implementation_complexity": "HIGH" if family in {"AGGREGATE_LIFETIME_IMPROVEMENT", "ESCAPE_ANALYSIS_IMPROVEMENT"} else "MEDIUM",
                       "correctness_risk": "HIGH" if family != "NO_SAFE_ARC_OPTIMIZATION" else "LOW",
                       "dependency_analyses": ["ownership", "loops", "escape", "provenance"]})
    recommendation = "PROCEED_TO_AGGREGATE_LIFETIME_ANALYSIS" if any(
        x["loop_role"] in {"AGGREGATE_TEMPORARY", "CONTAINER_ELEMENT_OWNERSHIP"} for x in ranked[:10]
    ) else "PAUSE_ARC_PROCEED_TO_LOOP_OPTIMIZATION"
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True, text=True,
                              capture_output=True).stdout.strip()
    return {
        "audit": "O2.9.1-hot-arc-opportunity", "schema_version": SCHEMA_VERSION,
        "tested_revision": revision, "methodology": "read-only production O2 lifecycle-expanded SSA census",
        "corpus": list(corpus), "corpus_failures": failures,
        "arc_baseline": {"retain": total["retain"], "release": total["release"], "total": sum(total.values()),
                         "outside_loops": len(operations) - len(loop_sites),
                         "functions_with_arc": len({(x["workload"], x["function"]) for x in operations})},
        "loop_arc_baseline": {"retain": loop_total["retain"], "release": loop_total["release"], "total": len(loop_sites),
                              "functions": len({(x["workload"], x["function"]) for x in loop_sites}),
                              "workloads": len({x["workload"] for x in loop_sites})},
        "workload_summary": workload_rows, "type_category_summary": dict(sorted(types.items())),
        "release_classification": dict(sorted(releases.items())), "arc_operations": operations,
        "loop_arc_sites": loop_sites, "loop_role_summary": dict(sorted(roles.items())),
        "candidate_pairs": pairs,
        "blocker_distribution": dict(sorted(blockers.items())),
        "escape_blocker_distribution": dict(sorted(escape_blockers.items())),
        "provenance_blocker_distribution": dict(sorted(provenance_blockers.items())),
        "alias_modref_blockers": {"unknown_call": sum("call" in " ".join(x["secondary_blockers"]) for x in loop_sites),
                                  "may_alias": sum("alias" in x["secondary_blockers"] for x in loop_sites)},
        "exception_arc": {"loop_operations": sum(x["escape_state"]["exceptional"] for x in loop_sites),
                          "all_operations": sum(x["escape_state"]["exceptional"] for x in operations)},
        "structural_hotness_definition": "max(1, 1 + 2*loop_depth - conditional + real_workload - test_only)",
        "ranked_hot_opportunities": ranked[:max(10, min(25, len(ranked)))],
        "optimization_family_matrix": matrix,
        "llvm_overlap": {"ARC_RUNTIME_CALLS": "AETHER_UNIQUE", "aggregate_lowering": "LLVM_PARTIAL"},
        "real_synthetic_distribution": dict(sorted(Counter(x["workload_kind"] for x in loop_sites).items())),
        "non_arc_comparison": [
            {"candidate": "MEMORY_LICM", "dynamic_relevance": "HIGH", "llvm_overlap": "LLVM_PARTIAL", "risk": "MEDIUM"},
            {"candidate": "GVN_CSE", "dynamic_relevance": "MEDIUM", "llvm_overlap": "LLVM_CONVERGES", "risk": "MEDIUM"},
            {"candidate": "LOOP_OPTIMIZATION", "dynamic_relevance": "HIGH", "llvm_overlap": "LLVM_PARTIAL", "risk": "MEDIUM"},
        ],
        "final_recommendation": recommendation,
        "production_codegen_changed": False, "arc_changed": False, "optimization_profiles_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    report = generate(root, tuple(args.paths) or DEFAULT_CORPUS)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    else: print(text, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
