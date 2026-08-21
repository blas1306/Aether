#!/usr/bin/env python3
"""TEST-PERF-3.1: observational profile of O2.13 pre-LLVM materialization."""
from __future__ import annotations

import argparse
import cProfile
from collections import Counter, defaultdict
from dataclasses import fields, is_dataclass
import io
import json
from pathlib import Path
import platform
import pstats
import time

from aether.backend.llvm import LLVMBackend
from aether.backend.llvm.build import _has_native_entry_point
from aether.capabilities import BackendIdentity, validate_backend_capabilities
from aether.ir.lifecycle import expand_lifecycle
from aether.ir.optimizer import build_optimizer_pipeline
from aether.optimization import optimization_profile
from aether.pipeline import IRBackend, SSAPipeline
from aether.ssa import SSAVerifier
from aether.ssa.optimizer import build_ssa_optimizer_pipeline
from aether.typechecker import TypeChecker
from aether import pipeline

try:
    from scripts.o2_measurement import load_manifest
except ModuleNotFoundError:
    from o2_measurement import load_manifest


LEVELS = ("O0", "O1", "O2")
STAGES = (
    "source_loading", "lexing_parsing_ast", "semantic_type_analysis",
    "initial_ir_lowering", "initial_ir_verification", "lifecycle_expansion",
    "ir_optimization", "post_ir_verification", "ssa_construction",
    "initial_ssa_verification", "optimizer_pipeline_construction",
    "ssa_optimization", "post_optimization_verification", "llvm_backend_emit",
)


def _measure(action):
    started = time.perf_counter()
    value = action()
    return value, time.perf_counter() - started


def _graph_count(value: object) -> int:
    """Count AST dataclass nodes without following checker/runtime objects."""
    seen: set[int] = set()
    def visit(item: object) -> int:
        if item is None or isinstance(item, (str, bytes, int, float, bool)):
            return 0
        if isinstance(item, (tuple, list)):
            return sum(visit(x) for x in item)
        if not is_dataclass(item) or item.__class__.__module__ != "aether.ast":
            return 0
        identity = id(item)
        if identity in seen:
            return 0
        seen.add(identity)
        return 1 + sum(visit(getattr(item, field.name)) for field in fields(item))
    return visit(value)


def _module_metrics(module) -> dict[str, int]:
    return {
        "functions": len(module.functions),
        "blocks": sum(len(fn.blocks) for fn in module.functions),
        "instructions": sum(len(block.instructions) for fn in module.functions for block in fn.blocks),
    }


def _profile_stats(action) -> list[dict]:
    profiler = cProfile.Profile()
    profiler.runcall(action)
    stats = pstats.Stats(profiler, stream=io.StringIO()).strip_dirs().sort_stats("cumulative")
    rows = []
    for (filename, line, function), (primitive, calls, own, cumulative, _callers) in stats.stats.items():
        rows.append({"function": f"{filename}:{line}({function})", "calls": calls,
                     "primitive_calls": primitive, "own_seconds": own,
                     "cumulative_seconds": cumulative})
    return sorted(rows, key=lambda row: row["cumulative_seconds"], reverse=True)[:20]


