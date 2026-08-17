import json
from pathlib import Path

import pytest

from scripts.o2_hot_arc_opportunity_audit import structural_hotness
from scripts.o2_post_immediate_borrow_optimization_audit import (
    PRIMARY_RECOMMENDATION, SECONDARY_RECOMMENDATION, generate,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/compiler/o2_post_immediate_borrow_optimization_audit.json"


@pytest.fixture(scope="module")
def current():
    return generate(ROOT)


def test_current_post_o297_baseline(current):
    census = current["current_ownership_census"]
    assert (census["explicit_ssa"]["retain"], census["explicit_ssa"]["release"]) == (48, 901)
    assert census["backend_implicit_retains"] == 69
    assert (census["loop_explicit"]["retain"], census["loop_explicit"]["release"]) == (11, 37)
    assert census["loop_implicit_retains"] == 11
    assert len(census["functions_with_loop_ownership"]) == 2
    assert len(census["workloads_with_loop_ownership"]) == 1


def test_stable_candidate_identity_and_status(current):
    stable = current["stable_candidate_analysis"]
    assert stable["candidate_id"].endswith(":%373")
    assert stable["array_root"] == "357" and stable["index"]["value"] == 0
    assert stable["classification"] == "CALL_SUMMARY_EXTENSION"
    assert stable["status"] == "NOT_OPTIMIZED"
    assert stable["theoretical_arc_reduction"] == {"backend_implicit_retain": 1, "explicit_release": 1}


def test_family_counts_hotness_and_llvm_overlap_are_deterministic(current):
    families = {x["family"]: x for x in current["optimization_family_matrix"]}
    assert families["stable borrow"]["static_candidates"] == 1
    assert families["aggregate copy elision"]["static_candidates"] == 4
    assert families["scalar replacement"]["static_candidates"] == 4
    assert structural_hotness(2, False, "REAL_WORKLOAD") == 6
    assert current["llvm_overlap"] == {
        "GVN/CSE": "LLVM_ALREADY_ELIMINATES",
        "aggregate_copy": "LLVM_PARTIAL",
        "scalar_replacement": "AETHER_NEEDED_FOR_EARLIER_PASSES",
        "stable_borrow": "AETHER_CAN_PROVE_MORE",
    }


def test_recommendation_and_json_regeneration_are_deterministic(current):
    assert current["primary_recommendation"] == PRIMARY_RECOMMENDATION
    assert current["secondary_recommendation"] == SECONDARY_RECOMMENDATION
    assert current["exact_next_milestone"]["kind"] == "ANALYSIS_ONLY"
    assert REPORT.read_text(encoding="utf-8") == json.dumps(current, indent=2, sort_keys=True) + "\n"
    assert not any(current["production_freeze"].values())
