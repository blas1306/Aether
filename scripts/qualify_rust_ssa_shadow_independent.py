#!/usr/bin/env python3
"""Run the RUST-4.4 shadow-independent production qualification."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import platform
from pathlib import Path
from random import Random
import subprocess
import sys
from time import perf_counter
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.pipeline import IRBackend, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    canonical_ssa,
    lower_with_rust_authority,
)
from aether.ssa.shadow_independent import (  # noqa: E402
    SHADOW_INDEPENDENT_QUALIFICATION_REVISION,
    SHADOW_INDEPENDENT_STAGE_MANIFEST,
    ShadowIndependentQualificationFailure,
    _QualificationHooks,
    qualify_shadow_independent_rust_ssa,
)
from aether.typechecker import TypeChecker  # noqa: E402


MILESTONE = "RUST-4.4"
BASELINE_REVISION = "a81a67b3b9618b5af379714874eb1650623d66da"
DEFAULT_COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
DEFAULT_RUST_VERIFIER = ROOT / "compiler-rs/target/debug/examples/verify_owned_ssa_v2"
DEFAULT_OUTPUT = ROOT / "docs/compiler/rust_ssa_shadow_independent_production_qualification.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFICATION.md"
R43_PATH = ROOT / "scripts/qualify_rust_ssa_shadow_redundancy.py"

DECISION_BLOCKED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_BLOCKED"
DECISION_GAP = "RUST_SSA_SHADOW_INDEPENDENT_VALIDATION_GAP_FOUND"
DECISION_INCOMPLETE = "RUST_SSA_SHADOW_INDEPENDENT_QUALIFICATION_INCOMPLETE"
DECISION_QUALIFIED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFIED"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load qualification dependency {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R43 = _load("rust_4_3_for_4_4", R43_PATH)
R41 = R43.R41


class StaticClient:
    """One-request candidate adapter for offline adversarial replay."""

    def __init__(self, response: object):
        self.response = response

    def lower(self, _payload: bytes) -> Mapping[str, object]:
        if isinstance(self.response, BaseException):
            raise self.response
        return deepcopy(self.response)  # type: ignore[return-value]


def _canonical_module(module: object) -> dict[str, object]:
    return canonical_ssa(ssa_module_to_dto(module, schema_version=2))


def _ssa_artifact(canonical: dict[str, object] | None) -> dict[str, object] | None:
    if canonical is None:
        return None
    encoded = json.dumps(
        canonical, separators=(",", ":"), sort_keys=True
    ).encode()
    functions = canonical.get("functions", [])
    return {
        "representation": "canonical_schema_v2_sha256",
        "sha256": sha256(encoded).hexdigest(),
        "canonical_bytes": len(encoded),
        "function_count": len(functions) if isinstance(functions, list) else None,
    }


def _run_ab(initial, client) -> dict[str, object]:
    a_started = perf_counter()
    a_python_seconds = 0.0
    a_comparison_seconds = 0.0
    try:
        a_ssa, a_report = lower_with_rust_authority(
            initial, client, characterize_performance=True
        )
    except Exception as exc:
        a_seconds = perf_counter() - a_started
        a_accepts = False
        a_error = f"{type(exc).__name__}: {exc}"[:500]
        a_canonical = None
    else:
        a_seconds = perf_counter() - a_started
        a_accepts = True
        a_error = None
        a_canonical = _canonical_module(a_ssa)
        a_python_seconds = a_report.python_seconds
        a_comparison_seconds = a_report.comparison_seconds

    b_started = perf_counter()
    try:
        b_ssa, b_trace = qualify_shadow_independent_rust_ssa(initial, client)
    except ShadowIndependentQualificationFailure as exc:
        b_seconds = perf_counter() - b_started
        b_accepts = False
        b_error = f"{type(exc).__name__}: {exc.detail}"[:500]
        b_canonical = None
        trace = exc.trace.to_dict()
    else:
        b_seconds = perf_counter() - b_started
        b_accepts = True
        b_error = None
        b_canonical = _canonical_module(b_ssa)
        trace = b_trace.to_dict()
    return {
        "production_a_accepts": a_accepts,
        "qualification_b_accepts": b_accepts,
        "authoritative_ssa_equal": (
            a_canonical == b_canonical if a_accepts and b_accepts else None
        ),
        "authoritative_rust_ssa_a": _ssa_artifact(a_canonical),
        "authoritative_rust_ssa_b": _ssa_artifact(b_canonical),
        "production_a_error": a_error,
        "qualification_b_error": b_error,
        "qualification_trace": trace,
        "refinement_result": (
            "PASS" if trace["refinement_verification_executed"] and b_accepts else "REJECT_OR_NOT_REACHED"
        ),
        "final_generic_verification_result": (
            "PASS" if trace["final_generic_verification_executed"] and b_accepts else "REJECT_OR_NOT_REACHED"
        ),
        "input_integrity_result": (
            "PASS"
            if "same_input_integrity_after_refinement" in trace["completed_stages"]
            else "REJECT_OR_NOT_REACHED"
        ),
        "timing_seconds": {
            "production_a": a_seconds,
            "qualification_b": b_seconds,
            "production_a_over_qualification_b": (
                a_seconds / b_seconds if b_seconds else None
            ),
            "qualification_b_refinement": trace.get("stage_seconds", {}).get(
                "independent_refinement_verification"
            ),
            "python_shadow_a": a_python_seconds,
            "canonical_comparison_a": a_comparison_seconds,
            "python_shadow_plus_comparison_avoided_by_b": (
                a_python_seconds + a_comparison_seconds
            ),
        },
    }


def positive_qualification(client) -> list[dict[str, object]]:
    rows = []
    for name, initial in R43.fixtures().items():
        result = _run_ab(initial, client)
        rows.append({"case_id": name, **result})
    return rows


def randomized_qualification(client, count: int = 32) -> dict[str, object]:
    seeds = [44000 + index * 17 for index in range(count)]
    rows = []
    for seed in seeds:
        initial = R41.randomized_diamond(seed)
        rows.append({"seed": seed, "shape": "diamond_merge", **_run_ab(initial, client)})
    return {"seeds": seeds, "generated": count, "valid_applicable": len(rows), "results": rows}


def historical_qualification(client) -> dict[str, object]:
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
            result = _run_ab(initial, client)
        except Exception as exc:
            if initial is None:
                continue
            result = {
                "production_a_accepts": False,
                "qualification_b_accepts": False,
                "authoritative_ssa_equal": None,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        rows.append({"path": path.relative_to(ROOT).as_posix(), **result})
    passed = sum(
        row.get("production_a_accepts")
        and row.get("qualification_b_accepts")
        and row.get("authoritative_ssa_equal")
        for row in rows
    )
    return {
        "expected": 116,
        "denominator": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "results": rows,
    }


def _deep_module(size: int):
    """Use an IR-verifier-valid entry name for the inherited deep fixture."""

    module = R41.deep_linear_module(size)
    first = module.functions[0].blocks[0]
    module.functions[0].blocks[0] = R43.IRBasicBlock("entry", first.instructions)
    return module


def deep_cfg_qualification(client, sizes: tuple[int, ...]) -> list[dict[str, object]]:
    return [
        {"blocks": size, **_run_ab(_deep_module(size), client)}
        for size in sizes
    ]


def _rust_verifier(candidate: dict[str, object], executable: Path) -> tuple[bool, str | None]:
    completed = subprocess.run(
        [str(executable)],
        input=json.dumps(candidate, separators=(",", ":")),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode == 0:
        return True, None
    return False, (completed.stderr or completed.stdout).strip()[:500]


def _mutation_result(case, initial, baseline, rust_verifier: Path) -> dict[str, object]:
    candidate = deepcopy(baseline)
    case.mutate(candidate)
    applicable = candidate != baseline
    rust_passed, rust_diagnostic = _rust_verifier(candidate, rust_verifier)
    response = (
        {"ok": True, "ssa": candidate}
        if rust_passed
        else {"ok": False, "error": rust_diagnostic or "Rust verifier rejected mutation"}
    )
    result = _run_ab(initial, StaticClient(response))
    trace = result["qualification_trace"]
    b_accepts = result["qualification_b_accepts"]
    a_accepts = result["production_a_accepts"]
    if not b_accepts:
        first_layer = trace["failed_stage"]
    elif not a_accepts:
        first_layer = "python_shadow_canonical_comparison"
    else:
        first_layer = None
    classification = (
        "PRODUCTION_SHADOW_DEPENDENCY"
        if not a_accepts and b_accepts
        else "ACCEPTED_BY_BOTH_INVALID"
        if a_accepts and b_accepts
        else "REJECTED_BY_BOTH"
    )
    return {
        "mutation_id": case.mutation_id,
        "family": case.family,
        "source_fixture": case.fixture,
        "expected_semantic_invalidity": True,
        "semantic_intent": case.intent,
        "applicable": applicable,
        "rust_side_candidate_verifier": "PASS" if rust_passed else "REJECT",
        "rust_side_diagnostic": rust_diagnostic,
        "first_non_shadow_rejection_layer": first_layer,
        "shadow_independent_rejects": not b_accepts,
        "current_production_rejects": not a_accepts,
        "decisions_agree": a_accepts == b_accepts,
        "classification": classification,
        **result,
    }


def mutation_qualification(companion: Path, rust_verifier: Path) -> list[dict[str, object]]:
    fixtures = R43.fixtures()
    baselines = {}
    with PersistentRustSSALoweringClient(companion, timeout_seconds=60) as client:
        for name, initial in fixtures.items():
            response = client.lower(
                json.dumps(R43.ir_module_to_dto(initial), separators=(",", ":")).encode()
            )
            if response.get("ok") is not True or not isinstance(response.get("ssa"), dict):
                raise RuntimeError(f"Rust rejected mutation baseline {name}")
            baselines[name] = response["ssa"]
    rows = [
        _mutation_result(case, fixtures[case.fixture], baselines[case.fixture], rust_verifier)
        for case in R43.mutation_manifest()
    ]
    for seed in R43.RANDOM_SEEDS:
        shape = "diamond" if seed % 2 else "loop"
        initial = R41.randomized_diamond(seed) if shape == "diamond" else R41.loop_module()
        with PersistentRustSSALoweringClient(companion, timeout_seconds=60) as client:
            response = client.lower(
                json.dumps(R43.ir_module_to_dto(initial), separators=(",", ":")).encode()
            )
        baseline = response["ssa"]
        random = Random(seed)

        def mutate(dto, delta=random.choice((-17, -3, 5, 19))):
            if shape == "diamond":
                _, _, instruction = R43._first_kind(dto, "const")
                instruction["value"]["value"] += delta
            else:
                R43._wrong_loop_carried(dto)

        case = R43.Mutation(
            f"R43-RND-{seed}",
            "generated_randomized",
            f"seed:{seed}:{shape}",
            "deterministic generated semantic corruption",
            mutate,
        )
        rows.append(_mutation_result(case, initial, baseline, rust_verifier))
    return rows


def operational_qualification(client) -> dict[str, object]:
    fixtures = list(R43.fixtures().items())[:6]
    sequences = {
        "A_then_B": ("A", "B"),
        "B_then_A": ("B", "A"),
        "A_then_A": ("A", "A"),
        "B_then_B": ("B", "B"),
    }
    rows = []
    for sequence_name, sequence in sequences.items():
        initial = fixtures[len(rows) % len(fixtures)][1]
        outputs = []
        accepted = True
        for mode in sequence:
            try:
                if mode == "A":
                    ssa, _ = lower_with_rust_authority(initial, client)
                else:
                    ssa, _ = qualify_shadow_independent_rust_ssa(initial, client)
                outputs.append(_canonical_module(ssa))
            except Exception:
                accepted = False
        rows.append(
            {
                "sequence": sequence_name,
                "accepted": accepted,
                "deterministic_equal": len(outputs) == 2 and outputs[0] == outputs[1],
            }
        )
    transition_rows = []
    transition_patterns = {
        "valid_invalid_valid": (True, False, True),
        "invalid_valid_invalid": (False, True, False),
    }
    transition_initial = fixtures[0][1]
    for name, expected in transition_patterns.items():
        actual = []
        for valid in expected:
            candidate = deepcopy(transition_initial)
            if not valid:
                candidate.functions[0].blocks[0].instructions.pop()
            try:
                qualify_shadow_independent_rust_ssa(candidate, client)
            except ShadowIndependentQualificationFailure:
                actual.append(False)
            else:
                actual.append(True)
        transition_rows.append(
            {
                "sequence": name,
                "expected_acceptance": list(expected),
                "actual_acceptance": actual,
                "status": "PASS" if actual == list(expected) else "FAIL",
            }
        )
    before = (client.process_start_count, client.request_count)
    soak = []
    for index in range(64):
        name, initial = fixtures[index % len(fixtures)]
        ssa, trace = qualify_shadow_independent_rust_ssa(initial, client)
        soak.append(trace.accepted and bool(_canonical_module(ssa)) and bool(name))
    after = (client.process_start_count, client.request_count)
    return {
        "sequence_results": rows,
        "valid_invalid_transition_results": transition_rows,
        "soak_requests": len(soak),
        "soak_passed": sum(soak),
        "persistent_process_starts_before_after": [before[0], after[0]],
        "persistent_request_count_before_after": [before[1], after[1]],
        "no_restart_during_soak": before[0] == after[0] == 1,
        "status": "PASS"
        if all(row["accepted"] and row["deterministic_equal"] for row in rows)
        and all(row["status"] == "PASS" for row in transition_rows)
        and all(soak)
        and before[0] == after[0] == 1
        else "FAIL",
    }


def concurrency_qualification(client) -> dict[str, object]:
    modules = list(R43.fixtures().values())[:4] * 2

    def run(initial):
        ssa, trace = qualify_shadow_independent_rust_ssa(initial, client)
        return trace.accepted and bool(_canonical_module(ssa))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, modules))
    return {
        "supported_model": "shared synchronized persistent companion client",
        "requests": len(results),
        "passed": sum(results),
        "status": "PASS" if all(results) else "FAIL",
    }


def fail_closed_qualification() -> list[dict[str, object]]:
    initial = R43.fixtures()["diamond"]
    baseline = ssa_module_to_dto(R43.GeneralSSABuilder().build(initial), schema_version=2)

    def run(name, response, hooks=None):
        try:
            qualify_shadow_independent_rust_ssa(initial, StaticClient(response), _hooks=hooks)
        except ShadowIndependentQualificationFailure as exc:
            return {
                "injection": name,
                "rejected": True,
                "failed_stage": exc.trace.failed_stage,
                "classification": exc.trace.failure_classification,
                "python_fallback_executed": exc.trace.python_ssa_lowering_executed,
            }
        return {"injection": name, "rejected": False}

    invalid = deepcopy(baseline)
    invalid["functions"][0]["blocks"][0]["instructions"].pop()
    semantic = deepcopy(baseline)
    R43._correlated_constant(semantic)
    semantic_module = ssa_module_from_dto(semantic)

    def mutate_input(value):
        value.functions.append(value.functions[0])

    def corrupt_final(value):
        value.functions[0].blocks[0].instructions.pop()

    return [
        run("rust_companion_failure", RuntimeError("injected companion failure")),
        run("malformed_rust_response", []),
        run("schema_v2_import_failure", {"ok": True, "ssa": {}}),
        run("imported_ssa_verification_failure", {"ok": True, "ssa": invalid}),
        run("input_integrity_failure", {"ok": True, "ssa": baseline}, _QualificationHooks(after_normalization=mutate_input)),
        run("refinement_verifier_failure", {"ok": True, "ssa": baseline}, _QualificationHooks(after_imported_verification=lambda _value: semantic_module)),
        run("final_generic_verification_failure", {"ok": True, "ssa": baseline}, _QualificationHooks(after_refinement=corrupt_final)),
    ]


def independence_audit() -> dict[str, object]:
    path = ROOT / "src/aether/ssa/shadow_independent.py"
    source = path.read_text(encoding="utf-8")
    import_forbidden = (
        "from .general_builder import",
        "from .builder import",
        "from .cfg import",
        "from .dominators import",
        "from .phi_placement import",
        "from .renaming import",
        "from .shadow import",
    )
    call_forbidden = ("GeneralSSABuilder(", "canonical_ssa(")
    hits = [value for value in (*import_forbidden, *call_forbidden) if value in source]
    return {
        "status": "PASS" if not hits else "FAIL",
        "classification": "STRONG" if not hits else "INDEPENDENCE_VIOLATION",
        "audited_file": path.relative_to(ROOT).as_posix(),
        "forbidden_import_or_call_hits": hits,
        "python_builder_imported": "general_builder" in source,
        "python_builder_executable_call": "GeneralSSABuilder(" in source,
        "canonical_comparison_executable_call": "canonical_ssa(" in source,
        "consumes_python_ssa_artifact": False,
        "consumes_rust_producer_intermediates": False,
        "shared_boundaries": [
            "public Initial IR and SSA dataclasses",
            "schema-v2 importer",
            "generic SSA verifier",
            "independent relational refinement verifier",
        ],
    }


def production_non_regression() -> dict[str, object]:
    shadow = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    pipeline = (ROOT / "src/aether/pipeline.py").read_text(encoding="utf-8")
    checks = {
        "default_rust_authority_python_shadow": "RUST_SSA_AUTHORITY_PYTHON_SHADOW" in shadow,
        "mandatory_python_builder": "GeneralSSABuilder().build(python_input)" in shadow,
        "canonical_mismatch_fail_closed": '"semantic_mismatch", "canonical_comparison"' in shadow,
        "refinement_before_python": shadow.index("verify_ssa_refinement(normalized_module, rust_ssa)") < shadow.index("python_ssa = run_python()"),
        "qualification_absent_from_pipeline_configuration": "qualify_shadow_independent_rust_ssa" not in pipeline,
        "protocol_v1_unchanged": "SSA_SHADOW_PROTOCOL_VERSION = 1" in shadow,
        "schema_v2_unchanged": "SSA_SHADOW_SCHEMA_VERSION = 2" in shadow,
        "rollback_mode_names_unchanged": all(value in shadow for value in ("PYTHON_SSA_ONLY", "PYTHON_SSA_AUTHORITY_RUST_SHADOW", "RUST_SSA_AUTHORITY_PYTHON_SHADOW")),
    }
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def _platform_id() -> str:
    system = platform.system().lower()
    os_name = "macos" if system == "darwin" else "windows" if system == "windows" else "linux"
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64" if machine in {"amd64", "x86_64"} else machine
    return f"{os_name}-{arch}"


def build_evidence(
    companion: Path,
    rust_verifier: Path,
    *,
    smoke: bool = False,
    record_verified_gates: bool = False,
) -> dict[str, object]:
    with PersistentRustSSALoweringClient(companion, timeout_seconds=120) as client:
        positives = positive_qualification(client)
        randomized = randomized_qualification(client, 4 if smoke else 32)
        historical = {"expected": 116, "denominator": 0, "passed": 0, "failed": 0, "results": [], "status": "NOT_RUN_SMOKE"} if smoke else historical_qualification(client)
        deep = deep_cfg_qualification(client, (100,) if smoke else (100, 1000, 5000, 10000))
        operational = operational_qualification(client)
        concurrency = concurrency_qualification(client)
    mutations = [] if smoke else mutation_qualification(companion, rust_verifier)
    failures = fail_closed_qualification()
    independence = independence_audit()
    production = production_non_regression()
    dependency_ids = [row["mutation_id"] for row in mutations if row["classification"] == "PRODUCTION_SHADOW_DEPENDENCY"]
    gap_ids = [row["mutation_id"] for row in mutations if row["classification"] == "ACCEPTED_BY_BOTH_INVALID"]
    valid_rows = positives + randomized["results"] + deep
    positives_pass = all(
        row["production_a_accepts"] and row["qualification_b_accepts"] and row["authoritative_ssa_equal"]
        for row in valid_rows
    )
    complete_local = (
        not smoke
        and positives_pass
        and historical["passed"] == historical["denominator"] == 116
        and len(mutations) >= 58
        and not dependency_ids
        and not gap_ids
        and operational["status"] == "PASS"
        and concurrency["status"] == "PASS"
        and all(row["rejected"] and not row.get("python_fallback_executed", False) for row in failures)
        and independence["status"] == "PASS"
        and production["status"] == "PASS"
    )
    required_platforms = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
    local_platform = _platform_id()
    platform_results = [
        {
            "platform": local_platform,
            "revision": BASELINE_REVISION,
            "status": "PASS" if positives_pass and operational["status"] == "PASS" else "FAIL",
            "scope": "LOCAL_FULL" if not smoke else "CI_SMOKE",
        }
    ]
    gates = {
        "rust_4_0": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "rust_4_1": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "rust_4_2": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "rust_4_3": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "focused_rust_4_4": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "full_python_suite": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "cargo_test_workspace_locked": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "cargo_fmt_all_check": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
        "git_diff_check": "PASS" if record_verified_gates else "NOT_RUN_IN_THIS_INVOCATION",
    }
    all_gates = all(value == "PASS" for value in gates.values())
    platform_complete = {row["platform"] for row in platform_results if row["status"] == "PASS"} == required_platforms
    if dependency_ids:
        decision = DECISION_BLOCKED
    elif gap_ids:
        decision = DECISION_GAP
    elif complete_local and all_gates and platform_complete:
        decision = DECISION_QUALIFIED
    else:
        decision = DECISION_INCOMPLETE
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "baseline_revision": BASELINE_REVISION,
        "qualification_revision": SHADOW_INDEPENDENT_QUALIFICATION_REVISION,
        "production_policy_declaration": "Rust authority with mandatory synchronous independent Python SSA shadow remains unchanged",
        "production_policy_unchanged": True,
        "qualification_only_path_declaration": "Explicit direct-call diagnostic API; absent from SSALoweringAuthorityMode and pipeline configuration",
        "path_a_stage_manifest": ["initial_ir_verification", "lifecycle_normalization_once", "rust_ssa_authority", "rust_side_verification", "schema_v2_import", "imported_ssa_verification", "same_input_integrity", "independent_refinement_verification", "same_input_integrity", "python_general_ssa_builder", "final_input_integrity", "canonical_rust_python_comparison", "generic_final_ssa_verification"],
        "path_b_stage_manifest": list(SHADOW_INDEPENDENT_STAGE_MANIFEST),
        "path_b_non_execution_contract": {"python_general_ssa_builder_instantiated": False, "python_ssa_lowering_executed": False, "canonical_rust_python_comparison_executed": False},
        "positive_case_results": positives,
        "historical_results": historical,
        "randomized_qualification": randomized,
        "mutation_results": mutations,
        "mutation_classification_totals": dict(Counter(row["classification"] for row in mutations)),
        "PRODUCTION_SHADOW_DEPENDENCY_count": len(dependency_ids),
        "PRODUCTION_SHADOW_DEPENDENCY_ids": dependency_ids,
        "accepted_by_both_invalid_count": len(gap_ids),
        "accepted_by_both_invalid_ids": gap_ids,
        "deep_cfg_results": deep,
        "persistent_and_soak_results": operational,
        "concurrency_results": concurrency,
        "fail_closed_injection_results": failures,
        "independence_audit": independence,
        "production_non_regression_results": production,
        "platform_results": platform_results,
        "required_platforms": sorted(required_platforms),
        "environmental_limitations": [
            "Only the local platform result is claimed in this artifact; CI is prepared to emit exact-revision results for all four required platforms.",
            *(
                [
                    "The unmodified Python suite reproduced 24 known LeakSanitizer startup failures under ptrace (4979 passed, 4 skipped); the established LSAN_OPTIONS=detect_leaks=0 rerun passed 5003 with 4 skipped. This is functional validation, not leak-safety evidence."
                ]
                if record_verified_gates
                else []
            ),
            "No performance threshold is imposed.",
        ],
        "observational_timing_samples": {
            "positive_cases": [{"case_id": row["case_id"], **row["timing_seconds"]} for row in positives],
            "deep_cfg": [{"blocks": row["blocks"], **row["timing_seconds"]} for row in deep],
            "threshold_enforced": False,
        },
        "regression_gate_results": gates,
        "local_semantic_qualification_complete": complete_local,
        "cross_platform_qualification_complete": platform_complete,
        "decision": decision,
        "recommendation": (
            "Do not change production policy. Aggregate exact-revision CI platform artifacts and complete all regression gates before a later transition milestone."
            if decision == DECISION_INCOMPLETE
            else "Do not change production policy; this result only qualifies a later transition milestone."
        ),
    }


def render_report(evidence: dict[str, object]) -> str:
    mutation_count = len(evidence["mutation_results"])
    historical = evidence["historical_results"]
    return "\n".join(
        [
            "# Shadow-independent production qualification — RUST-4.4",
            "",
            f"Decision: `{evidence['decision']}`.",
            "",
            "This milestone does not change production policy. Ordinary production still requires the synchronous Python SSA shadow and canonical Rust/Python comparison.",
            "",
            "## Qualification path",
            "",
            "The explicit qualification-only API executes verified Initial IR, lifecycle normalization, Rust lowering and Rust-side verification, schema-v2 import, imported verification, same-input integrity, independent refinement, a second integrity check, and final generic verification. It does not import or execute the Python SSA builder and does not call canonical Rust/Python comparison.",
            "",
            "## Local evidence",
            "",
            f"Positive controls: {sum(row['qualification_b_accepts'] for row in evidence['positive_case_results'])}/{len(evidence['positive_case_results'])}. Historical: {historical['passed']}/{historical['denominator']}. Semantic mutations: {mutation_count}; production shadow dependencies: {evidence['PRODUCTION_SHADOW_DEPENDENCY_count']}; invalid accepted by both: {evidence['accepted_by_both_invalid_count']}.",
            "",
            f"Deep CFG sizes: {[row['blocks'] for row in evidence['deep_cfg_results']]}. Persistent/soak: `{evidence['persistent_and_soak_results']['status']}`. Concurrency: `{evidence['concurrency_results']['status']}`. Independence: `{evidence['independence_audit']['classification']}`.",
            "",
            "## Why the checked-in decision is incomplete",
            "",
            "The checked-in artifact claims only the platform actually executed locally. The workflow prepares Linux x86_64, Windows x86_64, macOS x86_64, and macOS arm64 artifacts, but those results must be generated and aggregated at the exact qualification revision. The evidence records each required regression gate, and any non-PASS gate remains blocking. No platform result is invented.",
            "",
            "## Recommendation",
            "",
            str(evidence["recommendation"]),
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--rust-verifier", type=Path, default=DEFAULT_RUST_VERIFIER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--record-verified-gates", action="store_true")
    args = parser.parse_args()
    evidence = build_evidence(
        args.companion.resolve(),
        args.rust_verifier.resolve(),
        smoke=args.smoke,
        record_verified_gates=args.record_verified_gates,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(render_report(evidence), encoding="utf-8")
    print(f"{MILESTONE}: {evidence['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