def _materialize(typed, level: str, *, emit: bool = True) -> tuple[dict, object]:
    profile = optimization_profile(level)
    timings = {name: 0.0 for name in STAGES}
    counts = Counter()
    pass_seconds: Counter[str] = Counter()
    backend = IRBackend()

    ir, timings["initial_ir_lowering"] = _measure(lambda: backend.lower(typed)); counts["initial_ir_lowering"] += 1
    initial_ir = _module_metrics(ir)
    ir, timings["initial_ir_verification"] = _measure(lambda: backend.verify(ir)); counts["initial_ir_verifier"] += 1
    if profile.ir_passes:
        ir, timings["lifecycle_expansion"] = _measure(lambda: expand_lifecycle(ir)); counts["lifecycle_expansion"] += 1
        optimizer, construction = _measure(lambda: build_optimizer_pipeline(profile))
        timings["optimizer_pipeline_construction"] += construction; counts[f"optimizer_pipeline_build_{level}"] += 1
        original = optimizer._run_pass
        def measured_pass(opt_pass, module):
            result, elapsed = _measure(lambda: original(opt_pass, module))
            pass_seconds[f"IR/{type(opt_pass).__name__}"] += elapsed
            return result
        optimizer._run_pass = measured_pass
        ir, timings["ir_optimization"] = _measure(lambda: optimizer.run(ir)); counts[f"ir_optimizer_run_{level}"] += 1
        ir, timings["post_ir_verification"] = _measure(lambda: backend.verify(ir)); counts["initial_ir_verifier"] += 1

    ssa_pipeline = SSAPipeline()
    ssa, timings["ssa_construction"] = _measure(lambda: ssa_pipeline.build(ir)); counts["ssa_build"] += 1
    ssa, timings["initial_ssa_verification"] = _measure(lambda: ssa_pipeline.verify(ssa)); counts["ssa_verifier"] += 1
    base_ssa = _module_metrics(ssa)
    optimizer, construction = _measure(lambda: build_ssa_optimizer_pipeline(profile, verify_after_each=True))
    timings["optimizer_pipeline_construction"] += construction; counts[f"optimizer_pipeline_build_{level}"] += 1
    original = optimizer._run_pass
    def measured_ssa_pass(opt_pass, module):
        result, elapsed = _measure(lambda: original(opt_pass, module))
        pass_seconds[f"SSA/{type(opt_pass).__name__}"] += elapsed
        return result
    optimizer._run_pass = measured_ssa_pass
    before_verify = Counter()
    original_verify = optimizer._verify
    def measured_verify(module, stage):
        result, elapsed = _measure(lambda: original_verify(module, stage))
        before_verify["calls"] += 1; before_verify["seconds"] += elapsed
        return result
    optimizer._verify = measured_verify
    ssa, timings["ssa_optimization"] = _measure(lambda: optimizer.run(ssa)); counts[f"ssa_optimizer_run_{level}"] += 1
    counts["ssa_verifier"] += int(before_verify["calls"])
    timings["ssa_optimizer_embedded_verification"] = before_verify["seconds"]
    ssa, timings["post_optimization_verification"] = _measure(lambda: SSAVerifier(ssa).verify()); counts["ssa_verifier"] += 1
    if emit:
        _llvm, timings["llvm_backend_emit"] = _measure(
            lambda: LLVMBackend().emit(ssa, native_entry=_has_native_entry_point(typed)))
        counts["llvm_backend_emit"] += 1
    total = sum(timings[name] for name in STAGES)
    return ({"profile": level, "initial_ir": initial_ir, "base_ssa": base_ssa,
             "final_ssa": _module_metrics(ssa), "timings_seconds": timings,
             "operation_counts": dict(counts), "optimizer_pass_seconds": dict(pass_seconds),
             "total_materialization_seconds": total,
             "pre_llvm_seconds": total - timings["llvm_backend_emit"]}, ssa)


