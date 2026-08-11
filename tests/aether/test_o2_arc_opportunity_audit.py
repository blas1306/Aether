import json
from pathlib import Path

from scripts.o2_arc_opportunity_audit import generate


def test_o285_discovers_arc_pairs_and_uses_closed_classifications() -> None:
    root = Path(__file__).resolve().parents[2]
    report = generate(root, (
        "examples/classes/implements_interface.ae",
        "corpus/exceptions/positive/constructor_failure.ae",
    ))
    assert report["audit"] == "O2.8.6-exact-provenance"
    assert report["arc_counts"]["ssa"]["retain"] > 0
    assert report["arc_counts"]["ssa"]["release"] > 0
    assert report["candidate_count"] == len(report["candidates"])
    allowed = {
        "PROVABLE_NOW", "BLOCKED_PROVENANCE", "BLOCKED_METHODRESULT", "BLOCKED_CONSTRUCTOR_LIFECYCLE",
        "BLOCKED_NESTED_AGGREGATE", "BLOCKED_EXCEPTION_JOIN", "BLOCKED_NORMAL_JOIN",
        "BLOCKED_ESCAPE_UNKNOWN", "BLOCKED_ALIAS_UNKNOWN", "BLOCKED_INTERFACE_BOX",
        "BLOCKED_CALL_SUMMARY", "NOT_REDUNDANT",
    }
    assert {item["classification"] for item in report["candidates"]} <= allowed
    assert all(item["workload_kind"] == "REAL_WORKLOAD" for item in report["candidates"])
    assert report["production_codegen_changed"] is False
    assert report["arc_changed"] is False
    assert all(
        item["productive_classification"] == "ELIGIBLE"
        for item in report["candidates"]
        if item["classification"] == "PROVABLE_NOW"
    )
    assert set(report["local_arc_dry_run"]) == {
        "phase1_semantic_candidates", "phase1_structural_candidates",
        "phase2_semantic_candidates", "phase2_structural_candidates",
        "would_eliminate",
    }
    assert all(set(item["crosses"]) == {
        "call", "phi", "field", "collection", "interface", "exception_edge",
        "method_result", "runtime_helper",
    } for item in report["candidates"])
    assert all(
        item["classification"] != "PROVABLE_NOW"
        for item in report["candidates"]
        if item["provenance"]["exact"] is False
    )


def test_o285_methodresult_constructor_and_json_are_deterministic() -> None:
    root = Path(__file__).resolve().parents[2]
    corpus = ("corpus/exceptions/positive/constructor_failure.ae",)
    first = generate(root, corpus)
    second = generate(root, corpus)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["contexts"].get("METHODRESULT", 0) > 0
    assert first["candidate_classifications"].get("PROVABLE_NOW", 0) == 0


def test_committed_o285_report_has_required_precision_and_readiness_sections() -> None:
    root = Path(__file__).resolve().parents[2]
    report = json.loads((root / "docs/compiler/o2_arc_opportunity_audit.json").read_text())
    assert report["recommendation"] in {
        "PROCEED_TO_LOCAL_ARC_ELIMINATION", "IMPROVE_CONSTRUCTOR_METHODRESULT_OWNERSHIP",
        "IMPROVE_EXACT_OWNERSHIP_PROVENANCE",
        "IMPROVE_NESTED_AGGREGATE_OWNERSHIP", "IMPROVE_OWNERSHIP_JOIN_PRECISION",
        "DEFER_ARC_OPTIMIZATION",
    }
    assert len(report["precision_scorecard"]) >= 6
    assert set(report["local_readiness"]) == {
        "same_block", "straight_line_multi_block", "after_exception_region_exclusion",
    }
