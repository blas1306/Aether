import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_committed_borrow_baseline_reconciles_exact_candidate_set():
    report = json.loads((ROOT / "docs/compiler/o2_collection_extraction_borrow_baseline.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["candidate_count"] == 19
    assert len(report["candidates"]) == 19
    assert len({row["o2_9_2_identity"] for row in report["candidates"]}) == 19
    assert sum(report["classification_counts"].values()) == 19
    assert report["production_freeze"]["arc_before"] == report["production_freeze"]["arc_after"]
    assert not any(report["production_freeze"][key] for key in (
        "local_arc_changed", "lifecycle_changed", "codegen_changed",
        "optimization_profiles_changed", "collection_semantics_changed",
    ))


def test_baseline_candidate_order_is_deterministic():
    report = json.loads((ROOT / "docs/compiler/o2_collection_extraction_borrow_baseline.json").read_text(encoding="utf-8"))
    keys = [(x["workload"], x["function"], x["loop_id"] or "", x["ssa_value"]) for x in report["candidates"]]
    assert keys == sorted(keys)
