from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_rust_ir_2_pre_lifecycle_shadow_qualification_closure_bd156a5.py"
EVIDENCE = ROOT / "docs/compiler/rust_ir_2_pre_lifecycle_shadow_qualification_closure_bd156a5.json"
REPORT = ROOT / "docs/compiler/RUST_IR_2_PRE_LIFECYCLE_SHADOW_QUALIFICATION_CLOSURE_BD156A5.md"
WORKFLOW = ROOT / ".github/workflows/rust-ir-pre-lifecycle-shadow-qualification.yml"


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_ir_2_bd156a5_closure", CHECKER)
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


def _evidence() -> dict[str, object]:
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_official_rust_ir_2_closure_recomputes_qualified() -> None:
    record = _record()
    assert record["passed"] is True, record["checks"]
    assert record["qualification_eligible"] is True
    assert record["decision"] == "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFIED"
    assert all(record["checks"].values())


def test_closure_rejects_hand_edited_decision(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["final_decision"] = "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFICATION_BLOCKED"
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["decision_recomputes"] is False


def test_closure_rejects_wrong_revision(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["run"]["revision"] = "0" * 40
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["run_identity"] is False


def test_closure_rejects_missing_mandatory_job(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["run_jobs"] = evidence["run_jobs"][:-1]
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["required_jobs"] is False


def test_closure_rejects_invented_artifact_digest(tmp_path: Path) -> None:
    evidence = deepcopy(_evidence())
    evidence["artifact_manifest"][0]["github_digest_sha256"] = "f" * 64
    evidence["artifact_manifest"][0]["downloaded_zip_sha256"] = "f" * 64
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["producer_artifacts"] is False


def test_closure_rejects_acceptance_divergence(tmp_path: Path) -> None:
    evidence = deepcopy(_evidence())
    evidence["gates"]["mutation_campaign"]["acceptance_divergences"] = 1
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["mutation_campaign"] is False


def test_closure_rejects_authority_promotion(tmp_path: Path) -> None:
    evidence = deepcopy(_evidence())
    evidence["gates"]["contract_and_authority"]["rust_initial_ir_authority_promoted"] = True
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["authority_scope"] is False


def test_closure_requires_source_owned_refinement_build(tmp_path: Path) -> None:
    evidence = deepcopy(_evidence())
    evidence["gates"]["source_development_install"]["verify_owned_ssa_refinement_built_in_job"] = False
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["source_development_install"] is False


def test_closure_rejects_lsan_ptrace_reinterpretation(tmp_path: Path) -> None:
    evidence = deepcopy(_evidence())
    evidence["gates"]["source_development_install"]["leak_sanitizer_or_ptrace_failures"] = 24
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["source_development_install"] is False


def test_closure_preserves_both_failed_runs(tmp_path: Path) -> None:
    evidence = deepcopy(_evidence())
    evidence["historical_runs"] = evidence["historical_runs"][1:]
    record = _record(_write_evidence(tmp_path, evidence))
    assert record["passed"] is False
    assert record["checks"]["historical_runs_immutable"] is False
