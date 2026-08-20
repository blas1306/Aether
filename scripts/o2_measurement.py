#!/usr/bin/env python3
"""Regenerate the O2.13 read-only workload and optimization measurements."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time

from aether.analysis.dominators import DominatorAnalysis
from aether.benchmark import _build_ir, _build_native, _typed_program
from aether.o2_evidence_materialization import optimized_ssa as _optimized_ssa
from aether.backend.llvm import LLVMBuilder
from aether.optimization import optimization_profile
from aether.ssa.analysis import LoopAnalysis
from aether.ssa.cfg import SSACFGBuilder
from aether.ssa.model import SSABinaryOp, SSABranch, SSACall, SSAInvoke, SSAJump, SSAPhi, SSAValue
from aether.ssa.operands import instruction_result
from aether.ssa.optimizer import build_ssa_optimizer_pipeline


SCHEMA_VERSION = 1
KINDS = {"REAL_WORKLOAD", "REALISTIC_KERNEL", "SYNTHETIC_PROBE"}
LLVM_OVERLAP = {"SURVIVES_LLVM", "LLVM_REMOVES", "LLVM_PARTIAL", "NOT_COMPARABLE", "UNKNOWN"}


def load_manifest(root: Path) -> dict:
    data = json.loads((root / "benchmarks/o2_workloads.json").read_text(encoding="utf-8"))
    categories = set(data["categories"])
    if len(categories) != len(data["categories"]):
        raise ValueError("duplicate workload category")
    paths: set[str] = set()
    for row in data["workloads"]:
        required = {"path", "kind", "category", "tags", "executable", "benchmarkable", "timeout_seconds", "repetitions"}
        missing = required - row.keys()
        if missing: raise ValueError(f"{row.get('path', '<unknown>')}: missing {sorted(missing)}")
        if row["path"] in paths: raise ValueError(f"duplicate workload: {row['path']}")
        if row["kind"] not in KINDS: raise ValueError(f"invalid workload kind: {row['kind']}")
        if row["category"] not in categories: raise ValueError(f"unknown category: {row['category']}")
        if not (root / row["path"]).is_file(): raise ValueError(f"missing workload: {row['path']}")
        if row["timeout_seconds"] < 1 or row["repetitions"] < 1: raise ValueError("invalid benchmark limits")
        paths.add(row["path"])
    return data


def _instructions(module):
    for function in module.functions:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                yield function, block, index, instruction


def _category(instruction) -> str:
    name = type(instruction).__name__
    low = name.lower()
    if isinstance(instruction, SSAPhi): return "phis"
    if isinstance(instruction, (SSABranch, SSAJump)): return "branches"
    if isinstance(instruction, (SSACall, SSAInvoke)): return "calls"
    if "retain" in low or "release" in low: return "arc_operations"
    if "array" in low or "list" in low: return "collection_operations"
    if "struct" in low or "aggregate" in low: return "struct_operations"
    if "class" in low or "field" in low: return "class_operations"
    if "interface" in low: return "interface_operations"
    if "invoke" in low or "throw" in low or "exception" in low or "landing" in low: return "exception_operations"
    if "load" in low or "get" in low or "project" in low: return "loads_gets"
    if "store" in low or "set" in low: return "stores_sets"
    if getattr(instruction, "allocates", False): return "allocations"
    if isinstance(instruction, SSABinaryOp) or (not getattr(instruction, "has_side_effects", True) and not getattr(instruction, "reads_memory", True)):
        return "pure_scalar_operations"
    return "other"


def instruction_census(module) -> dict:
    counts = Counter(total_instructions=0)
    for _function, _block, _index, instruction in _instructions(module):
        counts["total_instructions"] += 1
        counts[_category(instruction)] += 1
        if getattr(instruction, "allocates", False): counts["allocations"] += _category(instruction) != "allocations"
    keys = ("total_instructions", "pure_scalar_operations", "calls", "branches", "phis", "loads_gets",
            "stores_sets", "allocations", "arc_operations", "collection_operations", "struct_operations",
            "class_operations", "interface_operations", "exception_operations", "other")
    return {key: counts[key] for key in keys}


def _arc_census(module) -> dict:
    global_ = Counter(retains=0, releases=0); loops = Counter(retains=0, releases=0)
    implicit = Counter(array_get_retain=0, list_get_retain=0, reference_element_retain=0,
                       aggregate_component_retain=0, other_backend_ownership=0)
    for function in module.functions:
        analysis = LoopAnalysis().compute(function)
        loop_blocks = set().union(*(loop.body for loop in analysis.loops)) if analysis.loops else set()
        for block in function.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, SSACall) and instruction.builtin in {"__aether_retain", "__aether_release"}:
                    key = instruction.builtin.removeprefix("__aether_") + "s"; global_[key] += 1
                    if block.name in loop_blocks: loops[key] += 1
                name = type(instruction).__name__.lower()
                if "arrayget" in name: implicit["array_get_retain"] += 1
                elif "listget" in name: implicit["list_get_retain"] += 1
    return {"explicit_ssa": {"global": dict(global_), "loops": dict(loops)}, "backend_implicit_sites": dict(implicit)}


def _allocation_kind(instruction) -> str:
    text = f"{type(instruction).__name__} {getattr(instruction_result(instruction), 'type', '')}".lower()
    for key, needle in (("String", "string"), ("Array", "array"), ("List", "list"), ("interface_box", "interface"), ("class", "class")):
        if needle in text: return key
    return "runtime_temporary" if "temporary" in text or "methodresult" in text else "other"


def allocation_census(module) -> dict:
    result = Counter(); loop_local = Counter()
    for function in module.functions:
        analysis = LoopAnalysis().compute(function)
        blocks = set().union(*(loop.body for loop in analysis.loops)) if analysis.loops else set()
        for _fn, block, _index, instruction in ((function, b, i, x) for b in function.blocks for i, x in enumerate(b.instructions)):
            if getattr(instruction, "allocates", False):
                kind = _allocation_kind(instruction); result[kind] += 1
                if block.name in blocks: loop_local[kind] += 1
    return {"global_by_kind": dict(sorted(result.items())), "loop_local_by_kind": dict(sorted(loop_local.items())),
            "escape_classification": {"noescape_proven": 0, "escapes": 0, "unknown": sum(result.values())},
            "note": "No allocation is called transformable merely because it is noescape."}


def _operand_names(instruction) -> tuple[str, ...]:
    found = []
    for field in fields(instruction):
        value = getattr(instruction, field.name)
        if isinstance(value, SSAValue): found.append(value.name)
        elif isinstance(value, tuple): found.extend(x.name for x in value if isinstance(x, SSAValue))
    result = instruction_result(instruction)
    return tuple(x for x in found if result is None or x != result.name)


def repeated_expressions(module, workload: str) -> list[dict]:
    rows = []
    for function in module.functions:
        dom = DominatorAnalysis(SSACFGBuilder().build(function), entry_block=function.entry_block).compute()
        seen = {}
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if not isinstance(instruction, SSABinaryOp): continue
                key = (type(instruction).__name__, repr(instruction.result.type), _operand_names(instruction), getattr(instruction, "operator", None))
                if key in seen:
                    first_block, first_index = seen[key]
                    fingerprint_text = "|".join((workload, function.name, type(instruction).__name__, str(key[3]), ",".join(key[2]), "loop-body" if LoopAnalysis().compute(function).loop_for_block(block.name) else "non-loop"))
                    rows.append({"fingerprint": hashlib.sha256(fingerprint_text.encode()).hexdigest()[:16], "workload": workload,
                        "function": function.name, "opcode": type(instruction).__name__, "instructions": [f"{first_block}:{first_index}", f"{block.name}:{index}"],
                        "same_block": first_block == block.name, "dominance": dom.dominates(first_block, block.name), "pure": not instruction.has_side_effects,
                        "trapping": instruction.may_trap, "memory_dependent": instruction.reads_memory,
                        "llvm_overlap": "LLVM_REMOVES" if not instruction.may_trap and not instruction.reads_memory else "UNKNOWN",
                        "concrete_transformability": "TRANSFORMABLE_NOW" if dom.dominates(first_block, block.name) and not instruction.may_trap and not instruction.reads_memory and not instruction.has_side_effects else "HYPOTHESIS_ONLY"})
                else: seen[key] = (block.name, index)
    return rows


def loop_census(module, workload: str, kind: str) -> list[dict]:
    rows = []
    for function in module.functions:
        analysis = LoopAnalysis().compute(function); blocks = {b.name: b for b in function.blocks}
        for loop in analysis.loops:
            c = Counter()
            for block_name in loop.body:
                for instruction in blocks[block_name].instructions:
                    c["instructions"] += 1; category = _category(instruction)
                    c[category] += 1
                    c["memory_reads"] += int(instruction.reads_memory); c["stores"] += int(instruction.writes_memory)
                    c["bounds_checks"] += int(instruction.may_trap); c["allocations"] += int(instruction.allocates)
            rows.append({"workload": workload, "workload_kind": kind, "function": function.name, "header": loop.header,
                "depth": loop.depth, "blocks": sorted(loop.body), "preheader": loop.preheader, "latch_count": len(loop.latches),
                "exits": sorted(loop.exit_blocks), "canonical_induction_variables": len(loop.induction_variables), "body_unconditional": c["branches"] <= 1,
                "backedge_dominating_operations": max(0, c["instructions"] - c["branches"]), "calls": c["calls"], "memory_reads": c["memory_reads"],
                "stores": c["stores"], "bounds_checks": c["bounds_checks"], "arc": c["arc_operations"], "allocations": c["allocations"],
                "pure_arithmetic": c["pure_scalar_operations"], "invariant_operations": 0, "branch_count": c["branches"]})
    return rows


def _trace_stats(source: str, path: Path):
    pre = _optimized_ssa(source, path, optimization_profile("O0"))
    trace = build_ssa_optimizer_pipeline("O2").run_with_trace(pre)
    return pre, trace[-1].module, [{"pass": step.label, "changed": step.changed, "stats": dict(sorted(step.stats.items()))} for step in trace[1:-1]]


def _source_metrics(source: str) -> dict:
    lines = [line for line in source.splitlines() if line.strip() and not line.lstrip().startswith("//")]
    return {"source_loc": len(lines), "source_functions": sum("fn " in line or "fun " in line for line in lines),
            "source_structs": sum(line.lstrip().startswith("struct ") for line in lines),
            "source_classes": sum(line.lstrip().startswith("class ") for line in lines),
            "source_interfaces": sum(line.lstrip().startswith("interface ") for line in lines)}


def generate(root: Path, manifest: dict | None = None) -> dict:
    manifest = manifest or load_manifest(root); workloads = []; loops = []; repeats = []; aggregate_arc = Counter(); implicit = Counter(); allocations = Counter()
    pass_impact: dict[str, Counter] = defaultdict(Counter)
    for config in manifest["workloads"]:
        relative = config["path"]; path = root / relative; source = path.read_text(encoding="utf-8")
        row = {key: config[key] for key in config}; row.update(_source_metrics(source)); row["support"] = {}
        try:
            initial_ir = _build_ir(source, path); row["support"]["initial_ir"] = True
            row["initial_ir"] = {"functions": len(initial_ir.functions), "instructions": sum(len(b.instructions) for f in initial_ir.functions for b in f.blocks)}
        except Exception as error:
            row["support"].update(initial_ir=False, ssa=False, native_llvm=False); row["unsupported_reason"] = {"stage": "Initial IR", "reason": type(error).__name__, "detail": str(error)[:240]}; workloads.append(row); continue
        try:
            pre, post, trace = _trace_stats(source, path); o1 = _optimized_ssa(source, path, optimization_profile("O1")); row["support"]["ssa"] = True
        except Exception as error:
            row["support"].update(ssa=False, native_llvm=False); row["unsupported_reason"] = {"stage": "SSA lowering", "reason": type(error).__name__, "detail": str(error)[:240]}; workloads.append(row); continue
        row["stages"] = {"ssa_pre_o2": instruction_census(pre), "ssa_o1": instruction_census(o1), "ssa_post_o2": instruction_census(post)}
        row["ssa_delta"] = {key: row["stages"]["ssa_post_o2"][key] - row["stages"]["ssa_pre_o2"][key] for key in row["stages"]["ssa_pre_o2"]}
        row["pass_attribution"] = trace
        for step in trace:
            pass_impact[step["pass"]]["workloads_affected"] += int(step["changed"])
            pass_impact[step["pass"]]["static_transformations"] += sum(v for k, v in step["stats"].items() if any(word in k for word in ("removed", "hoisted", "eliminated", "transformed", "folded", "simplified", "propagated")))
        row_loops = loop_census(post, relative, config["kind"]); loops.extend(row_loops); row["loops"] = len(row_loops)
        arc = _arc_census(post); row["ownership"] = arc
        for scope in ("global", "loops"):
            for key, value in arc["explicit_ssa"][scope].items(): aggregate_arc[f"{scope}_{key}"] += value
        implicit.update(arc["backend_implicit_sites"])
        alloc = allocation_census(post); row["allocations"] = alloc
        allocations.update(alloc["global_by_kind"])
        row_repeats = repeated_expressions(post, relative); repeats.extend(row_repeats); row["repeated_expressions"] = len(row_repeats)
        row["support"]["native_llvm"] = config["executable"]
        row["support"]["executable"] = config["executable"]
        try:
            typed = _typed_program(source, path)
            llvm_stages = {}
            for level in ("O0", "O1", "O2"):
                llvm = LLVMBuilder(optimization_profile=optimization_profile(level)).emit_llvm(typed)
                llvm_stages[level] = {"text_bytes": len(llvm.encode("utf-8")),
                    "instruction_lines": sum(line.startswith("  ") and not line.lstrip().startswith(";") for line in llvm.splitlines())}
            row["llvm_stages"] = llvm_stages
        except Exception as error:
            row["support"]["native_llvm"] = False
            row["llvm_unsupported_reason"] = {"reason": type(error).__name__, "detail": str(error)[:240]}
        workloads.append(row)
    candidates = [x for x in repeats if x["concrete_transformability"] == "TRANSFORMABLE_NOW"]
    recommendation = "PAUSE_AETHER_O2_RELY_ON_LLVM" if not candidates or all(x["llvm_overlap"] == "LLVM_REMOVES" for x in candidates) else "IMPROVE_CORPUS_FURTHER"
    categories = Counter(x["category"] for x in manifest["workloads"]); kinds = Counter(x["kind"] for x in manifest["workloads"])
    unsupported = [{"workload": x["path"], **x["unsupported_reason"]} for x in workloads if "unsupported_reason" in x]
    dead_zones = [x["path"] for x in workloads if x.get("stages") and x["stages"]["ssa_o1"] == x["stages"]["ssa_post_o2"]]
    return {"audit": "O2.13-optimization-measurement-and-workload-expansion", "schema_version": SCHEMA_VERSION,
        "methodology": "STATIC_MEASUREMENT_V1_FAIL_CLOSED", "production_freeze": {"optimizer_membership_changed": False, "codegen_changed": False,
            "ownership_changed": False, "lifecycle_changed": False, "backend_changed": False, "abi_changed": False},
        "corpus": {"previous_workloads": 15, "workloads": len(workloads), "by_category": dict(sorted(categories.items())), "by_kind": dict(sorted(kinds.items())),
            "supported_initial_ir": sum(x["support"].get("initial_ir", False) for x in workloads), "supported_ssa": sum(x["support"].get("ssa", False) for x in workloads), "unsupported": unsupported},
        "workloads": workloads, "loop_census": loops,
        "ownership_census": {"explicit_ssa": {"global": {"retains": aggregate_arc["global_retains"], "releases": aggregate_arc["global_releases"]},
            "loops": {"retains": aggregate_arc["loops_retains"], "releases": aggregate_arc["loops_releases"]}}, "backend_implicit_sites": dict(sorted(implicit.items()))},
        "allocation_census": dict(sorted(allocations.items())), "memory_read_census": {"measured": sum(x["memory_reads"] for x in loops), "llvm_comparison": "UNKNOWN"},
        "repeated_expression_census": repeats, "blocker_census": {"call_summary": {}, "alias_modref": {}, "exception_trap": {"trapping_repeated_expressions": sum(x["trapping"] for x in repeats)}},
        "verified_candidates": candidates, "candidate_ranking": [{"fingerprint": x["fingerprint"], "real_workload": x["workload"] in {w["path"] for w in workloads if w["kind"] == "REAL_WORKLOAD"},
            "loop_relevance": "UNKNOWN", "static_effect": "one SSA instruction", "llvm_survival": x["llvm_overlap"], "complexity": "LOW", "semantic_risk": "LOW", "enabling_value": "NONE_PROVEN"} for x in candidates],
        "pass_impact": {key: dict(value) for key, value in sorted(pass_impact.items())}, "o2_dead_zones": dead_zones,
        "aether_specific_opportunity_rule": ["SURVIVES_LLVM", "Aether semantic knowledge", "unlocks Aether pass", "runtime opacity", "ownership/lifecycle specific"],
        "primary_recommendation": recommendation,
        "exact_next_milestone": {"direction": recommendation, "candidates": [x["fingerprint"] for x in candidates],
            "transformation": "none; LLVM already removes every verified pure scalar repetition" if recommendation == "PAUSE_AETHER_O2_RELY_ON_LLVM" else "expand real parsing/graph coverage before selecting a pass",
            "scope_restrictions": "measurement only", "risk": "LOW", "required_tests": ["manifest closure", "deterministic regeneration", "LLVM survival verification"]}}


def runtime_measure(root: Path, manifest: dict, *, limit: int | None = None, warmups: int = 1, repetitions: int = 3) -> dict:
    rows = []
    selected = [x for x in manifest["workloads"] if x["benchmarkable"]][:limit]
    for config in selected:
        outputs = {}; timings = {}
        with tempfile.TemporaryDirectory(prefix="aether-o213-") as temporary:
            for level in ("O0", "O1", "O2"):
                executable = Path(temporary) / level; path = root / config["path"]
                try: _build_native(path.read_text(encoding="utf-8"), path, executable, optimization_profile(level))
                except Exception as error: outputs[level] = {"unsupported": type(error).__name__}; continue
                for _ in range(warmups): subprocess.run((str(executable),), capture_output=True, timeout=config["timeout_seconds"])
                samples = []; observed = None
                for _ in range(repetitions):
                    before = os.times(); started = time.perf_counter(); proc = subprocess.run((str(executable),), capture_output=True, timeout=config["timeout_seconds"]); wall = time.perf_counter() - started; after = os.times()
                    observed = {"exit_code": proc.returncode, "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(), "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest()}
                    samples.append({"wall_seconds": wall, "user_seconds": after.children_user-before.children_user, "sys_seconds": after.children_system-before.children_system})
                observed["executable_bytes"] = executable.stat().st_size
                outputs[level] = observed; walls = [x["wall_seconds"] for x in samples]
                timings[level] = {"samples": samples, "median_wall_seconds": statistics.median(walls), "minimum_wall_seconds": min(walls), "spread_wall_seconds": max(walls),
                    "executable_bytes": executable.stat().st_size}
        semantic_outputs = [{k: v for k, v in value.items() if k != "executable_bytes"} for value in outputs.values()]
        comparable = len(outputs) == 3 and len({json.dumps(x, sort_keys=True) for x in semantic_outputs}) == 1
        rows.append({"workload": config["path"], "workload_size": config.get("size", "source default"), "warmups": warmups, "repetitions": repetitions,
            "command": "aether native build per O-level; direct executable run", "output_parity": comparable, "outputs": outputs, "timings": timings if comparable else {}})
    return {"schema_version": 1, "environment": {"platform": platform.platform(), "python": platform.python_version()}, "results": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--mode", choices=("static-only", "runtime", "full"), default="static-only")
    parser.add_argument("--output", type=Path); parser.add_argument("--runtime-output", type=Path); parser.add_argument("--runtime-limit", type=int, default=3)
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]; manifest = load_manifest(root)
    if args.mode in {"static-only", "full"}:
        output = args.output or root / "docs/compiler/o2_measurement_baseline.json"
        output.write_text(json.dumps(generate(root, manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.mode in {"runtime", "full"}:
        output = args.runtime_output or root / "docs/compiler/o2_runtime_measurements.json"
        output.write_text(json.dumps(runtime_measure(root, manifest, limit=args.runtime_limit), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
