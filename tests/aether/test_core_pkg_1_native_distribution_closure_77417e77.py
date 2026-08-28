from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_core_pkg_1_native_distribution_closure_77417e77.py"
EVIDENCE = ROOT / "docs/compiler/core_pkg_1_native_compiler_core_distribution_closure_77417e77.json"
REPORT = ROOT / "docs/compiler/CORE_PKG_1_NATIVE_COMPILER_CORE_DISTRIBUTION_CLOSURE_77417E77.md"


def _checker_module():
    spec = importlib.util.spec_from_file_location("core_pkg_1_closure", CHECKER)
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


def _record(evidence: Path = EVIDENCE):
    return _checker_module().build_record(evidence, REPORT)


def test_official_core_pkg_1_closure_recomputes_qualified() -> None:
    record = _record()
    assert record["passed"] is True, record["checks"]
    assert record["qualification_eligible"] is True
    assert record["decision"] == "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
    assert all(record["checks"].values())


def test_closure_rejects_another_run_or_revision(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["official_run"]["run_id"] = 33188797944
    tampered["official_run"]["head_sha"] = "0" * 40
    record = _record(_write(tmp_path, tampered))
    assert record["passed"] is False
    assert record["checks"]["official_run_identity"] is False


def test_closure_rejects_missing_or_non_success_job(tmp_path: Path) -> None:
    missing = _evidence()
    missing["run_jobs"] = missing["run_jobs"][:-1]
    record = _record(_write(tmp_path, missing))
    assert record["checks"]["required_jobs"] is False

    cancelled = _evidence()
    cancelled["run_jobs"][0]["conclusion"] = "cancelled"
    record = _record(_write(tmp_path, cancelled))
    assert record["checks"]["required_jobs"] is False


def test_closure_rejects_artifact_id_digest_or_file_hash_substitution(tmp_path: Path) -> None:
    for field, value in (
        ("artifact_id", 1),
        ("github_digest_sha256", "f" * 64),
        ("archive_sha256", "f" * 64),
    ):
        tampered = _evidence()
        tampered["artifact_manifest"][0][field] = value
        record = _record(_write(tmp_path, tampered))
        assert record["checks"]["artifact_manifest"] is False

    tampered = _evidence()
    tampered["artifact_manifest"][7]["extracted_files"][0]["sha256"] = "e" * 64
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["artifact_manifest"] is False


def test_closure_rejects_non_reproducible_or_blocked_aggregate(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["official_aggregate_validation"]["comparison"] = "semantic-identical"
    tampered["official_aggregate_validation"]["official_and_recomputed_byte_identical"] = False
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["official_aggregate"] is False

    tampered = _evidence()
    tampered["official_aggregate_validation"]["aggregate_decision"] = (
        "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED"
    )
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["official_aggregate"] is False


def test_closure_rejects_weakened_package_or_core_identity(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["package_contract"]["native_dependency"] = "aether-compiler-core>=1.0.0rc4"
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["package_contract"] is False

    tampered = _evidence()
    tampered["compiler_core_identity"]["build_identity"] = "0" * 40
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["compiler_core_identity"] is False


def test_closure_rejects_incomplete_platform_or_python_matrix(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["platform_matrix"] = tampered["platform_matrix"][:-1]
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["platform_matrix"] is False

    tampered = _evidence()
    tampered["python_matrix"][0]["python_version"] = "3.11.0"
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["python_matrix"] is False


def test_closure_rejects_failed_binding_companion_source_or_failure_gate(tmp_path: Path) -> None:
    mutations = (
        ("binding_installed_smoke", "qualification_only", True, "binding_installed_smoke"),
        ("companion_installed_rollback", "protocol_v1", False, "companion_installed_rollback"),
        ("source_development_install", "binding_import", "FAIL", "source_development_install"),
        ("failure_campaign", "passed", 12, "failure_campaign"),
    )
    for section, field, value, check in mutations:
        tampered = _evidence()
        tampered[section][field] = value
        record = _record(_write(tmp_path, tampered))
        assert record["checks"][check] is False


def test_closure_rejects_pyo3_promotion_or_companion_removal(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["production_architecture_guard"]["production_transport"] = "in-process"
    tampered["production_architecture_guard"]["pyo3_is_production_default"] = True
    tampered["scope"]["pyo3_is_production_default"] = True
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["production_companion_default_guard"] is False
    assert record["checks"]["closure_scope"] is False


def test_closure_rejects_rewriting_historical_failure(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["historical_failed_run"]["conclusion"] = "success"
    tampered["historical_failed_run"]["aggregate_decision"] = (
        "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
    )
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["historical_failed_run"] is False


def test_closure_rejects_hand_edited_decision_or_eligibility(tmp_path: Path) -> None:
    tampered = _evidence()
    tampered["final_decision"] = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED"
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["decision_recomputes"] is False

    tampered = _evidence()
    del tampered["eligibility_checks"]["exact_revision_gate"]
    record = _record(_write(tmp_path, tampered))
    assert record["checks"]["declared_eligibility"] is False


def test_pre_ci_document_and_productive_sources_remain_pinned() -> None:
    checker = _checker_module()
    evidence = _evidence()
    assert checker._check_source_snapshot(evidence, ROOT) is True
    assert evidence["source_snapshot"][
        "docs/compiler/CORE_PKG_1_NATIVE_COMPILER_CORE_DISTRIBUTION.md"
    ] == "cf9557da2c82643c4f17ca83ab54ab95ea92e04a72a317c28c0774feca7356bb"


def test_closure_scope_is_distribution_only() -> None:
    evidence = _evidence()
    scope = evidence["scope"]
    assert scope["core_1_0b_promoted"] is False
    assert scope["core_1_1_authorized_or_implemented"] is False
    assert scope["semantic_changes_in_closure"] is False
    assert scope["pyo3_is_production_default"] is False
    assert scope["companion_can_be_removed"] is False
    assert scope["universal_platform_or_python_correctness"] is False


def test_checker_optional_download_arguments_fail_closed_when_incomplete(tmp_path: Path) -> None:
    checker = _checker_module()
    record = checker.build_record(EVIDENCE, REPORT, archive_dir=tmp_path)
    assert record["passed"] is False
    assert record["checks"]["downloaded_evidence_arguments"] is False


def test_closure_files_are_separate_from_pre_ci_artifacts() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    assert CHECKER.is_file()
    assert EVIDENCE.name.endswith("_77417e77.json")
    assert REPORT.name.endswith("_77417E77.md")
    assert (ROOT / "docs/compiler/core_pkg_1_native_compiler_core_distribution.json").is_file()
    assert (ROOT / "docs/compiler/CORE_PKG_1_NATIVE_COMPILER_CORE_DISTRIBUTION.md").is_file()
