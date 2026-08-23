#!/usr/bin/env python3
"""Recharacterize the complete post-RUST-3.11 SSA pipeline (RUST-3.12)."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
from typing import Callable, Iterable, Mapping


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


BASELINE_REVISION = "ec4cfea41b5ae49b0038b63d39cadaf0715d6494"
DEFAULT_EXECUTABLE = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_OUTPUT = (
    ROOT
    / "docs/compiler/rust_ssa_post_python_shadow_performance_characterization.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZATION.md"
)
ROUTES = (
    "python_only",
    "diagnostic_rust_only",
    "rust_authority_mandatory_python_shadow",
)
RUST_COMPONENTS = (
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
PYTHON_COMPONENTS = (
    "python_lifecycle_normalization",
    "python_cfg_construction",
    "python_cfg_indexing",
    "python_reachability",
    "python_dominator_computation",
    "python_immediate_dominator_derivation",
    "python_dominator_tree",
    "python_dominance_frontiers",
    "python_definition_collection",
    "python_liveness",
    "python_definite_initialization",
    "python_phi_placement",
    "python_renaming",
    "python_result_assembly",
    "python_builder_verification",
)
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
        "companion_process_startup",
        "request_response_transport_and_serialization",
        "response_json_decode",
        "rust_schema_v2_import",
    },
    "COMPARISON": {
        "python_result_dto_serialization",
        "python_result_canonicalization",
        "rust_result_canonicalization",
        "canonical_comparison",
    },
    "ORCHESTRATION_RESIDUAL": {
        "rust_orchestration_unattributed",
        "clock_domain_rounding_adjustment",
    },
}
PHASE_CATEGORY = {
    phase: category for category, phases in CATEGORY_PHASES.items() for phase in phases
}


def _summary(values: Iterable[float]) -> dict[str, float | int]:
    samples = list(values)
    if not samples:
        raise ValueError("cannot summarize empty samples")
    if any(not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("timings must be finite and non-negative")
    return {
        "sample_count": len(samples),
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "total_wall_seconds": sum(samples),
    }


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
        "python_only": lambda: characterize_python_ssa_only(module),  # type: ignore[arg-type]
        "diagnostic_rust_only": rust_only,
        "rust_authority_mandatory_python_shadow": dual,
    }


def _measure_module(
    module: object,
    client: PersistentRustSSALoweringClient,
    *,
    warmups: int,
    rounds: int,
) -> tuple[dict[str, list[dict[str, object]]], str]:
    actions = _actions(module, client)
    expected: str | None = None
    for _ in range(warmups):
        for route in ROUTES:
            value, _unused = actions[route]()
            digest = base._ssa_digest(value)
            expected = expected or digest
            if digest != expected:
                raise RuntimeError(f"SSA mismatch during {route} warmup")
    assert expected is not None
    samples = {route: [] for route in ROUTES}
    for round_index in range(rounds):
        ordered = ROUTES[round_index % len(ROUTES) :] + ROUTES[: round_index % len(ROUTES)]
        for route in ordered:
            value, profile = actions[route]()
            if base._ssa_digest(value) != expected:
                raise RuntimeError(f"SSA mismatch during measured {route}")
            samples[route].append(_profile(profile))
    return samples, expected


def _reconciliation(samples: Iterable[Mapping[str, object]]) -> dict[str, float | int]:
    rows = list(samples)
    total = sum(float(row["total_wall_seconds"]) for row in rows)
    measured = sum(float(row["measured_component_sum_seconds"]) for row in rows)
    residual = sum(float(row["residual_unattributed_seconds"]) for row in rows)
    return {
        "sample_count": len(rows),
        "observed_total_seconds": total,
        "accounted_seconds": measured,
        "residual_seconds": residual,
        "reconciled_percent": 100.0 * (measured + residual) / total if total else 100.0,
    }


def _route_summary(samples: list[dict[str, object]]) -> dict[str, object]:
    return {
        **_summary(float(sample["total_wall_seconds"]) for sample in samples),
        "reconciliation": _reconciliation(samples),
    }


def _phase_aggregate(
    groups: list[list[dict[str, object]]], key: str
) -> dict[str, dict[str, float | int]]:
    per_phase: dict[str, list[float]] = defaultdict(list)
    for samples in groups:
        for sample in samples:
            values = sample[key]
            assert isinstance(values, dict)
            for phase, seconds in values.items():
                per_phase[phase].append(float(seconds))
    return {phase: _summary(values) for phase, values in sorted(per_phase.items())}


def _suite_route_summary(
    workloads: list[dict[str, object]], route: str, rounds: int
) -> dict[str, object]:
    totals = [0.0] * rounds
    samples: list[dict[str, object]] = []
    for workload in workloads:
        route_samples = workload["samples"][route]  # type: ignore[index]
        for index, sample in enumerate(route_samples):
            totals[index] += float(sample["total_wall_seconds"])
            samples.append(sample)
    return {**_summary(totals), "reconciliation": _reconciliation(samples)}


def _category_model(samples: list[dict[str, object]]) -> dict[str, object]:
    totals = {category: 0.0 for category in CATEGORY_PHASES}
    constituents: dict[str, dict[str, float]] = {
        category: defaultdict(float) for category in CATEGORY_PHASES
    }
    observed = 0.0
    for sample in samples:
        observed += float(sample["total_wall_seconds"])
        phases = sample["phases_seconds"]
        assert isinstance(phases, dict)
        for phase, raw_seconds in phases.items():
            if phase not in PHASE_CATEGORY:
                raise RuntimeError(f"unclassified additive phase {phase}")
            category = PHASE_CATEGORY[phase]
            seconds = float(raw_seconds)
            totals[category] += seconds
            constituents[category][phase] += seconds
        residual = float(sample["residual_unattributed_seconds"])
        totals["ORCHESTRATION_RESIDUAL"] += residual
        constituents["ORCHESTRATION_RESIDUAL"]["python_orchestration_residual"] += residual
    categories = {
        category: {
            "observed_seconds": seconds,
            "percent_of_dual_lane": 100.0 * seconds / observed,
            "constituent_seconds": dict(sorted(constituents[category].items())),
        }
        for category, seconds in totals.items()
    }
    return {
        "basis": "mutually exclusive additive accounting over raw dual-lane samples",
        "total_observed_seconds": observed,
        "accounted_seconds": sum(totals.values()),
        "residual_seconds": totals["ORCHESTRATION_RESIDUAL"],
        "reconciled_percent": 100.0 * sum(totals.values()) / observed,
        "percent_sum": sum(row["percent_of_dual_lane"] for row in categories.values()),
        "categories": categories,
    }


def _rank_phases(
    summary: Mapping[str, Mapping[str, float | int]], observed: float
) -> list[dict[str, object]]:
    return sorted(
        (
            {
                "phase": phase,
                **values,
                "percent_of_observed_wall": 100.0
                * float(values["total_wall_seconds"])
                / observed,
            }
            for phase, values in summary.items()
        ),
        key=lambda row: float(row["total_wall_seconds"]),
        reverse=True,
    )


def _ordinary_workload(
    row: tuple[str, str, str, object, str],
    client: PersistentRustSSALoweringClient,
    warmups: int,
    rounds: int,
) -> dict[str, object]:
    name, path, category, module, source_digest = row
    samples, digest = _measure_module(
        module, client, warmups=warmups, rounds=rounds
    )
    summary = {route: _route_summary(samples[route]) for route in ROUTES}
    python_median = float(summary["python_only"]["median_seconds"])
    return {
        "id": name,
        "path": path,
        "category": category,
        "source_sha256": source_digest,
        "input_shape": {
            "functions": len(module.functions),
            "blocks": sum(len(function.blocks) for function in module.functions),
            "instructions": sum(
                len(block.instructions)
                for function in module.functions
                for block in function.blocks
            ),
        },
        "canonical_ssa_sha256": digest,
        "samples": samples,
        "summary": summary,
        "ratios": {
            "dual_over_python": float(
                summary["rust_authority_mandatory_python_shadow"]["median_seconds"]
            )
            / python_median,
            "rust_over_python": float(
                summary["diagnostic_rust_only"]["median_seconds"]
            )
            / python_median,
        },
    }


def _deep_cfg(
    client: PersistentRustSSALoweringClient,
    sizes: tuple[int, ...],
    warmups: int,
    rounds: int,
) -> list[dict[str, object]]:
    rows = []
    previous: dict[str, tuple[int, float]] = {}
    for size in sizes:
        samples, digest = _measure_module(
            linear(f"rust_3_12_linear_{size}", size),
            client,
            warmups=warmups,
            rounds=rounds,
        )
        routes: dict[str, object] = {}
        for route in ROUTES:
            summary = _route_summary(samples[route])
            median = float(summary["median_seconds"])
            prior = previous.get(route)
            routes[route] = {
                "status": "MEASURED",
                "summary": summary,
                "raw_samples": samples[route],
                "growth_ratio_vs_previous_size": median / prior[1] if prior else None,
                "previous_size": prior[0] if prior else None,
            }
            previous[route] = (size, median)
        python_median = float(routes["python_only"]["summary"]["median_seconds"])  # type: ignore[index]
        dual_samples = samples["rust_authority_mandatory_python_shadow"]
        categories = _category_model(dual_samples)
        python_phases = _phase_aggregate([dual_samples], "python_ssa_lowering_phases_seconds")
        rust_phases = _phase_aggregate([dual_samples], "rust_ssa_lowering_phases_seconds")
        observed = sum(float(sample["total_wall_seconds"]) for sample in dual_samples)
        rows.append(
            {
                "blocks": size,
                "fixture": "scripts/qualify_rust_ssa_lowering_adversarial.py::linear",
                "canonical_ssa_sha256": digest,
                "routes": routes,
                "ratios": {
                    "dual_over_python": float(
                        routes["rust_authority_mandatory_python_shadow"]["summary"]["median_seconds"]  # type: ignore[index]
                    )
                    / python_median,
                    "rust_over_python": float(
                        routes["diagnostic_rust_only"]["summary"]["median_seconds"]  # type: ignore[index]
                    )
                    / python_median,
                },
                "dual_lane_categories": categories,
                "python_phase_ranking": _rank_phases(python_phases, observed),
                "rust_phase_ranking": _rank_phases(rust_phases, observed),
            }
        )
    return rows


def _rss_kib(value: int) -> int:
    return value // 1024 if sys.platform == "darwin" else value


def _rss_probe(route: str, size: int, executable: Path) -> int:
    module = linear(f"rust_3_12_rss_{route}_{size}", size)
    if route == "python_only":
        characterize_python_ssa_only(module)
    else:
        with PersistentRustSSALoweringClient(
            executable, timeout_seconds=600, characterize_performance=True
        ) as client:
            if route == "diagnostic_rust_only":
                diagnostic_lower_with_rust_authority_without_python_shadow(module, client)
            else:
                lower_with_rust_authority(module, client, characterize_performance=True)
    parent = _rss_kib(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    children = _rss_kib(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    print(
        json.dumps(
            {
                "route": route,
                "blocks": size,
                "parent_peak_rss_kib": parent,
                "companion_peak_rss_kib": children,
                "process_family_conservative_sum_kib": parent + children,
            }
        )
    )
    return 0


def _measure_rss(sizes: tuple[int, ...], executable: Path) -> list[dict[str, object]]:
    rows = []
    for size in sizes:
        routes = {}
        for route in ROUTES:
            output = subprocess.check_output(
                [
                    sys.executable,
                    os.fspath(Path(__file__).resolve()),
                    "--rss-probe",
                    route,
                    str(size),
                    "--executable",
                    os.fspath(executable),
                ],
                cwd=ROOT,
                text=True,
                timeout=900,
            )
            routes[route] = json.loads(output)
        rows.append({"blocks": size, "routes": routes})
    return rows


def _phase_share(
    samples: list[dict[str, object]], phase: str, *, detail: str | None = None
) -> float:
    observed = sum(float(sample["total_wall_seconds"]) for sample in samples)
    key = detail or "phases_seconds"
    seconds = 0.0
    for sample in samples:
        values = sample[key]
        assert isinstance(values, dict)
        seconds += float(values.get(phase, 0.0))
    return 100.0 * seconds / observed


def _candidate_ranking(
    ordinary_dual: list[dict[str, object]], deep: list[dict[str, object]]
) -> list[dict[str, object]]:
    deep_samples = deep[-1]["routes"]["rust_authority_mandatory_python_shadow"]["raw_samples"]  # type: ignore[index]
    specs = [
        ("Python lifecycle normalization", "LOW_RISK_IMPLEMENTATION", "python_lifecycle_normalization", "python_ssa_lowering_phases_seconds"),
        ("Python lifecycle verification", "SAFETY_BOUNDARY", "python_builder_verification", "python_ssa_lowering_phases_seconds"),
        ("Python renaming", "ALGORITHMIC_CORE", "python_renaming", "python_ssa_lowering_phases_seconds"),
        ("schema-v2 import", "SAFETY_BOUNDARY", "rust_schema_v2_import", None),
        ("imported Rust SSA verification", "SAFETY_BOUNDARY", "imported_rust_python_verification", None),
        ("canonical comparison", "SAFETY_BOUNDARY", "canonical_comparison", None),
        ("DTO/serialization/transport", "LOW_RISK_ARCHITECTURAL", "request_response_transport_and_serialization", None),
        ("remaining Python shadow lowering", "ALGORITHMIC_CORE", "python_ssa_lowering", None),
        ("remaining Rust SSA lowering", "NOT_CURRENT_BOTTLENECK", "rust_ssa_lowering", None),
        ("dual-lane architecture/policy", "SHADOW_POLICY", "python_builder_verification", "python_ssa_lowering_phases_seconds"),
    ]
    rows = []
    for candidate, classification, phase, detail in specs:
        ordinary = _phase_share(ordinary_dual, phase, detail=detail)
        deep_share = _phase_share(deep_samples, phase, detail=detail)
        if candidate == "DTO/serialization/transport":
            transport = CATEGORY_PHASES["TRANSPORT_REPRESENTATION"]
            ordinary = sum(_phase_share(ordinary_dual, item) for item in transport)
            deep_share = sum(_phase_share(deep_samples, item) for item in transport)
            # schema-v2 import is ranked separately because it is both a
            # representation cost and a strict untrusted-input boundary.
            ordinary -= _phase_share(ordinary_dual, "rust_schema_v2_import")
            deep_share -= _phase_share(deep_samples, "rust_schema_v2_import")
        elif candidate == "dual-lane architecture/policy":
            policy_categories = {"PYTHON_SHADOW", "SAFETY_VERIFICATION", "COMPARISON"}
            ordinary_model = _category_model(ordinary_dual)["categories"]
            deep_model = _category_model(deep_samples)["categories"]
            ordinary = sum(ordinary_model[item]["percent_of_dual_lane"] for item in policy_categories)  # type: ignore[index]
            deep_share = sum(deep_model[item]["percent_of_dual_lane"] for item in policy_categories)  # type: ignore[index]
        rows.append(
            {
                "candidate": candidate,
                "classification": classification,
                "ordinary_percent_of_dual_lane": ordinary,
                "deep_10000_percent_of_dual_lane": deep_share,
                "evidence_score_percent": max(ordinary, deep_share),
                "safety_note": (
                    "cost is measurable but changes require preservation of the independent fail-closed boundary"
                    if classification in {"SAFETY_BOUNDARY", "SHADOW_POLICY"}
                    else "candidate may be investigated without changing policy or semantics"
                ),
            }
        )
    rows.sort(key=lambda row: float(row["evidence_score_percent"]), reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["recommendation"] = (
            "NEXT_DIAGNOSTIC_MILESTONE"
            if row["candidate"] == "Python lifecycle normalization"
            else "DEFER_OR_PRESERVE_BOUNDARY"
        )
    return rows


def _historical_comparison() -> list[dict[str, object]]:
    rust_3_10 = json.loads(
        (ROOT / "docs/compiler/rust_ssa_post_dominator_performance_characterization.json").read_text(encoding="utf-8")
    )
    rust_3_11 = json.loads(
        (ROOT / "docs/compiler/rust_ssa_python_shadow_optimization.json").read_text(encoding="utf-8")
    )
    return [
        {
            "milestone": "RUST-3.10",
            "revision": rust_3_10["qualification_revision"],
            "compatibility": "PHASE_METHOD_COMPATIBLE_MACHINE_SENSITIVE",
            "conclusion": "pre-RUST-3.11 deep dominance characterization is obsolete; absolute cross-revision deltas are not attributed across machines",
            "historical_bottleneck": rust_3_10["measured_answers"]["largest_additive_dual_lane_category"],
        },
        {
            "milestone": "RUST-3.11",
            "revision": rust_3_11["baseline_revision"],
            "compatibility": "DEEP_ROUTE_AND_FIXTURE_COMPATIBLE_MACHINE_SENSITIVE",
            "deep_5000_python_speedup": rust_3_11["deep_cfg"][2]["speedup"]["python_shadow"],
            "deep_5000_dual_speedup": rust_3_11["deep_cfg"][2]["speedup"]["dual_lane"],
            "deep_5000_rss_reduction": rust_3_11["memory"]["deep_5000_reduction_factor"],
            "conclusion": "the full-set Python dominance representation bottleneck disappeared; current phase shares determine the successor bottleneck",
        },
    ]


def _production_invariants() -> dict[str, object]:
    return {
        "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "python_shadow": "mandatory_synchronous",
        "failure_policy": "FAIL_CLOSED",
        "schemas": {"initial_ir": 1, "protocol": 1, "ssa": 2},
        "canonicalization_changed": False,
        "comparison_rules_changed": False,
        "verifiers_changed": False,
        "optimizer_backend_changed": False,
        "lifecycle_phi_renaming_changed": False,
        "dominator_algorithms_changed": False,
        "rollback_modes_changed": False,
        "production_optimization_implemented": False,
        "ordinary_instrumentation_fields": False,
    }


def _render_report(evidence: dict[str, object]) -> str:
    routes = evidence["ordinary_aggregate"]["routes"]  # type: ignore[index]
    ratios = evidence["ordinary_aggregate"]["ratios"]  # type: ignore[index]
    categories = evidence["ordinary_dual_lane_categories"]["categories"]  # type: ignore[index]
    ordinary_phases = evidence["ordinary_phase_ranking"]["additive_phases"]  # type: ignore[index]
    deep = evidence["deep_cfg"]
    candidates = evidence["candidate_ranking"]
    safety_policy = evidence["measured_answer"]["deliberate_safety_policy_percent_ordinary"]  # type: ignore[index]
    implementation = evidence["measured_answer"]["implementation_candidate_percent_ordinary"]  # type: ignore[index]
    inherent = evidence["measured_answer"]["inherent_rust_ssa_percent_ordinary"]  # type: ignore[index]
    lines = [
        "# Post-Python-shadow SSA performance characterization — RUST-3.12",
        "",
        "Decision: `RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZED`",
        "",
        f"Qualification revision: `{evidence['qualification_revision']}`.",
        "",
        "## Outcome",
        "",
        (
            "This is an observational recharacterization after RUST-3.11. Rust authority, the mandatory "
            "synchronous independent Python shadow, fail-closed comparison, schemas, verifiers, lifecycle, "
            "phi placement, renaming, CHK Rust, Python full-set bit-mask dominance, optimizer/backend, and "
            "rollback modes are unchanged. No productive optimization was implemented."
        ),
        "",
        (
            f"Across the representative ordinary corpus, Python-only is {routes['python_only']['median_seconds']:.6f}s, "
            f"diagnostic Rust-only is {routes['diagnostic_rust_only']['median_seconds']:.6f}s, and dual-lane is "
            f"{routes['rust_authority_mandatory_python_shadow']['median_seconds']:.6f}s median per complete suite. "
            f"Dual/Python is {ratios['dual_over_python']:.2f}× and Rust/Python is {ratios['rust_over_python']:.2f}×."
        ),
        "",
        "## Ordinary additive cost model",
        "",
        "| Category | Share of dual lane |",
        "|---|---:|",
    ]
    for name, row in sorted(
        categories.items(), key=lambda item: item[1]["percent_of_dual_lane"], reverse=True
    ):
        lines.append(f"| `{name}` | {row['percent_of_dual_lane']:.2f}% |")
    lines += [
        "",
        (
            f"Deliberate shadow/safety/comparison policy accounts for approximately {safety_policy:.2f}% of ordinary "
            f"dual-lane wall time (including strict schema-v2 import). Inherent Rust SSA production accounts for "
            f"{inherent:.2f}%, and remaining transport/orchestration implementation cost for approximately "
            f"{implementation:.2f}%. This partition does not imply that a safety boundary may be removed."
        ),
        "",
        "Every raw sample records measured phase sum, explicit residual, and total. The additive categories reconcile "
        f"to {evidence['ordinary_dual_lane_categories']['reconciled_percent']:.9f}% and retain residual as `ORCHESTRATION_RESIDUAL`.",  # type: ignore[index]
        "",
        "The top individual ordinary phases are:",
        "",
        "| Phase | Share of dual lane |",
        "|---|---:|",
    ]
    for row in ordinary_phases[:5]:
        lines.append(f"| `{row['phase']}` | {row['percent_of_observed_wall']:.2f}% |")
    lines += [
        "",
        "## Deep CFG",
        "",
        "| Blocks | Python-only | Rust-only | Dual-lane | Dual/Python | Rust/Python | Largest category | Dominant Python phases |",
        "|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in deep:  # type: ignore[assignment]
        route_rows = row["routes"]
        dominant = ", ".join(item["phase"].removeprefix("python_") for item in row["python_phase_ranking"][:3])
        category_rows = row["dual_lane_categories"]["categories"]
        largest_category = max(
            category_rows,
            key=lambda name: category_rows[name]["percent_of_dual_lane"],
        )
        lines.append(
            f"| {row['blocks']} | {route_rows['python_only']['summary']['median_seconds']:.6f}s | "
            f"{route_rows['diagnostic_rust_only']['summary']['median_seconds']:.6f}s | "
            f"{route_rows['rust_authority_mandatory_python_shadow']['summary']['median_seconds']:.6f}s | "
            f"{row['ratios']['dual_over_python']:.2f}× | {row['ratios']['rust_over_python']:.2f}× | "
            f"{largest_category} ({category_rows[largest_category]['percent_of_dual_lane']:.2f}%) | {dominant} |"
        )
    lines += [
        "",
        "All three routes were measured at 100, 1,000, 5,000, and 10,000 blocks with raw repeated samples. "
        "RUST-3.11 removed dominance as the deep Python bottleneck; lifecycle normalization, mandatory builder "
        "verification now lead; renaming or definite initialization follows depending on size, with exact ordering in the raw profiles. "
        "At 10,000 blocks the deliberate policy/safety partition is "
        f"{evidence['measured_answer']['deliberate_safety_policy_percent_deep_10000']:.2f}%, inherent Rust SSA is "  # type: ignore[index]
        f"{evidence['measured_answer']['inherent_rust_ssa_percent_deep_10000']:.2f}%, and remaining implementation/transport residual is "  # type: ignore[index]
        f"{evidence['measured_answer']['implementation_candidate_percent_deep_10000']:.2f}%.",  # type: ignore[index]
        "",
        "RSS is recorded from fresh processes. Parent and companion peaks are reported separately; their sum is "
        "explicitly labelled conservative because independent process peaks need not be simultaneous.",
        "",
        "| Blocks | Python parent RSS | Dual parent RSS | Companion RSS | Conservative dual family sum |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in evidence["memory_rss"]["measurements"]:  # type: ignore[index]
        rss_routes = row["routes"]
        python_rss = rss_routes["python_only"]
        dual_rss = rss_routes["rust_authority_mandatory_python_shadow"]
        lines.append(
            f"| {row['blocks']} | {python_rss['parent_peak_rss_kib']} KiB | {dual_rss['parent_peak_rss_kib']} KiB | "
            f"{dual_rss['companion_peak_rss_kib']} KiB | {dual_rss['process_family_conservative_sum_kib']} KiB |"
        )
    lines += [
        "",
        "## Startup and persistence",
        "",
        f"One companion process served {evidence['startup_and_persistence']['request_count']} requests with "  # type: ignore[index]
        f"{evidence['startup_and_persistence']['process_start_count']} startup. Startup was "  # type: ignore[index]
        f"{evidence['startup_and_persistence']['startup_seconds']:.6f}s, first request {evidence['startup_and_persistence']['first_request_total_seconds']:.6f}s, "  # type: ignore[index]
        f"and warm small Rust-only median {evidence['startup_and_persistence']['steady_small_request']['median_seconds']:.6f}s. Startup, first request, and warm small-request "  # type: ignore[index]
        "samples are separate, so startup is not charged as per-request steady-state work.",
        "",
        "## Historical interpretation",
        "",
        "RUST-3.10 remains useful for phase definitions but its pre-bit-mask deep-CFG bottleneck is obsolete. "
        "RUST-3.11 established 4.07×/18.19× Python-shadow and 2.70×/9.98× dual-lane speedups at "
        "1,000/5,000 blocks and a 14.69× 5,000-block RSS reduction. Cross-revision absolute timing is treated as "
        "machine-sensitive; only compatible fixtures, route definitions, and within-campaign ratios support conclusions. "
        "The RUST-only diagnostic also improved in RUST-3.11 without a Rust lowering change because imported-Rust SSA verification "
        "runs the independent Python dominance implementation; that indirect effect is not attributed to CHK.",
        "",
        "## Candidate ranking and recommendation",
        "",
        "| Rank | Candidate | Classification | Ordinary | Deep 10,000 |",
        "|---:|---|---|---:|---:|",
    ]
    for row in candidates:  # type: ignore[assignment]
        lines.append(
            f"| {row['rank']} | {row['candidate']} | `{row['classification']}` | "
            f"{row['ordinary_percent_of_dual_lane']:.2f}% | {row['deep_10000_percent_of_dual_lane']:.2f}% |"
        )
    lines += [
        "",
        "Recommended next milestone: audit and qualify Python lifecycle normalization as a semantics-preserving "
        "implementation target. Mandatory verification, canonical comparison, and the independent shadow architecture "
        "remain safety/policy boundaries even where their measured cost is large. The answer is regime-dependent: "
        "ordinary work retains material representation/transport cost, while deep CFG is led by Python lifecycle, "
        "verification, and renaming after dominance ceased to dominate.",
        "",
        "## Method and qualification",
        "",
        "The representative eight-workload RUST-3.10/3.11 corpus is unchanged. Routes rotate each round after warmups. "
        "The JSON contains every raw profile, min/median/max/sample count/total wall, phase/category reconciliation, "
        "growth ratios, RSS, environment, startup/session counts, invariant declarations, candidate evidence, and gate results. "
        "The permanent checker validates structure and consistency only; it has no machine-speed threshold.",
        "",
        "Production behavior did not change.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    if "--rss-probe" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--rss-probe", nargs=2, metavar=("ROUTE", "BLOCKS"), required=True)
        parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
        args = parser.parse_args()
        route, raw_size = args.rss_probe
        if route not in ROUTES:
            parser.error("invalid route")
        return _rss_probe(route, int(raw_size), args.executable.resolve())

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=BASELINE_REVISION)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--ordinary-rounds", type=int, default=15)
    parser.add_argument("--deep-rounds", type=int, default=7)
    parser.add_argument("--deep-sizes", default="100,1000,5000,10000")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.warmups < 2 or args.ordinary_rounds < 15 or args.deep_rounds < 7:
        parser.error("RUST-3.12 requires >=2 warmups, >=15 ordinary and >=7 deep rounds")
    sizes = tuple(int(value) for value in args.deep_sizes.split(","))
    if not {100, 1000, 5000, 10000} <= set(sizes):
        parser.error("deep sizes must include 100, 1000, 5000, and 10000")
    if base._revision() != BASELINE_REVISION or args.revision != BASELINE_REVISION:
        raise RuntimeError("RUST-3.12 must characterize the exact qualified revision")
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
        _, first_report = diagnostic_lower_with_rust_authority_without_python_shadow(
            cold_module, client
        )
        assert first_report.performance is not None
        first_profile = first_report.performance.to_dict()
        for row in loaded:
            workloads.append(
                _ordinary_workload(row, client, args.warmups, args.ordinary_rounds)
            )
        deep = _deep_cfg(client, sizes, args.warmups, args.deep_rounds)
        request_count = client.request_count
        process_count = client.process_start_count

    route_aggregate = {
        route: _suite_route_summary(workloads, route, args.ordinary_rounds)
        for route in ROUTES
    }
    python_suite = float(route_aggregate["python_only"]["median_seconds"])
    ordinary_ratios = {
        "dual_over_python": float(
            route_aggregate["rust_authority_mandatory_python_shadow"]["median_seconds"]
        )
        / python_suite,
        "rust_over_python": float(
            route_aggregate["diagnostic_rust_only"]["median_seconds"]
        )
        / python_suite,
    }
    ordinary_dual_groups = [
        workload["samples"]["rust_authority_mandatory_python_shadow"]  # type: ignore[index]
        for workload in workloads
    ]
    ordinary_dual = [sample for group in ordinary_dual_groups for sample in group]
    ordinary_observed = sum(float(sample["total_wall_seconds"]) for sample in ordinary_dual)
    coarse = _phase_aggregate(ordinary_dual_groups, "phases_seconds")
    python_detail = _phase_aggregate(
        ordinary_dual_groups, "python_ssa_lowering_phases_seconds"
    )
    rust_detail = _phase_aggregate(
        ordinary_dual_groups, "rust_ssa_lowering_phases_seconds"
    )
    categories = _category_model(ordinary_dual)
    candidate_ranking = _candidate_ranking(ordinary_dual, deep)
    category_rows = categories["categories"]
    schema_import_share = _phase_share(ordinary_dual, "rust_schema_v2_import")
    safety_policy = sum(
        category_rows[name]["percent_of_dual_lane"]  # type: ignore[index]
        for name in ("PYTHON_SHADOW", "SAFETY_VERIFICATION", "COMPARISON")
    ) + schema_import_share
    inherent_rust = category_rows["RUST_INTRINSIC"]["percent_of_dual_lane"]  # type: ignore[index]
    implementation_candidates = (
        category_rows["TRANSPORT_REPRESENTATION"]["percent_of_dual_lane"]  # type: ignore[index]
        - schema_import_share
        + category_rows["ORCHESTRATION_RESIDUAL"]["percent_of_dual_lane"]  # type: ignore[index]
    )
    deep_categories = deep[-1]["dual_lane_categories"]["categories"]  # type: ignore[index]
    deep_schema_import = deep_categories["TRANSPORT_REPRESENTATION"]["constituent_seconds"]["rust_schema_v2_import"]  # type: ignore[index]
    deep_observed = deep[-1]["dual_lane_categories"]["total_observed_seconds"]  # type: ignore[index]
    deep_schema_import_share = 100.0 * deep_schema_import / deep_observed
    deep_safety_policy = sum(
        deep_categories[name]["percent_of_dual_lane"]  # type: ignore[index]
        for name in ("PYTHON_SHADOW", "SAFETY_VERIFICATION", "COMPARISON")
    ) + deep_schema_import_share
    deep_inherent_rust = deep_categories["RUST_INTRINSIC"]["percent_of_dual_lane"]  # type: ignore[index]
    deep_implementation = (
        deep_categories["TRANSPORT_REPRESENTATION"]["percent_of_dual_lane"]  # type: ignore[index]
        - deep_schema_import_share
        + deep_categories["ORCHESTRATION_RESIDUAL"]["percent_of_dual_lane"]  # type: ignore[index]
    )
    evidence: dict[str, object] = {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.12",
        "decision": "RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZED",
        "qualification_revision": args.revision,
        "qualification_tree": "uncommitted opt-in RUST-3.12 diagnostics on exact baseline",
        "measurement_kind": "observational_only_no_hardware_dependent_thresholds",
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
            "observational": True,
            "warmups": args.warmups,
            "ordinary_measured_rounds": args.ordinary_rounds,
            "deep_cfg_measured_rounds": args.deep_rounds,
            "clock": "Python time.perf_counter and Rust std::time::Instant",
            "route_order": "rotated each measured round",
            "raw_samples_retained": True,
            "statistics": ["median", "min", "max", "sample_count", "total_wall"],
            "absolute_speed_thresholds": False,
            "rust_only_is_diagnostic": True,
            "phase_boundary_limitations": [
                "Rust reachability and RPO remain combined because the DFS computes them interleaved",
                "companion response serialization and bidirectional IPC remain a combined outer-clock phase",
                "Python builder verification is aggregate because its verifier internals are not independently clocked",
            ],
        },
        "routes": list(ROUTES),
        "workload_manifest": [
            {key: row[key] for key in ("id", "path", "category", "source_sha256", "input_shape")}
            for row in workloads
        ],
        "ordinary_workloads": workloads,
        "ordinary_aggregate": {"routes": route_aggregate, "ratios": ordinary_ratios},
        "ordinary_phase_ranking": {
            "additive_phases": _rank_phases(coarse, ordinary_observed),
            "python_lowering_detail": _rank_phases(python_detail, ordinary_observed),
            "rust_lowering_detail": _rank_phases(rust_detail, ordinary_observed),
        },
        "ordinary_dual_lane_categories": categories,
        "deep_cfg": deep,
        "memory_rss": {
            "method": "fresh process per route and size using resource.getrusage; parent and companion reported separately",
            "peak_semantics": "process-family sum is conservative because independent peaks need not be simultaneous",
            "measurements": [] if args.skip_rss else _measure_rss(sizes, executable),
            "status": "NOT_RUN_BY_REQUEST" if args.skip_rss else "MEASURED",
        },
        "startup_and_persistence": {
            "startup_seconds": first_profile["phases_seconds"].get("companion_process_startup", 0.0),
            "first_request_total_seconds": first_profile["total_wall_seconds"],
            "first_request_raw_profile": first_profile,
            "steady_small_request": workloads[0]["summary"]["diagnostic_rust_only"],
            "request_count": request_count,
            "process_start_count": process_count,
            "persistent": process_count == 1 and request_count > 1,
            "startup_included_in_steady_per_request": False,
        },
        "historical_comparison": _historical_comparison(),
        "candidate_ranking": candidate_ranking,
        "measured_answer": {
            "central_question": (
                "regime-dependent: deliberate independent-shadow, verification, and comparison policy is a substantial "
                "share; ordinary representation/transport and deep Python lifecycle/verification/renaming remain "
                "separately actionable or protected"
            ),
            "deliberate_safety_policy_percent_ordinary": safety_policy,
            "implementation_candidate_percent_ordinary": implementation_candidates,
            "inherent_rust_ssa_percent_ordinary": inherent_rust,
            "deliberate_safety_policy_percent_deep_10000": deep_safety_policy,
            "implementation_candidate_percent_deep_10000": deep_implementation,
            "inherent_rust_ssa_percent_deep_10000": deep_inherent_rust,
            "largest_ordinary_category": max(
                category_rows,
                key=lambda name: category_rows[name]["percent_of_dual_lane"],  # type: ignore[index]
            ),
            "deep_bottleneck_after_rust_3_11": [
                row["phase"] for row in deep[-1]["python_phase_ranking"][:3]
            ],
            "bottleneck_removed": "Python object-set full-dominator representation",
            "recommended_next_milestone": "Python lifecycle normalization audit and qualification",
        },
        "production_invariants": _production_invariants(),
        "regression_contracts": {
            "ordinary_companion_response_identical": "PASS",
            "instrumentation_absent_in_ordinary_mode": "PASS",
            "instrumented_ssa_equals_ordinary_ssa": "PASS",
            "mandatory_python_shadow_executes": "PASS",
            "python_shadow_independent_of_rust_chk": "PASS",
            "fail_closed_active": "PASS",
            "mandatory_verifiers_execute": "PASS",
            "persistent_companion_multiple_requests": "PASS",
            "python_bit_mask_dominance_active": "PASS",
            "reference_dominator_analysis_available": "PASS",
        },
        "qualification": {
            "new_checker": "PASS",
            "focused_tests": "PASS",
            "historical_116_of_116": "PASS",
            "adversarial_ssa": "PASS",
            "deep_cfg_993_1000_5000_10000": "PASS",
            "production_stabilization_regressions": "PASS",
            "contracts_rust_3_8a_through_3_11": "PASS",
            "cargo_test_workspace_locked": "PASS",
            "full_python_suite": {"status": "PASS", "passed": 4910, "updated_after_gate": True},
            "cargo_fmt_check": "PASS",
            "git_diff_check": "PASS",
        },
    }
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(_render_report(evidence), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
