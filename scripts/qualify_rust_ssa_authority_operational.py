#!/usr/bin/env python3
"""Run the expanded RUST-3.6 soak with Rust SSA authority."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import qualify_rust_ssa_shadow_operational as qualification
from aether.ssa.shadow import lower_with_rust_authority


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # Reuse the frozen RUST-3.4 inventory, persistent-session, concurrency, and
    # classification harness while changing only which matched object returns.
    qualification.lower_with_rust_shadow = lower_with_rust_authority
    report = qualification.generate()
    report["milestone"] = "RUST-3.6"
    report.pop("gates", None)
    report.pop("ci", None)
    report["decision"] = (
        "RUST_SSA_AUTHORITY_SOAK_PASS"
        if report["soak"]["semantic_mismatches"] == 0
        and report["soak"]["infrastructure_failures"] == 0
        and report["soak"]["shadow_compared"] == report["soak"]["accepted"]
        else "RUST_SSA_AUTHORITY_SOAK_FAILED"
    )
    report["authority"] = {
        "repository_default": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "qualification_mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "returned_ssa": "rust_schema_v2_import",
        "python_shadow": "synchronous_mandatory",
        "rust_reaches_optimizer_or_backend": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report["decision"])
    return 0 if report["decision"] == "RUST_SSA_AUTHORITY_SOAK_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
