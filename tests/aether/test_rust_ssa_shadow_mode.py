from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from aether.ir.model import IRModule
from aether.pipeline import SSAPipeline
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
    PersistentRustSSALoweringClient,
    discover_packaged_rust_ssa_shadow,
    lower_with_rust_shadow,
)


class StubClient:
    process_start_count = 1

    def __init__(self, response):
        self.response = response
        self.request_count = 0
        self.payloads = []

    def lower(self, payload: bytes):
        self.request_count += 1
        self.payloads.append(payload)
        return self.response


def empty_response():
    return {"ok": True, "ssa": {"schema_version": 2, "representation": "aether_ssa", "functions": [], "structs": []}}


def test_python_only_is_default_and_never_requires_rust() -> None:
    result = SSAPipeline().run(IRModule()).ssa_module
    assert ssa_module_to_dto(result) == empty_response()["ssa"]


def test_shadow_returns_python_authority_and_uses_one_exact_snapshot() -> None:
    module = IRModule()
    client = StubClient(empty_response())
    expected_snapshot = json.dumps(
        __import__("aether.ir.dto", fromlist=["ir_module_to_dto"]).ir_module_to_dto(module),
        sort_keys=True, separators=(",", ":"),
    ).encode()
    result, report = lower_with_rust_shadow(module, client)
    assert report.classification == "match"
    assert client.payloads == [expected_snapshot]
    assert result is not client.response["ssa"]


def test_mismatch_and_infrastructure_fail_closed_with_structured_report() -> None:
    malformed = StubClient({"ok": True, "ssa": {"wrong": True}})
    with pytest.raises(SSAShadowFailure) as caught:
        lower_with_rust_shadow(IRModule(), malformed)
    assert caught.value.report.classification == "malformed_rust_response"
    assert len(str(caught.value)) < 1000

    mismatch = StubClient({"ok": True, "ssa": {
        "schema_version": 2, "representation": "aether_ssa", "functions": [],
        "structs": [{"name": "Unexpected", "fields": []}],
    }})
    with pytest.raises(SSAShadowFailure) as semantic:
        lower_with_rust_shadow(IRModule(), mismatch)
    assert semantic.value.report.classification == "semantic_mismatch"
    assert semantic.value.report.first_difference == "$.structs"


def test_pipeline_shadow_selection_is_explicit() -> None:
    client = StubClient(empty_response())
    configuration = SSALoweringAuthorityConfiguration(
        SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
    )
    result = SSAPipeline(authority_configuration=configuration, rust_shadow_client=client).run(IRModule())
    assert result.ssa_module.functions == []
    assert client.request_count == 1


@pytest.fixture(scope="module")
def rust_ssa_shadow_executable() -> Path:
    root = Path(__file__).resolve().parents[2]
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo is required")
    subprocess.run(
        [cargo, "build", "-p", "aether-verifier", "--bin", "aether-ssa-shadow"],
        cwd=root / "compiler-rs", check=True,
    )
    suffix = ".exe" if sys.platform == "win32" else ""
    return root / "compiler-rs" / "target" / "debug" / f"aether-ssa-shadow{suffix}"


def test_real_companion_long_session_is_persistent_and_isolated(
    rust_ssa_shadow_executable: Path,
) -> None:
    payload_a = json.dumps(
        __import__("aether.ir.dto", fromlist=["ir_module_to_dto"]).ir_module_to_dto(IRModule()),
        sort_keys=True, separators=(",", ":"),
    ).encode()
    # Semantically identical, separately allocated input proves no response state leaks.
    payload_b = bytes(bytearray(payload_a))
    with PersistentRustSSALoweringClient(rust_ssa_shadow_executable) as client:
        responses = [client.lower(payload_a if index % 2 == 0 else payload_b) for index in range(500)]
        assert client.process_start_count == 1
        assert client.request_count == 500
        assert all(response == responses[0] for response in responses)


def test_real_companion_serializes_concurrent_requests(
    rust_ssa_shadow_executable: Path,
) -> None:
    payload = json.dumps(
        __import__("aether.ir.dto", fromlist=["ir_module_to_dto"]).ir_module_to_dto(IRModule()),
        sort_keys=True, separators=(",", ":"),
    ).encode()
    with PersistentRustSSALoweringClient(rust_ssa_shadow_executable) as client:
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(client.lower, [payload] * 64))
        assert client.process_start_count == 1
        assert client.request_count == 64
        assert all(response == responses[0] for response in responses)


def test_packaged_discovery_has_no_path_or_checkout_fallback(
    tmp_path: Path, rust_ssa_shadow_executable: Path,
) -> None:
    import platform
    aliases = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}
    os_name = "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"
    architecture = aliases[platform.machine().lower().replace("-", "_")]
    from aether.ssa.shadow import rust_ssa_shadow_package_manifest
    destination = tmp_path / rust_ssa_shadow_executable.name
    shutil.copy2(rust_ssa_shadow_executable, destination)
    destination.chmod(destination.stat().st_mode | 0o111)
    manifest = rust_ssa_shadow_package_manifest(destination, platform_id=f"{os_name}-{architecture}")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert discover_packaged_rust_ssa_shadow(tmp_path) == destination
    with pytest.raises(FileNotFoundError):
        discover_packaged_rust_ssa_shadow(tmp_path / "missing")
