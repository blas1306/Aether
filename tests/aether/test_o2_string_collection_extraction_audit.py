import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/compiler/o2_string_collection_extraction_audit.json"


def report():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_exact_string_extraction_set_is_deterministic_and_complete():
    data = report()
    assert data["schema_version"] == 1
    assert data["candidate_count"] == len(data["candidates"]) == 19
    assert len({x["o2_9_2_identity"] for x in data["candidates"]}) == 19
    keys = [(x["workload"], x["function"], x["loop_id"] or "", x["string_ssa_value"])
            for x in data["candidates"]]
    assert keys == sorted(keys)


def test_real_categories_and_arc_attribution_are_exact():
    data = report()
    assert data["classification_counts"] == {
        "DIRECT_PROJECTION_CANDIDATE": 15,
        "IMMEDIATE_BORROW_CANDIDATE": 3,
        "STABLE_REGION_BORROW_CANDIDATE": 1,
    }
    assert data["loop_sites"] == 19
    assert data["corrected_theoretical_arc_reduction"] == {"retain": 19, "release": 19}
    assert all(x["current_extraction_arc"] == {"retain": 1, "release": 1}
               for x in data["candidates"])
    assert all(not x["escape"] and not x["array_mutation_crossing"]
               and not x["exceptional_crossing"] for x in data["candidates"])


def test_production_freeze_and_decision():
    data = report()
    freeze = data["production_freeze"]
    assert freeze["arc_before"] == freeze["arc_after"] == {"retain": 48, "release": 919}
    assert not any(value for key, value in freeze.items() if key not in {"arc_before", "arc_after"})
    assert data["recommendation"] == "PROCEED_TO_OWNERSHIP_ELIDED_ARRAY_GET"
