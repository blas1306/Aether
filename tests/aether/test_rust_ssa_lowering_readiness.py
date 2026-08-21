from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_rust_ssa_lowering_readiness.py"
ARTIFACT = ROOT / "docs/compiler/rust_ssa_lowering_readiness.json"


def _module():
    spec = importlib.util.spec_from_file_location("rust_ssa_readiness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_historical_readiness_artifact_is_byte_preserved() -> None:
    # RUST-3.5 must not regenerate this pre-implementation blocked snapshot
    # from today's expanded model.  Pin its historical bytes instead.
    assert sha256(ARTIFACT.read_bytes()).hexdigest() == (
        "d0f76e8f108467207705128729305a320edec0febd7d9f49b0d84b59e123c941"
    )


def test_readiness_blocks_rust_lowering_without_changing_authority_or_rp3() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert report["verdict"] == "RUST_SSA_LOWERING_NOT_READY"
    assert report["scope_constraints"] == {
        "authority_changed": False,
        "backend_changed": False,
        "optimizer_changed": False,
        "rp3_changed": False,
        "rust_lowering_implemented": False,
        "ssa_semantics_changed": False,
    }
    assert report["blocking_rule_ids"]
    assert sum(report["classification_counts"].values()) == len(report["rules"])


def test_inventory_covers_every_current_instruction_dataclass() -> None:
    module = _module()
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert [row["name"] for row in report["inventories"]["initial_ir_instruction_types"]] == [
        item.__name__
        for item in module._concrete_subclasses(module.ir.IRInstruction)
        if not item.__name__.startswith("_")
    ]
    assert [row["name"] for row in report["inventories"]["ssa_instruction_types"]] == [
        item.__name__
        for item in module._concrete_subclasses(module.ssa.SSAInstruction)
        if not item.__name__.startswith("_")
    ]


def test_corpus_measurement_exposes_wire_and_end_to_end_gaps() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    summary = report["corpus"]["summary"]
    assert summary["discovered"] >= 100
    assert summary["python_ssa"] > 0
    assert summary["python_ssa_wire_eligible_percent"] == 100.0
    assert summary["demonstrated_rust_roundtrip_percent"] == 0.0
    assert set(report["corpus"]["by_category"]) == {
        "examples", "exceptions", "expense_tracker", "function_values",
        "numerical_workloads", "string_array_list", "structs_classes_interfaces",
    }


def test_future_differential_is_alpha_invariant_but_metadata_strict() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    design = report["differential_design"]
    assert any("alpha-rename" in step for step in design["comparison"])
    assert any("phi" in step for step in design["comparison"])
    assert {"exception edge kind", "ownership calls", "transferred_storage"} <= set(design["must_not_ignore"])
