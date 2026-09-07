#!/usr/bin/env python3
"""Warm-cache debug/release driver snapshots; see README for timer scopes.

Each invocation builds through clang, but reported core time is the sum of the
original eight internal compiler timers, excluding clang, I/O and discovery.
Detail timers are inclusive and overlapping; never add them to core time.
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
    "v15_capabilities.ae", "v16_owned_collections.ae",
    "v17_array_storage.ae", "v17_list_storage.ae", "v17_storable.ae",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/aether-next")
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    report = {"binary": str(args.binary.resolve()), "platform": platform.platform(),
              "runs_per_fixture": args.runs, "warmups_per_fixture": 1,
              "unit": "milliseconds", "core_phases": CORE, "fixtures": {}}
    with tempfile.TemporaryDirectory(prefix="aether-v17-timing-") as temp:
        for fixture in FIXTURES:
            samples = []
            for run in range(args.runs + 1):
                result = subprocess.run(
                    [str(args.binary.resolve()), "build", str(ROOT / "tests/programs" / fixture),
                     "-o", str(Path(temp) / "artifact"), "--timings"],
                    capture_output=True, text=True, check=True,
                )
                timings = {key: int(value) / 1_000_000 for key, value in
                           re.findall(r"^timing (\S+): (\d+) ns$", result.stderr, re.MULTILINE)}
                timings["core"] = sum(timings[key] for key in CORE)
                if run:
                    samples.append(timings)
            report["fixtures"][fixture] = {
                key: {"mean": statistics.mean(sample[key] for sample in samples),
                      "median": statistics.median(sample[key] for sample in samples)}
                for key in samples[0]
            }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
