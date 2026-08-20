from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

import pytest

from aether.ir import (
    IRBasicBlock,
    IRFunction,
    IRModule,
    RustVerifierAcceptedOutcome,
    RustVerifierClientKind,
    RustVerifierInvocation,
    RustVerifierInvocationMetadata,
    VerifierAuthorityConfiguration,
    VerifierAuthorityEnvironment,
    VerifierAuthorityMode,
    VerifierAuthorityPipeline,
    VerifierSemanticDisagreement,
    VoidType,
    discover_packaged_rust_verifier,
    rust_verifier_package_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "docs/compiler/rust_initial_ir_verifier_rp3_operational_readiness.json"


class _AcceptingClient:
    def verify(self, request: object) -> RustVerifierInvocation:
        return RustVerifierInvocation(
            outcome=RustVerifierAcceptedOutcome(),
            metadata=RustVerifierInvocationMetadata(
                client_kind=RustVerifierClientKind.SUBPROCESS,
                duration_seconds=None,
                protocol_version=1,
                ir_schema_version=1,
            ),
        )


def test_historical_artifact_remains_python_rp2_but_default_is_promoted() -> None:
    record = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert record["current_authority"] == "python"
    assert record["current_migration_phase"] == "RP2"
    assert record["final_decision"] == "RP3_OPERATIONAL_READINESS_BLOCKED"
    configuration = VerifierAuthorityPipeline(client=_AcceptingClient()).configuration
    assert configuration.mode is VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
    assert configuration.environment is VerifierAuthorityEnvironment.DEFAULT


def test_rp3_default_and_rollback_are_configuration_only() -> None:
    production = VerifierAuthorityConfiguration(
        VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
    )
    rp3 = VerifierAuthorityConfiguration(
        VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
        VerifierAuthorityEnvironment.CANARY,
    )
    rollback = VerifierAuthorityConfiguration(
        VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW
    )
    assert rp3.authority.value == "rust"
    assert production.authority.value == "rust"
    assert rollback.authority.value == "python"


def test_rp3_semantic_disagreement_is_fatal_after_report() -> None:
    invalid = IRModule(
        [IRFunction("main", [], VoidType(), [IRBasicBlock("entry", [])])]
    )
    pipeline = VerifierAuthorityPipeline(
        client=_AcceptingClient(),
        configuration=VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
            VerifierAuthorityEnvironment.CANARY,
        ),
    )
    with pytest.raises(VerifierSemanticDisagreement):
        pipeline.verify(invalid)


def test_packaged_companion_clean_resolution(
    rust_verifier_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "installed-companion"
    package.mkdir()
    destination = package / rust_verifier_executable.name
    shutil.copy2(rust_verifier_executable, destination)
    manifest = rust_verifier_package_manifest(
        destination, platform_tag=sysconfig.get_platform()
    )
    (package / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    outside_checkout = tmp_path / "fresh-working-directory"
    outside_checkout.mkdir()
    monkeypatch.chdir(outside_checkout)
    monkeypatch.setenv("PATH", os.defpath)
    selection = discover_packaged_rust_verifier(package)
    assert selection.path.parent == package
    assert "compiler-rs" not in selection.path.parts


def test_readiness_artifact_is_deterministic_and_has_no_unknown_gate() -> None:
    subprocess.run(
        [sys.executable, "scripts/check_rust_verifier_rp3_operational_readiness.py", "--check"],
        cwd=ROOT,
        check=True,
    )
    record = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert {gate["status"] for gate in record["operational_gates"]} <= {
        "PASS",
        "BLOCKED",
        "NOT_APPLICABLE",
    }
    assert record["blockers"] == ["OP1", "OP5", "OP6", "OP10"]
    assert record["release_canary"]["total"] == 404
    assert record["release_canary"]["successful"] is True
