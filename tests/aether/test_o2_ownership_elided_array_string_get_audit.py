import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_post_o2_9_5_companion_census_reconciles_all_frozen_sites():
    report = json.loads((ROOT / "docs/compiler/o2_ownership_elided_array_string_get.json").read_text())
    assert report["target_count"] == report["qualified"] == report["transformed"] == 15
    assert len(report["sites"]) == 15
    assert report["whole_pipeline_ssa_arc"] == {
        "before": {"retain": 48, "release": 919, "total": 967},
        "after": {"retain": 48, "release": 904, "total": 952},
    }
    assert report["loop_ssa_arc"] == {
        "before": {"retain": 11, "release": 55, "total": 66},
        "after": {"retain": 11, "release": 40, "total": 51},
    }
    assert all(site["pre"]["backend_retain"] == "emitted" and
               site["pre"]["ssa_release"] is not None and
               site["post"]["backend_retain"] == "prevented" and
               site["post"]["ssa_release"] is None and
               not site["post"]["owned_consumers"] and
               site["array_owner_covers_use"] for site in report["sites"])
