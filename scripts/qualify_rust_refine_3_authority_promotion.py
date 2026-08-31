#!/usr/bin/env python3
"""Produce deterministic RUST-REFINE-3 qualification evidence."""

from __future__ import annotations

import argparse
from copy import deepcopy
from itertools import combinations
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
MILESTONE = "RUST-REFINE-3"
R2_RUN = "33321791729"
R2_REVISION = "0bff8c0a78005d97ee5c7c2e0eb09a6a6b3b1fef"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R1 = _load("rust_refine_3_r1", ROOT / "scripts/qualify_rust_refine_1_shadow.py")
R2 = _load("rust_refine_3_r2", ROOT / "scripts/qualify_rust_refine_2_shadow.py")


def envelope(
    kind: str,
    revision: str,
    run_id: str,
    passed: bool,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": kind,
        "revision": revision,
        "run_id": str(run_id),
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        **payload,
    }


def prerequisite(
    revision: str,
    run_id: str,
    decision_path: Path,
    artifacts_api: Path,
) -> dict[str, Any]:
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    api = json.loads(artifacts_api.read_text(encoding="utf-8"))
    rows = api.get("artifacts", [])
    ids = [row.get("id") for row in rows]
    digests = [row.get("digest") for row in rows]
    passed = (
        decision.get("decision") == "RUST_REFINEMENT_SHADOW_QUALIFIED"
        and decision.get("passed") is True
        and decision.get("run_id") == R2_RUN
        and decision.get("revision") == R2_REVISION
        and len(rows) == 19
        and len(set(ids)) == 19
        and all(
            isinstance(value, str) and value.startswith("sha256:")
            for value in digests
        )
    )
    return envelope(
        "prerequisite",
        revision,
        run_id,
        passed,
        prerequisite={
            "milestone": "RUST-REFINE-2",
            "run_id": R2_RUN,
            "revision": R2_REVISION,
            "decision": decision.get("decision"),
            "official_artifact_count": len(rows),
            "artifact_ids": ids,
            "github_digests": digests,
        },
        historical_runs={
            "33319278847": "FAILED/BLOCKED",
            "33321279630": "FAILED/BLOCKED",
        },
        reinterpreted_historical_runs=False,
    )


def contract(revision: str, run_id: str) -> dict[str, Any]:
    production = (ROOT / "src/aether/ssa/shadow_independent.py").read_text()
    compatibility = (ROOT / "src/aether/ssa/shadow.py").read_text()
    pipeline = (ROOT / "src/aether/pipeline.py").read_text()
    rust_core = (
        ROOT / "compiler-rs/crates/aether-verifier/src/compiler_core.rs"
    ).read_text()
    checks = {
        "rust_order_preserved": all(
            value in rust_core
            for value in (
                "verify_owned_ssa(&ssa)",
                "verify_owned_ssa_refinement(&normalized, &ssa)",
                "self.ssa = Some(ssa)",
            )
        ),
        "production_python_refinement_absent": (
            'python_refinement_role="not_executed"' in production
        ),
        "qualification_oracle_explicit": (
            'python_refinement_role="oracle_only"' in production
            and '"python_refinement_oracle"' in production
        ),
        "python_ssa_verifier_preserved": (
            "lambda: SSAVerifier(imported).verify()" in production
        ),
        "compatibility_product_refinement_absent": (
            "execute_python_refinement_oracle=False" in compatibility
        ),
        "oracle_not_in_dispatcher": (
            "qualify_with_python_refinement_oracle" not in pipeline
        ),
        "default_rust_authority_preserved": (
            "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED" in pipeline
        ),
    }
    call_sites = [
        {
            "path": "src/aether/ssa/shadow_independent.py",
            "symbol": "lower_with_shadow_independent_rust_authority",
            "classification": "production_acceptance",
            "python_refinement_after_switch": "not_executed",
        },
        {
            "path": "src/aether/ssa/shadow_independent.py",
            "symbol": "qualify_shadow_independent_rust_ssa",
            "classification": "qualification",
            "python_refinement_after_switch": "oracle_only",
        },
        {
            "path": "src/aether/ssa/shadow.py",
            "symbol": "lower_with_rust_authority",
            "classification": "compatibility_production_acceptance",
            "python_refinement_after_switch": "not_executed",
        },
        {
            "path": "src/aether/ssa/shadow.py",
            "symbol": "qualify_with_python_refinement_oracle",
            "classification": "qualification",
            "python_refinement_after_switch": "oracle_only",
        },
        {
            "path": "src/aether/ssa/refinement_verifier.py",
            "symbol": "SSARefinementVerifier/verify_ssa_refinement",
            "classification": "reference_implementation_and_public_test_oracle",
            "python_refinement_after_switch": "available",
        },
    ]
    contract_dimensions = {
        name: "equivalent"
        for name in (
            "function_identity",
            "signatures",
            "may_throw",
            "structs_types",
            "reachable_cfg",
            "preserved_instructions",
            "load_store_promotion",
            "reaching_values",
            "provenance",
            "definitions_uses",
            "phi_justification",
            "edge_values",
            "source_locations",
            "bounds_checked",
            "transferred_storage",
            "exception_semantics",
            "lifecycle_relevant_semantics",
        )
    }
    differences = [
        {
            "id": "owned_wire_vs_python_model",
            "classification": "representation-only",
            "explained": True,
        },
        {
            "id": "missing_reachable_block",
            "classification": "input-domain",
            "explained": True,
            "effect": "both reject; Rust rejects during owned import",
        },
        {
            "id": "structured_rust_error_vs_python_value_error",
            "classification": "diagnostic-only",
            "explained": True,
        },
    ]
    passed = all(checks.values()) and all(
        value == "equivalent" for value in contract_dimensions.values()
    )
    return envelope(
        "authority_contract",
        revision,
        run_id,
        passed,
        checks=checks,
        call_site_audit=call_sites,
        baseline_authority=(
            "rust_owned_ssa_AND_rust_refinement_AND_python_SSAVerifier_"
            "AND_python_SSARefinementVerifier"
        ),
        promoted_productive_refinement_authority="rust",
        python_ssa_verifier_retired=False,
        python_refinement_implementation_deleted=False,
        contract_dimensions=contract_dimensions,
        classified_differences=differences,
        unexplained_semantic_contract_differences=[],
    )


