#!/usr/bin/env python3
"""Create a deterministic native aether-ssa-shadow companion archive."""
from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import stat
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ssa.shadow import (  # noqa: E402
    SSA_SHADOW_PRODUCT_VERSION,
    canonical_rust_ssa_shadow_platform_id,
    rust_ssa_shadow_artifact_name,
    rust_ssa_shadow_package_manifest,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _archive(path: Path, members: list[tuple[str, bytes, int]]) -> None:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data, mode in members:
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = mode << 16
                archive.writestr(info, data)
        return
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, data, mode in members:
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime, info.uid, info.gid = len(data), mode, 0, 0, 0
                    archive.addfile(info, io.BytesIO(data))


def package(executable: Path, output_dir: Path, platform_id: str) -> Path:
    executable = executable.resolve()
    if not executable.is_file() or executable.parent.name != "release" or "debug" in executable.parts:
        raise RuntimeError("production packaging requires a target/release binary")
    if not platform_id.startswith("windows-") and not executable.stat().st_mode & stat.S_IXUSR:
        raise RuntimeError("Rust SSA companion is not executable")
    manifest = rust_ssa_shadow_package_manifest(executable, platform_id=platform_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / rust_ssa_shadow_artifact_name(platform_id)
    if artifact.exists():
        raise RuntimeError(f"refusing to overwrite artifact: {artifact}")
    mode = 0o644 if platform_id.startswith("windows-") else 0o755
    _archive(artifact, [(str(manifest["binary"]), executable.read_bytes(), mode),
                        ("manifest.json", _json_bytes(manifest), 0o644),
                        ("LICENSE", (ROOT / "LICENSE").read_bytes(), 0o644)])
    digest = sha256(artifact.read_bytes()).hexdigest()
    artifact.with_name(artifact.name + ".sha256").write_text(
        f"{digest}  {artifact.name}\n", encoding="ascii", newline="\n"
    )
    index = {"schema_version": 1, "product": "aether-ssa-shadow",
             "product_version": SSA_SHADOW_PRODUCT_VERSION, "protocol_version": 1,
             "artifacts": {platform_id: {"artifact": artifact.name, "sha256": digest}}}
    (output_dir / "ssa-shadow-companions.json").write_bytes(_json_bytes(index))
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--platform", choices=("linux", "windows", "macos"), required=True)
    parser.add_argument("--arch", required=True)
    args = parser.parse_args()
    platform_id = canonical_rust_ssa_shadow_platform_id(args.platform, args.arch)
    print(package(args.executable, args.output_dir, platform_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
