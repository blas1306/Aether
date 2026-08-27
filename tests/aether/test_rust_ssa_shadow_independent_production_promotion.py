from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

import pytest

from aether.ir.model import IRModule
from aether.pipeline import SSAPipeline
from aether.ssa import GeneralSSABuilder
from aether.ssa.shadow import (
    RUST_SSA_QUALIFICATION_EXECUTABLE_ENV,
    SSA_AUTHORITY_MODE_ENV,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
    lower_with_rust_authority,
)
from aether.ssa.shadow_independent import (
    SHADOW_INDEPENDENT_STAGE_MANIFEST,
    ShadowIndependentRustAuthorityFailure,
)


EMPTY_RESPONSE = {
    "ok": True,
    "ssa": {
        "schema_version": 2,
        "representation": "aether_ssa",
        "functions": [],
        "structs": [],
    },
}
ROOT = Path(__file__).resolve().parents[2]
CHECKER = (
    ROOT
    / "scripts/check_rust_ssa_shadow_independent_production_promotion.py"
)
EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_promotion.json"
)
REPORT = (
    ROOT / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION.md"
)


class StaticClient:
    process_start_count = 1

    def __init__(self, response: object = EMPTY_RESPONSE):
        self.response = response
        self.request_count = 0
        self.payloads: list[bytes] = []

    def lower(self, payload: bytes) -> Mapping[str, object]:
        self.request_count += 1
        self.payloads.append(payload)
        if isinstance(self.response, BaseException):
            raise self.response
        return deepcopy(self.response)  # type: ignore[return-value]


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_4_5_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_override_selects_new_production_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SSA_AUTHORITY_MODE_ENV, raising=False)
    configuration = SSALoweringAuthorityConfiguration()
    assert (
        configuration.mode
        is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED
    )


@pytest.mark.parametrize("mode", list(SSALoweringAuthorityMode))
def test_explicit_environment_policy_selects_every_preserved_mode(
    monkeypatch: pytest.MonkeyPatch, mode: SSALoweringAuthorityMode
) -> None:
    monkeypatch.setenv(SSA_AUTHORITY_MODE_ENV, mode.value)
    assert SSALoweringAuthorityConfiguration().mode is mode


def test_invalid_environment_policy_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SSA_AUTHORITY_MODE_ENV, "automatic_fallback")
    with pytest.raises(ValueError, match="invalid AETHER_SSA_AUTHORITY_MODE"):
        SSALoweringAuthorityConfiguration()


def test_explicit_configuration_has_priority_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SSA_AUTHORITY_MODE_ENV, "invalid-but-not-consulted")
    configuration = SSALoweringAuthorityConfiguration(
        SSALoweringAuthorityMode.PYTHON_SSA_ONLY
    )
    assert configuration.mode is SSALoweringAuthorityMode.PYTHON_SSA_ONLY


def test_selected_policy_is_inherited_by_child_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SSA_AUTHORITY_MODE_ENV,
        SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW.value,
    )
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.fspath(root / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from aether.ssa.shadow import SSALoweringAuthorityConfiguration; "
            "print(SSALoweringAuthorityConfiguration().mode.value)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.stdout.strip() == "rust_ssa_authority_python_shadow"


def test_internal_companion_override_cannot_change_production_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SSA_AUTHORITY_MODE_ENV, raising=False)
    monkeypatch.setenv(RUST_SSA_QUALIFICATION_EXECUTABLE_ENV, "/tmp/not-run")
    assert (
        SSALoweringAuthorityConfiguration().mode
        is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED
    )


def test_new_default_has_exact_order_and_no_python_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Python SSA or canonical comparison executed")

    monkeypatch.delenv(SSA_AUTHORITY_MODE_ENV, raising=False)
    monkeypatch.setattr(GeneralSSABuilder, "__init__", forbidden)
    monkeypatch.setattr(GeneralSSABuilder, "build", forbidden)
    monkeypatch.setattr("aether.ssa.shadow.canonical_ssa", forbidden)
    monkeypatch.setattr("aether.ssa.shadow.ssa_module_to_dto", forbidden)
    client = StaticClient()
    pipeline = SSAPipeline(rust_shadow_client=client)

    result = pipeline.run(IRModule())
    trace = pipeline.last_authority_report

    assert result.ssa_module.functions == []
    assert pipeline.last_returned_ssa_origin == "rust_schema_v2_import"
    assert trace is not None
    assert trace.mode == "rust_ssa_authority_refinement_verified"
    assert trace.completed_stages == SHADOW_INDEPENDENT_STAGE_MANIFEST
    assert set(trace.stage_execution_counts.values()) == {1}
    assert trace.refinement_verification_executed is True
    assert trace.final_generic_verification_executed is True
    assert trace.python_general_ssa_builder_instantiated is False
    assert trace.python_ssa_lowering_executed is False
    assert trace.canonical_rust_python_comparison_executed is False
    assert client.request_count == 1


