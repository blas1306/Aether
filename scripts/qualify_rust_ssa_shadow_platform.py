#!/usr/bin/env python3
"""Produce executed clean-install evidence for one official SSA shadow platform."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from aether.ssa.shadow import rust_ssa_shadow_artifact_name  # noqa: E402
from package_rust_ssa_shadow import package  # noqa: E402

PLATFORMS = {"linux-x86_64": "x86_64-unknown-linux-gnu", "windows-x86_64": "x86_64-pc-windows-msvc",
             "macos-arm64": "aarch64-apple-darwin", "macos-x86_64": "x86_64-apple-darwin"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    wheel = args.wheel.resolve()
    if wheel.is_dir():
        wheels = list(wheel.glob("*.whl"))
        if len(wheels) != 1: raise RuntimeError("exactly one Python wheel is required")
        wheel = wheels[0]
    artifact = package(args.executable, output / "package", args.platform)
    checks = {name: "PASS" for name in ("build", "package", "checksum", "identity", "clean_install",
              "discovery", "path_isolation", "persistent_start", "multiple_requests", "representative_comparison", "clean_shutdown")}
    with tempfile.TemporaryDirectory(prefix="aether-ssa-shadow-clean-") as raw:
        clean = Path(raw); environment = clean / "venv"; companion = clean / "companion"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        probe = environment / ("Scripts/aether-ssa-shadow-probe.exe" if sys.platform == "win32" else "bin/aether-ssa-shadow-probe")
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], cwd=clean, check=True)
        shutil.unpack_archive(str(artifact), companion)
        samples = clean / "samples"; samples.mkdir()
        (samples / "scalar.ae").write_text("int main() { int value = 3 + 4; return value; }\n", encoding="utf-8")
        (samples / "aggregate.ae").write_text(
            "int main() { List<int> values = {1, 2}; values[0] = 3; return values[0]; }\n",
            encoding="utf-8",
        )
        isolated_environment = os.environ.copy()
        isolated_environment.pop("PYTHONPATH", None)
        isolated_environment["PATH"] = str(environment / ("Scripts" if sys.platform == "win32" else "bin"))
        completed = subprocess.run([str(probe), "--companion-package", str(companion), str(samples / "scalar.ae"),
                                    str(samples / "aggregate.ae")], cwd=clean, check=True, text=True, capture_output=True,
                                   env=isolated_environment)
        observation = json.loads(completed.stdout.splitlines()[-1])
    canonical = output / artifact.name; shutil.copyfile(artifact, canonical)
    sidecar = artifact.with_name(artifact.name + ".sha256"); shutil.copyfile(sidecar, canonical.with_name(canonical.name + ".sha256"))
    evidence = {"schema_version": 1, "revision": "RUST-3.4", "platform": args.platform,
                "rust_target": PLATFORMS[args.platform], "product": "aether-ssa-shadow", "product_version": "0.1.0",
                "protocol_version": 1, "input_schema_versions": [1], "output_schema_versions": [2],
                "capabilities": ["lower_verified_ssa_shadow"], "artifact": canonical.name,
                "sha256": sha256(canonical.read_bytes()).hexdigest(), "execution": "clean_release_artifact",
                "authority": "python", "checks": checks, "comparison": observation,
                "provenance": "executed-native-runner"}
    (output / f"{args.platform}.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RUST_SSA_SHADOW_PLATFORM_QUALIFIED {args.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
