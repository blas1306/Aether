from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLOSURE = (
    ROOT
    / "docs/compiler/rust_refine_3_authority_promotion_closure_a5ae9d4b.json"
)
CHECKER = (
    ROOT
    / "scripts/check_rust_refine_3_authority_promotion_closure_a5ae9d4b.py"
)


def _load_checker():
    spec = importlib.util.spec_from_file_location("rust_refine_3_closure", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker():
    return _load_checker()


@pytest.fixture
def closure() -> dict[str, object]:
    return json.loads(CLOSURE.read_text(encoding="utf-8"))


def test_sealed_closure_promotes(checker, closure) -> None:
    result = checker.check(closure)
    assert result == {
        "decision": checker.PROMOTED,
        "passed": True,
        "errors": [],
    }


@pytest.mark.parametrize(
    ("section", "field", "bad_value"),
    [
        ("source_run", "id", "33360257587"),
        ("source_run", "revision", "0" * 40),
        ("source_run", "conclusion", "failure"),
        ("aggregate_artifact", "id", 0),
        ("aggregate_artifact", "zip_sha256", "0" * 64),
        ("aggregate_artifact", "decision_sha256", "0" * 64),
        ("prerequisite", "run_id", "33321279630"),
        ("prerequisite", "official_decision", "BLOCKED"),
        ("authority_provenance", "productive_refinement_authority", "python"),
        ("authority_provenance", "productive_python_refinement_role", "authority"),
        ("authority_provenance", "python_rescue_attempted", True),
        ("authority_provenance", "python_ssa_verifier_retained", False),
    ],
)
def test_closure_blocks_identity_hash_and_authority_tampering(
    checker,
    closure,
    section: str,
    field: str,
    bad_value: object,
) -> None:
    tampered = copy.deepcopy(closure)
    tampered[section][field] = bad_value
    result = checker.check(tampered)
    assert result["decision"] == checker.BLOCKED
    assert result["passed"] is False
    assert result["errors"]


def test_closure_blocks_missing_or_failed_job(checker, closure) -> None:
    for mutation in ("missing", "failed"):
        tampered = copy.deepcopy(closure)
        if mutation == "missing":
            tampered["jobs"].pop()
        else:
            tampered["jobs"][0]["conclusion"] = "failure"
        assert checker.check(tampered)["decision"] == checker.BLOCKED


def test_closure_blocks_artifact_id_digest_zip_evidence_or_status(checker, closure) -> None:
    for field, value in (
        ("id", 0),
        ("github_digest", "sha256:" + "0" * 64),
        ("zip_sha256", "0" * 64),
        ("evidence_sha256", "0" * 64),
        ("status", "MISSING"),
    ):
        tampered = copy.deepcopy(closure)
        tampered["artifacts"][0][field] = value
        assert checker.check(tampered)["decision"] == checker.BLOCKED


def test_closure_blocks_divergence_regression_mutation_and_matrix_loss(
    checker,
    closure,
) -> None:
    mutations = (
        ("evidence_results", "rust_accept_python_reject", 1),
        ("evidence_results", "rust_reject_python_accept", 1),
        ("evidence_results", "valid_acceptance_regressions", 1),
        ("evidence_results", "accepted_mutations", 1),
    )
    for section, field, value in mutations:
        tampered = copy.deepcopy(closure)
        tampered[section][field] = value
        assert checker.check(tampered)["decision"] == checker.BLOCKED
    for matrix in ("platform_matrix", "python_matrix"):
        tampered = copy.deepcopy(closure)
        tampered[matrix].pop()
        assert checker.check(tampered)["decision"] == checker.BLOCKED


def test_closure_blocks_decision_disagreement_or_lost_failed_history(
    checker,
    closure,
) -> None:
    tampered = copy.deepcopy(closure)
    tampered["decision_recomposition"]["independent"]["decision"] = checker.BLOCKED
    assert checker.check(tampered)["decision"] == checker.BLOCKED

    tampered = copy.deepcopy(closure)
    del tampered["prerequisite"]["historical_failed_runs"]["33360257587"]
    assert checker.check(tampered)["decision"] == checker.BLOCKED


@pytest.mark.parametrize(
    ("section", "field", "bad_value"),
    [
        ("packaged_clean_consumer", "checkout_importable", True),
        ("packaged_clean_consumer", "cargo_required", True),
        ("evidence_results", "directed_cases", 222),
        ("evidence_results", "source_full_suite", {}),
        ("api_snapshot_sha256", "artifacts", "0" * 64),
        ("implementation_history", "failed_run_status", "PASS"),
    ],
)
def test_closure_blocks_clean_consumer_campaign_and_seal_tampering(
    checker,
    closure,
    section: str,
    field: str,
    bad_value: object,
) -> None:
    tampered = copy.deepcopy(closure)
    tampered[section][field] = bad_value
    assert checker.check(tampered)["decision"] == checker.BLOCKED


def test_closure_blocks_transport_patch_and_eligibility_tampering(
    checker,
    closure,
) -> None:
    for section, field in (
        ("transport_matrix", "observed"),
        ("platform_matrix", "python_patch"),
        ("python_matrix", "patch"),
    ):
        tampered = copy.deepcopy(closure)
        tampered[section][0][field] = "wrong"
        assert checker.check(tampered)["decision"] == checker.BLOCKED

    tampered = copy.deepcopy(closure)
    del tampered["promotion_eligibility"]["checks"]["clean_packaged_consumer"]
    assert checker.check(tampered)["decision"] == checker.BLOCKED