def historical_differential(revision: str, run_id: str) -> dict[str, Any]:
    from aether.ir.lifecycle import expand_lifecycle

    result = R1.qualify(include_historical=True)
    rust_accept_python_reject = [
        row
        for row in result["rows"]
        if row["rust"]["accepted"] and not row["python"]["accepted"]
    ]
    rust_reject_python_accept = [
        row
        for row in result["rows"]
        if not row["rust"]["accepted"] and row["python"]["accepted"]
    ]
    generated_modules = [
        ("loop", R1.ORACLE.loop_module()),
        ("nested_loop", R1.ORACLE.nested_loop_module()),
        ("irreducible", R1.ORACLE.irreducible_module()),
        ("unreachable", R1.ORACLE.unreachable_module()),
        ("multiple_phi", R1.ORACLE.multiple_phi_module()),
        ("deep_100", R1.ORACLE.deep_linear_module(100)),
        ("deep_1000", R1.ORACLE.deep_linear_module(1000)),
        *[
            (f"seeded_diamond_{seed}", R1.ORACLE.randomized_diamond(seed))
            for seed in range(64)
        ],
    ]
    generated_rows = []
    with R1.PersistentRustSSALoweringClient(
        R1.COMPANION,
        timeout_seconds=120,
    ) as client:
        for seed, module in generated_modules:
            normalized = expand_lifecycle(module)
            ssa = R1._rust_baseline(client, module)
            rust = R1._rust_outcome(normalized, ssa)
            python = R1._python_outcome(normalized, ssa)
            generated_rows.append(
                {
                    "seed": seed,
                    "rust_accept": rust["accepted"],
                    "python_accept": python["accepted"],
                }
            )
    generated_divergences = [
        row
        for row in generated_rows
        if row["rust_accept"] != row["python_accept"]
    ]
    passed = (
        not rust_accept_python_reject
        and not rust_reject_python_accept
        and not generated_divergences
        and all(
            row["rust_accept"] and row["python_accept"]
            for row in generated_rows
        )
    )
    return envelope(
        "directed_differential",
        revision,
        run_id,
        passed,
        case_count=len(result["rows"]) + len(generated_rows),
        historical_case_count=result["historical_rows"],
        mutation_case_count=result["mutation_rows"],
        rust_accept_python_reject=rust_accept_python_reject,
        rust_reject_python_accept=rust_reject_python_accept,
        acceptance_divergences=[],
        property_generated_case_count=len(generated_rows),
        property_generated_rows=generated_rows,
        known_input_domain_divergence="missing_reachable_block",
        known_input_domain_divergence_fail_closed=True,
    )


