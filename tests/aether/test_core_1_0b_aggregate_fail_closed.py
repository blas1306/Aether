from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_core_1_0b_in_process_transport.py"
REVISION = "a" * 40
RUN_ID = "424242"


def _checker_module():
    spec = importlib.util.spec_from_file_location("core_1_0b_checker_adversarial", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _both_transport_gate() -> dict[str, dict[str, str]]:
    return {
        "in_process": {"status": "PASS"},
        "companion": {"status": "PASS"},
    }


def _lane(role: str, *, platform: str = "linux-x86_64", python: str = "3.13") -> dict[str, object]:
    failures = [
        {
            "case_id": case_id,
            "same_input_bytes": True,
            "companion_accepts": False,
            "in_process_accepts": False,
            "acceptance_parity": True,
            "machine_diagnostic_parity": True,
            "source_location_parity": True,
            "passed": True,
        }
        for case_id in {
            "malformed_initial_ir_json",
            "non_object_binding_input",
            "unsupported_schema",
            "unknown_root_field",
            "invalid_cfg_target",
            "duplicate_function",
        }
    ]
    record: dict[str, object] = {
        "artifact_schema_version": 1,
        "kind": "core_1_0b_transport_lane",
        "milestone": "CORE-1.0B",
        "status": "PASS",
        "exact_revision": REVISION,
        "ci_run_id": RUN_ID,
        "platform": platform,
        "python_minor": python,
        "matrix_role": role,
        "previous_blocker": "resolved_by_CORE_PKG_1",
        "default_transport": "in_process",
        "automatic_fallback": False,
        "native_distribution": {
            "name": "aether-compiler-core",
            "qualification_only": False,
            "build_identity": REVISION,
        },
        "provenance": {
            "in_process": {
                "requested_transport": "in_process",
                "observed_transport": "in_process",
            },
            "companion": {
                "requested_transport": "companion",
                "observed_transport": "companion",
            },
        },
        "historical": {"status": "PASS"},
        "production_pipeline": {"status": "PASS"},
        "deep_cfg": {"status": "PASS"},
        "sessions_concurrency": {"status": "PASS"},
        "companion_rollback": {"status": "PASS"},
        "representative_failures": {
            "status": "PASS",
            "same_input_structured_campaign": failures,
            "compared_contract": [
                "accept_reject",
                "structured_error_category",
                "phase",
                "source_location",
            ],
        },
        "differential": _both_transport_gate(),
        "differential_divergence": _both_transport_gate(),
        "ssa_refinement_corruptions": _both_transport_gate(),
        "rollback": _both_transport_gate(),
        "rust_4_5_affected": "PASS",
        "packaging_regression": "PASS",
        "ide_cli_shared_pipeline": "PASS",
    }
    if role == "functional":
        phases = {name: 0.001 for name in (
            "conversion", "core", "ipc_protocol", "result_conversion"
        )}
        workloads = {
            name: {
                "phase_samples": 5,
                "phase_median": phases,
                "phase_dispersion_pstdev": phases,
                "samples": 5,
                **({"payloads_per_sample": 116} if name == "historical_116" else {}),
            }
            for name in (
                "ordinary", "historical_116", "deep_cfg_1000", "real_ae_expense_tracker"
            )
        }
        record["historical"] = {
            "status": "PASS",
            "expected": 116,
            "accepted": 116,
            "executed_both_transports": 116,
        }
        record["deep_cfg"] = {
            "status": "PASS",
            "depths": [993, 1000, 5000, 10000],
        }
        record["production_pipeline"] = {
            "status": "PASS",
            "cases": [
                {"full_productive_pipeline": True, "transport_parity": True}
                for _ in range(116)
            ],
        }
        record["performance"] = {
            "in_process": {"workloads": workloads},
            "companion": {"workloads": workloads},
        }
    return record


def _consumer(role: str, transport: str, *, platform: str, python: str) -> dict[str, object]:
    return {
        "artifact_schema_version": 1,
        "kind": (
            "core_1_0b_packaged_clean_consumer"
            if role == "packaged_clean_consumer"
            else "core_1_0b_packaged_consumer"
        ),
        "milestone": "CORE-1.0B",
        "status": "PASS",
        "artifact_role": role,
        "exact_revision": REVISION,
        "ci_run_id": RUN_ID,
        "platform": platform,
        "python_minor": python,
        "expected_transport": transport,
        "default_selection": transport == "in_process",
        "requested_transport": transport,
        "observed_transport": transport,
        "language_version": "1.0.0rc4",
        "native_version": "1.0.0rc4",
        "exact_native_dependency": True,
        "native_build_identity": REVISION,
        "outside_source_checkout": True,
        "source_checkout_available": False,
        "cargo_available": False,
        "rustc_available": False,
        "python_executable": "/clean/bin/python",
        "python_version": "3.13.0",
        "handled_failure_recovery": True,
        "representative_compilation": True,
        "successful_output_sha256": "1" * 64,
        "successful_function_count": 2,
        "companion_from_installed_package": True,
        "process_start_count": 1 if transport == "companion" else 0,
        "request_count": 3,
        "pyo3_binding_calls": 0,
    }


def _install_record() -> dict[str, object]:
    return {
        "artifact_schema_version": 1,
        "kind": "core_1_0b_clean_consumer_install",
        "milestone": "CORE-1.0B",
        "status": "PASS",
        "exact_revision": REVISION,
        "ci_run_id": RUN_ID,
        "wheels": {
            name: {
                "distribution": name,
                "version": "1.0.0rc4",
                "path": f"/wheels/{name}.whl",
                "sha256": character * 64,
            }
            for name, character in (
                ("aether-language", "1"),
                ("aether-compiler-core", "2"),
            )
        },
        "runtime_requirements_from_wheel_metadata": ["numpy==2.4.2"],
        "installed_distributions": [
            {"name": "numpy", "version": "2.4.2"},
            {"name": "aether-language", "version": "1.0.0rc4"},
            {"name": "aether-compiler-core", "version": "1.0.0rc4"},
        ],
        "python_executable": "/clean/bin/python",
        "python_version": "3.13.0",
        "aether_index_resolution_permitted": False,
        "dependency_validation": "pip check PASS",
    }


def _write_complete_evidence(directory: Path, checker) -> None:
    install = _install_record()
    blocker = {
        "artifact_schema_version": 1,
        "kind": "core_pkg_1_native_compiler_core_distribution_closure_check",
        "passed": True,
        "decision": checker.CORE_PKG_1_QUALIFIED,
        "run_id": checker.CORE_PKG_1_RUN_ID,
        "exact_revision": checker.CORE_PKG_1_REVISION,
    }
    for filename, spec in checker._required_ci_artifacts().items():
        if filename == "blocker-resolution.json":
            record = blocker
        elif filename == "core-1.0b-packaged-install.json":
            record = install
        elif spec["kind"] == "core_1_0b_transport_lane":
            record = _lane(
                spec["role"],
                platform=spec.get("platform", "linux-x86_64"),
                python=spec.get("python_minor", "3.13"),
            )
        else:
            record = _consumer(
                spec["role"],
                spec["transport"],
                platform=spec.get("platform", "linux-x86_64"),
                python=spec.get("python_minor", "3.13"),
            )
            if spec["role"] == "packaged_clean_consumer":
                record["install_evidence"] = install
        (directory / filename).write_text(
            json.dumps(record, sort_keys=True) + "\n", encoding="utf-8"
        )


def _check(directory: Path, checker):
    return checker.check(
        directory,
        exact_revision=REVISION,
        ci_run_id=RUN_ID,
        ci_closure=True,
    )


def test_required_consumer_filenames_match_workflow_hyphenated_outputs() -> None:
    checker = _checker_module()
    required = checker._required_ci_artifacts()
    assert "consumer-linux-x86_64-in-process.json" in required
    assert "consumer-python-3.13-in-process.json" in required
    assert not any("in_process.json" in filename for filename in required)


def test_complete_required_evidence_promotes_and_cli_exits_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    aggregate, errors = _check(tmp_path, checker)
    assert errors == []
    assert aggregate["decision"] == checker.PROMOTED
    assert all(aggregate["required_prerequisites"].values())

    output = tmp_path.parent / "aggregate.json"
    monkeypatch.setattr(sys, "argv", [
        str(CHECKER), "--evidence-dir", str(tmp_path), "--revision", REVISION,
        "--ci-run-id", RUN_ID, "--ci-closure", "--require-promoted",
        "--output", str(output),
    ])
    assert checker.main() == 0


def test_missing_packaged_clean_consumer_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    (tmp_path / "core-1.0b-packaged-default.json").unlink()
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert any("missing required CI artifact" in error for error in errors)
    monkeypatch.setattr(sys, "argv", [
        str(CHECKER), "--evidence-dir", str(tmp_path), "--revision", REVISION,
        "--ci-run-id", RUN_ID, "--ci-closure", "--require-promoted",
        "--output", str(tmp_path.parent / "blocked-aggregate.json"),
    ])
    assert checker.main() != 0


def test_failed_packaged_clean_consumer_blocks(tmp_path: Path) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    path = tmp_path / "core-1.0b-packaged-default.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["status"] = "BLOCKED"
    path.write_text(json.dumps(record), encoding="utf-8")
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert any("status is not PASS" in error for error in errors)


def test_corrupt_packaged_clean_consumer_blocks(tmp_path: Path) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    (tmp_path / "core-1.0b-packaged-default.json").write_text("{", encoding="utf-8")
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert any("invalid JSON evidence" in error for error in errors)


def test_packaged_clean_consumer_revision_mismatch_blocks(tmp_path: Path) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    path = tmp_path / "core-1.0b-packaged-default.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["exact_revision"] = "b" * 40
    path.write_text(json.dumps(record), encoding="utf-8")
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert any("revision mismatch" in error for error in errors)


def test_default_observed_transport_mismatch_blocks(tmp_path: Path) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    path = tmp_path / "core-1.0b-packaged-default.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["observed_transport"] = "companion"
    path.write_text(json.dumps(record), encoding="utf-8")
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert any("dedicated packaged-clean-consumer" in error for error in errors)


def test_companion_rollback_not_observed_blocks(tmp_path: Path) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    path = tmp_path / "core-1.0b-packaged-companion.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["observed_transport"] = None
    path.write_text(json.dumps(record), encoding="utf-8")
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert any("dedicated packaged-clean-consumer" in error for error in errors)


def test_another_required_prerequisite_missing_blocks(tmp_path: Path) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    (tmp_path / "development-install.json").unlink()
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert any("development-install.json" in error for error in errors)


def test_redundant_matrix_consumers_do_not_substitute_dedicated_artifact(
    tmp_path: Path,
) -> None:
    checker = _checker_module()
    _write_complete_evidence(tmp_path, checker)
    for filename in checker.PACKAGED_CLEAN_CONSUMER_FILES.values():
        (tmp_path / filename).unlink()
    aggregate, errors = _check(tmp_path, checker)
    assert aggregate["decision"] == checker.BLOCKED
    assert aggregate["packaged_clean_consumer"] is False
    assert len([error for error in errors if "missing required CI artifact" in error]) == 2
