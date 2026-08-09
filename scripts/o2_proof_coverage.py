#!/usr/bin/env python3
"""Generate the internal O2.1 bounds/shape proof-coverage report."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess

from aether.benchmark import _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa.analysis import CoverageReport, ProofCoverageAudit


DEFAULT_CORPUS = (
    "benchmarks/array_sum.ae",
    "benchmarks/list_for_sum.ae",
    "benchmarks/matrix_mul.ae",
    "benchmarks/nested_loops.ae",
    "benchmarks/vector_dot.ae",
    "examples/llvm/array_sum.ae",
    "examples/llvm/for_break_continue.ae",
    "examples/llvm/list_index.ae",
    "examples/llvm/list_push_alias.ae",
    "examples/llvm/list_set_alias.ae",
    "examples/llvm/matrix_index.ae",
    "examples/llvm/matrix_matmul.ae",
    "examples/llvm/vector_add.ae",
    "examples/numerical_methods/main.ae",
    "examples/ProbandoNR/probandoNR2.ae",
    "tests/fixtures/o2_proof_coverage/slices.ae",
)


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    checks = []
    failures = []
    auditor = ProofCoverageAudit()
    for relative in corpus:
        path = root / relative
        try:
            module = _optimized_ssa(path.read_text(), path, optimization_profile("O2"))
            for record in auditor.audit(module).checks:
                checks.append(replace(record, function=f"{relative}::{record.function}"))
        except Exception as error:  # audit tooling records corpus gaps; it does not hide them
            failures.append({"path": relative, "error": type(error).__name__})
    report = CoverageReport(1, tuple(checks))
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=root, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    return {
        "audit": "O2.1.5",
        "corpus_revision": revision,
        "optimization_profile": "O2",
        "methodology": "optimized SSA; read-only O2.1 Loop/Range/Shape analyses",
        "corpus": list(corpus),
        "corpus_failures": failures,
        **report.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = json.dumps(generate(root), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
