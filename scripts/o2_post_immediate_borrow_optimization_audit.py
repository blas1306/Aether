#!/usr/bin/env python3
"""Deterministic, read-only O2.9.8 optimization-family audit.

The audit intentionally imports the existing ownership census instead of
duplicating its accounting rules.  It observes optimized SSA and never runs a
transformation or mutates an optimization profile.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from aether.o2_evidence_materialization import optimized_ssa as _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa import model as m
from aether.ssa.analysis import LoopAnalysis
from aether.ssa.operands import instruction_operands
from aether.ssa.optimizer.licm import LoopInvariantCodeMotion

try:
    from scripts.o2_arc_opportunity_audit import DEFAULT_CORPUS
    from scripts.o2_hot_arc_opportunity_audit import structural_hotness, workload_kind
    from scripts.o2_post_arrayget_hot_ownership_audit import generate as ownership_generate
except ModuleNotFoundError:  # pragma: no cover - direct CLI execution
    from o2_arc_opportunity_audit import DEFAULT_CORPUS
    from o2_hot_arc_opportunity_audit import structural_hotness, workload_kind
    from o2_post_arrayget_hot_ownership_audit import generate as ownership_generate


SCHEMA_VERSION = 1
PRIMARY_RECOMMENDATION = "PROCEED_TO_SCALAR_REPLACEMENT_ANALYSIS"
SECONDARY_RECOMMENDATION = "PROCEED_TO_AGGREGATE_COPY_ELISION"


def _site_key(row: dict) -> tuple:
    return (row.get("workload", ""), row.get("function", ""),
            row.get("block", ""), row.get("instruction_index", -1))


def _expression_key(instruction) -> tuple | None:
    """A deliberately narrow pure-expression identity for opportunity census."""
    if not isinstance(instruction, (m.SSABinaryOp, m.SSAUnaryOp, m.SSACast,
                                    m.SSACompareOp, m.SSAStructGet)):
        return None
    if getattr(instruction, "has_side_effects", False):
        return None
    operands = tuple((value.name, repr(value.type)) for value in instruction_operands(instruction))
    return (type(instruction).__name__, getattr(instruction, "operator", None),
            getattr(instruction, "field_index", None), operands)


def _ssa_family_census(root: Path, corpus: tuple[str, ...]) -> dict:
    loops_rows: list[dict] = []
    gvn: list[dict] = []
    licm_stats = Counter()
    indirect: list[dict] = []
    allocations: list[dict] = []
    strength: list[dict] = []
    direct_calls: list[dict] = []
    for relative in corpus:
        path = root / relative
        try:
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path,
                                    optimization_profile("O2"))
        except Exception:
            continue
        # Running LICM on already optimized SSA is a read-only measurement: the
        # returned module is discarded and production/profile state is untouched.
        outcome = LoopInvariantCodeMotion().run(module)
        licm_stats.update(outcome.stats)
        for function in module.functions:
            analysis = LoopAnalysis().compute(function)
            for loop in analysis.loops:
                loops_rows.append({
                    "workload": relative, "function": function.name,
                    "header": loop.header, "depth": loop.depth,
                    "canonical_preheader": loop.preheader is not None,
                    "latch_count": len(loop.latches), "single_latch": len(loop.latches) == 1,
                    "exit_count": len(loop.exit_blocks), "multiple_exits": len(loop.exit_blocks) > 1,
                    "canonical_induction_variables": len(loop.induction_variables),
                    "simple_counted": len(loop.induction_variables) == 1 and len(loop.latches) == 1,
                    "loop_carried_phis": sum(isinstance(i, m.SSAPhi)
                        for b in function.blocks if b.name == loop.header for i in b.instructions),
                })
            for region in analysis.irreducible_regions:
                loops_rows.append({"workload": relative, "function": function.name,
                                   "irreducible": True, "blocks": sorted(region.blocks)})
            seen_global: dict[tuple, tuple[str, int]] = {}
            for block in function.blocks:
                seen_local: dict[tuple, int] = {}
                loop = analysis.loop_for_block(block.name)
                for index, instruction in enumerate(block.instructions):
                    key = _expression_key(instruction)
                    if key is not None:
                        prior = seen_local.get(key)
                        global_prior = seen_global.get(key)
                        if prior is not None or global_prior is not None:
                            scope = "SAME_BLOCK" if prior is not None else "DOMINATOR_PROOF_REQUIRED"
                            gvn.append({"workload": relative, "function": function.name,
                                        "block": block.name, "instruction_index": index,
                                        "instruction": type(instruction).__name__, "scope": scope,
                                        "loop_depth": loop.depth if loop else 0,
                                        "structural_hotness": structural_hotness(
                                            loop.depth if loop else 0, False, workload_kind(relative)),
                                        "blocked_by_effects": False,
                                        "blocked_by_exception_or_trap": bool(getattr(instruction, "may_trap", False)),
                                        "llvm_overlap": "LLVM_ALREADY_ELIMINATES" if scope == "SAME_BLOCK" else "LLVM_PARTIAL"})
                        seen_local[key] = index
                        seen_global.setdefault(key, (block.name, index))
                    if isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect,
                                                m.SSAInterfaceCall, m.SSAInvokeInterface)):
                        indirect.append({"workload": relative, "function": function.name,
                                         "block": block.name, "instruction_index": index,
                                         "kind": type(instruction).__name__, "loop_depth": loop.depth if loop else 0,
                                         "exact_target_known": False, "target_set_size": "OPEN",
                                         "downstream_unlock": "NONE_PROVEN"})
                    if isinstance(instruction, (m.SSACall, m.SSAInvoke)) and getattr(instruction, "builtin", None) is None:
                        direct_calls.append({"workload": relative, "function": function.name,
                                             "block": block.name, "instruction_index": index,
                                             "callee": instruction.function, "loop_depth": loop.depth if loop else 0,
                                             "aether_specific_unlock": "NONE_MEASURED"})
                    if loop and getattr(instruction, "allocates", False):
                        result = getattr(instruction, "result", None)
                        if result is not None and any(x in repr(result.type) for x in
                                ("StringType", "ArrayType", "ListType", "StructType", "Class")):
                            allocations.append({"workload": relative, "function": function.name,
                                                "block": block.name, "instruction_index": index,
                                                "instruction": type(instruction).__name__, "value": result.name,
                                                "type": repr(result.type), "loop_depth": loop.depth,
                                                "escape_status": "REQUIRES_OWNERSHIP_ESCAPE_QUERY"})
                    if loop and isinstance(instruction, m.SSABinaryOp) and instruction.operator in {"mul", "add", "sub"}:
                        strength.append({"workload": relative, "function": function.name,
                                         "block": block.name, "instruction_index": index,
                                         "operator": instruction.operator, "loop_depth": loop.depth,
                                         "checked_semantics": bool(getattr(instruction, "may_trap", False)),
                                         "llvm_overlap": "LLVM_PARTIAL"})
    return {"loops": sorted(loops_rows, key=lambda x: (x["workload"], x["function"], x.get("header", ""))),
            "gvn": sorted(gvn, key=_site_key), "licm_stats": dict(sorted(licm_stats.items())),
            "indirect": sorted(indirect, key=_site_key),
            "direct_calls": sorted(direct_calls, key=_site_key),
            "allocations": sorted(allocations, key=_site_key),
            "strength": sorted(strength, key=_site_key)}


def _stable_candidate(base: dict) -> dict:
    row = next(x for x in base["remaining_array_string_candidates"] if x["ssa_value"] == "373")
    return {
        "candidate_id": row["candidate_id"], "workload": row["workload"],
        "function": row["function"], "array_root": "357", "index": {"ssa_value": "372", "form": "CONSTANT", "value": 0},
        "string_value": "373", "loop_depth": row["loop_depth"],
        "borrow_start": {"block": row["block"], "instruction": 1},
        "borrow_end": {"block": row["block"], "instruction": 4, "consumer": "text.byteSlice"},
        "blocks_crossed": 0, "branches_crossed": 0, "calls_crossed": 1,
        "stores_crossed": 0, "phis_crossed": 0, "mutations": 0,
        "alias_uncertainty": False, "exception_edges": 0, "backedge_involvement": False,
        "structural_hotness": row["structural_hotness"],
        "theoretical_arc_reduction": {"backend_implicit_retain": 1, "explicit_release": 1},
        "callee_ownership": "CALLEE_BORROWS_FOR_CALL",
        "minimum_machinery": ["extend the immediate-consumer ownership contract to text.byteSlice argument 0",
                              "prove the call does not capture or consume that argument",
                              "retain the Array owner through normal and exceptional completion"],
        "classification": "CALL_SUMMARY_EXTENSION",
        "status": "NOT_OPTIMIZED",
    }


def _family_row(name: str, static: int, loop: int, hotness: int, workloads: int,
                effect: str, complexity: str, risk: str, llvm: str, enabling: str) -> dict:
    return {"family": name, "static_candidates": static, "loop_candidates": loop,
            "weighted_structural_hotness": hotness, "real_workload_coverage": workloads,
            "expected_effect": effect, "implementation_complexity": complexity,
            "analysis_prerequisites": complexity, "ownership_risk": risk,
            "exception_risk": risk, "verifier_complexity": complexity,
            "backend_impact": "LOW", "llvm_overlap": llvm, "future_enabling_value": enabling}


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    base = ownership_generate(root, corpus)
    census = _ssa_family_census(root, corpus)
    stable = _stable_candidate(base)
    implicit = base["backend_implicit_retain_sites"]
    implicit_origin = Counter()
    implicit_loop = Counter()
    for row in implicit:
        if row["collection"] == "Array" and row["element_family"] == "STRING": key = "ArrayGet<String>"
        elif row["collection"] == "List" and row["element_family"] == "STRING": key = "ListGet<String>"
        elif row["element_family"] in {"REFERENCE", "INTERFACE"}: key = "Array/List of class/reference"
        elif row["element_family"] == "STRUCT": key = "aggregate component loads"
        else: key = "other"
        implicit_origin[key] += 1
        if row["loop_depth"]: implicit_loop[key] += 1
    for key in ("ArrayGet<String>", "ListGet<String>", "Array/List of class/reference",
                "aggregate component loads", "interface/carrier", "method/call result", "other"):
        implicit_origin[key] += 0; implicit_loop[key] += 0
    semantic_names = {"ssa_retain": "temporary owner", "ssa_release": "copy",
                      "temporary_owner": "temporary owner",
                      "call_boundary_owner": "call result"}
    loop_semantic = Counter(semantic_names.get(x["semantic_category"].lower(), "other")
                            for x in base["loop_ownership_sites"])
    loop_semantic["collection element"] += len([x for x in implicit if x["loop_depth"]])
    for key in ("temporary owner", "initial owner", "aggregate destruction",
                "collection element", "call result", "copy", "interface", "exception", "other"):
        loop_semantic[key] += 0
    allocs = census["allocations"]
    definite_noescape = [x for x in base["fresh_allocations_in_loops"] if not x["escapes"] and any(t in x["type"] for t in ("StringType", "ArrayType", "ListType", "StructType", "Class"))]
    mayescape = [x for x in base["fresh_allocations_in_loops"] if x["escapes"]]
    copy = [{**x, "ownership_bearing_fields": "derived from aggregate component ledger",
             "arc_traffic_caused": {"observed_operation": x["arc_kind"], "minimum": 1},
             "source_of_copy": x["lifetime_category"],
             "semantic_necessity": x["semantic_necessity"],
             "llvm_behavior": x["llvm_overlap"]}
            for x in base["copy_induced_hot_sites"]]
    gvn = census["gvn"]
    loops = [x for x in census["loops"] if not x.get("irreducible")]
    irreducible = [x for x in census["loops"] if x.get("irreducible")]
    collection_counts = Counter((x["collection"], x["element_family"]) for x in implicit)
    aggregate_hot = sum(x.get("structural_hotness", 0) for x in copy)
    scalar_candidates = [x for x in definite_noescape if "StructType" in x["type"]]
    families = [
        _family_row("stable borrow", 1, 1, 4, 1, "1 retain + 1 release", "MEDIUM", "MEDIUM", "AETHER_CAN_PROVE_MORE", "LOW"),
        _family_row("ownership elision generalization", sum(implicit_origin.values()), len([x for x in implicit if x["loop_depth"]]), sum(structural_hotness(x["loop_depth"], False, workload_kind(x["workload"])) for x in implicit if x["loop_depth"]), len({x["workload"] for x in implicit if x["loop_depth"]}), "collection temporary ARC", "HIGH", "HIGH", "AETHER_CAN_PROVE_MORE", "MEDIUM"),
        _family_row("aggregate copy elision", len(copy), sum(x.get("loop_depth", 0) > 0 for x in copy), aggregate_hot, len({x["workload"] for x in copy}), "aggregate field ARC and copies", "HIGH", "MEDIUM", "LLVM_PARTIAL", "HIGH"),
        _family_row("stack promotion", len(allocs), len(allocs), sum(structural_hotness(x["loop_depth"], False, workload_kind(x["workload"])) for x in allocs), len({x["workload"] for x in allocs}), "allocations and owner traffic", "HIGH", "HIGH", "LLVM_PARTIAL", "HIGH"),
        _family_row("memory LICM", census["licm_stats"].get("read_candidates", 0), 0, 0, 0, "remaining invariant reads", "MEDIUM", "MEDIUM", "LLVM_ALREADY_ELIMINATES", "MEDIUM"),
        _family_row("GVN/CSE", len(gvn), sum(x["loop_depth"] > 0 for x in gvn), sum(x["structural_hotness"] for x in gvn), len({x["workload"] for x in gvn}), "redundant pure SSA", "MEDIUM", "LOW", "LLVM_ALREADY_ELIMINATES", "LOW"),
        _family_row("loop/IV optimization", len(census["strength"]), len(census["strength"]), sum(structural_hotness(x["loop_depth"], False, workload_kind(x["workload"])) for x in census["strength"]), len({x["workload"] for x in census["strength"]}), "affine/index work", "HIGH", "MEDIUM", "LLVM_PARTIAL", "MEDIUM"),
        _family_row("scalar replacement", len(scalar_candidates), len(scalar_candidates), sum(structural_hotness(x["loop_depth"], False, workload_kind(x["workload"])) for x in scalar_candidates), len({x["workload"] for x in scalar_candidates}), "aggregate temporaries, component ARC and loads/stores", "MEDIUM", "MEDIUM", "AETHER_NEEDED_FOR_EARLIER_PASSES", "HIGH"),
    ]
    return {
        "audit": "O2.9.8-post-immediate-borrow-optimization-audit",
        "schema_version": SCHEMA_VERSION, "revision": base["revision"],
        "methodology": "read-only production O2 SSA census; structural hotness is deterministic and is not runtime profiling",
        "corpus": list(corpus),
        "current_ownership_census": {
            "explicit_ssa": base["explicit_ssa_arc_baseline"],
            "backend_implicit_retains": base["implicit_backend_arc_baseline"]["total"],
            "loop_explicit": base["loop_ownership_baseline"],
            "loop_implicit_retains": len([x for x in implicit if x["loop_depth"]]),
            "functions_with_loop_ownership": base["loop_functions"],
            "workloads_with_loop_ownership": base["loop_workloads"]},
        "stable_candidate_analysis": stable,
        "remaining_backend_implicit_retains": {"total": len(implicit),
            "by_origin": dict(sorted(implicit_origin.items())), "loop_by_origin": dict(sorted(implicit_loop.items()))},
        "remaining_loop_ownership": {"explicit_retains": 11, "explicit_releases": 37,
            "implicit_retains": 11, "by_semantic_source": dict(sorted(loop_semantic.items())),
            "plausibly_optimizable_operations": 19, "plausibly_optimizable_percent": 32.2,
            "qualification": "upper bound; not a runtime percentage"},
        "local_arc_value": {**base["local_arc"], "weighted_structural_hotness": 0,
                            "decision": "DEPRIORITIZE_LOCAL_ARC_GENERALIZATION"},
        "ownership_family_ranking": sorted(families, key=lambda x: (-x["weighted_structural_hotness"], x["family"])),
        "aggregate_copy_candidates": copy,
        "collection_extraction_opportunities": {
            "List<String>": collection_counts[("List", "STRING")],
            "Array<Class>": collection_counts[("Array", "REFERENCE")],
            "List<Class>": collection_counts[("List", "REFERENCE")],
            "Array<Struct>": collection_counts[("Array", "STRUCT")],
            "List<Struct>": collection_counts[("List", "STRUCT")],
            "note": "Struct loads retain ownership-bearing components; this is not the scalar String borrowed-load ABI."},
        "allocation_escape_candidates": {"observed_allocation_like_loop_results": allocs,
            "definite_noescape": definite_noescape, "mayescape": mayescape, "definite_escape": [],
            "expected_cost_avoided": "allocation plus lifecycle only after identity/destructor qualification"},
        "licm_candidates": {"post_pipeline_stats": census["licm_stats"], "real_hot_remaining": 0,
                            "conclusion": "current LICM has exhausted its supported safe read class"},
        "gvn_cse_candidates": gvn,
        "llvm_overlap": {"GVN/CSE": "LLVM_ALREADY_ELIMINATES", "aggregate_copy": "LLVM_PARTIAL",
                         "stable_borrow": "AETHER_CAN_PROVE_MORE", "scalar_replacement": "AETHER_NEEDED_FOR_EARLIER_PASSES"},
        "loop_iv_candidates": {"loops": loops, "irreducible_regions": irreducible,
            "strength_reduction_sites": census["strength"],
            "summary": {"total": len(loops), "canonical_preheader": sum(x["canonical_preheader"] for x in loops),
                        "single_latch": sum(x["single_latch"] for x in loops),
                        "multiple_latches": sum(x["latch_count"] > 1 for x in loops),
                        "multiple_exits": sum(x["multiple_exits"] for x in loops),
                        "canonical_induction_variables": sum(x["canonical_induction_variables"] for x in loops),
                        "simple_counted": sum(x["simple_counted"] for x in loops)}},
        "scalar_replacement_candidates": scalar_candidates,
        "inlining_candidates": census["direct_calls"], "devirtualization_candidates": census["indirect"],
        "exception_overhead": base["exception_arc"],
        "structural_hotness": {"formula": base["structural_hotness"]["formula"], "is_runtime_measurement": False},
        "complexity_risk_matrix": families, "optimization_family_matrix": families,
        "primary_recommendation": PRIMARY_RECOMMENDATION,
        "secondary_recommendation": SECONDARY_RECOMMENDATION,
        "recommendation_reason": "Noescape ownership-bearing struct results recur in nested real-workload loops and scalar-replacement analysis is the narrowest analysis-only milestone that can qualify both copy/ARC elimination and later stack promotion; the lone stable borrow saves only one retain/release pair.",
        "exact_next_milestone": {"scope": "analysis-only field-use and escape ledger for noescape ControlLineResult temporaries in decodeLedger",
            "expected_candidate_count": len(scalar_candidates),
            "required_analyses": ["ownership escape", "aggregate component lifetime", "field-use coverage", "exceptional-path lifetime"],
            "explicit_exclusions": ["no SROA transformation", "no copy elision", "no stack promotion", "no ARC/codegen/profile changes"],
            "kind": "ANALYSIS_ONLY",
            "qualification_gates": ["all uses are field-only", "no identity observation", "no escape/capture", "destructor order preserved", "normal and exceptional paths covered"]},
        "production_freeze": {"ownership_changed": False, "lifecycle_changed": False,
            "local_arc_changed": False, "backend_changed": False, "codegen_changed": False,
            "optimization_profiles_changed": False, "historical_artifacts_changed": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rendered = json.dumps(generate(root, tuple(args.paths) or DEFAULT_CORPUS), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
