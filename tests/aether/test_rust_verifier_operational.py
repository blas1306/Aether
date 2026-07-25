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
    IRModule,
    CollectingShadowReportSink,
    RustVerifierAcceptedOutcome,
    RustVerifierExecutableIntegrityError,
    RustVerifierExecutableNotFound,
    RustVerifierIncompatibleExecutable,
    RustVerifierInvalidExecutable,
    RustVerifierNotExecutable,
    RustVerifierProcessFailure,
    RustVerifierTimeout,
    VerifierAuthorityConfiguration,
    VerifierAuthorityEnvironment,
    VerifierAuthorityMode,
    VerifierAuthorityPipeline,
    VerifierImplementation,
    build_canonical_rust_verifier_request,
    discover_packaged_rust_verifier,
    discover_rust_verifier_executable,
    rust_verifier_package_manifest,
    select_rust_verifier_executable,
)
from aether.ir.rust_verifier import SubprocessRustVerifierClient


IDENTITY = {
    "identity_schema_version": 1,
    "executable": "aether-ir-verifier",
    "version": "0.0.0",
    "protocol_versions": [1],
    "ir_schema_versions": [1],
    "capabilities": ["verify"],
}
ACCEPTED = {"protocol_version": 1, "status": "accepted"}


def _identity_command(
    identity: dict[str, object],
    *,
    response: dict[str, object] = ACCEPTED,
) -> list[str]:
    identity_bytes = (
        json.dumps(identity, separators=(",", ":")).encode() + b"\n"
    )
    response_bytes = (
        json.dumps(response, separators=(",", ":")).encode() + b"\n"
    )
    return [
        sys.executable,
        "-c",
        "import os, sys\n"
        "sys.stdin.buffer.read()\n"
        f"identity = {identity_bytes!r}\n"
        f"response = {response_bytes!r}\n"
        "os.write(1, identity if '--identity' in sys.argv else response)\n",
    ]


def _write_package(
    package_directory: Path,
    executable: Path,
    *,
    platform_tag: str | None = None,
) -> None:
    package_directory.mkdir()
    destination = package_directory / executable.name
    shutil.copy2(executable, destination)
    manifest = rust_verifier_package_manifest(
        destination,
        platform_tag=platform_tag or sysconfig.get_platform(),
    )
    (package_directory / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_real_executable_identity_is_explicit_and_content_addressed(
    rust_verifier_executable: Path,
) -> None:
    first = select_rust_verifier_executable(rust_verifier_executable)
    second = select_rust_verifier_executable(rust_verifier_executable)

    assert first == second
    assert first.path == rust_verifier_executable.resolve()
    assert len(first.sha256) == 64
    assert first.identity.capabilities == ("verify",)
    assert first.identity.protocol_versions == (1,)
    assert first.identity.ir_schema_versions == (1,)
    assert first.identity.version == "0.0.0"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("identity_schema_version", 2),
        ("executable", "other-verifier"),
        ("version", "9.9.9"),
        ("protocol_versions", [2]),
        ("ir_schema_versions", [2]),
        ("capabilities", ["future"]),
    ],
)
def test_startup_rejects_every_incompatible_identity_field(
    field: str,
    value: object,
) -> None:
    identity = dict(IDENTITY)
    identity[field] = value
    client = SubprocessRustVerifierClient(
        executable=_identity_command(identity)
    )

    with pytest.raises(RustVerifierIncompatibleExecutable) as raised:
        client.verify(build_canonical_rust_verifier_request(IRModule()))

    assert raised.value.field_name == field
    assert str(raised.value).endswith(f"({field})")


def test_compatible_startup_identity_is_cached_per_client() -> None:
    client = SubprocessRustVerifierClient(
        executable=_identity_command(dict(IDENTITY))
    )
    request = build_canonical_rust_verifier_request(IRModule())

    assert client.verify(request).outcome == RustVerifierAcceptedOutcome()
    assert client.verify(request).outcome == RustVerifierAcceptedOutcome()
    assert client.inspect_identity() == client.inspect_identity()


def test_packaged_resolution_ignores_path_and_validates_manifest(
    rust_verifier_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_directory = tmp_path / "package"
    _write_package(package_directory, rust_verifier_executable)
    path_directory = tmp_path / "path"
    path_directory.mkdir()
    accidental = path_directory / "aether-ir-verifier"
    accidental.write_bytes(b"not the verifier")
    accidental.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_directory))

    selection = discover_packaged_rust_verifier(package_directory)

    assert selection.path.parent == package_directory
    assert selection.path != accidental
    with pytest.raises(RustVerifierExecutableNotFound):
        discover_rust_verifier_executable()


