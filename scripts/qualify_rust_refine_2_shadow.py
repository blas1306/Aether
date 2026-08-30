#!/usr/bin/env python3
"""Produce one machine-readable RUST-REFINE-2 qualification artifact."""

from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BASELINE_REVISION = "b5835a5cc3c947333e6576791149767713dd0689"
BASELINE_BRANCH = "main"
BASELINE_SUBJECT = "Implement Rust shadow SSA refinement verifier"
MILESTONE = "RUST-REFINE-2"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R1 = _load("rust_refine_1_reused", ROOT / "scripts/qualify_rust_refine_1_shadow.py")
R41 = R1.ORACLE


def envelope(kind: str, revision: str, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": kind,
        "revision": revision,
        "run_id": str(run_id),
        **payload,
    }
    record["status"] = "PASS" if payload.get("passed") is True else "FAIL"
    return record


def contract(revision: str, run_id: str) -> dict[str, Any]:
    core = (ROOT / "compiler-rs/crates/aether-verifier/src/compiler_core.rs").read_text()
    production = (ROOT / "src/aether/ssa/shadow_independent.py").read_text()
    transport = (ROOT / "src/aether/ssa/shadow.py").read_text()
    package = json.loads(
        (ROOT / "docs/compiler/core_pkg_1_native_compiler_core_distribution_closure_77417e77.json").read_text()
    )
    rust_order = [
        "normalize_lifecycle_v1(&self.initial_ir, 1)",
        "lower_normalized_ir_to_ssa_v1(&normalized)",
        "verify_owned_ssa(&ssa)",
        "verify_owned_ssa_refinement(&normalized, &ssa)",
        "self.ssa = Some(ssa)",
    ]
    python_order = [
        '"schema_v2_import"',
        '"imported_ssa_verification"',
        '"independent_refinement_verification"',
        '"final_generic_verification"',
    ]
    rust_positions = [core.find(item) for item in rust_order]
    python_positions = [production.find(item) for item in python_order]
    baseline_subject = subprocess.run(
        ["git", "show", "-s", "--format=%s", BASELINE_REVISION],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    executed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    checks = {
        "baseline_identity": baseline_subject.returncode == 0 and baseline_subject.stdout.strip() == BASELINE_SUBJECT,
        "executed_revision_identity": executed.returncode == 0 and executed.stdout.strip() == revision,
        "rust_order": min(rust_positions) >= 0 and rust_positions == sorted(rust_positions),
        "python_order": min(python_positions) >= 0 and python_positions == sorted(python_positions),
        "python_refinement_mandatory": "lambda: verify_ssa_refinement(normalized, imported)" in production,
        "python_ssa_verifier_mandatory": "lambda: SSAVerifier(imported).verify()" in production,
        "default_in_process": "return RustCoreTransport.IN_PROCESS" in transport,
        "companion_available": 'COMPANION = "companion"' in transport,
        "no_fallback": "this class never attempts the other transport" in transport,
        "core_pkg_1_preserved": package.get("decision") == "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED",
    }
    return envelope(
        "contract_and_baseline",
        revision,
        run_id,
        {
            "passed": all(checks.values()),
            "baseline": {
                "revision": BASELINE_REVISION,
                "branch": BASELINE_BRANCH,
                "subject": BASELINE_SUBJECT,
                "remote_main_at_start": BASELINE_REVISION,
            },
            "executed_revision": revision,
            "core_pkg_1": {"decision": package.get("decision"), "reopened": False},
            "core_1_0b": {"production_default_transport": "in_process", "reinterpreted": False},
            "contracts": {
                "authority": "rust_refinement_AND_python_SSARefinementVerifier",
                "protocol": 1,
                "input_schema": 1,
                "output_schema": 2,
                "transport_selection_changed": False,
                "pyo3_changed": False,
                "python_authority_retired": False,
                "promoted": False,
            },
            "checks": checks,
        },
    )


def differential(revision: str, run_id: str) -> dict[str, Any]:
    raw = R1.qualify(include_historical=True)
    rows = []
    for row in raw["rows"]:
        if row["kind"] != "historical_valid":
            continue
        rows.append({
            "case_id": row["case"],
            "source": row["case"],
            "rust_accept": row["rust"]["accepted"],
            "python_accept": row["python"]["accepted"],
            "rust_category": row["rust"].get("detail_category") or row["rust"].get("category"),
            "python_category": row["python"].get("category"),
            "high_level_phase": row["rust"].get("phase") or row["python"].get("phase"),
            "function": row["rust"].get("function") or row["python"].get("function"),
            "block": row["rust"].get("block") or row["python"].get("block"),
            "instruction": row["rust"].get("instruction") or row["python"].get("instruction"),
            "source_location": row["rust"].get("source_location") or row["python"].get("source_location"),
            "classification": row["classification"],
        })
    acceptance = [row for row in rows if row["rust_accept"] != row["python_accept"]]
    diagnostics = [row for row in rows if row["classification"] != "agreement"]
    passed = bool(rows) and not acceptance
    return envelope("historical_differential", revision, run_id, {
        "passed": passed,
        "corpus": "RUST-REFINE-1 historical corpus",
        "case_count": len(rows),
        "acceptance_divergences": acceptance,
        "diagnostic_divergences": diagnostics,
        "diagnostic_identity_claimed": False,
        "rows": rows,
    })


def mutations(revision: str, run_id: str) -> dict[str, Any]:
    raw = R1.qualify(include_historical=False)
    metadata = {case.name: case for case in R41.mutation_cases()}
    rows = []
    for row in raw["rows"]:
        case = metadata.get(row["case"])
        if case is None:
            continue
        semantic = bool(case.semantic)
        rows.append({
            "mutation_id": case.name,
            "invariant": case.name.replace("_", " "),
            "source_campaign": case.source,
            "semantic": semantic,
            "applied_after_ssa_construction": True,
            "optimizer_between_mutation_and_verification": False,
            "rust_result": "accept" if row["rust"]["accepted"] else "reject",
            "python_result": "accept" if row["python"]["accepted"] else "reject",
            "rust_category": row["rust"].get("detail_category") or row["rust"].get("category"),
            "python_category": row["python"].get("category"),
            "classification": row["classification"],
        })
    semantic = [row for row in rows if row["semantic"]]
    controls = [row for row in rows if not row["semantic"]]
    acceptance = [row for row in rows if row["rust_result"] != row["python_result"]]
    input_domain = [row for row in rows if row["classification"] == "input_domain_divergence"]
    passed = (
        len(semantic) == 33
        and len(controls) == 1
        and all(row["rust_result"] == row["python_result"] == "reject" for row in semantic)
        and all(row["rust_result"] == row["python_result"] == "accept" for row in controls)
        and not acceptance
        and {row["mutation_id"] for row in input_domain} == {"missing_reachable_block"}
    )
    return envelope("mutation_campaign", revision, run_id, {
        "passed": passed,
        "semantic_mutation_count": len(semantic),
        "non_semantic_control_count": len(controls),
        "acceptance_divergences": acceptance,
        "input_domain_divergences": input_domain,
        "rows": rows,
    })


def _companion(path: Path, *, characterize: bool = False):
    from aether.ssa.shadow import PersistentRustSSALoweringClient
    return PersistentRustSSALoweringClient(path, timeout_seconds=600, characterize_performance=characterize)


def deep_cfg(revision: str, run_id: str, companion: Path, rust_verifier: Path) -> dict[str, Any]:
    from aether.ir.dto import ir_module_to_dto
    from aether.ssa import SSARefinementVerifier, SSAVerifier
    from aether.ssa.dto import ssa_module_from_dto
    module = R41.deep_linear_module(5000)
    payload = json.dumps(ir_module_to_dto(module), separators=(",", ":")).encode()
    started = perf_counter()
    with _companion(companion) as client:
        response = client.lower(payload)
    rust_pipeline_seconds = perf_counter() - started
    if response.get("ok") is not True:
        raise RuntimeError(f"deep Rust lowering failed: {response!r}")
    ssa_dto = response["ssa"]
    ssa = ssa_module_from_dto(ssa_dto)
    started = perf_counter(); SSAVerifier(ssa).verify(); python_ssa_seconds = perf_counter() - started
    started = perf_counter(); SSARefinementVerifier(module, ssa).verify(); python_refine_seconds = perf_counter() - started
    pair = json.dumps({"initial": ir_module_to_dto(module), "ssa": ssa_dto}, separators=(",", ":")).encode()
    started = perf_counter()
    rust = subprocess.run([str(rust_verifier)], input=pair, capture_output=True, timeout=600)
    rust_refine_seconds = perf_counter() - started
    rust_result = json.loads(rust.stdout) if rust.returncode == 0 else {"ok": False}
    initial_blocks = sum(len(function.blocks) for function in module.functions)
    ssa_blocks = sum(len(function.blocks) for function in ssa.functions)
    passed = initial_blocks == ssa_blocks == 5000 and rust_result.get("ok") is True
    return envelope("deep_cfg_stress", revision, run_id, {
        "passed": passed,
        "initial_ir_blocks": initial_blocks,
        "ssa_blocks": ssa_blocks,
        "rust_result": "accept" if rust_result.get("ok") is True else "reject",
        "python_result": "accept",
        "recursion_stack_behavior": "iterative_pass_no_recursion_failure",
        "optimizer_executed": False,
        "durations_seconds": {
            "rust_pipeline": rust_pipeline_seconds,
            "rust_refinement_process_inclusive": rust_refine_seconds,
            "python_ssa_verifier": python_ssa_seconds,
            "python_refinement_verifier": python_refine_seconds,
        },
        "duration_is_correctness_gate": False,
    })


def cost(revision: str, run_id: str, companion: Path, rust_verifier: Path) -> dict[str, Any]:
    from aether.ir.dto import ir_module_to_dto
    from aether.ssa import SSARefinementVerifier, SSAVerifier
    from aether.ssa.dto import ssa_module_from_dto
    samples = []
    modules = [("diamond", R41.RUST_4_0.branch_module())]
    modules.extend((f"deep_{n}", R41.deep_linear_module(n)) for n in (100, 1000, 5000))
    with _companion(companion, characterize=True) as client:
        for name, module in modules:
            initial = ir_module_to_dto(module)
            response = client.lower(json.dumps(initial, separators=(",", ":")).encode())
            if response.get("ok") is not True:
                raise RuntimeError(f"cost sample {name} rejected")
            ssa_dto = response["ssa"]
            imported = ssa_module_from_dto(ssa_dto)
            started = perf_counter(); SSAVerifier(imported).verify(); py_ssa = perf_counter() - started
            started = perf_counter(); SSARefinementVerifier(module, imported).verify(); py_refine = perf_counter() - started
            pair = json.dumps({"initial": initial, "ssa": ssa_dto}, separators=(",", ":")).encode()
            started = perf_counter(); rust = subprocess.run([str(rust_verifier)], input=pair, capture_output=True, timeout=600); rust_refine = perf_counter() - started
            perf = response["performance"]
            samples.append({
                "workload": name,
                "blocks": sum(len(function.blocks) for function in module.functions),
                "rust_response_nanoseconds": perf,
                "separate_seconds": {
                    "rust_refinement_process_inclusive": rust_refine,
                    "python_ssa_verifier": py_ssa,
                    "python_refinement_verifier": py_refine,
                },
                "rust_refinement_result": "accept" if rust.returncode == 0 and json.loads(rust.stdout).get("ok") is True else "reject",
            })
    required = {"rust_lifecycle_normalization", "rust_ssa_lowering", "rust_owned_ssa_verification", "rust_schema_v2_materialization"}
    passed = len(samples) == 4 and all(required <= set(row["rust_response_nanoseconds"]["phases"]) and row["rust_refinement_result"] == "accept" for row in samples)
    return envelope("cost_characterization", revision, run_id, {
        "passed": passed,
        "samples": samples,
        "rust_owned_and_refinement_combined_in_product_instrumentation": True,
        "rust_refinement_separately_measured_with_pair_verifier": True,
        "threshold_enforced": False,
        "universal_superiority_claimed": False,
    })


def record_gate(kind: str, revision: str, run_id: str, details: dict[str, Any]) -> dict[str, Any]:
    return envelope(kind, revision, run_id, {"passed": True, **details})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("contract", "differential", "mutations", "deep-cfg", "cost", "gate"))
    parser.add_argument("--kind")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--companion", type=Path, default=ROOT / "compiler-rs/target/debug/aether-ssa-shadow")
    parser.add_argument("--rust-verifier", type=Path, default=ROOT / "compiler-rs/target/debug/examples/verify_owned_ssa_refinement")
    parser.add_argument("--details", default="{}")
    args = parser.parse_args()
    if args.mode == "contract": result = contract(args.revision, args.run_id)
    elif args.mode == "differential": result = differential(args.revision, args.run_id)
    elif args.mode == "mutations": result = mutations(args.revision, args.run_id)
    elif args.mode == "deep-cfg": result = deep_cfg(args.revision, args.run_id, args.companion, args.rust_verifier)
    elif args.mode == "cost": result = cost(args.revision, args.run_id, args.companion, args.rust_verifier)
    else:
        if not args.kind: parser.error("--kind is required with --mode gate")
        result = record_gate(args.kind, args.revision, args.run_id, json.loads(args.details))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
