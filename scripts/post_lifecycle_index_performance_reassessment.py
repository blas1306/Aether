#!/usr/bin/env python3
"""TEST-PERF-3.3: post lifecycle-index performance reassessment.

This is deliberately observational.  It reuses the TEST-PERF-3.1 stage
instrumentation and adds lifecycle-index counters and a repeated-prefix audit.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from aether.ir import IRVerifier
from aether.pipeline import IRBackend
from aether.typechecker import TypeChecker
from aether import pipeline
from scripts.pre_llvm_ir_ssa_materialization_profile import LEVELS, profile as stage_profile


def profile(root: Path, *, workload_limit: int | None = None,
            include_cprofile: bool = False, progress: bool = False) -> dict:
    counts: Counter[str] = Counter()
    original_build = IRVerifier._build_lifecycle_storage_index
    original_query = IRVerifier._is_lifecycle_storage

    def build(function):
        counts["index_constructions"] += 1
        counts["full_ir_scans"] += 1
        counts["functions_indexed"] += 1
        return original_build(function)

    def query(self, function, name):
        counts["lifecycle_queries"] += 1
        return original_query(self, function, name)

    started = time.perf_counter()
    IRVerifier._build_lifecycle_storage_index = staticmethod(build)
    IRVerifier._is_lifecycle_storage = query
    try:
        timing, structural = stage_profile(
            root, workload_limit=workload_limit,
            include_cprofile=include_cprofile, progress=progress)
    finally:
        IRVerifier._build_lifecycle_storage_index = staticmethod(original_build)
        IRVerifier._is_lifecycle_storage = original_query
    wall = time.perf_counter() - started
    aggregate_index_counts = dict(counts)

    focused: dict[str, float | int] = {}
    expense_path = root / "examples/expense_tracker/Main.ae"
    if workload_limit is None and expense_path.exists():
        source = expense_path.read_text(encoding="utf-8")
        checker = TypeChecker(source_root=expense_path.parent, entry_path=expense_path)
        program = pipeline.parse_source(source)
        checked = pipeline.typecheck_program(program, checker)
        semantic = pipeline.build_checked_program(checked, checker)
        normalized = pipeline.normalize_entry_point(checked, checker)
        typed = pipeline.TypedProgram(normalized, checker,
                                      pipeline.with_root_program(semantic, normalized))
        module = IRBackend().lower(typed)
        class FocusedVerifier(IRVerifier):
            def _build_lifecycle_storage_index(self, function):
                counts["index_constructions"] += 1
                counts["full_ir_scans"] += 1
                counts["functions_indexed"] += 1
                return super()._build_lifecycle_storage_index(function)

            def _is_lifecycle_storage(self, function, name):
                counts["lifecycle_queries"] += 1
                return super()._is_lifecycle_storage(function, name)

        counts.clear()
        verify_started = time.perf_counter()
        FocusedVerifier(module).verify()
        focused = {**counts, "verifier_seconds": time.perf_counter() - verify_started}

    rows = timing["records"]
    stages = timing["aggregate_stage_seconds"]
    grouped = {
        "frontend_parsing_type_analysis": sum(stages.get(x, 0.0) for x in
            ("source_loading", "lexing_parsing_ast", "semantic_type_analysis")),
        "initial_ir_construction": stages.get("initial_ir_lowering", 0.0),
        "initial_ir_verification": stages.get("initial_ir_verification", 0.0)
            + stages.get("post_ir_verification", 0.0),
        "lifecycle_ownership_processing": stages.get("lifecycle_expansion", 0.0),
        "ssa_construction": stages.get("ssa_construction", 0.0),
        "ssa_verification": sum(stages.get(x, 0.0) for x in
            ("initial_ssa_verification", "ssa_optimizer_embedded_verification",
             "post_optimization_verification")),
        "optimization": stages.get("ir_optimization", 0.0)
            + stages.get("ssa_optimization", 0.0)
            - stages.get("ssa_optimizer_embedded_verification", 0.0)
            + stages.get("optimizer_pipeline_construction", 0.0),
        "llvm_backend_emit": stages.get("llvm_backend_emit", 0.0),
    }
    grouped["audit_test_harness_overhead"] = max(0.0, wall - sum(grouped.values()))
    percentages = {key: value / wall * 100.0 for key, value in grouped.items()}

    # Frontend is already shared once per workload by this measurement.  The
    # safely identifiable duplicated prefix is lowering + first IR verification;
    # SSA is downstream of profile-specific IR/lifecycle passes for O1/O2.
    duplicated_ir = sum(
        row["timings_seconds"]["initial_ir_lowering"]
        + row["timings_seconds"]["initial_ir_verification"] for row in rows)
    keep_once = 0.0
    for workload in {row["workload"] for row in rows}:
        candidates = [row for row in rows if row["workload"] == workload]
        keep_once += min(row["timings_seconds"]["initial_ir_lowering"]
                         + row["timings_seconds"]["initial_ir_verification"]
                         for row in candidates)
    upper = max(0.0, duplicated_ir - keep_once)
    expense = [row for row in rows if row["workload"].endswith("expense_tracker/Main.ae")]
    result = {
        "audit": "TEST-PERF-3.3-post-lifecycle-index-performance-reassessment",
        "schema_version": 1,
        "environment": timing["environment"], "scope": timing["scope"],
        "wall_seconds": wall,
        "pre_llvm_seconds": sum(row["pre_llvm_seconds"] for row in rows),
        "llvm_seconds": grouped["llvm_backend_emit"],
        "stage_seconds": grouped, "stage_percent_of_wall": percentages,
        "lifecycle_index": aggregate_index_counts,
        "expense_tracker_lifecycle_index": focused,
        "prefix_sharing": {
            "measured_common_ir_prefix_seconds": duplicated_ir,
            "theoretical_upper_bound_saving_seconds": upper,
            "realistically_recoverable_saving_seconds": upper * 0.75,
            "base_ssa_shareable_without_clone_or_pipeline_change": False,
            "reason": "O1/O2 lifecycle and IR optimization occur before SSA; optimizers return rewritten modules and cannot share a mutable input safely.",
        },
        "expense_tracker": expense,
        "profiles": timing["profiles"], "records": rows,
        "unsupported": timing["unsupported"],
        "structural_records": structural["records"],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workload-limit", type=int)
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = profile(root, workload_limit=args.workload_limit, progress=args.progress)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
