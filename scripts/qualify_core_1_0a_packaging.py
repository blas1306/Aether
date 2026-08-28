#!/usr/bin/env python3
"""Build-independent clean-install qualification for one CORE-1.0A wheel."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/aether/rust_migration/fixtures/aggregate_list_set_temporary.initial_ir.json"
PROBE = ROOT / "scripts/core_1_0a_clean_install_probe.py"


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
    if args.wheel_dir is not None:
        candidates = sorted(args.wheel_dir.glob("*.whl"))
        if len(candidates) != 1:
            parser.error(f"expected one wheel in {args.wheel_dir}, found {len(candidates)}")
        wheel = candidates[0].resolve()
    else:
        assert args.wheel is not None
        wheel = args.wheel.resolve()
    companion = args.companion.resolve()
    if not wheel.is_file() or not companion.is_file():
        parser.error("wheel and companion must exist")
    actual_platform = _platform_id()
    if args.platform != actual_platform:
        parser.error(f"declared platform {args.platform} != runner {actual_platform}")

    rust_vv = subprocess.run(["rustc", "-vV"], check=True, capture_output=True, text=True).stdout
    rust_target = next(line.removeprefix("host: ") for line in rust_vv.splitlines() if line.startswith("host: "))
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
        # Every invoked executable has an absolute path. Keeping only the venv
        # scripts directory proves that wheel installation/import does not
        # discover Cargo or rustc from the runner toolchain.
        clean_path = str(scripts)
        environment["PATH"] = clean_path
        cargo_on_install_path = shutil.which("cargo", path=clean_path) is not None
        install = subprocess.run(
            [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
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

    parts = wheel.name.removesuffix(".whl").split("-")
    wheel_tag = "-".join(parts[-3:]) if len(parts) >= 5 else "INVALID"
    status = install.returncode == 0 and not cargo_on_install_path and probe_run is not None and probe_run.returncode == 0 and probe.get("status") == "PASS"
    report = {
        "artifact_schema_version": 1,
        "kind": "core_1_0a_packaging",
        "milestone": "CORE-1.0A",
        "status": "PASS" if status else "FAIL",
        "exact_revision": _revision(args.revision),
        "ci_run_id": args.ci_run_id or os.environ.get("GITHUB_RUN_ID") or "LOCAL_PRE_CI",
        "matrix_role": args.matrix_role,
        "platform": args.platform,
        "python": {"implementation": platform.python_implementation(), "version": platform.python_version()},
        "rust_target": rust_target,
        "worktree_clean": worktree_clean,
        "wheel": {"filename": wheel.name, "tag": wheel_tag, "sha256": _digest(wheel)},
        "companion": {"filename": companion.name, "sha256": _digest(companion)},
        "clean_environment": {
            "pip_no_index": True,
            "pip_no_deps": True,
            "cargo_on_install_path": cargo_on_install_path,
            "install_requires_rust": False,
            "install_returncode": install.returncode,
            "install_output_tail": (install.stdout + install.stderr)[-2000:],
        },
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
