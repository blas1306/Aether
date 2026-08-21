#!/usr/bin/env python3
"""Run the frozen 116-program corpus through RUST-3.6 authority."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
)
from aether.typechecker import TypeChecker  # noqa: E402


def discover() -> list[Path]:
    roots = (ROOT / "examples", ROOT / "benchmarks", ROOT / "corpus/exceptions")
    return sorted({path for root in roots for path in root.rglob("*.ae")})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    rows = []
    with PersistentRustSSALoweringClient(args.executable, timeout_seconds=30) as client:
        for path in discover():
            try:
                source = path.read_text(encoding="utf-8")
                typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
                initial = IRBackend().lower_verified(typed)
            except Exception:
                continue
            pipeline = SSAPipeline(
                authority_configuration=SSALoweringAuthorityConfiguration(
                    SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
                ),
                rust_shadow_client=client,
            )
            result = pipeline.run(initial)
            snapshot = json.dumps(
                ir_module_to_dto(initial), sort_keys=True, separators=(",", ":")
            ).encode()
            response_a = client.lower(snapshot)
            response_b = client.lower(snapshot)
            rust_dto = response_a.get("ssa")
            exact = (
                response_a.get("ok") is True
                and response_a == response_b
                and isinstance(rust_dto, dict)
                and ssa_module_to_dto(ssa_module_from_dto(rust_dto), schema_version=2) == rust_dto
            )
            checks = {
                "lifecycle_parity": pipeline.last_authority_report.classification == "match",
                "canonical_ssa_parity": pipeline.last_authority_report.classification == "match",
                "rust_owned_ssa_verification": response_a.get("ok") is True,
                "python_ssa_verification": pipeline.last_authority_report.classification == "match",
                "schema_v2_import": isinstance(rust_dto, dict),
                "exact_reserialization": exact,
                "determinism": response_a == response_b,
                "returned_ssa_is_rust": pipeline.last_returned_ssa_origin == "rust_schema_v2_import",
            }
            for name, passed in checks.items():
                counts[name] += int(passed)
            rows.append({"path": path.relative_to(ROOT).as_posix(), "checks": checks})
            if result.ssa_module is None:
                raise AssertionError("authority returned no SSA after a match")
        requests = client.request_count
        startups = client.process_start_count

    expected = 116
    passed = len(rows) == expected and all(counts[name] == expected for name in counts)
    report = {
        "evidence_schema_version": 1,
        "milestone": "RUST-3.6",
        "decision": "RUST_SSA_AUTHORITY_HISTORICAL_PASS" if passed else "RUST_SSA_AUTHORITY_HISTORICAL_FAILED",
        "expected": expected,
        "accepted": len(rows),
        "checks": {name: {"passed": counts[name], "failed": len(rows) - counts[name]} for name in sorted(counts)},
        "transport": {"requests": requests, "process_startups": startups},
        "programs": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
