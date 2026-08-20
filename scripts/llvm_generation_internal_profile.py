#!/usr/bin/env python3
"""TEST-PERF-3: profile the 78 unique O2.13 LLVM textual emissions."""
from __future__ import annotations

import argparse
import cProfile
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import platform
import pstats
import re
import statistics
import sys
import time

from aether.backend.llvm import LLVMBackend, LLVMGenerationProfiler
from aether.backend.llvm.build import _has_native_entry_point
from aether.benchmark import _typed_program
from aether.capabilities import BackendIdentity, validate_backend_capabilities
from aether.ir.optimizer import build_optimizer_pipeline
from aether.optimization import optimization_profile
from aether.pipeline import DEFAULT_SSA_BUILDER, IRBackend, lower_to_verified_ssa
from aether.ssa.optimizer import build_ssa_optimizer_pipeline
try:
    from scripts.o2_measurement import load_manifest
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from o2_measurement import load_manifest


LEVELS = ("O0", "O1", "O2")


def _materialize(typed: object, level: str):
    profile = optimization_profile(level)
    validate_backend_capabilities(typed, BackendIdentity.NATIVE)
    ir_backend = IRBackend()
    ir_module = ir_backend.lower_verified(typed)
    if profile.ir_passes:
        ir_module = ir_backend.optimize_verified(
            ir_module, optimizer=build_optimizer_pipeline(profile)
        )
    module = lower_to_verified_ssa(ir_module, builder=DEFAULT_SSA_BUILDER)
    return build_ssa_optimizer_pipeline(profile, verify_after_each=True).run(module)


def _module_metrics(module) -> dict:
    instructions = [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]
    return {
        "functions": len(module.functions),
        "blocks": sum(len(function.blocks) for function in module.functions),
        "instructions": len(instructions),
        "instruction_families": dict(sorted(Counter(type(x).__name__ for x in instructions).items())),
        "structs": len(module.structs),
    }


def _runtime_metrics(llvm: str) -> dict:
    # Runtime symbols have a reserved prefix.  Count whole top-level sections
    # containing one, rather than guessing from indentation inside functions.
    sections = llvm.split("\n\n")
    runtime = []
    for section in sections:
        first = section.splitlines()[0] if section else ""
        is_helper = first.startswith("define ") and re.search(
            r"@(aether_|__ae_|_?aether)", first
        )
        if (is_helper or first.startswith("declare ") or
                first.startswith("@.aether.") or first.startswith("%Aether")):
            runtime.append(section)
    text = "\n\n".join(runtime)
    helper_bodies = [section for section in runtime if section.startswith("define ")]
    return {
        "sections": len(runtime),
        "bytes": len(text.encode("utf-8")),
        "lines": len(text.splitlines()),
        "helper_definitions": len(helper_bodies),
        "helper_hashes": [hashlib.sha256(x.encode()).hexdigest()[:16] for x in helper_bodies],
    }


def _pearson(rows: list[dict], field: str) -> float | None:
    xs = [float(row[field]) for row in rows]
    ys = [float(row["seconds"]) for row in rows]
    if len(xs) < 2 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    return numerator / denominator**0.5 if denominator else None


def _top(rows: list[dict], field: str) -> list[dict]:
    keys = ("workload", "profile", "seconds", "functions", "blocks", "instructions", "llvm_bytes", "llvm_lines")
    return [{key: row[key] for key in keys} for row in sorted(rows, key=lambda x: x[field], reverse=True)[:10]]


def _cprofile(module, native_entry: bool) -> list[dict]:
    profile = cProfile.Profile()
    profile.enable()
    LLVMBackend().emit(module, native_entry=native_entry)
    profile.disable()
    stats = pstats.Stats(profile, stream=io.StringIO()).strip_dirs().sort_stats("cumulative")
    rows = []
    for (filename, line, function), (primitive, calls, own, cumulative, _callers) in list(stats.stats.items()):
        rows.append({"function": f"{filename}:{line}({function})", "calls": calls, "primitive_calls": primitive,
                     "own_seconds": own, "cumulative_seconds": cumulative})
    return sorted(rows, key=lambda row: row["cumulative_seconds"], reverse=True)[:20]


