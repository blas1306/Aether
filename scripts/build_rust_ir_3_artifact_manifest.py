#!/usr/bin/env python3
"""Bind official GitHub RUST-IR-3 artifact identities to extracted evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_rust_ir_3_authority_promotion import EXPECTED, EXPECTED_JOBS, MILESTONE, WORKFLOW  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--zip-root", type=Path, required=True)
    parser.add_argument("--artifacts-api", type=Path, required=True)
    parser.add_argument("--jobs-api", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact_api = json.loads(args.artifacts_api.read_text(encoding="utf-8"))
    jobs_api = json.loads(args.jobs_api.read_text(encoding="utf-8"))
    api_by_name = {item["name"]: item for item in artifact_api.get("artifacts", [])}
    if set(api_by_name) != set(EXPECTED):
        raise SystemExit("official producer artifact name set mismatch")
    job_conclusions = {
        item["name"]: item.get("conclusion")
        for item in jobs_api.get("jobs", [])
        if item["name"] in EXPECTED_JOBS
    }
    # aggregate-fail-closed is currently running and is sealed as success only
    # after this builder and the checker return successfully.
    job_conclusions["aggregate-fail-closed"] = "success"
    if set(job_conclusions) != EXPECTED_JOBS:
        raise SystemExit("official mandatory job name set mismatch")
    records = []
    for name, (source_job, kind, role) in EXPECTED.items():
        api = api_by_name[name]
        directory = args.artifact_root / name
        candidates = sorted(directory.rglob("*.json"))
        if len(candidates) != 1:
            raise SystemExit(f"{name}: expected exactly one JSON evidence file")
        evidence = candidates[0]
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        if payload.get("kind") != kind:
            raise SystemExit(f"{name}: evidence kind mismatch")
        archive = args.zip_root / f"{name}.zip"
        zip_digest = sha256(archive.read_bytes()).hexdigest()
        github_digest = str(api.get("digest", "")).removeprefix("sha256:")
        if zip_digest != github_digest:
            raise SystemExit(f"{name}: downloaded ZIP does not match GitHub digest")
        records.append({
            "id": api["id"],
            "name": name,
            "source_job": source_job,
            "kind": kind,
            "role": role,
            "run_id": str(args.run_id),
            "revision": args.revision,
            "github_digest": api["digest"],
            "zip_sha256": zip_digest,
            "evidence_path": os.path.relpath(evidence, args.output.parent),
            "evidence_sha256": sha256(evidence.read_bytes()).hexdigest(),
            "status": payload.get("status"),
        })
    manifest = {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "workflow": WORKFLOW,
        "run_id": str(args.run_id),
        "revision": args.revision,
        "run_conclusion": "success",
        "job_conclusions": job_conclusions,
        "artifacts": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
