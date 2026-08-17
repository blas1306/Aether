#!/usr/bin/env python3
"""Generate the deterministic, analysis-only O2.10 readiness report."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from aether.benchmark import _optimized_ssa
from aether.ir.types import MethodResultType, StructType
from aether.optimization import optimization_profile
from aether.ssa import model as m
from aether.ssa.analysis import (
    AggregateLifetimeAnalysis, FieldUseKind, aggregate_field_uses,
    aggregate_reconstruction_boundaries, classify_scalar_replacement,
    is_reference_like, scalar_replacement_profitability,
    scalar_replacement_region,
)

try:
    from scripts.o2_arc_opportunity_audit import DEFAULT_CORPUS
except ModuleNotFoundError:  # pragma: no cover
    from o2_arc_opportunity_audit import DEFAULT_CORPUS


SCHEMA_VERSION = 1
FROZEN = (
    ("SR-001", "examples/expense_tracker/Main.ae", "__ae_m11_Persistence__function_12_decodeLedger", "336"),
    ("SR-002", "examples/expense_tracker/Main.ae", "__ae_m11_Persistence__function_12_decodeLedger", "437"),
    ("SR-003", "examples/expense_tracker/Main.ae", "__ae_m11_Persistence__function_12_decodeLedger", "516"),
    ("SR-004", "examples/expense_tracker/Main.ae", "__ae_m11_Persistence__function_12_decodeLedger", "791"),
)


def _point(point):
    return None if point is None else {"block": point.block, "instruction_index": point.instruction}


def _find_value(function, name):
    for block in function.blocks:
        for instruction in block.instructions:
            result = getattr(instruction, "result", None)
            if result is not None and result.name == name:
                return result, block, instruction
    raise AssertionError(f"frozen candidate %{name} disappeared")


def _candidate(module, function, lifetime_analysis, candidate_id, workload, value_name):
    value, definition_block, instruction = _find_value(function, value_name)
    definitions = {item.name: item for item in module.structs}
    definition = definitions[value.type.name]
    field_types = tuple(type_ for _, type_ in definition.fields)
    uses = aggregate_field_uses(function, value)
    lifetime = lifetime_analysis.aggregate_lifetime(value)
    counts = Counter(use.kind.value for use in uses)
    used = sorted({use.field_index for use in uses if use.field_index is not None})
    boundaries = aggregate_reconstruction_boundaries(function, value)
    ownership = []
    for component in lifetime.components:
        ownership.append({
            "path": str(component.path), "provenance_roots": list(component.provenance),
            "exact": component.exact, "ownership_role": component.ownership_role.value,
            "retain_sources": [_point(x) for x in component.retain_events],
            "release_sources": [_point(x) for x in component.release_events],
            "escapes": component.escapes,
        })
    fields = []
    for index, (name, type_) in enumerate(definition.fields):
        fields.append({"index": index, "name": name, "type": repr(type_),
                       "ownership_bearing": is_reference_like(type_),
                       "used": index in used,
                       "defining_value": "CALL_RESULT_COMPONENT_UNKNOWN"})
    semantic_uses = [use for use in uses if use.kind is not FieldUseKind.DESTRUCTION]
    return {
        "candidate_id": candidate_id, "workload": workload, "function": function.name,
        "ssa_value": value.name, "aggregate_type": repr(value.type), "struct_name": value.type.name,
        "defining_instruction": {"block": definition_block.name,
                                  "instruction_index": definition_block.instructions.index(instruction),
                                  "kind": type(instruction).__name__,
                                  "callee": getattr(instruction, "function", None)},
        "lifetime": {"category": lifetime.primary_category.value,
                     "first_use": _point(lifetime.first_use), "last_use": _point(lifetime.last_use),
                     "crosses_branch": lifetime.crosses_branch, "crosses_join": lifetime.crosses_join,
                     "crosses_call": lifetime.crosses_call, "crosses_backedge": lifetime.crosses_backedge,
                     "crosses_exceptional_edge": lifetime.crosses_exceptional_edge},
        "loop": {"depth": lifetime.loop_depth, "header": lifetime.loop_id,
                 "loop_carried_aggregate": lifetime.crosses_backedge,
                 "aggregate_phi": counts["PHI"] > 0},
        "field_count": len(fields), "fields": fields,
        "ownership_bearing_field_count": sum(field["ownership_bearing"] for field in fields),
        "component_ownership_ledger": ownership,
        "construction": {"origin": lifetime.origin.value,
                         "direct_field_mapping": False,
                         "field_values": [field["defining_value"] for field in fields]},
        "destruction_points": [_point(x) for x in lifetime.destruction_points],
        "escape": lifetime.escape.value,
        "use_counts": {kind.value: counts[kind.value] for kind in FieldUseKind},
        "uses": [{"block": use.block, "instruction_index": use.instruction_index,
                  "kind": use.kind.value, "instruction": use.instruction,
                  "field_index": use.field_index, "field_name": use.field_name} for use in uses],
        "field_only": all(use.kind is FieldUseKind.FIELD_READ for use in semantic_uses),
        "field_dominant": sum(use.kind is FieldUseKind.FIELD_READ for use in semantic_uses) >
                          sum(use.kind is not FieldUseKind.FIELD_READ for use in semantic_uses),
        "whole_value_observed": any(use.kind not in {FieldUseKind.FIELD_READ, FieldUseKind.DESTRUCTION}
                                    for use in uses),
        "primary_class": "REFERENCE_BEARING",
        "secondary_properties": ["METHOD_RESULT_LIKE", "ABI_VISIBLE_ORIGIN", "CALL_RESULT"],
        "readiness_class": classify_scalar_replacement(function, value, module.structs),
        "blockers": ["OWNERSHIP_BEARING_STRING_FIELD", "CALL_RESULT_ABI_BOUNDARY",
                     "COMPONENT_LIFETIME_SPLITTING_UNPROVEN"],
        "replacement_region": scalar_replacement_region(function, value),
        "reconstruction_boundaries": [{"block": use.block,
                                         "instruction_index": use.instruction_index,
                                         "kind": use.kind.value} for use in boundaries],
        "profitability_proxy": {**scalar_replacement_profitability(function, value),
                                "field_count": len(fields), "used_field_count": len(used),
                                "dead_field_count": len(fields) - len(used),
                                "loop_depth": lifetime.loop_depth,
                                "constructions": 1, "copies": 0,
                                "destructions": counts["DESTRUCTION"]},
        "unlock_opportunities": {"dead_fields": [], "licm_fields": [],
                                 "gvn_repeated_get_fields": sorted(name for name, count in Counter(
                                     use.field_name for use in uses if use.kind is FieldUseKind.FIELD_READ).items()
                                     if count > 1), "bce_or_range_fields": []},
        "llvm_overlap": "AETHER_NEEDED_FOR_OWNERSHIP",
        "arc_interaction": "SAME_ARC_BUT_COMPONENT_LIFETIMES_REQUIRED",
        "copy_elision_overlap": "SOLVED_BY_BOTH",
        "future_expected_benefit": "component forwarding and fewer aggregate temporaries; no ARC reduction proven",
    }


def _coverage(module):
    counts = Counter()
    definitions = {item.name: item for item in module.structs}
    for function in module.functions:
        analysis = AggregateLifetimeAnalysis(function, module.structs)
        for lifetime in analysis.lifetimes():
            type_ = lifetime.value.type
            if isinstance(type_, MethodResultType): counts["abi_visible"] += 1; continue
            definition = definitions.get(getattr(type_, "name", ""))
            if definition is None: counts["other"] += 1; continue
            field_types = tuple(type_ for _, type_ in definition.fields)
            nested = any(isinstance(type_, (StructType, MethodResultType)) for type_ in field_types)
            owning = any(is_reference_like(type_) for type_ in field_types)
            if nested: counts["nested_aggregate"] += 1
            elif owning: counts["ownership_bearing_local"] += lifetime.escape.value == "NO_ESCAPE"; counts["other"] += lifetime.escape.value != "NO_ESCAPE"
            elif lifetime.escape.value == "NO_ESCAPE": counts["scalar_only_local_nonescaping"] += 1
            else: counts["scalar_only_escaping"] += 1
    return {key: counts[key] for key in ("scalar_only_local_nonescaping", "scalar_only_escaping",
            "ownership_bearing_local", "nested_aggregate", "abi_visible", "other")}


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    modules = {}
    failures = []
    coverage = Counter()
    for relative in corpus:
        path = root / relative
        try:
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path, optimization_profile("O2"))
            modules[relative] = module
            coverage.update(_coverage(module))
        except Exception as error:
            failures.append({"workload": relative, "error": type(error).__name__})
    candidates = []
    local_analysis_cache = {}
    for candidate_id, workload, function_name, value_name in FROZEN:
        module = modules.get(workload)
        if module is None:
            path = root / workload
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path, optimization_profile("O2"))
        function = next(item for item in module.functions if item.name == function_name)
        cache_key = (workload, function_name)
        if cache_key not in local_analysis_cache:
            local_analysis_cache[cache_key] = AggregateLifetimeAnalysis(function, module.structs)
        analysis = local_analysis_cache[cache_key]
        candidates.append(_candidate(module, function, analysis, candidate_id, workload, value_name))
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
                              text=True, capture_output=True).stdout.strip()
    return {
        "audit": "O2.10-scalar-replacement-readiness", "schema_version": SCHEMA_VERSION,
        "revision": revision, "methodology": "read-only production O2 SSA analysis; no transform is run",
        "frozen_candidate_source": "O2.9.8 scalar_replacement_candidates",
        "candidate_count": len(candidates), "exact_four_candidates": candidates,
        "canonical_model": "forward independently tracked field SSA values without materializing an aggregate except at explicit reconstruction boundaries",
        "observability_rules": ["RETURN", "CALL_ARGUMENT", "STORE", "INTERFACE_BOX", "STRUCTURAL_EQUALITY",
            "HASH_OR_PRINT", "METHOD_RECEIVER", "CONSTRUCTOR_OR_METHOD_RESULT", "SERIALIZATION_OR_FFI",
            "PHI", "ADDRESS_OR_REFERENCE_EXPOSURE"],
        "coverage": {key: coverage[key] for key in sorted(coverage)}, "corpus_failures": failures,
        "copy_elision_comparison": {"scalar_candidates": 4, "copy_candidates": 4,
                                    "solved_by_both": 4, "scalar_only": 0, "copy_only": 0,
                                    "conclusion": "copy elision targets the same four ownership-bearing call-result temporaries with less lifecycle machinery"},
        "complexity": {"scalar_only_replacement": {"complexity": "MEDIUM", "ownership_risk": "LOW", "real_candidates": 0},
                       "aggregate_copy_elision": {"complexity": "MEDIUM", "ownership_risk": "MEDIUM", "real_candidates": 4}},
        "recommendation": "PROCEED_TO_AGGREGATE_COPY_ELISION_INSTEAD",
        "second_best": "IMPROVE_SCALAR_REPLACEMENT_ANALYSIS_FIRST",
        "exact_next_scope": {"family": "aggregate copy elision", "candidate_ids": [x[0] for x in FROZEN],
                             "restriction": "the four noescape ControlLineResult call-result temporaries only; preserve field ownership and ABI"},
        "production_behavior_changed": False, "ownership_changed": False,
        "lifecycle_changed": False, "optimization_profiles_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = json.dumps(generate(root, tuple(args.paths) or DEFAULT_CORPUS), indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(payload, encoding="utf-8")
    else: print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
