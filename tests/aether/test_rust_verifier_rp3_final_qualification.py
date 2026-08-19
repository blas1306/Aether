from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_rust_verifier_rp3_final_qualification.py"
SPEC = importlib.util.spec_from_file_location("rust13_qualification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


def record() -> dict[str, object]:
    return qualification.build_record()


def test_final_qualification_is_ready_and_deterministic() -> None:
    first = record()
    second = record()
    assert first == second
    assert qualification.render_json(first) == qualification.render_json(second)
    assert first["final_decision"] == "READY_FOR_RP3_AUTHORITY_SWITCH"
    assert json.loads(qualification.render_json(first)) == first


def test_semantic_parity_and_all_operational_gates_are_required() -> None:
    value = record()
    assert value["semantic_parity"]["status"] == "RUST_VERIFIER_SEMANTIC_PARITY_COMPLETE"
    assert value["semantic_parity"]["production_rules"] == 150
    assert all(item["status"] == "PASS" for item in value["operational_gates"].values())

    blocked = deepcopy(value)
    blocked["operational_gates"]["OP4"]["status"] = "BLOCKED"
    assert qualification.evaluate(blocked)[0] == "RP3_AUTHORITY_SWITCH_BLOCKED"
    blocked = deepcopy(value)
    blocked["semantic_parity"]["rust_coverage"] = 149
    assert qualification.evaluate(blocked)[0] == "RP3_AUTHORITY_SWITCH_BLOCKED"


def test_python_authority_rp2_and_no_authority_switch() -> None:
    value = record()
    assert value["current_authority"] == "python"
    assert value["current_migration_phase"] == "RP2"
    assert value["authority_configuration"]["current_default"] == "PYTHON_AUTHORITY_RUST_SHADOW"
    source = (ROOT / value["switch_point"]["file"]).read_text(encoding="utf-8")
    assert "_AUTHORITY_CONFIGURATION = VerifierAuthorityConfiguration(\n    VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW\n)" in source

    for field, replacement in (("current_authority", "rust"), ("current_migration_phase", "RP3")):
        blocked = deepcopy(value)
        blocked[field] = replacement
        assert qualification.evaluate(blocked)[0] == "RP3_AUTHORITY_SWITCH_BLOCKED"


def test_rollback_ci_packaging_cross_platform_and_disagreement_are_required() -> None:
    value = record()
    for field in ("rollback", "rp3_ci", "packaging", "cross_platform", "semantic_disagreement"):
        blocked = deepcopy(value)
        blocked[field]["status"] = "BLOCKED"
        assert qualification.evaluate(blocked)[0] == "RP3_AUTHORITY_SWITCH_BLOCKED"
    assert value["rp3_ci"]["mode"] == "rust_authority_python_shadow"
    assert value["rp3_ci"]["python_shadow"] == "required"
    assert set(value["cross_platform"]["platforms"]) == {
        "linux-x86_64", "windows-x86_64", "macos-arm64", "macos-x86_64"
    }
    assert value["semantic_disagreement"]["fatal_in_rp3"] is True


def test_exact_switch_point_and_full_canary_are_required() -> None:
    value = record()
    assert value["switch_point"] == {
        "file": "src/aether/ir/shadow_verifier.py",
        "symbol": "_AUTHORITY_CONFIGURATION",
        "old_value": "PYTHON_AUTHORITY_RUST_SHADOW",
        "new_value": "RUST_AUTHORITY_PYTHON_SHADOW",
        "phase_registry": "docs/architecture/implementation_language_ownership.json",
    }
    blocked = deepcopy(value)
    blocked["switch_point"]["old_value"] = "RUST_AUTHORITY_PYTHON_SHADOW"
    assert qualification.evaluate(blocked)[0] == "RP3_AUTHORITY_SWITCH_BLOCKED"
    blocked = deepcopy(value)
    blocked["full_canary"]["semantic_mismatches"] = 1
    assert qualification.evaluate(blocked)[0] == "RP3_AUTHORITY_SWITCH_BLOCKED"


def test_historical_snapshots_are_referenced_with_preserved_final_states() -> None:
    value = record()
    expected = {
        "RUST-1": "KEEP_RUST_SHADOW",
        "RUST-1.1": "RUST_VERIFIER_SEMANTIC_PARITY_COMPLETE",
        "RUST-1.2": "RP3_OPERATIONAL_READINESS_BLOCKED",
        "RUST-1.2.1": "COMPANION_PACKAGING_FOUNDATION_READY",
        "RUST-1.2.2": "CROSS_PLATFORM_COMPANION_QUALIFIED",
    }
    assert {key: item["state"] for key, item in value["historical_evidence"].items()} == expected
    for item in value["historical_evidence"].values():
        assert (ROOT / item["artifact"]).is_file()


def test_checked_artifact_matches_builder() -> None:
    checked = json.loads(
        (ROOT / "docs/compiler/rust_initial_ir_verifier_rp3_final_qualification.json").read_text(encoding="utf-8")
    )
    assert checked == record()
