#!/usr/bin/env python3
"""Fail-closed aggregate checker for CORE-1.0A evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re


QUALIFIED = "CORE_IN_PROCESS_BOUNDARY_QUALIFIED"
BLOCKED = "CORE_IN_PROCESS_BOUNDARY_QUALIFICATION_BLOCKED"
PRODUCTION_GUARD_QUALIFIED = "CORE_IN_PROCESS_PRODUCTION_GUARD_QUALIFIED"
PRODUCTION_GUARD_BLOCKED = "CORE_IN_PROCESS_PRODUCTION_GUARD_BLOCKED"
PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
PYTHON_MINORS = {"3.11", "3.12", "3.13", "3.14"}
PRODUCTION_REGRESSION_GATES = {
    "differential_python_shadow",
    "lifecycle",
    "persistent_companion",
    "protocol_v1",
    "rollback_modes",
    "rust_4_5_default_policy",
    "rust_ssa_output",
    "structured_failure_and_locations",
    "verification_and_refinement",
}
SHARED_CORE_GUARDS = {
    "companion_calls_compiler_core",
    "core_not_coupled_to_pyo3",
    "in_process_not_in_default_selector",
    "pyo3_calls_compiler_core",
}
INITIAL_FAILURE_CATEGORIES = {
    "malformed Initial IR",
    "invalid CFG",
    "wrong return/value flow",
    "lifecycle errors",
    "malformed protocol/binding inputs",
}
DOWNSTREAM_FAILURE_CATEGORIES = {
    "invalid phi",
    "refinement failures",
    "imported SSA failures",
}


def _load(path: Path, errors: list[str]) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except Exception as error:
        errors.append(f"{path}: invalid JSON: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path}: evidence must be an object")
        return None
    return value


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _one(kind: str, artifacts: list[tuple[Path, dict[str, object]]], errors: list[str]) -> tuple[Path, dict[str, object]] | None:
    selected = [item for item in artifacts if item[1].get("kind") == kind]
    _require(len(selected) == 1, f"expected exactly one {kind} artifact, found {len(selected)}", errors)
    return selected[0] if len(selected) == 1 else None


def _all_true(value: object) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def check_production(evidence_path: Path) -> tuple[dict[str, object], list[str]]:
    """Validate one CORE-1.0A production-preservation artifact only.

    This deliberately does not claim closure of the semantic, session, packaging,
    platform, or Python lanes required by the full CORE-1.0A checker.
    """

    errors: list[str] = []
    production = _load(evidence_path, errors)
    if production is None:
        production = {}

    _require(production.get("artifact_schema_version") == 1, "production evidence schema is not version 1", errors)
    _require(production.get("kind") == "core_1_0a_production", "production evidence kind is not core_1_0a_production", errors)
    _require(production.get("milestone") == "CORE-1.0A", "production evidence milestone is not CORE-1.0A", errors)
    _require(production.get("status") == "PASS", "production preservation lane did not pass", errors)
    revision = str(production.get("exact_revision", ""))
    run_id = str(production.get("ci_run_id", ""))
    _require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "production evidence must identify one exact revision", errors)
    _require(run_id not in {"", "None"}, "production evidence must identify its local or CI run", errors)
    _require(production.get("worktree_clean") is True, "production evidence must come from a clean exact revision", errors)
    _require(production.get("qualification_only") is True, "CORE-1.0A evidence must retain qualification-only identity", errors)
    _require(production.get("production_default_changed") is False, "production default changed", errors)
    _require(production.get("companion_remains_production_and_rollback") is True, "companion is no longer production and rollback", errors)
    _require(production.get("automatic_fallback") is False, "automatic fallback appeared", errors)

    gates = production.get("production_regression_gates")
    _require(
        isinstance(gates, dict)
        and set(gates) == PRODUCTION_REGRESSION_GATES
        and all(gates.get(name) is True for name in PRODUCTION_REGRESSION_GATES),
        "one or more affected RUST-4.5 production gates failed",
        errors,
    )
    guards = production.get("shared_core_guards")
    _require(
        isinstance(guards, dict)
        and set(guards) == SHARED_CORE_GUARDS
        and all(guards.get(name) is True for name in SHARED_CORE_GUARDS),
        "shared CompilerCore adapter guard failed",
        errors,
    )
    default = production.get("default_companion")
    _require(
        isinstance(default, dict)
        and default.get("identity_and_protocol_v1") == "PASS"
        and default.get("response_shape_preserved") is True
        and default.get("persistent_process_starts") == 1
        and default.get("repeated_result_equal") is True,
        "protocol-v1/persistent companion behavior changed",
        errors,
    )

    decision = PRODUCTION_GUARD_QUALIFIED if not errors else PRODUCTION_GUARD_BLOCKED
    report = {
        "artifact_schema_version": 1,
        "kind": "core_1_0a_production_check",
        "milestone": "CORE-1.0A",
        "decision": decision,
        "exact_revision": production.get("exact_revision"),
        "ci_run_id": production.get("ci_run_id"),
        "source_evidence": {
            "path": evidence_path.name,
            "sha256": sha256(evidence_path.read_bytes()).hexdigest() if evidence_path.is_file() else None,
            "kind": production.get("kind"),
            "milestone": production.get("milestone"),
        },
        "production_default_changed": production.get("production_default_changed"),
        "companion_remains_production_and_rollback": production.get("companion_remains_production_and_rollback"),
        "automatic_fallback": production.get("automatic_fallback"),
        "errors": errors,
    }
    return report, errors


def check(evidence_dir: Path) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    artifacts: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(evidence_dir.rglob("*.json")):
        value = _load(path, errors)
        if value is not None and str(value.get("kind", "")).startswith("core_1_0a_"):
            artifacts.append((path, value))

    semantic_item = _one("core_1_0a_semantic", artifacts, errors)
    production_item = _one("core_1_0a_production", artifacts, errors)
    sessions_item = _one("core_1_0a_sessions", artifacts, errors)
    packaging = [item for item in artifacts if item[1].get("kind") == "core_1_0a_packaging"]
    revisions = {str(value.get("exact_revision")) for _, value in artifacts}
    run_ids = {str(value.get("ci_run_id")) for _, value in artifacts}
    _require(len(revisions) == 1 and next(iter(revisions), "") != "None", "all evidence must identify one exact revision", errors)
    _require(len(run_ids) == 1 and next(iter(run_ids), "") not in {"None", "LOCAL_PRE_CI"}, "all qualifying evidence must come from one non-local CI run", errors)
    _require(bool(artifacts) and all(value.get("worktree_clean") is True for _, value in artifacts), "all qualifying evidence must come from a clean exact revision", errors)

    if semantic_item is not None:
        _, semantic = semantic_item
        _require(semantic.get("status") == "PASS", "semantic lane did not pass", errors)
        historical = semantic.get("historical")
        _require(isinstance(historical, dict) and historical.get("passed") == 116 and historical.get("denominator") == 116 and historical.get("status") == "PASS", "historical transport parity must be 116/116", errors)
        deep = semantic.get("deep_cfg")
        deep_rows = deep if isinstance(deep, list) else []
        _require({int(str(row.get("case_id", "")).removeprefix("deep_cfg_")) for row in deep_rows if isinstance(row, dict) and str(row.get("case_id", "")).removeprefix("deep_cfg_").isdigit()} == {993, 1000, 5000, 10000} and all(row.get("passed") is True for row in deep_rows), "deep CFG 993/1000/5000/10000 parity is mandatory", errors)
        failures = semantic.get("failure_campaign")
        failure_rows = failures if isinstance(failures, list) else []
        _require(INITIAL_FAILURE_CATEGORIES <= {str(row.get("campaign_category")) for row in failure_rows if isinstance(row, dict)}, "Initial IR failure campaign categories are incomplete", errors)
        _require(
            bool(failure_rows)
            and all(
                row.get("passed") is True
                and (
                    row.get("machine_diagnostic_parity") is True
                    and row.get("source_location_parity") is True
                    if row.get("companion_accepts") is False
                    else row.get("verification_outcome_parity") is True
                    and row.get("refinement_outcome_parity") is True
                    and row.get("source_locations_equal") is True
                )
                for row in failure_rows
            ),
            "Initial IR failure/diagnostic/location parity failed",
            errors,
        )
        downstream = semantic.get("imported_ssa_and_refinement_campaign")
        downstream_rows = downstream if isinstance(downstream, list) else []
        _require(DOWNSTREAM_FAILURE_CATEGORIES <= {str(row.get("category")) for row in downstream_rows if isinstance(row, dict)}, "imported SSA/refinement mutation categories are incomplete", errors)
        _require(bool(downstream_rows) and all(row.get("passed") is True and row.get("divergence") is None for row in downstream_rows), "imported SSA/refinement outcomes diverged", errors)
        ordinary = semantic.get("ordinary")
        ordinary_rows = ordinary if isinstance(ordinary, list) else []
        _require(bool(ordinary_rows) and all(row.get("passed") is True and row.get("verification_outcome_parity") is True and row.get("refinement_outcome_parity") is True for row in ordinary_rows), "ordinary semantic/verification/refinement parity failed", errors)
        performance = semantic.get("performance")
        _require(isinstance(performance, dict) and performance.get("correction_gate") is False and set((performance.get("workloads") or {})) == {"ordinary", "historical_batch", "deep_cfg", "repository_real"}, "performance characterization is incomplete", errors)
        _require(
            isinstance(performance, dict)
            and isinstance(performance.get("workloads"), dict)
            and isinstance(performance["workloads"].get("historical_batch"), dict)
            and performance["workloads"]["historical_batch"].get("payload_count") == 116,
            "historical performance batch must contain all 116 qualified inputs",
            errors,
        )

    if production_item is not None:
        _, production = production_item
        _require(production.get("status") == "PASS", "production preservation lane did not pass", errors)
        _require(_all_true(production.get("production_regression_gates")), "one or more affected RUST-4.5 production gates failed", errors)
        _require(_all_true(production.get("shared_core_guards")), "shared CompilerCore adapter guard failed", errors)
        default = production.get("default_companion")
        _require(isinstance(default, dict) and default.get("response_shape_preserved") is True and default.get("persistent_process_starts") == 1, "protocol-v1/persistent companion behavior changed", errors)

    if sessions_item is not None:
        _, sessions = sessions_item
        _require(sessions.get("status") == "PASS", "session/concurrency lane did not pass", errors)
        _require(_all_true(sessions.get("session_and_handle_gates")), "session/handle/concurrency gate failed", errors)
        concurrency = sessions.get("concurrency")
        _require(isinstance(concurrency, dict) and isinstance(concurrency.get("gil_ticker_progress_during_rust"), int) and concurrency["gil_ticker_progress_during_rust"] > 0, "GIL release was not observed", errors)
        memory = sessions.get("memory")
        _require(isinstance(memory, dict) and memory.get("iterations", 0) >= 500 and memory.get("unbounded_growth_observed") is False, "500-iteration session memory soak is missing or failed", errors)
        traits = sessions.get("rust_traits")
        _require(isinstance(traits, dict) and traits.get("unsafe") is False and "Send + Sync" in str(traits.get("CompilerCore")) and "Send + Sync" in str(traits.get("CompilationSession")), "Send/Sync/unsafe contract is missing", errors)

    platform_rows = [value for _, value in packaging if value.get("matrix_role") == "platform"]
    compatibility_rows = [value for _, value in packaging if value.get("matrix_role") == "python_compatibility"]
    _require({str(row.get("platform")) for row in platform_rows} == PLATFORMS, "clean-install platform matrix is incomplete", errors)
    _require({".".join(str(row.get("python", {}).get("version", "")).split(".")[:2]) for row in compatibility_rows if isinstance(row.get("python"), dict)} == PYTHON_MINORS, "CPython 3.11-3.14 compatibility matrix is incomplete", errors)
    for row in platform_rows + compatibility_rows:
        wheel = row.get("wheel")
        clean = row.get("clean_environment")
        build = row.get("build_environment")
        candidates = row.get("wheel_candidates")
        python = row.get("python")
        _require(row.get("status") == "PASS" and row.get("companion_remains_usable") is True, f"packaging row failed: {row.get('platform')} {row.get('python')}", errors)
        _require(
            isinstance(wheel, dict)
            and wheel.get("distribution") == "aether-core-qualification"
            and re.fullmatch(r"[0-9a-f]{64}", str(wheel.get("sha256", ""))) is not None
            and bool(wheel.get("tag"))
            and bool(wheel.get("python_tags"))
            and bool(wheel.get("abi_tags"))
            and bool(wheel.get("platform_tags"))
            and bool(wheel.get("selected_reason")),
            "binding wheel identity, tags, selection reason, or hash missing",
            errors,
        )
        _require(
            isinstance(candidates, list)
            and sum(
                item.get("eligible") is True
                for item in candidates
                if isinstance(item, dict)
            )
            == 1,
            "wheel selection evidence must contain exactly one eligible candidate",
            errors,
        )
        _require(
            isinstance(python, dict) and bool(python.get("sys_version")),
            "packaging evidence must record sys.version",
            errors,
        )
        _require(
            isinstance(build, dict)
            and build.get("cargo_available") is True
            and build.get("rustc_available") is True
            and build.get("wheel_prebuilt") is True,
            "wheel build environment must explicitly provide Rust and Cargo",
            errors,
        )
        _require(
            isinstance(clean, dict)
            and clean.get("install_requires_rust") is False
            and clean.get("cargo_on_install_path") is False
            and clean.get("rustc_on_install_path") is False
            and clean.get("pip_only_binary") is True
            and clean.get("original_path_preserved") is True,
            "clean wheel consumer must preserve PATH and not expose Rust/Cargo",
            errors,
        )

    manifest = [
        {"path": path.relative_to(evidence_dir).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest(), "kind": value.get("kind")}
        for path, value in artifacts
    ]
    decision = QUALIFIED if not errors else BLOCKED
    aggregate = {
        "artifact_schema_version": 1,
        "kind": "core_1_0a_aggregate",
        "milestone": "CORE-1.0A",
        "decision": decision,
        "exact_revision": next(iter(revisions)) if len(revisions) == 1 else None,
        "ci_run_id": next(iter(run_ids)) if len(run_ids) == 1 else None,
        "required_platforms": sorted(PLATFORMS),
        "required_python_minors": sorted(PYTHON_MINORS),
        "production_default_changed": False,
        "in_process_is_production_default": False,
        "companion_remains_production_and_rollback": True,
        "trust_statement": "The in-process boundary is operationally qualified against the existing companion and qualified corpus on the tested platforms." if decision == QUALIFIED else "Qualification is blocked; no universal or operational correctness claim is made.",
        "errors": errors,
        "artifact_manifest": manifest,
    }
    return aggregate, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--evidence-dir", type=Path)
    source.add_argument("--production-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    if args.production_evidence is not None:
        aggregate, errors = check_production(args.production_evidence)
    else:
        aggregate, errors = check(args.evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n")
    print(aggregate["decision"])
    for error in errors:
        print(f"- {error}")
    return 1 if args.require_qualified and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
