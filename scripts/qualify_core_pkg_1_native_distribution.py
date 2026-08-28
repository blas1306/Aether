#!/usr/bin/env python3
"""Qualify one installed platform build of the CORE-PKG-1 wheel pair."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts/core_pkg_1_consumer_probe.py"
FIXTURE = ROOT / "tests/aether/rust_migration/fixtures/aggregate_list_set_temporary.initial_ir.json"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def wheel_record(path: Path) -> dict[str, object]:
    parts = path.name.removesuffix(".whl").rsplit("-", 3)
    if len(parts) != 4:
        raise RuntimeError(f"invalid wheel filename: {path.name}")
    _prefix, python_tag, abi_tag, platform_tag = parts
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    dist_info = metadata_name.split("/", 1)[0].removesuffix(".dist-info")
    distribution, version = dist_info.rsplit("-", 1)
    return {
        "filename": path.name,
        "distribution": distribution.replace("_", "-"),
        "version": version,
        "python_tag": python_tag,
        "abi_tag": abi_tag,
        "platform_tag": platform_tag,
        "sha256": digest(path),
        "size": path.stat().st_size,
        "requires_exact_native_core": "Requires-Dist: aether-compiler-core==1.0.0rc4" in metadata,
        "contains_binding": any(
            name.startswith("aether_compiler_core/_aether_core.")
            for name in names
        ),
        "contains_companion": any("aether_compiler_core/_native/aether-ssa-shadow" in name for name in names),
        "contains_native_manifest": "aether_compiler_core/_native/native-core-manifest.json" in names,
    }


def commands(environment: Path) -> tuple[Path, Path]:
    directory = environment / ("Scripts" if os.name == "nt" else "bin")
    return directory / ("python.exe" if os.name == "nt" else "python"), directory


def run(arguments: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(arguments, cwd=cwd, env=env, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def qualify(
    native_wheel: Path,
    language_wheel: Path,
    output: Path,
    *,
    platform_id: str,
    matrix_role: str,
    python_minor: str,
    dependency_site_packages: Path | None = None,
) -> dict[str, object]:
    native = wheel_record(native_wheel)
    language = wheel_record(language_wheel)
    with tempfile.TemporaryDirectory(prefix="aether-core-pkg-1-consumer-") as raw:
        temporary = Path(raw)
        environment = temporary / "venv"
        work = temporary / "work"
        work.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        python, scripts = commands(environment)
        consumer_env = os.environ.copy()
        consumer_env.pop("PYTHONPATH", None)
        consumer_env["PYTHONNOUSERSITE"] = "1"
        # Every consumer command uses an absolute interpreter/executable path.
        # Keeping only the venv scripts directory proves installation and use
        # do not discover Cargo/rustc through the host PATH.
        consumer_env["PATH"] = str(scripts)
        if dependency_site_packages is not None:
            purelib = run(
                [str(python), "-c", "import sysconfig;print(sysconfig.get_path('purelib'))"],
                cwd=work,
                env=consumer_env,
            ).stdout.strip()
            (Path(purelib) / "qualification-dependencies.pth").write_text(
                str(dependency_site_packages.resolve()) + "\n",
                encoding="utf-8",
            )
            install_options = ["--no-index", "--no-deps"]
            install_targets = [str(native_wheel.resolve()), str(language_wheel.resolve())]
        else:
            install_options = ["--find-links", str(native_wheel.resolve().parent)]
            install_targets = [str(language_wheel.resolve())]
        run(
            [
                str(python), "-m", "pip", "install", "--disable-pip-version-check",
                "--force-reinstall", *install_options, *install_targets,
            ],
            cwd=work,
            env=consumer_env,
        )
        probe_output = temporary / "probe.json"
        run(
            [
                str(python), str(PROBE), "--fixture", str(FIXTURE),
                "--repository", str(ROOT), "--output", str(probe_output),
            ],
            cwd=work,
            env=consumer_env,
        )
        probe = json.loads(probe_output.read_text(encoding="utf-8"))

    platform_ready = (
        native["distribution"] == "aether-compiler-core"
        and native["version"] == "1.0.0rc4"
        and native["contains_binding"] is True
        and native["contains_companion"] is True
        and native["contains_native_manifest"] is True
        and language["distribution"] == "aether-language"
        and language["requires_exact_native_core"] is True
        and probe["status"] == "PASS"
    )
    result = {
        "artifact_schema_version": 1,
        "kind": "core_pkg_1_platform",
        "milestone": "CORE-PKG-1",
        "decision": (
            "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_PENDING_CI"
            if platform_ready
            else "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED"
        ),
        "platform": platform_id,
        "rust_target": probe["native_metadata"]["target"],
        "matrix_role": matrix_role,
        "python_minor": python_minor,
        "python": sys.version,
        "build_environment": {
            "cargo_available": shutil.which("cargo") is not None,
            "rustc_available": shutil.which("rustc") is not None,
            "build_requires_rust": True,
        },
        "native_wheel": native,
        "language_wheel": language,
        "clean_consumer": probe,
        "dependency_install_mode": (
            "preinstalled_dependency_wheels_via_unprocessed_pth"
            if dependency_site_packages is not None
            else "pip_resolved_from_language_wheel"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["decision"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-wheel", type=Path, required=True)
    parser.add_argument("--language-wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument(
        "--matrix-role",
        choices=("platform", "python_compatibility"),
        required=True,
    )
    parser.add_argument("--python-minor", required=True)
    parser.add_argument(
        "--dependency-site-packages",
        type=Path,
        help="Local-only dependency reuse; CI omits this and resolves the language wheel normally.",
    )
    args = parser.parse_args()
    result = qualify(
        args.native_wheel,
        args.language_wheel,
        args.output,
        platform_id=args.platform,
        matrix_role=args.matrix_role,
        python_minor=args.python_minor,
        dependency_site_packages=args.dependency_site_packages,
    )
    return 0 if result["decision"].endswith("PENDING_CI") else 1


if __name__ == "__main__":
    raise SystemExit(main())
