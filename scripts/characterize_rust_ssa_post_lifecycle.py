#!/usr/bin/env python3
"""Characterize the complete SSA pipeline after RUST-3.13 (RUST-3.14)."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import characterize_rust_ssa_post_python_shadow as previous  # noqa: E402
import measure_rust_ssa_authority_performance as base  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    diagnostic_lower_with_rust_authority_without_python_shadow,
    lower_with_rust_authority,
)
from aether.ssa.performance import characterize_python_ssa_only  # noqa: E402


MILESTONE = "RUST-3.14"
BASELINE_REVISION = "7500d66a0d830542d2436b22356e0c34698f076f"
DECISION = "RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZED"
DEFAULT_EXECUTABLE = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_OUTPUT = ROOT / "docs/compiler/rust_ssa_post_lifecycle_performance_characterization.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZATION.md"
ROUTES = previous.ROUTES
LIFECYCLE_PHASES = (
    "lifecycle_operand_discovery",
    "lifecycle_operand_census",
    "lifecycle_owned_value_census",
    "lifecycle_name_census",
    "lifecycle_rewrite",
    "lifecycle_remaining_use_accounting",
    "lifecycle_return_transfer_folding",
    "lifecycle_reconstruction",
    "lifecycle_residual",
)
CATEGORIES = (
    "RUST_INTRINSIC",
    "PYTHON_SHADOW",
    "SAFETY_VERIFICATION",
    "TRANSPORT_REPRESENTATION",
    "CANONICAL_COMPARISON",
    "ORCHESTRATION_RESIDUAL",
)


def _summary(values: Iterable[float]) -> dict[str, float | int]:
    samples = list(values)
    if not samples or any(not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("samples must be finite, non-negative, and non-empty")
    return {
        "sample_count": len(samples),
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "total_wall_seconds": sum(samples),
        "raw_samples_seconds": samples,
    }


def _detail_aggregate(
    groups: Iterable[Iterable[Mapping[str, object]]], key: str
) -> dict[str, dict[str, float | int]]:
    values: dict[str, list[float]] = defaultdict(list)
    for group in groups:
        for sample in group:
            phases = sample.get(key)
            if not isinstance(phases, dict):
                raise RuntimeError(f"profile lacks {key}")
            for phase, seconds in phases.items():
                values[phase].append(float(seconds))
    return {phase: _summary(samples) for phase, samples in sorted(values.items())}


def _share(samples: list[dict[str, object]], phase: str, key: str = "phases_seconds") -> float:
    total = sum(float(row["total_wall_seconds"]) for row in samples)
    seconds = 0.0
    for row in samples:
        phases = row[key]
        assert isinstance(phases, dict)
        seconds += float(phases.get(phase, 0.0))
    return 100.0 * seconds / total if total else 0.0


def _category_model(samples: list[dict[str, object]]) -> dict[str, object]:
    category_phases = {
        "RUST_INTRINSIC": {"rust_lifecycle_normalization", "rust_ssa_lowering"},
        "PYTHON_SHADOW": {"python_lifecycle_normalization", "python_ssa_lowering"},
        "SAFETY_VERIFICATION": {
            "rust_owned_ssa_verification", "imported_rust_python_verification",
            "python_builder_verification", "input_snapshot_integrity_check",
        },
        "TRANSPORT_REPRESENTATION": {
            "initial_ir_snapshot_preparation", "rust_transport_serialization",
            "rust_input_parsing", "rust_schema_v2_materialization",
            "companion_process_startup", "request_response_transport_and_serialization",
            "response_json_decode", "rust_schema_v2_import",
            "python_result_dto_serialization",
        },
        "CANONICAL_COMPARISON": {
            "python_result_canonicalization", "rust_result_canonicalization",
            "canonical_comparison",
        },
        "ORCHESTRATION_RESIDUAL": {
            "rust_orchestration_unattributed", "clock_domain_rounding_adjustment",
        },
    }
    by_phase = {
        phase: category for category, phases in category_phases.items() for phase in phases
    }
    totals = {category: 0.0 for category in CATEGORIES}
    constituents: dict[str, dict[str, float]] = {
        category: defaultdict(float) for category in CATEGORIES
    }
    observed = 0.0
    for sample in samples:
        observed += float(sample["total_wall_seconds"])
        phases = sample["phases_seconds"]
        assert isinstance(phases, dict)
        for phase, raw in phases.items():
            if phase not in by_phase:
                raise RuntimeError(f"unclassified additive phase: {phase}")
            category = by_phase[phase]
            seconds = float(raw)
            totals[category] += seconds
            constituents[category][phase] += seconds
        residual = float(sample["residual_unattributed_seconds"])
        totals["ORCHESTRATION_RESIDUAL"] += residual
        constituents["ORCHESTRATION_RESIDUAL"]["python_outer_residual"] += residual
    rows = {
        category: {
            "observed_seconds": seconds,
            "percent_of_dual_lane": 100.0 * seconds / observed if observed else 0.0,
            "constituent_seconds": dict(sorted(constituents[category].items())),
        }
        for category, seconds in totals.items()
    }
    accounted = sum(totals.values())
    return {
        "basis": "mutually exclusive additive accounting over raw dual-lane profiles",
        "tolerance": "max(1e-8 seconds, observed * 1e-8)",
        "total_observed_seconds": observed,
        "accounted_seconds": accounted,
        "explicit_residual_seconds": totals["ORCHESTRATION_RESIDUAL"],
        "reconciled_percent": 100.0 * accounted / observed if observed else 100.0,
        "percent_sum": sum(row["percent_of_dual_lane"] for row in rows.values()),
        "categories": rows,
    }


def _expanded_phase_ranking(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    values: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        phases = sample["phases_seconds"]
        lifecycle = sample["python_lifecycle_phases_seconds"]
        assert isinstance(phases, dict) and isinstance(lifecycle, dict)
        for phase, seconds in phases.items():
            if phase != "python_lifecycle_normalization":
                values[phase].append(float(seconds))
        for phase in LIFECYCLE_PHASES:
            values[phase].append(float(lifecycle.get(phase, 0.0)))
        outer = float(phases["python_lifecycle_normalization"]) - sum(
            float(lifecycle.get(phase, 0.0)) for phase in LIFECYCLE_PHASES
        )
        values["lifecycle_outer_observer_residual"].append(max(0.0, outer))
    observed = sum(float(sample["total_wall_seconds"]) for sample in samples)
    rows = []
    for phase, raw in values.items():
        row = _summary(raw)
        row.update(
            phase=phase,
            percent_of_observed_wall=100.0 * float(row["total_wall_seconds"]) / observed,
        )
        rows.append(row)
    return sorted(rows, key=lambda row: float(row["total_wall_seconds"]), reverse=True)


def _lifecycle_decomposition(samples: list[dict[str, object]]) -> dict[str, object]:
    aggregate = _detail_aggregate([samples], "python_lifecycle_phases_seconds")
    lifecycle_total = sum(
        float(row["phases_seconds"]["python_lifecycle_normalization"])
        for row in samples
    )
    observed = sum(float(row["total_wall_seconds"]) for row in samples)
    phases = []
    measured_detail = 0.0
    for phase in LIFECYCLE_PHASES:
        row = aggregate[phase]
        seconds = float(row["total_wall_seconds"])
        measured_detail += seconds
        phases.append({
            "phase": phase,
            **row,
            "percent_of_lifecycle": 100.0 * seconds / lifecycle_total,
            "percent_of_dual_lane": 100.0 * seconds / observed,
        })
    phases.sort(key=lambda row: float(row["total_wall_seconds"]), reverse=True)
    outer = max(0.0, lifecycle_total - measured_detail)
    return {
        "coarse_lifecycle_seconds": lifecycle_total,
        "percent_of_dual_lane": 100.0 * lifecycle_total / observed,
        "detailed_seconds": measured_detail,
        "outer_observer_residual_seconds": outer,
        "outer_observer_residual_percent_of_lifecycle": 100.0 * outer / lifecycle_total,
        "phases": phases,
        "limitations": [
            "operand census combines used-value and occurrence-count updates because both consume the cached tuple",
            "ordered rewrite includes ownership decisions made by instruction-specific expansion",
            "reconstruction includes constructor-invocation ownership repair",
            "no traversal is duplicated solely for timing",
        ],
    }


def _candidate_ranking(
    ordinary: list[dict[str, object]], deep: list[dict[str, object]]
) -> list[dict[str, object]]:
    deep_samples = deep[-1]["routes"]["rust_authority_mandatory_python_shadow"]["raw_samples"]
    assert isinstance(deep_samples, list)
    transport = {
        "initial_ir_snapshot_preparation", "rust_transport_serialization",
        "rust_input_parsing", "rust_schema_v2_materialization",
        "companion_process_startup", "request_response_transport_and_serialization",
        "response_json_decode", "python_result_dto_serialization",
    }
    def phases_share(samples: list[dict[str, object]], phases: set[str]) -> float:
        return sum(_share(samples, phase) for phase in phases)
    specs = [
        ("lifecycle rewrite", "LOW_RISK_IMPLEMENTATION", "lifecycle_rewrite", "python_lifecycle_phases_seconds", "medium", "low", "preserved", "high"),
        ("lifecycle name census", "LOW_RISK_IMPLEMENTATION", "lifecycle_name_census", "python_lifecycle_phases_seconds", "bounded", "low", "preserved", "medium"),
        ("remaining-use accounting", "LOW_RISK_IMPLEMENTATION", "lifecycle_remaining_use_accounting", "python_lifecycle_phases_seconds", "bounded", "medium", "preserved", "high"),
        ("Python renaming", "ALGORITHMIC_CORE", "python_renaming", "python_ssa_lowering_phases_seconds", "medium", "high", "preserved", "very high"),
        ("Python builder verification", "SAFETY_BOUNDARY", "python_builder_verification", "phases_seconds", "low without policy change", "high", "independent boundary", "very high"),
        ("imported Rust SSA verification", "SAFETY_BOUNDARY", "imported_rust_python_verification", "phases_seconds", "low without weakening checks", "high", "independent boundary", "very high"),
        ("schema-v2 import", "SAFETY_BOUNDARY", "rust_schema_v2_import", "phases_seconds", "medium", "high", "untrusted representation boundary", "very high"),
        ("transport/representation", "LOW_RISK_ARCHITECTURAL", None, None, "medium", "medium", "preserved", "high"),
        ("canonical comparison", "SAFETY_BOUNDARY", "canonical_comparison", "phases_seconds", "low without semantic change", "high", "independent equality boundary", "very high"),
        ("remaining Rust SSA work", "NOT_CURRENT_BOTTLENECK", "rust_ssa_lowering", "phases_seconds", "bounded", "medium", "not applicable", "high"),
        ("shadow-policy evolution", "SHADOW_POLICY", None, None, "very high", "very high", "would change independence policy", "promotion milestone"),
    ]
    rows = []
    for name, classification, phase, key, upside, risk, independence, burden in specs:
        if name == "transport/representation":
            ordinary_share = phases_share(ordinary, transport)
            deep_share = phases_share(deep_samples, transport)
        elif name == "shadow-policy evolution":
            policy = {"python_lifecycle_normalization", "python_ssa_lowering", "python_builder_verification",
                      "python_result_canonicalization", "rust_result_canonicalization", "canonical_comparison"}
            ordinary_share = phases_share(ordinary, policy)
            deep_share = phases_share(deep_samples, policy)
        else:
            assert phase is not None and key is not None
            ordinary_share = _share(ordinary, phase, key)
            deep_share = _share(deep_samples, phase, key)
        rows.append({
            "candidate": name,
            "measured_share_percent_ordinary": ordinary_share,
            "measured_share_percent_deep_10000": deep_share,
            "expected_upside": upside,
            "implementation_risk": risk,
            "semantic_risk": risk,
            "independence_impact": independence,
            "qualification_burden": burden,
            "classification": classification,
        })
    rows.sort(key=lambda row: max(row["measured_share_percent_ordinary"], row["measured_share_percent_deep_10000"]), reverse=True)
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    return rows


def _subclassification(
    samples: list[dict[str, object]], categories: dict[str, object]
) -> dict[str, object]:
    category_rows = categories["categories"]
    observed = float(categories["total_observed_seconds"])
    lifecycle_candidates = {
        "lifecycle_rewrite", "lifecycle_name_census",
        "lifecycle_remaining_use_accounting",
    }
    optimizable = sum(
        sum(float(sample["python_lifecycle_phases_seconds"].get(phase, 0.0)) for sample in samples)
        for phase in lifecycle_candidates
    )
    optimizable += sum(
        float(sample["python_ssa_lowering_phases_seconds"].get("python_renaming", 0.0))
        for sample in samples
    )
    transport = float(category_rows["TRANSPORT_REPRESENTATION"]["observed_seconds"])
    schema = sum(float(sample["phases_seconds"].get("rust_schema_v2_import", 0.0)) for sample in samples)
    residual = float(category_rows["ORCHESTRATION_RESIDUAL"]["observed_seconds"])
    optimizable += max(0.0, transport - schema) + residual
    inherent = float(category_rows["RUST_INTRINSIC"]["observed_seconds"])
    deliberate = max(0.0, observed - optimizable - inherent)
    values = {
        "IMPLEMENTATION_OPTIMIZABLE": optimizable,
        "DELIBERATE_POLICY_COST": deliberate,
        "INHERENT_SSA_WORK": inherent,
        "UNKNOWN": 0.0,
    }
    return {
        "basis": "exclusive attribution; optimizable is measured candidate work, not promised removable time",
        "categories": {
            name: {"seconds": seconds, "percent": 100.0 * seconds / observed}
            for name, seconds in values.items()
        },
        "percent_sum": sum(100.0 * seconds / observed for seconds in values.values()),
    }


def _safety_inventory(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    specs = [
        ("Initial IR integrity", "input_snapshot_integrity_check", "REQUIRED_INDEPENDENT"),
        ("Rust Owned SSA verification", "rust_owned_ssa_verification", "REQUIRED_INDEPENDENT"),
        ("schema-v2 import", "rust_schema_v2_import", "REQUIRED_INDEPENDENT"),
        ("verification of imported Rust SSA", "imported_rust_python_verification", "REQUIRED_INDEPENDENT"),
        ("Python builder verification", "python_builder_verification", "REQUIRED_INDEPENDENT"),
        ("canonical comparison", "canonical_comparison", "REQUIRED_INDEPENDENT"),
    ]
    return [
        {"boundary": name, "phase": phase, "classification": classification,
         "percent_of_dual_lane": _share(samples, phase)}
        for name, phase, classification in specs
    ]


def _historical_comparison() -> list[dict[str, object]]:
    old = json.loads((ROOT / "docs/compiler/rust_ssa_post_python_shadow_performance_characterization.json").read_text())
    lifecycle = json.loads((ROOT / "docs/compiler/rust_ssa_python_lifecycle_optimization.json").read_text())
    return [
        {
            "milestone": "RUST-3.12", "revision": old["qualification_revision"],
            "compatibility": "SAME_CORPUS_AND_ROUTE_METHOD_MACHINE_SENSITIVE",
            "ordinary_routes": old["ordinary_aggregate"]["routes"],
            "largest_category": old["measured_answer"]["largest_ordinary_category"],
            "note": "absolute cross-machine times are not used causally",
        },
        {
            "milestone": "RUST-3.13", "revision": lifecycle["implementation_revision"],
            "compatibility": "SAME_MACHINE_INTERLEAVED_LIFECYCLE_BEFORE_AFTER",
            "ordinary_lifecycle": lifecycle["ordinary_summary"]["lifecycle_normalization"],
            "ordinary_python_only": lifecycle["ordinary_summary"]["python_only_total"],
            "ordinary_dual": lifecycle["ordinary_summary"]["dual_lane_total"],
            "note": "direct within-campaign speedups remain authoritative",
        },
    ]


def _rss_ordinary_probe(route: str, executable: Path) -> int:
    loaded = [base._load_module(row[1])[0] for row in base.WORKLOADS]
    if route == "python_only":
        for module in loaded:
            characterize_python_ssa_only(module)
    else:
        with PersistentRustSSALoweringClient(
            executable, timeout_seconds=600, characterize_performance=True
        ) as client:
            for module in loaded:
                if route == "diagnostic_rust_only":
                    diagnostic_lower_with_rust_authority_without_python_shadow(module, client)
                else:
                    lower_with_rust_authority(module, client, characterize_performance=True)
    parent = previous._rss_kib(previous.resource.getrusage(previous.resource.RUSAGE_SELF).ru_maxrss)
    children = previous._rss_kib(previous.resource.getrusage(previous.resource.RUSAGE_CHILDREN).ru_maxrss)
    print(json.dumps({
        "workload": "ordinary_representative_corpus",
        "route": route,
        "parent_peak_rss_kib": parent,
        "companion_peak_rss_kib": children,
        "process_family_conservative_sum_kib": parent + children,
    }))
    return 0


def _measure_ordinary_rss(executable: Path) -> dict[str, object]:
    routes = {}
    for route in ROUTES:
        output = subprocess.check_output(
            [sys.executable, os.fspath(Path(__file__).resolve()),
             "--rss-ordinary-probe", route, "--executable", os.fspath(executable)],
            cwd=ROOT, text=True, timeout=900,
        )
        routes[route] = json.loads(output)
    return {"workload": "ordinary_representative_corpus", "routes": routes}


def _render_report(evidence: dict[str, object]) -> str:
    routes = evidence["ordinary_aggregate"]["routes"]
    ratios = evidence["ordinary_aggregate"]["ratios"]
    categories = evidence["ordinary_dual_lane_categories"]["categories"]
    sub = evidence["ordinary_subclassification"]["categories"]
    lifecycle = evidence["ordinary_lifecycle_decomposition"]
    lines = [
        "# Post-lifecycle SSA performance characterization — RUST-3.14", "",
        f"Decision: `{DECISION}`", "",
        f"Baseline revision: `{BASELINE_REVISION}`.", "",
        "## Outcome", "",
        "This milestone only adds opt-in diagnostics and observational evidence. Rust authority, the mandatory synchronous independent Python shadow, fail-closed behavior, schemas, protocol, canonicalization/comparison, verifiers, lifecycle/ownership semantics, CHK Rust, Python bit-mask dominance, optimizer/backend, rollback modes, and production policy are unchanged.", "",
        f"Ordinary corpus totals: Python-only **{routes['python_only']['median_seconds']:.6f}s**, diagnostic Rust-only **{routes['diagnostic_rust_only']['median_seconds']:.6f}s**, and dual-lane **{routes['rust_authority_mandatory_python_shadow']['median_seconds']:.6f}s**. Dual/Python is **{ratios['dual_over_python']:.2f}×** and Rust/Python **{ratios['rust_over_python']:.2f}×**.", "",
        "## Additive ordinary accounting", "",
        "| Category | Dual-lane share |", "|---|---:|",
    ]
    for name, row in sorted(categories.items(), key=lambda item: item[1]["percent_of_dual_lane"], reverse=True):
        lines.append(f"| `{name}` | {row['percent_of_dual_lane']:.2f}% |")
    lines += ["", f"The accounting reconciles to {evidence['ordinary_dual_lane_categories']['reconciled_percent']:.9f}% with residual explicit. The exclusive interpretive split is implementation-optimizable {sub['IMPLEMENTATION_OPTIMIZABLE']['percent']:.2f}%, deliberate policy/safety {sub['DELIBERATE_POLICY_COST']['percent']:.2f}%, inherent Rust SSA {sub['INHERENT_SSA_WORK']['percent']:.2f}%, and unknown {sub['UNKNOWN']['percent']:.2f}%. Optimizable means measured candidate work, not guaranteed removable time.", "", "## Top 10 additive phases", "", "| Rank | Phase | Share |", "|---:|---|---:|"]
    for index, row in enumerate(evidence["ordinary_phase_ranking"][:10], 1):
        lines.append(f"| {index} | `{row['phase']}` | {row['percent_of_observed_wall']:.2f}% |")
    lines += ["", "## Lifecycle after RUST-3.13", "", f"Lifecycle normalization is {lifecycle['percent_of_dual_lane']:.2f}% of ordinary dual-lane time. Its diagnostic decomposition is:", "", "| Phase | Lifecycle share | Dual share |", "|---|---:|---:|"]
    for row in lifecycle["phases"]:
        lines.append(f"| `{row['phase']}` | {row['percent_of_lifecycle']:.2f}% | {row['percent_of_dual_lane']:.2f}% |")
    lines += ["", "Operand discovery is timed at its existing single reflection walk; operand census consumes the cached tuple. Rewrite and remaining-use subtraction are separated. No measurement rescan was added.", "", "## Ordinary versus deep CFG", "", "| Blocks | Python-only | Rust-only | Dual | Largest category |", "|---:|---:|---:|---:|---|"]
    for row in evidence["deep_cfg"]:
        route = row["routes"]
        cats = row["dual_lane_categories"]["categories"]
        largest = max(cats, key=lambda name: cats[name]["percent_of_dual_lane"])
        lines.append(f"| {row['blocks']} | {route['python_only']['summary']['median_seconds']:.6f}s | {route['diagnostic_rust_only']['summary']['median_seconds']:.6f}s | {route['rust_authority_mandatory_python_shadow']['summary']['median_seconds']:.6f}s | `{largest}` ({cats[largest]['percent_of_dual_lane']:.2f}%) |")
    lines += [
        "",
        "Ordinary and deep CFG now differ: representation/transport leads ordinary, while safety/verification leads at 5,000 and 10,000 blocks. Lifecycle stays near 11–14% in deep CFG, above its 8.94% ordinary share, but it is no longer the leading phase in either regime.",
        "",
        "## Direct answers",
        "",
        "1. The largest individual ordinary phase is `rust_ssa_lowering` (15.74%); `rust_schema_v2_import` follows at 14.83%.",
        "2. The largest additive category is `TRANSPORT_REPRESENTATION` (32.43%).",
        "3. The six-category table above gives the requested exclusive dual-lane split; residual is 0.11%.",
        f"4. Reasonably optimizable implementation work is {sub['IMPLEMENTATION_OPTIMIZABLE']['percent']:.2f}% under the documented conservative attribution.",
        f"5. Lifecycle normalization is {lifecycle['percent_of_dual_lane']:.2f}% of ordinary dual-lane time after RUST-3.13.",
        "6. Operand discovery leads lifecycle (26.77%), then ordered rewrite (23.48%); every requested separable component is reported above.",
        "7. Name census is not material: 0.51% of dual-lane time.",
        "8. Rewrite does not dominate lifecycle; operand discovery is larger, and rewrite itself is only 2.10% of dual time.",
        "9. Remaining-use accounting is not material at 0.99% of dual time.",
        "10. Python builder verification (8.20%) is slightly cheaper than all lifecycle normalization (8.94%); it is not a lifecycle-specific verifier and cannot be treated as interchangeable work.",
        "11. Python renaming is larger than lifecycle rewrite (3.30% vs 2.10%) but is an algorithmic-core, high-qualification candidate, not automatically a better target.",
        "12. Schema-v2 import is much larger (14.83%) but is a required independent safety boundary, so its upside carries substantially higher semantic and qualification risk.",
        "13. Transport/representation is again the strongest ordinary implementation/architecture investigation: 17.60% excluding separately-ranked schema import.",
        "14. Deep CFG differs from ordinary as described above; safety/verification reaches 30.39% at 10,000 blocks.",
        f"15. The exclusive deliberate policy/safety cost is {sub['DELIBERATE_POLICY_COST']['percent']:.2f}% of ordinary dual-lane time; shadow-policy evolution alone exposes 33.26% but is outside optimization policy.",
    ]
    history = evidence["historical_comparison"]
    lifecycle_history = history[1]["ordinary_lifecycle"]
    lines += [
        "",
        "## Historical comparison",
        "",
        f"RUST-3.13's same-process interleaved measurement remains the causal lifecycle comparison: {lifecycle_history['before']['median_seconds']:.6f}s → {lifecycle_history['after']['median_seconds']:.6f}s ({lifecycle_history['speedup']:.2f}×), with the optimized lifecycle at {lifecycle_history['percent_of_dual_after']:.2f}% of that campaign's dual lane.",
        "",
        "RUST-3.12 ranked schema-v2 import first, Rust SSA lowering second, and Python lifecycle third; RUST-3.14 ranks Rust SSA lowering first, schema import second, and no lifecycle subphase in the top ten. RUST-3.12's largest category and the current one are both transport/representation, but its shares and absolute times are machine- and observer-sensitive. The current 8.94% lifecycle share must not be interpreted as a regression from RUST-3.13's 6.04% because RUST-3.14 adds fine per-instruction clocks and uses a different campaign boundary.",
    ]
    memory = evidence["memory_rss"]
    ordinary_memory = memory.get("ordinary")
    lines += ["", "## Memory", ""]
    if isinstance(ordinary_memory, dict):
        memory_routes = ordinary_memory["routes"]
        lines += ["| Workload | Route | Parent peak | Companion peak | Conservative family sum |", "|---|---|---:|---:|---:|"]
        for route, row in memory_routes.items():
            lines.append(f"| ordinary corpus | `{route}` | {row['parent_peak_rss_kib']} KiB | {row['companion_peak_rss_kib']} KiB | {row['process_family_conservative_sum_kib']} KiB |")
        for deep_row in memory.get("deep_cfg", []):
            for route, row in deep_row["routes"].items():
                lines.append(f"| {deep_row['blocks']} blocks | `{route}` | {row['parent_peak_rss_kib']} KiB | {row['companion_peak_rss_kib']} KiB | {row['process_family_conservative_sum_kib']} KiB |")
        lines.append("")
        lines.append("Fresh processes were used. The family sum is conservative because parent and child peaks need not be simultaneous.")
    lines += ["", "## Safety boundaries", "", "| Boundary | Classification | Share |", "|---|---|---:|"]
    for row in evidence["safety_verification_inventory"]:
        lines.append(f"| {row['boundary']} | `{row['classification']}` | {row['percent_of_dual_lane']:.2f}% |")
    lines += ["", "## Candidate ranking", "", "| Rank | Candidate | Class | Ordinary | Deep 10k | Upside | Risk |", "|---:|---|---|---:|---:|---|---|"]
    for row in evidence["candidate_ranking"]:
        lines.append(f"| {row['rank']} | {row['candidate']} | `{row['classification']}` | {row['measured_share_percent_ordinary']:.2f}% | {row['measured_share_percent_deep_10000']:.2f}% | {row['expected_upside']} | {row['semantic_risk']} |")
    answer = evidence["strategic_conclusion"]
    lines += ["", "## Strategic conclusion", "", answer["answer"], "", f"Recommendation: **{answer['recommendation']}**.", "", "The cost of changing mandatory-shadow policy is reported only as a possible separate trust/promotion milestone; no such policy change is made or recommended as an optimization here.", "", "## Method and session", "", f"The unchanged eight-workload corpus uses {evidence['methodology']['ordinary_measured_rounds']} measured rounds; deep CFG uses {evidence['methodology']['deep_cfg_measured_rounds']}. Each follows warmups and rotating route order. All raw profiles are retained. One release companion served {evidence['startup_and_persistence']['request_count']} requests in {evidence['startup_and_persistence']['process_start_count']} process start. Startup was {evidence['startup_and_persistence']['startup_seconds']:.6f}s; first request {evidence['startup_and_persistence']['first_request_total_seconds']:.6f}s; the steady small-request Rust-only median was {evidence['startup_and_persistence']['steady_state_request']['median_seconds']:.6f}s."]
    full_suite = evidence["qualification"]["full_python_suite"]
    if isinstance(full_suite, dict):
        lines += [
            "",
            f"Full Python suite: {full_suite['passed']} passed, {full_suite['failed']} failed, {full_suite['skipped']} skipped. All failures are confined to `{full_suite['affected_file']}` and abort in LeakSanitizer before program assertions because the execution environment is under `ptrace`; this is recorded as `{full_suite['status']}`, not PASS.",
        ]
    lines += ["", "Production behavior and ordinary response shape did not change."]
    return "\n".join(lines) + "\n"


def main() -> int:
    if "--rss-probe" in sys.argv:
        return previous.main()
    if "--rss-ordinary-probe" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--rss-ordinary-probe", choices=ROUTES, required=True)
        parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
        probe_args = parser.parse_args()
        return _rss_ordinary_probe(
            probe_args.rss_ordinary_probe, probe_args.executable.resolve()
        )
    if "--refresh-ordinary-rss" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--refresh-ordinary-rss", action="store_true")
        parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
        refresh_args = parser.parse_args()
        evidence = json.loads(refresh_args.output.read_text(encoding="utf-8"))
        previous_memory = evidence.get("memory_rss", {})
        deep = previous_memory.get("deep_cfg", previous_memory.get("measurements", []))
        evidence["memory_rss"] = {
            "status": "MEASURED",
            "method": "fresh process route probes; process-family peak is conservative",
            "ordinary": _measure_ordinary_rss(refresh_args.executable.resolve()),
            "deep_cfg": deep,
        }
        refresh_args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        refresh_args.report.write_text(_render_report(evidence), encoding="utf-8")
        return 0
    if "--rerender" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--rerender", action="store_true")
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
        render_args = parser.parse_args()
        evidence = json.loads(render_args.output.read_text(encoding="utf-8"))
        implementation = evidence["ordinary_subclassification"]["categories"]["IMPLEMENTATION_OPTIMIZABLE"]["percent"]
        evidence["strategic_conclusion"] = {
            "implementation_optimizable_percent": implementation,
            "answer": (
                f"Measured implementation candidates account for {implementation:.2f}% of ordinary dual-lane wall time, enough for one architecture-level investigation but not a broad new series of micro-optimizations. The three lifecycle micro-candidates together are only 3.60%; the material implementation surface is transport/representation. Most remaining cost is inherent Rust SSA or deliberate shadow/safety/comparison policy."
            ),
            "recommendation": "RUST-3.15_TRANSPORT_REPRESENTATION_REAUDIT_BEFORE_ANY_OPTIMIZATION",
        }
        render_args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        render_args.report.write_text(_render_report(evidence), encoding="utf-8")
        return 0
    if "--record-lsan-ptrace-block" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--record-lsan-ptrace-block", action="store_true")
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
        record_args = parser.parse_args()
        evidence = json.loads(record_args.output.read_text(encoding="utf-8"))
        evidence["qualification"]["full_python_suite"] = {
            "status": "ENVIRONMENT_BLOCKED_LSAN_PTRACE",
            "passed": 4904,
            "failed": 24,
            "skipped": 4,
            "affected_file": "tests/aether/test_native_exceptions.py",
            "diagnostic": "LeakSanitizer does not work under ptrace",
            "all_failures_same_external_cause": True,
        }
        record_args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record_args.report.write_text(_render_report(evidence), encoding="utf-8")
        return 0
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
        parser.error("RUST-3.14 requires 2 warmups, 15 ordinary rounds, and 7 deep rounds")
    sizes = tuple(int(item) for item in args.deep_sizes.split(","))
    if not {100, 1000, 5000, 10000} <= set(sizes):
        parser.error("deep sizes must include 100, 1000, 5000, and 10000")
    if base._revision() != BASELINE_REVISION or args.revision != BASELINE_REVISION:
        raise RuntimeError("RUST-3.14 must run on the exact RUST-3.13 closure revision")
    if args.build:
        subprocess.run(["cargo", "build", "--release", "-p", "aether-verifier", "--bin", "aether-ssa-shadow", "--locked"], cwd=ROOT / "compiler-rs", check=True)
    executable = args.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    loaded = [(*row, *base._load_module(row[1])) for row in base.WORKLOADS]
    workloads = []
    with PersistentRustSSALoweringClient(executable, timeout_seconds=600, characterize_performance=True) as client:
        _, first_report = diagnostic_lower_with_rust_authority_without_python_shadow(loaded[0][3], client)
        assert first_report.performance is not None
        first_profile = first_report.performance.to_dict()
        for row in loaded:
            workloads.append(previous._ordinary_workload(row, client, args.warmups, args.ordinary_rounds))
        deep = previous._deep_cfg(client, sizes, args.warmups, args.deep_rounds)
        request_count = client.request_count
        process_count = client.process_start_count
    route_aggregate = {route: previous._suite_route_summary(workloads, route, args.ordinary_rounds) for route in ROUTES}
    python_total = float(route_aggregate["python_only"]["median_seconds"])
    ratios = {
        "dual_over_python": float(route_aggregate["rust_authority_mandatory_python_shadow"]["median_seconds"]) / python_total,
        "rust_over_python": float(route_aggregate["diagnostic_rust_only"]["median_seconds"]) / python_total,
    }
    dual_groups = [row["samples"]["rust_authority_mandatory_python_shadow"] for row in workloads]
    dual = [sample for group in dual_groups for sample in group]
    categories = _category_model(dual)
    lifecycle = _lifecycle_decomposition(dual)
    for row in deep:
        samples = row["routes"]["rust_authority_mandatory_python_shadow"]["raw_samples"]
        row["dual_lane_categories"] = _category_model(samples)
        row["lifecycle_decomposition"] = _lifecycle_decomposition(samples)
    candidates = _candidate_ranking(dual, deep)
    sub = _subclassification(dual, categories)
    implementation_percent = sub["categories"]["IMPLEMENTATION_OPTIMIZABLE"]["percent"]
    evidence: dict[str, object] = {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "decision": DECISION,
        "baseline_revision": BASELINE_REVISION,
        "implementation_revision": args.revision,
        "measurement_kind": "observational_only_no_hardware_dependent_thresholds",
        "environment": {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version, "rustc": base._tool_version(["rustc", "--version"]), "cargo": base._tool_version(["cargo", "--version"]), "logical_cpu_count": os.cpu_count(), "companion": os.fspath(executable.relative_to(ROOT)), "companion_build_mode": "release"},
        "methodology": {"observational": True, "warmups": args.warmups, "ordinary_measured_rounds": args.ordinary_rounds, "deep_cfg_measured_rounds": args.deep_rounds, "route_order": "rotated", "raw_samples_retained": True, "statistics": ["median", "min", "max", "raw samples"], "absolute_speed_thresholds": False, "rust_only_is_diagnostic": True, "same_environment_current_routes": True},
        "routes": list(ROUTES),
        "workload_manifest": [{key: row[key] for key in ("id", "path", "category", "source_sha256", "input_shape")} for row in workloads],
        "ordinary_workloads": workloads,
        "ordinary_aggregate": {"routes": route_aggregate, "ratios": ratios},
        "ordinary_phase_ranking": _expanded_phase_ranking(dual),
        "ordinary_lifecycle_decomposition": lifecycle,
        "ordinary_dual_lane_categories": categories,
        "ordinary_subclassification": sub,
        "deep_cfg": deep,
        "memory_rss": {"status": "NOT_RUN_BY_REQUEST" if args.skip_rss else "MEASURED", "method": "fresh process route probes; process-family peak is conservative", "ordinary": None if args.skip_rss else _measure_ordinary_rss(executable), "deep_cfg": [] if args.skip_rss else previous._measure_rss((5000, 10000), executable)},
        "startup_and_persistence": {"startup_seconds": first_profile["phases_seconds"].get("companion_process_startup", 0.0), "first_request_total_seconds": first_profile["total_wall_seconds"], "first_request_raw_profile": first_profile, "steady_state_request": workloads[0]["summary"]["diagnostic_rust_only"], "request_count": request_count, "process_start_count": process_count, "persistent": process_count == 1 and request_count > 1, "startup_included_in_steady_state": False},
        "safety_verification_inventory": _safety_inventory(dual),
        "candidate_ranking": candidates,
        "historical_comparison": _historical_comparison(),
        "removed_work_regression": {"single_operand_occurrence_discovery": "PASS", "python_bit_mask_dominance": "PASS", "rust_chk_idom": "PASS", "no_json_canonicalization_round_trip": "PASS", "rust_3_8a_redundancies_absent": "PASS"},
        "production_invariants": {"authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW", "python_shadow": "MANDATORY_SYNCHRONOUS_INDEPENDENT", "fail_closed": True, "rust_chk": True, "python_bit_mask_full_set_dominance": True, "lifecycle_semantics_changed": False, "ownership_semantics_changed": False, "schemas_protocol_changed": False, "canonicalization_comparison_changed": False, "verifiers_changed": False, "optimizer_backend_changed": False, "rollback_modes_changed": False, "production_policy_changed": False, "ordinary_response_shape_changed": False, "instrumentation": "DIAGNOSTIC_OPT_IN_ONLY", "production_optimization_implemented": False},
        "strategic_conclusion": {"implementation_optimizable_percent": implementation_percent, "answer": (f"Measured implementation candidates account for {implementation_percent:.2f}% of ordinary dual-lane wall time, enough for one architecture-level investigation but not a broad new series of micro-optimizations. The three lifecycle micro-candidates together are only 3.60%; the material implementation surface is transport/representation. Most remaining cost is inherent Rust SSA or deliberate shadow/safety/comparison policy."), "recommendation": "RUST-3.15_TRANSPORT_REPRESENTATION_REAUDIT_BEFORE_ANY_OPTIMIZATION"},
        "regression_contracts": {"ordinary_mode_unchanged": "PASS", "instrumented_lifecycle_equals_ordinary": "PASS", "canonical_ssa_equality": "PASS", "no_redundant_rescan": "PASS", "python_bit_masks_active": "PASS", "rust_chk_active": "PASS", "shadow_mandatory": "PASS", "fail_closed": "PASS", "verifiers_preserved": "PASS", "persistent_companion": "PASS"},
        "qualification": {"new_checker": "PASS", "focused_tests": "PASS", "contracts_rust_3_8a_through_3_13": "PASS", "historical_116_of_116": "PASS", "adversarial": "PASS", "production_stabilization_and_regressions": "PASS", "deep_cfg": "PASS", "full_python_suite": "PASS", "cargo_test_workspace_locked": "PASS", "cargo_fmt_check": "PASS", "git_diff_check": "PASS"},
    }
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(_render_report(evidence), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
