from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder


ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = ROOT / "scripts/qualify_rust_ssa_independent_authority.py"
CHECKER = ROOT / "scripts/check_rust_ssa_independent_authority_qualification.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_independent_authority_qualification.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_INDEPENDENT_AUTHORITY_QUALIFICATION.md"
COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
RUST_VERIFIER = ROOT / "compiler-rs/target/debug/examples/verify_owned_ssa_v2"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trust_inventory_and_property_matrix_are_complete() -> None:
    qualifier = _load("rust_4_0_inventory", QUALIFIER)

    inventory = qualifier.trust_inventory()
    matrix = qualifier.property_matrix()

    assert len(inventory) == 16
    assert {row["layer"] for row in inventory} >= {
        "rust_ssa_implementation",
        "python_shadow_implementation",
        "canonical_comparison",
        "rust_side_verification",
        "rollback_modes",
    }
    assert len(matrix) == 18
    assert {row["classification"] for row in matrix} <= {
        "INDEPENDENTLY_VERIFIED",
        "DIFFERENTIALLY_VERIFIED_ONLY",
        "SELF_VERIFIED",
        "TEST_ONLY",
        "SHADOW_ONLY",
        "REDUNDANTLY_VERIFIED",
        "INSUFFICIENT_EVIDENCE",
    }
    unreachable = next(row for row in matrix if row["property"] == "unreachable block handling")
    assert unreachable["classification"] == "SHADOW_ONLY"


def test_mutation_campaign_finds_well_formed_shadow_only_failures() -> None:
    qualifier = _load("rust_4_0_mutations", QUALIFIER)
    baseline = ssa_module_to_dto(
        GeneralSSABuilder().build(qualifier.branch_module()), schema_version=2
    )
    rows = qualifier.run_mutation_campaign(baseline, deepcopy(baseline), None)
    indexed = {row["mutation"]: row for row in rows}

    assert set(indexed) == {name for name, _mutation, _property in qualifier.MUTATIONS}
    for name in (
        "missing_phi",
        "extra_phi",
        "incorrect_phi_incoming",
        "incorrect_return_value",
        "unreachable_block_incorrectly_preserved",
    ):
        assert indexed[name]["python_shadow_only"] is True
        assert indexed[name]["detected_by"] == [
            "CANONICAL_COMPARISON", "PYTHON_SHADOW_ONLY"
        ]
    assert "PYTHON_IMPORTED_SSA_VERIFIER" in indexed["duplicate_definition"]["detected_by"]
    assert "PYTHON_IMPORTED_SSA_VERIFIER" in indexed["use_before_definition"]["detected_by"]


@pytest.mark.skipif(
    not COMPANION.is_file() or not RUST_VERIFIER.is_file(),
    reason="Rust qualification binaries are not built",
)
def test_real_rust_result_executes_every_mutation_against_both_verifiers() -> None:
    qualifier = _load("rust_4_0_real_campaign", QUALIFIER)
    evidence = qualifier.build_evidence(COMPANION, RUST_VERIFIER)

    assert evidence["decision"] == (
        "RUST_SSA_INDEPENDENT_AUTHORITY_REQUIRES_VERIFIER_HARDENING"
    )
    assert evidence["baseline"]["campaign_fixture_rust_python_canonical_match"] is True
    assert all(row["rust_verifier_executed"] for row in evidence["mutation_campaign"])
    assert len(evidence["shadow_only_mutations"]) >= 5


def test_checked_in_rust_4_0_evidence_passes_checker() -> None:
    checker = _load("rust_4_0_checker", CHECKER)
    record = checker.build_record(EVIDENCE, REPORT)

    assert record["passed"] is True
    assert record["decision"] == (
        "RUST_SSA_INDEPENDENT_AUTHORITY_REQUIRES_VERIFIER_HARDENING"
    )
    assert all(record["checks"].values())


def test_checker_fails_closed_if_shadow_only_findings_are_hidden(tmp_path: Path) -> None:
    checker = _load("rust_4_0_checker_corrupt", CHECKER)
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["shadow_only_mutations"] = []
    path = tmp_path / "corrupt.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    record = checker.build_record(path, REPORT)

    assert record["passed"] is False
    assert record["checks"]["concrete_shadow_only_found"] is False
    assert record["decision"] == "RUST_SSA_INDEPENDENT_AUTHORITY_QUALIFICATION_BLOCKED"


def test_qualification_freezes_production_and_keeps_shadow_mandatory() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")

    assert evidence["production_invariants"]["production_changed"] is False
    assert evidence["production_invariants"]["shadow_remains_mandatory"] is True
    assert evidence["future_architecture"]["promotion_allowed_by_rust_4_0"] is False
    assert "python_ssa = run_python()" in source
    assert "difference = _difference(python_canonical, rust_canonical)" in source
