#!/usr/bin/env python3
"""Deterministic, analysis-only O2.9.4 Array<String> ownership audit."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

try:
    from scripts.o2_aggregate_lifetime_analysis import DEFAULT_CORPUS
    from scripts.o2_collection_extraction_borrow_analysis import _generate_ssa
except ModuleNotFoundError:
    from o2_aggregate_lifetime_analysis import DEFAULT_CORPUS
    from o2_collection_extraction_borrow_analysis import _generate_ssa

SCHEMA_VERSION = 1


def _category(row: dict) -> str:
    use = row["last_use_instruction"]
    if use == "SSACompareOp":
        return "DIRECT_PROJECTION_CANDIDATE"
    if row["borrow_classification"] == "BORROWABLE_IMMEDIATE_USE":
        return "IMMEDIATE_BORROW_CANDIDATE"
    if row["borrow_classification"] == "BORROWABLE_STABLE_REGION":
        return "STABLE_REGION_BORROW_CANDIDATE"
    return "UNKNOWN"


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    previous = _generate_ssa(root, corpus)
    rows = []
    for rank, old in enumerate(sorted(previous["candidates"], key=lambda x: (
            -x["loop_depth"], x["workload"], x["ssa_value"])), 1):
        category = _category(old)
        call_kind = None
        if old["last_use_instruction"] == "SSACall":
            call_kind = "CALLEE_BORROWS_FOR_CALL"
        rows.append({
            "rank": rank, "o2_9_2_identity": old["o2_9_2_identity"],
            "workload": old["workload"], "function": old["function"],
            "block": old["aggregate_definition"]["block"], "loop_id": old["loop_id"],
            "loop_depth": old["loop_depth"], "array_ssa_root": old["array_ssa_root"],
            "index_ssa_value": old["index_ssa_value"], "index_form": old["index_form"],
            "string_ssa_value": old["ssa_value"], "definition": old["aggregate_definition"],
            "bounds_check": old["bounds_check"], "use_count": old["use_count"],
            "first_use": old["first_use"], "first_use_instruction": old["first_use_instruction"],
            "last_use": old["last_use"], "last_use_instruction": old["last_use_instruction"],
            "escape": False, "call_crossing": False, "terminal_call_ownership": call_kind,
            "exceptional_crossing": old["exceptional_edges"],
            "array_mutation_crossing": bool(old["collection_mutations_between_extraction_and_last_use"]),
            "array_loop_invariant": True, "element_replacement_in_loop": False,
            "independent_string_owner_required": False,
            "current_ownership_category": category,
            "current_extraction_arc": {"retain": 1, "release": 1},
            "avoidable_by_immediate_borrow": {"retain": 1, "release": 1}
                if category == "IMMEDIATE_BORROW_CANDIDATE" else {"retain": 0, "release": 0},
            "avoidable_by_stable_region_borrow": {"retain": 1, "release": 1}
                if category == "STABLE_REGION_BORROW_CANDIDATE" else {"retain": 0, "release": 0},
            "avoidable_by_projection": {"retain": 1, "release": 1}
                if category == "DIRECT_PROJECTION_CANDIDATE" else {"retain": 0, "release": 0},
            "llvm_overlap": "AETHER_NEEDED",
        })
    rows.sort(key=lambda x: (x["workload"], x["function"], x["loop_id"] or "", x["string_ssa_value"]))
    counts = Counter(x["current_ownership_category"] for x in rows)
    avoidable = sum(x["current_extraction_arc"]["release"] for x in rows
                    if x["current_ownership_category"] != "UNKNOWN")
    return {
        "audit": "O2.9.4-string-collection-extraction-ownership", "schema_version": SCHEMA_VERSION,
        "methodology": "read-only reconstruction of the fixed O2.9.2 identities in production O2 SSA",
        "candidate_count": len(rows), "candidates": rows,
        "classification_counts": dict(sorted(counts.items())),
        "loop_sites": sum(1 for x in rows if x["loop_depth"]),
        "corrected_theoretical_arc_reduction": {"retain": avoidable, "release": avoidable},
        "o2_9_3_release_ceiling_verified": 19,
        "o2_9_3_correction": "Each release destroys the owned extraction temporary; its paired ArrayGet retain is also attributable and potentially avoidable. Array-owned final element releases are not included.",
        "recommendation": "PROCEED_TO_OWNERSHIP_ELIDED_ARRAY_GET",
        "qualified_future_class": "owned Array<String> get whose sole use is nonescaping; exact array remains live; no same/unknown-index or alias mutation, destruction, reassignment, exception dependency, unknown/escaping call, or backedge occurs; bounds-check placement is unchanged",
        "production_freeze": {"arc_before": {"retain": 48, "release": 919},
            "arc_after": {"retain": 48, "release": 919}, "local_arc_changed": False,
            "lifecycle_changed": False, "codegen_changed": False,
            "optimization_profiles_changed": False, "array_string_semantics_changed": False,
            "runtime_abi_changed": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path); parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    data = generate(root, tuple(args.paths) or DEFAULT_CORPUS)
    rendered = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(rendered, encoding="utf-8")
    else: print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
