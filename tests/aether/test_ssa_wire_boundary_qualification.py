from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_ssa_wire_boundary.py"
EVIDENCE = ROOT / "docs/compiler/ssa_wire_boundary_qualification.json"


def _report() -> dict[str, object]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_historical_a1_evidence_remains_frozen() -> None:
    # RUST-3.A1 describes the dataclass domain that existed when it ran.  A2
    # deliberately extends that domain, so regenerating A1 would rewrite
    # history rather than validate it.
    report = _report()
    assert report["audit"] == "RUST-3.A1-explicit-SSA-wire-schema-v2"
    assert report["decision"] == "SSA_WIRE_SCHEMA_V2_QUALIFIED"
    assert report["corpus"]["summary"]["ssa_wire_roundtrip_passed"] == 116


def test_all_77_instruction_dataclasses_are_field_audited() -> None:
    report = _report()
    inventory = report["instruction_inventory"]
    assert report["instruction_dataclass_count"] == 77 == len(inventory)
    assert len({row["kind"] for row in inventory}) == 77
    assert all(row["fields"] and row["field_count"] == len(row["fields"]) for row in inventory)


def test_schema_delta_is_explicit_and_protocol_v1_is_unchanged() -> None:
    report = _report()
    assert report["decision"] == "SSA_WIRE_SCHEMA_V2_QUALIFIED"
    assert report["ssa_wire_schema_version"] == 2
    assert report["scope_constraints"]["schema_v1_changed"] is False
    assert list(report["schema_delta"]["added_fields"]) == [
        "array_get", "array_set", "list_get", "list_set",
        "matrix_get", "matrix_set", "vector_get", "vector_set",
    ]
    assert all(fields == ["bounds_checked"] for fields in report["schema_delta"]["added_fields"].values())


def test_corpus_gate_excludes_frontend_and_initial_ir_failures() -> None:
    summary = _report()["corpus"]["summary"]
    assert summary["discovered"] == (
        summary["verified_python_ssa_denominator"]
        + summary["pre_ssa_failures_excluded_from_denominator"]
    )
    assert summary["ssa_wire_roundtrip_passed"] + summary["ssa_wire_roundtrip_failed"] == summary["verified_python_ssa_denominator"]
    assert summary["verified_python_ssa_denominator"] == 116
    assert summary["ssa_wire_roundtrip_passed"] == 116
    assert summary["ssa_wire_roundtrip_failed"] == 0
