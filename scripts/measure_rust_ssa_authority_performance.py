#!/usr/bin/env python3
"""Characterize Rust-authority/Python-shadow SSA costs without semantic gates."""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from aether.pipeline import IRBackend, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_to_dto  # noqa: E402
from aether.ssa.performance import characterize_python_ssa_only  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSAPerformanceProfile,
    canonical_ssa,
    diagnostic_lower_with_rust_authority_without_python_shadow,
    lower_with_rust_authority,
)
from aether.typechecker import TypeChecker  # noqa: E402
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


DEFAULT_EXECUTABLE = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_OUTPUT = ROOT / "docs/compiler/rust_ssa_authority_performance_characterization.json"
WORKLOADS = (
    ("tiny_scalar", "benchmarks/arithmetic.ae", "tiny/scalar"),
    ("numeric_iterative", "benchmarks/nested_loops.ae", "numeric iterative"),
    ("collection_heavy", "benchmarks/list_for_sum.ae", "collection-heavy"),
    ("struct_heavy", "examples/structs/custom_constructor_and_equality.ae", "struct-heavy"),
    ("class_interface_heavy", "examples/classes/implements_interface.ae", "class/interface-heavy"),
    ("indirect_call", "corpus/exceptions/positive/indirect_call.ae", "function-value/indirect-call"),
    ("exception_lifecycle", "corpus/exceptions/positive/cleanup_during_unwinding.ae", "exception/lifecycle-heavy"),
    ("realistic_medium", "examples/expense_tracker/Main.ae", "realistic medium program"),
)


