#!/usr/bin/env python3
"""Generate the read-only O2.6.2 next-optimization opportunity audit."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import fields
import json
from pathlib import Path
import subprocess

from aether.benchmark import _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa.analysis import LoopAnalysis
from aether.ssa.model import (
    SSAArrayGet, SSAArrayLength, SSACall, SSACallIndirect, SSAClassGet,
    SSAInterfaceCall, SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface,
    SSAListGet, SSAListLength, SSAMatrixColumns, SSAMatrixGet, SSAMatrixRows,
    SSAStructGet, SSAValue, SSAVectorGet, SSAVectorLength,
)
from aether.ssa.optimizer import LoopInvariantCodeMotion, ProvenBoundsCheckEliminator
from aether.ssa.operands import instruction_result
try:
    from scripts.o2_proof_coverage import DEFAULT_CORPUS
except ModuleNotFoundError:  # direct ``python scripts/...`` invocation
    from o2_proof_coverage import DEFAULT_CORPUS


GENERAL_READS = (SSAArrayGet, SSAListGet, SSAVectorGet, SSAMatrixGet, SSAClassGet, SSAStructGet)
DIRECT_CALLS = (SSACall, SSAInvoke)
INDIRECT_CALLS = (SSACallIndirect, SSAInvokeIndirect)
INTERFACE_CALLS = (SSAInterfaceCall, SSAInvokeInterface)


def _instructions(module):
    for function in module.functions:
        for block in function.blocks:
            for instruction in block.instructions:
                yield function, block, instruction


def _operands(instruction) -> tuple[SSAValue, ...]:
    result = instruction_result(instruction)
    values = []
    for item in fields(instruction):
        value = getattr(instruction, item.name)
        if isinstance(value, SSAValue) and value != result:
            values.append(value)
        elif isinstance(value, tuple):
            values.extend(entry for entry in value if isinstance(entry, SSAValue))
    return tuple(values)


def _instruction_count(module) -> int:
    return sum(1 for _ in _instructions(module))


def _read_kind(instruction) -> str:
    if isinstance(instruction, SSAArrayGet): return "ArrayGet"
    if isinstance(instruction, SSAListGet): return "ListGet"
    if isinstance(instruction, SSAClassGet): return "class_field"
    if isinstance(instruction, SSAStructGet): return "struct_field"
    if isinstance(instruction, SSAVectorGet): return "VectorGet"
    return "MatrixGet"


def _general_reads(module) -> tuple[Counter, Counter, Counter]:
    candidates, blockers, readiness = Counter(), Counter(), Counter()
    for function in module.functions:
        definitions = {
            value.name: block.name
            for block in function.blocks for instruction in block.instructions
            if (value := instruction_result(instruction)) is not None
        }
        for loop in LoopAnalysis().compute(function).loops:
            for block in function.blocks:
                if block.name not in loop.body: continue
                for instruction in block.instructions:
                    if not isinstance(instruction, GENERAL_READS): continue
                    candidates[_read_kind(instruction)] += 1
                    operands = _operands(instruction)
                    variant = any(definitions.get(value.name) in loop.body for value in operands)
                    checked = getattr(instruction, "bounds_checked", False)
                    if variant:
                        reason = "index_or_base_varies"
                    elif checked:
                        reason = "may_trap_bounds_check_remains"
                    elif isinstance(instruction, SSAClassGet):
                        reason = "field_insensitive_memory_model"
                    elif isinstance(instruction, SSAStructGet):
                        reason = "ownership_or_aggregate_provenance"
                    else:
                        reason = "modref_proof_required"
                    blockers[reason] += 1
                    if not variant and not checked:
                        readiness["nontrapping_invariant_address"] += 1
                        readiness["needs_field_sensitive_aliasing" if isinstance(instruction, SSAClassGet)
                                  else "immediately_implementable_pending_modref"] += 1
                    elif checked:
                        readiness["needs_BCE_first"] += 1
    return candidates, blockers, readiness


def _arc(module) -> tuple[Counter, Counter, list[dict], list[dict]]:
    counts, hot = Counter(), Counter()
    by_function = []
    for function in module.functions:
        loops = LoopAnalysis().compute(function).loops
        loop_blocks = set().union(*(loop.body for loop in loops)) if loops else set()
        local = Counter()
        for block in function.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, (SSACall, SSAInvoke)):
                    if instruction.builtin in {"__aether_retain", "__aether_release"}:
                        kind = instruction.builtin.removeprefix("__aether_")
                        counts[kind] += 1; local[kind] += 1
                        if block.name in loop_blocks: hot[kind] += 1
                if type(instruction).__name__ == "SSAExceptionDestroy":
                    counts["destroy"] += 1; local["destroy"] += 1
                    if block.name in loop_blocks: hot["destroy"] += 1
        if local:
            by_function.append({"function": function.name, **dict(sorted(local.items()))})
    # Textual balance is only an opportunity upper bound; it is not a proof.
    apparent = min(counts["retain"], counts["release"])
    classes = Counter({"NEEDS_OWNERSHIP_DATAFLOW": apparent})
    return counts, hot, [{"classification": key, "count": value} for key, value in classes.items()], by_function


def _calls(module) -> dict:
    sizes = {function.name: sum(len(block.instructions) for block in function.blocks) for function in module.functions}
    distribution = sorted(sizes.values())
    q1 = distribution[max(0, len(distribution) // 4 - 1)] if distribution else 0
    median = distribution[max(0, len(distribution) // 2 - 1)] if distribution else 0
    counts, candidates = Counter(), Counter()
    graph: dict[str, set[str]] = {name: set() for name in sizes}
    for function, _block, instruction in _instructions(module):
        if isinstance(instruction, DIRECT_CALLS):
            counts["direct"] += 1
            if instruction.function in sizes:
                graph[function.name].add(instruction.function)
                callee = next(item for item in module.functions if item.name == instruction.function)
                recursive = instruction.function == function.name
                if recursive: counts["recursive"] += 1
                elif not callee.may_throw and sizes[instruction.function] <= median:
                    candidates["nonthrowing_small_or_tiny"] += 1
                elif callee.may_throw: candidates["excluded_may_throw"] += 1
        elif isinstance(instruction, INDIRECT_CALLS): counts["indirect"] += 1
        elif isinstance(instruction, INTERFACE_CALLS): counts["interface"] += 1
    mutual = sum(1 for caller, targets in graph.items() for target in targets
                 if caller != target and caller in graph.get(target, set())) // 2
    counts["mutually_recursive_pairs"] = mutual
    buckets = Counter()
    for size in sizes.values():
        buckets["TINY" if size <= q1 else "SMALL" if size <= median else "MEDIUM" if size <= max(median * 2, median + 1) else "LARGE"] += 1
    return {"calls": dict(sorted(counts.items())), "size_thresholds": {"tiny_max": q1, "small_max": median,
            "medium_max": max(median * 2, median + 1)}, "function_sizes": dict(sorted(buckets.items())),
            "immediate_candidates": dict(sorted(candidates.items()))}


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    impact, eligible_reads, reads, blockers, readiness = Counter(), Counter(), Counter(), Counter(), Counter()
    arc_counts, arc_hot, arc_classes = Counter(), Counter(), Counter()
    arc_functions, failures = [], []
    call_totals, size_buckets, inline_candidates = Counter(), Counter(), Counter()
    thresholds = []
    per_workload = []
    for relative in corpus:
        path = root / relative
        try:
            o1 = _optimized_ssa(path.read_text(), path, optimization_profile("O1"))
            after_bce = ProvenBoundsCheckEliminator().run(o1).module
            licm = LoopInvariantCodeMotion().run(after_bce)
            o2 = _optimized_ssa(path.read_text(), path, optimization_profile("O2"))
            impact.update(licm.stats)
            for function in after_bce.functions:
                loop_blocks = set().union(*(loop.body for loop in LoopAnalysis().compute(function).loops))
                for block in function.blocks:
                    if block.name not in loop_blocks: continue
                    for instruction in block.instructions:
                        if isinstance(instruction, SSAArrayLength): eligible_reads["Array.length"] += 1
                        elif isinstance(instruction, SSAListLength): eligible_reads["List.length"] += 1
                        elif isinstance(instruction, SSAVectorLength): eligible_reads["Vector.length"] += 1
                        elif isinstance(instruction, (SSAMatrixRows, SSAMatrixColumns)): eligible_reads["Matrix.rows_columns"] += 1
            c, b, r = _general_reads(after_bce); reads.update(c); blockers.update(b); readiness.update(r)
            ac, ah, classes, by_fn = _arc(o1); arc_counts.update(ac); arc_hot.update(ah)
            arc_classes.update({item["classification"]: item["count"] for item in classes})
            arc_functions.extend({"workload": relative, **item} for item in by_fn)
            calls = _calls(o1); call_totals.update(calls["calls"]); size_buckets.update(calls["function_sizes"])
            inline_candidates.update(calls["immediate_candidates"]); thresholds.append(calls["size_thresholds"])
            per_workload.append({"path": relative, "o1_ssa_instructions": _instruction_count(o1),
                                 "o2_ssa_instructions": _instruction_count(o2),
                                 "reads_hoisted": licm.stats.get("reads_hoisted", 0),
                                 "loops_affected_upper_bound": licm.stats.get("reads_hoisted", 0)})
        except Exception as error:
            failures.append({"path": relative, "error": type(error).__name__, "message": str(error)[:160]})
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
                              text=True, capture_output=True).stdout.strip()
    return {
        "audit": "O2.6.2", "schema_version": 1, "corpus_revision": revision,
        "methodology": "O1 SSA inventory; proven BCE then isolated LICM statistics; final O2 SSA comparison; read-only static opportunity census",
        "corpus": list(corpus), "corpus_failures": failures, "per_workload": per_workload,
        "immutable_read_licm": {"eligible_by_kind": dict(sorted(eligible_reads.items())),
                                "pass_statistics": dict(sorted(impact.items()))},
        "llvm_overlap": {"classification": "LLVM_CONVERGES", "basis": "Aether emits ordinary loads/calls and clang -O2 receives the result; validate per-site with optimized LLVM before claiming AETHER_UNIQUE"},
        "general_memory_reads": {"candidates": dict(sorted(reads.items())), "blockers": dict(sorted(blockers.items())),
                                 "readiness": dict(sorted(readiness.items())), "future_policy": "require invariant base/address and bounds_checked=false"},
        "field_readiness": {"field_sensitive": False, "location_granularity": "whole semantic object", "blocked_candidates": blockers["field_insensitive_memory_model"]},
        "arc": {"operations": dict(sorted(arc_counts.items())), "hot_loop_operations": dict(sorted(arc_hot.items())),
                "apparent_pair_classification": dict(sorted(arc_classes.items())), "by_function": arc_functions,
                "smallest_safe_pass": "same-value local retain/release with ownership dataflow, no escape/consume, dominance and post-dominance, and explicit exceptional-path proof"},
        "inlining": {"calls": dict(sorted(call_totals.items())), "function_size_buckets": dict(sorted(size_buckets.items())),
                     "threshold_samples": thresholds, "immediate_candidates": dict(sorted(inline_candidates.items())),
                     "first_scope": "intra-current-module, direct, nonrecursive, nonthrowing tiny callees only"},
        "scoring": {
            "memory_read_LICM": {"repository_candidates": "LOW", "hot_relevance": "MEDIUM", "LLVM_overlap": "HIGH", "complexity": "MEDIUM", "risk": "MEDIUM"},
            "ARC_optimization": {"repository_candidates": "MEDIUM", "hot_relevance": "LOW", "LLVM_overlap": "LOW", "complexity": "HIGH", "risk": "VERY_HIGH"},
            "inlining": {"repository_candidates": "MEDIUM", "hot_relevance": "MEDIUM", "LLVM_overlap": "HIGH", "complexity": "VERY_HIGH", "risk": "HIGH"}},
        "primary_recommendation": "IMPROVE_ANALYSIS_FIRST",
        "primary_scope": "field-sensitive memory locations plus ownership dataflow and exception-aware escape summaries; rerun this audit before enabling a transform",
        "secondary_recommendation": "Re-audit nontrapping invariant ArrayGet/ListGet after field-sensitive mod/ref; delegate ordinary direct inlining to LLVM meanwhile",
        "production_codegen_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = json.dumps(generate(root), indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(payload)
    else: print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
