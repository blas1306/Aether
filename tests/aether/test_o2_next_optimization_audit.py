from pathlib import Path

from scripts.o2_next_optimization_audit import generate


def test_o262_audit_has_closed_recommendation_and_required_inventories() -> None:
    root = Path(__file__).resolve().parents[2]
    report = generate(root, ("benchmarks/array_sum.ae", "examples/llvm/list_index.ae"))
    assert report["audit"] == "O2.6.2"
    assert report["corpus_failures"] == []
    assert report["primary_recommendation"] in {
        "PROCEED_TO_MEMORY_READ_LICM", "PROCEED_TO_ARC_OPTIMIZATION",
        "PROCEED_TO_INLINING", "IMPROVE_ANALYSIS_FIRST",
    }
    assert report["general_memory_reads"]["future_policy"].endswith("bounds_checked=false")
    assert report["field_readiness"]["field_sensitive"] is False
    assert "operations" in report["arc"]
    assert "calls" in report["inlining"]
    assert report["production_codegen_changed"] is False
