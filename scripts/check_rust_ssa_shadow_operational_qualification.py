#!/usr/bin/env python3
"""Aggregate executed RUST-3.4 platform and semantic evidence."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

PLATFORMS = {"linux-x86_64": "x86_64-unknown-linux-gnu", "windows-x86_64": "x86_64-pc-windows-msvc",
             "macos-arm64": "aarch64-apple-darwin", "macos-x86_64": "x86_64-apple-darwin"}
CHECKS = ("build", "package", "checksum", "identity", "clean_install", "discovery", "path_isolation",
          "persistent_start", "multiple_requests", "representative_comparison", "clean_shutdown")


def flatten(imported: Path, evidence: Path) -> None:
    expected = {f"ssa-shadow-qualification-{platform}": platform for platform in PLATFORMS}
    actual = {path.name: path for path in imported.iterdir() if path.is_dir()}
    if set(actual) != set(expected):
        raise ValueError("downloaded artifacts do not exactly match the official platform matrix")
    evidence.mkdir(parents=True, exist_ok=False)
    for directory_name, platform in expected.items():
        directory = actual[directory_name]
        report = directory / f"{platform}.json"
        value = json.loads(report.read_text(encoding="utf-8"))
        archive = directory / value["artifact"]
        sidecar = archive.with_name(archive.name + ".sha256")
        for source in (report, archive, sidecar):
            destination = evidence / source.name
            if destination.exists(): raise ValueError(f"duplicate evidence: {source.name}")
            shutil.copyfile(source, destination)


def validate(directory: Path, platform: str) -> dict[str, object]:
    value = json.loads((directory / f"{platform}.json").read_text(encoding="utf-8"))
    expected = {"schema_version": 1, "revision": "RUST-3.4", "platform": platform,
                "rust_target": PLATFORMS[platform], "product": "aether-ssa-shadow", "product_version": "0.1.0",
                "protocol_version": 1, "input_schema_versions": [1], "output_schema_versions": [2],
                "capabilities": ["lower_verified_ssa_shadow"], "execution": "clean_release_artifact", "authority": "python"}
    if any(value.get(key) != wanted for key, wanted in expected.items()): raise ValueError(f"{platform}: incompatible evidence identity")
    if any(value.get("checks", {}).get(name) != "PASS" for name in CHECKS): raise ValueError(f"{platform}: executed checks incomplete")
    comparison = value.get("comparison", {})
    if comparison.get("comparisons", 0) < 2 or comparison.get("semantic_mismatches") != 0 or comparison.get("infrastructure_failures") != 0:
        raise ValueError(f"{platform}: comparison failed")
    archive = directory / value["artifact"]; sidecar = archive.with_name(archive.name + ".sha256")
    digest = sha256(archive.read_bytes()).hexdigest()
    if digest != value.get("sha256") or sidecar.read_text(encoding="ascii").split() != [digest, archive.name]:
        raise ValueError(f"{platform}: checksum mismatch")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flatten-downloaded", type=Path); parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--soak", type=Path); parser.add_argument("--output", type=Path)
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    if args.flatten_downloaded: flatten(args.flatten_downloaded, args.evidence_dir); return 0
    failures = {}; platforms = {}
    for platform in PLATFORMS:
        try: platforms[platform] = validate(args.evidence_dir, platform)
        except (OSError, ValueError, json.JSONDecodeError) as exc: failures[platform] = str(exc)
    soak = json.loads(args.soak.read_text(encoding="utf-8")) if args.soak else {}
    semantic_ok = (soak.get("soak", {}).get("semantic_mismatches") == 0
                   and soak.get("soak", {}).get("infrastructure_failures") == 0
                   and soak.get("soak", {}).get("shadow_compared") == soak.get("soak", {}).get("accepted")
                   and soak.get("long_session", {}).get("requests") == 1000
                   and soak.get("long_session", {}).get("process_startups") == 1
                   and soak.get("concurrency", {}).get("requests") == 128
                   and soak.get("concurrency", {}).get("process_startups") == 1)
    qualified = not failures and semantic_ok
    gates = {f"SO{number}": "PASS" if qualified else "BLOCKED" for number in range(1, 13)}
    record = {"evidence_schema_version": 1, "milestone": "RUST-3.4",
              "decision": "RUST_SSA_SHADOW_OPERATIONALLY_QUALIFIED" if qualified else "RUST_SSA_SHADOW_OPERATIONALLY_BLOCKED",
              "gates": gates, "platforms": platforms, "blockers": failures,
              "soak": soak.get("soak"), "authority": {"production_default": "PYTHON_SSA_ONLY", "returned_ssa": "python",
              "rust_reaches_optimizer_or_backend": False},
              "rollback": {"mode": "PYTHON_SSA_ONLY", "companion_required": False, "status": "PASS" if qualified else "BLOCKED"}}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(record["decision"])
    return 1 if args.require_qualified and not qualified else 0


if __name__ == "__main__": raise SystemExit(main())
