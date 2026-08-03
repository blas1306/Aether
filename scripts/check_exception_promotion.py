#!/usr/bin/env python3
"""Run the ERQ-006 corpus, differential oracle, and release contracts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.exception_evidence import (  # noqa: E402
    REPORT_PATH,
    build_report,
    canonical_report_text,
    capability_errors,
    catalog_errors,
    check_report,
    load_catalog,
    negative_errors,
    run_corpus,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-native",
        action="store_true",
        help="Run frontend/IR/SSA checks only (development use).",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Replace the checked-in deterministic differential report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    positives, negatives = load_catalog()
    errors = [
        *catalog_errors(),
        *capability_errors(positives),
        *negative_errors(negatives),
    ]
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    results = run_corpus(
        positives,
        native=not args.no_native,
        timeout=args.timeout,
    )
    report = build_report(results, negatives)
    if args.write_report:
        REPORT_PATH.write_text(
            canonical_report_text(report),
            encoding="utf-8",
            newline="\n",
        )
    elif not args.no_native:
        errors = check_report(report)
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1

    stage_count = len(results[0].stages) if results else 0
    comparisons = len(results) * max(0, stage_count - 1)
    mode = "all stages" if not args.no_native else "frontend/IR/SSA"
    print(
        f"PASS ERQ-006: {len(results)} positive, {len(negatives)} negative, "
        f"{comparisons} differential comparisons ({mode})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
