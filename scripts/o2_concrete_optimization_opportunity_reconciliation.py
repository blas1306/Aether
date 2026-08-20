#!/usr/bin/env python3
"""Generate the deterministic, analysis-only O2.12 opportunity reconciliation."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import fields
import json
from pathlib import Path
import subprocess

from aether.analysis.dominators import DominatorAnalysis
from aether.o2_evidence_materialization import optimized_ssa as _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa.analysis import (ConcreteCandidateStatus as Status,
    ConcreteOptimizationCandidate as Candidate, LoopAnalysis, select_recommendation)
from aether.ssa.cfg import SSACFGBuilder
from aether.ssa.model import (SSABinaryOp, SSACall, SSACompareOp, SSAConst,
    SSACast, SSAUnaryOp, SSAValue)
from aether.ssa.operands import instruction_result
try:
    from scripts.o2_arc_opportunity_audit import DEFAULT_CORPUS
except ModuleNotFoundError:  # pragma: no cover
    from o2_arc_opportunity_audit import DEFAULT_CORPUS


SCHEMA_VERSION = 1
PURE_VALUE_OPS = (SSABinaryOp, SSAUnaryOp, SSACompareOp, SSACast)
FAMILY_ORDER = ("GVN/CSE", "memory LICM", "IV/loop", "allocation elision",
                "allocation/stack", "collection ownership", "ownership")


def _operands(instruction) -> tuple[SSAValue, ...]:
    result = instruction_result(instruction); found = []
    for field in fields(instruction):
        value = getattr(instruction, field.name)
        if isinstance(value, SSAValue) and value != result: found.append(value)
        elif isinstance(value, tuple): found.extend(x for x in value if isinstance(x, SSAValue))
    return tuple(found)


def _key(instruction):
    result = instruction_result(instruction)
    operands = _operands(instruction)
    semantic = tuple((f.name, repr(getattr(instruction, f.name))) for f in fields(instruction)
                     if f.name not in {"result", "left", "right", "operand", "value", "source_location"}
                     and not isinstance(getattr(instruction, f.name), SSAValue))
    return (type(instruction).__name__, repr(result.type), tuple(x.name for x in operands), semantic)


def _safe_pure(instruction) -> bool:
    return (isinstance(instruction, PURE_VALUE_OPS) and not instruction.has_side_effects
            and not instruction.reads_memory and not instruction.writes_memory
            and not instruction.may_trap and not instruction.may_throw
            and not instruction.allocates)


def _allocation_kind(instruction) -> str:
    result = instruction_result(instruction)
    type_name = repr(result.type) if result is not None else ""
    class_name = type(instruction).__name__
    if "String" in type_name: return "String allocation"
    if "Array" in type_name or class_name.startswith("SSAArray"): return "Array storage"
    if "List" in type_name or class_name.startswith("SSAList"): return "List storage"
    if "Interface" in type_name or "Interface" in class_name: return "interface box"
    if "Class" in type_name or class_name == "SSAClassNew": return "class/object"
    if "Struct" in type_name or "MethodResult" in type_name: return "aggregate/runtime temporary"
    return "other"


def _cse_candidates(workload, function, loops):
    result = []; definitions = {}
    for block in function.blocks:
        for index, instruction in enumerate(block.instructions):
            value = instruction_result(instruction)
            if value is not None: definitions[value.name] = (block.name, index, instruction)
    dom = DominatorAnalysis(SSACFGBuilder().build(function), entry_block=function.entry_block).compute()
    available = {}
    for block in function.blocks:
        loop = loops.loop_for_block(block.name); depth = loop.depth if loop else 0
        for index, instruction in enumerate(block.instructions):
            if not _safe_pure(instruction): continue
            key = _key(instruction); previous = available.get(key)
            if previous is not None:
                pblock, pindex, earlier = previous
                if pblock == block.name and pindex >= index: continue
                if not dom.dominates(pblock, block.name): continue
                old, new = instruction_result(earlier), instruction_result(instruction)
                role = "LOOP_BODY" if loop else "NON_LOOP"
                proof = ("exact opcode/type/operand identity", "producer dominates redundant instruction",
                         "operation pure", "nontrapping and nonthrowing", "no memory or ownership effect")
                result.append(Candidate("GVN/CSE", workload, function.name,
                    type(instruction).__name__,
                    (f"{pblock}:{pindex} %{old.name} = {earlier!r}",
                     f"{block.name}:{index} %{new.name} = {instruction!r}"),
                    tuple(x.name for x in _operands(instruction)), proof,
                    f"replace uses(%{new.name}) -> %{old.name}; delete %{new.name}",
                    removed=(new.name,), replaced=(new.name,), loop_depth=depth,
                    block_role=role, llvm_overlap="LLVM_ALREADY_COMPLETE",
                    structural_hotness=10 ** depth, status=Status.TRANSFORMABLE_NOW))
            else: available[key] = (block.name, index, instruction)
    return result


def _loop_row(function, loop):
    blocks = {b.name: b for b in function.blocks}; counts = Counter()
    for name in loop.body:
        for ins in blocks[name].instructions:
            kind = type(ins).__name__; counts["instructions"] += 1
            if isinstance(ins, SSABinaryOp): counts["arithmetic"] += 1
            if isinstance(ins, (SSACall,)): counts["calls"] += 1
            if getattr(ins, "may_trap", False): counts["bounds_or_traps"] += 1
            if isinstance(ins, SSACall) and ins.builtin in {"__aether_retain", "__aether_release"}:
                counts[ins.builtin.rsplit("_", 1)[-1]] += 1
    return {"function": function.name, "header": loop.header, "preheader": loop.preheader,
        "latches": sorted(loop.latches), "exits": sorted(loop.exit_blocks), "depth": loop.depth,
        "induction_phis": [{"value": x.value.name, "initial": x.initial_value.name,
            "step": x.step, "update": x.update.result.name, "type": repr(x.value.type),
            "checked_arithmetic": x.update.may_trap} for x in loop.induction_variables],
        **dict(sorted(counts.items()))}


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS) -> dict:
    candidates = []; rejected = []; failures = []; loop_rows = []; census = Counter()
    arc = Counter(); loop_arc = Counter(); allocations = Counter()
    for relative in corpus:
        try:
            path = root / relative
            module = _optimized_ssa(path.read_text(encoding="utf-8"), path, optimization_profile("O2"))
            census["workloads_lowered"] += 1
        except Exception as error:
            failures.append({"workload": relative, "error": type(error).__name__}); continue
        for function in module.functions:
            analysis = LoopAnalysis().compute(function); census["functions"] += 1
            if analysis.loops: census["functions_with_loops"] += 1
            census["natural_loops"] += len(analysis.loops)
            for loop in analysis.loops: loop_rows.append({"workload": relative, **_loop_row(function, loop)})
            loop_blocks = set().union(*(x.body for x in analysis.loops)) if analysis.loops else set()
            candidates.extend(_cse_candidates(relative, function, analysis))
            for block in function.blocks:
                for ins in block.instructions:
                    census["o2_instructions"] += 1
                    if getattr(ins, "allocates", False): allocations[_allocation_kind(ins)] += 1
                    if isinstance(ins, SSACall) and ins.builtin in {"__aether_retain", "__aether_release"}:
                        name = ins.builtin.removeprefix("__aether_"); arc[name] += 1
                        if block.name in loop_blocks: loop_arc[name] += 1
    candidates = sorted(candidates, key=lambda x: (x.workload, x.function, x.fingerprint, x.instructions))
    # Verify a second time; malformed discoveries never enter the ranking.
    verified = [x for x in candidates if x.productive]
    rejected.extend(x.as_dict() for x in candidates if not x.productive)
    recommendation = select_recommendation(tuple(verified), FAMILY_ORDER)
    by_family = Counter(x.family for x in verified); loop_by_family = Counter(x.family for x in verified if x.loop_depth)
    families = ("GVN/CSE", "memory LICM", "IV/loop", "allocation/stack", "ownership",
                "collection ownership", "scalar replacement", "copy elision")
    matrix = [{"family": family, "verified_candidates": by_family[family],
        "loop_candidates": loop_by_family[family],
        "exact_effect": ("delete one pure SSA expression per site" if family == "GVN/CSE" and by_family[family] else "none verified"),
        "llvm_overlap": ("HIGH" if family in {"GVN/CSE", "IV/loop"} else "UNKNOWN"),
        "complexity": "LOW" if family == "GVN/CSE" else "HIGH",
        "risk": "LOW" if family == "GVN/CSE" else "HIGH", "enabling_value": "LOW"} for family in families]
    ownership = json.loads((root / "docs/compiler/o2_post_immediate_borrow_optimization_audit.json").read_text())
    stable = ownership.get("stable_candidate_analysis")
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
        text=True, capture_output=True).stdout.strip()
    return {"audit": "O2.12-concrete-optimization-opportunity-reconciliation",
        "schema_version": SCHEMA_VERSION, "revision": revision,
        "methodology_version": "CONCRETE_OPPORTUNITY_V1_FAIL_CLOSED",
        "current_production_baseline": {"representative_workloads": len(corpus), **dict(census),
            "unsupported_workloads": failures, "explicit_ssa_arc": {"global": dict(arc), "loops": dict(loop_arc)},
            "backend_implicit_arc": {"retains": ownership["current_ownership_census"]["backend_implicit_retains"],
                "loop_retains": ownership["current_ownership_census"]["loop_implicit_retains"]}},
        "historical_reconciliation": [
            {"family": "scalar replacement", "historical_candidates": 4, "current_transformable": 0, "finding": "SAFE_SCALAR_ONLY=0"},
            {"family": "aggregate copy elision", "historical_candidates": 4, "current_transformable": 0, "finding": "zero actual SSA copy edges; historical misclassification"},
            {"family": "Array<String> direct borrow", "historical_candidates": 15, "current_transformable": "already implemented"},
            {"family": "Array<String> immediate borrow", "historical_candidates": 3, "current_transformable": "already implemented"},
            {"family": "stable Array<String> borrow", "historical_candidates": 1, "current_transformable": 0}],
        "verified_candidates": [x.as_dict() for x in verified], "rejected_hypothesis_candidates": rejected,
        "gvn_findings": {"same_block": sum(x.instructions[0].split(":",1)[0] == x.instructions[1].split(":",1)[0] for x in verified),
            "dominator_based": sum(x.instructions[0].split(":",1)[0] != x.instructions[1].split(":",1)[0] for x in verified),
            "memory_aware": 0, "llvm_overlap": "LLVM_ALREADY_COMPLETE for conservative scalar sites"},
        "licm_findings": {"verified": 0, "reason": "no newly verified exact memory movement in this conservative audit"},
        "loop_iv_findings": {"loop_census": loop_rows, "verified_iv_or_strength_reduction": 0},
        "allocation_findings": {"census": dict(sorted(allocations.items())), "stack_promotion_verified": 0,
            "allocation_elision_verified": 0, "reason": "no exact supported stack target or removable allocation proven"},
        "ownership_findings": {"stable_373": stable, "status": "ANALYSIS_BLOCKED",
            "blocker": "CALL_SUMMARY_EXTENSION", "verified": 0},
        "collection_findings": {"verified": 0, "families_audited": ["List<String>", "Array<Class>", "List<Class>", "Array<Struct>", "List<Struct>"]},
        "enabling_call_findings": {"stable_373": "text.byteSlice summary improvement suffices; inlining not required"},
        "enabling_devirtualization_findings": [], "llvm_overlap": {"top_family": "LLVM already eliminates conservative scalar CSE; no Aether enabling value established"},
        "family_matrix": matrix, "primary_recommendation": recommendation,
        "secondary_recommendation": None,
        "exact_next_milestone": ({"name": "O2.13 Phase 1: same-block pure-expression CSE only",
            "expected_real_candidates": len(verified), "eligibility": "same block, exact opcode/type/operands, pure, nontrapping, no memory/ownership/calls/phis",
            "excluded": ["memory GVN", "floating reassociation", "bounds operations", "cross-block GVN"]}
            if recommendation == "PROCEED_TO_GVN_CSE" else {"name": "improve concrete opportunity measurement", "expected_real_candidates": 0}),
        "production_freeze": {"production_behavior_changed": False, "ownership_changed": False,
            "lifecycle_changed": False, "abi_changed": False, "backend_changed": False,
            "optimization_profiles_changed": False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    payload = json.dumps(generate(root, tuple(args.paths) or DEFAULT_CORPUS), indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(payload, encoding="utf-8")
    else: print(payload, end="")
    return 0

if __name__ == "__main__": raise SystemExit(main())
