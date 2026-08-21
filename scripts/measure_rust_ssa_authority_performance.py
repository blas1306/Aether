#!/usr/bin/env python3
"""Record observational dual-lane SSA authority performance measurements."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.pipeline import IRBackend, prepare_typed_program  # noqa: E402
from aether.ssa.general_builder import GeneralSSABuilder  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    lower_with_rust_authority,
)
from aether.typechecker import TypeChecker  # noqa: E402


WORKLOADS = (
    "benchmarks/arithmetic.ae",
    "examples/numerical_methods/main.ae",
    "examples/expense_tracker/Main.ae",
    "corpus/exceptions/positive/indirect_call.ae",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--revision")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")

    modules = []
    for relative in WORKLOADS:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
        modules.append((relative, IRBackend().lower_verified(typed)))

    rows = []
    with PersistentRustSSALoweringClient(args.executable, timeout_seconds=30) as client:
        for name, module in modules:
            python_times = []
            authority_times = []
            for _ in range(args.rounds):
                started = perf_counter_ns()
                GeneralSSABuilder().build(module)
                python_times.append(perf_counter_ns() - started)
                started = perf_counter_ns()
                lower_with_rust_authority(module, client)
                authority_times.append(perf_counter_ns() - started)
            python_median = int(statistics.median(python_times))
            authority_median = int(statistics.median(authority_times))
            rows.append(
                {
                    "workload": name,
                    "rounds": args.rounds,
                    "python_only_median_ns": python_median,
                    "rust_authority_python_shadow_median_ns": authority_median,
                    "observed_authority_over_python_ratio": round(authority_median / python_median, 3),
                }
            )
        requests = client.request_count
        startups = client.process_start_count
    python_total = sum(row["python_only_median_ns"] for row in rows)
    authority_total = sum(row["rust_authority_python_shadow_median_ns"] for row in rows)
    report = {
        "schema_version": 1,
        "milestone": "RUST-3.5b" if args.revision else "RUST-3.6",
        **({"qualification_revision": args.revision} if args.revision else {}),
        "measurement_kind": "observational; no timing assertion or absolute gate",
        "workloads": rows,
        "python_only_representative_median_total_ns": python_total,
        "rust_authority_python_shadow_representative_median_total_ns": authority_total,
        "observed_authority_over_python_ratio": round(authority_total / python_total, 3),
        "requests": requests,
        "process_startups": startups,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
