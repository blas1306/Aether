from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_rust_verifier_parity.py"
ARTIFACT = ROOT / "docs/compiler/rust_initial_ir_verifier_parity_closure.json"


def _module():
    spec = importlib.util.spec_from_file_location("rust_parity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_original_twenty_six_are_frozen_closed_and_known() -> None:
    record = _module().build_record()
    gaps = record["original_gaps"]
    assert record["original_gap_count"] == len(gaps) == 26
    assert len({gap["id"] for gap in gaps}) == 26
    assert all(gap["blocker_category"] != "UNKNOWN" for gap in gaps)
    assert all(gap["final_status"] == "PARITY_PROVEN" for gap in gaps)


def test_coverage_is_derived_and_semantic_gate_passes() -> None:
    record = _module().build_record()
    coverage = record["final_rule_mapping"]
    assert coverage == {
        "production_rules": 150,
        "python_evidence": 150,
        "rust_direct_evidence": 150,
        "unresolved": 0,
    }
    assert record["semantic_divergences"] == 0
    assert record["semantic_parity_decision"] == "RUST_VERIFIER_SEMANTIC_PARITY_COMPLETE"
    assert record["authority"] == "python"
    assert record["migration_phase"] == "RP2"


def test_diagnostics_protocol_and_completeness_contracts() -> None:
    record = _module().build_record()
    assert record["diagnostic_divergences"]["classification"] == "ACCEPTABLE_EQUIVALENT_CATEGORY_AND_CONTEXT"
    assert record["canary_results"]["infrastructure_failure"] == 0
    assert record["instruction_coverage"]["unsupported_verification_relevant"] == 0
    assert record["type_coverage"]["lossy_representations"] == 0


def test_checked_in_json_is_byte_deterministic() -> None:
    module = _module()
    assert ARTIFACT.read_text(encoding="utf-8") == module.render(module.build_record())
    assert json.loads(ARTIFACT.read_text(encoding="utf-8"))["revision"] == "RUST-1.1"
