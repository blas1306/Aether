#!/usr/bin/env python3
"""V26 warm-cache snapshots using the eight V17 core phase boundaries.

Run after building the debug driver, without concurrent builds. Each sample is
one fresh process, including clang/link, which are excluded from core timings.
Optional baseline binary must be built separately from the unmodified V25 tree.
"""
import argparse
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORE = (
    "frontend.parse", "frontend.signature_collection", "frontend.semantic_bodies",
    "middle.mir_lower", "middle.mir_verify", "middle.ssa_build",
    "middle.ssa_verify", "backend.llvm",
)
FIXTURES = (
    "v25_vector_view_normal.ae", "v26_matrix_axis_row.ae",
    "v26_matrix_axis_column.ae", "v26_matrix_axis_transpose_row.ae",
    "v26_matrix_axis_projected.ae",
)


def measure(binary, fixture, runs, artifact):
    samples = []
    for run in range(runs + 1):
        result = subprocess.run(
            [str(binary.resolve()), "build", str(ROOT / "tests/programs" / fixture),
             "-o", str(artifact), "--timings"],
            capture_output=True, text=True, check=True,
        )
        timings = {key: int(value) / 1_000_000 for key, value in
                   re.findall(r"^timing (\S+): (\d+) ns$", result.stderr, re.MULTILINE)}
        timings["core"] = sum(timings[key] for key in CORE)
        if run:
            samples.append(timings)
    return {
        key: {"mean": statistics.mean(sample[key] for sample in samples),
              "median": statistics.median(sample[key] for sample in samples)}
        for key in samples[0]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/aether-next")
    parser.add_argument("--baseline-binary", type=Path)
    parser.add_argument("--baseline-revision")
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    report = {
        "binary": str(args.binary.resolve()), "platform": platform.platform(),
        "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "clang": subprocess.check_output(["clang", "--version"], text=True).splitlines()[0],
        "runs_per_fixture": args.runs, "warmups_per_fixture": 1,
        "unit": "milliseconds", "core_phases": CORE, "fixtures": {},
    }
    with tempfile.TemporaryDirectory(prefix="aether-v26-timing-") as temp:
        artifact = Path(temp) / "artifact"
        if args.baseline_binary:
            report["v25_baseline"] = {
                "binary": str(args.baseline_binary.resolve()),
                "revision": args.baseline_revision,
                "fixture": "v25_vector_view_normal.ae",
                "timings": measure(args.baseline_binary, "v25_vector_view_normal.ae", args.runs, artifact),
            }
        for fixture in FIXTURES:
            report["fixtures"][fixture] = measure(args.binary, fixture, args.runs, artifact)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