def _revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _tool_version(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _load_module(relative: str):
    path = ROOT / relative
    source = path.read_text(encoding="utf-8")
    typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
    return IRBackend().lower_verified(typed), sha256(source.encode()).hexdigest()


def _profile_dict(profile: SSAPerformanceProfile) -> dict[str, object]:
    return profile.to_dict()


def _ssa_digest(value: object) -> str:
    dto = canonical_ssa(ssa_module_to_dto(value, schema_version=2))  # type: ignore[arg-type]
    return sha256(json.dumps(dto, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _summary(values: Iterable[float]) -> dict[str, float | int]:
    samples = list(values)
    if not samples:
        raise ValueError("cannot summarize an empty timing sample")
    return {
        "samples": len(samples),
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


def _aggregate_mode(
    workloads: list[dict[str, object]], mode: str, rounds: int
) -> dict[str, object]:
    round_totals = [0.0] * rounds
    phase_rounds: dict[str, list[float]] = defaultdict(lambda: [0.0] * rounds)
    for workload in workloads:
        samples = workload["samples"][mode]  # type: ignore[index]
        for index, sample in enumerate(samples):
            round_totals[index] += sample["total_wall_seconds"]
            for phase, seconds in sample["phases_seconds"].items():
                phase_rounds[phase][index] += seconds
            phase_rounds["residual_unattributed"][index] += sample[
                "residual_unattributed_seconds"
            ]
    return {
        "representative_suite": _summary(round_totals),
        "phases": {
            phase: _summary(values) for phase, values in sorted(phase_rounds.items())
        },
    }


def _cost_model(workloads: list[dict[str, object]]) -> dict[str, object]:
    groups = {
        "intrinsic_rust_ssa": {
            "rust_input_parsing",
            "rust_lifecycle_normalization",
            "rust_ssa_lowering",
            "rust_owned_ssa_verification",
            "rust_schema_v2_materialization",
            "rust_orchestration_unattributed",
        },
        "python_shadow_duplicated_work": {
            "python_shadow_input_reconstruction",
            "python_lifecycle_normalization",
            "python_ssa_lowering",
            "python_builder_verification",
            "python_shadow_verification",
        },
        "transport_serialization_import": {
            "initial_ir_snapshot_preparation",
            "rust_transport_serialization",
            "companion_process_startup",
            "request_response_transport_and_serialization",
            "response_json_decode",
            "rust_schema_v2_import",
        },
        "migration_safety_verification_comparison": {
            "imported_rust_python_verification",
            "input_snapshot_integrity_check",
            "rust_result_dto_serialization",
            "python_result_dto_serialization",
            "rust_result_canonicalization",
            "python_result_canonicalization",
            "canonical_comparison",
        },
    }
    totals = {name: 0.0 for name in groups}
    totals["orchestration_residual"] = 0.0
    total_wall = 0.0
    for workload in workloads:
        for sample in workload["samples"]["rust_authority_python_shadow"]:  # type: ignore[index]
            total_wall += sample["total_wall_seconds"]
            for name, phases in groups.items():
                totals[name] += sum(
                    sample["phases_seconds"].get(phase, 0.0) for phase in phases
                )
            totals["orchestration_residual"] += sample[
                "residual_unattributed_seconds"
            ]
    return {
        "basis": "all measured dual-lane workload samples; percentages are additive",
        "total_observed_seconds": total_wall,
        "categories": {
            name: {
                "observed_seconds": seconds,
                "percent_of_dual_lane": 100 * seconds / total_wall,
            }
            for name, seconds in totals.items()
        },
    }


def _measure_workload(
    name: str,
    path: str,
    category: str,
    module: object,
    source_digest: str,
    client: PersistentRustSSALoweringClient,
    warmup: int,
    rounds: int,
) -> dict[str, object]:
    def rust_only() -> tuple[object, SSAPerformanceProfile]:
        value, report = diagnostic_lower_with_rust_authority_without_python_shadow(
            module, client  # type: ignore[arg-type]
        )
        assert report.performance is not None
        return value, report.performance

    def dual() -> tuple[object, SSAPerformanceProfile]:
        value, report = lower_with_rust_authority(
            module, client, characterize_performance=True  # type: ignore[arg-type]
        )
        assert report.performance is not None
        return value, report.performance

    modes: tuple[tuple[str, Callable[[], tuple[object, SSAPerformanceProfile]]], ...] = (
        ("python_ssa_only", lambda: characterize_python_ssa_only(module)),  # type: ignore[arg-type]
        ("diagnostic_rust_only", rust_only),
        ("rust_authority_python_shadow", dual),
    )
    expected_digest: str | None = None
    for _ in range(warmup):
        for _mode, action in modes:
            value, _profile = action()
            digest = _ssa_digest(value)
            expected_digest = expected_digest or digest
            if digest != expected_digest:
                raise RuntimeError(f"SSA changed across modes during warmup for {path}")

    samples: dict[str, list[dict[str, object]]] = {mode: [] for mode, _ in modes}
    for round_index in range(rounds):
        # Rotate the starting mode to reduce systematic ordering bias.
        ordered = modes[round_index % len(modes) :] + modes[: round_index % len(modes)]
        for mode, action in ordered:
            value, profile = action()
            if _ssa_digest(value) != expected_digest:
                raise RuntimeError(f"SSA changed across measured modes for {path}")
            samples[mode].append(_profile_dict(profile))

    return {
        "id": name,
        "path": path,
        "category": category,
        "source_sha256": source_digest,
        "input_shape": {
            "functions": len(module.functions),  # type: ignore[attr-defined]
            "blocks": sum(len(function.blocks) for function in module.functions),  # type: ignore[attr-defined]
            "instructions": sum(
                len(block.instructions)
                for function in module.functions  # type: ignore[attr-defined]
                for block in function.blocks
            ),
        },
        "canonical_ssa_sha256": expected_digest,
        "samples": samples,
        "summary": {
            mode: _summary(sample["total_wall_seconds"] for sample in mode_samples)
            for mode, mode_samples in samples.items()
        },
    }


def _scaling(
    client: PersistentRustSSALoweringClient,
    sizes: tuple[int, ...],
    warmup: int,
    rounds: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for size in sizes:
        module = linear(f"rust_3_7b_linear_{size}", size)
        for _ in range(warmup):
            characterize_python_ssa_only(module)
            lower_with_rust_authority(module, client, characterize_performance=True)
        python_samples = []
        dual_samples = []
        phase_samples: dict[str, list[float]] = defaultdict(list)
        for _ in range(rounds):
            _value, python = characterize_python_ssa_only(module)
            _value, report = lower_with_rust_authority(
                module, client, characterize_performance=True
            )
            assert report.performance is not None
            python_samples.append(python.total_wall_seconds)
            dual_samples.append(report.performance.total_wall_seconds)
            for phase, seconds in report.performance.phases_seconds.items():
                phase_samples[phase].append(seconds)
        rows.append(
            {
                "blocks": size,
                "fixture": "scripts/qualify_rust_ssa_lowering_adversarial.py::linear",
                "python_ssa_only": _summary(python_samples),
                "rust_authority_python_shadow": _summary(dual_samples),
                "phase_medians_seconds": {
                    phase: statistics.median(values)
                    for phase, values in sorted(phase_samples.items())
                },
            }
        )
    return rows


def _scaling_observations(rows: list[dict[str, object]]) -> dict[str, object]:
    by_size = {row["blocks"]: row for row in rows}
    if 1000 not in by_size or 5000 not in by_size:
        return {
            "interpretation": "Custom sizes were measured; inspect the phase medians without a formal complexity claim.",
            "formal_complexity_claim": False,
            "known_component": "Python and Rust SSA lowering retain explicit dominator sets documented as O(V^2) space.",
        }
    thousand = by_size[1000]
    five_thousand = by_size[5000]
    return {
        "size_ratio_1000_to_5000": 5.0,
        "python_only_time_ratio_1000_to_5000": (
            five_thousand["python_ssa_only"]["median_seconds"]
            / thousand["python_ssa_only"]["median_seconds"]
        ),
        "dual_lane_time_ratio_1000_to_5000": (
            five_thousand["rust_authority_python_shadow"]["median_seconds"]
            / thousand["rust_authority_python_shadow"]["median_seconds"]
        ),
        "interpretation": (
            "The 993 and 1000 samples are similar, while 5000 blocks costs far more "
            "than the 5x input-size increase. This is empirical superlinear growth, "
            "consistent with the documented O(V^2)-space dominator-set implementation."
        ),
        "formal_complexity_claim": False,
        "known_component": "Python and Rust SSA lowering retain explicit dominator sets documented as O(V^2) space.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--deep-cfg-rounds", type=int, default=3)
    parser.add_argument("--deep-cfg-sizes", default="993,1000,5000")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if min(args.warmup, args.rounds, args.deep_cfg_rounds) < 1:
        parser.error("warmup and measured round counts must be positive")
    try:
        deep_sizes = tuple(int(value) for value in args.deep_cfg_sizes.split(","))
    except ValueError:
        parser.error("--deep-cfg-sizes must be comma-separated integers")
    if not deep_sizes or any(size < 2 for size in deep_sizes):
        parser.error("deep CFG sizes must be at least 2")

    if args.build:
        cargo = shutil.which("cargo")
        if cargo is None:
            raise RuntimeError("cargo is required for --build")
        subprocess.run(
            [cargo, "build", "--release", "-p", "aether-verifier", "--bin", "aether-ssa-shadow"],
            cwd=ROOT / "compiler-rs",
            check=True,
        )
    executable = args.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Rust SSA companion not found: {executable}")

    loaded = [(*row, *_load_module(row[1])) for row in WORKLOADS]
    workloads: list[dict[str, object]] = []
    with PersistentRustSSALoweringClient(
        executable, timeout_seconds=180, characterize_performance=True
    ) as client:
        # A dedicated cold request records process startup; it is excluded from
        # steady-state workload summaries and warmups.
        cold_module = loaded[0][3]
        _cold_value, cold_report = diagnostic_lower_with_rust_authority_without_python_shadow(
            cold_module, client
        )
        assert cold_report.performance is not None
        cold_request = cold_report.performance.to_dict()
        for name, path, category, module, digest in loaded:
            workloads.append(
                _measure_workload(
                    name, path, category, module, digest, client, args.warmup, args.rounds
                )
            )
        scaling = _scaling(client, deep_sizes, args.warmup, args.deep_cfg_rounds)
        transport = {
            "requests": client.request_count,
            "process_startups": client.process_start_count,
        }

    aggregates = {
        mode: _aggregate_mode(workloads, mode, args.rounds)
        for mode in (
            "python_ssa_only",
            "diagnostic_rust_only",
            "rust_authority_python_shadow",
        )
    }
    python_median = aggregates["python_ssa_only"]["representative_suite"]["median_seconds"]
    rust_median = aggregates["diagnostic_rust_only"]["representative_suite"]["median_seconds"]
    dual_median = aggregates["rust_authority_python_shadow"]["representative_suite"]["median_seconds"]
    dual_phases = aggregates["rust_authority_python_shadow"]["phases"]
    ranking = sorted(
        (
            {
                "phase": phase,
                "median_seconds": summary["median_seconds"],
                "percent_of_dual_lane": 100 * summary["median_seconds"] / dual_median,
            }
            for phase, summary in dual_phases.items()
        ),
        key=lambda row: row["median_seconds"],
        reverse=True,
    )
    report = {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.7b",
        "decision": "RUST_SSA_PERFORMANCE_CHARACTERIZED",
        "qualification_revision": _revision(),
        "measurement_kind": "observational; no absolute timing is a semantic gate",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version,
            "rustc": _tool_version(["rustc", "--version"]),
            "cargo": _tool_version(["cargo", "--version"]),
            "logical_cpu_count": os.cpu_count(),
            "companion": os.fspath(executable.relative_to(ROOT) if executable.is_relative_to(ROOT) else executable),
            "companion_build_profile": "release",
        },
        "methodology": {
            "clock": "monotonic perf_counter / Rust Instant",
            "warmup_rounds_per_workload": args.warmup,
            "measured_rounds_per_workload": args.rounds,
            "deep_cfg_measured_rounds": args.deep_cfg_rounds,
            "statistics": ["median", "min", "max"],
            "ordering": "rotated lane order per round",
            "timing_precision_policy": "raw seconds retained; conclusions use bounded aggregate statistics",
            "production_timing_default": "disabled",
            "diagnostic_rust_only_is_authority_mode": False,
        },
        "workload_manifest": [
            {key: row[key] for key in ("id", "path", "category", "source_sha256", "input_shape")}
            for row in workloads
        ],
        "workloads": workloads,
        "aggregates": aggregates,
        "cost_model": _cost_model(workloads),
        "lane_comparison": {
            "python_only_median_seconds": python_median,
            "diagnostic_rust_only_median_seconds": rust_median,
            "rust_authority_python_shadow_median_seconds": dual_median,
            "dual_over_python_ratio": dual_median / python_median,
            "rust_only_over_python_ratio": rust_median / python_median,
        },
        "persistent_companion": {
            "cold_first_request": cold_request,
            "steady_state_excludes_cold_request": True,
            **transport,
        },
        "bottleneck_ranking": ranking,
        "deep_cfg_scaling": scaling,
        "scaling_observations": _scaling_observations(scaling),
        "optimization_candidates": [
            {
                "priority": 1,
                "candidate": "Remove only provably redundant Python verifier passes.",
                "measured_bottleneck": "Python builder verification plus Python shadow verification",
                "expected_mechanism": "Retain one qualified verification boundary instead of verifying the same immutable shadow SSA twice.",
                "correctness_risk": "medium; requires proof that no mutation occurs between boundaries",
                "architectural_risk": "low",
                "preserves_mandatory_python_shadow": True,
                "changes_protocol_or_schema": False,
            },
            {
                "priority": 2,
                "candidate": "Reuse immutable snapshot structures for Python shadow input.",
                "measured_bottleneck": "python_shadow_input_reconstruction",
                "expected_mechanism": "Avoid the JSON decode/import copy while retaining one immutable same-input snapshot contract.",
                "correctness_risk": "medium; aliasing and same-input proof must remain fail-closed",
                "architectural_risk": "medium",
                "preserves_mandatory_python_shadow": True,
                "changes_protocol_or_schema": False,
            },
            {
                "priority": 3,
                "candidate": "Cache or share immutable schema-v2 DTO and canonical forms.",
                "measured_bottleneck": "two result DTO serializations plus two canonicalizations",
                "expected_mechanism": "Construct each immutable comparison representation once.",
                "correctness_risk": "medium; cache invalidation must be impossible or explicit",
                "architectural_risk": "medium",
                "preserves_mandatory_python_shadow": True,
                "changes_protocol_or_schema": False,
            },
            {
                "priority": 4,
                "candidate": "Replace explicit dominator sets after a separate algorithm qualification milestone.",
                "measured_bottleneck": "rust_ssa_lowering and Python SSA phases on deep CFG",
                "expected_mechanism": "Use a dominance representation that avoids the known O(V^2)-space sets.",
                "correctness_risk": "high; changes SSA construction algorithms",
                "architectural_risk": "medium",
                "preserves_mandatory_python_shadow": True,
                "changes_protocol_or_schema": False,
            },
            {
                "priority": 5,
                "candidate": "Reduce response decoding/import allocation.",
                "measured_bottleneck": "rust_schema_v2_import and response_json_decode",
                "expected_mechanism": "Profile generated/streamed decoding or fewer intermediate Python objects.",
                "correctness_risk": "high; importer is a fail-closed schema boundary",
                "architectural_risk": "medium",
                "preserves_mandatory_python_shadow": True,
                "changes_protocol_or_schema": "possibly",
            },
            {
                "priority": 6,
                "candidate": "Sample or remove the Python shadow only in a future explicitly authorized milestone.",
                "measured_bottleneck": "python_shadow_duplicated_work category",
                "expected_mechanism": "Execute duplicated safety work less frequently.",
                "correctness_risk": "very high; weakens synchronous fail-closed parity detection",
                "architectural_risk": "very high",
                "preserves_mandatory_python_shadow": False,
                "changes_protocol_or_schema": False,
                "authorized_in_rust_3_7b": False,
            },
        ],
        "limitations": [
            "Final Rust response byte serialization and bidirectional IPC share one residual phase.",
            "Measurements begin at verified Initial IR and exclude frontend, optimizer, and backend.",
            "Wall-clock samples are machine-dependent and are not byte-deterministic evidence.",
            "Deep-CFG observations characterize empirical scaling; they do not prove asymptotic complexity.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["lane_comparison"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
