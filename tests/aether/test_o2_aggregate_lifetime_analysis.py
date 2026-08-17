import json
from pathlib import Path

from scripts.o2_aggregate_lifetime_analysis import generate


ROOT = Path(__file__).resolve().parents[2]
EXPENSE = ("examples/expense_tracker/Main.ae",)


def test_real_hot_workload_reconciles_every_site_deterministically():
    report = generate(ROOT, EXPENSE)
    # Current-state census: O2.9.5 removed 15 sites and O2.9.7 removed the
    # three immediate Array<String> extraction lifecycles.
    assert report["hot_arc_reconciliation_count"] == 14
    assert report["lifetime_classifications"] == {
        "COPY_INDUCED": 4, "ESCAPE_REQUIRED": 9, "EXTRACTION_TEMPORARY": 1,
    }
    assert report["attribution_counts"] == {
        "COLLECTION_EXTRACTION": 9, "TEMPORARY_DESTROY": 5,
    }
    assert report["recommendation"] == "PROCEED_TO_COLLECTION_EXTRACTION_BORROW_ANALYSIS"
    keys = [(x["workload"], x["function"], x["loop_id"] or "", x["ssa_value"],
             x["block"], x["instruction_index"]) for x in report["hot_arc_reconciliation"]]
    assert keys == sorted(keys)
    assert json.dumps(report, sort_keys=True) == json.dumps(report, sort_keys=True)


def test_committed_baseline_is_complete_and_production_frozen():
    path = ROOT / "docs/compiler/o2_aggregate_lifetime_baseline.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["hot_arc_reconciliation_count"] == 32
    assert len(report["hot_arc_reconciliation"]) == 32
    assert report["production_freeze"] == {
        "arc_before": {"release": 919, "retain": 48},
        "arc_after": {"release": 919, "retain": 48},
        "codegen_changed": False,
        "lifecycle_changed": False,
        "local_arc_changed": False,
        "optimization_profiles_changed": False,
    }
