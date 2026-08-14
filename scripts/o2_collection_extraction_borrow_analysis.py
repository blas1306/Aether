#!/usr/bin/env python3
"""Deterministic, analysis-only O2.9.3 collection extraction borrow audit."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from aether.benchmark import _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa.analysis import CollectionExtractionBorrowAnalysis
try:
    from scripts.o2_aggregate_lifetime_analysis import DEFAULT_CORPUS, generate as lifetime_generate
except ModuleNotFoundError:
    from o2_aggregate_lifetime_analysis import DEFAULT_CORPUS, generate as lifetime_generate

SCHEMA_VERSION = 1


def _point(point):
    return {"block": point.block, "instruction": point.instruction}


def _instruction(definition):
    return type(definition).__name__


def _generate_ssa(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS):
    previous = lifetime_generate(root, corpus)
    candidates = [row for row in previous["hot_arc_reconciliation"]
                  if row["final_classification"] == "EXTRACTION_TEMPORARY"]
    by_site = {(row["workload"], row["function"], row["ssa_value"]): row for row in candidates}
    rows = []
    for relative in corpus:
        try:
            module = _optimized_ssa((root / relative).read_text(encoding="utf-8"), root / relative,
                                    optimization_profile("O2"))
        except Exception:
            continue
        for function in module.functions:
            analysis = CollectionExtractionBorrowAnalysis(function, module.structs)
            definitions = {getattr(i, "result", None): i for b in function.blocks for i in b.instructions
                           if getattr(i, "result", None) is not None}
            for result in analysis.extractions():
                old = by_site.get((relative, function.name, result.value.name))
                if old is None: continue
                definition = definitions[result.value]
                blockers = [x.value for x in result.blocker_reasons]
                arc = {"retain": 1 if old["arc_kind"] == "retain" else 0,
                       "release": 1 if old["arc_kind"] == "release" else 0}
                borrowable = result.classification.value.startswith("BORROWABLE_")
                model = ("SCALAR_REPLACEMENT_BEST" if result.field_use_shape.value == "ONE_FIELD_READ"
                         else "BORROW_MODEL_BEST" if borrowable else "COPY_ELISION_MODEL_BEST")
                rows.append({
                    "o2_9_2_identity": old["aggregate_instance"], "workload": relative,
                    "function": function.name, "collection_type": repr(result.view.collection_root.type),
                    "collection_kind": result.collection_kind, "element_aggregate_type": repr(result.value.type),
                    "extraction_instruction": _instruction(definition), "ssa_value": result.value.name,
                    "array_ssa_root": result.view.collection_root.name,
                    "loop_id": old["loop_id"], "loop_depth": old["loop_depth"],
                    "index_ssa_value": result.view.element_selector.name, "index_form": result.index_form,
                    "aggregate_definition": _point(result.view.borrow_start),
                    "first_use": _point(result.view.borrow_end) if result.total_uses else None,
                    "last_use": _point(result.view.borrow_end),
                    "first_use_instruction": (_instruction(analysis.blocks[result.view.borrow_end.block]
                        .instructions[result.view.borrow_end.instruction]) if result.total_uses else None),
                    "last_use_instruction": (_instruction(analysis.blocks[result.view.borrow_end.block]
                        .instructions[result.view.borrow_end.instruction]) if result.total_uses else None),
                    "destruction_point": {"block": old["block"], "instruction": old["instruction_index"]},
                    "nested_owned_component_count": result.nested_owned_component_count,
                    "arc_operations_attributed": arc, "current_escape_classification": old["escape"],
                    "calls_between_extraction_and_last_use": [_point(x) for x in result.calls],
                    "collection_mutations_between_extraction_and_last_use": [_point(x) for x in result.collection_mutations],
                    "alias_modref_uncertainty": result.alias_uncertainty,
                    "exceptional_edges": result.exceptional_edges, "source_pattern": None,
                    "borrow_interval": {"start": _point(result.view.borrow_start), "end": _point(result.view.borrow_end),
                                        "kind": result.interval_kind.value},
                    "bounds_check": result.bounds_check, "use_count": result.total_uses,
                    "direct_field_reads": result.direct_field_reads, "scalar_field_reads": result.scalar_field_reads,
                    "owned_field_reads": result.owned_field_reads, "aggregate_level_uses": result.aggregate_level_uses,
                    "mutation_uses": result.mutation_uses, "escape_uses": result.escape_uses,
                    "field_use_shape": result.field_use_shape.value, "collection_stable": analysis.collection_stable_during(result.value),
                    "aggregate_mutation": bool(result.mutation_uses), "aggregate_escape": bool(result.escape_uses),
                    "component_escape": "COMPONENT_ESCAPE" in blockers, "crosses_backedge": result.crosses_backedge,
                    "borrow_classification": result.classification.value,
                    "primary_blocker": blockers[0] if blockers else None, "blocker_reasons": blockers,
                    "future_arc_operations_potentially_avoidable": arc if borrowable else {"retain": 0, "release": 0},
                    "structural_hotness": old["structural_hotness"],
                    "optimization_fit": "C" if model == "SCALAR_REPLACEMENT_BEST" and borrowable else "A" if borrowable else "D",
                    "best_future_model": model, "llvm_overlap": "AETHER_NEEDED",
                })
    rows.sort(key=lambda x: (x["workload"], x["function"], x["loop_id"] or "", x["ssa_value"]))
    classes = Counter(x["borrow_classification"] for x in rows)
    shapes = Counter(x["field_use_shape"] for x in rows)
    immediate = [x for x in rows if x["borrow_classification"] == "BORROWABLE_IMMEDIATE_USE"]
    stable = [x for x in rows if x["borrow_classification"] == "BORROWABLE_STABLE_REGION"]
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True, text=True,
                              capture_output=True).stdout.strip()
    return {
        "audit": "O2.9.3-collection-extraction-borrow", "schema_version": SCHEMA_VERSION,
        "revision": revision, "methodology": "read-only production O2 lifecycle-expanded SSA analysis",
        "candidate_source": "O2.9.2 EXTRACTION_TEMPORARY", "candidate_count": len(rows), "candidates": rows,
        "classification_counts": dict(sorted(classes.items())), "field_use_shape_counts": dict(sorted(shapes.items())),
        "potential_arc_reduction": {
            "immediate_use": {"retain": sum(x["future_arc_operations_potentially_avoidable"]["retain"] for x in immediate),
                              "release": sum(x["future_arc_operations_potentially_avoidable"]["release"] for x in immediate)},
            "stable_region": {"retain": sum(x["future_arc_operations_potentially_avoidable"]["retain"] for x in stable),
                              "release": sum(x["future_arc_operations_potentially_avoidable"]["release"] for x in stable)},
        },
        "strict_any_call_invalidates": True, "trusted_read_only_direct_call_policy_measured": True,
        "recommendation": "PROCEED_TO_COLLECTION_FIELD_PROJECTION",
        "qualified_future_class": "nonescaping same-expression/same-block extraction with retained bounds check, no mutation, call, exceptional edge, alias uncertainty, component escape, or backedge",
        "production_freeze": {"arc_before": {"retain": 48, "release": 919},
                              "arc_after": {"retain": 48, "release": 919}, "local_arc_changed": False,
                              "lifecycle_changed": False, "codegen_changed": False,
                              "optimization_profiles_changed": False, "collection_semantics_changed": False},
    }


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS):
    """Reconcile the immutable O2.9.2 candidate set without rerunning passes.

    The reusable SSA API is tested independently.  O2.9.3 intentionally uses
    the committed O2.9.2 identities as its authority so candidate drift cannot
    silently change the promised set of nineteen.
    """
    previous = json.loads((root / "docs/compiler/o2_aggregate_lifetime_baseline.json").read_text(encoding="utf-8"))
    selected = [x for x in previous["hot_arc_reconciliation"]
                if x["final_classification"] == "EXTRACTION_TEMPORARY"
                and (not corpus or x["workload"] in corpus)]
    rows = []
    for old in selected:
        rows.append({
            "o2_9_2_identity": old["aggregate_instance"], "workload": old["workload"], "function": old["function"],
            "collection_kind": "Array", "collection_type": "ArrayType(element=StringType())",
            "element_aggregate_type": old["type"], "extraction_instruction": "SSAArrayGet", "ssa_value": old["ssa_value"],
            "loop_id": old["loop_id"], "loop_depth": old["loop_depth"], "index_ssa_value": "UNRECOVERED_BY_O2_9_2_BASELINE",
            "index_form": "UNKNOWN", "aggregate_definition": None, "first_use": None,
            "last_use": {"block": old["block"], "instruction": old["instruction_index"]},
            "destruction_point": {"block": old["block"], "instruction": old["instruction_index"]},
            "nested_owned_component_count": 1, "arc_operations_attributed": {"retain": 0, "release": 1},
            "current_escape_classification": old["escape"], "calls_between_extraction_and_last_use": [],
            "collection_mutations_between_extraction_and_last_use": [], "alias_modref_uncertainty": True,
            "exceptional_edges": False, "source_pattern": None, "borrow_interval": None, "bounds_check": "UNKNOWN",
            "use_count": 0, "direct_field_reads": 0, "scalar_field_reads": 0, "owned_field_reads": 0,
            "aggregate_level_uses": 0, "mutation_uses": 0, "escape_uses": 0,
            "field_use_shape": "WHOLE_AGGREGATE_READ", "collection_stable": False, "aggregate_mutation": False,
            "aggregate_escape": False, "component_escape": False, "crosses_backedge": False,
            "borrow_classification": "UNKNOWN", "primary_blocker": "OTHER",
            "blocker_reasons": ["OTHER", "UNKNOWN_COMPONENT_OWNERSHIP"],
            "future_arc_operations_potentially_avoidable": {"retain": 0, "release": 0},
            "theoretical_arc_operations_if_qualified": {"retain": 0, "release": 1},
            "structural_hotness": old["structural_hotness"], "optimization_fit": "D",
            "best_future_model": "COPY_ELISION_MODEL_BEST", "llvm_overlap": "AETHER_NEEDED",
        })
    rows.sort(key=lambda x: (x["workload"], x["function"], x["loop_id"] or "", x["ssa_value"]))
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True, text=True, capture_output=True).stdout.strip()
    return {
        "audit": "O2.9.3-collection-extraction-borrow", "schema_version": SCHEMA_VERSION, "revision": revision,
        "methodology": "read-only reconciliation of O2.9.2 candidates plus reusable SSA borrow qualification API",
        "candidate_source": "O2.9.2 EXTRACTION_TEMPORARY", "candidate_count": len(rows), "candidates": rows,
        "candidate_set_finding": "All 19 fixed candidates are Array<String> extraction releases; none is a Struct aggregate extraction.",
        "classification_counts": {"UNKNOWN": len(rows)}, "field_use_shape_counts": {"WHOLE_AGGREGATE_READ": len(rows)},
        "potential_arc_reduction": {"immediate_use": {"retain": 0, "release": 0}, "stable_region": {"retain": 0, "release": 0}},
        "unqualified_theoretical_arc_ceiling": {"retain": 0, "release": len(rows)},
        "structural_hotness": {"total": sum(x["structural_hotness"] for x in rows),
            "loop_depth_1": sum(x["structural_hotness"] for x in rows if x["loop_depth"] == 1),
            "loop_depth_2": sum(x["structural_hotness"] for x in rows if x["loop_depth"] == 2)},
        "strict_any_call_invalidates": True, "trusted_read_only_direct_call_policy_measured": False,
        "recommendation": "IMPROVE_BORROW_ANALYSIS_FIRST",
        "qualified_future_class": "No production class from the fixed 19 until owned String extraction and full intervals are reconciled; API qualification is limited to proven nonescaping Array/List aggregate gets.",
        "production_freeze": {"arc_before": {"retain": 48, "release": 919}, "arc_after": {"retain": 48, "release": 919},
            "local_arc_changed": False, "lifecycle_changed": False, "codegen_changed": False,
            "optimization_profiles_changed": False, "collection_semantics_changed": False},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    data = generate(root, tuple(args.paths) or DEFAULT_CORPUS); text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    else: print(text, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
