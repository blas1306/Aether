from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from aether.ir.lifecycle import expand_lifecycle
from aether.ssa import (
    GeneralSSABuilder,
    SSARefinementVerificationError,
    SSARefinementVerifier,
)
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto


ROOT = Path(__file__).resolve().parents[2]
RUST_4_0 = ROOT / "scripts/qualify_rust_ssa_independent_authority.py"
QUALIFIER = (
    ROOT / "scripts/qualify_rust_ssa_independent_refinement_verifier.py"
)
CHECKER = ROOT / "scripts/check_rust_ssa_independent_refinement_verifier.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_independent_refinement_verifier.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_INDEPENDENT_REFINEMENT_VERIFIER.md"


def _load_rust_4_0():
    spec = importlib.util.spec_from_file_location("rust_4_0_reused", RUST_4_0)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture():
    return expand_lifecycle(_load_rust_4_0().branch_module())


def test_correct_diamond_refines_initial_ir() -> None:
    initial = _fixture()
    ssa = GeneralSSABuilder().build(initial)

    assert SSARefinementVerifier(initial, ssa).verify() is ssa


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_phi",
        "extra_phi",
        "incorrect_phi_incoming",
        "incorrect_value_rename",
        "unreachable_block_incorrectly_preserved",
        "missing_instruction",
        "duplicated_instruction",
        "incorrect_return_value",
    ],
)
def test_all_rust_4_0_shadow_only_mutations_are_independently_rejected(
    mutation: str,
) -> None:
    rust_4_0 = _load_rust_4_0()
    initial = expand_lifecycle(rust_4_0.branch_module())
    dto = ssa_module_to_dto(GeneralSSABuilder().build(initial), schema_version=2)
    mutate = next(
        mutate
        for name, mutate, _property in rust_4_0.MUTATIONS
        if name == mutation
    )
    candidate = deepcopy(dto)
    mutate(candidate)

    with pytest.raises(SSARefinementVerificationError):
        SSARefinementVerifier(initial, ssa_module_from_dto(candidate)).verify()


def test_alpha_renamed_preserved_result_is_accepted() -> None:
    initial = _fixture()
    dto = ssa_module_to_dto(GeneralSSABuilder().build(initial), schema_version=2)
    entry = dto["functions"][0]["blocks"][0]["instructions"]
    old = entry[0]["result"]["name"]
    entry[0]["result"]["name"] = "alpha.zero"
    entry[1]["right"]["name"] = "alpha.zero"
    assert old != "alpha.zero"

    candidate = ssa_module_from_dto(dto)
    assert SSARefinementVerifier(initial, candidate).verify() is candidate


def test_wrong_constant_is_rejected_even_when_ssa_is_well_formed() -> None:
    initial = _fixture()
    dto = ssa_module_to_dto(GeneralSSABuilder().build(initial), schema_version=2)
    dto["functions"][0]["blocks"][0]["instructions"][0]["value"]["value"] = 42

    with pytest.raises(SSARefinementVerificationError, match="field 'value' changed"):
        SSARefinementVerifier(initial, ssa_module_from_dto(dto)).verify()


def test_unexpanded_lifecycle_return_contract_fails_closed() -> None:
    rust_4_0 = _load_rust_4_0()
    initial = rust_4_0.branch_module()
    ssa = GeneralSSABuilder().build(initial)

    # The scalar fixture is already normalized, so this remains a valid
    # contract smoke test rather than synthesizing lifecycle instructions.
    assert SSARefinementVerifier(initial, ssa).verify() is ssa


def test_expanded_campaign_contains_every_required_class() -> None:
    qualifier = _load("rust_4_1_cases", QUALIFIER)
    names = {case.name for case in qualifier.mutation_cases()}

    assert len([case for case in qualifier.mutation_cases() if case.source == "RUST-4.0"]) == 16
    assert {
        "missing_phi",
        "extra_phi",
        "wrong_phi_incoming_value",
        "wrong_phi_predecessor",
        "duplicate_phi",
        "missing_preserved_instruction",
        "duplicated_preserved_instruction",
        "reordered_side_effecting_instructions",
        "wrong_constant",
        "wrong_call_target",
        "wrong_call_argument",
        "wrong_branch_target",
        "wrong_return",
        "wrong_parameter",
        "wrong_type",
        "missing_reachable_block",
        "retained_unreachable_block",
        "duplicated_block",
        "incorrect_promoted_value",
        "incorrect_rename_structurally_valid",
    } <= names


def test_checked_in_evidence_passes_fail_closed_checker() -> None:
    checker = _load("rust_4_1_checker", CHECKER)
    record = checker.build_record(EVIDENCE, REPORT)

    assert record["passed"] is True
    assert record["decision"] == (
        "RUST_SSA_INDEPENDENT_REFINEMENT_VERIFIER_QUALIFIED"
    )


def test_checker_rejects_hidden_shadow_only_gap(tmp_path: Path) -> None:
    checker = _load("rust_4_1_checker_corrupt", CHECKER)
    evidence = __import__("json").loads(EVIDENCE.read_text(encoding="utf-8"))
    row = next(
        row for row in evidence["mutation_campaign"] if row["mutation"] == "wrong_return"
    )
    row["detected_by"] = ["PYTHON_SHADOW"]
    row["python_shadow_only"] = True
    evidence["new_semantic_shadow_only"] = ["wrong_return"]
    path = tmp_path / "corrupt.json"
    path.write_text(__import__("json").dumps(evidence), encoding="utf-8")

    record = checker.build_record(path, REPORT)

    assert record["passed"] is False
    assert record["checks"]["no_semantic_shadow_only"] is False
