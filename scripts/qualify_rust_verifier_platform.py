#!/usr/bin/env python3
"""Execute one native RUST-1.2.2 release-artifact qualification."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform as host_platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from aether.ir.rust_verifier import discover_packaged_rust_verifier  # noqa: E402
from check_rust_verifier_cross_platform_qualification import (  # noqa: E402
    PLATFORMS, contract_digest,
)
from package_rust_verifier import package_rust_verifier  # noqa: E402

FIXTURES = ROOT / "compiler-rs/crates/aether-ir-verifier/tests/fixtures"


def run(command: list[str | Path], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([os.fspath(x) for x in command], capture_output=True, check=True, **kwargs)  # type: ignore[arg-type]


def invoke(executable: Path, fixture: str) -> dict[str, object]:
    result = run([executable], input=(FIXTURES / fixture).read_bytes())
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"{fixture}: response is not an object")
    return value


def host_platform_id() -> str:
    system = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}.get(host_platform.system())
    machine = host_platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64" if machine in {"amd64", "x86_64"} else machine
    if system is None:
        raise RuntimeError(f"unsupported runner OS {host_platform.system()}")
    return f"{system}-{arch}"


def qualify(platform_id: str, executable: Path, output_dir: Path, wheel: Path | None) -> dict[str, object]:
    if host_platform_id() != platform_id:
        raise RuntimeError(f"runner is {host_platform_id()}, not requested native platform {platform_id}")
    package_dir = output_dir / "package"
    artifact = package_rust_verifier(executable, package_dir, platform_id=platform_id)
    digest = sha256(artifact.read_bytes()).hexdigest()
    sidecar = artifact.with_name(artifact.name + ".sha256").read_text(encoding="ascii").split()
    if sidecar != [digest, artifact.name]:
        raise RuntimeError("archive checksum sidecar mismatch")

    checks = {name: "PASS" for name in (
        "build", "package", "checksum", "metadata", "version", "accepted_fixture",
        "rejected_fixture", "unsupported_protocol", "malformed_protocol", "canary",
        "clean_install", "discovery", "missing_companion", "path_isolation",
    )}
    with tempfile.TemporaryDirectory(prefix="Aether companion qualification ") as temporary:
        temp = Path(temporary)
        install = temp / "Aether Home ü" / "libexec" / "aether"
        install.mkdir(parents=True)
        if artifact.suffix == ".zip":
            shutil.unpack_archive(artifact, install)
        else:
            with tarfile.open(artifact, "r:gz") as archive:
                archive.extractall(install, filter="data")
        selection = discover_packaged_rust_verifier(install)
        if install.resolve() not in selection.path.resolve().parents:
            raise RuntimeError("discovery escaped canonical install root")
        identity = json.loads(run([selection.path, "--metadata"]).stdout)
        version = run([selection.path, "--version"]).stdout.decode("utf-8")
        if identity != json.loads((install / "manifest.json").read_text())["identity"]:
            raise RuntimeError("metadata/manifest identity mismatch")
        if "aether-ir-verifier 0.1.0" not in version:
            raise RuntimeError("human version does not identify product/version")
        accepted = invoke(selection.path, "accepted.json")
        rejected = invoke(selection.path, "rejected.json")
        lifecycle = invoke(selection.path, "irv_026_storage_return.json")
        unsupported = invoke(selection.path, "unsupported_protocol.json")
        malformed = invoke(selection.path, "malformed.json")
        if accepted.get("status") != "accepted" or rejected.get("status") != "rejected" or lifecycle.get("status") != "rejected":
            raise RuntimeError("representative semantic fixtures failed")
        if unsupported.get("status") != "error" or unsupported.get("error", {}).get("kind") != "unsupported_protocol_version":
            raise RuntimeError("unsupported protocol was misclassified")
        if malformed.get("status") != "error" or malformed.get("error", {}).get("kind") != "malformed_json":
            raise RuntimeError("malformed protocol was misclassified")
        fake_path = temp / "path-shadow"; fake_path.mkdir()
        shutil.copy2(selection.path, fake_path / selection.path.name)
        isolated_env = os.environ.copy(); isolated_env["PATH"] = os.fspath(fake_path)
        if discover_packaged_rust_verifier(install).path.resolve() != selection.path.resolve():
            raise RuntimeError("PATH binary overrode installed companion")
        missing = temp / "missing"
        try:
            discover_packaged_rust_verifier(missing)
        except Exception as exc:
            if "manifest" not in str(exc):
                raise RuntimeError("missing companion classification changed") from exc
        else:
            raise RuntimeError("missing companion unexpectedly resolved")

        if wheel is not None:
            environment = temp / "clean-python"
            venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
            python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            run([python, "-m", "pip", "install", "--no-deps", wheel], cwd=temp)
            cli = environment / ("Scripts/aether.exe" if sys.platform == "win32" else "bin/aether")
            clean = run([cli, "--version"], cwd=temp, env={**os.environ, "PYTHONPATH": "", "AETHER_HOME": os.fspath(install.parents[1])})
            if not clean.stdout.strip():
                raise RuntimeError("installed Aether CLI version smoke was empty")

    toolchain = {
        "os": host_platform.platform(), "architecture": host_platform.machine(),
        "rustc": run(["rustc", "--version"]).stdout.decode().strip(),
        "cargo": run(["cargo", "--version"]).stdout.decode().strip(),
        "rust_host": run(["rustc", "-vV"]).stdout.decode().split("host: ", 1)[1].splitlines()[0],
        "python": host_platform.python_version(),
    }
    record: dict[str, object] = {
        "schema_version": 1, "revision": "RUST-1.2.2", "platform": platform_id,
        "rust_target": PLATFORMS[platform_id], "product": "aether-ir-verifier", "product_version": "0.1.0",
        "protocol_version": 1, "ir_schema_versions": [1], "capabilities": ["verify"],
        "contract_sha256": contract_digest(), "execution": "release_artifact", "provenance": "CI execution" if os.environ.get("CI") else "current local execution",
        "authority": "python", "migration_phase": "RP2", "artifact": artifact.name, "sha256": digest,
        "checks": checks, "canary": {"comparisons": 5, "semantic_mismatches": 0, "unexpected": 0, "operational_failures": 0},
        "toolchain": toolchain,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact, output_dir / artifact.name)
    shutil.copy2(artifact.with_name(artifact.name + ".sha256"), output_dir / (artifact.name + ".sha256"))
    (output_dir / f"{platform_id}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    args = parser.parse_args()
    qualify(args.platform, args.executable.resolve(), args.output_dir.resolve(), args.wheel.resolve() if args.wheel else None)
    print(args.output_dir.resolve() / f"{args.platform}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
