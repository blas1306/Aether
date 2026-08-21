from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

import aether.ssa.shadow as shadow_module
from aether.ir.model import IRModule
from aether.pipeline import SSAPipeline
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailurePolicy,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_rust_ssa_authority_promotion.py"
ARTIFACT = ROOT / "docs/compiler/rust_ssa_authority_promotion.json"
HISTORICAL = ROOT / "docs/compiler/rust_ssa_authority_promotion_qualification.json"
OPERATIONAL = ROOT / "docs/compiler/rust_ssa_shadow_operational_qualified.json"


class _ExplodingClient:
    process_start_count = 0
    request_count = 0

    def lower(self, _payload: bytes):
        self.request_count += 1
        raise RuntimeError("controlled Rust authority failure")


class _EmptyMatchClient:
    process_start_count = 1

    def __init__(self) -> None:
        self.request_count = 0

    def lower(self, _payload: bytes):
        self.request_count += 1
        return {
            "ok": True,
            "ssa": {
                "schema_version": 2,
                "representation": "aether_ssa",
                "functions": [],
                "structs": [],
            },
        }


class _ResponseClient(_EmptyMatchClient):
    def __init__(self, response) -> None:
        super().__init__()
        self.response = response

    def lower(self, _payload: bytes):
        self.request_count += 1
        return self.response


def test_failed_promotion_artifact_remains_historical_evidence() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert report["milestone"] == "RUST-3.6"
    assert report["decision"] == "RUST_SSA_AUTHORITY_PROMOTION_FAILED"
    assert report["scope"]["historical_artifacts_modified"] is False


def test_final_decision_refuses_to_reuse_pre_promotion_platform_evidence() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert report["decision"] == "RUST_SSA_AUTHORITY_PROMOTION_FAILED"
    assert [gate["id"] for gate in report["gates"]] == [f"P{number:02d}" for number in range(1, 17)]
    assert next(gate for gate in report["gates"] if gate["id"] == "P09")["status"] == "PASS"
    assert next(gate for gate in report["gates"] if gate["id"] == "P11")["status"] == "BLOCKED"
    assert next(gate for gate in report["gates"] if gate["id"] == "P12")["status"] == "BLOCKED"
    assert next(gate for gate in report["gates"] if gate["id"] == "P13")["status"] == "BLOCKED"
    assert len(report["unresolved_blockers"]["operational"]) == 3
    assert len(report["unresolved_blockers"]["semantic"]) == 4


def test_failed_promotion_restores_python_authority_rust_shadow_default() -> None:
    assert {mode.name for mode in SSALoweringAuthorityMode} == {
        "PYTHON_SSA_ONLY",
        "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
    }
    assert (
        SSALoweringAuthorityConfiguration().mode
        is SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
    )
    client = _ExplodingClient()
    with pytest.raises(shadow_module.SSAShadowFailure) as caught:
        SSAPipeline(rust_shadow_client=client).run(IRModule())
    assert caught.value.report.classification == "rust_infrastructure_failure"
    assert client.request_count == 1
    with pytest.raises(ValueError, match="requires fail-closed"):
        SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW,
            failure_policy=SSAShadowFailurePolicy.OBSERVE,
        )


def test_safe_default_returns_python_ssa_and_still_rejects_rust_mismatch(
    monkeypatch,
) -> None:
    python_results = []
    original_build = shadow_module.GeneralSSABuilder.build

    def capture_python(self, module):
        value = original_build(self, module)
        python_results.append(value)
        return value

    monkeypatch.setattr(shadow_module.GeneralSSABuilder, "build", capture_python)
    matching = SSAPipeline(rust_shadow_client=_EmptyMatchClient())
    returned = matching.run(IRModule()).ssa_module
    assert returned is python_results[0]
    assert matching.last_returned_ssa_origin == "python_general_ssa_builder"

    mismatched = _ResponseClient(
        {
            "ok": True,
            "ssa": {
                "schema_version": 2,
                "representation": "aether_ssa",
                "functions": [],
                "structs": [{"name": "Mismatch", "fields": []}],
            },
        }
    )
    with pytest.raises(shadow_module.SSAShadowFailure) as caught:
        SSAPipeline(rust_shadow_client=mismatched).run(IRModule())
    assert caught.value.report.classification == "semantic_mismatch"
    assert mismatched.request_count == 1


