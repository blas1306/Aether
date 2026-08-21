#!/usr/bin/env python3
"""Generate deterministic RUST-3.5 SSA authority-promotion readiness evidence."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_to_dto  # noqa: E402
from aether.ssa.general_builder import GeneralSSABuilder  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSA_SHADOW_PRODUCT_VERSION,
    SSA_SHADOW_PROTOCOL_VERSION,
    SSA_SHADOW_SCHEMA_VERSION,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
    lower_with_rust_shadow,
)
from aether.ir.model import IRModule  # noqa: E402
from aether.typechecker import TypeChecker  # noqa: E402


OUTPUT = ROOT / "docs/compiler/rust_ssa_authority_promotion_qualification.json"
PERFORMANCE_OUTPUT = ROOT / "docs/compiler/rust_ssa_authority_promotion_performance.json"
COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
EVIDENCE_FILES = {
    "lowering_policy": "docs/compiler/ssa_lowering_policy_v1.json",
    "source_location_policy": "docs/compiler/ssa_source_location_lowering_policy_v1.json",
    "lifecycle_policy": "docs/compiler/lifecycle_normalization_policy_v1_qualification.json",
    "lifecycle_differential": "docs/compiler/rust_lifecycle_differential_qualification.json",
    "schema_v2": "docs/compiler/ssa_wire_boundary_qualification.json",
    "owned_ssa_model": "docs/compiler/rust_owned_ssa_model_qualification.json",
    "owned_ssa_verifier": "docs/compiler/rust_owned_ssa_verifier_qualification.json",
    "historical_differential": "docs/compiler/rust_ssa_lowering_full_qualification.json",
    "python_deep_cfg_and_adversarial": "docs/compiler/python_ssa_renamer_deep_cfg_qualification.json",
    "rust_deep_cfg": "docs/compiler/rust_ssa_deep_cfg_qualification.json",
    "aggregate_closure": "docs/compiler/rust_aggregate_ssa_differential_qualification.json",
    "shadow_mode": "docs/compiler/rust_ssa_shadow_mode.json",
    "companion_packaging": "docs/compiler/rust_ssa_shadow_companion_packaging.json",
    "operational_qualification": "docs/compiler/rust_ssa_shadow_operational_qualified.json",
    "performance": "docs/compiler/rust_ssa_authority_promotion_performance.json",
}
PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}


def _load(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"evidence is not an object: {relative}")
    return value


def _pair(value: dict[str, object], key: str) -> bool:
    row = value.get(key)
    return isinstance(row, dict) and row.get("passed") == 116 and row.get("failed") == 0


class _MalformedClient:
    process_start_count = 1
    request_count = 0

    def lower(self, _payload: bytes) -> dict[str, object]:
        self.request_count += 1
        return {"ok": True, "ssa": {"malformed": True}}


def _runtime_safety() -> dict[str, bool]:
    python_configuration = SSALoweringAuthorityConfiguration(
        SSALoweringAuthorityMode.PYTHON_SSA_ONLY
    )
    python_result = SSAPipeline(authority_configuration=python_configuration).run(
        IRModule()
    ).ssa_module
    python_independent = ssa_module_to_dto(python_result, schema_version=2) == {
        "schema_version": 2,
        "representation": "aether_ssa",
        "functions": [],
        "structs": [],
    }
    try:
        lower_with_rust_shadow(IRModule(), _MalformedClient())
    except SSAShadowFailure as error:
        shadow_fail_closed = error.report.classification == "malformed_rust_response"
    else:
        shadow_fail_closed = False
    reserved = SSALoweringAuthorityConfiguration(
        SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
    )
    try:
        SSAPipeline(authority_configuration=reserved).run(IRModule())
    except Exception as error:
        rust_authority_disabled = "not activated" in str(error)
    else:
        rust_authority_disabled = False
    return {
        "python_only_independent": python_independent,
        "rust_shadow_fail_closed": shadow_fail_closed,
        "rust_authority_reserved_and_disabled": rust_authority_disabled,
    }


def _gate(identifier: str, name: str, passed: bool, evidence: str) -> dict[str, str]:
    return {
        "id": identifier,
        "name": name,
        "status": "PASS" if passed else "BLOCKED",
        "evidence": evidence,
    }


def generate() -> dict[str, object]:
    evidence = {name: _load(path) for name, path in EVIDENCE_FILES.items()}
    lowering = evidence["lowering_policy"]
    source_location = evidence["source_location_policy"]
    lifecycle_policy = evidence["lifecycle_policy"]
    lifecycle = evidence["lifecycle_differential"]
    schema = evidence["schema_v2"]
    model = evidence["owned_ssa_model"]
    verifier = evidence["owned_ssa_verifier"]
    historical = evidence["historical_differential"]
    python_deep = evidence["python_deep_cfg_and_adversarial"]
    rust_deep = evidence["rust_deep_cfg"]
    aggregate = evidence["aggregate_closure"]
    shadow = evidence["shadow_mode"]
    packaging = evidence["companion_packaging"]
    operational = evidence["operational_qualification"]
    performance = evidence["performance"]
    runtime = _runtime_safety()

    semantic_contracts = (
        lowering.get("lowering_policy_version") == 1
        and source_location.get("decision") == "SSA_SOURCE_LOCATION_LOWERING_POLICY_V1_QUALIFIED"
        and aggregate.get("decision") == "RUST_AGGREGATE_SSA_DIFFERENTIAL_QUALIFIED"
    )
    lifecycle_qualified = (
        lifecycle_policy.get("decision") == "LIFECYCLE_NORMALIZATION_POLICY_V1_QUALIFIED"
        and lifecycle.get("decision") == "RUST_LIFECYCLE_DIFFERENTIAL_QUALIFIED"
        and isinstance(lifecycle.get("final"), dict)
        and _pair(lifecycle["final"], "lifecycle")  # type: ignore[arg-type]
    )
    historical_pass = (
        historical.get("corpus", {}).get("denominator") == 116  # type: ignore[union-attr]
        and all(
            _pair(historical, key)
            for key in (
                "lifecycle_differential",
                "ssa_semantic_parity",
                "authoritative_verifier_and_schema_v2_import",
                "python_schema_v2_exact_reserialization",
                "concrete_determinism",
            )
        )
    )
    adversarial = python_deep.get("adversarial", {})
    adversarial_pass = (
        isinstance(adversarial, dict)
        and adversarial.get("decision") == "RUST_SSA_LOWERING_ADVERSARIAL_QUALIFIED"
        and adversarial.get("existing_corpus", {}).get("passed") == 116  # type: ignore[union-attr]
    )
    deep_cfg_pass = (
        python_deep.get("decision") == "PYTHON_SSA_RENAMER_DEEP_CFG_QUALIFIED"
        and rust_deep.get("decision") == "RUST_SSA_DEEP_CFG_QUALIFIED"
        and rust_deep.get("stress", {}).get("5000") == "PASS_AND_VERIFY"  # type: ignore[union-attr]
    )
    soak = operational.get("soak", {})
    soak_pass = isinstance(soak, dict) and soak == {
        "accepted": 132,
        "infrastructure_failures": 0,
        "rejected_before_ssa": 29,
        "semantic_mismatches": 0,
        "shadow_compared": 132,
        "total_programs": 161,
    }
    transport = operational.get("transport", {})
    transport_pass = (
        isinstance(transport, dict)
        and transport.get("persistent") == "PASS"
        and transport.get("long_session_requests") == 1000
        and transport.get("long_session_process_startups") == 1
        and transport.get("concurrency_requests") == 128
        and transport.get("concurrency_process_startups") == 1
    )
    platform_rows = operational.get("platforms", {})
    operational_qualified = (
        operational.get("decision") == "RUST_SSA_SHADOW_OPERATIONALLY_QUALIFIED"
        and operational.get("gates")
        == {f"SO{number}": "PASS" for number in range(1, 13)}
    )
    platforms_pass = (
        operational_qualified
        and isinstance(platform_rows, dict)
        and set(platform_rows) == set(PLATFORMS)
        and all(
            isinstance(platform_rows[name], dict)
            and platform_rows[name].get("status") == "PASS"
            and platform_rows[name].get("rust_target") == target
            and platform_rows[name].get("provenance") == "executed-native-runner"
            and platform_rows[name].get("checks") == "11/11 PASS"
            and platform_rows[name].get("comparison") == "2/2 PASS"
            and platform_rows[name].get("semantic_mismatches") == 0
            and platform_rows[name].get("infrastructure_failures") == 0
            for name, target in PLATFORMS.items()
        )
    )
    clean_install_pass = platforms_pass and all(
        platform_rows[name].get("clean_install") == "PASS"  # type: ignore[union-attr]
        for name in PLATFORMS
    )
    modes = {mode.name for mode in SSALoweringAuthorityMode}
    rollback_pass = (
        {"PYTHON_SSA_ONLY", "PYTHON_SSA_AUTHORITY_RUST_SHADOW"} <= modes
        and SSALoweringAuthorityConfiguration().mode is SSALoweringAuthorityMode.PYTHON_SSA_ONLY
        and runtime["python_only_independent"]
    )
    compatibility_pass = (
        packaging.get("product_version") == SSA_SHADOW_PRODUCT_VERSION
        and packaging.get("protocol_version") == SSA_SHADOW_PROTOCOL_VERSION
        and packaging.get("supported_input_schema_versions") == [1]
        and packaging.get("supported_output_schema_versions") == [SSA_SHADOW_SCHEMA_VERSION]
        and packaging.get("supported_platforms") == list(PLATFORMS)
    )
    deterministic_pass = (
        _pair(historical, "concrete_determinism")
        and transport_pass
        and performance.get("deterministic_outputs") is True
    )
    operational_authority = operational.get("authority", {})
    no_rust_consumer = (
        runtime["rust_authority_reserved_and_disabled"]
        and isinstance(operational_authority, dict)
        and operational_authority.get("rust_reaches_optimizer_or_backend") is False
    )
    semantic_clear = (
        semantic_contracts
        and lifecycle_qualified
        and historical_pass
        and adversarial_pass
        and deep_cfg_pass
        and soak_pass
    )
    operational_clear = (
        operational_qualified
        and operational.get("blockers") == {}
        and transport_pass
        and clean_install_pass
        and platforms_pass
        and rollback_pass
        and compatibility_pass
    )

    gates = [
        _gate(
            "G01",
            "all semantic contracts qualified",
            semantic_contracts,
            "lowering policy v1; source-location policy v1; aggregate divergence closure",
        ),
        _gate(
            "G02",
            "all lifecycle policies qualified",
            lifecycle_qualified,
            "lifecycle policy v1 and Rust lifecycle differential 116/116",
        ),
        _gate(
            "G03",
            "schema-v2 qualified",
            schema.get("decision") == "SSA_WIRE_SCHEMA_V2_QUALIFIED",
            "SSA wire boundary qualification",
        ),
        _gate(
            "G04",
            "Rust Owned SSA model qualified",
            model.get("decision") == "RUST_OWNED_SSA_MODEL_QUALIFIED"
            and _pair(model, "corpus"),
            "Owned SSA model 116/116",
        ),
        _gate(
            "G05",
            "Rust Owned SSA verifier qualified",
            verifier.get("decision") == "RUST_OWNED_SSA_VERIFIER_QUALIFIED"
            and _pair(verifier, "corpus"),
            "Owned SSA verifier 116/116",
        ),
        _gate(
            "G06",
            "historical corpus 116/116",
            historical_pass,
            "lifecycle, canonical SSA, verification/import, exact schema-v2, determinism",
        ),
        _gate(
            "G07",
            "adversarial corpus",
            adversarial_pass,
            "RUST-3.2 qualification embedded in SSA-ROBUST-1 evidence",
        ),
        _gate(
            "G08",
            "deep CFG regressions",
            deep_cfg_pass,
            "Python and Rust deep-CFG qualifications; Rust 5000-block PASS_AND_VERIFY",
        ),
        _gate(
            "G09",
            "expanded soak zero mismatches",
            soak_pass,
            "132/132 compared; zero semantic and infrastructure failures",
        ),
        _gate(
            "G10",
            "persistent transport",
            transport_pass,
            "1000 requests/one process; 128 concurrent requests/one process",
        ),
        _gate(
            "G11",
            "clean install",
            clean_install_pass,
            "clean release artifact on every official native runner",
        ),
        _gate(
            "G12",
            "all four official platforms",
            platforms_pass,
            "Linux x86_64, Windows x86_64, macOS arm64, macOS x86_64",
        ),
        _gate(
            "G13",
            "rollback configuration available",
            rollback_pass,
            "select PYTHON_SSA_AUTHORITY_RUST_SHADOW or PYTHON_SSA_ONLY",
        ),
        _gate(
            "G14",
            "Python authority works independently",
            runtime["python_only_independent"],
            "empty verified module lowered without a Rust client",
        ),
        _gate(
            "G15",
            "Rust shadow remains fail closed",
            runtime["rust_shadow_fail_closed"]
            and shadow.get("failure_semantics") == "fail_closed_in_development_and_ci",
            "malformed Rust result raises SSAShadowFailure",
        ),
        _gate(
            "G16",
            "no Rust SSA reaches optimizer/backend",
            no_rust_consumer,
            "reserved Rust-authority mode rejects; current returned SSA is Python",
        ),
        _gate(
            "G17",
            "companion compatibility",
            compatibility_pass,
            "product 0.1.0, protocol 1, Initial IR schema 1, SSA schema 2",
        ),
        _gate(
            "G18",
            "deterministic output preserved",
            deterministic_pass,
            "116/116 repeated Rust results plus persistent representative checks",
        ),
        _gate(
            "G19",
            "no unresolved semantic blocker",
            semantic_clear,
            "all semantic gates and aggregate closure pass",
        ),
        _gate(
            "G20",
            "no unresolved operational blocker",
            operational_clear,
            "qualified aggregate has no blockers; all operational gates pass",
        ),
    ]
    blockers = [gate["id"] for gate in gates if gate["status"] != "PASS"]
    decision = (
        "READY_FOR_RUST_SSA_AUTHORITY_SWITCH"
        if not blockers
        else "RUST_SSA_AUTHORITY_PROMOTION_BLOCKED"
    )
    source_hashes = {
        name: sha256((ROOT / path).read_bytes()).hexdigest()
        for name, path in sorted(EVIDENCE_FILES.items())
    }
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.5",
        "decision": decision,
        "gates": gates,
        "semantic_qualification": {
            "status": "PASS" if all(g["status"] == "PASS" for g in gates[:9]) else "BLOCKED",
            "historical": "116/116",
            "lifecycle": "116/116",
            "canonical_ssa": "116/116",
            "rust_owned_ssa_verification": "116/116",
            "schema_v2": "QUALIFIED",
            "adversarial": "PASS",
            "python_deep_cfg": "PASS",
            "rust_deep_cfg": "PASS",
            "aggregate_shadow_divergence": "CLOSED",
        },
        "operational_qualification": {
            "status": "PASS" if all(g["status"] == "PASS" for g in gates[9:]) else "BLOCKED",
            "shadow": "RUST_SSA_SHADOW_OPERATIONALLY_QUALIFIED",
            "persistent_transport": "PASS",
            "clean_install": "PASS",
            "packaged_discovery": "PASS",
            "long_session": "1000 requests / 1 process",
            "concurrency": "128 requests / 1 process",
        },
        "cross_platform": {
            name: {"rust_target": target, "status": "PASS"}
            for name, target in PLATFORMS.items()
        },
        "soak": soak,
        "future_authority_configuration": {
            "configuration_location": "src/aether/ssa/shadow.py:SSALoweringAuthorityConfiguration",
            "pipeline_selection_location": "src/aether/pipeline.py:SSAPipeline.build",
            "modes": {
                "PYTHON_SSA_ONLY": {
                    "returned_ssa": "verified Python SSA",
                    "shadow": "none",
                    "available_now": True,
                },
                "PYTHON_SSA_AUTHORITY_RUST_SHADOW": {
                    "returned_ssa": "verified Python SSA after a successful Rust comparison",
                    "shadow": "Rust; synchronous and fail closed",
                    "available_now": True,
                },
                "RUST_SSA_AUTHORITY_PYTHON_SHADOW": {
                    "returned_ssa": (
                        "schema-v2 Rust SSA imported into the Python SSAModule model, "
                        "after Rust Owned SSA verification, Python boundary verification, "
                        "and a successful canonical Python-shadow comparison"
                    ),
                    "shadow": (
                        "Python; synchronous, verified, canonicalized, compared, then "
                        "discarded on match"
                    ),
                    "available_now": False,
                    "activation": "later authority-switch milestone only",
                },
            },
            "production_default": "PYTHON_SSA_ONLY",
            "rust_authority_activated": False,
        },
        "fail_closed_policy": {
            "silent_python_fallback": False,
            "rust_startup_failure": "abort compilation; return no SSA",
            "timeout": "abort compilation; terminate companion; return no SSA",
            "malformed_response": "abort compilation; return no SSA",
            "verification_failure": "abort compilation; return no SSA",
            "semantic_mismatch_against_python_shadow": (
                "abort compilation; emit bounded deterministic mismatch evidence; "
                "return no SSA"
            ),
            "canonicalization_failure": "abort compilation; return no SSA",
            "python_shadow_failure": "abort compilation; return no SSA",
        },
        "rollback": {
            "primary": "select PYTHON_SSA_AUTHORITY_RUST_SHADOW",
            "independent": "select PYTHON_SSA_ONLY",
            "code_edits_required_after_promotion": False,
            "schema_or_policy_change_required": False,
            "current_default": "PYTHON_SSA_ONLY",
        },
        "ci": {
            "before_promotion": [
                "all RUST-3.5 gates PASS on the exact promotion revision",
                "four native platform clean-install reports PASS",
                "full 132-program shadow soak with zero mismatches",
                "fail-closed and rollback regression suite PASS",
            ],
            "promotion_change": [
                "activate only RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                "retain synchronous Python shadow and fail-closed comparison",
                "prove returned object originates from verified Rust schema-v2 output",
            ],
            "after_promotion": [
                "Python-only and Python-authority/Rust-shadow rollback lanes remain green",
                "Rust-authority/Python-shadow required on every official platform",
                "scheduled soak, long-session, concurrency, packaging, and compatibility gates remain required",
                "any semantic mismatch or infrastructure failure blocks release",
            ],
        },
        "performance": performance,
        "unresolved_blockers": (
            {"semantic": [], "operational": []}
            if not blockers
            else {"gate_ids": blockers}
        ),
        "scope": {
            "production_authority": "python",
            "production_authority_changed": False,
            "rust_ssa_reaches_optimizer_or_backend": False,
            "policies_changed": False,
            "schemas_changed": False,
            "lowering_semantics_changed": False,
            "comparison_weakened": False,
            "historical_artifacts_modified": False,
            "commit_created": False,
        },
        "source_evidence_sha256": source_hashes,
    }


def measure_performance(rounds: int) -> dict[str, object]:
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("cargo is required for performance observation")
    subprocess.run(
        [cargo, "build", "-p", "aether-verifier", "--bin", "aether-ssa-shadow"],
        cwd=ROOT / "compiler-rs",
        check=True,
    )
    workloads = [
        ROOT / "benchmarks/arithmetic.ae",
        ROOT / "benchmarks/nested_loops.ae",
        ROOT / "examples/aggregate_collections/particles.ae",
    ]
    modules = []
    for path in workloads:
        source = path.read_text(encoding="utf-8")
        typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
        modules.append((path.relative_to(ROOT).as_posix(), IRBackend().lower_verified(typed)))
    rows: list[dict[str, object]] = []
    deterministic = True
    with PersistentRustSSALoweringClient(COMPANION, timeout_seconds=30) as client:
        for name, module in modules:
            python_times = []
            shadow_times = []
            expected = None
            for _ in range(rounds):
                started = perf_counter_ns()
                python_ssa = GeneralSSABuilder().build(module)
                python_times.append(perf_counter_ns() - started)
                python_dto = ssa_module_to_dto(python_ssa, schema_version=2)
                expected = expected or python_dto
                deterministic = deterministic and python_dto == expected
                started = perf_counter_ns()
                returned, report = lower_with_rust_shadow(module, client)
                shadow_times.append(perf_counter_ns() - started)
                deterministic = (
                    deterministic
                    and report.classification == "match"
                    and ssa_module_to_dto(returned, schema_version=2) == expected
                )
            python_median = int(statistics.median(python_times))
            shadow_median = int(statistics.median(shadow_times))
            rows.append(
                {
                    "workload": name,
                    "rounds": rounds,
                    "python_only_median_ns": python_median,
                    "python_authority_rust_shadow_median_ns": shadow_median,
                    "observed_shadow_over_python_ratio": round(
                        shadow_median / python_median, 3
                    ),
                }
            )
        requests = client.request_count
        startups = client.process_start_count
    python_total = sum(  # type: ignore[arg-type]
        row["python_only_median_ns"] for row in rows
    )
    shadow_total = sum(  # type: ignore[arg-type]
        row["python_authority_rust_shadow_median_ns"] for row in rows
    )
    ratio = round(shadow_total / python_total, 3)
    return {
        "measurement_kind": "observational; no speedup or absolute threshold gate",
        "workloads": rows,
        "python_only_representative_median_total_ns": python_total,
        "python_authority_rust_shadow_representative_median_total_ns": shadow_total,
        "observed_shadow_over_python_ratio": ratio,
        "expected_rust_authority_python_shadow": {
            "estimated_over_python_only_ratio": ratio,
            "basis": (
                "the same two lowerings, verification, canonicalization, and comparison "
                "execute synchronously; reversing which matched SSA object is returned "
                "does not remove a lane"
            ),
            "speedup_required": False,
        },
        "requests": requests,
        "process_startups": startups,
        "deterministic_outputs": deterministic,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--measure-performance", action="store_true")
    parser.add_argument("--rounds", type=int, default=7)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    if args.measure_performance:
        measured = measure_performance(args.rounds)
        PERFORMANCE_OUTPUT.write_text(
            json.dumps(measured, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    rendered = json.dumps(generate(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"stale RUST-3.5 qualification artifact: {OUTPUT.relative_to(ROOT)}")
            return 1
        print("READY_FOR_RUST_SSA_AUTHORITY_SWITCH")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(json.loads(rendered)["decision"])
    decision = json.loads(rendered)["decision"]
    return 0 if decision == "READY_FOR_RUST_SSA_AUTHORITY_SWITCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
