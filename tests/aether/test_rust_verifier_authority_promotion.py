from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from aether.ir.shadow_verifier import (
    DoubleFailClosedVerifierPipeline,
    VerifierAuthorityConfiguration,
    VerifierAuthorityEnvironment,
    VerifierAuthorityMode,
    VerifierAuthorityPipeline,
    VerifierImplementation,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_rust_verifier_authority_promotion.py"
SPEC = importlib.util.spec_from_file_location("rust2_promotion", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
promotion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(promotion)


class NeverCalledClient:
    def verify(self, request: object) -> object:
        raise AssertionError(request)


def test_historical_authority_pipeline_default_remains_available() -> None:
    configuration = VerifierAuthorityPipeline(client=NeverCalledClient()).configuration
    assert configuration.mode is VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
    assert configuration.environment is VerifierAuthorityEnvironment.DEFAULT
    assert configuration.authority is VerifierImplementation.RUST
    assert configuration.shadow is VerifierImplementation.PYTHON


def test_product_admission_is_explicit_double_fail_closed() -> None:
    pipeline = DoubleFailClosedVerifierPipeline(client=NeverCalledClient())
    assert pipeline.configuration.mode is VerifierAuthorityMode.DOUBLE_FAIL_CLOSED
    assert pipeline.configuration.authority is VerifierImplementation.PYTHON
    assert pipeline.configuration.shadow is VerifierImplementation.RUST
    assert pipeline.configuration.is_double_fail_closed is True


def test_explicit_rp2_rollback_configuration_remains_available() -> None:
    configuration = VerifierAuthorityConfiguration(VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW)
    assert configuration.authority is VerifierImplementation.PYTHON
    assert configuration.shadow is VerifierImplementation.RUST


def test_registry_records_pre_lifecycle_double_fail_closed_shadow() -> None:
    registry = json.loads((ROOT / "docs/architecture/implementation_language_ownership.json").read_text(encoding="utf-8"))
    component = next(item for item in registry["components"] if item["component"] == "initial_ir_verification")
    assert component["current_authority"] == "python"
    assert component["migration_phase"] == "RP2"
    assert component["allowed_shadows"] == ["rust"]
    assert component["operational_readiness_status"] == "double_fail_closed_shadow_integrated"


def test_historical_promotion_artifact_is_not_current_product_authority() -> None:
    first = promotion.build_record()
    second = promotion.build_record()
    assert first == second
    assert first["final_decision"] == "RUST_INITIAL_IR_AUTHORITY_PROMOTION_FAILED"
    checked = json.loads(
        (
            ROOT
            / "docs/compiler/rust_initial_ir_verifier_authority_promotion.json"
        ).read_text(encoding="utf-8")
    )
    assert checked["final_decision"] == "RUST_INITIAL_IR_AUTHORITY_PROMOTED"
    assert checked["python_verifier_retained"] is True


def test_historical_qualification_is_unchanged_and_ready() -> None:
    qualification = json.loads((ROOT / "docs/compiler/rust_initial_ir_verifier_rp3_final_qualification.json").read_text(encoding="utf-8"))
    assert qualification["current_authority"] == "python"
    assert qualification["current_migration_phase"] == "RP2"
    assert qualification["final_decision"] == "READY_FOR_RP3_AUTHORITY_SWITCH"


def test_promotion_preserves_disagreement_failure_and_companion_contract() -> None:
    record = promotion.build_record()
    assert record["policies"]["semantic_disagreement"] == "fatal"
    assert record["policies"]["rust_infrastructure_failure"] == "fail_closed_no_fallback"
    assert record["companion"]["discovery"] == "<aether-home>/libexec/aether/"
    assert record["protocol"] == {"verifier_protocol": 1, "ir_schema": 1, "changed": False}
