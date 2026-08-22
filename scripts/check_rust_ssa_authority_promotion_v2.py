#!/usr/bin/env python3
"""Aggregate exact-revision, evidence-only RUST-3.6-V2 promotion results."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_ssa_authority_promotion_v2.json"
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_authority_promotion_v2_evidence"
QUALIFIED_BASE_REVISION = "5ced223b0eaf77ef3e77e9b595f355a6ec18da42"
PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}
CHARACTERIZATION_MODES = {
    "python_ssa_only": "python_ssa_only",
    "diagnostic_rust_only": "diagnostic_rust_authority_without_python_shadow",
    "rust_authority_python_shadow": "rust_authority_python_shadow",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _optional(path: Path) -> dict[str, Any]:
    try:
        return _json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _same_revision(value: dict[str, Any], revision: str) -> bool:
    return value.get("qualification_revision", value.get("revision")) == revision


def _as_set(value: object) -> set[object]:
    return set(value) if isinstance(value, list) else set()


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _timing(value: object) -> bool:
    return (
        type(value) in {int, float}
        and math.isfinite(value)
        and value >= 0
    )


def _timing_summary(value: object, samples: int) -> bool:
    if not isinstance(value, dict):
        return False
    minimum = value.get("min_seconds")
    median = value.get("median_seconds")
    maximum = value.get("max_seconds")
    return (
        _positive_int(value.get("samples"))
        and value["samples"] == samples
        and all(_timing(item) for item in (minimum, median, maximum))
        and minimum <= median <= maximum
    )


def _timing_sample(value: object, mode: str) -> bool:
    if not isinstance(value, dict):
        return False
    phases = value.get("phases_seconds")
    component_sum = value.get("measured_component_sum_seconds")
    residual = value.get("residual_unattributed_seconds")
    total = value.get("total_wall_seconds")
    if not (
        value.get("mode") == CHARACTERIZATION_MODES[mode]
        and isinstance(value.get("clock"), str)
        and bool(value["clock"])
        and isinstance(value.get("rust_phase_detail"), str)
        and bool(value["rust_phase_detail"])
        and isinstance(phases, dict)
        and bool(phases)
        and all(
            isinstance(phase, str) and bool(phase) and _timing(seconds)
            for phase, seconds in phases.items()
        )
        and all(_timing(item) for item in (component_sum, residual, total))
    ):
        return False
    phase_tolerance = max(1e-9, component_sum * 1e-9)
    total_tolerance = max(1e-9, total * 1e-9)
    return (
        abs(sum(phases.values()) - component_sum) <= phase_tolerance
        and abs(component_sum + residual - total) <= total_tolerance
    )


def _workload_metadata(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    input_shape = value.get("input_shape")
    return (
        all(
            isinstance(value.get(key), str) and bool(value[key])
            for key in ("id", "path", "category")
        )
        and isinstance(value.get("source_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]) is not None
        and isinstance(input_shape, dict)
        and all(
            type(input_shape.get(key)) is int and input_shape[key] >= 0
            for key in ("functions", "blocks", "instructions")
        )
    )


def _historical_performance_evidence(value: dict[str, Any], revision: str) -> bool:
    return (
        _same_revision(value, revision)
        and value.get("measurement_kind")
        == "observational; no timing assertion or absolute gate"
        and isinstance(value.get("workloads"), list)
        and bool(value["workloads"])
    )


def _characterization_performance_evidence(
    value: dict[str, Any], revision: str
) -> bool:
    methodology = value.get("methodology")
    manifest = value.get("workload_manifest")
    workloads = value.get("workloads")
    aggregates = value.get("aggregates")
    if not (
        _same_revision(value, revision)
        and type(value.get("artifact_schema_version")) is int
        and value["artifact_schema_version"] == 1
        and isinstance(value.get("milestone"), str)
        and bool(value["milestone"])
        and value.get("decision")
        in {
            "RUST_SSA_PERFORMANCE_CHARACTERIZED",
            "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED",
        }
        and value.get("measurement_kind")
        == "observational; no absolute timing is a semantic gate"
        and isinstance(methodology, dict)
        and isinstance(methodology.get("clock"), str)
        and bool(methodology["clock"])
        and _positive_int(methodology.get("warmup_rounds_per_workload"))
        and _positive_int(methodology.get("measured_rounds_per_workload"))
        and methodology.get("statistics") == ["median", "min", "max"]
        and methodology.get("production_timing_default") == "disabled"
        and methodology.get("diagnostic_rust_only_is_authority_mode") is False
        and isinstance(manifest, list)
        and bool(manifest)
        and isinstance(workloads, list)
        and bool(workloads)
        and len(manifest) == len(workloads)
        and isinstance(aggregates, dict)
    ):
        return False

    rounds = methodology["measured_rounds_per_workload"]
    manifest_by_id: dict[str, dict[str, Any]] = {}
    for row in manifest:
        if not _workload_metadata(row) or row["id"] in manifest_by_id:
            return False
        manifest_by_id[row["id"]] = row

    workload_ids: set[str] = set()
    metadata_keys = ("id", "path", "category", "source_sha256", "input_shape")
    for workload in workloads:
        if not _workload_metadata(workload):
            return False
        identifier = workload["id"]
        if identifier in workload_ids or identifier not in manifest_by_id:
            return False
        workload_ids.add(identifier)
        if any(
            workload[key] != manifest_by_id[identifier].get(key)
            for key in metadata_keys
        ):
            return False
        if not (
            isinstance(workload.get("canonical_ssa_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", workload["canonical_ssa_sha256"])
            is not None
        ):
            return False
        samples = workload.get("samples")
        summaries = workload.get("summary")
        if not isinstance(samples, dict) or not isinstance(summaries, dict):
            return False
        for mode in CHARACTERIZATION_MODES:
            mode_samples = samples.get(mode)
            if not (
                isinstance(mode_samples, list)
                and len(mode_samples) == rounds
                and all(_timing_sample(sample, mode) for sample in mode_samples)
                and _timing_summary(summaries.get(mode), rounds)
            ):
                return False
    if workload_ids != set(manifest_by_id):
        return False

    return all(
        isinstance(aggregates.get(mode), dict)
        and _timing_summary(
            aggregates[mode].get("representative_suite"), rounds
        )
        for mode in CHARACTERIZATION_MODES
    )


def _performance_evidence_present(value: dict[str, Any], revision: str) -> bool:
    return _historical_performance_evidence(
        value, revision
    ) or _characterization_performance_evidence(value, revision)


def _gate(identifier: str, name: str, passed: bool, evidence: str) -> dict[str, str]:
    return {
        "id": identifier,
        "name": name,
        "status": "PASS" if passed else "BLOCKED",
        "evidence": evidence,
    }


def _platform_rows(directory: Path, revision: str) -> tuple[dict[str, Any], bool]:
    rows: dict[str, Any] = {}
    categories = {
        "scalar",
        "numerical",
        "collections",
        "aggregate",
        "class_interface",
        "exception",
        "constructor_ownership",
        "function_value_indirect_call",
    }
    for name, target in PLATFORMS.items():
        path = directory / f"{name}.json"
        value = _optional(path)
        comparison = value.get("comparison", {})
        checks = value.get("checks", {})
        valid = (
            value.get("milestone") == "RUST-3.6-V2"
            and value.get("revision") == revision
            and value.get("platform") == name
            and value.get("rust_target") == target
            and value.get("execution") == "clean_release_artifact_outside_checkout"
            and value.get("provenance") == "executed-native-runner"
            and value.get("mandatory_promotion_fixture_count") == 8
            and _as_set(value.get("representative_categories")) == categories
            and isinstance(checks, dict)
            and checks
            and set(checks.values()) == {"PASS"}
            and isinstance(comparison, dict)
            and comparison.get("mode") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
            and comparison.get("repository_default")
            == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
            and comparison.get("default_returned_ssa_origin")
            == "rust_schema_v2_import"
            and _as_set(comparison.get("modes_exercised"))
            == {
                "PYTHON_SSA_ONLY",
                "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
                "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            }
            and _as_set(comparison.get("returned_ssa_origins"))
            == {"rust_schema_v2_import"}
            and comparison.get("fixture_mode_matrix_checks") == 16
            and comparison.get("native_baseline_comparisons") == 8
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
                "reason": "fresh exact-promotion-revision native evidence missing or invalid",
            }
        )
    return rows, all(row["status"] == "PASS" for row in rows.values())


def build_record(revision: str, evidence_dir: Path) -> dict[str, Any]:
    readiness = _json(ROOT / "docs/compiler/rust_ssa_authority_requalification.json")
    failed_promotion = _json(ROOT / "docs/compiler/rust_ssa_authority_promotion.json")
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
    platforms, platforms_pass = _platform_rows(evidence_dir / "platforms", revision)

    shadow_source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    pipeline_source = (ROOT / "src/aether/pipeline.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/rust-ssa-shadow.yml").read_text(
        encoding="utf-8"
    )
    rust_default = re.search(
        r"mode:\s*SSALoweringAuthorityMode\s*=\s*"
        r"SSALoweringAuthorityMode\.RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        shadow_source,
    ) is not None
    return_origin_wired = all(
        token in pipeline_source
        for token in (
            "lower_with_rust_authority(module, client)",
            'last_returned_ssa_origin = "rust_schema_v2_import"',
            "return authoritative",
        )
    )
    python_preserved = "GeneralSSABuilder().build" in shadow_source
    fail_closed = (
        "Rust SSA authority requires fail-closed semantics" in shadow_source
        and "authoritative = rust_ssa if rust_authoritative else python_ssa"
        in shadow_source
        and "if difference:" in shadow_source
    )
    rollback_modes = {
        "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "PYTHON_SSA_ONLY",
    } <= set(re.findall(r"^\s+([A-Z_]+)\s*=", shadow_source, re.MULTILINE))
    ci_modes = all(
        token in workflow
        for token in (
            "full-suite-rust-default",
            "python-authority-rust-shadow",
            "python-only",
            "check_rust_ssa_authority_promotion_v2.py",
            "--require-promoted",
        )
    )

    history_preserved = (
        readiness.get("milestone") == "RUST-3.5b"
        and readiness.get("decision")
        in {
            "READY_FOR_RUST_SSA_AUTHORITY_SWITCH_V2",
            "RUST_SSA_AUTHORITY_REQUALIFICATION_BLOCKED",
        }
        and failed_promotion.get("decision") == "RUST_SSA_AUTHORITY_PROMOTION_FAILED"
        and classification.get("decision") == "RUST_SSA_PROMOTION_FAILURES_CLASSIFIED"
        and closure.get("decision") == "RUST_SSA_PROMOTION_LIFECYCLE_DEFECTS_CLOSED"
    )

    fixture_gates = fixtures.get("gates", [])
    fixture_rows = fixtures.get("fixtures", [])
    fixture_pass = (
        _same_revision(fixtures, revision)
        and fixtures.get("decision") == "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED"
        and fixtures.get("repository_default") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and fixtures.get("mandatory_fixture_count") == 8
        and isinstance(fixture_gates, list)
        and [row.get("id") for row in fixture_gates if isinstance(row, dict)]
        == [f"V2-L{number:02d}" for number in range(1, 6)]
        and all(row.get("status") == "PASS" for row in fixture_gates)
        and isinstance(fixture_rows, list)
        and len(fixture_rows) == 8
        and all(row.get("status") == "PASS" for row in fixture_rows)
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
        and soak_record.get("authority", {}).get("repository_default")
        == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and isinstance(soak, dict)
        and soak.get("accepted") == soak.get("shadow_compared") == 140
        and soak.get("semantic_mismatches") == 0
        and soak.get("infrastructure_failures") == 0
    )
    adversarial_pass = (
        _same_revision(adversarial, revision)
        and adversarial.get("decision") == "RUST_SSA_LOWERING_ADVERSARIAL_QUALIFIED"
        and adversarial.get("positive_case_count") == 21
        and adversarial.get("negative_case_count") == 7
    )
    stress = deep_cfg.get("stress", {})
    deep_cfg_pass = (
        _same_revision(deep_cfg, revision)
        and deep_cfg.get("decision") == "RUST_SSA_AUTHORITY_DEEP_CFG_PASS"
        and deep_cfg.get("cargo_workspace", {}).get("status") == "PASS"
        and isinstance(stress, dict)
        and all(
            stress.get(str(size), {}).get("python") == "PASS"
            and stress.get(str(size), {}).get("rust") == "PASS"
            for size in (993, 1000, 5000)
        )
    )
    full_suite_pass = (
        _same_revision(full_suite, revision)
        and full_suite.get("decision")
        == "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_PASS"
        and full_suite.get("mode") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and full_suite.get("failed") == 0
        and full_suite.get("semantic_mismatches") == 0
        and full_suite.get("infrastructure_failures") == 0
        and full_suite.get("environmental_failures") == 0
        and full_suite.get("unclassified_test_failures") == 0
    )
    transport = operational.get("transport", {})
    rollback = operational.get("rollback", {})
    authority_probe = operational.get("authority_probe", {})
    operational_pass = (
        _same_revision(operational, revision)
        and operational.get("decision")
        == "RUST_SSA_AUTHORITY_REQUALIFICATION_OPERATIONAL_PASS"
        and transport.get("persistent") == "PASS"
        and transport.get("same_input") == "PASS"
        and transport.get("fail_closed_semantic_mismatch") == "PASS"
        and transport.get("fail_closed_infrastructure") == "PASS"
        and transport.get("long_session") == "1000 requests / 1 process"
        and transport.get("concurrency") == "128 requests / 1 process"
        and rollback.get("configuration_only") is True
        and _as_set(rollback.get("modes"))
        == {"PYTHON_SSA_AUTHORITY_RUST_SHADOW", "PYTHON_SSA_ONLY"}
        and authority_probe.get("production_default_origin")
        == "rust_schema_v2_import"
        and authority_probe.get("python_authority_rollback_origin")
        == "python_general_ssa_builder"
    )
    performance_present = _performance_evidence_present(performance, revision)

    checks = [
        ("repository default is Rust authority/Python shadow", rust_default),
        ("returned object is wired from Rust schema-v2 import", return_origin_wired),
        ("Python GeneralSSABuilder remains mandatory", python_preserved),
        ("all authority failures remain fail closed", fail_closed),
        ("both configuration-only rollback modes remain", rollback_modes and operational_pass),
        ("historical qualification evidence is preserved", history_preserved),
        ("V2-L01 through V2-L05 pass after promotion", fixture_pass),
        ("historical corpus is 116/116 after promotion", historical_pass),
        ("expanded soak is 140/140 with zero failures", soak_pass),
        ("adversarial corpus is 21/21 positive and 7/7 negative", adversarial_pass),
        ("deep CFG 993, 1000, and 5000 pass", deep_cfg_pass),
        ("full suite passes under the new default", full_suite_pass),
        ("transport, same-input, fail-closed, and rollback pass", operational_pass),
        ("clean install and four native platforms pass", platforms_pass),
        ("fresh observational performance evidence exists", performance_present),
        ("CI requires default and both rollback configurations", ci_modes),
    ]
    gates = [
        _gate(f"PV2-G{index:02d}", name, passed, "exact promotion revision evidence")
        for index, (name, passed) in enumerate(checks, 1)
    ]
    blockers = [gate["id"] for gate in gates if gate["status"] != "PASS"]
    promoted = not blockers
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.6-V2",
        "promotion_revision": revision,
        "qualified_base_revision": QUALIFIED_BASE_REVISION,
        "decision": (
            "RUST_SSA_AUTHORITY_PROMOTED_V2"
            if promoted
            else "RUST_SSA_AUTHORITY_PROMOTION_V2_FAILED"
        ),
        "old_default": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "new_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "gates": gates,
        "blockers": blockers,
        "returned_origin": {
            "value": "rust_schema_v2_import",
            "identity_test_required": True,
            "optimizer_backend_handoff": "PASS" if platforms_pass else "BLOCKED",
        },
        "python_shadow": "mandatory_synchronous_verified_and_discarded_only_after_match",
        "failure_policy": "fail_closed_no_silent_fallback",
        "rollback_modes": [
            "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
            "PYTHON_SSA_ONLY",
        ],
        "v2_lifecycle_recurrence": {
            f"V2-L{number:02d}": "PASS" if fixture_pass else "BLOCKED"
            for number in range(1, 6)
        },
        "historical": {
            "decision": historical.get("decision"),
            "accepted": historical.get("accepted"),
            "expected": historical.get("expected"),
            "checks": historical_checks,
        },
        "soak": {
            "decision": soak_record.get("decision"),
            "result": soak,
        },
        "adversarial": {
            "decision": adversarial.get("decision"),
            "positive_case_count": adversarial.get("positive_case_count"),
            "negative_case_count": adversarial.get("negative_case_count"),
        },
        "deep_cfg": {
            "decision": deep_cfg.get("decision"),
            "stress": stress,
            "cargo_workspace": deep_cfg.get("cargo_workspace", {}),
        },
        "full_suite": {
            key: full_suite.get(key)
            for key in (
                "decision",
                "mode",
                "passed",
                "failed",
                "skipped",
                "semantic_mismatches",
                "infrastructure_failures",
                "environmental_failures",
                "unclassified_test_failures",
                "promotion_subset",
                "native_exception_ptrace_compatible",
                "summaries",
            )
        },
        "operational": {
            "decision": operational.get("decision"),
            "transport": transport,
            "rollback": rollback,
            "authority_probe": authority_probe,
            "packaging_and_discovery": operational.get("packaging_and_discovery"),
            "ci_integration": operational.get("ci_integration"),
        },
        "platforms": platforms,
        "clean_install": "PASS" if platforms_pass else "BLOCKED",
        "performance": {
            "measurement_kind": performance.get("measurement_kind"),
            "observed_authority_over_python_ratio": performance.get(
                "observed_authority_over_python_ratio"
            ),
            "process_startups": performance.get("process_startups"),
            "requests": performance.get("requests"),
            "workloads": performance.get("workloads", []),
        },
        "scope": {
            "schemas_changed": False,
            "policies_changed": False,
            "lifecycle_or_ssa_semantics_changed": False,
            "optimizer_or_backend_semantics_changed": False,
            "python_general_ssa_builder_preserved": python_preserved,
            "silent_fallback": False,
            "historical_artifacts_modified": False,
            "commit_created": False,
        },
    }


def _encoded(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    record = build_record(args.revision, args.evidence_dir)
    encoded = _encoded(record)
    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except OSError:
            current = ""
        if current != encoded:
            print("RUST-3.6-V2 promotion artifact is stale")
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(record["decision"])
    if args.require_promoted and record["decision"] != "RUST_SSA_AUTHORITY_PROMOTED_V2":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