def profile(root: Path, *, workload_limit: int | None = None,
            include_cprofile: bool = True, progress: bool = False) -> tuple[dict, dict]:
    configs = load_manifest(root)["workloads"]
    if workload_limit is not None:
        configs = configs[:workload_limit]
    records, unsupported = [], []
    cprofile_targets: dict[str, tuple[object, str]] = {}
    aggregate_counts = Counter(); aggregate_stages = Counter(); aggregate_passes = Counter()
    started_all = time.perf_counter()
    for index, config in enumerate(configs, 1):
        relative = config["path"]; path = root / relative
        if progress:
            print(f"[{index}/{len(configs)}] {relative}", flush=True)
        try:
            source, load_seconds = _measure(lambda: path.read_text(encoding="utf-8"))
            checker = TypeChecker(source_root=path.parent, entry_path=path)
            program, parse_seconds = _measure(lambda: pipeline.parse_source(source))
            def finish_frontend():
                checked = pipeline.typecheck_program(program, checker)
                semantic = pipeline.build_checked_program(checked, checker)
                normalized = pipeline.normalize_entry_point(checked, checker)
                return pipeline.TypedProgram(normalized, checker, pipeline.with_root_program(semantic, normalized))
            typed, type_seconds = _measure(finish_frontend)
            validate_backend_capabilities(typed, BackendIdentity.NATIVE)
            aggregate_counts.update({"source_load": 1, "parse": 1, "type_check": 1,
                                     "ast_construction": 1, "module_import_resolution": 1})
            for level in LEVELS:
                row, module = _materialize(typed, level)
                row.update({"workload": relative, "source_bytes": len(source.encode()),
                            "source_characters": len(source), "ast_nodes": _graph_count(program)})
                row["timings_seconds"]["source_loading"] = load_seconds / len(LEVELS)
                row["timings_seconds"]["lexing_parsing_ast"] = parse_seconds / len(LEVELS)
                row["timings_seconds"]["semantic_type_analysis"] = type_seconds / len(LEVELS)
                row["total_materialization_seconds"] += (load_seconds + parse_seconds + type_seconds) / len(LEVELS)
                row["pre_llvm_seconds"] += (load_seconds + parse_seconds + type_seconds) / len(LEVELS)
                records.append(row)
                aggregate_counts.update(row["operation_counts"])
                aggregate_stages.update(row["timings_seconds"])
                aggregate_passes.update(row["optimizer_pass_seconds"])
                if relative.endswith("expense_tracker/Main.ae") and level == "O2":
                    cprofile_targets["expense_tracker_o2"] = (typed, level)
                if "small_o0" not in cprofile_targets:
                    cprofile_targets["small_o0"] = (typed, "O0")
        except Exception as error:
            unsupported.append({"workload": relative, "reason": type(error).__name__, "detail": str(error)[:240]})
    elapsed = time.perf_counter() - started_all
    by_profile = {}
    for level in LEVELS:
        selected = [row for row in records if row["profile"] == level]
        by_profile[level] = {"records": len(selected),
            "total_materialization_seconds": sum(x["total_materialization_seconds"] for x in selected),
            "pre_llvm_seconds": sum(x["pre_llvm_seconds"] for x in selected),
            "llvm_backend_emit_seconds": sum(x["timings_seconds"]["llvm_backend_emit"] for x in selected)}
    cp = {}
    if include_cprofile:
        for name, (typed, level) in cprofile_targets.items():
            cp[name] = _profile_stats(lambda typed=typed, level=level: _materialize(typed, level, emit=False))
    timing = {"audit": "TEST-PERF-3.1-pre-LLVM-IR-SSA-materialization-performance-profile",
        "schema_version": 1, "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "scope": {"manifest_workloads": len(configs), "supported_workloads": len({x['workload'] for x in records}),
                  "profile_records": len(records)}, "wall_seconds": elapsed, "unsupported": unsupported,
        "aggregate_stage_seconds": dict(aggregate_stages), "aggregate_operation_counts": dict(aggregate_counts),
        "aggregate_optimizer_pass_seconds": dict(aggregate_passes), "profiles": by_profile,
        "cprofile_top_cumulative": cp, "records": records,
        "cache_boundary": {"value": "final optimized and verified SSA", "key": "source contents + canonical path + full optimization profile",
          "work_before_lookup": ["none inside optimized_ssa; callers may parse/type-check before requesting it"],
          "profile_independent_prefix_reused_across_profiles": False,
          "cache_hits_repeat_materialization": False}}
    structural = {"audit": timing["audit"], "schema_version": 1,
        "methodology": "DETERMINISTIC_STRUCTURE_ONLY_TIMING_IS_LOCAL_SIDECAR",
        "scope": timing["scope"], "unsupported": unsupported,
        "records": [{key: row[key] for key in ("workload", "profile", "source_bytes", "source_characters", "ast_nodes", "initial_ir", "base_ssa", "final_ssa", "operation_counts")} for row in records],
        "cache_boundary": timing["cache_boundary"]}
    return timing, structural


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing-output", type=Path); parser.add_argument("--structural-output", type=Path)
    parser.add_argument("--workload-limit", type=int); parser.add_argument("--no-cprofile", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    timing, structural = profile(root, workload_limit=args.workload_limit,
                                 include_cprofile=not args.no_cprofile, progress=args.progress)
    rendered = json.dumps(timing, indent=2, sort_keys=True) + "\n"
    if args.timing_output: args.timing_output.write_text(rendered, encoding="utf-8")
    else: print(rendered, end="")
    if args.structural_output:
        args.structural_output.write_text(json.dumps(structural, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
