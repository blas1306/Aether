#!/usr/bin/env python3
"""Build-independent clean-install qualification for one CORE-1.0A wheel."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import compat32
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from zipfile import BadZipFile, ZipFile

from packaging.tags import Tag, parse_tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/aether/rust_migration/fixtures/aggregate_list_set_temporary.initial_ir.json"
PROBE = ROOT / "scripts/core_1_0a_clean_install_probe.py"
EXPECTED_DISTRIBUTION = canonicalize_name("aether-core-qualification")


class WheelSelectionError(ValueError):
    """The binding wheel cannot be selected without guessing."""


def _platform_id() -> str:
    system = platform.system().lower()
    os_name = "macos" if system == "darwin" else "windows" if system == "windows" else "linux"
    machine = platform.machine().lower().replace("-", "_")
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x86_64" if machine in {"amd64", "x86_64"} else machine
    return f"{os_name}-{architecture}"


def _digest(path: Path) -> str:
    block = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            block.update(chunk)
    return block.hexdigest()


def _revision(value: str | None) -> str:
    revision = value or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if len(revision) != 40:
        raise ValueError("an exact revision is required")
    return revision


def _wheel_metadata(path: Path) -> tuple[str, str, frozenset[Tag]]:
    try:
        with ZipFile(path) as archive:
            metadata_members = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            wheel_members = [
                name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")
            ]
            if len(metadata_members) != 1 or len(wheel_members) != 1:
                raise WheelSelectionError(
                    "wheel must contain exactly one dist-info/METADATA and WHEEL"
                )
            metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(metadata_members[0])
            )
            wheel_metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(wheel_members[0])
            )
    except (BadZipFile, OSError) as error:
        raise WheelSelectionError(f"cannot read wheel metadata: {error}") from error
    distribution = metadata.get("Name")
    version = metadata.get("Version")
    raw_tags = wheel_metadata.get_all("Tag", [])
    if not distribution or not version or not raw_tags:
        raise WheelSelectionError("wheel metadata is missing Name, Version, or Tag")
    try:
        tags = frozenset(
            tag for raw_tag in raw_tags for tag in parse_tag(raw_tag.strip())
        )
    except ValueError as error:
        raise WheelSelectionError(f"invalid WHEEL Tag metadata: {error}") from error
    return distribution, version, tags


def _inspect_wheel(path: Path, supported: frozenset[Tag]) -> dict[str, object]:
    result: dict[str, object] = {
        "filename": path.name,
        "compatible": False,
        "eligible": False,
    }
    try:
        filename_distribution, filename_version, _build, filename_tags = (
            parse_wheel_filename(path.name)
        )
        metadata_distribution, metadata_version, metadata_tags = _wheel_metadata(path)
        normalized_filename_distribution = canonicalize_name(filename_distribution)
        normalized_metadata_distribution = canonicalize_name(metadata_distribution)
        tags = sorted(str(tag) for tag in filename_tags)
        matching_tags = sorted(str(tag) for tag in filename_tags & supported)
        result.update(
            {
                "filename_distribution": normalized_filename_distribution,
                "metadata_distribution": normalized_metadata_distribution,
                "metadata_version": metadata_version,
                "tags": tags,
                "python_tags": sorted({tag.interpreter for tag in filename_tags}),
                "abi_tags": sorted({tag.abi for tag in filename_tags}),
                "platform_tags": sorted({tag.platform for tag in filename_tags}),
                "matching_interpreter_tags": matching_tags,
            }
        )
        if normalized_filename_distribution != EXPECTED_DISTRIBUTION:
            result["reason"] = "filename distribution is not the qualification binding"
        elif normalized_metadata_distribution != EXPECTED_DISTRIBUTION:
            result["reason"] = "METADATA Name is not the qualification binding"
        elif str(filename_version) != metadata_version:
            result["reason"] = "filename and METADATA versions differ"
        elif filename_tags != metadata_tags:
            result["reason"] = "filename and WHEEL metadata tags differ"
        elif not matching_tags:
            result["reason"] = "wheel tags are incompatible with the current interpreter"
        else:
            result["compatible"] = True
            result["eligible"] = True
            result["reason"] = (
                "expected distribution in filename and METADATA with internally "
                "consistent tags compatible with the current interpreter"
            )
    except (WheelSelectionError, ValueError) as error:
        result["reason"] = str(error)
    return result


def _select_wheel(
    candidates: list[Path],
) -> tuple[Path, dict[str, object], list[dict[str, object]]]:
    supported = frozenset(sys_tags())
    inspections = [_inspect_wheel(path, supported) for path in candidates]
    eligible = [
        (path, inspection)
        for path, inspection in zip(candidates, inspections, strict=True)
        if inspection["eligible"] is True
    ]
    if len(eligible) != 1:
        summary = (
            "; ".join(
                f"{item['filename']}: tags={item.get('tags', [])}, "
                f"reason={item['reason']}"
                for item in inspections
            )
            or "directory contains no wheel files"
        )
        if not eligible:
            raise WheelSelectionError(
                f"no compatible {EXPECTED_DISTRIBUTION} wheel: {summary}"
            )
        raise WheelSelectionError(
            f"ambiguous compatible {EXPECTED_DISTRIBUTION} wheels ({len(eligible)}): "
            f"{summary}"
        )
    wheel, selected = eligible[0]
    return wheel.resolve(), selected, inspections


def _install_environment(
    base: dict[str, str], scripts: Path
) -> tuple[dict[str, str], dict[str, Path]]:
    """Keep the consumer PATH intact while making Rust tools unusable."""
    blockers: dict[str, Path] = {}
    for tool in ("cargo", "rustc"):
        if os.name == "nt":
            blocker = scripts / f"{tool}.cmd"
            blocker.write_text(
                "@echo Rust toolchain disabled in consumer environment 1>&2\n"
                "@exit /b 127\n"
            )
        else:
            blocker = scripts / tool
            blocker.write_text(
                "#!/bin/sh\n"
                "echo 'Rust toolchain disabled in consumer environment' >&2\n"
                "exit 127\n"
            )
            blocker.chmod(0o755)
        blockers[tool] = blocker
    environment = dict(base)
    original_path = environment.get("PATH", os.defpath)
    environment["PATH"] = os.pathsep.join((str(scripts), original_path))
    environment["CARGO"] = str(blockers["cargo"])
    environment["RUSTC"] = str(blockers["rustc"])
    return environment, blockers


def _resolves_to(path: str | None, expected: Path) -> bool:
    if path is None:
        return False
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(
        os.path.abspath(expected)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    wheel_group = parser.add_mutually_exclusive_group(required=True)
    wheel_group.add_argument("--wheel", type=Path)
    wheel_group.add_argument("--wheel-dir", type=Path)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--matrix-role", choices=("platform", "python_compatibility"), default="platform")
    parser.add_argument("--revision")
    parser.add_argument("--ci-run-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if platform.python_implementation() != "CPython":
        parser.error("CORE-1.0A packaging qualification requires CPython")
    candidates = (
        sorted(args.wheel_dir.glob("*.whl"), key=lambda path: path.name)
        if args.wheel_dir is not None
        else [args.wheel]
    )
    assert all(candidate is not None for candidate in candidates)
    print(f"CORE-1.0A build interpreter: {sys.version!r}")
    try:
        wheel, wheel_selection, wheel_candidates = _select_wheel(
            [candidate for candidate in candidates if candidate is not None]
        )
    except WheelSelectionError as error:
        parser.error(str(error))
    print("CORE-1.0A wheel candidates:")
    for candidate in wheel_candidates:
        print(
            f"- {candidate['filename']}: tags={candidate.get('tags', [])}; "
            f"reason={candidate['reason']}"
        )
    print(
        f"CORE-1.0A selected wheel: {wheel.name}; "
        f"tags={wheel_selection['tags']}; reason={wheel_selection['reason']}"
    )
    companion = args.companion.resolve()
    if not wheel.is_file() or not companion.is_file():
        parser.error("wheel and companion must exist")
    actual_platform = _platform_id()
    if args.platform != actual_platform:
        parser.error(f"declared platform {args.platform} != runner {actual_platform}")

    rust_vv = subprocess.run(["rustc", "-vV"], check=True, capture_output=True, text=True).stdout
    rust_target = next(line.removeprefix("host: ") for line in rust_vv.splitlines() if line.startswith("host: "))
    build_environment = {
        "python_executable": sys.executable,
        "python_sys_version": sys.version,
        "cargo_available": shutil.which("cargo") is not None,
        "rustc_available": shutil.which("rustc") is not None,
        "rust_target": rust_target,
        "wheel_prebuilt": True,
    }
    worktree_clean = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == ""
    with tempfile.TemporaryDirectory(prefix="aether-core-1-0a-") as temporary:
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        for name in tuple(environment):
            if name.startswith("AETHER_"):
                environment.pop(name)
        venv = Path(temporary) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, env=environment)
        scripts = venv / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        environment, blockers = _install_environment(environment, scripts)
        cargo_resolution = shutil.which("cargo", path=environment["PATH"])
        rustc_resolution = shutil.which("rustc", path=environment["PATH"])
        cargo_on_install_path = not _resolves_to(cargo_resolution, blockers["cargo"])
        rustc_on_install_path = not _resolves_to(rustc_resolution, blockers["rustc"])
        install = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--only-binary=:all:",
                str(wheel),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        probe_path = Path(temporary) / "probe.json"
        probe_run = subprocess.run(
            [str(python), str(PROBE), "--companion", str(companion), "--fixture", str(FIXTURE), "--output", str(probe_path)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        ) if install.returncode == 0 else None
        probe = json.loads(probe_path.read_text()) if probe_path.is_file() else {"status": "NOT_RUN"}

    wheel_tags = wheel_selection["tags"]
    consumer_environment = {
        "pip_no_index": True,
        "pip_no_deps": True,
        "pip_only_binary": True,
        "cargo_on_install_path": cargo_on_install_path,
        "rustc_on_install_path": rustc_on_install_path,
        "rust_tool_blockers": True,
        "original_path_preserved": True,
        "install_requires_rust": False,
        "install_returncode": install.returncode,
        "install_output_tail": (install.stdout + install.stderr)[-2000:],
    }
    status = (
        install.returncode == 0
        and not cargo_on_install_path
        and not rustc_on_install_path
        and probe_run is not None
        and probe_run.returncode == 0
        and probe.get("status") == "PASS"
    )
    report = {
        "artifact_schema_version": 1,
        "kind": "core_1_0a_packaging",
        "milestone": "CORE-1.0A",
        "status": "PASS" if status else "FAIL",
        "exact_revision": _revision(args.revision),
        "ci_run_id": args.ci_run_id or os.environ.get("GITHUB_RUN_ID") or "LOCAL_PRE_CI",
        "matrix_role": args.matrix_role,
        "platform": args.platform,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "sys_version": sys.version,
        },
        "rust_target": rust_target,
        "build_environment": build_environment,
        "worktree_clean": worktree_clean,
        "wheel": {
            "filename": wheel.name,
            "distribution": wheel_selection["metadata_distribution"],
            "tag": ",".join(wheel_tags),
            "tags": wheel_tags,
            "python_tags": wheel_selection["python_tags"],
            "abi_tags": wheel_selection["abi_tags"],
            "platform_tags": wheel_selection["platform_tags"],
            "selected_reason": wheel_selection["reason"],
            "sha256": _digest(wheel),
        },
        "wheel_candidates": wheel_candidates,
        "companion": {"filename": companion.name, "sha256": _digest(companion)},
        # clean_environment remains as the artifact-schema-v1 compatibility key.
        "clean_environment": consumer_environment,
        "consumer_environment": consumer_environment,
        "probe": probe,
        "probe_returncode": probe_run.returncode if probe_run is not None else None,
        "probe_output_tail": ((probe_run.stdout + probe_run.stderr)[-2000:] if probe_run is not None else ""),
        "production_default_changed": False,
        "companion_remains_usable": probe.get("companion_repeated_use") == "PASS",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"CORE-1.0A clean install {args.platform} Python {platform.python_version()}: {report['status']}")
    return 0 if status else 1


if __name__ == "__main__":
    raise SystemExit(main())
