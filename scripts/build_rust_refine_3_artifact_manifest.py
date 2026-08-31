#!/usr/bin/env python3
"""Build a fail-closed manifest for one official RUST-REFINE-3 run."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any


PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64")
PYTHONS = ("3.11", "3.12", "3.13", "3.14")
BASE = {
    "rust-refine-3-prerequisite": ("prerequisite-rust-refine-2", "prerequisite"),
    "rust-refine-3-contract": ("authority-contract", "authority_contract"),
    "rust-refine-3-differential": ("directed-differential", "directed_differential"),
    "rust-refine-3-mutations": ("mutation-adversarial", "mutation_adversarial"),
    "rust-refine-3-production-authority": ("production-authority", "production_authority"),
    "rust-refine-3-no-python-rescue": ("no-python-rescue", "no_python_rescue"),
    "rust-refine-3-transport": ("transport-parity", "transport_parity"),
    "rust-refine-3-production-pipeline": ("production-pipeline", "production_pipeline"),
    "rust-refine-3-packaged": ("packaged-clean-consumer", "packaged_clean_consumer"),
    "rust-refine-3-source": ("source-development", "source_development"),
    "rust-refine-3-deep": ("deep-stress", "deep_stress"),
    "rust-refine-3-cost": ("cost-characterization", "cost_characterization"),
}


def expected() -> dict[str, tuple[str, str]]:
    result = dict(BASE)
    result.update(
        {
            f"rust-refine-3-platform-{value}": (
                "platform-qualification",
                "platform_qualification",
            )
            for value in PLATFORMS
        }
    )
    result.update(
        {
            f"rust-refine-3-python-{value}": (
                "python-compatibility",
                "python_compatibility",
            )
            for value in PYTHONS
        }
    )
    return result


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=Path, required=True)
    parser.add_argument("--downloaded", type=Path, required=True)
    parser.add_argument("--zips", type=Path, required=True)
    parser.add_argument("--job-results", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    api = json.loads(args.api.read_text(encoding="utf-8"))
    api_rows = {row["name"]: row for row in api.get("artifacts", [])}
    entries: list[dict[str, Any]] = []
    for name, (job, kind) in expected().items():
        api_row = api_rows.get(name, {})
        directory = args.downloaded / name
        evidence = None
        for candidate in sorted(directory.rglob("*.json")) if directory.is_dir() else ():
            try:
                value = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("kind") == kind:
                evidence = candidate
                break
        archive = args.zips / f"{name}.zip"
        record = (
            json.loads(evidence.read_text(encoding="utf-8"))
            if evidence is not None
            else {}
        )
        entries.append(
            {
                "artifact_id": api_row.get("id"),
                "name": name,
                "source_job": job,
                "kind": kind,
                "run_id": str(args.run_id),
                "revision": args.revision,
                "status": record.get("status", "MISSING"),
                "github_digest": api_row.get("digest"),
                "downloaded_zip": (
                    os.path.relpath(archive, args.output.parent)
                    if archive.is_file()
                    else None
                ),
                "downloaded_zip_sha256": (
                    _hash(archive) if archive.is_file() else None
                ),
                "extracted_evidence": (
                    os.path.relpath(evidence, args.output.parent)
                    if evidence is not None
                    else None
                ),
                "extracted_evidence_sha256": (
                    _hash(evidence) if evidence is not None else None
                ),
            }
        )
    jobs = json.loads(args.job_results.read_text(encoding="utf-8"))
    passed = all(row["status"] == "PASS" for row in entries) and all(
        value == "success" for value in jobs.values()
    )
    manifest = {
        "artifact_schema_version": 1,
        "milestone": "RUST-REFINE-3",
        "kind": "official_artifact_manifest",
        "revision": args.revision,
        "run_id": str(args.run_id),
        "job_results": jobs,
        "artifacts": entries,
        "aggregate_claim": (
            "RUST_REFINEMENT_AUTHORITY_PROMOTED"
            if passed
            else "RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"manifested {len(entries)} mandatory artifacts")
    # Always hand the complete manifest to the dedicated checker.  The checker
    # owns the non-zero fail-closed decision and emits the decision artifact.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
