import json
from pathlib import Path
import pytest

from scripts.o2_hot_arc_opportunity_audit import (
    balance, generate, release_category, structural_hotness, workload_kind,
)


ROOT = Path(__file__).resolve().parents[2]
EXPENSE = ("examples/expense_tracker/Main.ae",)


@pytest.fixture(scope="module")
def expense_report() -> dict:
    return generate(ROOT, EXPENSE)


def test_hot_arc_census_loop_depth_balance_and_closed_taxonomies(expense_report) -> None:
    report = expense_report
    assert report["arc_baseline"] == {
        "retain": 34, "release": 884, "total": 918,
        "outside_loops": 852, "functions_with_arc": 17,
    }
    assert report["loop_arc_baseline"] == {
        "retain": 11, "release": 55, "total": 66, "functions": 2, "workloads": 1,
    }
    assert all(site["loop_depth"] >= 1 for site in report["loop_arc_sites"])
    assert {site["loop_role"] for site in report["loop_arc_sites"]} <= {
        "PER_ITERATION_LOCAL", "LOOP_CARRIED_OWNER", "LOOP_INVARIANT_IDENTITY",
        "LOOP_VARIANT_IDENTITY", "CONTAINER_ELEMENT_OWNERSHIP", "AGGREGATE_TEMPORARY",
        "CALL_BOUNDARY_OWNERSHIP", "EXCEPTION_LIFETIME", "DESTRUCTION_ONLY",
        "UNKNOWN_LOOP_ROLE",
    }
    assert {pair["per_iteration_balance"] for pair in report["candidate_pairs"]} <= {
        "BALANCED_PER_ITERATION", "BALANCED_ACROSS_MULTIPLE_ITERATIONS",
        "BALANCED_ONLY_AT_LOOP_EXIT", "PATH_DEPENDENT_BALANCE", "UNKNOWN_BALANCE",
    }


def test_release_blockers_ranking_workload_and_recommendation_are_deterministic(expense_report) -> None:
    report = expense_report
    assert sum(report["release_classification"].values()) == report["arc_baseline"]["release"]
    assert sum(report["blocker_distribution"].values()) == report["arc_baseline"]["total"]
    assert workload_kind("examples/x.ae") == "REAL_WORKLOAD"
    assert workload_kind("tests/x.ae") == "TEST_ONLY"
    assert workload_kind("corpus/x.ae") == "SYNTHETIC_PROBE"
    assert structural_hotness(2, False, "REAL_WORKLOAD") == 6
    assert structural_hotness(2, True, "REAL_WORKLOAD") == 5
    ranked = report["ranked_hot_opportunities"]
    assert [x["structural_hotness"] for x in ranked] == sorted(
        (x["structural_hotness"] for x in ranked), reverse=True
    )
    assert report["final_recommendation"] == "PROCEED_TO_AGGREGATE_LIFETIME_ANALYSIS"
    assert json.dumps(report, sort_keys=True) == json.dumps(report, sort_keys=True)


def test_pure_per_iteration_and_release_classifiers_are_stable() -> None:
    assert balance({"same_loop": True, "crosses_backedge": False,
                    "release_postdominates_retain": True,
                    "retain_dominates_release": True}) == "BALANCED_PER_ITERATION"
    assert balance({"same_loop": True, "crosses_backedge": True,
                    "release_postdominates_retain": True,
                    "retain_dominates_release": True}) == "BALANCED_ACROSS_MULTIPLE_ITERATIONS"
    assert release_category(None, type("V", (), {"type": None})(), False, False) == "PARAMETER_CLEANUP"


def test_committed_hot_arc_json_is_stable_and_complete() -> None:
    path = ROOT / "docs/compiler/o2_hot_arc_opportunity_audit.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(report, sort_keys=True)) == report
    assert report["schema_version"] == 1
    assert report["arc_baseline"]["retain"] == 48
    assert report["arc_baseline"]["release"] == 919
    assert report["loop_arc_baseline"]["retain"] == 11
    assert report["loop_arc_baseline"]["release"] == 55
    assert report["production_codegen_changed"] is False
    assert report["arc_changed"] is False
