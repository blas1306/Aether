from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

from aether.ssa import GeneralSSABuilder
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.shadow import canonical_ssa


ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = ROOT / "scripts/qualify_rust_ssa_shadow_redundancy.py"
CHECKER = ROOT / "scripts/check_rust_ssa_shadow_redundancy.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_shadow_redundancy_qualification.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_SHADOW_REDUNDANCY_QUALIFICATION.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R43 = _load("rust_4_3_qualification_tests", QUALIFIER)
CHECK = _load("rust_4_3_checker_tests", CHECKER)


def test_manifest_is_broad_stable_unique_and_all_mutations_apply() -> None:
    cases = R43.mutation_manifest()
    assert len(cases) >= 40
    assert len({case.mutation_id for case in cases}) == len(cases)
    assert all(case.mutation_id.startswith("R43-") for case in cases)
    assert {case.family for case in cases} >= {
        "cfg_reachability",
        "phi",
        "value_provenance",
        "instruction_preservation",
        "effects",
        "return_termination",
        "slot_promotion",
    }
    fixtures = R43.fixtures()
    for case in cases:
        baseline = ssa_module_to_dto(
            GeneralSSABuilder().build(fixtures[case.fixture]), schema_version=2
        )
        candidate = deepcopy(baseline)
        case.mutate(candidate)
        assert candidate != baseline, case.mutation_id


def test_layer_attribution_detects_semantic_corruption_after_structure() -> None:
    initial = R43.fixtures()["diamond"]
    baseline = ssa_module_to_dto(GeneralSSABuilder().build(initial), schema_version=2)
    case = next(case for case in R43.mutation_manifest() if case.mutation_id == "R43-SLOT-001")
    row = R43.evaluate_candidate(case, initial, baseline, baseline, None)
    assert row["applicable"] is True
    assert row["refinement_rejected"] is True
    assert row["python_shadow_rejected"] is True
    assert row["accepted_without_shadow"] is False
    assert row["classification"] == "REFINEMENT_AND_SHADOW"


def test_alpha_renaming_is_a_legitimate_positive_control() -> None:
    initial = R43.fixtures()["multiple_phi"]
    baseline = ssa_module_to_dto(GeneralSSABuilder().build(initial), schema_version=2)
    renamed = deepcopy(baseline)
    R43._alpha_rename(renamed)
    assert renamed != baseline
    assert canonical_ssa(renamed) == canonical_ssa(baseline)


def test_independence_audit_is_fail_closed_and_finds_no_shared_builder() -> None:
    result = R43.independence_audit()
    assert result["status"] == "PASS"
    assert result["forbidden_import_or_oracle_hits"] == []
    assert result["uses_python_shadow_as_oracle"] is False
    assert result["consumes_rust_producer_intermediates"] is False


def test_checked_committed_evidence_recomputes() -> None:
    record = CHECK.build_record(EVIDENCE, REPORT)
    assert record["passed"] is True, record["checks"]
