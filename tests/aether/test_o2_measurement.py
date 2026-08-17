import json
from pathlib import Path

from scripts.o2_measurement import (LLVM_OVERLAP, generate, instruction_census,
    load_manifest, repeated_expressions, runtime_measure)


ROOT = Path(__file__).resolve().parents[2]


def test_manifest_validity_category_closure_and_balance():
    manifest = load_manifest(ROOT)
    assert 25 <= len(manifest["workloads"]) <= 35
    assert {x["kind"] for x in manifest["workloads"]} == {"REAL_WORKLOAD", "REALISTIC_KERNEL", "SYNTHETIC_PROBE"}
    assert {x["category"] for x in manifest["workloads"]} <= set(manifest["categories"])
    assert len({x["path"] for x in manifest["workloads"]}) == len(manifest["workloads"])
    assert sum(x["category"] == "MIXED_REAL_PROGRAM" for x in manifest["workloads"]) < len(manifest["workloads"]) * .7


def test_static_measurement_required_censuses_and_unsupported_reporting():
    report = generate(ROOT, {"categories": load_manifest(ROOT)["categories"], "workloads": load_manifest(ROOT)["workloads"][:2]})
    assert report["audit"].startswith("O2.13")
    assert report["loop_census"]
    assert set(report["ownership_census"]["explicit_ssa"]) == {"global", "loops"}
    assert "backend_implicit_sites" in report["ownership_census"]
    assert "allocation_census" in report and "memory_read_census" in report
    assert "repeated_expression_census" in report and "blocker_census" in report
    for row in report["workloads"]:
        assert row["support"]["initial_ir"]
        for stage in ("ssa_pre_o2", "ssa_o1", "ssa_post_o2"):
            assert "total_instructions" in row["stages"][stage]


def test_candidate_fingerprints_and_overlap_are_stable():
    one = generate(ROOT, {"categories": load_manifest(ROOT)["categories"], "workloads": load_manifest(ROOT)["workloads"][:2]})
    two = generate(ROOT, {"categories": load_manifest(ROOT)["categories"], "workloads": load_manifest(ROOT)["workloads"][:2]})
    assert [x["fingerprint"] for x in one["repeated_expression_census"]] == [x["fingerprint"] for x in two["repeated_expression_census"]]
    assert all(x["llvm_overlap"] in LLVM_OVERLAP for x in one["repeated_expression_census"])
    assert one["pass_impact"] == two["pass_impact"]


def test_checked_in_static_baseline_is_exactly_regenerated():
    expected = json.loads((ROOT / "docs/compiler/o2_measurement_baseline.json").read_text())
    assert generate(ROOT) == expected


def test_runtime_empty_subset_schema_is_a_lightweight_smoke():
    manifest = load_manifest(ROOT)
    result = runtime_measure(ROOT, manifest, limit=0)
    assert result["schema_version"] == 1 and result["results"] == []

