#!/usr/bin/env python3
"""Check the permanent RUST-3.9a evidence and implementation contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_transport_representation_optimization.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_TRANSPORT_REPRESENTATION_OPTIMIZATION.md"
)
VALID_CLASSIFICATIONS = {
    "PROVEN_REDUNDANT_REPRESENTATION",
    "PROVEN_REDUNDANT_TRAVERSAL",
    "SAFE_IMMUTABLE_REUSE",
    "PROTOCOL_INTERNAL_OPTIMIZATION",
    "SAFETY_BOUNDARY_DO_NOT_TOUCH",
    "SEMANTIC_BOUNDARY_DO_NOT_TOUCH",
    "INSUFFICIENT_EVIDENCE",
}
TARGET_PHASES = {
    "rust_transport_serialization",
    "rust_schema_v2_materialization",
    "request_response_transport_and_serialization",
    "python_result_canonicalization",
    "rust_result_canonicalization",
}


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    scope = evidence.get("scope", {})
    measurement = evidence.get("measurement", {})
    modes = measurement.get("modes", {})
    phases = measurement.get("affected_phase_medians", {})
    candidates = evidence.get("candidate_audit", [])
    correctness = evidence.get("correctness", {})
    shadow_source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    companion_source = (
        ROOT
        / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")

    dual = modes.get("rust_authority_python_shadow", {})
    before = dual.get("before", {})
    after = dual.get("after", {})
    checks = {
        "decision": evidence.get("decision")
        == "RUST_SSA_TRANSPORT_REPRESENTATION_OPTIMIZED",
        "baseline_revision": evidence.get("baseline_revision")
        == "14902424f91b0a8cd622a12be114484d541a0705",
        "production_invariants": scope
        == {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "mandatory_synchronous",
            "failure_policy": "FAIL_CLOSED",
            "initial_ir_schema": 1,
            "ssa_schema": 2,
            "protocol": 1,
            "protocol_replaced": False,
            "schema_import_bypassed": False,
            "verification_removed": False,
            "lowering_or_dominator_algorithm_changed": False,
            "packaging_or_discovery_changed": False,
        },
        "flow_audit_complete": len(evidence.get("representation_flow", [])) >= 10
        and all(
            {
                "source",
                "destination",
                "allocation",
                "full_traversal",
                "json",
                "copy",
                "normalization",
                "ownership_reason",
                "subsequent_traversal",
            }
            <= set(row)
            for row in evidence.get("representation_flow", [])
        ),
        "candidate_classifications": len(candidates) >= 10
        and all(row.get("classification") in VALID_CLASSIFICATIONS for row in candidates),
        "measurement_rounds": measurement.get("warmups", 0) >= 2
        and measurement.get("measured_rounds", 0) >= 7,
        "dual_samples": before.get("samples") == after.get("samples") == 15
        and len(before.get("round_total_samples_seconds", [])) == 15
        and len(after.get("round_total_samples_seconds", [])) == 15,
        "dual_median_reduced": after.get("median_seconds", 1)
        < before.get("median_seconds", 0),
        "target_phase_effect": TARGET_PHASES <= set(phases)
        and all(phases[name].get("after_seconds", 1) < phases[name].get("before_seconds", 0)
                for name in TARGET_PHASES),
        "schema_import_retained": "value = ssa_module_from_dto(rust_comparison_dto)"
        in shadow_source,
        "imported_verifier_retained": "SSAVerifier(value).verify()" in shadow_source,
        "python_shadow_retained": "GeneralSSABuilder().build(python_input)"
        in shadow_source,
        "typed_response_direct": "ssa: aether_ir::wire::SSAModuleV2DTO"
        in companion_source
        and "serde_json::to_value(owned.to_schema_v2())" not in companion_source,
        "json_protocol_retained": "json.loads(response)" in shadow_source
        and "serde_json::from_slice(&body)" in companion_source,
        "correctness_gates": correctness.get("historical_corpus") == "116/116 PASS"
        and correctness.get("deep_cfg_993_1000_5000") == "PASS"
        and correctness.get("cargo_test_workspace_locked") == "PASS"
        and correctness.get("linux_clean_install") == "PASS"
        and "PASS" in correctness.get("full_python_suite", ""),
        "report_present": report_path.read_text(encoding="utf-8").startswith(
            "# Rust SSA transport and representation optimization — RUST-3.9a"
        ),
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.9a",
        "decision": (
            "RUST_SSA_TRANSPORT_REPRESENTATION_OPTIMIZED"
            if passed
            else "RUST_SSA_TRANSPORT_REPRESENTATION_BLOCKED"
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
    return int(
        args.require_optimized
        and record["decision"]
        != "RUST_SSA_TRANSPORT_REPRESENTATION_OPTIMIZED"
    )


if __name__ == "__main__":
    raise SystemExit(main())
