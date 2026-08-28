from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_core_1_0a_in_process_closure_6f6851df.py"
EVIDENCE = (
    ROOT
    / "docs/compiler/core_1_0a_in_process_compiler_core_qualification_closure_6f6851df.json"
)
REPORT = (
    ROOT
    / "docs/compiler/CORE_1_0A_IN_PROCESS_COMPILER_CORE_QUALIFICATION_CLOSURE_6F6851DF.md"
)
WORKFLOW = ROOT / ".github/workflows/core-in-process.yml"


def _checker_module():
    spec = importlib.util.spec_from_file_location("core_1_0a_closure", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_evidence(tmp_path: Path, evidence: dict[str, object]) -> Path:
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    return path


def _record(path: Path = EVIDENCE):
    return _checker_module().build_record(path, REPORT, WORKFLOW)


def test_official_core_1_0a_closure_recomputes_qualified() -> None:
    record = _record()
    assert record["passed"] is True, record["checks"]
    assert record["qualification_eligible"] is True
    assert record["decision"] == "CORE_IN_PROCESS_BOUNDARY_QUALIFIED"
    assert all(record["checks"].values())


def test_closure_rejects_hand_edited_decision(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["final_decision"] = (
        "CORE_IN_PROCESS_BOUNDARY_QUALIFICATION_BLOCKED"
    )
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["decision_recomputes"] is False


def test_closure_rejects_mixed_revision_artifact(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["artifact_manifest"][0]["exact_revision"] = "0" * 40
    record = _record(_write_evidence(tmp_path, tampered))
    assert record["passed"] is False
    assert record["checks"]["artifact_manifest"] is False


def test_closure_rejects_invented_well_formed_digest(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["artifact_manifest"][1]["github_artifact_digest_sha256"] = "f" * 64
    tampered["artifact_manifest"][1]["downloaded_archive_sha256"] = "f" * 64
    record = _record(_write_evidence(tmp_path, tampered))
    assert record["passed"] is False
    assert record["checks"]["artifact_manifest"] is False


def test_closure_rejects_missing_required_job(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["run_jobs"] = tampered["run_jobs"][:-1]
    record = _record(_write_evidence(tmp_path, tampered))
    assert record["passed"] is False
    assert record["checks"]["required_jobs"] is False


def test_closure_rejects_incomplete_platform_matrix(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["platform_matrix"] = tampered["platform_matrix"][:-1]
    record = _record(_write_evidence(tmp_path, tampered))
    assert record["passed"] is False
    assert record["checks"]["platform_matrix"] is False


def test_closure_rejects_production_default_contamination(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["production_regression"]["in_process_is_production_default"] = True
    tampered["scope"]["in_process_is_production_default"] = True
    record = _record(_write_evidence(tmp_path, tampered))
    assert record["passed"] is False
    assert record["checks"]["production_regression"] is False
    assert record["checks"]["non_promotion_scope"] is False


def test_historical_blocked_qualification_remains_immutable() -> None:
    checker = _checker_module()
    assert checker._check_historical_files() is True
    blocked = json.loads(
        (
            ROOT
            / "docs/compiler/core_1_0a_in_process_compiler_core_qualification.json"
        ).read_text(encoding="utf-8")
    )
    assert blocked["decision"] == (
        "CORE_IN_PROCESS_BOUNDARY_QUALIFICATION_BLOCKED"
    )
    report = (
        ROOT / "docs/compiler/CORE_1_0A_IN_PROCESS_COMPILER_CORE_QUALIFICATION.md"
    ).read_text(encoding="utf-8")
    assert "33143156047" in report
    assert "2401ab8d56c13d7837aab245735105764e65ade0" in report
