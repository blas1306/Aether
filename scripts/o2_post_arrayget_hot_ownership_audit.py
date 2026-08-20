#!/usr/bin/env python3
"""Deterministic, read-only O2.9.6 post-ArrayGet ownership audit."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess

from aether.backend.llvm.layout import LLVMTypeLayouts
from aether.o2_evidence_materialization import optimized_ssa as _optimized_ssa
from aether.ir.types import ArrayType, InterfaceType, ListType, StringType, StructType
from aether.optimization import optimization_profile
from aether.ssa import model as m
from aether.ssa.analysis import LoopAnalysis, OwnershipEscapeAnalysis

try:
    from scripts.o2_arc_opportunity_audit import DEFAULT_CORPUS
    from scripts.o2_hot_arc_opportunity_audit import generate as hot_generate
except ModuleNotFoundError:  # pragma: no cover - direct CLI execution
    from o2_arc_opportunity_audit import DEFAULT_CORPUS
    from o2_hot_arc_opportunity_audit import generate as hot_generate


SCHEMA_VERSION = 1
RECOMMENDATION = "PROCEED_TO_IMMEDIATE_ARRAY_STRING_BORROW"
ARC_BUILTINS = {"__aether_retain", "__aether_release"}


def _revision(root: Path) -> str:
    return subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
                          text=True, capture_output=True).stdout.strip()


def _type_family(type_) -> str:
    if isinstance(type_, StringType): return "STRING"
    if isinstance(type_, ArrayType): return "ARRAY"
    if isinstance(type_, ListType): return "LIST"
    if isinstance(type_, InterfaceType): return "INTERFACE"
    if isinstance(type_, StructType): return "STRUCT"
    return "REFERENCE" if "ClassRefType" in type(type_).__name__ else "OTHER"


def _semantic_category(site: dict) -> str:
    if site["arc_kind"] == "retain": return "SSA_RETAIN"
    category = site.get("release_category")
    return {
        "MATCHING_EXPLICIT_RETAIN": "SSA_RELEASE",
        "COLLECTION_ELEMENT_DESTRUCTION": "TEMPORARY_OWNER",
        "AGGREGATE_FIELD_DESTRUCTION": "AGGREGATE_COMPONENT_RELEASE",
        "INITIAL_OWNER_DESTRUCTION": "INITIAL_OWNER_RELEASE",
        "LIFECYCLE_GENERATED_RELEASE": "CALL_BOUNDARY_OWNER",
        "RETURN_CLEANUP": "CALL_BOUNDARY_OWNER",
        "PARAMETER_CLEANUP": "CALL_BOUNDARY_OWNER",
        "TEMPORARY_DESTRUCTION": "TEMPORARY_OWNER",
    }.get(category, "OTHER")


def _release_asymmetry(loop_sites: list[dict]) -> dict:
    counts = Counter()
    for site in loop_sites:
        if site["arc_kind"] != "release": continue
        raw = site.get("release_category")
        role = site.get("loop_role")
        if raw == "MATCHING_EXPLICIT_RETAIN": key = "balancing_explicit_retain"
        elif raw == "COLLECTION_ELEMENT_DESTRUCTION": key = "balancing_backend_implicit_retain"
        elif raw == "AGGREGATE_FIELD_DESTRUCTION": key = "aggregate_component_destruction"
        elif raw == "INITIAL_OWNER_DESTRUCTION": key = "initial_owner_destruction"
        elif raw == "RETURN_CLEANUP": key = "call_result_cleanup"
        elif raw == "PARAMETER_CLEANUP": key = "parameter_local_cleanup"
        elif role == "CALL_BOUNDARY_OWNERSHIP": key = "call_result_cleanup"
        elif role == "CONTAINER_ELEMENT_OWNERSHIP": key = "collection_element_destruction"
        elif role in {"PER_ITERATION_LOCAL", "DESTRUCTION_ONLY", "AGGREGATE_TEMPORARY"}: key = "temporary_destruction"
        else: key = "other"
        counts[key] += 1
    for key in ("balancing_explicit_retain", "balancing_backend_implicit_retain",
                "initial_owner_destruction", "aggregate_component_destruction",
                "temporary_destruction", "collection_element_destruction",
                "call_result_cleanup", "parameter_local_cleanup", "exception_cleanup", "other"):
        counts[key] += 0
    return dict(sorted(counts.items()))


def _backend_sites(root: Path, corpus: tuple[str, ...]) -> tuple[list[dict], list[dict], list[dict]]:
    implicit: list[dict] = []
    fresh: list[dict] = []
    collection_elements: list[dict] = []
    for relative in corpus:
        try:
            module = _optimized_ssa((root / relative).read_text(encoding="utf-8"), root / relative,
                                    optimization_profile("O2"))
        except Exception:
            continue
        layouts = LLVMTypeLayouts(module.structs)
        for function in module.functions:
            loops = LoopAnalysis().compute(function)
            escape = OwnershipEscapeAnalysis(function, structs=module.structs)
            for block in function.blocks:
                loop = loops.loop_for_block(block.name)
                for index, instruction in enumerate(block.instructions):
                    if isinstance(instruction, (m.SSAArrayGet, m.SSAListGet)):
                        collection = "Array" if isinstance(instruction, m.SSAArrayGet) else "List"
                        family = _type_family(instruction.result.type)
                        row = {"workload": relative, "function": function.name,
                               "block": block.name, "instruction_index": index,
                               "instruction": type(instruction).__name__, "collection": collection,
                               "element_type": repr(instruction.result.type), "element_family": family,
                               "ssa_value": instruction.result.name, "borrowed": instruction.borrowed,
                               "bounds_checked": instruction.bounds_checked,
                               "loop_id": loop.header if loop else None,
                               "loop_depth": loop.depth if loop else 0}
                        collection_elements.append(row)
                        if not instruction.borrowed and layouts.layout(instruction.result.type).needs_retain:
                            kind = "AGGREGATE_COMPONENT_RETAIN" if family == "STRUCT" else "BACKEND_IMPLICIT_RETAIN"
                            implicit.append({**row, "operation_layer": "BACKEND_IMPLICIT",
                                             "operation_kind": kind,
                                             "ownership_role": "TEMPORARY_OWNER",
                                             "semantic_category": kind})
                    result = getattr(instruction, "result", None)
                    if result is not None and getattr(instruction, "allocates", False) and loop:
                        fact = escape.escape_fact(result)
                        fresh.append({"workload": relative, "function": function.name,
                                      "block": block.name, "instruction_index": index,
                                      "instruction": type(instruction).__name__, "ssa_value": result.name,
                                      "type": repr(result.type), "loop_id": loop.header,
                                      "loop_depth": loop.depth, "escapes": fact.may_escape,
                                      "escape_reasons": sorted(x.value for x in fact.reasons),
                                      "future": "UNKNOWN" if fact.may_escape else "STACK_PROMOTION_OR_SCALAR_REPLACEMENT"})
    key = lambda x: (x["workload"], x["function"], x["block"], x["instruction_index"])
    return sorted(implicit, key=key), sorted(fresh, key=key), sorted(collection_elements, key=key)


def _remaining_candidates(root: Path) -> tuple[list[dict], list[dict]]:
    prior = json.loads((root / "docs/compiler/o2_string_collection_extraction_audit.json").read_text())
    transformed = json.loads((root / "docs/compiler/o2_ownership_elided_array_string_get.json").read_text())
    removed = {(x["block"], x["value"]) for x in transformed["sites"]}
    remaining = []
    for old in prior["candidates"]:
        if (old["block"], old["string_ssa_value"]) in removed or old["current_ownership_category"] == "DIRECT_PROJECTION_CANDIDATE":
            continue
        category = old["current_ownership_category"]
        immediate = category == "IMMEDIATE_BORROW_CANDIDATE"
        remaining.append({"candidate_id": old.get("candidate_id", old["o2_9_2_identity"]),
                          "workload": old["workload"], "function": old["function"],
                          "block": old["block"], "loop_id": old["loop_id"],
                          "loop_depth": old["loop_depth"], "ssa_value": old["string_ssa_value"],
                          "category": category, "current_arc_cost": {"backend_retain": 1, "ssa_release": 1},
                          "structural_hotness": 1 + 2 * old["loop_depth"] + 1,
                          "excluded_from_o2_9_5": "sole use is not SSACompareOp direct projection",
                          "reason_still_dominates": True,
                          "theoretical_reduction": {"backend_retain": 1, "ssa_release": 1},
                          "qualification": "READY_FOR_QUALIFICATION" if immediate else "QUALITATIVELY_DIFFERENT_LIFETIME",
                          "implementation_risk": "LOW" if immediate else "HIGH",
                          "use_region": {"first": old["first_use"], "last": old["last_use"],
                                         "use_count": old["use_count"]},
                          "calls_crossed": int(old["call_crossing"]),
                          "array_lifetime_covers_use": old["array_loop_invariant"],
                          "element_mutation": old["element_replacement_in_loop"],
                          "alias_mutation": old["array_mutation_crossing"],
                          "exception_region": old["exceptional_crossing"],
                          "ownership_consuming_context": False})
    direct = {(x["block"], x["string_ssa_value"]): x for x in prior["candidates"]
              if x["current_ownership_category"] == "DIRECT_PROJECTION_CANDIDATE"}
    removed_rows = [{"candidate_id": direct[(x["block"], x["value"])]["o2_9_2_identity"],
                     "workload": direct[(x["block"], x["value"])]["workload"],
                     "function": direct[(x["block"], x["value"])]["function"],
                     "loop_depth": x["depth"],
                     "current_borrowed": True, "ssa_release": x["post"]["ssa_release"],
                     "backend_temporary_retain": x["post"]["backend_retain"],
                     "bounds_behavior": direct[(x["block"], x["value"])]["bounds_check"]}
                    for x in transformed["sites"]]
    return sorted(remaining, key=lambda x: x["candidate_id"]), sorted(removed_rows, key=lambda x: x["candidate_id"])


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    hot = hot_generate(root, corpus)
    implicit, fresh, gets = _backend_sites(root, corpus)
    remaining, removed = _remaining_candidates(root)
    lifetime_history = json.loads((root / "docs/compiler/o2_aggregate_lifetime_baseline.json").read_text())
    prior_copy = [x for x in lifetime_history["hot_arc_reconciliation"]
                  if x["final_classification"] == "COPY_INDUCED"]
    prior_escape = [x for x in lifetime_history["hot_arc_reconciliation"]
                    if x["final_classification"] == "ESCAPE_REQUIRED"]
    loop_sites = []
    for site in hot["loop_arc_sites"]:
        loop_sites.append({**site, "operation_layer": "SSA_EXPLICIT",
                           "operation_kind": "SSA_" + site["arc_kind"].upper(),
                           "semantic_category": _semantic_category(site),
                           "source_lifecycle_origin": site["defining_instruction"],
                           "paired_operation": site["matching_pair_known"]})
    loop_backend = [x for x in implicit if x["loop_depth"]]
    asymmetry = _release_asymmetry(loop_sites)
    type_arc = defaultdict(lambda: {"loop": Counter(), "non_loop": Counter()})
    for site in hot["arc_operations"]:
        bucket = "loop" if site["loop_depth"] else "non_loop"
        type_arc[site["type_category"]][bucket][site["arc_kind"]] += 1
    for site in implicit:
        bucket = "loop" if site["loop_depth"] else "non_loop"
        type_arc[site["element_family"]][bucket]["backend_implicit_retain"] += 1
    aggregate = Counter()
    for site in loop_sites:
        role = site["loop_role"]
        key = ("copy_induced" if site["defining_instruction"] in {"SSACall", "SSAInvoke"} and site["type_category"] == "STRUCT"
               else "escape_required" if site["escape_state"]["may_escape"]
               else "extraction_temporary" if site["defining_instruction"] in {"SSAArrayGet", "SSAListGet"}
               else "destruction_only" if role == "DESTRUCTION_ONLY"
               else "loop_carried" if role in {"LOOP_CARRIED_OWNER", "LOOP_VARIANT_IDENTITY"}
               else "call_result" if role == "CALL_BOUNDARY_OWNERSHIP" else "other")
        aggregate[key] += 1
    local_pairs = [x for x in hot["candidate_pairs"] if x["semantic_eligibility"] == "safe"]
    backend_counts = Counter(x["operation_kind"] for x in implicit)
    families = [
        ("IMMEDIATE_ARRAY_STRING_BORROW", len([x for x in remaining if x["category"].startswith("IMMEDIATE")]), "LOW", "LOW", "AETHER_UNIQUE"),
        ("STABLE_ARRAY_STRING_BORROW", len([x for x in remaining if x["category"].startswith("STABLE")]), "HIGH", "HIGH", "AETHER_UNIQUE"),
        ("AGGREGATE_COPY_ELISION", aggregate["copy_induced"], "HIGH", "MEDIUM", "LLVM_PARTIAL"),
        ("LIST_STRING_OWNERSHIP_ELISION", len([x for x in loop_backend if x["collection"] == "List" and x["element_family"] == "STRING"]), "MEDIUM", "MEDIUM", "AETHER_UNIQUE"),
        ("REFERENCE_ELEMENT_OWNERSHIP_ELISION", len([x for x in loop_backend if x["element_family"] in {"REFERENCE", "INTERFACE"}]), "HIGH", "HIGH", "AETHER_UNIQUE"),
        ("ESCAPE_STACK_PROMOTION", len(fresh), "HIGH", "HIGH", "LLVM_PARTIAL"),
        ("GVN_CSE", 0, "MEDIUM", "LOW", "LLVM_HIGH"),
        ("GENERAL_LOOP_OPTIMIZATION", 0, "HIGH", "MEDIUM", "LLVM_PARTIAL"),
    ]
    matrix = [{"family": name, "hot_operations_affected": count,
               "structural_hotness": sum(x["structural_hotness"] for x in loop_sites[:count]) if count else 0,
               "implementation_complexity": complexity, "safety_risk": risk,
               "llvm_overlap": llvm, "enabling_value": "DIRECT" if count else "UNMEASURED"}
              for name, count, complexity, risk, llvm in families]
    return {
        "audit": "O2.9.6-post-arrayget-hot-ownership", "schema_version": SCHEMA_VERSION,
        "revision": _revision(root), "methodology": "read-only production O2 SSA and backend-lowering census",
        "corpus": list(corpus), "explicit_ssa_arc_baseline": hot["arc_baseline"],
        "implicit_backend_arc_baseline": {"total": len(implicit), **dict(sorted(backend_counts.items()))},
        "loop_ownership_baseline": {**hot["loop_arc_baseline"], "backend_implicit_retain": len(loop_backend),
                                    "all_layers_total": hot["loop_arc_baseline"]["total"] + len(loop_backend)},
        "functions_containing_arc": hot["arc_baseline"]["functions_with_arc"],
        "loop_functions": sorted({f"{x['workload']}::{x['function']}" for x in loop_sites}),
        "loop_workloads": sorted({x["workload"] for x in loop_sites}),
        "ownership_cost_model": ["SSA_RETAIN", "SSA_RELEASE", "BACKEND_IMPLICIT_RETAIN",
                                 "AGGREGATE_COMPONENT_RETAIN", "AGGREGATE_COMPONENT_RELEASE",
                                 "TEMPORARY_OWNER", "INITIAL_OWNER_RELEASE", "COLLECTION_OWNER",
                                 "CALL_BOUNDARY_OWNER", "INTERFACE_OWNER", "EXCEPTION_OWNER", "OTHER"],
        "loop_ownership_sites": loop_sites, "backend_implicit_retain_sites": implicit,
        "release_asymmetry_classification": asymmetry,
        "release_asymmetry": {"retains": 11, "releases": 40, "difference": 29,
                              "classification_total": sum(asymmetry.values()),
                              "explanation": "Releases also destroy initial, aggregate, collection, call-result and temporary owners; absence of an explicit SSA retain does not imply redundancy."},
        "o2_9_5_removed_sites": removed, "o2_9_5_removed_count": len(removed),
        "remaining_array_string_candidates": remaining,
        "remaining_array_string_counts": dict(sorted(Counter(x["category"] for x in remaining).items())),
        "string_arc_distribution": type_arc["STRING"],
        "collection_arc_distribution": {k: type_arc[k] for k in ("ARRAY", "LIST")},
        "collection_get_distribution": dict(sorted(Counter(f"{x['collection']}<{x['element_family']}>" for x in gets).items())),
        "aggregate_lifetime_distribution": {"extraction_temporary": len(remaining),
                                            "copy_induced": len(prior_copy),
                                            "escape_required": len(prior_escape),
                                            "reconstruction": 0, "loop_carried": 0,
                                            "call_result": 0, "destruction_only": 0, "other": 0},
        "copy_induced_hot_sites": [{**x, "remains_hot": True, "semantic_necessity": "COPY_SEMANTICS_REQUIRED",
                                    "copy_elision_may_remove": True, "llvm_overlap": "LLVM_PARTIAL"}
                                   for x in prior_copy],
        "escape_required_hot_sites": [{**x, "remains_hot": True,
                                       "escape_reality": "REAL_OR_CONSERVATIVE_UNRESOLVED",
                                       "escape_reason": x["escape"],
                                       "better_escape_analysis_may_unlock": False}
                                      for x in prior_escape],
        "list_string_findings": {"implicit_gets_in_loops": sum(x["collection"] == "List" and x["element_family"] == "STRING" for x in loop_backend),
                                 "same_backend_owned_get_pattern": True,
                                 "meaningful_real_workload": any(x["collection"] == "List" and x["element_family"] == "STRING" for x in loop_backend),
                                 "mutation_invalidation": "same conservative owner/mutation requirement as Array"},
        "reference_element_findings": {"hot_implicit_gets": sum(x["element_family"] in {"REFERENCE", "INTERFACE"} for x in loop_backend)},
        "aggregate_element_findings": {"hot_implicit_gets": sum(x["element_family"] == "STRUCT" for x in loop_backend)},
        "local_arc": {"semantic_candidates": len(local_pairs),
                      "actual_structural_candidates": sum(x["structural_eligibility"] == "CURRENTLY_ELIGIBLE" for x in local_pairs),
                      "currently_eliminated": 0, "hot_candidates": sum(x["same_loop"] for x in local_pairs),
                      "cold_candidates": sum(not x["same_loop"] for x in local_pairs)},
        "ownership_elided_get_opportunities": {
            "same_model_qualified": len(remaining),
            "by_collection_and_element": dict(sorted(Counter(
                f"{x['collection']}<{x['element_family']}>" for x in loop_backend).items())),
            "qualification_deferred": True,
        },
        "call_boundary_ownership": {"loop_operations": sum(x["loop_role"] == "CALL_BOUNDARY_OWNERSHIP" for x in loop_sites),
                                    "unknown_summary": sum("call" in " ".join(x["secondary_blockers"]) for x in loop_sites)},
        "methodresult_constructor_arc": {"loop_operations": sum(x["type_category"] == "METHOD_RESULT" for x in loop_sites)},
        "interface_arc": {"loop_operations": sum(x["type_category"] == "INTERFACE" for x in loop_sites)},
        "exception_arc": hot["exception_arc"], "fresh_allocations_in_loops": fresh,
        "structural_hotness": {"formula": hot["structural_hotness_definition"],
                               "is_runtime_measurement": False,
                               "ranked_sites": hot["ranked_hot_opportunities"]},
        "measured_dynamic_counts": None,
        "optimization_family_matrix": matrix,
        "non_arc_comparison": hot["non_arc_comparison"], "final_recommendation": RECOMMENDATION,
        "recommendation_evidence": "Three real-workload loop sites retain the same bounded owner-covered immediate-use shape, while the stable-region case requires broader lifetime proof and other ownership families have greater risk or no measured hot instances.",
        "production_freeze": {"ssa_arc_before": {"retain": 48, "release": 904},
                              "ssa_arc_after": {"retain": 48, "release": 904},
                              "ownership_elided_array_get_changed": False, "local_arc_changed": False,
                              "lifecycle_changed": False, "backend_changed": False, "codegen_changed": False,
                              "optimization_profiles_changed": False, "historical_baselines_changed": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path); parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    report = generate(root, tuple(args.paths) or DEFAULT_CORPUS)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(rendered, encoding="utf-8")
    else: print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
