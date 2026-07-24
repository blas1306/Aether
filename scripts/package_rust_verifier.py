#!/usr/bin/env python3
"""Build one versioned, content-addressed Rust verifier package directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.rust_verifier import (  # noqa: E402
    RUST_VERIFIER_PACKAGE_VERSION,
    rust_verifier_package_manifest,
)


def _cargo() -> str:
    discovered = shutil.which("cargo")
    if discovered is not None:
        return discovered
    fallback = Path.home() / ".cargo" / "bin" / "cargo"
    if fallback.is_file():
        return str(fallback)
    raise RuntimeError("cargo was not found")


def package_rust_verifier(
    output_root: Path,
    *,
    profile: str,
    platform_tag: str,
) -> Path:
    """Build and package the exact host artifact, returning its directory."""

    command = [
        _cargo(),
        "build",
        "--locked",
        "--package",
        "aether-ir-verifier",
    ]
    if profile == "release":
        command.append("--release")
    subprocess.run(
        command,
        cwd=ROOT / "compiler-rs",
        check=True,
    )
    executable_name = (
        "aether-ir-verifier.exe"
        if sys.platform == "win32"
        else "aether-ir-verifier"
    )
    source = ROOT / "compiler-rs" / "target" / profile / executable_name
    package_directory = (
        output_root.resolve()
        / RUST_VERIFIER_PACKAGE_VERSION
        / platform_tag
    )
    if package_directory.exists() and any(package_directory.iterdir()):
        raise RuntimeError(
            f"package directory is not empty: {package_directory}"
        )
    package_directory.mkdir(parents=True, exist_ok=True)
    destination = package_directory / executable_name
    shutil.copy2(source, destination)
    manifest = rust_verifier_package_manifest(
        destination,
        platform_tag=platform_tag,
    )
    (package_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return package_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=("debug", "release"),
        default="release",
    )
    parser.add_argument("--platform", default=sysconfig.get_platform())
    args = parser.parse_args(argv)
    package_directory = package_rust_verifier(
        args.output,
        profile=args.profile,
        platform_tag=args.platform,
    )
    print(package_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
