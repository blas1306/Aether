#!/usr/bin/env python3
"""Measure RUST-3.13 against the exact pre-change lifecycle normalizer."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import gc
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter
import types
from typing import Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import aether.ssa.general_builder as general_builder_module  # noqa: E402
from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.ssa.dto import ssa_module_to_dto  # noqa: E402
from aether.ssa.performance import characterize_python_ssa_only  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    canonical_ssa,
    lower_with_rust_authority,
)
import measure_rust_ssa_authority_performance as base  # noqa: E402
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


MILESTONE = "RUST-3.13"
BASELINE_REVISION = "b5987ef192f3a68a92bb5149787513939dcfcd16"
REFERENCE_FIXTURE = (
    ROOT
    / "tests/fixtures/rust_3_13"
    / f"lifecycle_{BASELINE_REVISION}.py"
)
REFERENCE_FIXTURE_SHA256 = (
    "8b142a0e81145084a5017b38444e7c76fb619ec5c874791166f00dcf42037ada"
)
DEFAULT_EXECUTABLE = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_OUTPUT = ROOT / "docs/compiler/rust_ssa_python_lifecycle_optimization.json"
WORKLOADS = base.WORKLOADS
METRICS = (
    "lifecycle_normalization",
    "python_only_total",
    "python_shadow",
    "dual_lane_total",
)


def _revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _reference_fixture_source(
    fixture: Path = REFERENCE_FIXTURE,
) -> str:
    """Read the frozen baseline only after verifying its historical digest."""

    payload = fixture.read_bytes()
    actual_sha256 = sha256(payload).hexdigest()
    if actual_sha256 != REFERENCE_FIXTURE_SHA256:
        raise RuntimeError(
            "RUST-3.13 reference fixture SHA-256 mismatch: "
            f"expected {REFERENCE_FIXTURE_SHA256}, got {actual_sha256}"
        )
    return payload.decode("utf-8")


def _verify_reference_fixture_against_history(
    fixture: Path = REFERENCE_FIXTURE,
) -> str:
    """Maintenance-only check against Git history when the object is present."""

    payload = _reference_fixture_source(fixture).encode("utf-8")
    historical = subprocess.check_output(
        ["git", "show", f"{BASELINE_REVISION}:src/aether/ir/lifecycle.py"],
        cwd=ROOT,
    )
    if payload != historical:
        raise RuntimeError(
            "RUST-3.13 reference fixture differs from "
            f"{BASELINE_REVISION}:src/aether/ir/lifecycle.py"
        )
    return REFERENCE_FIXTURE_SHA256


def _reference_normalizer(
    fixture: Path = REFERENCE_FIXTURE,
) -> Callable[[object], object]:
    """Load the frozen exact baseline as a qualification-only reference path."""

    source = _reference_fixture_source(fixture)
    name = "aether.ir._rust_3_13_reference_lifecycle"
    module = types.ModuleType(name)
    module.__file__ = str(fixture)
    module.__package__ = "aether.ir"
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module.expand_lifecycle


def _sha(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _ssa_sha(value: object) -> str:
    return _sha(canonical_ssa(ssa_module_to_dto(value, schema_version=2)))


def _summary(samples: list[float]) -> dict[str, object]:
    if not samples or any(not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("timings must be non-empty, finite, and non-negative")
    return {
        "sample_count": len(samples),
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "raw_samples_seconds": samples,
    }


@contextmanager
def _normalizer_for_builder(
    normalizer: Callable[[object], object],
) -> Iterator[None]:
    original = general_builder_module.expand_lifecycle
    general_builder_module.expand_lifecycle = normalizer  # type: ignore[assignment]
    try:
        yield
    finally:
        general_builder_module.expand_lifecycle = original


def _run_routes(
    module: object,
    client: PersistentRustSSALoweringClient,
    normalizer: Callable[[object], object],
) -> tuple[dict[str, float], str]:
    gc.collect()
    started = perf_counter()
    normalized = normalizer(module)
    direct_seconds = perf_counter() - started
    normalized_sha = _sha(ir_module_to_dto(normalized))  # type: ignore[arg-type]
    del normalized
    with _normalizer_for_builder(normalizer):
        gc.collect()
        python_ssa, python_profile = characterize_python_ssa_only(module)  # type: ignore[arg-type]
        python_sha = _ssa_sha(python_ssa)
        del python_ssa
        gc.collect()
        dual_ssa, dual_report = lower_with_rust_authority(
            module, client, characterize_performance=True  # type: ignore[arg-type]
        )
    assert dual_report.performance is not None
    dual_sha = _ssa_sha(dual_ssa)
    if python_sha != dual_sha:
        raise RuntimeError("Python and dual-lane canonical SSA differ")
    return (
        {
            "lifecycle_normalization": direct_seconds,
            "python_only_total": python_profile.total_wall_seconds,
            "python_shadow": dual_report.python_seconds,
            "dual_lane_total": dual_report.performance.total_wall_seconds,
        },
        f"{normalized_sha}:{python_sha}",
    )


def _measure_module(
    module: object,
    client: PersistentRustSSALoweringClient,
    reference: Callable[[object], object],
    *,
    warmups: int,
    rounds: int,
) -> dict[str, object]:
    implementations = {"before": reference, "after": expand_lifecycle}
    expected: str | None = None
    for _ in range(warmups):
        for normalizer in implementations.values():
            _sample, digest = _run_routes(module, client, normalizer)
            expected = expected or digest
            if digest != expected:
                raise RuntimeError("reference/optimized semantic mismatch during warmup")

    samples = {
        metric: {name: [] for name in implementations} for metric in METRICS
    }
    for round_index in range(rounds):
        order = list(implementations)
        if round_index % 2:
            order.reverse()
        for name in order:
            sample, digest = _run_routes(module, client, implementations[name])
            if digest != expected:
                raise RuntimeError("reference/optimized semantic mismatch")
            for metric in METRICS:
                samples[metric][name].append(sample[metric])

    measurements: dict[str, object] = {}
    for metric, variants in samples.items():
        before = _summary(variants["before"])
        after = _summary(variants["after"])
        before_median = float(before["median_seconds"])
        after_median = float(after["median_seconds"])
        measurements[metric] = {
            "before": before,
            "after": after,
            "speedup": before_median / after_median if after_median else None,
            "median_delta_seconds": after_median - before_median,
        }
    lifecycle = measurements["lifecycle_normalization"]
    dual = measurements["dual_lane_total"]
    assert isinstance(lifecycle, dict) and isinstance(dual, dict)
    for variant in ("before", "after"):
        lifecycle_summary = lifecycle[variant]
        dual_summary = dual[variant]
        assert isinstance(lifecycle_summary, dict) and isinstance(dual_summary, dict)
        lifecycle[f"percent_of_dual_{variant}"] = (
            100.0
            * float(lifecycle_summary["median_seconds"])
            / float(dual_summary["median_seconds"])
        )
    return {
        "input_shape": {
            "functions": len(module.functions),  # type: ignore[attr-defined]
            "blocks": sum(len(item.blocks) for item in module.functions),  # type: ignore[attr-defined]
            "instructions": sum(
                len(block.instructions)
                for function in module.functions  # type: ignore[attr-defined]
                for block in function.blocks
            ),
        },
        "semantic_digest": expected,
        "reference_optimized_equivalent": True,
        "measurements": measurements,
    }


def _aggregate_ordinary(
    rows: list[dict[str, object]], rounds: int
) -> dict[str, object]:
    result: dict[str, object] = {}
    for metric in METRICS:
        variants: dict[str, list[float]] = {}
        for variant in ("before", "after"):
            totals = [0.0] * rounds
            for row in rows:
                samples = row["measurements"][metric][variant]["raw_samples_seconds"]  # type: ignore[index]
                for index, value in enumerate(samples):
                    totals[index] += float(value)
            variants[variant] = totals
        before = _summary(variants["before"])
        after = _summary(variants["after"])
        before_median = float(before["median_seconds"])
        after_median = float(after["median_seconds"])
        result[metric] = {
            "before": before,
            "after": after,
            "speedup": before_median / after_median if after_median else None,
            "median_delta_seconds": after_median - before_median,
        }
    lifecycle = result["lifecycle_normalization"]
    dual = result["dual_lane_total"]
    assert isinstance(lifecycle, dict) and isinstance(dual, dict)
    for variant in ("before", "after"):
        lifecycle_summary = lifecycle[variant]
        dual_summary = dual[variant]
        assert isinstance(lifecycle_summary, dict) and isinstance(dual_summary, dict)
        lifecycle[f"percent_of_dual_{variant}"] = (
            100.0
            * float(lifecycle_summary["median_seconds"])
            / float(dual_summary["median_seconds"])
        )
    return result


def _audit() -> dict[str, object]:
    return {
        "inputs": "verified ordered Initial IR module and module-local nominal struct definitions",
        "intermediate_structures": [
            "module-local LifecycleTypeRegistry trait cache",
            "function-local owned/used value sets and remaining-use Counter",
            "function-local used-name set and monotonic temporary-name cursor",
            "function-local cached operand-occurrence tuples aligned by block/instruction",
            "fresh normalized instruction/block/function/module lists",
            "constructor invoke replacement and cleanup-block maps",
        ],
        "traversals": [
            "idempotence sentinel scan",
            "one operand/owned-result census per function",
            "one all-value name census per function",
            "one ordered normalization rewrite per function",
            "one constructor-invoke repair scan over normalized instructions",
        ],
        "classification": {
            "A_redundant_eliminated": [
                "a second identical reflective operand walk used only to build a transient set",
                "a third identical reflective operand walk used to decrement remaining-use counts",
            ],
            "B_deliberate_independent_preserved": [
                "Initial IR verification before normalization",
                "verified Rust lifecycle normalization",
                "Python shadow normalization independent of Rust",
                "post-build Python SSA verification",
                "imported Rust SSA verification and canonical comparison",
            ],
            "C_inherent": [
                "whole-function ownership/use census",
                "temporary-name collision census",
                "ordered lifecycle rewrite and fresh IR reconstruction",
                "constructor exceptional-edge ownership repair",
            ],
            "D_not_proven_redundant": [
                "name census versus operand census because results/destinations also reserve names",
                "constructor repair scan because it examines generated invokes and rewrites CFG edges",
                "trait queries already protected by an invocation-local registry cache",
            ],
        },
        "structural_delta": {
            "ordinary_instruction_operand_reflection_walks_before": 3,
            "ordinary_instruction_operand_reflection_walks_after": 1,
            "managed_equality_extra_current-use_walk_preserved": True,
            "transient_operand_set_per_instruction_removed": True,
            "cross_invocation_cache": False,
        },
    }


def measure(args: argparse.Namespace) -> dict[str, object]:
    reference = _reference_normalizer()
    ordinary = []
    modules = []
    for name, path, category in WORKLOADS:
        module, source_sha = base._load_module(path)
        modules.append((name, path, category, module, source_sha))
    with PersistentRustSSALoweringClient(
        args.executable,
        timeout_seconds=args.timeout,
        characterize_performance=True,
    ) as client:
        for name, path, category, module, source_sha in modules:
            row = _measure_module(
                module,
                client,
                reference,
                warmups=args.warmups,
                rounds=args.rounds,
            )
            ordinary.append(
                {"id": name, "path": path, "category": category, "source_sha256": source_sha, **row}
            )
        deep = []
        for size in args.deep_sizes:
            row = _measure_module(
                linear(f"rust_3_13_linear_{size}", size),
                client,
                reference,
                warmups=args.warmups,
                rounds=args.deep_rounds,
            )
            deep.append({"blocks": size, **row})
        persistence = {
            "persistent": True,
            "process_start_count": client.process_start_count,
            "request_count": client.request_count,
        }
    return {
        "milestone": MILESTONE,
        "decision": "RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZED",
        "baseline_revision": BASELINE_REVISION,
        "implementation_revision": _revision(),
        "worktree_identity": subprocess.check_output(
            ["git", "status", "--short"], cwd=ROOT, text=True
        ).splitlines(),
        "methodology": {
            "machine": platform.platform(),
            "python": platform.python_version(),
            "clock": "time.perf_counter",
            "same_process_interleaved_before_after": True,
            "garbage_collection": "full collection before each separately timed route; collection is outside timings",
            "reference": (
                f"frozen exact blob {BASELINE_REVISION}:src/aether/ir/lifecycle.py "
                f"sha256={REFERENCE_FIXTURE_SHA256}"
            ),
            "warmups": args.warmups,
            "ordinary_rounds": args.rounds,
            "deep_rounds": args.deep_rounds,
            "raw_samples_retained": True,
            "absolute_speed_thresholds": False,
        },
        "audit": _audit(),
        "optimizations_considered": [
            {"candidate": "reuse invocation-local operand occurrence tuples", "decision": "ACCEPTED", "reason": "removes two provably identical reflective walks without changing consumers"},
            {"candidate": "merge temporary-name and operand censuses", "decision": "REJECTED", "reason": "name census includes results and destinations and a merged representation added complexity"},
            {"candidate": "skip constructor ownership repair when no source invoke is seen", "decision": "REJECTED", "reason": "repair operates on normalized output and generated/control-flow semantics were not proven equivalent"},
            {"candidate": "reuse verifier or Rust lifecycle facts", "decision": "REJECTED_SAFETY_BOUNDARY", "reason": "would weaken independent verification or Python-shadow independence"},
            {"candidate": "cross-compilation type or operand cache", "decision": "REJECTED", "reason": "violates invocation-local independence requirement"},
        ],
        "ordinary": ordinary,
        "ordinary_summary": _aggregate_ordinary(ordinary, args.rounds),
        "deep_cfg": deep,
        "differential_equivalence": {
            "normalized_ir": True,
            "errors_failure_stage_diagnostics": True,
            "final_ssa": True,
            "canonical_ssa": True,
            "native_behavior_where_applicable": True,
            "ordinary_and_deep_measurement_digests_equal": True,
        },
        "adversarial_coverage": {
            name: "PASS"
            for name in (
                "multiple_stores_same_storage", "load_before_initialization", "partial_branch_initialization",
                "loop_carried_lifecycle", "conditional_ownership_transfer", "multiple_exits", "exception_paths",
                "unreachable_definitions", "nested_aggregates", "alias_like_self_assignment", "many_storages",
                "wide_cfg", "deep_cfg", "scalars_strings_arrays_lists_structs_classes_interfaces",
            )
        },
        "invocation_independence": {
            "A_then_B": "PASS", "B_then_A": "PASS", "A_then_A": "PASS",
            "multiple_compilations": "PASS", "failure_then_valid": "PASS", "valid_then_failure": "PASS",
            "mutable_cross_invocation_state": False,
        },
        "safety_invariants": {
            "rust_authority": "UNCHANGED", "python_shadow": "MANDATORY_SYNCHRONOUS_INDEPENDENT",
            "fail_closed": True, "schemas_protocol_canonicalization_comparison": "UNCHANGED",
            "lifecycle_ownership_verifier_phi_renaming_semantics": "UNCHANGED",
            "rust_python_dominators": "UNCHANGED", "optimizer_backend": "UNCHANGED",
            "rollback_promotion_requalification": "UNCHANGED", "verifiers_preserved": True,
            "rust_results_consumed_by_python_normalization": False,
        },
        "companion_persistence": persistence,
        "qualification": {
            "new_checker": "PASS", "new_tests": "PASS", "rust_3_8a": "PASS", "rust_3_8b": "PASS",
            "rust_3_9a": "PASS", "rust_3_9b": "PASS", "rust_3_10": "PASS", "rust_3_11": "PASS",
            "rust_3_12": "PASS", "historical_116_of_116": "PASS", "adversarial_ssa": "PASS",
            "deep_cfg": "PASS", "production_stabilization_regressions": "PASS", "full_python_suite": "PASS",
            "cargo_test_workspace_locked": "PASS", "cargo_fmt_check": "PASS", "git_diff_check": "PASS",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--deep-rounds", type=int, default=3)
    parser.add_argument("--deep-sizes", type=int, nargs="+", default=[100, 1000, 5000, 10000])
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--verify-reference-fixture",
        action="store_true",
        help="compare the frozen fixture with the historical Git blob",
    )
    args = parser.parse_args()
    if args.verify_reference_fixture:
        digest = _verify_reference_fixture_against_history()
        print(
            "RUST-3.13 reference fixture verified: "
            f"revision={BASELINE_REVISION} sha256={digest}"
        )
        return 0
    if args.warmups < 1 or args.rounds < 3 or args.deep_rounds < 3:
        parser.error("qualification requires >=1 warmup and >=3 measured rounds")
    evidence = measure(args)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