def test_pipeline_returns_the_imported_rust_object_not_python_shadow(monkeypatch) -> None:
    imported = []
    python_results = []
    original_import = shadow_module.ssa_module_from_dto
    original_build = shadow_module.GeneralSSABuilder.build

    def capture_import(dto):
        value = original_import(dto)
        imported.append(value)
        return value

    def capture_python(self, module):
        value = original_build(self, module)
        python_results.append(value)
        return value

    monkeypatch.setattr(shadow_module, "ssa_module_from_dto", capture_import)
    monkeypatch.setattr(shadow_module.GeneralSSABuilder, "build", capture_python)
    pipeline = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
        ),
        rust_shadow_client=_EmptyMatchClient(),
    )
    result = pipeline.run(IRModule()).ssa_module
    assert result is imported[0]
    assert result is not python_results[0]
    assert pipeline.last_returned_ssa_origin == "rust_schema_v2_import"


def test_python_shadow_runs_after_rust_and_cannot_be_skipped_or_substituted(monkeypatch) -> None:
    client = _EmptyMatchClient()

    def fail_python(_self, _module):
        assert client.request_count == 1
        raise RuntimeError("controlled Python shadow failure")

    monkeypatch.setattr(shadow_module.GeneralSSABuilder, "build", fail_python)
    with pytest.raises(shadow_module.SSAShadowFailure) as caught:
        SSAPipeline(
            authority_configuration=SSALoweringAuthorityConfiguration(
                SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
            ),
            rust_shadow_client=client,
        ).run(IRModule())
    assert caught.value.report.classification == "python_shadow_failure"
    assert client.request_count == 1


@pytest.mark.parametrize(
    ("client", "classification"),
    [
        (_ResponseClient({"ok": True, "ssa": {"malformed": True}}), "malformed_rust_response"),
        (
            _ResponseClient(
                {
                    "ok": True,
                    "ssa": {
                        "schema_version": 2,
                        "representation": "aether_ssa",
                        "functions": [],
                        "structs": [{"name": "Mismatch", "fields": []}],
                    },
                }
            ),
            "semantic_mismatch",
        ),
    ],
)
def test_rust_authority_never_substitutes_python_on_invalid_or_mismatched_rust(
    client, classification
) -> None:
    with pytest.raises(shadow_module.SSAShadowFailure) as caught:
        SSAPipeline(
            authority_configuration=SSALoweringAuthorityConfiguration(
                SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
            ),
            rust_shadow_client=client,
        ).run(IRModule())
    assert caught.value.report.classification == classification
    assert client.request_count == 1


def test_both_rollback_selections_are_configuration_only_and_return_python_ssa() -> None:
    python_only = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_ONLY
        ),
        rust_shadow_client=_ExplodingClient(),
    ).run(IRModule()).ssa_module
    shadow_client = _EmptyMatchClient()
    python_authority = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
        ),
        rust_shadow_client=shadow_client,
    ).run(IRModule()).ssa_module
    assert ssa_module_to_dto(python_only, schema_version=2) == ssa_module_to_dto(
        python_authority, schema_version=2
    )
    assert shadow_client.request_count == 1


def test_native_operational_snapshot_is_qualified_without_rewriting_blocked_history() -> None:
    operational = json.loads(OPERATIONAL.read_text(encoding="utf-8"))
    historical = json.loads(
        (ROOT / "docs/compiler/rust_ssa_shadow_operational_qualification.json").read_text(
            encoding="utf-8"
        )
    )
    assert operational["decision"] == "RUST_SSA_SHADOW_OPERATIONALLY_QUALIFIED"
    assert set(operational["platforms"]) == {
        "linux-x86_64",
        "windows-x86_64",
        "macos-arm64",
        "macos-x86_64",
    }
    assert all(row["status"] == "PASS" for row in operational["platforms"].values())
    assert historical["decision"] == "RUST_SSA_SHADOW_OPERATIONALLY_BLOCKED"


def test_promotion_scope_moves_only_ssa_authority() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert report["authority"]["production_configuration"] == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
    assert report["authority"]["returned_ssa_origin"] == "rust_schema_v2_import"
    assert report["scope"]["production_authority"] == "rust"
    assert report["scope"]["rust_ssa_reaches_optimizer_or_backend"] is True
    assert report["fail_closed_policy"]["silent_python_fallback"] is False


def test_rust_3_5_readiness_evidence_remains_historical_and_unchanged() -> None:
    report = json.loads(HISTORICAL.read_text(encoding="utf-8"))
    assert report["decision"] == "READY_FOR_RUST_SSA_AUTHORITY_SWITCH"
    assert report["scope"]["historical_artifacts_modified"] is False
