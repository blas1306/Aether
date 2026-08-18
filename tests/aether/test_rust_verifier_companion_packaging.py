from __future__ import annotations
import json, os, shutil, subprocess, sys, tarfile
from hashlib import sha256
from pathlib import Path
import pytest
from aether.ir import VerifierAuthorityConfiguration, VerifierAuthorityMode
from aether.ir.rust_verifier import (
    RUST_VERIFIER_PACKAGE_VERSION, RustVerifierExecutableNotFound,
    RustVerifierIncompatibleExecutable, canonical_rust_verifier_platform_id,
    discover_packaged_rust_verifier, normalize_rust_verifier_architecture,
    rust_verifier_artifact_name, rust_verifier_package_manifest,
)
from scripts.package_rust_verifier import package_rust_verifier

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/compiler/rust_verifier_companion_packaging.json"

def test_contract_is_deterministic_and_authority_stays_python_rp2() -> None:
    subprocess.run([sys.executable, "scripts/check_rust_verifier_companion_packaging.py", "--check"], cwd=ROOT, check=True)
    data = json.loads(CONTRACT.read_text())
    assert data["final_decision"] == "COMPANION_PACKAGING_FOUNDATION_READY"
    assert data["current_authority"] == "python" and data["current_migration_phase"] == "RP2"
    assert VerifierAuthorityConfiguration(VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW).mode is VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW

@pytest.mark.parametrize(("value", "expected"), [("amd64", "x86_64"), ("x86_64", "x86_64"), ("aarch64", "arm64"), ("arm64", "arm64")])
def test_architecture_normalization(value: str, expected: str) -> None:
    assert normalize_rust_verifier_architecture(value) == expected

def test_platform_and_artifact_names_are_canonical() -> None:
    assert canonical_rust_verifier_platform_id("linux", "amd64") == "linux-x86_64"
    assert rust_verifier_artifact_name("windows-x86_64") == f"aether-ir-verifier-{RUST_VERIFIER_PACKAGE_VERSION}-windows-x86_64.zip"
    with pytest.raises(ValueError, match="unsupported"):
        rust_verifier_artifact_name("plan9-x86_64")

def test_manifest_is_deterministic_and_protocol_compatible(rust_verifier_executable: Path) -> None:
    first = rust_verifier_package_manifest(rust_verifier_executable, platform_tag=canonical_rust_verifier_platform_id())
    second = rust_verifier_package_manifest(rust_verifier_executable, platform_tag=canonical_rust_verifier_platform_id())
    assert first == second
    assert first["product"] == "aether-ir-verifier" and first["product_version"] == RUST_VERIFIER_PACKAGE_VERSION
    assert first["protocol_version"] == 1 and first["supported_ir_schema_versions"] == [1] and first["capabilities"] == ["verify"]

def test_debug_binary_is_rejected(rust_verifier_executable: Path, tmp_path: Path) -> None:
    debug = tmp_path / "debug" / rust_verifier_executable.name; debug.parent.mkdir(); shutil.copy2(rust_verifier_executable, debug)
    with pytest.raises(RuntimeError, match="target/release"):
        package_rust_verifier(debug, tmp_path / "dist", platform_id=canonical_rust_verifier_platform_id())

def test_release_package_roundtrip_checksum_discovery_and_protocol(tmp_path: Path) -> None:
    executable = ROOT / "compiler-rs/target/release" / ("aether-ir-verifier.exe" if sys.platform == "win32" else "aether-ir-verifier")
    if not executable.exists(): pytest.skip("release binary is built by packaging CI")
    artifact = package_rust_verifier(executable, tmp_path / "dist", platform_id=canonical_rust_verifier_platform_id())
    duplicate = package_rust_verifier(executable, tmp_path / "dist-duplicate", platform_id=canonical_rust_verifier_platform_id())
    assert artifact.read_bytes() == duplicate.read_bytes()
    sidecar = artifact.with_name(artifact.name + ".sha256").read_text().split()[0]
    assert sidecar == sha256(artifact.read_bytes()).hexdigest()
    installed = tmp_path / "outside-checkout"; installed.mkdir()
    if artifact.suffix == ".zip": shutil.unpack_archive(artifact, installed)
    else:
        with tarfile.open(artifact, "r:gz") as archive: archive.extractall(installed, filter="data")
    selection = discover_packaged_rust_verifier(installed)
    assert ROOT not in selection.path.parents
    accepted = subprocess.run([selection.path], input=b'{"protocol_version":1,"operation":"verify","module":{"schema_version":1,"functions":[],"structs":[]}}\n', capture_output=True, check=True)
    rejected = subprocess.run([selection.path], input=b'{"protocol_version":2,"operation":"verify","module":{"schema_version":1,"functions":[],"structs":[]}}\n', capture_output=True, check=True)
    assert json.loads(accepted.stdout)["status"] == "accepted"
    assert json.loads(rejected.stdout)["error"]["kind"] == "unsupported_protocol_version"
    manifest = json.loads((installed / "manifest.json").read_text()); manifest["protocol_version"] = 2
    (installed / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(Exception, match="invalid|incompatible"):
        discover_packaged_rust_verifier(installed)

def test_missing_package_is_classified_without_path_or_source_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", os.fspath(ROOT / "compiler-rs/target/release"))
    with pytest.raises(RustVerifierExecutableNotFound, match="manifest"):
        discover_packaged_rust_verifier(tmp_path / "not-installed")
