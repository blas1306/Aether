#!/usr/bin/env python3
"""Profile O2.13 regeneration without changing its deterministic evidence.

Timing data is diagnostic and is deliberately written to a separate report.
The canonical ``o2_measurement_baseline.json`` never consumes this module.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import platform
import time
from unittest.mock import patch

import aether.backend.llvm.build as llvm_build
from aether.backend.llvm import LLVMBackend, LLVMBuilder
from aether.o2_evidence_materialization import (
    clear_materialization_cache,
    materialization_counts,
)
from scripts import o2_measurement


class Recorder:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.seconds: Counter[str] = Counter()
        self.requests: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
        self.rows: list[dict] = []

    def call(self, stage, original, *, request=None):
        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                self.counts[stage] += 1
                self.seconds[stage] += elapsed
                key = request(args, kwargs) if request else None
                if key is not None:
                    self.requests[stage][key] += 1
                self.rows.append({"stage": stage, "seconds": elapsed, "request": key})
        return measured

    def summary(self) -> dict:
        duplicates = {}
        for stage, requests in self.requests.items():
            duplicates[stage] = {
                "requests": sum(requests.values()),
                "unique_requests": len(requests),
                "exact_duplicate_requests": sum(value - 1 for value in requests.values()),
            }
        slowest = sorted(self.rows, key=lambda row: row["seconds"], reverse=True)[:10]
        return {
            "counts": dict(sorted(self.counts.items())),
            "seconds": {key: round(value, 6) for key, value in sorted(self.seconds.items())},
            "duplication": duplicates,
            "slowest_operations": slowest,
        }


def _source_profile_request(args, _kwargs):
    source, path, profile = args[:3]
    digest = hashlib.sha256(source.encode()).hexdigest()
    return (f"{Path(path).resolve()}:{digest}", profile.name)


def _llvm_request(args, _kwargs):
    builder, typed = args[:2]
    # Object identity is intentionally session-local: generate() prepares one typed
    # program per workload and submits that exact immutable object at O0/O1/O2.
    # Avoid repr(typed), whose traversal would contaminate the measurement.
    return (str(id(typed)), builder.optimization_profile.name)


@contextmanager
def instrument(recorder: Recorder):
    original_emit = LLVMBuilder.emit_llvm
    original_backend_emit = LLVMBackend.emit
    original_lower = llvm_build.lower_to_verified_ssa
    with (
        patch.object(o2_measurement, "_build_ir", recorder.call("initial_ir", o2_measurement._build_ir)),
        patch.object(o2_measurement, "_optimized_ssa", recorder.call("ssa_request", o2_measurement._optimized_ssa, request=_source_profile_request)),
        patch.object(o2_measurement, "_typed_program", recorder.call("typed_program", o2_measurement._typed_program)),
        patch.object(LLVMBuilder, "emit_llvm", recorder.call("llvm_generation", original_emit, request=_llvm_request)),
        patch.object(LLVMBackend, "emit", recorder.call("llvm_textual_emission", original_backend_emit)),
        patch.object(llvm_build, "lower_to_verified_ssa", recorder.call("llvm_ssa_lowering", original_lower)),
        patch.object(o2_measurement, "instruction_census", recorder.call("evidence_analysis", o2_measurement.instruction_census)),
        patch.object(o2_measurement, "loop_census", recorder.call("evidence_analysis", o2_measurement.loop_census)),
        patch.object(o2_measurement, "allocation_census", recorder.call("evidence_analysis", o2_measurement.allocation_census)),
        patch.object(o2_measurement, "repeated_expressions", recorder.call("evidence_analysis", o2_measurement.repeated_expressions)),
    ):
        yield


def audit(root: Path, *, workload_limit: int | None = None) -> dict:
    manifest = o2_measurement.load_manifest(root)
    if workload_limit is not None:
        manifest = {**manifest, "workloads": manifest["workloads"][:workload_limit]}
    recorder = Recorder()
    clear_materialization_cache()
    started = time.perf_counter()
    with instrument(recorder):
        generated = o2_measurement.generate(root, manifest)
    generation_seconds = time.perf_counter() - started
    started = time.perf_counter()
    rendered = json.dumps(generated, indent=2, sort_keys=True) + "\n"
    rendering_seconds = time.perf_counter() - started
    recorder.counts["json_rendering"] += 1
    recorder.seconds["json_rendering"] += rendering_seconds
    canonical = root / "docs/compiler/o2_measurement_baseline.json"
    deterministic_match = workload_limit is None and canonical.read_bytes() == rendered.encode()
    ssa = materialization_counts()
    return {
        "audit": "TEST-PERF-2-O2.13-LLVM-evidence-performance-audit",
        "schema_version": 1,
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "scope": {"workloads": len(manifest["workloads"]), "full_manifest": workload_limit is None},
        "total_generation_seconds": round(generation_seconds, 6),
        "operations": recorder.summary(),
        "ssa_materialization": ssa,
        "determinism": {"canonical_baseline_byte_equal": deterministic_match},
        "native_compiler_invocations": 0,
        "native_executable_invocations": 0,
        "note": "Static O2.13 regeneration performs no native compilation or execution; runtime_measure is opt-in.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workload-limit", type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = audit(root, workload_limit=args.workload_limit)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
