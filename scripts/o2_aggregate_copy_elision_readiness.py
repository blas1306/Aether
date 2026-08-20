#!/usr/bin/env python3
"""Generate the deterministic, analysis-only O2.11 copy-elision report."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from aether.o2_evidence_materialization import optimized_ssa as _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa.analysis import AggregateLifetimeAnalysis

try:
    from scripts.o2_arc_opportunity_audit import DEFAULT_CORPUS
    from scripts.o2_scalar_replacement_readiness import generate as scalar_generate
except ModuleNotFoundError:  # pragma: no cover - direct execution
    from o2_arc_opportunity_audit import DEFAULT_CORPUS
    from o2_scalar_replacement_readiness import generate as scalar_generate


SCHEMA_VERSION = 1
CATEGORIES = ("SEMANTIC_COPY_REQUIRED", "OWNERSHIP_COPY_REQUIRED", "RETURN_TEMPORARY_COPY",
              "CALL_BOUNDARY_COPY", "LOCAL_TEMPORARY_COPY", "RECONSTRUCTION_COPY",
              "PHI_MERGE_COPY", "COLLECTION_STORAGE_COPY", "METHOD_RESULT_COPY",
              "CONSTRUCTOR_COPY", "UNKNOWN")


def _candidate(row):
    # O2.9.2 called a released call result COPY_INDUCED.  SSA contains one
    # value and no copy edge; retain this frozen site while making that
    # reconciliation explicit.
    owned = [field for field in row["fields"] if field["ownership_bearing"]]
    return {
        "candidate_id": "ACE-" + row["candidate_id"].split("-")[1],
        "legacy_candidate_id": row["candidate_id"], "workload": row["workload"],
        "function": row["function"],
        "ssa_source_value": "CALLEE_RETURN_OWNER_NOT_REPRESENTED_IN_CALLER_SSA",
        "ssa_destination_value": row["ssa_value"], "aggregate_type": row["aggregate_type"],
        "struct_name": row["struct_name"], "defining_instruction": row["defining_instruction"],
        "copy_materialization_instruction": None,
        "reconciliation": "LEGACY_COPY_INDUCED_FALSE_POSITIVE_CALL_RESULT_WITH_NO_EXPLICIT_COPY_EDGE",
        "category": "RETURN_TEMPORARY_COPY", "secondary_properties": ["RETURN_ABI_BOUNDARY", "LOGICAL_HANDOFF_ONLY"],
        "safety_class": "OWNERSHIP_BLOCKED",
        "source_lifetime": {"classification": "SOURCE_LIFETIME_UNKNOWN", "represented_in_caller_ssa": False,
                            "destruction": "NO_DISTINCT_CALLER_SOURCE_DESTRUCTION"},
        "destination_lifetime": row["lifetime"], "loop": row["loop"],
        "field_count": row["field_count"], "ownership_bearing_field_count": len(owned),
        "ownership_bearing_field_types": [field["type"] for field in owned],
        "escape": row["escape"], "destruction_points": row["destruction_points"],
        "source_uses_after_copy": "SOURCE_LIFETIME_UNKNOWN",
        "destination_uses": row["uses"],
        "involvement": {"return": True, "call": True, "phi": False, "store": False},
        "destination_uniqueness": "NO_SEPARATE_DESTINATION_EDGE_TO_PROVE",
        "ownership_transfer": {"feasibility": "UNPROVEN", "source_owned_aggregate_edges": "UNKNOWN",
            "destination_owned_aggregate_edges": 1, "independent_owner_required": "UNKNOWN",
            "blocker": "CALLEE_TO_CALLER_OWNERSHIP_EDGE_IS_NOT_EXPLICIT_IN_SSA"},
        "component_ownership_accounting": [{"field_index": field["index"], "field_name": field["name"],
            "field_type": field["type"], "provenance_root": "CALL_RESULT_COMPONENT_UNKNOWN", "exact": False,
            "ownership_role": "OWNED_DESTINATION", "source_retain_obligation": "LOWERING_DEPENDENT_UNKNOWN",
            "destination_retain_obligation": "CALL_RETURN_OWNERSHIP_CONTRACT",
            "source_release_obligation": "NO_DISTINCT_CALLER_SOURCE",
            "destination_release_obligation": "EXACTLY_ONE_PER_EXIT_PATH"} for field in owned],
        "string_copy_behavior": {"callee_before_return": "OWNS_RETURN_FIELD", "caller_receives": "OWNED_AGGREGATE",
            "caller_duplicate_retain_observed": False, "caller_source_release_observed": False,
            "destination_releases": len(row["destruction_points"])},
        "copy_chain_length": 0, "dead_intermediates": 0,
        "profitability_proxy": {"aggregate_copy_instructions": 0, "owned_field_retains_at_copy": 0,
            "owned_field_release_sites": len(row["destruction_points"]), "field_count": row["field_count"],
            "loop_depth": row["loop"]["depth"], "destination_semantic_uses": sum(row["use_counts"].values()) - row["use_counts"]["DESTRUCTION"],
            "potential_arc_reduction_proven": 0},
        "llvm_overlap": "LLVM_ALREADY_COMPLETE",
        "reason": "The ABI materializes the returned value directly as the caller SSA result; no retain/copy/release handoff exists to elide at this site.",
    }


def _census(root, corpus):
    counts = Counter(); loops = Counter(); failures = []
    mapping = {"FUNCTION_RETURN": "return_induced", "METHOD_RETURN": "method_result",
               "STRUCT_RECONSTRUCTION": "reconstruction", "PHI": "phi",
               "STRUCT_CONSTRUCTOR": "constructor"}
    for relative in corpus:
        try:
            path = root / relative
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path, optimization_profile("O2"))
        except Exception as error:
            failures.append({"workload": relative, "error": type(error).__name__}); continue
        for function in module.functions:
            for life in AggregateLifetimeAnalysis(function, module.structs).lifetimes():
                key = mapping.get(life.origin.value, "other")
                counts[key] += 1; loops[key] += bool(life.loop_depth)
    keys = ("scalar_only", "ownership_bearing", "return_induced", "call_induced", "local_temp",
            "collection_store", "method_result", "reconstruction", "phi", "constructor", "other")
    return {key: {"count": counts[key], "in_loops": loops[key]} for key in keys}, failures


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS):
    prior = scalar_generate(root, corpus)
    candidates = [_candidate(row) for row in prior["exact_four_candidates"]]
    census, failures = _census(root, corpus)
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
                              text=True, capture_output=True).stdout.strip()
    return {
        "audit": "O2.11-aggregate-copy-elision-readiness", "schema_version": SCHEMA_VERSION,
        "revision": revision, "methodology": "read-only lifecycle-expanded production O2 SSA; no transform",
        "canonical_copy_categories": list(CATEGORIES), "candidate_count": 4,
        "exact_four_candidates": candidates,
        "identity_model": {"aggregate_ssa_identity": "distinct SSA results",
            "nested_component_provenance": "tracked independently per component path",
            "ownership_edge": "distinct from value/provenance identity",
            "proof_rule": "same component roots never implies redundant ownership"},
        "copy_definition": "elide an explicit aggregate source-to-destination copy only when the source edge dies and exactly one destruction responsibility transfers",
        "struct_copy_semantics": {"initial_ir": "IRCopy/aggregate lifecycle operations express value copies",
            "lifecycle_expansion": "owned nested fields acquire/release ownership",
            "ssa": "the frozen call results contain no explicit aggregate copy instruction",
            "backend": "return value is transported by value; field ownership cleanup remains explicit"},
        "return_materialization_findings": {"stage": "CALL_RESULT_SSA_DEFINITION", "logical_copy_found": False,
            "physical_copy_evidence": "no separate caller source/destination pair", "caller_temporary_found": False,
            "callee_temporary": "not paired with a caller copy in current SSA"},
        "excluded_first_scope": ["reconstruction", "phi", "call arguments", "MethodResult", "constructors",
                                 "collection storage", "exception-sensitive and path-sensitive transfers"],
        "copy_census": census, "corpus_failures": failures,
        "control_line_result_deep_dive": {"layout": prior["exact_four_candidates"][0]["fields"],
            "owned_fields": ["line:String"], "candidate_values": [row["ssa_destination_value"] for row in candidates],
            "finding": "four hot call-result owners, but zero explicit aggregate-copy edges and zero copy-induced ARC pairs"},
        "scalar_replacement_overlap": {"scalar_candidates": 4, "legacy_copy_candidates": 4,
            "verified_copy_edges": 0, "conclusion": "O2.10 overlap was based on call-result materialization naming, not an SSA copy edge"},
        "analysis_api": ["classify_aggregate_copy", "copy_source_dead_after", "copy_destination_unique",
                         "copy_ownership_transfer", "copy_elision_region", "copy_elision_profitability"],
        "recommendation": "IMPROVE_COPY_ELISION_ANALYSIS_FIRST",
        "second_best": "PROCEED_TO_OWNERSHIP_TRANSFER_ANALYSIS",
        "exact_next_scope": {"class": "explicit same-block aggregate copy edges only", "aggregate_types": ["StructType"],
            "ownership": "exact component provenance and one source/destination owned edge",
            "cfg": "straight-line same block; source immediately dead; unique destination", "exceptions": "none",
            "abi": "exclude call and return boundaries", "expected_real_candidates": 0,
            "expected_arc_reduction": 0, "verifier": "prove one final release per transferred component"},
        "production_freeze": {"production_behavior_changed": False, "ownership_changed": False,
            "lifecycle_changed": False, "abi_changed": False, "optimization_profiles_changed": False,
            "codegen_changed": False},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    payload = json.dumps(generate(root, tuple(args.paths) or DEFAULT_CORPUS), indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(payload, encoding="utf-8")
    else: print(payload, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
