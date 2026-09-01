#!/usr/bin/env python3
"""Build the official manifest for one RUST-IR-2 GitHub Actions run."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rust_ir_2_artifacts import (  # noqa: E402
    BLOCKED,
    MILESTONE,
    QUALIFIED,
    expected,
)


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _role(kind: str) -> str:
    if kind == "platform_qualification":
        return "platform"
    if kind == "python_compatibility":
        return "python_compatibility"
    return "dedicated"


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
        evidence = None
        record: dict[str, Any] = {}
        for candidate in candidates:
            try:
                candidate_record = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if candidate_record.get("kind") == kind:
                evidence = candidate
                record = candidate_record
                break
        archive = args.zips / f"{name}.zip"
        entries.append(
            {
                "artifact_id": api_row.get("id"),
                "name": name,
                "source_job": job,
                "run_id": str(args.run_id),
                "revision": args.revision,
                "kind": kind,
                "role": _role(kind),
                "status": record.get("status", "MISSING"),
                "github_digest": api_row.get("digest"),
                "downloaded_zip": (
                    os.path.relpath(archive, args.output.parent)
                    if archive.is_file()
                    else None
                ),
                "downloaded_zip_sha256": (
                    file_hash(archive) if archive.is_file() else None
                ),
                "extracted_evidence": (
                    os.path.relpath(evidence, args.output.parent)
                    if evidence is not None
                    else None
                ),
                "extracted_evidence_sha256": (
                    file_hash(evidence) if evidence is not None else None
                ),
            }
        )
    jobs = json.loads(args.job_results.read_text(encoding="utf-8"))
    manifest = {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": "official_artifact_manifest",
        "revision": args.revision,
        "run_id": str(args.run_id),
        "job_results": jobs,
        "artifacts": entries,
    }
    manifest["aggregate_claim"] = (
        QUALIFIED
        if all(row["status"] == "PASS" for row in entries)
        and all(status == "success" for status in jobs.values())
        else BLOCKED
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"manifested {len(entries)} mandatory artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
