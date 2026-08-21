#!/usr/bin/env python3
"""Aggregate evidence-only RUST-3.5b SSA authority requalification."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_ssa_authority_requalification.json"
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_authority_requalification_evidence"
PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _optional(path: Path) -> dict[str, Any]:
    try:
        return _json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _same_revision(value: dict[str, Any], revision: str) -> bool:
    return value.get("qualification_revision", value.get("revision")) == revision


def _set(value: object) -> set[object]:
    return set(value) if isinstance(value, list) else set()


def _gate(
    identifier: str, name: str, passed: bool, evidence: str
) -> dict[str, str]:
    return {
        "id": identifier,
        "name": name,
        "status": "PASS" if passed else "BLOCKED",
        "evidence": evidence,
    }


def _platforms(
    directory: Path, revision: str
) -> tuple[dict[str, Any], bool]:
    rows: dict[str, Any] = {}
    for name, target in PLATFORMS.items():
        path = directory / f"{name}.json"
        value = _optional(path)
        comparison = value.get("comparison", {})
        checks = value.get("checks", {})
        valid = (
            value.get("milestone") == "RUST-3.5b"
            and value.get("revision") == revision
            and value.get("platform") == name
            and value.get("rust_target") == target
            and value.get("execution")
            == "clean_release_artifact_outside_checkout"
            and value.get("provenance") == "executed-native-runner"
            and value.get("mandatory_promotion_fixture_count") == 8
            and isinstance(checks, dict)
            and checks
            and set(checks.values()) == {"PASS"}
            and isinstance(comparison, dict)
            and comparison.get("mode")
            == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
            and comparison.get("repository_default")
            == "PYTHON_SSA_AUTHORITY_RUST_SHADOW"
            and comparison.get("default_returned_ssa_origin")
            == "python_general_ssa_builder"
            and _set(comparison.get("modes_exercised"))
            == {
                "PYTHON_SSA_ONLY",
                "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
                "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            }
            and _set(comparison.get("returned_ssa_origins"))
            == {"rust_schema_v2_import"}
            and comparison.get("fixture_mode_matrix_checks") == 14
            and comparison.get("semantic_mismatches") == 0
            and comparison.get("infrastructure_failures") == 0
        )
        rows[name] = (
            {
                "status": "PASS",
                "rust_target": target,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
            if valid
            else {
                "status": "BLOCKED",
                "rust_target": target,
                "reason": "fresh exact-revision native evidence missing or invalid",
            }
        )
    return rows, all(row["status"] == "PASS" for row in rows.values())


def build_record(revision: str, evidence_dir: Path) -> dict[str, Any]:
    historical_v1 = _json(
        ROOT / "docs/compiler/rust_ssa_authority_promotion_qualification.json"
    )
    failed_promotion = _json(
        ROOT / "docs/compiler/rust_ssa_authority_promotion.json"
    )
    classification = _json(
        ROOT / "docs/compiler/rust_ssa_promotion_failure_root_cause_audit.json"
    )
    closure = _json(
        ROOT / "docs/compiler/rust_ssa_promotion_lifecycle_defect_closure.json"
    )
    fixtures = _optional(evidence_dir / "promotion_fixtures.json")
    historical = _optional(evidence_dir / "historical.json")
    soak_record = _optional(evidence_dir / "soak.json")
    adversarial = _optional(evidence_dir / "adversarial.json")
    deep_cfg = _optional(evidence_dir / "deep_cfg.json")
    full_suite = _optional(evidence_dir / "full_suite.json")
    operational = _optional(evidence_dir / "operational.json")
    performance = _optional(evidence_dir / "performance.json")
    platforms, platforms_pass = _platforms(evidence_dir / "platforms", revision)
    fixture_gates = fixtures.get("gates", [])
    fixture_rows = fixtures.get("fixtures", [])
    if not isinstance(fixture_gates, list):
        fixture_gates = []
    if not isinstance(fixture_rows, list):
        fixture_rows = []

    source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    safe_default = re.search(
        r"mode:\s*SSALoweringAuthorityMode\s*=\s*"
        r"SSALoweringAuthorityMode\.PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        source,
    ) is not None
    original_gates_pass = (
        historical_v1.get("decision") == "READY_FOR_RUST_SSA_AUTHORITY_SWITCH"
        and len(historical_v1.get("gates", [])) == 20
        and all(row.get("status") == "PASS" for row in historical_v1["gates"])
    )
    preserved_history = (
        failed_promotion.get("decision") == "RUST_SSA_AUTHORITY_PROMOTION_FAILED"
        and classification.get("decision")
        == "RUST_SSA_PROMOTION_FAILURES_CLASSIFIED"
        and closure.get("decision")
        == "RUST_SSA_PROMOTION_LIFECYCLE_DEFECTS_CLOSED"
    )
    fixture_pass = (
        _same_revision(fixtures, revision)
        and fixtures.get("decision")
        == "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED"
        and fixtures.get("mandatory_fixture_count") == 8
        and fixtures.get("historical_minimized_fixture_count") == 7
        and len(fixture_gates) == 5
        and all(
            isinstance(row, dict) and row.get("status") == "PASS"
            for row in fixture_gates
        )
        and all(
            isinstance(row, dict) and row.get("status") == "PASS"
            for row in fixture_rows
        )
    )
    historical_checks = historical.get("checks", {})
    historical_pass = (
        _same_revision(historical, revision)
        and historical.get("decision") == "RUST_SSA_AUTHORITY_HISTORICAL_PASS"
        and historical.get("accepted") == historical.get("expected") == 116
        and isinstance(historical_checks, dict)
        and len(historical_checks) == 8
        and all(
            isinstance(row, dict)
            and row.get("passed") == 116
            and row.get("failed") == 0
            for row in historical_checks.values()
        )
    )
    soak = soak_record.get("soak", {})
    soak_pass = (
        _same_revision(soak_record, revision)
        and soak_record.get("decision") == "RUST_SSA_AUTHORITY_SOAK_PASS"
        and isinstance(soak, dict)
        and soak.get("accepted", 0) >= 139
        and soak.get("shadow_compared") == soak.get("accepted")
        and soak.get("semantic_mismatches") == 0
        and soak.get("infrastructure_failures") == 0
    )
    adversarial_pass = (
        _same_revision(adversarial, revision)
        and adversarial.get("decision")
        == "RUST_SSA_LOWERING_ADVERSARIAL_QUALIFIED"
        and adversarial.get("positive_case_count") == 21
        and adversarial.get("negative_case_count") == 7
    )
    stress = deep_cfg.get("stress", {})
    cargo_workspace = deep_cfg.get("cargo_workspace", {})
    deep_cfg_pass = (
        _same_revision(deep_cfg, revision)
        and deep_cfg.get("decision") == "RUST_SSA_AUTHORITY_DEEP_CFG_PASS"
        and isinstance(cargo_workspace, dict)
        and cargo_workspace.get("status") == "PASS"
        and isinstance(stress, dict)
        and all(
            isinstance(stress.get(str(size)), dict)
            and stress[str(size)].get("python") == "PASS"
            and stress[str(size)].get("rust") == "PASS"
            for size in (993, 1000, 5000)
        )
    )
    full_suite_pass = (
        _same_revision(full_suite, revision)
        and full_suite.get("decision")
        == "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_PASS"
        and full_suite.get("mode") == "PYTHON_SSA_AUTHORITY_RUST_SHADOW"
        and full_suite.get("failed") == 0
        and full_suite.get("real_semantic_failures") == 0
        and full_suite.get("promotion_subset_rust_authority_failures") == 0
        and full_suite.get("native_exception_ptrace_compatible") == "54/54 PASS"
    )
    transport = operational.get("transport", {})
    rollback = operational.get("rollback", {})
    operational_pass = (
        _same_revision(operational, revision)
        and operational.get("decision")
        == "RUST_SSA_AUTHORITY_REQUALIFICATION_OPERATIONAL_PASS"
        and isinstance(transport, dict)
        and transport.get("persistent") == "PASS"
        and transport.get("same_input") == "PASS"
        and transport.get("fail_closed_semantic_mismatch") == "PASS"
        and transport.get("fail_closed_infrastructure") == "PASS"
        and transport.get("long_session") == "1000 requests / 1 process"
        and transport.get("concurrency") == "128 requests / 1 process"
        and isinstance(rollback, dict)
        and rollback.get("configuration_only") is True
        and _set(rollback.get("modes"))
        == {"PYTHON_SSA_AUTHORITY_RUST_SHADOW", "PYTHON_SSA_ONLY"}
    )
    performance_present = (
        _same_revision(performance, revision)
        and performance.get("measurement_kind")
        == "observational; no timing assertion or absolute gate"
        and isinstance(performance.get("workloads"), list)
        and bool(performance["workloads"])
    )
    clean_install_pass = platforms_pass
    semantic_clear = (
        fixture_pass
        and historical_pass
        and soak_pass
        and adversarial_pass
        and deep_cfg_pass
        and full_suite_pass
    )
    operational_clear = (
        operational_pass
        and clean_install_pass
        and platforms_pass
        and performance_present
        and safe_default
    )

    current_checks = [
        ("all semantic contracts qualified", fixture_pass and preserved_history),
        ("all lifecycle policies qualified", fixture_pass),
        ("schema-v2 qualified", fixture_pass and historical_pass),
        ("Rust Owned SSA model qualified", historical_pass),
        ("Rust Owned SSA verifier qualified", historical_pass),
        ("historical corpus 116/116", historical_pass),
        ("adversarial corpus 21/21 and 7/7", adversarial_pass),
        ("deep CFG 993, 1000, and 5000", deep_cfg_pass),
        ("expanded soak zero mismatches", soak_pass),
        ("persistent transport and session stress", operational_pass),
        ("clean installation in both dual-lane modes", clean_install_pass),
        ("all four official platforms", platforms_pass),
        ("rollback is configuration-only", operational_pass),
        ("Python authority works independently", safe_default and operational_pass),
        ("dual lanes remain fail closed", operational_pass),
        ("authority origin and optimizer/backend handoff", platforms_pass),
        ("companion packaging and discovery compatibility", platforms_pass),
        ("deterministic output preserved", historical_pass and soak_pass),
        ("no unresolved semantic blocker", semantic_clear),
        ("no unresolved operational blocker", operational_clear),
    ]
    gates = [
        _gate(
            f"V2-G{index:02d}",
            name,
            passed,
            "fresh exact-revision RUST-3.5b aggregate evidence",
        )
        for index, (name, passed) in enumerate(current_checks, 1)
    ]
    fixture_gate_rows = {
        row.get("id"): row for row in fixture_gates if isinstance(row, dict)
    }
    manifest = _json(
        ROOT
        / "tests/fixtures/rust_ssa_promotion_failure/qualification_manifest.json"
    )
    for cause in manifest["root_causes"]:
        row = fixture_gate_rows.get(cause["promotion_gate"], {})
        gates.append(
            _gate(
                cause["promotion_gate"],
                cause["name"],
                fixture_pass and row.get("status") == "PASS",
                ", ".join(cause["fixtures"]),
            )
        )

    blockers = [row["id"] for row in gates if row["status"] != "PASS"]
    ready = (
        original_gates_pass
        and preserved_history
        and not blockers
        and safe_default
    )
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.5b",
        "qualification_revision": revision,
        "decision": (
            "READY_FOR_RUST_SSA_AUTHORITY_SWITCH_V2"
            if ready
            else "RUST_SSA_AUTHORITY_REQUALIFICATION_BLOCKED"
        ),
        "repository_default": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "rust_authority_selected_only_for_qualification": True,
        "historical_preservation": {
            "original_rust_3_5_ready": historical_v1.get("decision"),
            "failed_rust_3_6_promotion": failed_promotion.get("decision"),
            "rust_3_6a_classification": classification.get("decision"),
            "rust_3_6b_closure": closure.get("decision"),
            "status": "PASS" if preserved_history else "BLOCKED",
        },
        "original_twenty_gate_baseline": {
            "status": "PASS" if original_gates_pass else "BLOCKED",
            "passed": sum(
                row.get("status") == "PASS"
                for row in historical_v1.get("gates", [])
            ),
            "expected": 20,
        },
        "expanded_gates": gates,
        "five_root_cause_fixture_gates": gates[20:],
        "historical_corpus": historical.get("checks", {}),
        "soak": soak,
        "soak_denominator": {
            "minimum_expected_compared": 139,
            "actual_compared": soak.get("shadow_compared") if isinstance(soak, dict) else None,
            "permanent_is_empty_fixture_may_raise_denominator_to": 140,
            "reason": "RUST-3.5b adds an explicit owning List.is_empty temporary fixture; the seven RUST-3.6a minimizers remain unchanged",
        },
        "adversarial": {
            "decision": adversarial.get("decision"),
            "positive_case_count": adversarial.get("positive_case_count"),
            "negative_case_count": adversarial.get("negative_case_count"),
        },
        "deep_cfg": {
            "decision": deep_cfg.get("decision"),
            "stress": deep_cfg.get("stress", {}),
            "cargo_workspace": deep_cfg.get("cargo_workspace", {}),
            "transport": deep_cfg.get("transport", {}),
        },
        "full_suite": full_suite,
        "operational": operational,
        "performance": {
            "measurement_kind": performance.get("measurement_kind"),
            "workloads": performance.get("workloads", []),
            "python_only_representative_median_total_ns": performance.get(
                "python_only_representative_median_total_ns"
            ),
            "rust_authority_python_shadow_representative_median_total_ns": (
                performance.get(
                    "rust_authority_python_shadow_representative_median_total_ns"
                )
            ),
            "observed_authority_over_python_ratio": performance.get(
                "observed_authority_over_python_ratio"
            ),
            "speedup_required": False,
        },
        "platforms": platforms,
        "blind_spot_closure": [
            {
                "previous_root_cause": cause["id"],
                "permanent_qualification_fixtures": cause["fixtures"],
                "promotion_gate": cause["promotion_gate"],
            }
            for cause in manifest["root_causes"]
        ],
        "why_v1_missed_defects": (
            "V1 relied on a 116-program historical corpus and a broad soak whose "
            "accepted inputs did not explicitly require the five lifecycle families. "
            "Workflow and full-suite coverage were treated as evidence without a "
            "root-cause-to-fixture-to-gate contract."
        ),
        "v2_recurrence_prevention": (
            "The eight-source manifest is a mandatory, independently executed "
            "three-mode gate on every qualification revision and every official "
            "platform; missing evidence blocks aggregation."
        ),
        "unresolved_blockers": blockers,
        "source_evidence_sha256": {
            name: sha256((evidence_dir / filename).read_bytes()).hexdigest()
            for name, filename in {
                "promotion_fixtures": "promotion_fixtures.json",
                "historical": "historical.json",
                "soak": "soak.json",
                "adversarial": "adversarial.json",
                "deep_cfg": "deep_cfg.json",
                "full_suite": "full_suite.json",
                "operational": "operational.json",
                "performance": "performance.json",
            }.items()
            if (evidence_dir / filename).is_file()
        },
        "scope": {
            "production_authority_changed": False,
            "lowering_semantics_changed": False,
            "lifecycle_policies_changed": False,
            "schemas_changed": False,
            "canonicalizer_changed": False,
            "optimizer_backend_semantics_changed": False,
            "comparison_weakened": False,
            "commit_created": False,
        },
    }


def render(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    record = build_record(args.revision, args.evidence_dir.resolve())
    rendered = render(record)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            print(f"stale RUST-3.5b requalification artifact: {args.output}")
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(record["decision"])
    if args.require_ready and record["decision"] != "READY_FOR_RUST_SSA_AUTHORITY_SWITCH_V2":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
