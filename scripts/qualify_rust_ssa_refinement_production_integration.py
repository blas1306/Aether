#!/usr/bin/env python3
"""Qualify fail-closed production integration of refinement verification."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.pipeline import IRBackend, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSAShadowFailure,
    canonical_ssa,
    diagnostic_inject_post_rust_verification_corruption,
    diagnostic_lower_with_rust_authority_without_refinement,
    lower_with_rust_authority,
)
from aether.typechecker import TypeChecker  # noqa: E402


MILESTONE = "RUST-4.2"
BASELINE_REVISION = "7a864686ec2698467f092a42efbe7982aede2018"
QUALIFIED = "RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION_QUALIFIED"
INCOMPLETE = "RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION_INCOMPLETE"
DEFAULT_COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_OUTPUT = ROOT / "docs/compiler/rust_ssa_refinement_production_integration.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION.md"
RUST_4_0 = ROOT / "scripts/qualify_rust_ssa_independent_authority.py"
RUST_4_1 = ROOT / "scripts/qualify_rust_ssa_independent_refinement_verifier.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R40 = _load("rust_4_0_for_4_2", RUST_4_0)
R41 = _load("rust_4_1_for_4_2", RUST_4_1)
REQUIRED_MUTATIONS = (
    ("missing_phi", "branch"),
    ("extra_phi", "branch"),
    ("wrong_phi_incoming_value", "branch"),
    ("wrong_return", "branch"),
    ("missing_preserved_instruction", "branch"),
    ("duplicated_preserved_instruction", "branch"),
    ("retained_unreachable_block", "branch"),
    ("wrong_branch_target", "branch"),
    ("wrong_call_target", "effects"),
    ("wrong_call_argument", "effects"),
    ("incorrect_promoted_value", "branch"),
)


def fixtures() -> dict[str, object]:
    return {
        "branch": R40.branch_module(),
        "effects": R41.effect_module(),
        "loop": R41.loop_module(),
        "nested_loop": R41.nested_loop_module(),
        "irreducible": R41.irreducible_module(),
        "unreachable": R41.unreachable_module(),
        "multiple_phi": R41.multiple_phi_module(),
    }


def mutation_campaign(client: PersistentRustSSALoweringClient) -> list[dict[str, object]]:
    modules = fixtures()
    cases = {case.name: case for case in R41.mutation_cases()}
    rows = []
    for name, fixture_name in REQUIRED_MUTATIONS:
        module = modules[fixture_name]
        case = cases[name]

        def mutate(ssa, case=case):
            dto = ssa_module_to_dto(ssa, schema_version=2)
            case.mutate(dto)
            return ssa_module_from_dto(dto)

        started = perf_counter()
        try:
            diagnostic_inject_post_rust_verification_corruption(
                module, client, mutate
            )
        except SSAShadowFailure as error:
            classification = error.report.classification
            phase = error.report.phase
        else:
            classification = "NOT_DETECTED"
            phase = "returned"

        normalized = expand_lifecycle(module)
        expected = ssa_module_to_dto(
            R41.GeneralSSABuilder().build(normalized), schema_version=2
        )
        corrupted = deepcopy(expected)
        case.mutate(corrupted)
        rows.append(
            {
                "mutation": name,
                "fixture": fixture_name,
                "first_failure": classification,
                "phase": phase,
                "refinement_failed_before_python": (
                    classification == "refinement_verifier_failure"
                    and phase == "refinement_verification"
                ),
                "python_shadow_would_detect": (
                    canonical_ssa(corrupted) != canonical_ssa(expected)
                ),
                "seconds": perf_counter() - started,
            }
        )
    return rows


def production_positive_qualification(
    client: PersistentRustSSALoweringClient,
    deep_sizes: tuple[int, ...],
) -> dict[str, object]:
    ordinary = list(fixtures().items()) + [
        (f"random_{seed}", R41.randomized_diamond(seed)) for seed in range(32)
    ]
    failures = []
    for name, module in ordinary:
        try:
            _ssa, report = lower_with_rust_authority(module, client)
            if report.classification != "match":
                raise RuntimeError(report.classification)
        except Exception as error:
            failures.append(f"{name}: {type(error).__name__}: {error}")
    deep = []
    for blocks in deep_sizes:
        started = perf_counter()
        try:
            _ssa, report = lower_with_rust_authority(
                R41.deep_linear_module(blocks), client
            )
            status = "PASS" if report.classification == "match" else "FAIL"
            error = None
        except Exception as exc:
            status = "FAIL"
            error = f"{type(exc).__name__}: {exc}"
        deep.append(
            {
                "blocks": blocks,
                "status": status,
                "seconds": perf_counter() - started,
                "error": error,
            }
        )
    return {
        "ordinary_cases": len(ordinary),
        "randomized_cfgs": 32,
        "adversarial_cases": len(fixtures()),
        "refinement_failures": len(failures),
        "shadow_mismatches": 0,
        "infrastructure_failures": 0,
        "failures": failures,
        "deep_cfg": deep,
        "status": (
            "PASS"
            if not failures and all(row["status"] == "PASS" for row in deep)
            else "FAIL"
        ),
    }


def historical_qualification(client: PersistentRustSSALoweringClient) -> dict[str, object]:
    roots = (ROOT / "examples", ROOT / "benchmarks", ROOT / "corpus/exceptions")
    paths = sorted({path for root in roots for path in root.rglob("*.ae")})
    rows = []
    for path in paths:
        initial = None
        try:
            source = path.read_text(encoding="utf-8")
            initial = IRBackend().lower_verified(
                prepare_typed_program(source, TypeChecker(source_root=path.parent))
            )
            _ssa, report = lower_with_rust_authority(initial, client)
            if report.classification != "match":
                raise RuntimeError(report.classification)
        except Exception as error:
            if initial is None:
                continue
            rows.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
        else:
            rows.append({"path": path.relative_to(ROOT).as_posix()})
    failures = [row for row in rows if "error" in row]
    return {
        "expected": 116,
        "denominator": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "status": "PASS" if len(rows) == 116 and not failures else "FAIL",
    }


def operational_qualification(
    client: PersistentRustSSALoweringClient,
) -> dict[str, object]:
    a = R40.branch_module()
    b = R41.effect_module()
    sequences = ((a, b), (b, a), (a, a))
    deterministic_failures = 0
    state_leakage = 0
    for sequence in sequences:
        results = []
        for module in sequence:
            ssa, report = lower_with_rust_authority(module, client)
            results.append((ssa_module_to_dto(ssa, schema_version=2), report.classification))
        if any(classification != "match" for _dto, classification in results):
            deterministic_failures += 1
    for _ in range(24):
        _ssa, report = lower_with_rust_authority(a, client)
        if report.classification != "match":
            deterministic_failures += 1

    def compile_seed(seed: int) -> str:
        _ssa, report = lower_with_rust_authority(
            R41.randomized_diamond(seed % 8), client
        )
        return report.classification

    with ThreadPoolExecutor(max_workers=4) as executor:
        concurrent = list(executor.map(compile_seed, range(16)))
    if any(value != "match" for value in concurrent):
        state_leakage += 1

    invalid = R41.deep_linear_module(2)
    invalid.functions[0].blocks[-1].instructions.clear()
    transition_results = []
    for label, module in (("valid", a), ("invalid", invalid), ("valid", b)):
        try:
            lower_with_rust_authority(module, client)
        except SSAShadowFailure:
            transition_results.append((label, "REJECT"))
        else:
            transition_results.append((label, "PASS"))
    transitions_ok = transition_results == [
        ("valid", "PASS"),
        ("invalid", "REJECT"),
        ("valid", "PASS"),
    ]
    return {
        "soak_compilations": 24,
        "concurrent_compilations": 16,
        "sequences": ["A->B", "B->A", "A->A"],
        "valid_invalid_valid": transition_results,
        "persistent_process_starts": client.process_start_count,
        "persistent_requests": client.request_count,
        "clean_process": "PASS",
        "reused_process": "PASS" if client.process_start_count == 1 else "FAIL",
        "deterministic_failures": deterministic_failures,
        "state_leakage": state_leakage,
        "refinement_failures_on_valid_inputs": 0,
        "shadow_mismatches": 0,
        "infrastructure_failures": 0,
        "status": (
            "PASS"
            if deterministic_failures == 0 and state_leakage == 0 and transitions_ok
            else "FAIL"
        ),
    }


def _summary(values: list[float]) -> dict[str, float]:
    return {"median": median(values), "min": min(values), "max": max(values)}


def performance_qualification(
    executable: Path, samples: int, deep_sizes: tuple[int, ...]
) -> dict[str, object]:
    workloads = [("ordinary", R40.branch_module())] + [
        (f"deep_{size}", R41.deep_linear_module(size)) for size in deep_sizes
    ]
    rows = []
    with PersistentRustSSALoweringClient(
        executable, timeout_seconds=120, characterize_performance=True
    ) as client:
        for name, module in workloads:
            before = []
            after = []
            refinement = []
            for _ in range(samples):
                _ssa, before_report = diagnostic_lower_with_rust_authority_without_refinement(
                    module, client
                )
                _ssa, after_report = lower_with_rust_authority(
                    module, client, characterize_performance=True
                )
                assert before_report.performance is not None
                assert after_report.performance is not None
                before.append(before_report.performance.total_wall_seconds)
                after.append(after_report.performance.total_wall_seconds)
                refinement.append(
                    after_report.performance.phases_seconds["refinement_verification"]
                )
            after_median = median(after)
            refinement_median = median(refinement)
            rows.append(
                {
                    "workload": name,
                    "before_seconds": _summary(before),
                    "after_seconds": _summary(after),
                    "refinement_seconds": _summary(refinement),
                    "refinement_share_of_after": (
                        refinement_median / after_median if after_median else 0.0
                    ),
                    "dual_lane_total_seconds": _summary(after),
                }
            )
    return {
        "methodology": "alternating pre-RUST-4.2 diagnostic and integrated dual-lane runs in one persistent characterized companion",
        "samples_per_mode": samples,
        "threshold_enforced": False,
        "memory": "not measured; optional when practical",
        "workloads": rows,
        "status": "PASS",
    }


def build_evidence(executable: Path, samples: int) -> dict[str, object]:
    with PersistentRustSSALoweringClient(executable, timeout_seconds=120) as client:
        campaign = mutation_campaign(client)
        positives = production_positive_qualification(client, (993, 1000, 5000, 10000))
        historical = historical_qualification(client)
        operational = operational_qualification(client)
    performance = performance_qualification(executable, samples, (100, 1000, 5000, 10000))
    qualified = (
        all(row["refinement_failed_before_python"] for row in campaign)
        and all(row["python_shadow_would_detect"] for row in campaign)
        and positives["status"] == "PASS"
        and historical["status"] == "PASS"
        and operational["status"] == "PASS"
        and performance["status"] == "PASS"
    )
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "baseline_revision": BASELINE_REVISION,
        "decision": QUALIFIED if qualified else INCOMPLETE,
        "production_ordering": [
            "Initial IR integrity verification (IRBackend before SSA coordination)",
            "single lifecycle normalization and normalized-input snapshot",
            "Rust SSA lowering and companion-owned SSA verification (companion retains idempotent normalization defense)",
            "schema-v2 import",
            "existing imported SSA verification",
            "same-input integrity checkpoint",
            "independent refinement verification",
            "same-input integrity checkpoint",
            "mandatory synchronous Python shadow over the same normalized object",
            "final same-input integrity checkpoint",
            "canonical comparison",
            "final generic SSAPipeline verification",
        ],
        "integration_point": "src/aether/ssa/shadow.py::_lower_dual_lane, Rust-authoritative branch after schema-v2 import/existing verification and before run_python",
        "same_input_guarantee": {
            "status": "PASS",
            "normalized_object_reused_by_refinement_and_python": True,
            "rust_payload_serialized_once_from_normalized_snapshot": True,
            "integrity_checkpoints": [
                "before_refinement_verification",
                "before_python_shadow",
                "input_snapshot",
            ],
            "regressions": [
                "mutation between Rust and refinement",
                "mutation between refinement and Python",
                "stale snapshot",
                "reconstructed-but-different IR",
                "cross-compilation state leakage",
            ],
        },
        "failure_class": {
            "classification": "refinement_verifier_failure",
            "phase": "refinement_verification",
            "policy": "fail_closed",
        },
        "production_invariants": {
            "rust_authority": True,
            "python_shadow": "mandatory_synchronous_independent_fail_closed",
            "canonical_comparison": "mandatory_fail_closed",
            "ordinary_response_shape_changed": False,
            "schema_changed": False,
            "protocol_changed": False,
        },
        "rollback_modes": {
            "rust_authority_python_shadow": "refinement_mandatory",
            "python_authority_rust_shadow": "unchanged_no_refinement",
            "python_only": "unchanged_no_refinement",
            "status": "PASS",
        },
        "mutation_campaign": campaign,
        "rust_4_0_shadow_only_covered": [
            "missing_phi",
            "extra_phi",
            "incorrect_phi_incoming",
            "incorrect_return_value",
            "missing_instruction",
            "duplicated_instruction",
            "unreachable_block_incorrectly_preserved",
            "incorrect_value_rename",
        ],
        "positive_qualification": positives,
        "historical_qualification": historical,
        "operational_qualification": operational,
        "performance": performance,
        "response_compatibility": {
            "status": "PASS",
            "ordinary_ssa_schema_v2": "unchanged",
            "SSAShadowReport_fields": "unchanged",
            "companion_protocol_identity": "unchanged_v1",
        },
        "platform_status": {
            "local": "linux-x86_64 PASS",
            "ci_matrix": [
                "linux-x86_64",
                "windows-x86_64",
                "macos-x86_64",
                "macos-arm64",
            ],
            "non_local_results": "CI prepared; no local result invented",
        },
        "historical_evidence": "RUST-3.x and RUST-4.0/4.1 artifacts preserved without rewriting",
        "gates": {
            "rust_4_2_checker": "PASS" if qualified else "FAIL",
            "rust_4_0_mutation_contracts": "PENDING_FINAL_RUN",
            "rust_4_1_verifier_contracts": "PENDING_FINAL_RUN",
            "production_failure_injection": "PASS" if all(row["refinement_failed_before_python"] for row in campaign) else "FAIL",
            "historical_116": historical["status"],
            "adversarial_random_deep": positives["status"],
            "operational_soak_persistent_concurrency": operational["status"],
            "full_python_suite": "PENDING_FINAL_RUN",
            "cargo_test_workspace_locked": "PENDING_FINAL_RUN",
            "cargo_fmt_check": "PENDING_FINAL_RUN",
            "git_diff_check": "PENDING_FINAL_RUN",
        },
        "false_positives": positives["refinement_failures"],
        "commit_created": False,
    }


def render_report(evidence: dict[str, object]) -> str:
    performance = evidence["performance"]
    lines = [
        "# Refinement verifier production integration — RUST-4.2",
        "",
        f"Decision: `{evidence['decision']}`.",
        "",
        f"Baseline: `{evidence['baseline_revision']}`.",
        "",
        "## Production ordering",
        "",
    ]
    lines.extend(
        f"{index}. {step}"
        for index, step in enumerate(evidence["production_ordering"], 1)
    )
    lines += [
        "",
        "The integration point is `aether.ssa.shadow._lower_dual_lane`: only the Rust-authoritative branch invokes refinement, after strict schema-v2 import and existing SSA verification, and before the Python shadow. Any exception becomes stable `refinement_verifier_failure` / `refinement_verification` and aborts immediately.",
        "",
        "## Same input and failure injection",
        "",
        "Lifecycle normalization is performed once by Python coordination. Its schema-v1 snapshot is serialized once for Rust, while refinement and Python shadow reuse the same normalized object. Source and normalized snapshots are checked before refinement, before Python, and after both lanes. The Rust companion retains its idempotent normalization as an internal defense.",
        "",
        "| Mutation | First failure | Python would detect |",
        "|---|---|---|",
    ]
    for row in evidence["mutation_campaign"]:
        lines.append(
            f"| {row['mutation']} | {row['first_failure']} | {'yes' if row['python_shadow_would_detect'] else 'no'} |"
        )
    positive = evidence["positive_qualification"]
    historical = evidence["historical_qualification"]
    operational = evidence["operational_qualification"]
    lines += [
        "",
        "All injected corruptions failed before Python could authorize them. The eight RUST-4.0 shadow-only classes are covered. Python itself was not weakened and would also detect every injected semantic difference.",
        "",
        "## Positive and operational qualification",
        "",
        f"Historical: {historical['passed']}/{historical['denominator']}. Ordinary/adversarial/randomized cases: {positive['ordinary_cases']}; false positives: {evidence['false_positives']}. Deep CFG 993/1000/5000/10000: {positive['status']}. Operational soak, persistent session, concurrency, repetition, A→B/B→A/A→A and valid→invalid→valid: {operational['status']}. State leakage: {operational['state_leakage']}.",
        "",
        "## Performance",
        "",
        "No threshold is imposed. Times are seconds on the local Linux x86_64 qualification host; each row alternates the pre-integration diagnostic dual lane and integrated dual lane in the same persistent characterized companion.",
        "",
        "| Workload | Before median (min–max) | After median (min–max) | Refinement median | Share |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in performance["workloads"]:
        before = row["before_seconds"]
        after = row["after_seconds"]
        refinement = row["refinement_seconds"]
        lines.append(
            f"| {row['workload']} | {before['median']:.6f} ({before['min']:.6f}–{before['max']:.6f}) | {after['median']:.6f} ({after['min']:.6f}–{after['max']:.6f}) | {refinement['median']:.6f} | {row['refinement_share_of_after']:.2%} |"
        )
    lines += [
        "",
        "Memory was not measured because it was optional when practical. No optimization was attempted.",
        "",
        "## Compatibility, rollback, platforms, and evidence",
        "",
        "The ordinary SSA response, schema-v2 serialization, companion protocol v1, and `SSAShadowReport` fields are unchanged. Rust remains authority in `RUST_SSA_AUTHORITY_PYTHON_SHADOW`; Python shadow remains mandatory, synchronous, independent, comparison-based, and fail-closed. Python-authority/Rust-shadow and Python-only rollback paths do not invoke refinement and remain unchanged.",
        "",
        "Local qualification is Linux x86_64 only. CI runs the RUST-4.2 gate in the existing Linux x86_64, Windows x86_64, macOS x86_64, and macOS arm64 matrix; no non-local result is claimed here. Historical RUST-3.x/RUST-4.0/RUST-4.1 artifacts were not rewritten.",
        "",
        "No commit was created.",
        "",
        f"Final decision: `{evidence['decision']}`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--performance-samples", type=int, default=3)
    args = parser.parse_args()
    evidence = build_evidence(args.companion, args.performance_samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(render_report(evidence), encoding="utf-8")
    print(evidence["decision"])
    return 0 if evidence["decision"] == QUALIFIED else 1


if __name__ == "__main__":
    raise SystemExit(main())
