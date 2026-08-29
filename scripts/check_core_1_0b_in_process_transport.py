#!/usr/bin/env python3
"""Fail-closed aggregate checker for CORE-1.0B promotion evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


PENDING = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_PENDING_CI"
PROMOTED = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTED"
BLOCKED = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED"
PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
PYTHONS = {"3.11", "3.12", "3.13", "3.14"}


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _performance_complete(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    workloads = value.get("workloads")
    required = {
        "ordinary",
        "historical_116",
        "deep_cfg_1000",
        "real_ae_expense_tracker",
    }
    if not isinstance(workloads, dict) or set(workloads) != required:
        return False
    if not all(isinstance(workload, dict) for workload in workloads.values()):
        return False
    historical = workloads["historical_116"]
    return historical.get("payloads_per_sample") == 116 and all(
        workload.get("samples") == 5 for workload in workloads.values()
    )


def _packaged_consumer_complete(
    records: list[dict[str, object]], revision: str
) -> bool:
    if len(records) != 2:
        return False
    by_transport = {str(record.get("expected_transport")): record for record in records}
    if set(by_transport) != {"in_process", "companion"}:
        return False
    for transport, record in by_transport.items():
        expected_starts = 1 if transport == "companion" else 0
        if not (
            record.get("status") == "PASS"
            and record.get("exact_revision") == revision
            and record.get("requested_transport") == transport
            and record.get("observed_transport") == transport
            and record.get("language_version") == "1.0.0rc4"
            and record.get("native_version") == "1.0.0rc4"
            and record.get("exact_native_dependency") is True
            and record.get("native_build_identity") == revision
            and record.get("outside_source_checkout") is True
            and record.get("cargo_available") is False
            and record.get("rustc_available") is False
            and record.get("handled_failure_recovery") is True
            and record.get("process_start_count") == expected_starts
            and record.get("request_count") == 3
            and record.get("pyo3_binding_calls") == 0
            and str(record.get("ci_run_id")) not in {"", "LOCAL_PRE_CI"}
        ):
            return False
    return by_transport["in_process"].get("default_selection") is True and (
        by_transport["companion"].get("default_selection") is False
    )


def check(
    evidence_dir: Path,
    *,
    exact_revision: str | None = None,
    ci_closure: bool = False,
) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    lanes: list[dict[str, object]] = []
    packaged_consumers: list[dict[str, object]] = []
    for path in sorted(evidence_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON evidence {path}: {exc}")
            continue
        if isinstance(value, dict) and value.get("kind") == "core_1_0b_transport_lane":
            lanes.append(value)
        if isinstance(value, dict) and value.get("kind") == "core_1_0b_packaged_consumer":
            packaged_consumers.append(value)
    _require(bool(lanes), "missing CORE-1.0B transport evidence", errors)

    revisions = {str(lane.get("exact_revision", "")) for lane in lanes}
    _require(len(revisions) == 1, "evidence does not have one exact revision", errors)
    revision = next(iter(revisions), "")
    _require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "exact revision is invalid", errors)
    if exact_revision is not None:
        _require(revision == exact_revision, "evidence revision differs from required revision", errors)

    for lane in lanes:
        label = f"{lane.get('platform')}/{lane.get('python_minor')}/{lane.get('matrix_role')}"
        _require(lane.get("status") == "PASS", f"lane failed: {label}", errors)
        _require(
            lane.get("previous_blocker") == "resolved_by_CORE_PKG_1",
            f"previous distribution blocker resolution is missing: {label}",
            errors,
        )
        _require(lane.get("default_transport") == "in_process", f"default guard failed: {label}", errors)
        _require(lane.get("automatic_fallback") is False, f"fallback guard failed: {label}", errors)
        native = lane.get("native_distribution")
        _require(
            isinstance(native, dict)
            and native.get("name") == "aether-compiler-core"
            and native.get("qualification_only") is False,
            f"productive package guard failed: {label}",
            errors,
        )
        provenance = lane.get("provenance")
        _require(
            isinstance(provenance, dict)
            and set(provenance) == {"in_process", "companion"}
            and all(
                isinstance(provenance.get(name), dict)
                and provenance[name].get("requested_transport") == name
                and provenance[name].get("observed_transport") == name
                for name in ("in_process", "companion")
            ),
            f"requested/observed provenance failed: {label}",
            errors,
        )
        for gate in (
            "historical",
            "production_pipeline",
            "deep_cfg",
            "representative_failures",
            "sessions_concurrency",
            "companion_rollback",
        ):
            value = lane.get(gate)
            _require(isinstance(value, dict) and value.get("status") == "PASS", f"{gate} failed: {label}", errors)
        differential = lane.get("differential")
        rollback = lane.get("rollback")
        for name, value in (
            ("differential", differential),
            ("differential_divergence", lane.get("differential_divergence")),
            ("ssa_refinement_corruptions", lane.get("ssa_refinement_corruptions")),
            ("rollback", rollback),
        ):
            _require(
                isinstance(value, dict)
                and set(value) == {"in_process", "companion"}
                and all(
                    isinstance(value[transport], dict)
                    and value[transport].get("status") == "PASS"
                    for transport in value
                ),
                f"{name} both-transports gate failed: {label}",
                errors,
            )
        _require(lane.get("rust_4_5_affected") == "PASS", f"RUST-4.5 gate failed: {label}", errors)
        _require(lane.get("packaging_regression") == "PASS", f"packaging regression failed: {label}", errors)
        _require(lane.get("ide_cli_shared_pipeline") == "PASS", f"IDE/CLI smoke failed: {label}", errors)

    functional = [lane for lane in lanes if lane.get("matrix_role") == "functional"]
    _require(bool(functional), "full functional transport evidence is missing", errors)
    for lane in functional:
        historical = lane.get("historical")
        deep = lane.get("deep_cfg")
        pipeline = lane.get("production_pipeline")
        _require(
            isinstance(historical, dict)
            and historical.get("expected") == 116
            and historical.get("accepted") == 116
            and historical.get("executed_both_transports") == 116,
            "historical 116 both-transports evidence is incomplete",
            errors,
        )
        _require(
            isinstance(deep, dict)
            and set(deep.get("depths", ())) == {993, 1000, 5000, 10000},
            "deep CFG both-transports evidence is incomplete",
            errors,
        )
        _require(
            isinstance(pipeline, dict)
            and isinstance(pipeline.get("cases"), list)
            and len(pipeline["cases"]) == 116
            and all(
                isinstance(row, dict)
                and row.get("full_productive_pipeline") is True
                and row.get("transport_parity") is True
                for row in pipeline["cases"]
            ),
            "full production .ae pipeline parity evidence is incomplete",
            errors,
        )
        performance = lane.get("performance")
        _require(
            isinstance(performance, dict)
            and set(performance) == {"in_process", "companion"}
            and all(
                _performance_complete(performance[transport])
                for transport in ("in_process", "companion")
            ),
            "multi-workload performance characterization is incomplete",
            errors,
        )

    observed_platforms = {str(lane.get("platform")) for lane in lanes if lane.get("matrix_role") == "platform"}
    observed_pythons = {str(lane.get("python_minor")) for lane in lanes if lane.get("matrix_role") == "python_compatibility"}
    if ci_closure:
        _require(observed_platforms == PLATFORMS, "platform matrix evidence is incomplete", errors)
        _require(observed_pythons == PYTHONS, "Python matrix evidence is incomplete", errors)
        _require(
            all(
                isinstance(lane.get("native_distribution"), dict)
                and lane["native_distribution"].get("build_identity") == revision
                for lane in lanes
            ),
            "native build identity does not match the exact CI revision",
            errors,
        )
        _require(
            all(str(lane.get("ci_run_id")) not in {"", "LOCAL_PRE_CI"} for lane in lanes),
            "official CI run provenance is missing",
            errors,
        )
        _require(
            _packaged_consumer_complete(packaged_consumers, revision),
            "packaged clean-consumer evidence is incomplete",
            errors,
        )

    decision = BLOCKED if errors else PROMOTED if ci_closure else PENDING
    aggregate = {
        "artifact_schema_version": 1,
        "kind": "core_1_0b_transport_aggregate",
        "milestone": "CORE-1.0B",
        "decision": decision,
        "exact_revision": revision or None,
        "ci_closure": ci_closure,
        "lanes": len(lanes),
        "platforms": sorted(observed_platforms),
        "python_minors": sorted(observed_pythons),
        "packaged_clean_consumer": _packaged_consumer_complete(
            packaged_consumers, revision
        ),
        "default_observed": "in_process" if not errors else None,
        "explicit_companion_observed": "companion" if not errors else None,
        "no_fallback": not errors,
        "errors": errors,
    }
    return aggregate, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--ci-closure", action="store_true")
    parser.add_argument("--require-pending", action="store_true")
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    aggregate, _errors = check(
        args.evidence_dir,
        exact_revision=args.revision,
        ci_closure=args.ci_closure,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(aggregate["decision"])
    expected = PROMOTED if args.require_promoted else PENDING if args.require_pending else aggregate["decision"]
    return 0 if aggregate["decision"] == expected and aggregate["decision"] != BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
