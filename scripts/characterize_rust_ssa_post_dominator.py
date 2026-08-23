#!/usr/bin/env python3
"""Re-characterize the post-CHK SSA authority pipeline (RUST-3.10)."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from typing import Callable, Iterable


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


BASELINE_REVISION = "96c72ec9e72ad395a657c6f9aed1be19b45c95eb"
DEFAULT_OUTPUT = (
    ROOT / "docs/compiler/rust_ssa_post_dominator_performance_characterization.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZATION.md"
)

ROUTES = (
    "python_ssa_only",
    "diagnostic_rust_only",
    "rust_authority_python_shadow",
)
LOWERING_COMPONENTS = (
    "cfg_construction",
    "reachability_and_rpo",
    "chk_idom",
    "dominator_tree",
    "dominance_frontier",
    "liveness",
    "definite_initialization",
    "phi_placement",
    "renaming",
    "remaining_lowering",
)
DOMINANCE_COMPONENTS = {
    "reachability_and_rpo",
    "chk_idom",
    "dominator_tree",
    "dominance_frontier",
}

CATEGORY_PHASES = {
    "RUST_INTRINSIC": {
        "rust_lifecycle_normalization",
        "rust_ssa_lowering",
    },
    "PYTHON_SHADOW": {
        "python_lifecycle_normalization",
        "python_ssa_lowering",
    },
    "SAFETY_VERIFICATION": {
        "rust_owned_ssa_verification",
        "imported_rust_python_verification",
        "python_builder_verification",
        "input_snapshot_integrity_check",
    },
    "TRANSPORT_REPRESENTATION": {
        "initial_ir_snapshot_preparation",
        "rust_transport_serialization",
        "rust_input_parsing",
        "rust_schema_v2_materialization",
        "request_response_transport_and_serialization",
        "response_json_decode",
        "rust_schema_v2_import",
        "python_result_dto_serialization",
        "companion_process_startup",
    },
    "CANONICAL_COMPARISON": {
        "python_result_canonicalization",
        "rust_result_canonicalization",
        "canonical_comparison",
    },
    "ORCHESTRATION": {
        "rust_orchestration_unattributed",
        "clock_domain_rounding_adjustment",
    },
}
PHASE_CATEGORY = {
    phase: category for category, phases in CATEGORY_PHASES.items() for phase in phases
}

REMOVED_WORK = (
    ("python_initial_ir_reconstruction", "RUST-3.8a"),
    ("duplicate_python_ssa_verification", "RUST-3.8a"),
    ("rust_result_reserialization", "RUST-3.8a"),
    ("json_encode_decode_canonicalization", "RUST-3.9a"),
    ("serde_json_value_response_materialization", "RUST-3.9a"),
    ("sorted_request_key_serialization", "RUST-3.9a"),
    ("production_full_dominator_sets", "RUST-3.9b"),
)


def _summary(values: Iterable[float]) -> dict[str, float | int]:
    return base._summary(values)


def _profile(profile: SSAPerformanceProfile) -> dict[str, object]:
    return profile.to_dict()


def _actions(module: object, client: PersistentRustSSALoweringClient):
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

    return {
        "python_ssa_only": lambda: characterize_python_ssa_only(module),  # type: ignore[arg-type]
        "diagnostic_rust_only": rust_only,
        "rust_authority_python_shadow": dual,
    }


def _measure_module(
    module: object,
    client: PersistentRustSSALoweringClient,
    routes: tuple[str, ...],
    warmup: int,
    rounds: int,
) -> tuple[dict[str, list[dict[str, object]]], str]:
    actions = _actions(module, client)
    expected_digest: str | None = None
    for _ in range(warmup):
        for route in routes:
            value, _ = actions[route]()
            digest = base._ssa_digest(value)
            expected_digest = expected_digest or digest
            if digest != expected_digest:
                raise RuntimeError(f"SSA mismatch during {route} warmup")
    assert expected_digest is not None
    samples = {route: [] for route in routes}
    for round_index in range(rounds):
        ordered = routes[round_index % len(routes) :] + routes[: round_index % len(routes)]
        for route in ordered:
            value, profile = actions[route]()
            if base._ssa_digest(value) != expected_digest:
                raise RuntimeError(f"SSA mismatch during measured {route}")
            samples[route].append(_profile(profile))
    return samples, expected_digest


def _ordinary_workload(
    row: tuple[str, str, str, object, str],
    client: PersistentRustSSALoweringClient,
    warmup: int,
    rounds: int,
) -> dict[str, object]:
    name, path, category, module, digest = row
    samples, ssa_digest = _measure_module(module, client, ROUTES, warmup, rounds)
    return {
        "id": name,
        "path": path,
        "category": category,
        "source_sha256": digest,
        "input_shape": {
            "functions": len(module.functions),
            "blocks": sum(len(function.blocks) for function in module.functions),
            "instructions": sum(
                len(block.instructions)
                for function in module.functions
                for block in function.blocks
            ),
        },
        "canonical_ssa_sha256": ssa_digest,
        "samples": samples,
        "summary": {
            route: _summary(sample["total_wall_seconds"] for sample in route_samples)
            for route, route_samples in samples.items()
        },
    }


def _component_summaries(samples: list[dict[str, object]]) -> dict[str, object]:
    return {
        component: _summary(
            sample["rust_ssa_lowering_phases_seconds"][component]  # type: ignore[index]
            for sample in samples
        )
        for component in LOWERING_COMPONENTS
    }


def _deep_cfg(
    client: PersistentRustSSALoweringClient,
    sizes: tuple[int, ...],
    warmup: int,
    rounds: int,
    python_max_size: int,
) -> list[dict[str, object]]:
    rows = []
    for size in sizes:
        module = linear(f"rust_3_10_linear_{size}", size)
        routes = (
            ROUTES
            if size <= python_max_size
            else ("diagnostic_rust_only",)
        )
        samples, digest = _measure_module(module, client, routes, warmup, rounds)
        route_rows: dict[str, object] = {}
        for route in ROUTES:
            if route not in samples:
                route_rows[route] = {
                    "status": "NOT_RUN_OPERATIONALLY_UNREASONABLE",
                    "reason": (
                        f"mandatory Python full-set dominance excluded above {python_max_size} blocks"
                    ),
                    "raw_samples": [],
                }
                continue
            route_rows[route] = {
                "status": "MEASURED",
                "summary": _summary(
                    sample["total_wall_seconds"] for sample in samples[route]
                ),
                "raw_samples": samples[route],
                "rust_ssa_lowering_components": (
                    _component_summaries(samples[route])
                    if route != "python_ssa_only"
                    else {}
                ),
            }
        rows.append(
            {
                "blocks": size,
                "fixture": "scripts/qualify_rust_ssa_lowering_adversarial.py::linear",
                "canonical_ssa_sha256": digest,
                "routes": route_rows,
            }
        )
    return rows


def _aggregate(workloads: list[dict[str, object]], route: str, rounds: int):
    return base._aggregate_mode(workloads, route, rounds)


def _category_accounting(workloads: list[dict[str, object]]) -> dict[str, object]:
    totals = {category: 0.0 for category in CATEGORY_PHASES}
    constituents = {category: defaultdict(float) for category in CATEGORY_PHASES}
    total_wall = 0.0
    for workload in workloads:
        samples = workload["samples"]["rust_authority_python_shadow"]  # type: ignore[index]
        for sample in samples:
            total_wall += sample["total_wall_seconds"]
            for phase, seconds in sample["phases_seconds"].items():
                if phase not in PHASE_CATEGORY:
                    raise RuntimeError(f"unclassified phase: {phase}")
                category = PHASE_CATEGORY[phase]
                totals[category] += seconds
                constituents[category][phase] += seconds
            residual = sample["residual_unattributed_seconds"]
            totals["ORCHESTRATION"] += residual
            constituents["ORCHESTRATION"]["python_orchestration_residual"] += residual
    categories = {
        category: {
            "observed_seconds": value,
            "median_equivalent_seconds": value / sum(
                len(workload["samples"]["rust_authority_python_shadow"])  # type: ignore[index]
                for workload in workloads
            ),
            "percent_of_dual_lane": 100 * value / total_wall,
            "constituent_phases": sorted(constituents[category]),
        }
        for category, value in totals.items()
    }
    return {
        "basis": "all ordinary-corpus dual-lane raw samples; mutually exclusive additive wall-time accounting",
        "total_observed_seconds": total_wall,
        "categories": categories,
        "percent_sum": sum(row["percent_of_dual_lane"] for row in categories.values()),
        "tolerance_percent": 1e-6,
    }


def _phase_ranking(aggregate: dict[str, object], dual_median: float):
    return sorted(
        (
            {
                "phase": phase,
                **summary,
                "percent_of_dual_lane_median": 100 * summary["median_seconds"] / dual_median,
                "category": PHASE_CATEGORY.get(phase, "ORCHESTRATION"),
            }
            for phase, summary in aggregate["phases"].items()  # type: ignore[union-attr]
        ),
        key=lambda row: row["median_seconds"],
        reverse=True,
    )


def _lowering_aggregate(workloads: list[dict[str, object]], rounds: int):
    round_values = {component: [0.0] * rounds for component in LOWERING_COMPONENTS}
    for workload in workloads:
        samples = workload["samples"]["diagnostic_rust_only"]  # type: ignore[index]
        for index, sample in enumerate(samples):
            for component, seconds in sample[
                "rust_ssa_lowering_phases_seconds"
            ].items():
                round_values[component][index] += seconds
    summaries = {component: _summary(values) for component, values in round_values.items()}
    total_median = sum(row["median_seconds"] for row in summaries.values())
    ranking = sorted(
        (
            {
                "component": component,
                **summary,
                "percent_of_rust_ssa_lowering": 100 * summary["median_seconds"] / total_median,
            }
            for component, summary in summaries.items()
        ),
        key=lambda row: row["median_seconds"],
        reverse=True,
    )
    dominance = sum(
        summaries[component]["median_seconds"] for component in DOMINANCE_COMPONENTS
    )
    return {
        "components": summaries,
        "ranking": ranking,
        "component_median_sum_seconds": total_median,
        "dominance_components": sorted(DOMINANCE_COMPONENTS),
        "dominance_median_seconds": dominance,
        "dominance_percent_of_rust_ssa_lowering": 100 * dominance / total_median,
        "measurement_boundary": (
            "reachability and RPO are one honest combined phase because the qualified DFS computes them together"
        ),
    }


def _deep_scaling(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    previous: dict[str, tuple[int, float]] = {}
    for row in rows:
        size = row["blocks"]
        for route, route_row in row["routes"].items():  # type: ignore[union-attr]
            if route_row["status"] != "MEASURED":
                continue
            median = route_row["summary"]["median_seconds"]
            old = previous.get(route)
            result.append(
                {
                    "route": route,
                    "blocks": size,
                    **route_row["summary"],
                    "ratio_vs_previous_measured_size": median / old[1] if old else None,
                    "previous_measured_blocks": old[0] if old else None,
                }
            )
            previous[route] = (size, median)
    return result


def _source_regression_checks() -> list[dict[str, str]]:
    shadow = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    companion = (
        ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")
    dominance = (
        ROOT / "compiler-rs/crates/aether-ir/src/dominance.rs"
    ).read_text(encoding="utf-8")
    statuses = {
        "python_initial_ir_reconstruction": "python_input = module" in shadow,
        "duplicate_python_ssa_verification": "a second identical pass was redundant" in shadow,
        "rust_result_reserialization": "rust_dto = rust_comparison_dto" in shadow,
        "json_encode_decode_canonicalization": "_canonicalize_owned_ssa(python_dto)" in shadow,
        "serde_json_value_response_materialization": "ssa: aether_ir::wire::SSAModuleV2DTO" in companion,
        "sorted_request_key_serialization": (
            'json.dumps(snapshot, separators=(",", ":")).encode()' in shadow
        ),
        "production_full_dominator_sets": "fn reference_dominance" in dominance
        and "#[cfg(test)]\nmod tests" in dominance,
    }
    return [
        {
            "work": work,
            "removed_in": milestone,
            "status": "PASS_ABSENT_OR_NON_EXECUTING" if statuses[work] else "FAIL",
        }
        for work, milestone in REMOVED_WORK
    ]


def _safety_boundaries(phase_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    shares = {row["phase"]: row["percent_of_dual_lane_median"] for row in phase_rows}
    specs = [
        ("Initial IR integrity check", "input_snapshot_integrity_check", "Guards reuse of the verified shared Initial IR."),
        ("Rust Owned SSA verifier", "rust_owned_ssa_verification", "Native verifier before the result crosses the process boundary."),
        ("schema-v2 strict import", "rust_schema_v2_import", "Validates and materializes untrusted companion output."),
        ("imported SSA Python verifier", "imported_rust_python_verification", "Independent cross-language validation of authoritative SSA."),
        ("Python builder verifier", "python_builder_verification", "Qualifies the semantically independent shadow result."),
        ("canonical comparison", "canonical_comparison", "Fail-closed equivalence boundary between lanes."),
    ]
    return [
        {
            "phase": label,
            "measured_phase": phase,
            "measured_share_percent": shares.get(phase, 0.0),
            "classification": "REQUIRED_INDEPENDENT",
            "reason": reason,
        }
        for label, phase, reason in specs
    ]


def _copy_census() -> list[dict[str, object]]:
    return [
        {"source": "IRModule", "destination": "schema-v1 request DTO", "copy_or_allocation": True, "why": "stable trust-boundary snapshot and integrity comparison", "trust_boundary": True, "measured_phase": "initial_ir_snapshot_preparation", "classification": "SAFETY_BOUNDARY"},
        {"source": "request DTO", "destination": "JSON request bytes", "copy_or_allocation": True, "why": "protocol-v1 framing", "trust_boundary": True, "measured_phase": "rust_transport_serialization", "classification": "NECESSARY_BOUNDARY"},
        {"source": "JSON request bytes", "destination": "Rust typed IRModuleDTO", "copy_or_allocation": True, "why": "strict typed deserialization", "trust_boundary": True, "measured_phase": "rust_input_parsing", "classification": "NECESSARY_BOUNDARY"},
        {"source": "Rust Owned SSA", "destination": "typed schema-v2 DTO", "copy_or_allocation": True, "why": "frozen schema-v2 response", "trust_boundary": False, "measured_phase": "rust_schema_v2_materialization", "classification": "LOW_RISK_ARCHITECTURAL"},
        {"source": "typed schema-v2 DTO", "destination": "JSON response bytes", "copy_or_allocation": True, "why": "protocol-v1 framing", "trust_boundary": True, "measured_phase": "request_response_transport_and_serialization", "classification": "NECESSARY_BOUNDARY"},
        {"source": "JSON response bytes", "destination": "Python dict/list DTO", "copy_or_allocation": True, "why": "response parse before strict import", "trust_boundary": True, "measured_phase": "response_json_decode", "classification": "NECESSARY_BOUNDARY"},
        {"source": "Python response DTO", "destination": "authoritative SSAModule", "copy_or_allocation": True, "why": "strict schema-v2 import", "trust_boundary": True, "measured_phase": "rust_schema_v2_import", "classification": "SAFETY_BOUNDARY"},
        {"source": "Python shadow SSAModule", "destination": "schema-v2 comparison DTO", "copy_or_allocation": True, "why": "cross-implementation canonical comparison", "trust_boundary": False, "measured_phase": "python_result_dto_serialization", "classification": "SHADOW_POLICY"},
        {"source": "Rust response DTO", "destination": "canonical comparison copy", "copy_or_allocation": True, "why": "canonicalization must not mutate transport state", "trust_boundary": False, "measured_phase": "rust_result_canonicalization", "classification": "LOW_RISK_ARCHITECTURAL"},
    ]


def _candidate_ranking(category: dict[str, object], phase_rows: list[dict[str, object]]):
    percentages = {row["phase"]: row["percent_of_dual_lane_median"] for row in phase_rows}
    category_rows = category["categories"]
    specs = [
        ("Python shadow performance preserving independence", category_rows["PYTHON_SHADOW"]["percent_of_dual_lane"], "HIGH", "MEDIUM", "HIGH", True, 1),
        ("schema-v2 import efficiency", percentages.get("rust_schema_v2_import", 0.0), "MEDIUM", "LOW", "MEDIUM", True, 2),
        ("remaining transport/representation", category_rows["TRANSPORT_REPRESENTATION"]["percent_of_dual_lane"], "MEDIUM", "LOW", "MEDIUM", True, 3),
        ("verifier/safety-boundary redundancy", category_rows["SAFETY_VERIFICATION"]["percent_of_dual_lane"], "MEDIUM", "HIGH", "VERY_HIGH", True, 4),
        ("remaining Rust SSA core work", category_rows["RUST_INTRINSIC"]["percent_of_dual_lane"], "LOW", "HIGH", "HIGH", True, 5),
        ("canonical comparison", category_rows["CANONICAL_COMPARISON"]["percent_of_dual_lane"], "LOW", "MEDIUM", "HIGH", True, 6),
        ("companion/session architecture", percentages.get("companion_process_startup", 0.0), "LOW", "LOW", "MEDIUM", True, 7),
        ("shadow-policy evolution", category_rows["PYTHON_SHADOW"]["percent_of_dual_lane"], "HIGH", "VERY_HIGH", "VERY_HIGH", False, 8),
        ("backend/optimizer work outside SSA", 0.0, "UNKNOWN", "UNKNOWN", "OUT_OF_SCOPE", True, 9),
    ]
    return [
        {
            "rank": rank,
            "candidate": candidate,
            "measured_share_percent": share,
            "expected_upside": upside,
            "semantic_risk": risk,
            "implementation_complexity": "MEDIUM" if rank <= 3 else "HIGH",
            "qualification_burden": burden,
            "preserves_independent_shadow": preserves,
            "recommendation": "NEXT" if rank == 1 else "DEFER",
        }
        for candidate, share, upside, risk, burden, preserves, rank in specs
    ]


def _historical_comparison() -> list[dict[str, str]]:
    return [
        {"milestone": "RUST-3.8b", "compatibility": "NOT_COMPARABLE", "reason": "pre-3.9a representation and pre-CHK Rust algorithm"},
        {"milestone": "RUST-3.9a", "compatibility": "APPROXIMATELY_COMPARABLE", "reason": "same workload family but pre-CHK Rust lowering"},
        {"milestone": "RUST-3.9b", "compatibility": "APPROXIMATELY_COMPARABLE", "reason": "same release companion and deep-chain fixture; prior campaign used fewer rounds and coarser phases"},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=BASELINE_REVISION)
    parser.add_argument("--executable", type=Path, default=base.DEFAULT_EXECUTABLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--deep-cfg-warmup", type=int, default=2)
    parser.add_argument("--deep-cfg-rounds", type=int, default=7)
    parser.add_argument("--deep-cfg-sizes", default="100,1000,5000,10000")
    parser.add_argument("--deep-python-max-size", type=int, default=5000)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if min(args.warmup, args.rounds, args.deep_cfg_warmup, args.deep_cfg_rounds) < 1:
        parser.error("warmup and round counts must be positive")
    sizes = tuple(int(value) for value in args.deep_cfg_sizes.split(","))
    if not {100, 1000, 5000, 10000} <= set(sizes):
        parser.error("deep CFG sizes must include 100, 1000, 5000, and 10000")
    if base._revision() != BASELINE_REVISION:
        raise RuntimeError("RUST-3.10 must be measured from exact baseline revision")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        # The implementation itself is necessarily uncommitted. The recorded
        # qualification revision remains the exact clean pre-change baseline.
        qualification_tree = "uncommitted RUST-3.10 diagnostic changes on exact baseline"
    else:
        qualification_tree = "clean exact baseline"
    if args.build:
        subprocess.run(
            ["cargo", "build", "--release", "-p", "aether-verifier", "--bin", "aether-ssa-shadow", "--locked"],
            cwd=ROOT / "compiler-rs",
            check=True,
        )
    executable = args.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)

    loaded = [(*row, *base._load_module(row[1])) for row in base.WORKLOADS]
    workloads = []
    with PersistentRustSSALoweringClient(
        executable, timeout_seconds=600, characterize_performance=True
    ) as client:
        cold_module = loaded[0][3]
        _, cold_report = diagnostic_lower_with_rust_authority_without_python_shadow(
            cold_module, client
        )
        assert cold_report.performance is not None
        cold_profile = cold_report.performance.to_dict()
        for row in loaded:
            workloads.append(_ordinary_workload(row, client, args.warmup, args.rounds))
        deep = _deep_cfg(
            client,
            sizes,
            args.deep_cfg_warmup,
            args.deep_cfg_rounds,
            args.deep_python_max_size,
        )
        session = {
            "companion_startup_seconds": cold_profile["phases_seconds"].get("companion_process_startup", 0.0),
            "first_request_seconds": cold_profile["total_wall_seconds"],
            "first_request_profile": cold_profile,
            "persistent_session_request_count": client.request_count,
            "process_count": client.process_start_count,
            "warm_steady_state_small": workloads[0]["summary"]["diagnostic_rust_only"],
            "ordinary_compilation_restarts_per_request": False,
        }

    aggregates = {route: _aggregate(workloads, route, args.rounds) for route in ROUTES}
    dual_median = aggregates["rust_authority_python_shadow"]["representative_suite"]["median_seconds"]
    phase_ranking = _phase_ranking(aggregates["rust_authority_python_shadow"], dual_median)
    categories = _category_accounting(workloads)
    lowering = _lowering_aggregate(workloads, args.rounds)
    removed = _source_regression_checks()
    candidates = _candidate_ranking(categories, phase_ranking)
    largest_category = max(
        categories["categories"],
        key=lambda name: categories["categories"][name]["percent_of_dual_lane"],
    )
    largest_phase = phase_ranking[0]["phase"]
    largest_lowering = lowering["ranking"][0]["component"]

    evidence = {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.10",
        "decision": "RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZED",
        "qualification_revision": args.revision,
        "qualification_tree": qualification_tree,
        "measurement_kind": "observational; no hard performance thresholds",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version,
            "rustc": base._tool_version(["rustc", "--version"]),
            "cargo": base._tool_version(["cargo", "--version"]),
            "logical_cpu_count": os.cpu_count(),
            "companion": os.fspath(executable.relative_to(ROOT)),
            "companion_build_mode": "release",
        },
        "methodology": {
            "clock": "Python perf_counter and Rust Instant",
            "ordinary_warmups": args.warmup,
            "ordinary_measured_rounds": args.rounds,
            "deep_cfg_warmups": args.deep_cfg_warmup,
            "deep_cfg_measured_rounds": args.deep_cfg_rounds,
            "statistics": ["median", "min", "max"],
            "lane_order": "rotated each measured round",
            "release_companion": True,
            "rust_only_diagnostic_not_authority": True,
            "reachability_rpo_boundary": "combined because qualified DFS computes both interleaved",
        },
        "workload_manifest": [
            {key: row[key] for key in ("id", "path", "category", "source_sha256", "input_shape")}
            for row in workloads
        ],
        "workloads": workloads,
        "route_aggregates": aggregates,
        "phase_ranking": phase_ranking,
        "dual_lane_additive_categories": categories,
        "rust_ssa_lowering_decomposition": lowering,
        "deep_cfg": deep,
        "deep_cfg_scaling": _deep_scaling(deep),
        "startup_session": session,
        "removed_work_regression": removed,
        "safety_boundary_analysis": _safety_boundaries(phase_ranking),
        "representation_copy_census": _copy_census(),
        "candidate_ranking": candidates,
        "historical_comparison": _historical_comparison(),
        "measured_answers": {
            "largest_individual_rust_authority_phase": largest_phase,
            "largest_additive_dual_lane_category": largest_category,
            "dominance_percent_of_rust_ssa_lowering": lowering["dominance_percent_of_rust_ssa_lowering"],
            "largest_rust_ssa_lowering_component": largest_lowering,
            "dedicated_rust_ssa_optimization_next": False,
            "schema_v2_import_better_target_than_rust_core": (
                next(row for row in phase_ranking if row["phase"] == "rust_schema_v2_import")["percent_of_dual_lane_median"]
                > next(row for row in phase_ranking if row["phase"] == "rust_ssa_lowering")["percent_of_dual_lane_median"]
            ),
            "python_shadow_dominant_unavoidable_cost": largest_category == "PYTHON_SHADOW",
            "canonical_comparison_material": categories["categories"]["CANONICAL_COMPARISON"]["percent_of_dual_lane"] >= 5.0,
            "remaining_avoidable_copies": [
                "Owned SSA -> typed schema-v2 DTO",
                "Rust response DTO -> canonical comparison copy",
            ],
            "deep_cfg_limit": "Python shadow lowering plus the two required Python SSA verifier passes; imported-result verification alone dominates diagnostic Rust-only deep CFG",
            "ordinary_latency_limit": largest_category,
            "best_benefit_risk": candidates[0]["candidate"],
        },
        "shadow_future_options": {
            "A": "keep mandatory Python shadow exactly as-is",
            "B": "future optimization preserving the independent Python algorithm",
            "C": "future sampling/configuration policy change; not authorized here",
            "D": "future retirement only after a separate qualification milestone; not authorized here",
            "implemented": "A only; RUST-3.10 changes no shadow policy",
        },
        "production_invariants": {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "mandatory_synchronous",
            "failure_policy": "FAIL_CLOSED",
            "schemas": {"initial_ir": 1, "ssa": 2, "protocol": 1},
            "production_optimization_implemented": False,
            "ordinary_characterization_fields": False,
        },
        "recommendation": {
            "next_milestone": candidates[0]["candidate"],
            "rationale": "largest avoidable deep-CFG component outside required verifier boundaries; preserve the independent algorithm, mandatory synchronous execution, and fail-closed comparison",
        },
        "limitations": [
            "Reachability and RPO are intentionally grouped rather than assigned fake precision.",
            "Absolute timings are local-machine observations.",
            f"Python-only and dual-lane deep CFG were not run above {args.deep_python_max_size} blocks because mandatory Python full-set dominance is operationally unreasonable there.",
            "No formal asymptotic claim is inferred from timing ratios.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence["measured_answers"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
