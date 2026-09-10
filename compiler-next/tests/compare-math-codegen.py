#!/usr/bin/env python3
"""Compare complete emitted LLVM for V27..V33 using two separately built drivers.

No LLVM normalization: names, ordering, helpers and instructions must all match.
CLI build status lines are excluded. Both builds use the same source paths.
Native artifacts are linked to validate LLVM, but are not executed here; the
workspace suite independently qualifies runtime values, traps and counters.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def emit(binary, fixture, artifact):
    result = subprocess.run(
        [str(binary.resolve()), "build", str(fixture), "-o", str(artifact),
         "--emit", "llvm"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.split("== llvm ==\n", 1)[1].rsplit("\nbuilt ", 1)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-binary", type=Path, required=True)
    parser.add_argument("--binary", type=Path,
                        default=ROOT / "target/debug/aether-next")
    parser.add_argument("--baseline-revision", required=True)
    args = parser.parse_args()
    prefixes = tuple(f"v{i}_" for i in range(27, 34))
    fixtures = sorted(p for p in (ROOT / "tests/programs").glob("*.ae")
                      if p.name.startswith(prefixes))
    fixtures.append(ROOT / "tests/programs/math_arch_1_double_transpose.ae")
    records = []
    with tempfile.TemporaryDirectory(prefix="aether-math-codegen-") as temp:
        artifact = Path(temp) / "artifact"
        for fixture in fixtures:
            before = emit(args.baseline_binary, fixture, artifact)
            after = emit(args.binary, fixture, artifact)
            records.append({
                "fixture": str(fixture.relative_to(ROOT)),
                "identical": before == after,
                "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
            })
    failures = sum(not record["identical"] for record in records)
    print(json.dumps({
        "baseline_revision": args.baseline_revision,
        "comparison": "complete LLVM, byte for byte; no normalization",
        "checked": len(records), "failures": failures, "fixtures": records,
    }, indent=2, sort_keys=True))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
