#!/usr/bin/env python3
"""Generate the deterministic, read-only O2.8.5 ARC opportunity audit.

The audit deliberately consumes lifecycle-expanded SSA.  It never runs an ARC
rewrite and is therefore safe to use as a regression/measurement gate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from aether.benchmark import _optimized_ssa
from aether.optimization import optimization_profile
from aether.ir.types import InterfaceType, MethodResultType, StructType, StringType
from aether.ssa.analysis import ArcPairClassification, LoopAnalysis, OwnershipEscapeAnalysis
from aether.ssa.model import SSACall, SSAInvoke


DEFAULT_CORPUS = (
    "examples/classes/counter_basic.ae",
    "examples/classes/custom_constructor.ae",
    "examples/classes/implements_interface.ae",
    "examples/structs/custom_constructor_and_equality.ae",
    "examples/aggregate_collections/particles.ae",
    "examples/llvm/array_sum.ae",
    "examples/llvm/list_for_sum.ae",
    "examples/expense_tracker/Main.ae",
    "examples/numerical_methods/main.ae",
    "examples/nonlinear_systems/newton_system.ae",
    "examples/probandoNR.ae",
    "tests/aether/parity_corpus/strings.ae",
    "corpus/exceptions/positive/owned_aggregates_arc.ae",
    "corpus/exceptions/positive/constructor_failure.ae",
    "corpus/exceptions/positive/method_interface_dispatch.ae",
)


def _loop_depths(function) -> dict[str, int]:
    depths: Counter[str] = Counter()
    for loop in LoopAnalysis().compute(function).loops:
        for name in loop.body:
            depths[name] += 1
    return dict(depths)


def _tags(path: str) -> list[str]:
    low = path.lower()
    tags = [name for name, needle in (
        ("CLASS", "class"), ("STRUCT", "struct"), ("COLLECTION", "collection"),
        ("STRING", "string"), ("INTERFACE", "interface"),
        ("CONSTRUCTOR", "constructor"), ("EXCEPTION", "exception"),
        ("NUMERICAL", "numerical"), ("PROBANDO_NR", "probandonr"),
        ("EXPENSE_TRACKER", "expense"),
    ) if needle in low]
    return tags or ["GENERAL"]


def _context(function, value, retain_block: str, release_block: str) -> str:
    type_ = value.type
    name = function.name.lower()
    blocks = {b.name: b for b in function.blocks}
    region = blocks[retain_block].instructions
    if retain_block != release_block:
        region = (*region, *blocks[release_block].instructions)
    if "constructor" in name or name.endswith(".__init__"):
        return "CONSTRUCTOR_LIFECYCLE"
    if isinstance(type_, MethodResultType) or any("MethodResult" in type(i).__name__ for i in region):
        return "METHODRESULT"
    if isinstance(type_, InterfaceType) or any("Interface" in type(i).__name__ for i in region):
        return "INTERFACE_BOX"
    if isinstance(type_, StructType):
        return "NESTED_AGGREGATE"
    if any(getattr(i, "may_throw", False) or isinstance(i, SSAInvoke) for i in region):
        return "EXCEPTION"
    return "LOCAL"


def _classification(pair, context: str) -> str:
    # O2.8's generic exact-value pairing cannot describe ownership of these
    # packaging constructs yet.  They remain opportunities, never proofs.
    if context == "METHODRESULT": return "BLOCKED_METHODRESULT"
    if context == "CONSTRUCTOR_LIFECYCLE": return "BLOCKED_CONSTRUCTOR_LIFECYCLE"
    if context == "NESTED_AGGREGATE": return "BLOCKED_NESTED_AGGREGATE"
    if context == "INTERFACE_BOX": return "BLOCKED_INTERFACE_BOX"
    if pair.classification is ArcPairClassification.LOCALLY_PROVABLE:
        return "PROVABLE_NOW"
    if pair.classification is ArcPairClassification.BLOCKED_BY_EXCEPTION:
        return "BLOCKED_EXCEPTION_JOIN"
    if pair.classification is ArcPairClassification.NEEDS_PATH_SENSITIVE_OWNERSHIP:
        return "BLOCKED_NORMAL_JOIN"
    if pair.classification is ArcPairClassification.BLOCKED_BY_ALIAS:
        return "BLOCKED_ALIAS_UNKNOWN"
    if pair.classification is ArcPairClassification.NEEDS_ESCAPE_INFO:
        return "BLOCKED_ESCAPE_UNKNOWN"
    return "NOT_REDUNDANT"


def _safe_same_block(function, pair) -> bool:
    if pair.retain_block != pair.release_block: return False
    block = next(b for b in function.blocks if b.name == pair.retain_block)
    between = block.instructions[pair.retain_index + 1:pair.release_index]
    return not any(isinstance(i, (SSACall, SSAInvoke)) or i.has_side_effects or
                   i.writes_memory or i.may_throw for i in between)


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    counts, loop_counts, lifecycle, blockers, contexts, escape_reasons = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    candidates, workloads, failures = [], [], []
    same_block = straight_line = exception_free = 0
    for relative in corpus:
        path = root / relative
        try:
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path, optimization_profile("O2"))
            local = Counter()
            for function in module.functions:
                depths = _loop_depths(function)
                analysis = OwnershipEscapeAnalysis(function)
                for block in function.blocks:
                    for index, instruction in enumerate(block.instructions):
                        instruction_name = type(instruction).__name__
                        if "Destroy" in instruction_name: lifecycle["destroy"] += 1
                        elif "Move" in instruction_name or "Relocate" in instruction_name: lifecycle["move_or_consume"] += 1
                        elif "MethodResult" in instruction_name: lifecycle["method_result"] += 1
                        elif "Interface" in instruction_name and "Call" not in instruction_name: lifecycle["interface_box_or_carrier"] += 1
                        elif "Exception" in instruction_name or instruction_name in {"SSAThrow", "SSARethrow", "SSAPropagate"}: lifecycle["exception_payload_or_event"] += 1
                        if not isinstance(instruction, (SSACall, SSAInvoke)): continue
                        if instruction.builtin not in {"__aether_retain", "__aether_release"}: continue
                        kind = instruction.builtin.removeprefix("__aether_")
                        counts[kind] += 1; local[kind] += 1
                        depth = depths.get(block.name, 0)
                        if depth: loop_counts[kind] += 1
                for pair in analysis.candidate_arc_pairs():
                    context = _context(function, pair.value, pair.retain_block, pair.release_block)
                    classification = _classification(pair, context)
                    depth = max(depths.get(pair.retain_block, 0), depths.get(pair.release_block, 0))
                    safe = classification == "PROVABLE_NOW"
                    same = safe and _safe_same_block(function, pair)
                    multi = safe and pair.retain_block != pair.release_block
                    has_exception = pair.classification is ArcPairClassification.BLOCKED_BY_EXCEPTION
                    same_block += int(same); straight_line += int(multi); exception_free += int(safe and not has_exception)
                    blockers[classification] += 1; contexts[context] += 1
                    for reason in pair.reasons: escape_reasons[reason.value] += 1
                    candidates.append({
                        "workload": relative, "workload_kind": "REAL_WORKLOAD",
                        "function": function.name, "value": pair.value.name,
                        "retain": f"{pair.retain_block}:{pair.retain_index}",
                        "release": f"{pair.release_block}:{pair.release_index}",
                        "classification": classification, "context": context,
                        "loop_depth": depth, "relevance": "HIGH" if depth > 1 else "MEDIUM" if depth == 1 else "LOW",
                        "unknown_reasons": sorted(reason.value for reason in pair.reasons),
                    })
            workloads.append({"path": relative, "tags": _tags(relative), **dict(sorted(local.items()))})
        except Exception as error:
            failures.append({"path": relative, "error": type(error).__name__, "message": str(error)[:200]})
    candidates.sort(key=lambda x: (x["workload"], x["function"], x["retain"], x["release"]))
    provable = blockers["PROVABLE_NOW"]
    deltas = {
        "constructor_methodresult": blockers["BLOCKED_CONSTRUCTOR_LIFECYCLE"] + blockers["BLOCKED_METHODRESULT"],
        "nested_aggregate": blockers["BLOCKED_NESTED_AGGREGATE"],
        "normal_join": blockers["BLOCKED_NORMAL_JOIN"],
        "exceptional_join": blockers["BLOCKED_EXCEPTION_JOIN"],
    }
    ranked = max(deltas, key=lambda key: (deltas[key], key))
    if provable:
        recommendation = "PROCEED_TO_LOCAL_ARC_ELIMINATION"
        expected = provable
    elif ranked == "constructor_methodresult" and deltas[ranked]:
        recommendation = "IMPROVE_CONSTRUCTOR_METHODRESULT_OWNERSHIP"; expected = deltas[ranked]
    elif ranked == "nested_aggregate" and deltas[ranked]:
        recommendation = "IMPROVE_NESTED_AGGREGATE_OWNERSHIP"; expected = deltas[ranked]
    elif deltas["normal_join"] + deltas["exceptional_join"]:
        recommendation = "IMPROVE_OWNERSHIP_JOIN_PRECISION"; expected = deltas["normal_join"] + deltas["exceptional_join"]
    else:
        recommendation = "DEFER_ARC_OPTIMIZATION"; expected = 0
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
                              text=True, capture_output=True).stdout.strip()
    return {
        "audit": "O2.8.5", "schema_version": 1, "corpus_revision": revision,
        "methodology": "read-only lifecycle-expanded O2 SSA census with exact-identity O2.8 pairing and complete CFG post-dominance",
        "corpus": list(corpus), "corpus_failures": failures, "workloads": workloads,
        "arc_counts": {"initial_ir": {"retain": 0, "release": 0},
                       "lifecycle_expanded_ir": dict(sorted(counts.items())),
                       "ssa": dict(sorted(counts.items())),
                       "llvm": {"classification": "LLVM_CANNOT_SEE_OWNERSHIP", "source_operations": sum(counts.values())}},
        "lifecycle_operations": dict(sorted(lifecycle.items())),
        "loop_arc": dict(sorted(loop_counts.items())), "candidate_count": len(candidates),
        "candidate_classifications": dict(sorted(blockers.items())), "candidates": candidates,
        "blocker_reasons": dict(sorted(escape_reasons.items())), "contexts": dict(sorted(contexts.items())),
        "local_readiness": {"same_block": same_block, "straight_line_multi_block": straight_line,
                            "after_exception_region_exclusion": exception_free},
        "precision_deltas": deltas,
        "precision_scorecard": [
            {"area": area, "current_precision": "coarse", "blocked_candidates": count,
             "potential_unlocked": count, "risk": "HIGH" if area == "exceptional_join" else "MEDIUM",
             "implementation_cost": "HIGH" if area in {"nested_aggregate", "exceptional_join"} else "MEDIUM"}
            for area, count in deltas.items()
        ] + [{"area": "call_summaries", "current_precision": "direct-known/indirect-conservative",
              "blocked_candidates": blockers["BLOCKED_CALL_SUMMARY"], "potential_unlocked": blockers["BLOCKED_CALL_SUMMARY"],
              "risk": "MEDIUM", "implementation_cost": "MEDIUM"},
             {"area": "interface_boxes", "current_precision": "carrier-only/coarse box",
              "blocked_candidates": blockers["BLOCKED_INTERFACE_BOX"], "potential_unlocked": blockers["BLOCKED_INTERFACE_BOX"],
              "risk": "HIGH", "implementation_cost": "HIGH"}],
        "recommendation": recommendation, "expected_unlock_count": expected,
        "production_codegen_changed": False, "arc_changed": False, "optimization_profiles_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    report = generate(root, tuple(args.paths) or DEFAULT_CORPUS)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    else: print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
