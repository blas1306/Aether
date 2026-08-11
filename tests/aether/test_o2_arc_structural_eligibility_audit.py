import json
from pathlib import Path

from scripts.o2_arc_structural_eligibility_audit import generate


def _report() -> dict:
    root = Path(__file__).resolve().parents[2]
    return generate(root, ("examples/expense_tracker/Main.ae",))


def test_exact_pairs_and_structural_blockers() -> None:
    report = _report()
    assert report["pair_count"] == 2
    assert [(p["ssa_value"], p["retain"], p["release"]) for p in report["pairs"]] == [
        ("1", {"block": "entry", "index": 2}, {"block": "logic.merge5", "index": 33}),
        ("2", {"block": "entry", "index": 4}, {"block": "logic.merge5", "index": 32}),
    ]
    assert {p["primary_blocker"] for p in report["pairs"]} == {"DIFFERENT_BLOCK_BRANCH"}
    assert all(not p["phase1_eligible"] and not p["phase2_eligible"] for p in report["pairs"])


def test_cfg_dominance_paths_joins_and_phis_are_reported() -> None:
    for pair in _report()["pairs"]:
        assert pair["cfg_slice"]["normal_path_count"] == 64
        assert pair["cfg_slice"]["exceptional_path_count"] == 0
        assert pair["dominance"] == {
            "retain_dominates_release": True,
            "retain_dominates_all_relevant_uses": True,
            "release_postdominates_retain": True,
            "release_postdominates_relevant_uses": True,
            "counterexamples": [],
        }
        assert pair["unique_path"]["multiple_normal_paths"] is True
        assert pair["joins"]["count"] == 6
        assert pair["phis"]["count"] == 7
        assert pair["phis"]["pair_value_merged"] is False


def test_json_is_stable_and_audit_is_read_only() -> None:
    first, second = _report(), _report()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["recommendation"] == "PROCEED_TO_NESTED_AGGREGATE_PROVENANCE"
    assert first["production_codegen_changed"] is False
    assert first["arc_transformation_changed"] is False
