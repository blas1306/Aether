#!/usr/bin/env python3
"""Fail-closed aggregate checker for CORE-1.0B promotion evidence."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PENDING = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_PENDING_CI"
PROMOTED = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTED"
BLOCKED = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED"
CORE_PKG_1_QUALIFIED = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
CORE_PKG_1_RUN_ID = 33216160463
CORE_PKG_1_REVISION = "77417e7751482fc5a88a7d4207e99d67692da043"
PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
PYTHONS = {"3.11", "3.12", "3.13", "3.14"}
REPRESENTATIVE_REJECTIONS = {
    "malformed_initial_ir_json",
    "non_object_binding_input",
    "unsupported_schema",
    "unknown_root_field",
    "invalid_cfg_target",
    "duplicate_function",
}
PACKAGED_CLEAN_CONSUMER_FILES = {
    "in_process": "core-1.0b-packaged-default.json",
    "companion": "core-1.0b-packaged-companion.json",
}


def _required_ci_artifacts() -> dict[str, dict[str, str]]:
    """Return every machine-readable artifact required for CI closure."""
    required = {
        "blocker-resolution.json": {
            "kind": "core_pkg_1_native_compiler_core_distribution_closure_check",
            "role": "blocker_resolution",
        },
        "functional.json": {
            "kind": "core_1_0b_transport_lane",
            "role": "functional",
        },
        "development-install.json": {
            "kind": "core_1_0b_transport_lane",
            "role": "development_install",
        },
        "core-1.0b-packaged-install.json": {
            "kind": "core_1_0b_clean_consumer_install",
            "role": "packaged_clean_consumer_install",
        },
    }
    for transport, filename in PACKAGED_CLEAN_CONSUMER_FILES.items():
        required[filename] = {
            "kind": "core_1_0b_packaged_clean_consumer",
            "role": "packaged_clean_consumer",
            "transport": transport,
        }
    for platform in sorted(PLATFORMS):
        required[f"platform-{platform}.json"] = {
            "kind": "core_1_0b_transport_lane",
            "role": "platform",
            "platform": platform,
        }
        for transport in ("in_process", "companion"):
            transport_filename = transport.replace("_", "-")
            required[f"consumer-{platform}-{transport_filename}.json"] = {
                "kind": "core_1_0b_packaged_consumer",
                "role": "platform",
                "platform": platform,
                "transport": transport,
            }
    for python in sorted(PYTHONS):
        required[f"python-{python}.json"] = {
            "kind": "core_1_0b_transport_lane",
            "role": "python_compatibility",
            "python_minor": python,
        }
        for transport in ("in_process", "companion"):
            transport_filename = transport.replace("_", "-")
            required[f"consumer-python-{python}-{transport_filename}.json"] = {
                "kind": "core_1_0b_packaged_consumer",
                "role": "python_compatibility",
                "python_minor": python,
                "transport": transport,
            }
    return required


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _official_ci_run_id(value: object) -> bool:
    return re.fullmatch(r"[1-9][0-9]*", str(value)) is not None


def _blocker_resolution_record() -> dict[str, object]:
    """Recompute the exact CORE-PKG-1 closure; never trust a lane label alone."""
    checker_path = (
        ROOT
        / "scripts/check_core_pkg_1_native_distribution_closure_77417e77.py"
    )
    try:
        spec = importlib.util.spec_from_file_location(
            "core_pkg_1_closure_for_core_1_0b", checker_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load the CORE-PKG-1 closure checker")
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        closure = checker.build_record(root=ROOT)
        evidence = json.loads(checker.DEFAULT_EVIDENCE.read_text(encoding="utf-8"))
        contract = evidence.get("package_contract")
        run = evidence.get("official_run")
        native_contents = (
            contract.get("native_contents") if isinstance(contract, dict) else None
        )
        surfaces_present = bool(
            isinstance(native_contents, dict)
            and native_contents.get("stable_python_wrapper")
            == "aether_compiler_core"
            and native_contents.get("pyo3_binding") is True
            and native_contents.get("installed_companion") is True
            and native_contents.get("native_version_manifest") is True
        )
        exact_dependency = bool(
            isinstance(contract, dict)
            and contract.get("language_distribution") == "aether-language"
            and contract.get("language_version") == "1.0.0rc4"
            and contract.get("native_distribution") == "aether-compiler-core"
            and contract.get("native_version") == "1.0.0rc4"
            and contract.get("native_dependency")
            == "aether-compiler-core==1.0.0rc4"
            and contract.get("native_dependency_exact") is True
        )
        passed = bool(
            closure.get("passed") is True
            and closure.get("decision") == CORE_PKG_1_QUALIFIED
            and closure.get("run_id") == CORE_PKG_1_RUN_ID
            and closure.get("exact_revision") == CORE_PKG_1_REVISION
            and evidence.get("decision") == CORE_PKG_1_QUALIFIED
            and isinstance(run, dict)
            and run.get("run_id") == CORE_PKG_1_RUN_ID
            and run.get("head_sha") == CORE_PKG_1_REVISION
            and exact_dependency
            and surfaces_present
        )
        return {
            "passed": passed,
            "decision": closure.get("decision"),
            "official_run": run.get("run_id") if isinstance(run, dict) else None,
            "qualified_revision": (
                run.get("head_sha") if isinstance(run, dict) else None
            ),
            "exact_version_contract": exact_dependency,
            "productive_surfaces": surfaces_present,
        }
    except Exception as exc:
        return {
            "passed": False,
            "decision": BLOCKED,
            "official_run": None,
            "qualified_revision": None,
            "exact_version_contract": False,
            "productive_surfaces": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


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
    phases = {"conversion", "core", "ipc_protocol", "result_conversion"}
    if not all(
        workload.get("phase_samples") == 5
        and isinstance(workload.get("phase_median"), dict)
        and set(workload["phase_median"]) == phases
        and isinstance(workload.get("phase_dispersion_pstdev"), dict)
        and set(workload["phase_dispersion_pstdev"]) == phases
        for workload in workloads.values()
    ):
        return False
    historical = workloads["historical_116"]
    return historical.get("payloads_per_sample") == 116 and all(
        workload.get("samples") == 5 for workload in workloads.values()
    )


def _failure_campaign_complete(value: object) -> bool:
    if not isinstance(value, dict) or value.get("status") != "PASS":
        return False
    rows = value.get("same_input_structured_campaign")
    compared = value.get("compared_contract")
    return bool(
        isinstance(rows, list)
        and {str(row.get("case_id")) for row in rows if isinstance(row, dict)}
        == REPRESENTATIVE_REJECTIONS
        and all(
            isinstance(row, dict)
            and row.get("same_input_bytes") is True
            and row.get("companion_accepts") is False
            and row.get("in_process_accepts") is False
            and row.get("acceptance_parity") is True
            and row.get("machine_diagnostic_parity") is True
            and row.get("source_location_parity") is True
            and row.get("passed") is True
            for row in rows
        )
        and set(compared or ())
        == {
            "accept_reject",
            "structured_error_category",
            "phase",
            "source_location",
        }
    )


def _packaged_consumer_complete(
    records: list[dict[str, object]],
    revision: str,
    *,
    required_role: str | None = None,
    required_platforms: set[str] | None = None,
    required_pythons: set[str] | None = None,
) -> bool:
    valid: list[dict[str, object]] = []
    for record in records:
        transport = str(record.get("expected_transport"))
        if transport not in {"in_process", "companion"}:
            continue
        expected_starts = 1 if transport == "companion" else 0
        if (
            record.get("status") == "PASS"
            and (
                required_role is None
                or record.get("artifact_role") == required_role
            )
            and record.get("exact_revision") == revision
            and record.get("requested_transport") == transport
            and record.get("observed_transport") == transport
            and record.get("language_version") == "1.0.0rc4"
            and record.get("native_version") == "1.0.0rc4"
            and record.get("exact_native_dependency") is True
            and record.get("native_build_identity") == revision
            and record.get("outside_source_checkout") is True
            and record.get("source_checkout_available") is False
            and record.get("cargo_available") is False
            and record.get("rustc_available") is False
            and record.get("handled_failure_recovery") is True
            and record.get("representative_compilation") is True
            and isinstance(record.get("successful_output_sha256"), str)
            and len(str(record.get("successful_output_sha256"))) == 64
            and isinstance(record.get("successful_function_count"), int)
            and int(record.get("successful_function_count", 0)) > 0
            and record.get("companion_from_installed_package") is True
            and isinstance(record.get("python_executable"), str)
            and isinstance(record.get("python_version"), str)
            and record.get("process_start_count") == expected_starts
            and record.get("request_count") == 3
            and record.get("pyo3_binding_calls") == 0
            and _official_ci_run_id(record.get("ci_run_id"))
        ):
            valid.append(record)

    def paired(rows: list[dict[str, object]]) -> bool:
        if len(rows) != 2:
            return False
        by_transport = {
            str(record.get("expected_transport")): record for record in rows
        }
        return bool(
            set(by_transport) == {"in_process", "companion"}
            and by_transport["in_process"].get("default_selection") is True
            and by_transport["companion"].get("default_selection") is False
            and by_transport["in_process"].get("successful_output_sha256")
            == by_transport["companion"].get("successful_output_sha256")
        )

    if (
        required_platforms is None
        and required_pythons is None
        and not paired(valid)
    ):
        return False
    if required_platforms is not None and any(
        not paired(
            [record for record in valid if record.get("platform") == platform]
        )
        for platform in required_platforms
    ):
        return False
    if required_pythons is not None and any(
        not paired(
            [record for record in valid if record.get("python_minor") == python]
        )
        for python in required_pythons
    ):
        return False
    return True


def _validate_required_ci_artifacts(
    records_by_name: dict[str, dict[str, object]],
    revision: str,
    *,
    expected_ci_run_id: str | None,
    errors: list[str],
) -> dict[str, bool]:
    required = _required_ci_artifacts()
    results: dict[str, bool] = {}
    current_records = [
        records_by_name[name]
        for name in required
        if name != "blocker-resolution.json" and name in records_by_name
    ]
    observed_run_ids = {
        str(record.get("ci_run_id", "")) for record in current_records
    }
    if expected_ci_run_id is None:
        _require(
            len(observed_run_ids) == 1
            and all(_official_ci_run_id(run_id) for run_id in observed_run_ids),
            "required artifacts do not have one official CI run id",
            errors,
        )
        required_run_id = next(iter(observed_run_ids), "")
    else:
        required_run_id = str(expected_ci_run_id)
        _require(
            _official_ci_run_id(required_run_id),
            "expected CI run id is not an official numeric run id",
            errors,
        )
        _require(
            observed_run_ids == {required_run_id},
            "required artifact run id differs from the expected CI run",
            errors,
        )

    for filename, spec in required.items():
        record = records_by_name.get(filename)
        if record is None:
            errors.append(f"missing required CI artifact: {filename}")
            results[filename] = False
            continue
        artifact_errors: list[str] = []
        _require(
            record.get("kind") == spec["kind"],
            f"required artifact kind mismatch: {filename}",
            artifact_errors,
        )
        if filename == "blocker-resolution.json":
            _require(
                record.get("passed") is True
                and record.get("decision") == CORE_PKG_1_QUALIFIED
                and record.get("run_id") == CORE_PKG_1_RUN_ID
                and record.get("exact_revision") == CORE_PKG_1_REVISION,
                "blocker-resolution artifact did not pass its exact historical gate",
                artifact_errors,
            )
        else:
            _require(
                record.get("status") == "PASS",
                f"required artifact status is not PASS: {filename}",
                artifact_errors,
            )
            _require(
                record.get("exact_revision") == revision,
                f"required artifact revision mismatch: {filename}",
                artifact_errors,
            )
            _require(
                str(record.get("ci_run_id", "")) == required_run_id,
                f"required artifact run mismatch: {filename}",
                artifact_errors,
            )

        role = spec.get("role")
        if spec["kind"] == "core_1_0b_transport_lane":
            _require(
                record.get("matrix_role") == role,
                f"required transport lane role mismatch: {filename}",
                artifact_errors,
            )
        elif spec["kind"] in {
            "core_1_0b_packaged_consumer",
            "core_1_0b_packaged_clean_consumer",
        }:
            _require(
                record.get("artifact_role") == role,
                f"required packaged consumer role mismatch: {filename}",
                artifact_errors,
            )
        if "transport" in spec:
            _require(
                record.get("expected_transport") == spec["transport"],
                f"required transport subgate mismatch: {filename}",
                artifact_errors,
            )
        if "platform" in spec:
            _require(
                record.get("platform") == spec["platform"],
                f"required platform subgate mismatch: {filename}",
                artifact_errors,
            )
        if "python_minor" in spec:
            _require(
                record.get("python_minor") == spec["python_minor"],
                f"required Python subgate mismatch: {filename}",
                artifact_errors,
            )
        if spec["kind"] == "core_1_0b_clean_consumer_install":
            wheels = record.get("wheels")
            _require(
                isinstance(wheels, dict)
                and set(wheels) == {"aether-language", "aether-compiler-core"}
                and all(
                    isinstance(wheels[name], dict)
                    and wheels[name].get("version") == "1.0.0rc4"
                    and isinstance(wheels[name].get("path"), str)
                    and isinstance(wheels[name].get("sha256"), str)
                    and len(str(wheels[name].get("sha256"))) == 64
                    for name in wheels
                )
                and isinstance(
                    record.get("runtime_requirements_from_wheel_metadata"), list
                )
                and bool(record.get("runtime_requirements_from_wheel_metadata"))
                and isinstance(record.get("installed_distributions"), list)
                and record.get("aether_index_resolution_permitted") is False
                and record.get("dependency_validation") == "pip check PASS",
                "packaged clean-consumer install evidence is incomplete",
                artifact_errors,
            )
        errors.extend(artifact_errors)
        results[filename] = not artifact_errors
    return results


def check(
    evidence_dir: Path,
    *,
    exact_revision: str | None = None,
    ci_run_id: str | None = None,
    ci_closure: bool = False,
) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    blocker_resolution = _blocker_resolution_record()
    _require(
        blocker_resolution.get("passed") is True,
        "CORE-PKG-1 blocker resolution did not revalidate",
        errors,
    )
    lanes: list[dict[str, object]] = []
    packaged_consumers: list[dict[str, object]] = []
    records_by_name: dict[str, dict[str, object]] = {}
    for path in sorted(evidence_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON evidence {path}: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"JSON evidence is not an object: {path}")
            continue
        if path.name in records_by_name:
            errors.append(f"duplicate evidence filename: {path.name}")
            continue
        records_by_name[path.name] = value
        if isinstance(value, dict) and value.get("kind") == "core_1_0b_transport_lane":
            lanes.append(value)
        if value.get("kind") in {
            "core_1_0b_packaged_consumer",
            "core_1_0b_packaged_clean_consumer",
        }:
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
            "sessions_concurrency",
            "companion_rollback",
        ):
            value = lane.get(gate)
            _require(isinstance(value, dict) and value.get("status") == "PASS", f"{gate} failed: {label}", errors)
        _require(
            _failure_campaign_complete(lane.get("representative_failures")),
            f"representative structured failure parity failed: {label}",
            errors,
        )
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
    prerequisite_results: dict[str, bool] = {}
    packaged_clean_consumers = [
        record
        for record in packaged_consumers
        if record.get("kind") == "core_1_0b_packaged_clean_consumer"
    ]
    platform_consumers = [
        record
        for record in packaged_consumers
        if record.get("artifact_role") == "platform"
    ]
    python_consumers = [
        record
        for record in packaged_consumers
        if record.get("artifact_role") == "python_compatibility"
    ]
    packaged_clean_consumer_complete = _packaged_consumer_complete(
        packaged_clean_consumers,
        revision,
        required_role="packaged_clean_consumer",
    )
    if ci_closure:
        prerequisite_results = _validate_required_ci_artifacts(
            records_by_name,
            revision,
            expected_ci_run_id=ci_run_id,
            errors=errors,
        )
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
            all(_official_ci_run_id(lane.get("ci_run_id")) for lane in lanes),
            "official CI run provenance is missing",
            errors,
        )
        _require(
            packaged_clean_consumer_complete,
            "dedicated packaged-clean-consumer evidence is incomplete",
            errors,
        )
        install_record = records_by_name.get("core-1.0b-packaged-install.json")
        _require(
            isinstance(install_record, dict)
            and all(
                record.get("install_evidence") == install_record
                for record in packaged_clean_consumers
            ),
            "dedicated packaged consumers do not reference the exact install evidence",
            errors,
        )
        _require(
            _packaged_consumer_complete(
                platform_consumers,
                revision,
                required_role="platform",
                required_platforms=PLATFORMS,
            ),
            "platform packaged-consumer evidence is incomplete",
            errors,
        )
        _require(
            _packaged_consumer_complete(
                python_consumers,
                revision,
                required_role="python_compatibility",
                required_pythons=PYTHONS,
            ),
            "Python packaged-consumer evidence is incomplete",
            errors,
        )

    decision = BLOCKED if errors else PROMOTED if ci_closure else PENDING
    aggregate = {
        "artifact_schema_version": 1,
        "kind": "core_1_0b_transport_aggregate",
        "milestone": "CORE-1.0B",
        "decision": decision,
        "blocker_resolution": blocker_resolution,
        "exact_revision": revision or None,
        "ci_closure": ci_closure,
        "lanes": len(lanes),
        "platforms": sorted(observed_platforms),
        "python_minors": sorted(observed_pythons),
        "required_prerequisites": prerequisite_results,
        "packaged_clean_consumer": packaged_clean_consumer_complete,
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
    parser.add_argument("--ci-run-id")
    parser.add_argument("--ci-closure", action="store_true")
    parser.add_argument("--require-pending", action="store_true")
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    aggregate, _errors = check(
        args.evidence_dir,
        exact_revision=args.revision,
        ci_run_id=args.ci_run_id,
        ci_closure=args.ci_closure,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(aggregate["decision"])
    expected = PROMOTED if args.require_promoted else PENDING if args.require_pending else aggregate["decision"]
    return 0 if aggregate["decision"] == expected and aggregate["decision"] != BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
