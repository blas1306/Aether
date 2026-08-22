from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_rust_ssa_transport_representation_optimization.py"
EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_transport_representation_optimization.json"
)
REPORT = ROOT / "docs/compiler/RUST_SSA_TRANSPORT_REPRESENTATION_OPTIMIZATION.md"


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_3_9a_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_rust_3_9a_evidence_is_optimized() -> None:
    record = _checker_module().build_record(EVIDENCE, REPORT)

    assert record["decision"] == "RUST_SSA_TRANSPORT_REPRESENTATION_OPTIMIZED"
    assert all(record["checks"].values())


def test_measurement_has_raw_samples_and_causal_phase_effects() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    measurement = evidence["measurement"]
    dual = measurement["modes"]["rust_authority_python_shadow"]

    assert measurement["warmups"] >= 2
    assert measurement["measured_rounds"] >= 7
    assert len(dual["before"]["round_total_samples_seconds"]) == 15
    assert len(dual["after"]["round_total_samples_seconds"]) == 15
    assert dual["after"]["median_seconds"] < dual["before"]["median_seconds"]
    for phase in {
        "rust_transport_serialization",
        "rust_schema_v2_materialization",
        "request_response_transport_and_serialization",
        "python_result_canonicalization",
        "rust_result_canonicalization",
    }:
        row = measurement["affected_phase_medians"][phase]
        assert row["after_seconds"] < row["before_seconds"]
