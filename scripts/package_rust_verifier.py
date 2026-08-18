#!/usr/bin/env python3
"""Create the canonical deterministic native aether-ir-verifier archive."""
from __future__ import annotations
import argparse, gzip, io, json, shutil, stat, subprocess, sys, tarfile, zipfile
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from aether.ir.rust_verifier import (  # noqa: E402
    RUST_VERIFIER_PACKAGE_VERSION, canonical_rust_verifier_platform_id,
    normalize_rust_verifier_architecture, rust_verifier_artifact_name,
    rust_verifier_package_manifest,
)

def _release_binary() -> Path:
    name = "aether-ir-verifier.exe" if sys.platform == "win32" else "aether-ir-verifier"
    return ROOT / "compiler-rs" / "target" / "release" / name

def build_release_binary() -> Path:
    subprocess.run(["cargo", "build", "--manifest-path", str(ROOT / "compiler-rs/Cargo.toml"),
                    "--release", "--locked", "--package", "aether-ir-verifier"], cwd=ROOT / "compiler-rs", check=True)
    return _release_binary()

def _require_release_binary(path: Path, platform_id: str) -> None:
    resolved = path.resolve()
    if not resolved.is_file(): raise RuntimeError(f"verifier release binary does not exist: {path}")
    if "debug" in resolved.parts or resolved.parent.name != "release":
        raise RuntimeError("production packaging requires a target/release binary")
    expected = "aether-ir-verifier.exe" if platform_id.startswith("windows-") else "aether-ir-verifier"
    if resolved.name != expected: raise RuntimeError(f"expected canonical executable name {expected}")
    if not platform_id.startswith("windows-") and not (resolved.stat().st_mode & stat.S_IXUSR):
        raise RuntimeError("verifier release binary is not executable")

def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()

def _archive(path: Path, members: list[tuple[str, bytes, int]]) -> None:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data, mode in members:
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = mode << 16
                archive.writestr(info, data)
        return
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, data, mode in members:
                    info = tarfile.TarInfo(name); info.size, info.mode, info.mtime, info.uid, info.gid = len(data), mode, 0, 0, 0
                    archive.addfile(info, io.BytesIO(data))

def package_rust_verifier(executable: Path, output_dir: Path, *, platform_id: str) -> Path:
    """Validate and archive one already-built release companion."""
    _require_release_binary(executable, platform_id); output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / rust_verifier_artifact_name(platform_id)
    if artifact.exists(): raise RuntimeError(f"refusing to overwrite artifact: {artifact}")
    arch = normalize_rust_verifier_architecture(platform_id.rsplit("-", 1)[1])
    manifest = rust_verifier_package_manifest(executable, platform_tag=platform_id, architecture=arch)
    binary_mode = 0o755 if not platform_id.startswith("windows-") else 0o644
    _archive(artifact, [(str(manifest["binary"]), executable.read_bytes(), binary_mode),
                        ("manifest.json", _json_bytes(manifest), 0o644),
                        ("LICENSE", (ROOT / "LICENSE").read_bytes(), 0o644)])
    digest = sha256(artifact.read_bytes()).hexdigest()
    artifact.with_name(artifact.name + ".sha256").write_text(f"{digest}  {artifact.name}\n", encoding="ascii", newline="\n")
    index = {"schema_version": 1, "product": "aether-ir-verifier", "product_version": RUST_VERIFIER_PACKAGE_VERSION,
             "protocol_version": manifest["protocol_version"], "artifacts": {platform_id: {"artifact": artifact.name, "sha256": digest}}}
    (output_dir / "verifier-companions.json").write_bytes(_json_bytes(index))
    return artifact

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", "--output", dest="output_dir", type=Path, required=True)
    parser.add_argument("--executable", type=Path); parser.add_argument("--platform", choices=("linux", "windows", "macos")); parser.add_argument("--arch")
    args = parser.parse_args(argv); platform_id = canonical_rust_verifier_platform_id(args.platform, args.arch)
    print(package_rust_verifier(args.executable or build_release_binary(), args.output_dir.resolve(), platform_id=platform_id)); return 0

if __name__ == "__main__": raise SystemExit(main())
