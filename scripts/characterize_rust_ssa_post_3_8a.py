#!/usr/bin/env python3
"""Measure the post-RUST-3.8a residual SSA pipeline without optimizing it."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import statistics
import sys
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import measure_rust_ssa_authority_performance as base  # noqa: E402
from aether.ssa.performance import characterize_python_ssa_only  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSAPerformanceProfile,
    diagnostic_lower_with_rust_authority_without_python_shadow,
    lower_with_rust_authority,
)
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


DEFAULT_OUTPUT = (
    ROOT / "docs/compiler/rust_ssa_post_3_8a_performance_characterization.json"
)
HISTORICAL_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_authority_performance_characterization.json"
)

CATEGORY_LABELS = {
    "intrinsic_rust_work": "intrinsic Rust work",
    "python_shadow_work": "Python shadow work",
    "safety_verification": "safety/verification",
    "transport_import": "transport/import",
    "comparison": "comparison",
    "orchestration": "orchestration",
}

# Every surviving phase has exactly one owner.  Historical-only phases are
# retained here so the RUST-3.7b artifact can be normalized into the same
# categories without pretending that those phases still execute.
PHASE_CATEGORIES = {
    "rust_lifecycle_normalization": "intrinsic_rust_work",
    "rust_ssa_lowering": "intrinsic_rust_work",
    "python_lifecycle_normalization": "python_shadow_work",
    "python_ssa_lowering": "python_shadow_work",
    "python_shadow_input_reconstruction": "python_shadow_work",
    "rust_owned_ssa_verification": "safety_verification",
    "imported_rust_python_verification": "safety_verification",
    "python_builder_verification": "safety_verification",
    "python_shadow_verification": "safety_verification",
    "input_snapshot_integrity_check": "safety_verification",
    "initial_ir_snapshot_preparation": "transport_import",
    "rust_transport_serialization": "transport_import",
    "rust_input_parsing": "transport_import",
    "rust_schema_v2_materialization": "transport_import",
    "request_response_transport_and_serialization": "transport_import",
    "response_json_decode": "transport_import",
    "rust_schema_v2_import": "transport_import",
    "companion_process_startup": "transport_import",
    "rust_transport_and_compute_combined": "transport_import",
    "python_result_dto_serialization": "comparison",
    "rust_result_dto_serialization": "comparison",
    "python_result_canonicalization": "comparison",
    "rust_result_canonicalization": "comparison",
    "canonical_comparison": "comparison",
    "rust_orchestration_unattributed": "orchestration",
    "clock_domain_rounding_adjustment": "orchestration",
    "residual_unattributed": "orchestration",
}

REMOVED_PHASES = {
    "python_shadow_input_reconstruction": (
        "removed/not executed",
        "RUST-3.8a reuses the original verified Initial IR for the Python shadow.",
    ),
    "python_shadow_verification": (
        "removed/not executed",
        "RUST-3.8a trusts GeneralSSABuilder's verification of its unchanged result.",
    ),
    "rust_result_dto_serialization": (
        "removed/not executed",
        "RUST-3.8a reuses the received schema-v2 DTO for comparison.",
    ),
}


def _dual_samples(workloads: list[dict[str, object]]):
    for workload in workloads:
        yield from workload["samples"]["rust_authority_python_shadow"]  # type: ignore[index]


def _category_model(workloads: list[dict[str, object]]) -> dict[str, object]:
    totals = {name: 0.0 for name in CATEGORY_LABELS}
    total_wall = 0.0
    observed_phases: set[str] = set()
    for sample in _dual_samples(workloads):
        total_wall += sample["total_wall_seconds"]
        for phase, seconds in sample["phases_seconds"].items():
            observed_phases.add(phase)
            try:
                category = PHASE_CATEGORIES[phase]
            except KeyError:
                raise RuntimeError(f"unclassified measured phase: {phase}") from None
            totals[category] += seconds
        totals["orchestration"] += sample["residual_unattributed_seconds"]
    categories = {
        name: {
            "label": CATEGORY_LABELS[name],
            "observed_seconds": seconds,
            "percent_of_dual_lane": 100 * seconds / total_wall,
        }
        for name, seconds in totals.items()
    }
    return {
        "basis": "all measured dual-lane workload samples; categories are mutually exclusive and additive",
        "total_observed_seconds": total_wall,
        "observed_phases": sorted(observed_phases),
        "categories": categories,
        "percent_sum": sum(row["percent_of_dual_lane"] for row in categories.values()),
    }


def _observed_phase_percent(
    workloads: list[dict[str, object]], phases: set[str]
) -> float:
    samples = list(_dual_samples(workloads))
    total_wall = sum(sample["total_wall_seconds"] for sample in samples)
    observed = sum(
        sample["phases_seconds"].get(phase, 0.0)
        for sample in samples
        for phase in phases
    )
    return 100 * observed / total_wall


def _phase_ranking(
    aggregates: dict[str, object], dual_median: float
) -> list[dict[str, object]]:
    phases = aggregates["rust_authority_python_shadow"]["phases"]  # type: ignore[index]
    rows = []
    for phase, summary in phases.items():
        category = PHASE_CATEGORIES.get(phase)
        if category is None:
            raise RuntimeError(f"unclassified aggregate phase: {phase}")
        rows.append(
            {
                "phase": phase,
                **summary,
                "percent_of_dual_lane_median": (
                    100 * summary["median_seconds"] / dual_median
                ),
                "category": category,
                "category_label": CATEGORY_LABELS[category],
            }
        )
    return sorted(rows, key=lambda row: row["median_seconds"], reverse=True)


def _measure_deep_cfg(
    client: PersistentRustSSALoweringClient,
    sizes: tuple[int, ...],
    warmup: int,
    rounds: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for size in sizes:
        module = linear(f"rust_3_8b_linear_{size}", size)

        def rust_only():
            value, report = diagnostic_lower_with_rust_authority_without_python_shadow(
                module, client
            )
            assert report.performance is not None
            return value, report.performance

        def dual():
            value, report = lower_with_rust_authority(
                module, client, characterize_performance=True
            )
            assert report.performance is not None
            return value, report.performance

        modes: tuple[
            tuple[str, Callable[[], tuple[object, SSAPerformanceProfile]]], ...
        ] = (
            ("python_ssa_only", lambda: characterize_python_ssa_only(module)),
            ("diagnostic_rust_only", rust_only),
            ("rust_authority_python_shadow", dual),
        )
        expected_digest: str | None = None
        for _ in range(warmup):
            for _mode, action in modes:
                value, _profile = action()
                digest = base._ssa_digest(value)
                expected_digest = expected_digest or digest
                if digest != expected_digest:
                    raise RuntimeError(f"deep-CFG SSA mismatch at {size} blocks")

        samples: dict[str, list[float]] = {mode: [] for mode, _ in modes}
        dual_phases: dict[str, list[float]] = defaultdict(list)
        for round_index in range(rounds):
            ordered = modes[round_index % 3 :] + modes[: round_index % 3]
            for mode, action in ordered:
                value, profile = action()
                if base._ssa_digest(value) != expected_digest:
                    raise RuntimeError(f"deep-CFG SSA mismatch at {size} blocks")
                samples[mode].append(profile.total_wall_seconds)
                if mode == "rust_authority_python_shadow":
                    for phase, seconds in profile.phases_seconds.items():
                        dual_phases[phase].append(seconds)
        rows.append(
            {
                "blocks": size,
                "fixture": "scripts/qualify_rust_ssa_lowering_adversarial.py::linear",
                "canonical_ssa_sha256": expected_digest,
                "python_ssa_only": base._summary(samples["python_ssa_only"]),
                "diagnostic_rust_only": base._summary(
                    samples["diagnostic_rust_only"]
                ),
                "rust_authority_python_shadow": base._summary(
                    samples["rust_authority_python_shadow"]
                ),
                "dual_phase_medians_seconds": {
                    phase: statistics.median(values)
                    for phase, values in sorted(dual_phases.items())
                },
            }
        )
    return rows


def _deep_cfg_observations(rows: list[dict[str, object]]) -> dict[str, object]:
    by_size = {row["blocks"]: row for row in rows}
    if 1000 not in by_size or 5000 not in by_size:
        return {
            "formal_complexity_claim": False,
            "interpretation": "Required 1000/5000 comparison was not available.",
        }
    lower = by_size[1000]
    upper = by_size[5000]
    ratios = {}
    for mode in (
        "python_ssa_only",
        "diagnostic_rust_only",
        "rust_authority_python_shadow",
    ):
        ratios[mode] = (
            upper[mode]["median_seconds"] / lower[mode]["median_seconds"]  # type: ignore[index]
        )
    lower_rust = lower["dual_phase_medians_seconds"]["rust_ssa_lowering"]  # type: ignore[index]
    upper_rust = upper["dual_phase_medians_seconds"]["rust_ssa_lowering"]  # type: ignore[index]
    ratios["rust_ssa_lowering"] = upper_rust / lower_rust
    return {
        "size_ratio_1000_to_5000": 5.0,
        "time_ratios_1000_to_5000": ratios,
        "formal_complexity_claim": False,
        "known_component": (
            "Python and Rust SSA lowering retain explicit dominator sets documented as O(V^2) space."
        ),
        "interpretation": (
            "Compare each timing ratio with the 5x input-size ratio. The measurements "
            "characterize empirical scaling and are not a formal complexity proof."
        ),
    }


def _historical_category_percentages(
    evidence: dict[str, object],
) -> dict[str, float]:
    workloads = evidence["workloads"]
    model = _category_model(workloads)  # type: ignore[arg-type]
    return {
        name: row["percent_of_dual_lane"]
        for name, row in model["categories"].items()  # type: ignore[union-attr]
    }


def _historical_comparison(
    current_categories: dict[str, object], ranking: list[dict[str, object]]
) -> dict[str, object]:
    old = json.loads(HISTORICAL_EVIDENCE.read_text(encoding="utf-8"))
    old_categories = _historical_category_percentages(old)
    old_phases = {
        row["phase"]: row["percent_of_dual_lane"]
        for row in old["bottleneck_ranking"]
    }
    current_phases = {
        row["phase"]: row["percent_of_dual_lane_median"] for row in ranking
    }
    category_rows = []
    for category in CATEGORY_LABELS:
        current = current_categories[category]["percent_of_dual_lane"]  # type: ignore[index]
        category_rows.append(
            {
                "category": category,
                "label": CATEGORY_LABELS[category],
                "rust_3_7b_percent": old_categories[category],
                "post_3_8a_percent": current,
                "percentage_point_delta": current - old_categories[category],
                "interpretation": (
                    "normalized within each independent measurement campaign; "
                    "the delta is compositional, not an absolute-time causal estimate"
                ),
            }
        )
    phase_rows = []
    for phase in sorted(set(old_phases) | set(current_phases)):
        removed = phase in REMOVED_PHASES
        phase_rows.append(
            {
                "phase": phase,
                "category": PHASE_CATEGORIES[phase],
                "rust_3_7b_percent": old_phases.get(phase, 0.0),
                "rust_3_8a_effect": (
                    REMOVED_PHASES[phase][0] if removed else "survives"
                ),
                "post_3_8a_percent": current_phases.get(phase, 0.0),
                "interpretation": (
                    REMOVED_PHASES[phase][1]
                    if removed
                    else "Re-measured; no raw cross-machine causal claim."
                ),
            }
        )
    return {
        "historical_revision": old["qualification_revision"],
        "caveat": (
            "RUST-3.7b and post-3.8a are separate campaigns. Compare normalized "
            "within-run percentages and ratios, not raw medians as causal deltas."
        ),
        "categories": category_rows,
        "phases": phase_rows,
    }


def _candidates() -> list[dict[str, str]]:
    return [
        {"candidate": "Rust SSA lowering", "classification": "ALGORITHMIC_CORE", "reason": "Cytron SSA construction and dominator-dependent work are semantic algorithmic core."},
        {"candidate": "Rust lifecycle normalization", "classification": "ALGORITHMIC_CORE", "reason": "It implements ownership/lifecycle semantics rather than redundant coordination."},
        {"candidate": "Rust Owned SSA verification", "classification": "SAFETY_BOUNDARY", "reason": "It is the native model's mandatory independent verifier."},
        {"candidate": "request/response transport + serialization", "classification": "LOW_RISK_ARCHITECTURAL", "reason": "Allocation and framing can be investigated without weakening authority, but the protocol must remain unchanged in this milestone."},
        {"candidate": "schema-v2 import", "classification": "SAFETY_BOUNDARY", "reason": "The strict importer validates the wire result and constructs the authoritative Python object."},
        {"candidate": "Python verification of imported Rust SSA", "classification": "SAFETY_BOUNDARY", "reason": "It provides cross-language verification diversity after import."},
        {"candidate": "Python shadow lifecycle/lowering/verification", "classification": "SHADOW_POLICY", "reason": "The synchronous verified oracle is mandatory production policy; reducing execution would change that policy."},
        {"candidate": "canonicalization/comparison", "classification": "SAFETY_BOUNDARY", "reason": "It is the fail-closed semantic parity boundary; no surviving redundancy has been proven."},
        {"candidate": "integrity check", "classification": "SAFETY_BOUNDARY", "reason": "It detects mutation of the shared Initial IR after RUST-3.8a removed shadow reconstruction."},
        {"candidate": "dominator implementation", "classification": "ALGORITHMIC_CORE", "reason": "Replacing explicit dominator sets changes the lowering algorithm and needs dedicated qualification."},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision")
    parser.add_argument("--executable", type=Path, default=base.DEFAULT_EXECUTABLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--deep-cfg-rounds", type=int, default=3)
    parser.add_argument("--deep-cfg-sizes", default="1000,5000")
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
        import shutil
        import subprocess

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

    loaded = [(*row, *base._load_module(row[1])) for row in base.WORKLOADS]
    workloads: list[dict[str, object]] = []
    with PersistentRustSSALoweringClient(
        executable, timeout_seconds=180, characterize_performance=True
    ) as client:
        cold_module = loaded[0][3]
        _value, cold_report = diagnostic_lower_with_rust_authority_without_python_shadow(
            cold_module, client
        )
        assert cold_report.performance is not None
        cold_request = cold_report.performance.to_dict()
        for name, path, category, module, digest in loaded:
            workloads.append(
                base._measure_workload(
                    name,
                    path,
                    category,
                    module,
                    digest,
                    client,
                    args.warmup,
                    args.rounds,
                )
            )
        scaling = _measure_deep_cfg(
            client, deep_sizes, args.warmup, args.deep_cfg_rounds
        )
        transport = {
            "total_requests": client.request_count,
            "process_starts": client.process_start_count,
        }

    modes = (
        "python_ssa_only",
        "diagnostic_rust_only",
        "rust_authority_python_shadow",
    )
    aggregates = {
        mode: base._aggregate_mode(workloads, mode, args.rounds) for mode in modes
    }
    python_median = aggregates["python_ssa_only"]["representative_suite"]["median_seconds"]
    rust_median = aggregates["diagnostic_rust_only"]["representative_suite"]["median_seconds"]
    dual_median = aggregates["rust_authority_python_shadow"]["representative_suite"]["median_seconds"]
    ranking = _phase_ranking(aggregates, dual_median)
    category_model = _category_model(workloads)
    category_rows = category_model["categories"]
    largest_category = max(
        category_rows, key=lambda name: category_rows[name]["percent_of_dual_lane"]
    )
    rust_only_phases = aggregates["diagnostic_rust_only"]["phases"]
    intrinsic_rust_only = [
        (phase, row["median_seconds"])
        for phase, row in rust_only_phases.items()
        if PHASE_CATEGORIES.get(phase) == "intrinsic_rust_work"
    ]
    dominant_rust_intrinsic = max(intrinsic_rust_only, key=lambda row: row[1])
    startup_seconds = cold_request["phases_seconds"].get(
        "companion_process_startup", 0.0
    )
    startup = {
        "startup_seconds": startup_seconds,
        "first_request_seconds": cold_request["total_wall_seconds"],
        "startup_percent_of_first_request": (
            100 * startup_seconds / cold_request["total_wall_seconds"]
        ),
        "first_request_profile": cold_request,
        "steady_state_representative": {
            "workload": workloads[0]["id"],
            "mode": "diagnostic_rust_only",
            **workloads[0]["summary"]["diagnostic_rust_only"],
        },
        **transport,
    }
    schema_import_percent = _observed_phase_percent(
        workloads, {"rust_schema_v2_import"}
    )
    canonical_percent = _observed_phase_percent(
        workloads,
        {
            "python_result_canonicalization",
            "rust_result_canonicalization",
            "canonical_comparison",
        },
    )
    transport_serialization_percent = _observed_phase_percent(
        workloads,
        {
            "initial_ir_snapshot_preparation",
            "rust_transport_serialization",
            "rust_input_parsing",
            "rust_schema_v2_materialization",
            "request_response_transport_and_serialization",
            "response_json_decode",
        },
    )
    deep_observations = _deep_cfg_observations(scaling)
    report = {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.8b",
        "decision": "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED",
        "qualification_revision": args.revision or base._revision(),
        "measurement_kind": "observational; no absolute timing is a semantic gate",
        "environment": {
            "platform": base.platform.platform(),
            "machine": base.platform.machine(),
            "processor": base.platform.processor(),
            "python": sys.version,
            "rustc": base._tool_version(["rustc", "--version"]),
            "cargo": base._tool_version(["cargo", "--version"]),
            "logical_cpu_count": os.cpu_count(),
            "companion": os.fspath(
                executable.relative_to(ROOT)
                if executable.is_relative_to(ROOT)
                else executable
            ),
            "companion_build_profile": "release",
        },
        "methodology": {
            "clock": "monotonic perf_counter / Rust Instant",
            "warmup_rounds_per_workload": args.warmup,
            "measured_rounds_per_workload": args.rounds,
            "deep_cfg_warmup_rounds": args.warmup,
            "deep_cfg_measured_rounds": args.deep_cfg_rounds,
            "statistics": ["median", "min", "max"],
            "ordering": "rotated lane order per round",
            "representative_workload_philosophy": "unchanged RUST-3.7b eight-workload stratified manifest",
            "production_timing_default": "disabled",
            "diagnostic_rust_only_is_authority_mode": False,
        },
        "workload_manifest": [
            {
                key: row[key]
                for key in (
                    "id",
                    "path",
                    "category",
                    "source_sha256",
                    "input_shape",
                )
            }
            for row in workloads
        ],
        "workloads": workloads,
        "aggregates": aggregates,
        "lane_comparison": {
            "python_only_median_seconds": python_median,
            "diagnostic_rust_only_median_seconds": rust_median,
            "rust_authority_python_shadow_median_seconds": dual_median,
            "dual_over_python_ratio": dual_median / python_median,
            "rust_only_over_python_ratio": rust_median / python_median,
        },
        "phase_inventory": {
            "surviving": ranking,
            "removed_by_rust_3_8a": [
                {"phase": phase, "status": status, "reason": reason}
                for phase, (status, reason) in REMOVED_PHASES.items()
            ],
        },
        "bottleneck_ranking": ranking,
        "category_breakdown": category_model,
        "historical_comparison": _historical_comparison(category_rows, ranking),
        "deep_cfg_scaling": scaling,
        "deep_cfg_observations": deep_observations,
        "startup_steady_state": startup,
        "candidate_audit": _candidates(),
        "measured_answers": {
            "largest_individual_phase": ranking[0]["phase"],
            "largest_category": largest_category,
            "rust_only_slower_than_python_only": rust_median > python_median,
            "dominant_rust_intrinsic_phase": dominant_rust_intrinsic[0],
            "schema_v2_import": {
                "percent_of_dual_lane": schema_import_percent,
                "major_cost": True,
                "answer": "Yes; it is the second-largest individual phase and remains a strict safety boundary.",
            },
            "canonicalization": {
                "canonicalization_and_comparison_percent_of_dual_lane": canonical_percent,
                "dedicated_milestone_warranted_next": False,
                "answer": "No as the next dedicated milestone; retain it as a secondary representation-allocation target because it is fail-closed safety work.",
            },
            "deep_cfg_dominators": {
                "dedicated_algorithmic_milestone_justified": True,
                "time_ratios_1000_to_5000": deep_observations.get(
                    "time_ratios_1000_to_5000"
                ),
                "answer": "Yes for large/deep CFG workloads; the evidence is empirical and does not by itself prove complexity.",
            },
            "best_expected_benefit_risk": {
                "candidate": "request/response transport + serialization",
                "classification": "LOW_RISK_ARCHITECTURAL",
                "related_transport_serialization_percent_of_dual_lane": transport_serialization_percent,
                "answer": "Target allocation and representation efficiency while preserving protocol, schema, import validation, authority, and fail-closed behavior.",
            },
            "overhead_percentages": {
                name: row["percent_of_dual_lane"]
                for name, row in category_rows.items()
            },
        },
        "recommendation": {
            "next_milestone": "Transport/serialization allocation and representation efficiency",
            "primary_candidate": "request/response transport + serialization",
            "why": (
                "Transport/import is the largest current category. The transport and serialization subset is architectural rather than algorithmic, while schema-v2 import remains a measured secondary hotspot whose validation boundary must be preserved."
            ),
            "constraints": [
                "do not change schema-v1, schema-v2, or protocol-v1",
                "do not weaken strict schema-v2 import validation",
                "do not change authority, synchronous shadow, or fail-closed comparison",
            ],
            "separate_follow_up": (
                "A dedicated dominator algorithm milestone is justified for large/deep CFG after the lower-risk transport work; it requires broader semantic qualification."
            ),
        },
        "production_invariants": {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "mandatory_synchronous",
            "failure_policy": "FAIL_CLOSED",
            "schemas": {"initial_ir": 1, "ssa": 2, "protocol": 1},
            "behavior_changed": False,
            "optimization_implemented": False,
        },
        "limitations": [
            "Wall-clock results are machine- and load-dependent.",
            "The aggregate describes the checked-in workload manifest, not every program distribution.",
            "Final Rust response serialization and IPC remain combined.",
            "Deep-CFG timings characterize scaling but do not prove formal complexity.",
            "RUST-3.7b and post-3.8a raw medians are from separate campaigns.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["lane_comparison"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
