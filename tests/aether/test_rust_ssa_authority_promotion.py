from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from aether.errors import AetherRuntimeError
from aether.ir.model import IRModule
from aether.pipeline import SSAPipeline
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailurePolicy,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/qualify_rust_ssa_authority_promotion.py"
ARTIFACT = ROOT / "docs/compiler/rust_ssa_authority_promotion_qualification.json"
OPERATIONAL = ROOT / "docs/compiler/rust_ssa_shadow_operational_qualified.json"


class _ExplodingClient:
    process_start_count = 0
    request_count = 0

    def lower(self, _payload: bytes):
        self.request_count += 1
        raise AssertionError("reserved Rust-authority mode must not call the companion")


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


def test_final_promotion_artifact_is_deterministic_and_current() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "READY_FOR_RUST_SSA_AUTHORITY_SWITCH"


def test_final_decision_requires_exactly_twenty_passing_gates() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert report["decision"] == "READY_FOR_RUST_SSA_AUTHORITY_SWITCH"
    assert [gate["id"] for gate in report["gates"]] == [
        f"G{number:02d}" for number in range(1, 21)
    ]
    assert {gate["status"] for gate in report["gates"]} == {"PASS"}
    assert report["unresolved_blockers"] == {"operational": [], "semantic": []}


def test_future_mode_is_named_but_cannot_be_activated_in_rust_3_5() -> None:
    assert {mode.name for mode in SSALoweringAuthorityMode} == {
        "PYTHON_SSA_ONLY",
        "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
    }
    client = _ExplodingClient()
    configuration = SSALoweringAuthorityConfiguration(
        SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
    )
    with pytest.raises(AetherRuntimeError, match="not activated"):
        SSAPipeline(
            authority_configuration=configuration,
            rust_shadow_client=client,
        ).run(IRModule())
    assert client.request_count == 0
    with pytest.raises(ValueError, match="requires fail-closed"):
        SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW,
            failure_policy=SSAShadowFailurePolicy.OBSERVE,
        )


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


def test_final_scope_keeps_python_authority_and_rust_out_of_consumers() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert report["future_authority_configuration"]["production_default"] == "PYTHON_SSA_ONLY"
    assert report["future_authority_configuration"]["rust_authority_activated"] is False
    assert report["scope"]["production_authority"] == "python"
    assert report["scope"]["production_authority_changed"] is False
    assert report["scope"]["rust_ssa_reaches_optimizer_or_backend"] is False
    assert report["fail_closed_policy"]["silent_python_fallback"] is False
