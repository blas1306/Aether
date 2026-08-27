from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aether.ir.dto import ir_module_to_dto
from aether.ir.model import IRBasicBlock, IRConst, IRFunction, IRModule, IRReturn, IRValue
from aether.ir.types import IntType, VoidType
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.shadow import canonical_ssa


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/audit_rust_ssa_transport_representation.py"
CHECKER = ROOT / "scripts/check_rust_ssa_transport_representation_reaudit.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_transport_representation_reaudit.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_TRANSPORT_REPRESENTATION_REAUDIT.md"
COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _small_module() -> IRModule:
    value = IRValue("value", IntType())
    return IRModule([
        IRFunction(
            "small", [], VoidType(),
            [IRBasicBlock("entry", [IRConst(value, 1), IRReturn()])],
        )
    ])


def test_flow_map_is_complete_and_exclusively_classified() -> None:
    runner = _load("rust_3_15_flow", RUNNER)
    flow = runner._representation_flow()

    assert len(flow) >= 18
    assert all(row["classification"] in runner.CLASSIFICATIONS for row in flow)
    assert all(
        {
            "source", "destination", "full_traversal", "allocation", "deep_copy",
            "json_encode_decode", "validation", "trust_boundary", "consumer",
            "used_more_than_once", "equivalent_already_materialized",
            "classification",
        } <= set(row)
        for row in flow
    )
    assert sum(row["json_encode_decode"] for row in flow) == 4
    assert any(
        row["destination"] == "Python imported SSA objects"
        and row["classification"] == "SAFETY_BOUNDARY"
        for row in flow
    )


def test_volume_census_and_strict_import_preserve_exact_ssa() -> None:
    runner = _load("rust_3_15_census", RUNNER)
    module = _small_module()
    python_ssa = GeneralSSABuilder().build(module)
    dto = ssa_module_to_dto(python_ssa, schema_version=2)

    census = runner._module_census(module)
    tree = runner._tree_census(dto)
    imported = ssa_module_from_dto(dto)

    assert census["functions"] == 1
    assert census["blocks"] == 1
    assert census["instructions"] == 2
    assert tree["dicts"] > 0 and tree["lists"] > 0
    assert canonical_ssa(ssa_module_to_dto(imported, schema_version=2)) == canonical_ssa(dto)


def test_rust_3_14_surface_is_reconciled_without_schema_import() -> None:
    runner = _load("rust_3_15_baseline", RUNNER)
    baseline = runner._baseline_transport()

    assert baseline["implementation_surface_percent_excluding_schema_import"] == pytest.approx(
        17.600340538800534
    )
    assert baseline["schema_v2_import_percent"] == pytest.approx(14.826150662275102)
    assert baseline["transport_representation_percent_including_schema_import"] == pytest.approx(
        baseline["implementation_surface_percent_excluding_schema_import"]
        + baseline["schema_v2_import_percent"]
    )


def test_checked_in_evidence_is_reaudited() -> None:
    checker = _load("rust_3_15_checker", CHECKER)
    record = checker.build_record(EVIDENCE, REPORT)

    assert record["decision"] == (
        "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDITED_NO_MATERIAL_SAFE_OPTIMIZATION"
    )
    assert all(record["checks"].values())


def test_checker_rejects_double_counted_headline(tmp_path: Path) -> None:
    checker = _load("rust_3_15_checker_corrupt", CHECKER)
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["answer"]["proven_redundant_percent_of_dual_lane"] = 1.0
    path = tmp_path / "corrupt.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    record = checker.build_record(path, REPORT)

    assert record["checks"]["exclusive_answer_reconciles"] is False


def test_historical_removed_representation_work_remains_absent() -> None:
    runner = _load("rust_3_15_history", RUNNER)

    assert all(runner._historical_regression().values())


@pytest.mark.skipif(not COMPANION.is_file(), reason="release companion is not built")
def test_audit_frame_has_exact_shape_and_persists() -> None:
    runner = _load("rust_3_15_exchange", RUNNER)
    module = _small_module()
    payload = json.dumps(ir_module_to_dto(module), separators=(",", ":")).encode()

    with runner.AuditedClient(
        COMPANION, timeout_seconds=60, characterize_performance=True
    ) as client:
        first, first_raw, first_timings = client.exchange(payload)
        pid = client.process_id
        second, second_raw, second_timings = client.exchange(payload)

        assert client.process_start_count == 1
        assert client.request_count == 2
        assert client.process_id == pid

    assert set(first) == set(second) == {"ok", "ssa", "performance"}
    assert len(first_raw) > 0 and len(second_raw) > 0
    assert first_timings["companion_startup_amortized"] >= 0
    assert second_timings["companion_startup_amortized"] == 0
    assert first["ok"] is True
