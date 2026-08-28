#!/usr/bin/env python3
"""Fail-closed checker for the official CORE-1.0A closure at 6f6851df."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT
    / "docs/compiler/core_1_0a_in_process_compiler_core_qualification_closure_6f6851df.json"
)
DEFAULT_REPORT = (
    ROOT
    / "docs/compiler/CORE_1_0A_IN_PROCESS_COMPILER_CORE_QUALIFICATION_CLOSURE_6F6851DF.md"
)
DEFAULT_WORKFLOW = ROOT / ".github/workflows/core-in-process.yml"

RUN_ID = 33144738758
REVISION = "6f6851dfd353bb716eeffc05a701b6bc4dab5132"
WORKFLOW_NAME = "core-1.0a-in-process-qualification"
QUALIFIED = "CORE_IN_PROCESS_BOUNDARY_QUALIFIED"
BLOCKED = "CORE_IN_PROCESS_BOUNDARY_QUALIFICATION_BLOCKED"
HISTORICAL_RUN_ID = 33143156047
HISTORICAL_REVISION = "2401ab8d56c13d7837aab245735105764e65ade0"
SHA256 = re.compile(r"[0-9a-f]{64}")

EXPECTED_JOBS = {
    "semantic-historical-failures-deep": 98763185488,
    "rust-owned-sessions-gil-memory": 98763185574,
    "affected-rust-4.5-production-gates": 98763185664,
    "clean-install-linux-x86_64": 98763185667,
    "clean-install-windows-x86_64": 98763185605,
    "clean-install-macos-x86_64": 98763185642,
    "clean-install-macos-arm64": 98763185660,
    "cpython-3.11-linux-x86_64": 98763185661,
    "cpython-3.12-linux-x86_64": 98763185662,
    "cpython-3.13-linux-x86_64": 98763185693,
    "cpython-3.14-linux-x86_64": 98763185624,
    "aggregate-fail-closed-decision": 98763793041,
}

# artifact id, GitHub archive digest, extracted file, extracted file SHA-256,
# source job. All values were obtained with gh from run 33144738758.
EXPECTED_ARTIFACTS = {
    "core-1.0a-aggregate": (
        9675384624,
        "deb02f28243450a3c9840d7aefa7b71bad45c28fcacc1ad274ce4d9a0a556e2a",
        "core-1.0a-aggregate/aggregate.json",
        "8e70eb181f9b5adc4749cb1fd2baf68ad21a386f7ff5956762bb0a6fc868bf8f",
        "aggregate-fail-closed-decision",
    ),
    "core-1.0a-semantic": (
        9675359820,
        "0fc17e385cae5ebe5f2ec04b0526a1a100d9e63373421fddc0103bf8eb09807a",
        "core-1.0a-semantic/semantic.json",
        "b3df2c0448f66d73db5fa6b0209234893ce9593a81832e5eabd4000c415f1d99",
        "semantic-historical-failures-deep",
    ),
    "core-1.0a-sessions": (
        9675353087,
        "b16d9c62281d6a98825c3dd7bf29c328be9f80cde8bfb70ef76d45fdd4d89a7e",
        "core-1.0a-sessions/sessions.json",
        "40c7754c0e7f31d059a5c0086f7c8fc3421d5bc7c1268dfcc1190bebbd54a2cd",
        "rust-owned-sessions-gil-memory",
    ),
    "core-1.0a-production": (
        9675352005,
        "a3ece814208e1db56689d3504380f56582c2aa546372fb871669bf1d2f2a9c3d",
        "core-1.0a-production/production.json",
        "dad6da4546fb161e41ad86fbc98cbb8cd68d721c08fd5071d4297813006294a3",
        "affected-rust-4.5-production-gates",
    ),
    "core-1.0a-platform-linux-x86_64": (
        9675347463,
        "0abf8da9847ac6db3180b6e8a398d733b8064c760b43a495e63c2f47fcd705a3",
        "core-1.0a-platform-linux-x86_64/platform-linux-x86_64.json",
        "d94e64834ba21e052196758b5006dea1317f7378a00cc4b7c89730d57e8e8db1",
        "clean-install-linux-x86_64",
    ),
    "core-1.0a-platform-windows-x86_64": (
        9675376754,
        "4eba779837a9750c9f194beb63571c8a1c9dd19b485a9638a8ac66888348c670",
        "core-1.0a-platform-windows-x86_64/platform-windows-x86_64.json",
        "4ed805165e7fee5cbbe17a1a0d20f06400a4d8c841b8b0a5109c92aa3f80e4d7",
        "clean-install-windows-x86_64",
    ),
    "core-1.0a-platform-macos-x86_64": (
        9675381309,
        "98e4ce8e03dc228cc3a0d7b4dfddd723cf0e257b8b153d36f8fac89450635b96",
        "core-1.0a-platform-macos-x86_64/platform-macos-x86_64.json",
        "d6615ec8757dfbc86a8ce6c8ca49427123a6e54c132507b38109a028929a2ad7",
        "clean-install-macos-x86_64",
    ),
    "core-1.0a-platform-macos-arm64": (
        9675347129,
        "8fe9dc695b38ed9641611d65f300959d4c374bbdf6ae9531017bddcdeb085de1",
        "core-1.0a-platform-macos-arm64/platform-macos-arm64.json",
        "a016d19f480b68b3cbad9d0b3641ab3320793c6fa8ec29bce4c8868016966ae0",
        "clean-install-macos-arm64",
    ),
    "core-1.0a-python-3.11": (
        9675350998,
        "494e99adbec4f189ffa1583ffdd8525cd9b67d42254d623d29da75908759cb3a",
        "core-1.0a-python-3.11/python-3.11.json",
        "523623dcc950a9d1276ce9098350ead170d26a102352695cf9a5d4ddca154b17",
        "cpython-3.11-linux-x86_64",
    ),
    "core-1.0a-python-3.12": (
        9675347580,
        "d6c9b39cc0385eb924c6ad44e31b256ab5f740e033e60296d095cf55e12061e3",
        "core-1.0a-python-3.12/python-3.12.json",
        "7675f2a38ce24ff1780260ff4d192cbb1f02dd1e3d79e5712f4c3c0ddf07626a",
        "cpython-3.12-linux-x86_64",
    ),
    "core-1.0a-python-3.13": (
        9675346810,
        "9b8bfc8dd27e21a12482fc85d5ef0721588bc871acb6e0040026e35bb869bff2",
        "core-1.0a-python-3.13/python-3.13.json",
        "9999686b76cd7b8ebb7e71606d508ea4c946a9306102d17bbd4bfe68d489423f",
        "cpython-3.13-linux-x86_64",
    ),
    "core-1.0a-python-3.14": (
        9675348193,
        "0896a2da2324ec6ae0886d8a2f78e965023459aeaaf294a7b20ca710fbb56868",
        "core-1.0a-python-3.14/python-3.14.json",
        "655857145f0fd3636b5c6099599b7ca5626eeda1cb8fcc78cf3d417493c93edb",
        "cpython-3.14-linux-x86_64",
    ),
}

EXPECTED_PLATFORM_WHEELS = {
    "linux-x86_64": (
        "3.13.15",
        "aether_core_qualification-0.1.0-cp313-cp313-manylinux_2_34_x86_64.whl",
        "cp313-cp313-manylinux_2_34_x86_64",
        "697bc57834d6d1d42b851c11483c6f62f0d401fd7afe9859bf48b63e5568a76e",
    ),
    "windows-x86_64": (
        "3.13.15",
        "aether_core_qualification-0.1.0-cp313-cp313-win_amd64.whl",
        "cp313-cp313-win_amd64",
        "e751ede16f5a398195eeed70844cdf7f023a6aea3de3e69ceaa65d906f9c801f",
    ),
    "macos-x86_64": (
        "3.13.15",
        "aether_core_qualification-0.1.0-cp313-cp313-macosx_10_12_x86_64.whl",
        "cp313-cp313-macosx_10_12_x86_64",
        "01ec9613b961cfc9b53f71c7e476427b6b39feda5b4427adaaca2e033953c4c6",
    ),
    "macos-arm64": (
        "3.13.14",
        "aether_core_qualification-0.1.0-cp313-cp313-macosx_11_0_arm64.whl",
        "cp313-cp313-macosx_11_0_arm64",
        "b2fcfbf70c6708743cad80e3339198269bb84213e225df1f0b4ebf3f14050035",
    ),
}

EXPECTED_PYTHON_WHEELS = {
    "3.11.16": (
        "aether_core_qualification-0.1.0-cp311-cp311-manylinux_2_34_x86_64.whl",
        "cp311-cp311-manylinux_2_34_x86_64",
        "597ecb36dc0c8e84cab3f77d6c5361bf8f598adc014d9ff1f6b8642d63bc2f5a",
    ),
    "3.12.14": (
        "aether_core_qualification-0.1.0-cp312-cp312-manylinux_2_34_x86_64.whl",
        "cp312-cp312-manylinux_2_34_x86_64",
        "0fb1eba321722b29dd75d549aa66097dfd7854b52c60da381a3c4d0d9a9028a9",
    ),
    "3.13.15": (
        "aether_core_qualification-0.1.0-cp313-cp313-manylinux_2_34_x86_64.whl",
        "cp313-cp313-manylinux_2_34_x86_64",
        "1979edf8cd44c75539f57274fa9e89868f8f5791be60e4bdbeb0d6bebf322040",
    ),
    "3.14.7": (
        "aether_core_qualification-0.1.0-cp314-cp314-manylinux_2_34_x86_64.whl",
        "cp314-cp314-manylinux_2_34_x86_64",
        "522d7c99767b116186916f84fe0597da1b7bcf0eee67b69dc6c78fc48182ff6d",
    ),
}

HISTORICAL_FILES = {
    "docs/compiler/CORE_1_0A_IN_PROCESS_COMPILER_CORE_QUALIFICATION.md":
        "087e32005cbec201d719a5042158e0b61dfe0d1b821cc9a0966d0d5be78ba6ee",
    "docs/compiler/core_1_0a_in_process_compiler_core_qualification.json":
        "70c1f0714edf4f7b56f260750784919bd082d8d3b8c6b08062e323e4eac39d14",
}
WORKFLOW_SHA256 = "ecee256558249ded5bcf76f01fc1bbe771664817af249f278459b186cda7739a"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_true(value: object) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("closure evidence must be a JSON object")
    return value


def _check_jobs(evidence: dict[str, object]) -> bool:
    rows = evidence.get("run_jobs")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_JOBS):
        return False
    actual: dict[str, tuple[object, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            return False
        actual[str(row.get("name"))] = (row.get("id"), row.get("conclusion"))
    return actual == {name: (job_id, "success") for name, job_id in EXPECTED_JOBS.items()}


def _check_artifacts(evidence: dict[str, object]) -> bool:
    rows = evidence.get("artifact_manifest")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_ARTIFACTS):
        return False
    actual = {
        str(row.get("artifact_name")): row
        for row in rows
        if isinstance(row, dict)
    }
    if set(actual) != set(EXPECTED_ARTIFACTS):
        return False
    for name, (artifact_id, digest, file_path, file_hash, job) in EXPECTED_ARTIFACTS.items():
        row = actual[name]
        if not (
            row.get("artifact_id") == artifact_id
            and row.get("github_artifact_digest_sha256") == digest
            and row.get("downloaded_archive_sha256") == digest
            and row.get("digest_verified") is True
            and row.get("downloaded_file") == file_path
            and row.get("file_sha256") == file_hash
            and row.get("source_job") == job
            and row.get("source_job_id") == EXPECTED_JOBS[job]
            and row.get("exact_revision") == REVISION
            and row.get("validation_result") == "PASS"
            and SHA256.fullmatch(str(row.get("file_sha256", "")))
        ):
            return False
    return True


def _check_platforms(evidence: dict[str, object]) -> bool:
    rows = evidence.get("platform_matrix")
    if not isinstance(rows, list) or len(rows) != 4:
        return False
    actual = {str(row.get("platform")): row for row in rows if isinstance(row, dict)}
    if set(actual) != set(EXPECTED_PLATFORM_WHEELS):
        return False
    for platform, (python, wheel, tag, wheel_hash) in EXPECTED_PLATFORM_WHEELS.items():
        row = actual[platform]
        if not (
            row.get("python_version") == python
            and row.get("wheel_filename") == wheel
            and row.get("wheel_tag") == tag
            and row.get("wheel_sha256") == wheel_hash
            and row.get("extension_import") == "PASS"
            and row.get("probe_status") == "PASS"
            and row.get("compiler_core_session_creation") == "PASS"
            and row.get("ordinary_operation") == "PASS"
            and row.get("structured_failure") == "PASS"
            and row.get("repeated_use") == "PASS"
            and row.get("companion_contract") == "PASS"
            and row.get("consumer_without_rust_or_cargo") is True
        ):
            return False
    return True


def _check_python_matrix(evidence: dict[str, object]) -> bool:
    rows = evidence.get("python_compatibility_matrix")
    if not isinstance(rows, list) or len(rows) != 4:
        return False
    actual = {str(row.get("python_version")): row for row in rows if isinstance(row, dict)}
    if set(actual) != set(EXPECTED_PYTHON_WHEELS):
        return False
    for version, (wheel, tag, wheel_hash) in EXPECTED_PYTHON_WHEELS.items():
        row = actual[version]
        if not (
            row.get("platform") == "linux-x86_64"
            and row.get("wheel_filename") == wheel
            and row.get("compatibility_tags") == [tag]
            and row.get("wheel_sha256") == wheel_hash
            and row.get("extension_import") == "PASS"
            and row.get("smoke_operation") == "PASS"
            and row.get("clean_consumer_contract") == "PASS"
        ):
            return False
    return True


def _check_historical_files() -> bool:
    return all((ROOT / path).is_file() and _sha256(ROOT / path) == digest for path, digest in HISTORICAL_FILES.items())


def _check_report(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    required = {
        QUALIFIED,
        str(RUN_ID),
        REVISION,
        str(HISTORICAL_RUN_ID),
        HISTORICAL_REVISION,
        "116/116",
        "993, 1000, 5000 y 10000",
        "500",
        "CPython 3.11",
        "CPython 3.14",
        "companion sigue siendo producción y rollback",
        "in-process sigue siendo no-default",
        "CORE-1.1 no fue implementado",
    }
    return all(token in text for token in required)


def build_record(evidence_path: Path, report_path: Path, workflow_path: Path) -> dict[str, object]:
    evidence = _load(evidence_path)
    run = evidence.get("run") if isinstance(evidence.get("run"), dict) else {}
    historical = evidence.get("historical_incident") if isinstance(evidence.get("historical_incident"), dict) else {}
    aggregate = evidence.get("official_aggregate_validation") if isinstance(evidence.get("official_aggregate_validation"), dict) else {}
    semantic = evidence.get("semantic_qualification") if isinstance(evidence.get("semantic_qualification"), dict) else {}
    sessions = evidence.get("sessions_gil_memory") if isinstance(evidence.get("sessions_gil_memory"), dict) else {}
    production = evidence.get("production_regression") if isinstance(evidence.get("production_regression"), dict) else {}
    scope = evidence.get("scope") if isinstance(evidence.get("scope"), dict) else {}
    performance = evidence.get("performance") if isinstance(evidence.get("performance"), dict) else {}

    run_identity = (
        run.get("id") == RUN_ID
        and run.get("exact_revision") == REVISION
        and run.get("workflow") == WORKFLOW_NAME
        and run.get("workflow_path") == ".github/workflows/core-in-process.yml"
        and run.get("repository") == "blas1306/Aether"
    )
    aggregate_valid = (
        aggregate.get("aggregate_artifact_id") == EXPECTED_ARTIFACTS["core-1.0a-aggregate"][0]
        and aggregate.get("aggregate_decision") == QUALIFIED
        and aggregate.get("recomputed_decision") == QUALIFIED
        and aggregate.get("aggregate_errors") == []
        and aggregate.get("input_artifact_count") == 11
        and aggregate.get("official_and_recomputed_byte_identical") is True
        and aggregate.get("aggregate_file_sha256") == EXPECTED_ARTIFACTS["core-1.0a-aggregate"][3]
        and aggregate.get("checker_sha256") == "95316cf90b3b4385c8df71ad71362311ce3bc627e78868a63b13d500ab567481"
        and aggregate.get("validation_result") == "PASS"
    )
    semantic_valid = (
        semantic.get("status") == "PASS"
        and semantic.get("historical_companion") == "116/116"
        and semantic.get("historical_in_process") == "116/116"
        and semantic.get("historical_transport_equivalence") == "116/116"
        and semantic.get("historical_diagnostic_or_downstream_parity") == "116/116"
        and semantic.get("ordinary_cases") == "5/5"
        and semantic.get("initial_ir_and_binding_failure_campaign") == "8/8"
        and semantic.get("ssa_and_refinement_mutation_campaign") == "13/13"
        and semantic.get("deep_cfg") == [993, 1000, 5000, 10000]
        and semantic.get("deep_cfg_status") == "PASS"
    )
    session_memory = sessions.get("memory") if isinstance(sessions.get("memory"), dict) else {}
    sessions_valid = (
        sessions.get("status") == "PASS"
        and _all_true(sessions.get("session_gates"))
        and isinstance(sessions.get("gil_ticker_progress_during_rust"), int)
        and sessions["gil_ticker_progress_during_rust"] > 0
        and session_memory.get("iterations") == 500
        and session_memory.get("unbounded_growth_observed") is False
        and sessions.get("same_session_contract") == "serialized by Mutex<CompilationSession>; idempotent lowering"
    )
    production_valid = (
        production.get("status") == "PASS"
        and _all_true(production.get("gates"))
        and _all_true(production.get("shared_compiler_core_guards"))
        and production.get("default_mode_changed") is False
        and production.get("in_process_is_production_default") is False
        and production.get("companion_remains_production_and_rollback") is True
    )
    scope_valid = scope == {
        "authority_policy_changed": False,
        "companion_remains_production_and_rollback": True,
        "compiler_core_changed_by_closure": False,
        "core_1_1_implemented": False,
        "in_process_is_production_default": False,
        "lifecycle_changed_by_closure": False,
        "refinement_changed_by_closure": False,
        "ssa_changed_by_closure": False,
    }
    history_valid = (
        historical.get("run_id") == HISTORICAL_RUN_ID
        and historical.get("exact_revision") == HISTORICAL_REVISION
        and historical.get("status") == "FAILED"
        and historical.get("decision") == BLOCKED
        and historical.get("immutable") is True
        and len(historical.get("causes", [])) == 2
        and _check_historical_files()
    )
    workload_rows = performance.get("workloads")
    performance_valid = (
        performance.get("correction_gate") is False
        and performance.get("warmups") == 2
        and performance.get("rounds") == 5
        and isinstance(workload_rows, list)
        and {row.get("name") for row in workload_rows if isinstance(row, dict)}
        == {"ordinary", "historical_batch", "deep_cfg", "repository_real"}
        and any(isinstance(row, dict) and row.get("name") == "historical_batch" and row.get("payload_count") == 116 for row in workload_rows)
    )
    workflow_valid = (
        workflow_path.is_file()
        and _sha256(workflow_path) == WORKFLOW_SHA256
        and all(
            token in workflow_path.read_text(encoding="utf-8")
            for token in {
                "semantic-historical-failures-deep",
                "rust-owned-sessions-gil-memory",
                "affected-rust-4.5-production-gates",
                "clean-install-${{ matrix.platform }}",
                "cpython-${{ matrix.python }}-linux-x86_64",
                "aggregate-fail-closed-decision",
            }
        )
    )

    checks = {
        "record_identity": evidence.get("artifact_schema_version") == 1 and evidence.get("kind") == "core_1_0a_in_process_compiler_core_qualification_closure" and evidence.get("milestone") == "CORE-1.0A",
        "run_exact_revision_and_workflow": run_identity,
        "run_success": run.get("status") == "completed" and run.get("conclusion") == "success",
        "required_jobs": _check_jobs(evidence),
        "artifact_manifest": _check_artifacts(evidence),
        "official_aggregate": aggregate_valid,
        "semantic_qualification": semantic_valid,
        "sessions_gil_memory": sessions_valid,
        "production_regression": production_valid,
        "platform_matrix": _check_platforms(evidence),
        "python_compatibility_matrix": _check_python_matrix(evidence),
        "performance_characterization": performance_valid,
        "historical_incident_and_files": history_valid,
        "non_promotion_scope": scope_valid,
        "workflow_unchanged": workflow_valid,
        "report": _check_report(report_path),
        "recorded_eligibility_checks": _all_true(evidence.get("eligibility_checks")),
    }
    eligible = all(checks.values())
    recomputed = QUALIFIED if eligible else BLOCKED
    checks["decision_recomputes"] = evidence.get("final_decision") == recomputed
    passed = eligible and checks["decision_recomputes"]
    return {
        "passed": passed,
        "qualification_eligible": passed and recomputed == QUALIFIED,
        "decision": recomputed if checks["decision_recomputes"] else BLOCKED,
        "run_id": RUN_ID,
        "exact_revision": REVISION,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    args = parser.parse_args()
    try:
        record = build_record(args.evidence, args.report, args.workflow)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"passed": False, "decision": BLOCKED, "error": str(error)}, indent=2))
        return 1
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
