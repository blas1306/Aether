from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = (
    ROOT
    / "scripts/check_rust_ssa_shadow_independent_production_promotion_closure.py"
)
EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_promotion_closure.json"
)
REPORT = (
    ROOT
    / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE.md"
)
WORKFLOW = ROOT / ".github/workflows/rust-ssa-shadow.yml"


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_4_5_closure_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_official_closure_recomputes_fail_closed() -> None:
    record = _checker_module().build_record(EVIDENCE, REPORT, WORKFLOW)
    assert record["passed"] is True, record["checks"]
    assert record["promotion_eligible"] is False
    assert record["decision"] == (
        "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED"
    )
    assert record["eligibility_checks"]["differential_artifact_qualified"] is False
    assert all(
        passed
        for name, passed in record["eligibility_checks"].items()
        if name != "differential_artifact_qualified"
    )


def test_closure_rejects_a_hand_edited_promotion(
    tmp_path: Path,
) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["final_decision"] = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED"
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    record = _checker_module().build_record(path, REPORT, WORKFLOW)
    assert record["passed"] is False
    assert record["checks"]["decision_recomputes"] is False


def test_closure_rejects_mixed_revision_artifacts(
    tmp_path: Path,
) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["artifact_manifest"][0]["source_revision"] = "0" * 40
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    record = _checker_module().build_record(path, REPORT, WORKFLOW)
    assert record["passed"] is False
    assert record["checks"]["artifact_manifest"] is False
    assert record["eligibility_checks"]["required_artifacts_exact_revision"] is False


def test_differential_ci_remains_explicit_and_default_remains_unset() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    default_job = workflow.split(
        "  rust-4-5-shadow-independent-default:", 1
    )[1].split("  rust-4-5-mandatory-differential-shadow:", 1)[0]
    differential_job = workflow.split(
        "  rust-4-5-mandatory-differential-shadow:", 1
    )[1].split("  rust-4-5-clean-install-platform:", 1)[0]

    assert "AETHER_SSA_AUTHORITY_MODE" not in default_job
    assert (
        "AETHER_SSA_AUTHORITY_MODE: rust_ssa_authority_python_shadow"
        in differential_job
    )
    assert "rust-4.5-differential-shadow" in differential_job
