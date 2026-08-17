import json
from pathlib import Path
import pytest

from scripts.o2_hot_arc_opportunity_audit import structural_hotness
from scripts.o2_post_arrayget_hot_ownership_audit import RECOMMENDATION, generate


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "docs/compiler/o2_post_arrayget_hot_ownership_audit.json"


def _report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def current_production_report() -> dict:
    return generate(ROOT)


def test_historical_o296_explicit_and_loop_arc_census() -> None:
    report = _report()
    assert report["explicit_ssa_arc_baseline"]["retain"] == 48
    assert report["explicit_ssa_arc_baseline"]["release"] == 904
    assert report["explicit_ssa_arc_baseline"]["total"] == 952
    assert report["loop_ownership_baseline"]["retain"] == 11
    assert report["loop_ownership_baseline"]["release"] == 40
    assert report["loop_ownership_baseline"]["total"] == 51


def test_layers_and_release_asymmetry_reconcile() -> None:
    report = _report()
    assert report["implicit_backend_arc_baseline"]["total"] == len(
        report["backend_implicit_retain_sites"]
    )
    assert all(x["operation_layer"] == "BACKEND_IMPLICIT"
               for x in report["backend_implicit_retain_sites"])
    asymmetry = report["release_asymmetry"]
    assert asymmetry["releases"] - asymmetry["retains"] == asymmetry["difference"] == 29
    assert asymmetry["classification_total"] == asymmetry["releases"]


def test_removed_and_remaining_array_string_sets() -> None:
    report = _report()
    assert report["o2_9_5_removed_count"] == len(report["o2_9_5_removed_sites"]) == 15
    assert all(x["current_borrowed"] and x["ssa_release"] is None and
               x["backend_temporary_retain"] == "prevented"
               for x in report["o2_9_5_removed_sites"])
    assert report["remaining_array_string_counts"] == {
        "IMMEDIATE_BORROW_CANDIDATE": 3,
        "STABLE_REGION_BORROW_CANDIDATE": 1,
    }


def test_hotness_ranking_and_recommendation_are_deterministic() -> None:
    report = _report()
    assert structural_hotness(2, False, "REAL_WORKLOAD") == 6
    ranked = report["structural_hotness"]["ranked_sites"]
    assert [x["structural_hotness"] for x in ranked] == sorted(
        (x["structural_hotness"] for x in ranked), reverse=True
    )
    assert report["final_recommendation"] == RECOMMENDATION
    families = report["optimization_family_matrix"]
    assert [x["family"] for x in families] == [
        "IMMEDIATE_ARRAY_STRING_BORROW", "STABLE_ARRAY_STRING_BORROW",
        "AGGREGATE_COPY_ELISION", "LIST_STRING_OWNERSHIP_ELISION",
        "REFERENCE_ELEMENT_OWNERSHIP_ELISION", "ESCAPE_STACK_PROMOTION",
        "GVN_CSE", "GENERAL_LOOP_OPTIMIZATION",
    ]


def test_committed_historical_json_is_canonical_and_production_was_frozen() -> None:
    report = _report()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    assert REPORT_PATH.read_text(encoding="utf-8") == rendered
    # O2.9.6 is an immutable post-O2.9.5 snapshot.  Its generator observes the
    # current compiler, so regenerating it after O2.9.7 is not its historical
    # validation contract.
    assert report["schema_version"] == 1
    freeze = report["production_freeze"]
    assert freeze["ssa_arc_before"] == freeze["ssa_arc_after"]
    assert not any(value for key, value in freeze.items()
                   if key.endswith("_changed"))


def test_current_post_o297_production_census(current_production_report: dict) -> None:
    report = current_production_report
    assert report["explicit_ssa_arc_baseline"] == {
        "retain": 48, "release": 901, "total": 949,
        "outside_loops": 901, "functions_with_arc": 34,
    }
    assert report["implicit_backend_arc_baseline"] == {
        "AGGREGATE_COMPONENT_RETAIN": 9,
        "BACKEND_IMPLICIT_RETAIN": 60,
        "total": 69,
    }
    assert report["loop_ownership_baseline"]["retain"] == 11
    assert report["loop_ownership_baseline"]["release"] == 37
    assert report["loop_ownership_baseline"]["backend_implicit_retain"] == 11
