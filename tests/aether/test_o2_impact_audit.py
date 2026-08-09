from pathlib import Path

from scripts.o2_impact_audit import generate


def test_o2_impact_audit_is_read_only_and_reports_required_metrics() -> None:
    root = Path(__file__).resolve().parents[2]
    report = generate(root, ("examples/llvm/list_index.ae", "benchmarks/nested_loops.ae"))
    assert report["audit"] == "O2.5.5"
    assert report["list_coverage"]["current"]["PROVEN_SAFE"] == 1
    assert report["o1_o2_list_checks"] == {"O1": 1, "O2": 0, "removed": 1, "preserved": 0}
    assert report["loops"]["natural"] >= 2
    assert report["recommendation"] in {"PROCEED_TO_LICM", "IMPROVE_ANALYSIS_FIRST", "DEFER_LICM"}