def test_corrupted_package_is_rejected_before_execution(
    rust_verifier_executable: Path,
    tmp_path: Path,
) -> None:
    package_directory = tmp_path / "package"
    _write_package(package_directory, rust_verifier_executable)
    packaged_executable = package_directory / rust_verifier_executable.name
    with packaged_executable.open("ab") as stream:
        stream.write(b"corruption")

    with pytest.raises(
        RustVerifierExecutableIntegrityError,
        match="does not match the package manifest",
    ):
        discover_packaged_rust_verifier(package_directory)


def test_missing_not_executable_and_invalid_executable_have_stable_diagnostics(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(RustVerifierExecutableNotFound) as first_missing:
        select_rust_verifier_executable(missing)
    with pytest.raises(RustVerifierExecutableNotFound) as second_missing:
        select_rust_verifier_executable(missing)
    assert str(first_missing.value) == str(second_missing.value)

    not_executable = tmp_path / "not-executable"
    not_executable.write_bytes(b"not executable")
    if os.name != "nt":
        with pytest.raises(
            RustVerifierNotExecutable,
            match="file is not executable",
        ):
            select_rust_verifier_executable(not_executable)

    invalid = tmp_path / "invalid"
    invalid.write_bytes(b"not an executable format")
    invalid.chmod(0o755)
    with pytest.raises(
        RustVerifierInvalidExecutable,
        match="invalid executable format",
    ):
        select_rust_verifier_executable(invalid)


def test_timeout_and_process_crash_diagnostics_are_deterministic() -> None:
    request = build_canonical_rust_verifier_request(IRModule())
    timeout_client = SubprocessRustVerifierClient(
        executable=[
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ],
        timeout_seconds=0.05,
        validate_startup=False,
    )
    with pytest.raises(RustVerifierTimeout) as timeout:
        timeout_client.verify(request)
    assert str(timeout.value) == "Rust verifier exceeded the 0.05 second timeout"

    crash_client = SubprocessRustVerifierClient(
        executable=[sys.executable, "-c", "raise SystemExit(23)"],
        validate_startup=False,
    )
    with pytest.raises(RustVerifierProcessFailure) as crash:
        crash_client.verify(request)
    assert crash.value.returncode == 23
    assert str(crash.value) == "Rust verifier process exited with status 23"


def test_packaging_script_produces_resolvable_versioned_directory(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/package_rust_verifier.py",
            "--output",
            str(tmp_path),
            "--profile",
            "debug",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    package_directory = Path(completed.stdout.strip())

    assert package_directory == (
        tmp_path.resolve() / "0.0.0" / sysconfig.get_platform()
    )
    assert discover_packaged_rust_verifier(package_directory).path.is_file()


def test_authority_rollback_rehearsal_uses_configuration_only(
    rust_verifier_executable: Path,
) -> None:
    client = SubprocessRustVerifierClient(executable=rust_verifier_executable)
    configurations = (
        VerifierAuthorityConfiguration(
            VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW
        ),
        VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
            VerifierAuthorityEnvironment.CANARY,
        ),
        VerifierAuthorityConfiguration(
            VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW
        ),
    )
    observed_roles = []

    for configuration in configurations:
        sink = CollectingShadowReportSink()
        pipeline = VerifierAuthorityPipeline(
            client=client,
            sink=sink,
            configuration=configuration,
        )
        module = IRModule()

        assert pipeline.verify(module) is module
        report = sink.reports[0]
        observed_roles.append(
            (
                report.authority_result.implementation,
                report.shadow_result.implementation,
            )
        )

    assert observed_roles == [
        (VerifierImplementation.PYTHON, VerifierImplementation.RUST),
        (VerifierImplementation.RUST, VerifierImplementation.PYTHON),
        (VerifierImplementation.PYTHON, VerifierImplementation.RUST),
    ]
    assert [configuration.environment for configuration in configurations] == [
        VerifierAuthorityEnvironment.DEFAULT,
        VerifierAuthorityEnvironment.CANARY,
        VerifierAuthorityEnvironment.DEFAULT,
    ]
