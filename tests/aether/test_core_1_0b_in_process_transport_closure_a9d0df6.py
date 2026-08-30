from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / "docs/compiler/core_1_0b_in_process_production_transport_promotion_closure_a9d0df6.json"
)
REPORT = (
    ROOT
    / "docs/compiler/CORE_1_0B_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_CLOSURE_A9D0DF6.md"
)
CHECKER = ROOT / "scripts/check_core_1_0b_in_process_transport_closure_a9d0df6.py"


def _checker_module():
    spec = importlib.util.spec_from_file_location("core_1_0b_closure", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence() -> dict[str, object]:
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _record(path: Path):
    return _checker_module().build_record(path, REPORT)


def test_exact_closure_passes_and_promotes() -> None:
    checker = _checker_module()
    record = checker.build_record(EVIDENCE, REPORT)
    assert record["passed"] is True
    assert record["decision"] == checker.PROMOTED
    assert all(record["checks"].values())


def test_closure_rejects_wrong_run_revision_event_or_conclusion(tmp_path: Path) -> None:
    mutations = (
        ("run_id", 33293069494),
        ("head_sha", "0" * 40),
        ("event", "pull_request"),
        ("conclusion", "failure"),
    )
    for field, value in mutations:
        tampered = _evidence()
        tampered["official_run"][field] = value
        record = _record(_write(tmp_path, tampered))
        assert record["passed"] is False
        assert record["checks"]["official_run_identity"] is False


def test_closure_rejects_missing_failed_or_mismatched_job(tmp_path: Path) -> None:
    for mutation in ("missing", "failed", "wrong_sha", "wrong_id"):
        tampered = _evidence()
        jobs = tampered["run_jobs"]
        if mutation == "missing":
            jobs.pop()
        elif mutation == "failed":
            jobs[0]["conclusion"] = "failure"
        elif mutation == "wrong_sha":
            jobs[0]["head_sha"] = "0" * 40
        else:
            jobs[0]["id"] = 1
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["required_jobs"] is False


def test_closure_rejects_missing_or_tampered_artifact_identity(tmp_path: Path) -> None:
    mutations = ("missing", "id", "digest", "size", "job", "file_hash", "kind", "role")
    for mutation in mutations:
        tampered = _evidence()
        artifacts = tampered["artifact_manifest"]
        if mutation == "missing":
            artifacts.pop()
        elif mutation == "id":
            artifacts[0]["artifact_id"] = 1
        elif mutation == "digest":
            artifacts[0]["archive_sha256"] = "0" * 64
        elif mutation == "size":
            artifacts[0]["archive_size_bytes"] = 1
        elif mutation == "job":
            artifacts[0]["source_job_id"] = 1
        elif mutation == "file_hash":
            artifacts[0]["extracted_files"][0]["sha256"] = "0" * 64
        elif mutation == "kind":
            artifacts[0]["record_kinds"] = ["core_1_0b_packaged_consumer"]
        else:
            artifacts[0]["record_role"] = "platform"
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["artifact_manifest"] is False


def test_closure_rejects_core_pkg_1_label_without_exact_prerequisite(tmp_path: Path) -> None:
    for field, value in (
        ("decision", "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED"),
        ("run_id", 1),
        ("revision", "0" * 40),
        ("recomputed", False),
    ):
        tampered = _evidence()
        tampered["core_pkg_1_prerequisite"][field] = value
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["core_pkg_1_prerequisite"] is False


def test_closure_rejects_official_or_recomposed_aggregate_divergence(tmp_path: Path) -> None:
    for field, value in (
        ("official_decision", "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED"),
        ("recomposed_decision", "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED"),
        ("recomposed_sha256", "0" * 64),
        ("byte_identical", False),
    ):
        tampered = _evidence()
        tampered["aggregate_validation"][field] = value
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["aggregate_official_and_recomposed"] is False


def test_closure_rejects_transport_provenance_fallback_or_companion_removal(
    tmp_path: Path,
) -> None:
    mutations = (
        ("default_observed", "companion"),
        ("explicit_rollback_observed", "in_process"),
        ("automatic_fallback", True),
        ("mismatch_fails_closed", False),
        ("companion_remains_available", False),
    )
    for field, value in mutations:
        tampered = _evidence()
        tampered["transport_contract"][field] = value
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["transport_contract"] is False


def test_closure_rejects_sessions_functional_or_structured_failure_gap(
    tmp_path: Path,
) -> None:
    tampered = _evidence()
    tampered["sessions_concurrency"]["cross_session_state_leak_observed"] = True
    assert _record(_write(tmp_path, tampered))["checks"]["sessions_concurrency"] is False

    tampered = _evidence()
    tampered["functional_qualification"]["historical"] = "115/116 both transports"
    assert _record(_write(tmp_path, tampered))["checks"]["functional_qualification"] is False

    tampered = _evidence()
    tampered["structured_failure_campaign"]["cases"].pop()
    assert _record(_write(tmp_path, tampered))["checks"]["structured_failure_campaign"] is False


def test_closure_rejects_using_performance_as_correctness_gate(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["performance_characterization"]["correctness_gate"] = True
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["performance_characterization"] is False


def test_closure_rejects_incomplete_platform_or_python_matrix(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["platform_matrix"].pop()
    assert _record(_write(tmp_path, tampered))["checks"]["platform_matrix"] is False

    tampered = _evidence()
    tampered["python_matrix"][0]["patch"] = "3.11.15"
    assert _record(_write(tmp_path, tampered))["checks"]["python_matrix"] is False


def test_closure_rejects_missing_or_substituted_packaged_clean_consumer(
    tmp_path: Path,
) -> None:
    mutations = (
        ("artifact_kind", "core_1_0b_packaged_consumer"),
        ("artifact_role", "platform"),
        ("install_manifest", "core-1-0b-packaged-install.json"),
        ("matrix_records_cannot_substitute", False),
        ("cargo_available", True),
        ("default_observed", "companion"),
        ("companion_pyo3_calls", 1),
    )
    for field, value in mutations:
        tampered = _evidence()
        tampered["packaged_clean_consumer"][field] = value
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["packaged_clean_consumer"] is False


def test_closure_rejects_incomplete_source_development_install(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["source_development_install"]["companion_discovery"] = False
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["source_development_install"] is False


def test_closure_preserves_all_failed_runs_without_retroactive_promotion(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    assert [row["run_id"] for row in evidence["historical_failed_runs"]] == [
        33264243543,
        33265815894,
        33293069494,
    ]
    tampered = deepcopy(evidence)
    tampered["historical_failed_runs"][1]["emitted_promoted_aggregate_valid"] = True
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["historical_failed_runs"] is False


def test_closure_rejects_scope_inflation_or_protocol_removal(tmp_path: Path) -> None:
    for field in (
        "companion_removable",
        "protocol_v1_removable",
        "core_1_1_authorized",
        "universal_platform_support",
        "universal_performance_superiority",
    ):
        tampered = _evidence()
        tampered["scope"][field] = True
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["scope"] is False


def test_closure_rejects_hand_edited_decision(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["decision"] = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED"
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["decision_recomputes"] is False
    assert record["passed"] is False


def test_optional_download_arguments_fail_closed_when_incomplete(tmp_path: Path) -> None:
    checker = _checker_module()
    record = checker.build_record(EVIDENCE, REPORT, archive_dir=tmp_path)
    assert record["checks"]["downloaded_evidence_arguments"] is False
    assert record["passed"] is False


def test_closure_files_are_new_and_do_not_replace_historical_records() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    assert CHECKER.is_file()
    assert EVIDENCE.name.endswith("_a9d0df6.json")
    assert REPORT.name.endswith("_A9D0DF6.md")
    assert (
        ROOT / "docs/compiler/core_1_0b_in_process_production_transport_promotion.json"
    ).is_file()
    assert (
        ROOT / "docs/compiler/core_1_0b_in_process_production_transport_promotion_resumed.json"
    ).is_file()