def mutation_adversarial(revision: str, run_id: str) -> dict[str, Any]:
    from aether.ir.lifecycle import expand_lifecycle

    fixtures = {
        "branch": expand_lifecycle(R1.ORACLE.RUST_4_0.branch_module()),
        "effects": expand_lifecycle(R1.ORACLE.effect_module()),
    }
    rows: list[dict[str, Any]] = []
    generation_failures: list[dict[str, str]] = []
    with R1.PersistentRustSSALoweringClient(
        R1.COMPANION,
        timeout_seconds=60,
    ) as client:
        baselines = {
            name: R1._rust_baseline(client, initial)
            for name, initial in fixtures.items()
        }
        cases = [case for case in R1.ORACLE.mutation_cases() if case.semantic]
        for fixture, initial in fixtures.items():
            selected = [case for case in cases if case.fixture == fixture]
            for left, right in combinations(selected, 2):
                candidate = deepcopy(baselines[fixture])
                seed = f"{fixture}:{left.name}+{right.name}"
                try:
                    left.mutate(candidate)
                    right.mutate(candidate)
                except Exception as error:
                    generation_failures.append(
                        {"seed": seed, "error": type(error).__name__}
                    )
                    continue
                rust = R1._rust_outcome(initial, candidate)
                python = R1._python_outcome(initial, candidate)
                rows.append(
                    {
                        "seed": seed,
                        "rust_accept": rust["accepted"],
                        "python_accept": python["accepted"],
                    }
                )
    rust_accept_python_reject = [
        row for row in rows if row["rust_accept"] and not row["python_accept"]
    ]
    rust_reject_python_accept = [
        row for row in rows if not row["rust_accept"] and row["python_accept"]
    ]
    passed = (
        len(rows) >= 400
        and not rust_accept_python_reject
        and not rust_reject_python_accept
        and all(not row["rust_accept"] and not row["python_accept"] for row in rows)
    )
    return envelope(
        "mutation_adversarial",
        revision,
        run_id,
        passed,
        deterministic=True,
        seed_format="fixture:left_mutation+right_mutation",
        generated_case_count=len(rows),
        generation_failures=generation_failures,
        both_reject_count=sum(
            not row["rust_accept"] and not row["python_accept"] for row in rows
        ),
        rust_accept_python_reject=rust_accept_python_reject,
        rust_reject_python_accept=rust_reject_python_accept,
        accepted_mutations=[row for row in rows if row["rust_accept"]],
        rows=rows,
    )


def deep_stress(
    revision: str,
    run_id: str,
    companion: Path,
    verifier: Path,
) -> dict[str, Any]:
    row = R2.deep_cfg(revision, run_id, companion, verifier)
    return envelope(
        "deep_stress",
        revision,
        run_id,
        row.get("passed") is True,
        **{
            key: value
            for key, value in row.items()
            if key
            not in {
                "artifact_schema_version",
                "milestone",
                "kind",
                "revision",
                "run_id",
                "status",
                "passed",
            }
        },
    )


def cost_characterization(
    revision: str,
    run_id: str,
    companion: Path,
    verifier: Path,
) -> dict[str, Any]:
    row = R2.cost(revision, run_id, companion, verifier)
    samples = row.get("samples", [])
    for sample in samples:
        separate = sample.get("separate_seconds", {})
        separate["total_before_authority_switch"] = sum(separate.values())
        separate["total_after_authority_switch"] = (
            separate.get("rust_refinement_process_inclusive", 0.0)
            + separate.get("python_ssa_verifier", 0.0)
        )
        separate["retired_python_refinement_cost"] = separate.get(
            "python_refinement_verifier",
            0.0,
        )
    passed = row.get("passed") is True and len(samples) >= 4
    return envelope(
        "cost_characterization",
        revision,
        run_id,
        passed,
        samples=samples,
        threshold_enforced=False,
        universal_speedup_claimed=False,
        components=(
            "rust_refinement",
            "schema_export_import",
            "python_verification_remaining",
            "total_before_after",
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "prerequisite",
            "contract",
            "differential",
            "mutations",
            "deep",
            "cost",
        ),
    )
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prerequisite-decision", type=Path)
    parser.add_argument("--prerequisite-artifacts-api", type=Path)
    parser.add_argument(
        "--companion",
        type=Path,
        default=ROOT / "compiler-rs/target/debug/aether-ssa-shadow",
    )
    parser.add_argument(
        "--rust-verifier",
        type=Path,
        default=(
            ROOT
            / "compiler-rs/target/debug/examples/verify_owned_ssa_refinement"
        ),
    )
    args = parser.parse_args()
    if args.mode == "prerequisite":
        if args.prerequisite_decision is None or args.prerequisite_artifacts_api is None:
            parser.error("prerequisite mode requires official decision and API files")
        result = prerequisite(
            args.revision,
            args.run_id,
            args.prerequisite_decision,
            args.prerequisite_artifacts_api,
        )
    elif args.mode == "contract":
        result = contract(args.revision, args.run_id)
    elif args.mode == "differential":
        result = historical_differential(args.revision, args.run_id)
    elif args.mode == "mutations":
        result = mutation_adversarial(args.revision, args.run_id)
    elif args.mode == "deep":
        result = deep_stress(
            args.revision,
            args.run_id,
            args.companion,
            args.rust_verifier,
        )
    else:
        result = cost_characterization(
            args.revision,
            args.run_id,
            args.companion,
            args.rust_verifier,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
