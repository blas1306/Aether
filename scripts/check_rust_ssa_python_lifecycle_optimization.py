#!/usr/bin/env python3
"""Validate permanent structural and evidence contracts for RUST-3.13."""

from __future__ import annotations

import argparse
import inspect
import json
import math
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_python_lifecycle_optimization.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZATION.md"
BASELINE_REVISION = "b5987ef192f3a68a92bb5149787513939dcfcd16"
METRICS = {
    "lifecycle_normalization",
    "python_only_total",
    "python_shadow",
    "dual_lane_total",
}
DEEP_SIZES = {100, 1000, 5000, 10000}
ADVERSARIAL = {
    "multiple_stores_same_storage", "load_before_initialization", "partial_branch_initialization",
    "loop_carried_lifecycle", "conditional_ownership_transfer", "multiple_exits", "exception_paths",
    "unreachable_definitions", "nested_aggregates", "alias_like_self_assignment", "many_storages",
    "wide_cfg", "deep_cfg", "scalars_strings_arrays_lists_structs_classes_interfaces",
}
SEQUENCES = {
    "A_then_B", "B_then_A", "A_then_A", "multiple_compilations",
    "failure_then_valid", "valid_then_failure",
}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _sample_valid(value: object, expected_count: int) -> bool:
    if not isinstance(value, dict):
        return False
    raw = value.get("raw_samples_seconds")
    if not isinstance(raw, list) or len(raw) != expected_count:
        return False
    if not all(_number(item) for item in raw):
        return False
    return (
        value.get("sample_count") == expected_count
        and _number(value.get("median_seconds"))
        and _number(value.get("min_seconds"))
        and _number(value.get("max_seconds"))
        and abs(float(value["median_seconds"]) - statistics.median(raw)) <= 1e-12
        and value["min_seconds"] == min(raw)
        and value["max_seconds"] == max(raw)
    )


def _measurement_valid(value: object, expected_count: int) -> bool:
    if not isinstance(value, dict):
        return False
    before = value.get("before")
    after = value.get("after")
    if not (_sample_valid(before, expected_count) and _sample_valid(after, expected_count)):
        return False
    assert isinstance(before, dict) and isinstance(after, dict)
    before_median = float(before["median_seconds"])
    after_median = float(after["median_seconds"])
    speedup = value.get("speedup")
    expected_speedup = before_median / after_median if after_median else None
    return (
        (expected_speedup is None and speedup is None)
        or (
            _number(speedup)
            and abs(float(speedup) - expected_speedup) <= max(1e-12, expected_speedup * 1e-12)
        )
    )


