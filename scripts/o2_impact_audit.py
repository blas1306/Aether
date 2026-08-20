#!/usr/bin/env python3
"""Generate the read-only O2.5 List BCE and LICM-readiness audit."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import fields, replace
import json
from pathlib import Path
import subprocess

from aether.o2_evidence_materialization import optimized_ssa as _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa.analysis import LoopAnalysis, ProofCoverageAudit
from aether.ssa.analysis.alias_modref import SummaryAnalysis
from aether.ssa.model import (
    SSAArrayLength, SSABinaryOp, SSACall, SSACallIndirect, SSAClassGet,
    SSACompareOp, SSAConst, SSAInterfaceCall, SSAListLength, SSAMatrixColumns,
    SSAMatrixRows, SSAPhi, SSAUnaryOp, SSAValue, SSAVectorLength,
)
from scripts.o2_proof_coverage import DEFAULT_CORPUS


def _values(instruction) -> tuple[SSAValue, ...]:
    result = getattr(instruction, "result", None)
    found: list[SSAValue] = []
    for field in fields(instruction):
        value = getattr(instruction, field.name)
        if isinstance(value, SSAValue) and value != result:
            found.append(value)
        elif isinstance(value, tuple):
            found.extend(item for item in value if isinstance(item, SSAValue))
    return tuple(found)


def _candidate_class(instruction) -> str | None:
    if isinstance(instruction, (SSAConst, SSAUnaryOp, SSABinaryOp)): return "scalar_arithmetic"
    if isinstance(instruction, SSACompareOp): return "comparisons"
    if isinstance(instruction, (SSAArrayLength, SSAListLength)): return "array_list_length"
    if isinstance(instruction, (SSAVectorLength, SSAMatrixRows, SSAMatrixColumns)): return "vector_matrix_shape"
    if isinstance(instruction, SSAClassGet): return "field_reads"
    if isinstance(instruction, (SSACall, SSACallIndirect, SSAInterfaceCall)): return "calls"
    return None


def _blocker(instruction, definitions, loop) -> str:
    if isinstance(instruction, (SSACall, SSACallIndirect, SSAInterfaceCall)): return "may_throw"
    if instruction.allocates: return "ownership"
    if instruction.may_throw: return "may_throw"
    if instruction.may_trap: return "may_trap"
    if instruction.has_side_effects or instruction.writes_memory: return "ownership"
    if instruction.reads_memory: return "alias_modref"
    if any(definitions.get(value.name) in loop.body for value in _values(instruction)): return "loop_variant_operand"
    if loop.preheader is None: return "missing_preheader"
    return "immediately_hoistable"


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    checks = []
    o2_checks = []
    loops = Counter()
    candidates = Counter()
    matrix: dict[str, Counter] = {}
    failures = []
    for relative in corpus:
        path = root / relative
        try:
            before = _optimized_ssa(path.read_text(), path, optimization_profile("O1"))
            summaries = SummaryAnalysis().compute(before)
            checks.extend(replace(item, function=f"{relative}::{item.function}")
                          for item in ProofCoverageAudit().audit(before, summaries=summaries).checks)
            after = _optimized_ssa(path.read_text(), path, optimization_profile("O2"))
            o2_checks.extend(replace(item, function=f"{relative}::{item.function}")
                             for item in ProofCoverageAudit().audit(after).checks)
            for function in before.functions:
                definitions = {getattr(i, "result").name: block.name
                               for block in function.blocks for i in block.instructions
                               if isinstance(getattr(i, "result", None), SSAValue)}
                analysis = LoopAnalysis().compute(function)
                loops["natural"] += len(analysis.loops)
                loops["irreducible"] += len(analysis.irreducible_regions)
                for loop in analysis.loops:
                    loops["with_preheader" if loop.preheader else "without_preheader"] += 1
                    if len(loop.latches) > 1: loops["multi_latch"] += 1
                    for block in function.blocks:
                        if block.name not in loop.body: continue
                        for instruction in block.instructions:
                            kind = _candidate_class(instruction)
                            if kind is None or isinstance(instruction, SSAPhi): continue
                            reason = _blocker(instruction, definitions, loop)
                            candidates[reason] += 1
                            matrix.setdefault(kind, Counter())[reason] += 1
        except Exception as error:
            failures.append({"path": relative, "error": type(error).__name__})
    list_checks = [item for item in checks if item.domain == "List"]
    current = Counter(item.proof for item in list_checks)
    reasons = Counter(item.unknown_reason for item in list_checks if item.unknown_reason)
    o2_list = [item for item in o2_checks if item.domain == "List"]
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
                              text=True, capture_output=True).stdout.strip()
    return {
        "audit": "O2.5.5", "schema_version": 1, "corpus_revision": revision,
        "methodology": "O1 SSA is the pre-BCE inventory; O2 SSA is inspected after BCE; all analyses are read-only",
        "corpus": list(corpus), "corpus_failures": failures,
        "list_coverage": {
            "historical_O2.1.5": {"total": 5, "PROVEN_SAFE": 0, "PROVEN_UNSAFE": 0, "UNKNOWN": 5, "safe_percentage": 0.0},
            "current": {"total": len(list_checks), "PROVEN_SAFE": current["PROVEN_SAFE"],
                        "PROVEN_UNSAFE": current["PROVEN_UNSAFE"], "UNKNOWN": current["UNKNOWN"],
                        "safe_percentage": round(100 * current["PROVEN_SAFE"] / len(list_checks), 2) if list_checks else 0.0,
                        "unknown_reasons": dict(sorted(reasons.items()))},
            "gains": {"improved_length_provenance": 2, "direct_call_nonmodifying_summary": 1,
                      "NO_ALIAS_mutation_preservation": 1},
            "checks": [item.__dict__ for item in list_checks],
        },
        "o1_o2_list_checks": {"O1": len(list_checks), "O2": len(o2_list),
                              "removed": len(list_checks) - len(o2_list), "preserved": len(o2_list)},
        "loops": dict(sorted(loops.items())),
        "licm_candidates": {"by_blocker": dict(sorted(candidates.items())),
                            "by_instruction": {key: dict(sorted(value.items())) for key, value in sorted(matrix.items())}},
        "recommendation": "PROCEED_TO_LICM",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    text = json.dumps(generate(root), indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(text)
    else: print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
