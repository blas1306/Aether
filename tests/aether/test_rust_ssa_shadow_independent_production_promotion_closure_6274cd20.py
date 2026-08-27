from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = (
    ROOT
    / "scripts/check_rust_ssa_shadow_independent_production_promotion_closure_6274cd20.py"
)
EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_promotion_closure_6274cd20.json"
)
REPORT = (
    ROOT
    / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_6274CD20.md"
)
WORKFLOW = ROOT / ".github/workflows/rust-ssa-shadow.yml"


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_4_5_second_closure", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_evidence(tmp_path: Path, evidence: dict[str, object]) -> Path:
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    return path


def test_official_second_closure_recomputes_promoted() -> None:
    record = _checker_module().build_record(EVIDENCE, REPORT, WORKFLOW)
    assert record["passed"] is True, record["checks"]
    assert record["promotion_eligible"] is True
    assert record["decision"] == "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED"
    assert all(record["eligibility_checks"].values())


def test_second_closure_rejects_a_hand_edited_decision(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["final_decision"] = (
        "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED"
    )
    record = _checker_module().build_record(
        _write_evidence(tmp_path, evidence), REPORT, WORKFLOW
    )
    assert record["passed"] is False
    assert record["checks"]["decision_recomputes"] is False


def test_second_closure_rejects_mixed_revision_artifacts(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["artifact_manifest"][0]["source_revision"] = "0" * 40
    record = _checker_module().build_record(
        _write_evidence(tmp_path, tampered), REPORT, WORKFLOW
    )
    assert record["passed"] is False
    assert record["checks"]["artifact_manifest"] is False
    assert record["eligibility_checks"]["required_artifacts_exact_revision"] is False


def test_second_closure_rejects_invented_well_formed_hash(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["artifact_manifest"][0]["github_artifact_digest_sha256"] = "f" * 64
    record = _checker_module().build_record(
        _write_evidence(tmp_path, tampered), REPORT, WORKFLOW
    )
    assert record["passed"] is False
    assert record["checks"]["artifact_manifest"] is False


def test_second_closure_rejects_rust_4_5a_default_contamination(
    tmp_path: Path,
) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    observation = tampered["rust_4_5a"]["production_default_observation"]
    observation["environment_effective_value"] = (
        "rust_ssa_authority_python_shadow"
    )
    record = _checker_module().build_record(
        _write_evidence(tmp_path, tampered), REPORT, WORKFLOW
    )
    assert record["passed"] is False
    assert record["checks"]["rust_4_5a_evidence"] is False
    assert record["eligibility_checks"]["rust_4_5a_environment_isolation"] is False


def test_second_closure_rejects_rewritten_history_or_architecture(
    tmp_path: Path,
) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["historical_integrity"] = tampered["historical_integrity"][1:]
    tampered["production_architecture"][-1] = "accept"
    record = _checker_module().build_record(
        _write_evidence(tmp_path, tampered), REPORT, WORKFLOW
    )
    assert record["passed"] is False
    assert record["checks"]["historical_integrity"] is False
    assert record["checks"]["production_architecture"] is False


def test_historical_blocked_closure_remains_the_first_record() -> None:
    historical = json.loads(
        (
            ROOT
            / "docs/compiler/rust_ssa_shadow_independent_production_promotion_closure.json"
        ).read_text(encoding="utf-8")
    )
    assert historical["source_run_id"] == 33110365185
    assert historical["exact_revision"] == (
        "b7362b06ead8da36d3ad3a97351fd5813c258590"
    )
    assert historical["final_decision"] == (
        "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED"
    )