def test_default_returns_the_exact_imported_verified_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ssa.shadow_independent as production

    imported: list[object] = []
    original = production.ssa_module_from_dto

    def capture(dto):
        value = original(dto)
        imported.append(value)
        return value

    monkeypatch.setattr(production, "ssa_module_from_dto", capture)
    pipeline = SSAPipeline(rust_shadow_client=StaticClient())
    result = pipeline.run(IRModule())

    assert len(imported) == 1
    assert result.ssa_module is imported[0]
    assert pipeline.last_returned_ssa_origin == "rust_schema_v2_import"


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("companion failed"),
        [],
        {"ok": False, "error": "Rust verifier rejected"},
        {"ok": True, "ssa": {}},
    ],
)
def test_new_default_fails_closed_without_python_fallback(
    monkeypatch: pytest.MonkeyPatch, response: object
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("automatic Python fallback executed")

    monkeypatch.setattr(GeneralSSABuilder, "__init__", forbidden)
    monkeypatch.setattr(GeneralSSABuilder, "build", forbidden)
    with pytest.raises(ShadowIndependentRustAuthorityFailure):
        SSAPipeline(rust_shadow_client=StaticClient(response)).run(IRModule())


def test_new_default_refinement_failure_is_mandatory_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*_args, **_kwargs):
        raise RuntimeError("injected refinement rejection")

    monkeypatch.setattr(
        "aether.ssa.shadow_independent.verify_ssa_refinement", reject
    )
    with pytest.raises(ShadowIndependentRustAuthorityFailure) as caught:
        SSAPipeline(rust_shadow_client=StaticClient()).run(IRModule())
    assert caught.value.trace.failure_classification == "refinement_verifier_failure"
    assert caught.value.trace.final_generic_verification_executed is False
    assert caught.value.trace.python_ssa_lowering_executed is False


def test_differential_mode_executes_python_and_canonical_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"builder": 0, "canonical": 0}
    original_build = GeneralSSABuilder.build
    import aether.ssa.shadow as shadow

    original_canonical = shadow.canonical_ssa

    def build(builder, module):
        calls["builder"] += 1
        return original_build(builder, module)

    def canonical(dto):
        calls["canonical"] += 1
        return original_canonical(dto)

    monkeypatch.setattr(GeneralSSABuilder, "build", build)
    monkeypatch.setattr(shadow, "canonical_ssa", canonical)
    pipeline = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
        ),
        rust_shadow_client=StaticClient(),
    )
    pipeline.run(IRModule())
    assert calls == {"builder": 1, "canonical": 1}
    assert pipeline.last_authority_report.classification == "match"


def test_differential_canonical_mismatch_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ssa.shadow as shadow

    original = shadow._canonicalize_owned_ssa

    def mismatch(dto):
        value = original(dto)
        value["structs"].append({"name": "Injected", "fields": []})
        return value

    monkeypatch.setattr(shadow, "_canonicalize_owned_ssa", mismatch)
    with pytest.raises(SSAShadowFailure) as caught:
        lower_with_rust_authority(IRModule(), StaticClient())
    assert caught.value.report.classification == "semantic_mismatch"
    assert caught.value.report.phase == "canonical_comparison"


@pytest.mark.parametrize(
    "mode",
    [
        SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW,
        SSALoweringAuthorityMode.PYTHON_SSA_ONLY,
    ],
)
def test_explicit_python_rollback_modes_remain_available(
    mode: SSALoweringAuthorityMode,
) -> None:
    pipeline = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(mode),
        rust_shadow_client=(
            StaticClient() if mode is not SSALoweringAuthorityMode.PYTHON_SSA_ONLY else None
        ),
    )
    pipeline.run(IRModule())
    assert pipeline.last_returned_ssa_origin == "python_general_ssa_builder"


def test_permanent_evidence_recomputes_without_inventing_platforms() -> None:
    record = _checker_module().build_record(EVIDENCE, REPORT)
    assert record["passed"] is True, record["checks"]
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert record["decision"] == evidence["decision"]
    assert evidence["cross_platform_qualification_complete"] is False
    assert evidence["decision"] == (
        "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_PENDING_CI"
        if evidence["local_qualification_complete"]
        else "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_BLOCKED"
    )
    assert len(evidence["platform_results"]) == 1
    platform = evidence["platform_results"][0]
    assert platform["evidence"].endswith("linux-x86_64.json")
    assert platform["platform"] == "linux-x86_64"
    assert platform["status"] == "PASS"
    record = platform.get("record", evidence["clean_install"]["record"])
    assert record["shadow"] == "not_executed_by_default"
