#!/usr/bin/env python3
"""Build the official RUST-REFINE-2 artifact manifest from one Actions run."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any


BASE = {
    "rust-refine-2-contract": ("contract-and-baseline", "contract_and_baseline"),
    "rust-refine-2-rust-validation": ("rust-unit-and-adversarial", "rust_unit_and_adversarial"),
    "rust-refine-2-historical": ("historical-differential", "historical_differential"),
    "rust-refine-2-mutations": ("mutation-campaign", "mutation_campaign"),
    "rust-refine-2-production-pipeline": ("production-pipeline-shadow", "production_pipeline_shadow"),
    "rust-refine-2-transport-parity": ("transport-parity", "transport_parity"),
    "rust-refine-2-packaged-consumer": ("packaged-clean-consumer", "packaged_clean_consumer"),
    "rust-refine-2-source-install": ("source-development-install", "source_development_install"),
    "rust-refine-2-deep-cfg": ("deep-cfg-stress", "deep_cfg_stress"),
    "rust-refine-2-cost": ("cost-characterization", "cost_characterization"),
}
PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64")
PYTHONS = ("3.11", "3.12", "3.13", "3.14")


def expected() -> dict[str, tuple[str, str]]:
    result = dict(BASE)
    result.update({f"rust-refine-2-platform-{value}": ("platform-qualification", "platform_qualification") for value in PLATFORMS})
    result.update({f"rust-refine-2-python-{value}": ("python-compatibility", "python_compatibility") for value in PYTHONS})
    return result


def file_hash(path: Path) -> str:
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
        candidates = sorted(directory.rglob("*.json")) if directory.is_dir() else []
        evidence = next((path for path in candidates if json.loads(path.read_text(encoding="utf-8")).get("kind") == kind), None)
        archive = args.zips / f"{name}.zip"
        record = json.loads(evidence.read_text(encoding="utf-8")) if evidence else {}
        entries.append({
            "artifact_id": api_row.get("id"),
            "name": name,
            "source_job": job,
            "run_id": str(args.run_id),
            "revision": args.revision,
            "kind": kind,
            "status": record.get("status", "MISSING"),
            "github_digest": api_row.get("digest"),
            "downloaded_zip": os.path.relpath(archive, args.output.parent) if archive.is_file() else None,
            "downloaded_zip_sha256": file_hash(archive) if archive.is_file() else None,
            "extracted_evidence": os.path.relpath(evidence, args.output.parent) if evidence else None,
            "extracted_evidence_sha256": file_hash(evidence) if evidence else None,
        })
    manifest = {
        "artifact_schema_version": 1,
        "milestone": "RUST-REFINE-2",
        "kind": "official_artifact_manifest",
        "revision": args.revision,
        "run_id": str(args.run_id),
        "job_results": json.loads(args.job_results.read_text(encoding="utf-8")),
        "artifacts": entries,
    }
    manifest["aggregate_claim"] = (
        "RUST_REFINEMENT_SHADOW_QUALIFIED"
        if all(row["status"] == "PASS" for row in entries)
        and all(value == "success" for value in manifest["job_results"].values())
        else "RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"manifested {len(entries)} mandatory artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
