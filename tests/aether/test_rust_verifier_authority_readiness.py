from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/check_rust_verifier_authority_readiness.py"
ARTIFACT = ROOT / "docs/compiler/rust_initial_ir_verifier_authority_readiness.json"


def _audit_module():
    spec = importlib.util.spec_from_file_location("rust_readiness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readiness_artifact_is_deterministic() -> None:
    module = _audit_module()
    assert ARTIFACT.read_text(encoding="utf-8") == module.render(module.build_record())


def test_registry_is_complete_unique_and_has_no_unknown_rules() -> None:
    record = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    rules = record["production_rule_registry"]
    ids = [rule["id"] for rule in rules]
    assert len(ids) == len(set(ids)) == record["rule_coverage_summary"]["production_rules"]
    assert record["rule_coverage_summary"]["python_mapped"] == len(ids)
    assert record["rule_coverage_summary"]["unknown"] == 0
    assert all(rule["parity_status"] != "UNKNOWN" for rule in rules)


def test_instruction_and_type_inventories_match_python_models() -> None:
    module = _audit_module()
    record = module.build_record()
    assert record["instruction_coverage"]["python_instruction_classes"] == module._classes(module.MODEL, "IRInstruction")
    assert record["type_coverage"]["python_type_classes"] == module._classes(module.TYPES, "IRType")
    assert "IRArrayGet" in record["instruction_coverage"]["python_instruction_classes"]
    assert "IRExceptionEventType" not in record["type_coverage"]["python_type_classes"]
    assert "ExceptionEventType" in record["type_coverage"]["python_type_classes"]


def test_stop_conditions_force_keep_shadow_deterministically() -> None:
    record = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert record["rule_coverage_summary"]["divergent_or_missing"] > 0
    assert record["promotion_gates"]["G1"] == "FAIL"
    assert record["promotion_gates"]["G3"] == "FAIL"
    assert record["final_recommendation"] == "KEEP_RUST_SHADOW"
    assert record["exact_rust_2_scope"] is None


def test_protocol_and_infrastructure_are_not_semantic_rejections() -> None:
    record = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert record["protocol_status"]["failures_distinct_from_rejection"] is True
    assert record["infrastructure_failure_policy"] == "FAIL_CLOSED"
    assert "rust_infrastructure_failure" in record["shadow_outcomes"]