def profile(root: Path, *, workload_limit: int | None = None, include_cprofile: bool = True,
            progress: bool = False, workload: str | None = None,
            seed: dict | None = None) -> tuple[dict, dict]:
    manifest = load_manifest(root)
    configs = manifest["workloads"][:workload_limit] if workload_limit else manifest["workloads"]
    if workload is not None:
        configs = [config for config in configs if config["path"] == workload]
    rows = list(seed.get("records", ())) if seed else []
    modules = {}
    unsupported = list(seed.get("unsupported", ())) if seed else []
    completed = {(row["workload"], row["profile"]) for row in rows}
    for index, config in enumerate(configs, 1):
        if progress:
            print(f"[{index}/{len(configs)}] {config['path']}", file=sys.stderr, flush=True)
        path = root / config["path"]
        source = path.read_text(encoding="utf-8")
        try:
            typed = _typed_program(source, path)
            for level in LEVELS:
                if (config["path"], level) in completed:
                    continue
                if progress:
                    print(f"  {level}", file=sys.stderr, flush=True)
                module = _materialize(typed, level)
                profiler = LLVMGenerationProfiler()
                construction_started = time.perf_counter()
                backend = LLVMBackend(profiler=profiler)
                construction_seconds = time.perf_counter() - construction_started
                started = time.perf_counter()
                llvm = backend.emit(module, native_entry=_has_native_entry_point(typed))
                seconds = time.perf_counter() - started
                metrics = _module_metrics(module)
                runtime = _runtime_metrics(llvm)
                row = {
                    "workload": config["path"], "profile": level, **metrics,
                    "seconds": seconds, "backend_construction_seconds": construction_seconds,
                    "llvm_bytes": len(llvm.encode("utf-8")), "llvm_lines": len(llvm.splitlines()),
                    "runtime": runtime, "phases": profiler.snapshot(),
                }
                measured = sum(row["phases"].get(name, {}).get("seconds", 0.0) for name in
                               ("verification", "function_lowering", "runtime_helper_emission", "final_text_rendering"))
                row["module_setup_and_declarations_seconds"] = max(0.0, seconds - measured)
                rows.append(row)
                modules[(config["path"], level)] = (module, _has_native_entry_point(typed))
        except Exception as error:
            unsupported.append({"workload": config["path"], "reason": type(error).__name__, "detail": str(error)[:240]})

    by_profile = {}
    for level in LEVELS:
        selected = [row for row in rows if row["profile"] == level]
        by_profile[level] = {
            "emissions": len(selected), "seconds": sum(row["seconds"] for row in selected),
            "llvm_bytes": sum(row["llvm_bytes"] for row in selected),
            "instructions": sum(row["instructions"] for row in selected),
        }
    phase_totals = defaultdict(lambda: {"calls": 0, "seconds": 0.0})
    for row in rows:
        for name, values in row["phases"].items():
            phase_totals[name]["calls"] += values["calls"]
            phase_totals[name]["seconds"] += values["seconds"]
        phase_totals["backend_construction"]["calls"] += 1
        phase_totals["backend_construction"]["seconds"] += row["backend_construction_seconds"]
        phase_totals["module_setup_and_declarations"]["calls"] += 1
        phase_totals["module_setup_and_declarations"]["seconds"] += row["module_setup_and_declarations_seconds"]
    hashes = Counter(h for row in rows for h in row["runtime"]["helper_hashes"])
    slowest = max(rows, key=lambda row: row["seconds"]) if rows else None
    cp = []
    if include_cprofile and modules:
        available = [row for row in rows if (row["workload"], row["profile"]) in modules]
        representative = max(available, key=lambda row: row["seconds"])
        module, native_entry = modules[(representative["workload"], representative["profile"])]
        cp = _cprofile(module, native_entry)
    timing = {
        "audit": "TEST-PERF-3-LLVM-generation-internal-performance-profile", "schema_version": 1,
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "emissions": len(rows), "unsupported": unsupported,
        "total_seconds": sum(row["seconds"] for row in rows), "profiles": by_profile,
        "phase_totals": dict(sorted(phase_totals.items())),
        "correlations": {field: _pearson(rows, field) for field in ("instructions", "functions", "blocks", "llvm_bytes", "llvm_lines")},
        "top_slowest": _top(rows, "seconds"), "top_llvm_size": _top(rows, "llvm_bytes"),
        "top_instruction_count": _top(rows, "instructions"), "cprofile_top_cumulative": cp,
        "repeated_runtime_helpers": {"distinct_bodies": len(hashes), "body_emissions": sum(hashes.values()),
                                     "bodies_repeated_across_modules": sum(1 for count in hashes.values() if count > 1)},
        "records": rows,
    }
    structural_records = []
    for row in rows:
        structural_records.append({key: row[key] for key in (
            "workload", "profile", "functions", "blocks", "instructions", "instruction_families",
            "structs", "llvm_bytes", "llvm_lines", "runtime")})
    structural = {
        "audit": timing["audit"], "schema_version": 1,
        "methodology": "DETERMINISTIC_STRUCTURE_ONLY_TIMING_IS_LOCAL_SIDECAR",
        "emissions": len(rows), "profiles": {level: by_profile[level]["emissions"] for level in LEVELS},
        "unsupported": unsupported, "records": structural_records,
    }
    return timing, structural


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing-output", type=Path)
    parser.add_argument("--structural-output", type=Path)
    parser.add_argument("--workload-limit", type=int)
    parser.add_argument("--no-cprofile", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--workload")
    parser.add_argument("--resume-timing", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    seed = json.loads(args.resume_timing.read_text(encoding="utf-8")) if args.resume_timing else None
    timing, structural = profile(root, workload_limit=args.workload_limit,
                                 include_cprofile=not args.no_cprofile, progress=args.progress,
                                 workload=args.workload, seed=seed)
    rendered = json.dumps(timing, indent=2, sort_keys=True) + "\n"
    if args.timing_output:
        args.timing_output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.structural_output:
        args.structural_output.write_text(json.dumps(structural, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
