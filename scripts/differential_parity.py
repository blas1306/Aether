#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.differential import DEFAULT_CORPUS_ROOT, OPTIMIZATION_LEVELS, discover_cases, run_corpus


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare AST and native observations for the current capability profile.",
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    cases = discover_cases(args.corpus)
    results = run_corpus(cases, timeout=args.timeout)
    comparisons = len(results) * len(OPTIMIZATION_LEVELS)
    print(
        f"PASS: {len(results)} programs, {comparisons} AST/native comparisons "
        f"across {', '.join(OPTIMIZATION_LEVELS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
