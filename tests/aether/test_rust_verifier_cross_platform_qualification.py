from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from aether.ir import VerifierAuthorityConfiguration, VerifierAuthorityMode
from aether.ir.rust_verifier import RUST_VERIFIER_PACKAGE_VERSION, rust_verifier_artifact_name
from scripts.check_rust_verifier_cross_platform_qualification import (
    PLATFORMS, REQUIRED_CHECKS, build_record, contract_digest,
    flatten_downloaded_evidence, validate_evidence,
)


def evidence(platform: str) -> dict[str, object]:
    return {
        "schema_version": 1, "revision": "RUST-1.2.2", "platform": platform,
        "rust_target": PLATFORMS[platform], "product": "aether-ir-verifier",
        "product_version": RUST_VERIFIER_PACKAGE_VERSION, "protocol_version": 1,
        "ir_schema_versions": [1], "capabilities": ["verify"],
        "contract_sha256": contract_digest(), "execution": "release_artifact",
        "provenance": "CI execution", "authority": "python", "migration_phase": "RP2",
        "artifact": rust_verifier_artifact_name(platform), "sha256": "a" * 64,
        "checks": {name: "PASS" for name in REQUIRED_CHECKS},
        "canary": {"comparisons": 5, "semantic_mismatches": 0, "unexpected": 0, "operational_failures": 0},
    }


def write_all(path: Path) -> None:
    for platform in PLATFORMS:
        item = evidence(platform)
        artifact = path / str(item["artifact"])
        artifact.write_bytes(platform.encode())
        item["sha256"] = sha256(artifact.read_bytes()).hexdigest()
        artifact.with_name(artifact.name + ".sha256").write_text(f"{item['sha256']}  {artifact.name}\n")
        (path / f"{platform}.json").write_text(json.dumps(item))


def write_downloaded_artifacts(path: Path) -> None:
    for platform in PLATFORMS:
        qualification = path / f"verifier-qualification-{platform}"
        qualification.mkdir(parents=True)
        write_all_platform = evidence(platform)
        archive = qualification / str(write_all_platform["artifact"])
        archive.write_bytes(platform.encode())
        write_all_platform["sha256"] = sha256(archive.read_bytes()).hexdigest()
        sidecar = archive.with_name(archive.name + ".sha256")
        sidecar.write_text(f"{write_all_platform['sha256']}  {archive.name}\n")
        (qualification / f"{platform}.json").write_text(json.dumps(write_all_platform))
        package = qualification / "package"
        package.mkdir()
        (package / archive.name).write_bytes(archive.read_bytes())
        (package / sidecar.name).write_bytes(sidecar.read_bytes())


def test_matrix_and_targets_are_frozen() -> None:
    assert PLATFORMS == {
        "linux-x86_64": "x86_64-unknown-linux-gnu",
        "windows-x86_64": "x86_64-pc-windows-msvc",
        "macos-arm64": "aarch64-apple-darwin",
        "macos-x86_64": "x86_64-apple-darwin",
    }


def test_missing_evidence_blocks_without_changing_authority(tmp_path: Path) -> None:
    record = build_record(tmp_path)
    assert record["final_decision"] == "CROSS_PLATFORM_COMPANION_BLOCKED"
    assert record["current_authority"] == "python" and record["current_migration_phase"] == "RP2"
    assert VerifierAuthorityConfiguration(VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW).mode is VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW


def test_complete_executed_evidence_closes_gates(tmp_path: Path) -> None:
    write_all(tmp_path)
    record = build_record(tmp_path)
    assert record["final_decision"] == "CROSS_PLATFORM_COMPANION_QUALIFIED"
    assert record["operational_gates"] == {"OP1": "PASS", "OP6": "PASS", "OP10": "PASS"}
    assert len(record["release_index"]["artifacts"]) == 4


@pytest.mark.parametrize(("field", "value", "message"), [
    ("contract_sha256", "0" * 64, "contract_sha256"),
    ("product_version", "9.9.9", "product_version"),
    ("protocol_version", 2, "protocol_version"),
    ("artifact", "wrong.zip", "artifact"),
    ("sha256", "bad", "SHA-256"),
    ("execution", "build_only", "execution"),
])
def test_stale_mismatched_or_build_only_evidence_is_rejected(field: str, value: object, message: str) -> None:
    item = evidence("linux-x86_64"); item[field] = value
    with pytest.raises(ValueError, match=message):
        validate_evidence(item, "linux-x86_64")


def test_failed_clean_install_or_canary_is_rejected() -> None:
    item = evidence("linux-x86_64")
    item["checks"]["clean_install"] = "BLOCKED"
    with pytest.raises(ValueError, match="clean_install"):
        validate_evidence(item, "linux-x86_64")


def test_archive_checksum_mismatch_blocks_aggregate(tmp_path: Path) -> None:
    write_all(tmp_path)
    artifact = tmp_path / rust_verifier_artifact_name("linux-x86_64")
    artifact.write_bytes(b"tampered")
    record = build_record(tmp_path)
    assert record["final_decision"] == "CROSS_PLATFORM_COMPANION_BLOCKED"
    assert "checksum mismatch" in record["blockers"]["linux-x86_64"]
    item = evidence("linux-x86_64"); item["canary"]["semantic_mismatches"] = 1
    with pytest.raises(ValueError, match="canary"):
        validate_evidence(item, "linux-x86_64")


def test_flatten_downloaded_root_and_package_copies_uses_qualification_root(tmp_path: Path) -> None:
    imported = tmp_path / "imported"
    imported.mkdir()
    write_downloaded_artifacts(imported)
    flattened = tmp_path / "evidence"
    flatten_downloaded_evidence(imported, flattened)
    assert build_record(flattened)["final_decision"] == "CROSS_PLATFORM_COMPANION_QUALIFIED"
    assert len(list(flattened.iterdir())) == len(PLATFORMS) * 3


def test_flatten_rejects_mismatched_package_duplicate(tmp_path: Path) -> None:
    imported = tmp_path / "imported"
    imported.mkdir()
    write_downloaded_artifacts(imported)
    platform = "linux-x86_64"
    archive = rust_verifier_artifact_name(platform)
    (imported / f"verifier-qualification-{platform}" / "package" / archive).write_bytes(b"different")
    with pytest.raises(ValueError, match="differs from canonical"):
        flatten_downloaded_evidence(imported, tmp_path / "evidence")


def test_flatten_rejects_missing_sidecar_and_wrong_platform_archive(tmp_path: Path) -> None:
    imported = tmp_path / "imported"
    imported.mkdir()
    write_downloaded_artifacts(imported)
    platform = "linux-x86_64"
    qualification = imported / f"verifier-qualification-{platform}"
    (qualification / (rust_verifier_artifact_name(platform) + ".sha256")).unlink()
    with pytest.raises(ValueError, match="canonical qualification file missing"):
        flatten_downloaded_evidence(imported, tmp_path / "missing-sidecar")

    write_downloaded_artifacts(tmp_path / "second-imported")
    second = tmp_path / "second-imported" / f"verifier-qualification-{platform}"
    (second / rust_verifier_artifact_name("windows-x86_64")).write_bytes(b"wrong")
    with pytest.raises(ValueError, match="wrong-platform"):
        flatten_downloaded_evidence(tmp_path / "second-imported", tmp_path / "wrong-platform")


def test_workflow_contains_every_official_platform() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/rust-verifier-cross-platform.yml").read_text()
    for platform in PLATFORMS:
        assert f"platform: {platform}" in workflow
    assert "continue-on-error" not in workflow
