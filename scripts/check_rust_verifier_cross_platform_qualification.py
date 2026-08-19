#!/usr/bin/env python3
"""Validate and aggregate RUST-1.2.2 platform qualification evidence.

This checker is intentionally evidence-only: it never infers that a platform
was executed merely because an artifact or a workflow exists.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
with (ROOT / "compiler-rs/Cargo.toml").open("rb") as stream:
    RUST_VERIFIER_PACKAGE_VERSION = tomllib.load(stream)["workspace"]["package"]["version"]

PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}
REQUIRED_CHECKS = (
    "build", "package", "checksum", "metadata", "version", "accepted_fixture",
    "rejected_fixture", "unsupported_protocol", "malformed_protocol", "canary",
    "clean_install", "discovery", "missing_companion", "path_isolation",
)
CONTRACT = ROOT / "docs/compiler/rust_verifier_companion_packaging.json"
OUTPUT_JSON = ROOT / "docs/compiler/rust_verifier_cross_platform_qualification.json"
OUTPUT_MD = ROOT / "docs/compiler/RUST_VERIFIER_CROSS_PLATFORM_QUALIFICATION.md"


def rust_verifier_artifact_name(platform: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError(f"unsupported verifier platform: {platform}")
    extension = ".zip" if platform.startswith("windows-") else ".tar.gz"
    return f"aether-ir-verifier-{RUST_VERIFIER_PACKAGE_VERSION}-{platform}{extension}"


def canonical_contract_bytes(contract: Path = CONTRACT) -> bytes:
    """Return contract bytes with platform-independent LF line endings.

    The packaging contract is UTF-8 JSON text.  Git may materialize that text
    with CRLF on Windows, but checkout policy is not part of the contract's
    identity.  Normalize line endings only; every other byte remains covered
    by the digest.
    """
    return contract.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def contract_digest(contract: Path = CONTRACT) -> str:
    return sha256(canonical_contract_bytes(contract)).hexdigest()


def flatten_downloaded_evidence(imported_dir: Path, evidence_dir: Path) -> None:
    """Flatten canonical qualification-root evidence from downloaded artifacts.

    ``qualify_rust_verifier_platform.py`` creates the archive first in
    ``qualification/package`` and then publishes the qualified archive,
    sidecar, and report at the qualification root.  The latter is the
    qualification artifact contract consumed by aggregation; the package copy
    is retained only as intermediate packaging evidence.
    """
    expected_directories = {
        f"verifier-qualification-{platform}": platform for platform in PLATFORMS
    }
    actual_directories = {path.name: path for path in imported_dir.iterdir() if path.is_dir()}
    if set(actual_directories) != set(expected_directories):
        raise ValueError(
            "downloaded qualification platforms differ from official matrix: "
            f"expected {sorted(expected_directories)}, got {sorted(actual_directories)}"
        )

    selected: list[Path] = []
    for directory_name, platform in expected_directories.items():
        directory = actual_directories[directory_name]
        archive = directory / rust_verifier_artifact_name(platform)
        sidecar = archive.with_name(archive.name + ".sha256")
        report = directory / f"{platform}.json"
        for canonical in (report, archive, sidecar):
            if not canonical.is_file():
                raise ValueError(f"{platform}: canonical qualification file missing: {canonical.name}")

        package_archive = directory / "package" / archive.name
        package_sidecar = package_archive.with_name(package_archive.name + ".sha256")
        if package_archive.exists() or package_sidecar.exists():
            if not package_archive.is_file() or not package_sidecar.is_file():
                raise ValueError(f"{platform}: incomplete noncanonical package copy")
            if package_archive.read_bytes() != archive.read_bytes():
                raise ValueError(f"{platform}: package archive differs from canonical qualification archive")
            if package_sidecar.read_bytes() != sidecar.read_bytes():
                raise ValueError(f"{platform}: package checksum differs from canonical qualification checksum")

        archives = [
            path for path in directory.rglob("*")
            if path.is_file() and (path.name.endswith(".tar.gz") or path.name.endswith(".zip"))
        ]
        allowed_archives = {archive}
        if package_archive.is_file():
            allowed_archives.add(package_archive)
        unexpected = sorted(path.relative_to(directory) for path in archives if path not in allowed_archives)
        if unexpected:
            raise ValueError(f"{platform}: unexpected or wrong-platform archives: {unexpected}")
        selected.extend((report, archive, sidecar))

    if len(selected) != len(PLATFORMS) * 3:
        raise AssertionError("exactly one report, archive, and checksum are required per official platform")
    evidence_dir.mkdir(parents=True, exist_ok=False)
    for source in selected:
        destination = evidence_dir / source.name
        if destination.exists():
            raise ValueError(f"duplicate canonical evidence name: {source.name}")
        shutil.copyfile(source, destination)


def validate_evidence(value: object, platform: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{platform}: evidence must be a JSON object")
    expected = {
        "schema_version": 1, "revision": "RUST-1.2.2", "platform": platform,
        "rust_target": PLATFORMS[platform], "product": "aether-ir-verifier",
        "product_version": RUST_VERIFIER_PACKAGE_VERSION, "protocol_version": 1,
        "ir_schema_versions": [1], "capabilities": ["verify"],
        "contract_sha256": contract_digest(), "execution": "release_artifact",
    }
    for field, wanted in expected.items():
        if value.get(field) != wanted:
            raise ValueError(f"{platform}: {field} is {value.get(field)!r}, expected {wanted!r}")
    if value.get("authority") != "python" or value.get("migration_phase") != "RP2":
        raise ValueError(f"{platform}: authority/phase changed")
    if value.get("artifact") != rust_verifier_artifact_name(platform):
        raise ValueError(f"{platform}: non-canonical artifact name")
    digest = value.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"{platform}: invalid SHA-256")
    checks = value.get("checks")
    if not isinstance(checks, dict):
        raise ValueError(f"{platform}: checks must be an object")
    failed = [name for name in REQUIRED_CHECKS if checks.get(name) != "PASS"]
    if failed:
        raise ValueError(f"{platform}: missing/failed executed checks: {', '.join(failed)}")
    canary = value.get("canary")
    if not isinstance(canary, dict) or any(canary.get(k) != 0 for k in ("semantic_mismatches", "unexpected", "operational_failures")):
        raise ValueError(f"{platform}: canary did not close cleanly")
    if not isinstance(canary.get("comparisons"), int) or canary["comparisons"] < 2:
        raise ValueError(f"{platform}: canary evidence is not representative")
    return value


def load_evidence(evidence_dir: Path) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    valid: dict[str, dict[str, object]] = {}
    errors: dict[str, str] = {}
    for platform in PLATFORMS:
        path = evidence_dir / f"{platform}.json"
        if not path.is_file():
            errors[platform] = "executed evidence missing"
            continue
        try:
            item = validate_evidence(json.loads(path.read_text(encoding="utf-8")), platform)
            artifact = evidence_dir / str(item["artifact"])
            sidecar = artifact.with_name(artifact.name + ".sha256")
            if not artifact.is_file() or not sidecar.is_file():
                raise ValueError(f"{platform}: archive or checksum sidecar missing")
            actual = sha256(artifact.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise ValueError(f"{platform}: checksum mismatch")
            if sidecar.read_text(encoding="ascii").split() != [actual, artifact.name]:
                raise ValueError(f"{platform}: checksum sidecar mismatch")
            valid[platform] = item
        except (ValueError, json.JSONDecodeError) as exc:
            errors[platform] = str(exc)
    return valid, errors


def build_record(evidence_dir: Path) -> dict[str, object]:
    evidence, errors = load_evidence(evidence_dir)
    complete = len(evidence) == len(PLATFORMS)
    platform_records = {
        platform: evidence[platform] if platform in evidence else {"status": "BLOCKED", "reason": errors[platform]}
        for platform in PLATFORMS
    }
    artifacts = {
        platform: {"artifact": item["artifact"], "sha256": item["sha256"]}
        for platform, item in sorted(evidence.items())
    }
    return {
        "schema_version": 1,
        "revision": "RUST-1.2.2",
        "final_decision": "CROSS_PLATFORM_COMPANION_QUALIFIED" if complete else "CROSS_PLATFORM_COMPANION_BLOCKED",
        "current_authority": "python",
        "current_migration_phase": "RP2",
        "platforms": PLATFORMS,
        "product_version": RUST_VERIFIER_PACKAGE_VERSION,
        "build_command": "cargo build --manifest-path compiler-rs/Cargo.toml --release --locked --package aether-ir-verifier",
        "packaging_command": "python scripts/package_rust_verifier.py --executable <release-binary> --platform <os> --arch <arch> --output-dir <dir>",
        "evidence": platform_records,
        "release_index": {"schema_version": 1, "product": "aether-ir-verifier", "product_version": RUST_VERIFIER_PACKAGE_VERSION, "protocol_version": 1, "artifacts": artifacts},
        "operational_gates": {"OP1": "PASS" if complete else "BLOCKED", "OP6": "PASS" if complete else "BLOCKED", "OP10": "PASS" if complete else "BLOCKED"},
        "publication_semantics": "OP10 requires release-artifact clean installation; this workflow does not claim public publication",
        "full_canary_policy": "full 404-case canary on linux-x86_64; representative protocol subset on every official platform",
        "rust_1_3_handoff": "RP3 Final Promotion Qualification: re-run parity, require OP1-OP10 PASS, verify Python/RP2 and rollback, then produce READY_FOR_RP3_AUTHORITY_SWITCH",
        "blockers": errors,
    }


def render_markdown(record: dict[str, object]) -> str:
    rows = []
    evidence = record["evidence"]
    assert isinstance(evidence, dict)
    for platform, target in PLATFORMS.items():
        item = evidence[platform]
        status = "PASS" if isinstance(item, dict) and item.get("execution") == "release_artifact" else "BLOCKED"
        provenance = item.get("provenance", "none") if isinstance(item, dict) else "none"
        rows.append(f"| {platform} | `{target}` | {status} | {provenance} |")
    qualification_summary = (
        "All four current-contract reports are imported and OP1, OP6, and OP10 pass."
        if record["final_decision"] == "CROSS_PLATFORM_COMPANION_QUALIFIED"
        else "OP1, OP6, and OP10 remain blocked until all four current-contract reports are imported."
    )
    next_action = (
        "The checked aggregate is the canonical RUST-1.2.2 evidence consumed by RUST-1.3."
        if record["final_decision"] == "CROSS_PLATFORM_COMPANION_QUALIFIED"
        else "To finish: run the `Rust verifier cross-platform qualification` workflow, download its `cross-platform-qualification` artifact, and run `python scripts/check_rust_verifier_cross_platform_qualification.py --evidence-dir <reports> --write --require-qualified`."
    )
    return "\n".join([
        "# RUST-1.2.2 — Cross-Platform Release Qualification", "",
        f"Final decision: **{record['final_decision']}**", "", "Authority: **Python**. Migration phase: **RP2**.", "",
        "| Platform | Rust target | Result | Evidence provenance |", "|---|---|---|---|", *rows, "",
        f"The canonical release build and packaging commands are recorded in the machine-readable report. {qualification_summary}", "",
        "The workflow runs the full 404-case canary on Linux and a representative installed-artifact subset everywhere. It uploads archives, checksums, manifests, and qualification reports; it does not publish a public release.", "",
        next_action, "",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "docs/compiler/rust_verifier_platform_evidence")
    parser.add_argument(
        "--flatten-downloaded",
        type=Path,
        metavar="IMPORTED_DIR",
        help="flatten downloaded qualification artifacts into --evidence-dir and exit",
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-qualified", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.flatten_downloaded is not None:
        if args.write or args.check or args.require_qualified or args.output_dir is not None:
            parser.error("--flatten-downloaded cannot be combined with aggregate report options")
        flatten_downloaded_evidence(
            args.flatten_downloaded.resolve(), args.evidence_dir.resolve()
        )
        return 0
    record = build_record(args.evidence_dir.resolve())
    rendered_json = json.dumps(record, indent=2, sort_keys=True) + "\n"
    rendered_md = render_markdown(record)
    json_path = (args.output_dir / OUTPUT_JSON.name) if args.output_dir else OUTPUT_JSON
    md_path = (args.output_dir / OUTPUT_MD.name) if args.output_dir else OUTPUT_MD
    if args.write:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(rendered_json, encoding="utf-8", newline="\n")
        md_path.write_text(rendered_md, encoding="utf-8", newline="\n")
    if args.check and (not json_path.is_file() or json_path.read_text() != rendered_json or not md_path.is_file() or md_path.read_text() != rendered_md):
        print("stale RUST-1.2.2 qualification artifacts", file=sys.stderr)
        return 1
    print(record["final_decision"])
    return 1 if args.require_qualified and record["final_decision"] != "CROSS_PLATFORM_COMPANION_QUALIFIED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