def _rows_valid(rows: object, expected_count: int) -> bool:
    return isinstance(rows, list) and bool(rows) and all(
        isinstance(row, dict)
        and row.get("reference_optimized_equivalent") is True
        and isinstance(row.get("semantic_digest"), str)
        and isinstance(row.get("input_shape"), dict)
        and isinstance(row.get("measurements"), dict)
        and set(row["measurements"]) == METRICS
        and all(
            _measurement_valid(value, expected_count)
            for value in row["measurements"].values()
        )
        for row in rows
    )


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    methodology = evidence.get("methodology", {})
    audit = evidence.get("audit", {})
    classification = audit.get("classification", {}) if isinstance(audit, dict) else {}
    candidates = evidence.get("optimizations_considered", [])
    differential = evidence.get("differential_equivalence", {})
    adversarial = evidence.get("adversarial_coverage", {})
    independence = evidence.get("invocation_independence", {})
    safety = evidence.get("safety_invariants", {})
    qualification = evidence.get("qualification", {})

    source = (ROOT / "src/aether/ir/lifecycle.py").read_text(encoding="utf-8")
    shadow = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    builder = (ROOT / "src/aether/ssa/general_builder.py").read_text(encoding="utf-8")
    function_source = source.split("    def _expand_function", 1)[1].split(
        "    def _repair_constructor_invocation_ownership", 1
    )[0]
    report = report_path.read_text(encoding="utf-8")

    ordinary_rounds = methodology.get("ordinary_rounds", 0)
    deep_rounds = methodology.get("deep_rounds", 0)
    deep = evidence.get("deep_cfg", [])
    checks = {
        "milestone_decision_baseline": evidence.get("milestone") == "RUST-3.13"
        and evidence.get("decision") == "RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZED"
        and evidence.get("baseline_revision") == BASELINE_REVISION,
        "worktree_identity": isinstance(evidence.get("implementation_revision"), str)
        and len(evidence.get("implementation_revision", "")) == 40
        and isinstance(evidence.get("worktree_identity"), list),
        "comparable_raw_measurements": methodology.get("same_process_interleaved_before_after") is True
        and methodology.get("raw_samples_retained") is True
        and methodology.get("absolute_speed_thresholds") is False
        and methodology.get("warmups", 0) >= 1
        and isinstance(ordinary_rounds, int) and ordinary_rounds >= 3
        and isinstance(deep_rounds, int) and deep_rounds >= 3
        and _rows_valid(evidence.get("ordinary"), ordinary_rounds)
        and _rows_valid(deep, deep_rounds)
        and isinstance(evidence.get("ordinary_summary"), dict)
        and set(evidence.get("ordinary_summary", {})) == METRICS
        and all(
            _measurement_valid(value, ordinary_rounds)
            for value in evidence.get("ordinary_summary", {}).values()
        ),
        "deep_cfg_sizes": isinstance(deep, list)
        and {row.get("blocks") for row in deep if isinstance(row, dict)} == DEEP_SIZES,
        "target_phase_measured_without_speed_gate": all(
            "lifecycle_normalization" in row.get("measurements", {})
            for row in [*evidence.get("ordinary", []), *deep]
            if isinstance(row, dict)
        ),
        "audit_categories": isinstance(classification, dict)
        and set(classification) == {
            "A_redundant_eliminated", "B_deliberate_independent_preserved",
            "C_inherent", "D_not_proven_redundant",
        }
        and all(isinstance(value, list) and value for value in classification.values()),
        "candidates_audited": isinstance(candidates, list)
        and len(candidates) >= 5
        and any(row.get("decision") == "ACCEPTED" for row in candidates if isinstance(row, dict))
        and any("SAFETY_BOUNDARY" in row.get("decision", "") for row in candidates if isinstance(row, dict)),
        "production_structural_optimization": "operand_occurrences" in function_source
        and function_source.count("_instruction_operand_occurrences(instruction)") == 1
        and "self._used_values.update(occurrences)" in function_source
        and "self._remaining_uses.subtract(occurrences)" in function_source
        and "_instruction_operands" not in function_source,
        "differential_equivalence": isinstance(differential, dict)
        and differential
        and all(value is True for value in differential.values()),
        "adversarial_coverage": isinstance(adversarial, dict)
        and set(adversarial) == ADVERSARIAL
        and all(value == "PASS" for value in adversarial.values()),
        "invocation_independence": isinstance(independence, dict)
        and all(independence.get(name) == "PASS" for name in SEQUENCES)
        and independence.get("mutable_cross_invocation_state") is False,
        "shadow_and_verifiers_preserved": safety.get("python_shadow") == "MANDATORY_SYNCHRONOUS_INDEPENDENT"
        and safety.get("verifiers_preserved") is True
        and safety.get("rust_results_consumed_by_python_normalization") is False
        and "python_ssa = run_python()" in shadow
        and "SSAVerifier(value).verify()" in shadow
        and "return SSAVerifier(module).verify()" in builder,
        "fail_closed_and_frozen_contracts": safety.get("fail_closed") is True
        and safety.get("rust_authority") == "UNCHANGED"
        and safety.get("schemas_protocol_canonicalization_comparison") == "UNCHANGED"
        and safety.get("lifecycle_ownership_verifier_phi_renaming_semantics") == "UNCHANGED"
        and "SSAShadowFailure" in shadow
        and "compiler-rs" not in source,
        "no_hardware_threshold": "threshold" not in inspect.getsource(_measurement_valid).lower(),
        "qualification_gates": isinstance(qualification, dict)
        and len(qualification) >= 16
        and all(value == "PASS" for value in qualification.values()),
        "report_present": report.startswith("# Python lifecycle normalization optimization — RUST-3.13")
        and "RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZED" in report,
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.13",
        "decision": (
            "RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZED"
            if passed
            else "RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZATION_BLOCKED"
        ),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--require-optimized", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report)
    print(json.dumps(record, indent=2, sort_keys=True))
    return int(args.require_optimized and record["decision"] != "RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZED")


if __name__ == "__main__":
    raise SystemExit(main())
