#!/usr/bin/env python3
"""Project checked CORE-1.0A production evidence into CORE-PKG-1 evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib
import json
from pathlib import Path
import re


UPSTREAM_DECISION = "CORE_IN_PROCESS_PRODUCTION_GUARD_QUALIFIED"
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


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: evidence must be an object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def installed_binding_assertions() -> dict[str, object]:
    compatibility = importlib.import_module("_aether_core")
    native = importlib.import_module("aether_compiler_core._aether_core")
    package = importlib.import_module("aether_compiler_core")
    metadata = package.version_metadata()
    _require(getattr(compatibility, "QUALIFICATION_ONLY", None) is False, "installed compatibility binding is qualification-only")
    _require(getattr(native, "QUALIFICATION_ONLY", None) is False, "installed private binding is qualification-only")
    _require(metadata.get("protocol_version") == 1, "installed binding protocol is not v1")
    _require(package.CompilerCore() is not None, "installed CompilerCore could not be constructed")
    return {
        "compatibility_import": "_aether_core",
        "private_import": "aether_compiler_core._aether_core",
        "qualification_only": False,
        "protocol_version": 1,
        "compiler_core_constructed": True,
    }


def project(
    upstream_path: Path,
    check_path: Path,
    *,
    revision: str,
    ci_run_id: str,
    installed_binding: dict[str, object],
) -> dict[str, object]:
    upstream = _load(upstream_path)
    checked = _load(check_path)
    upstream_hash = sha256(upstream_path.read_bytes()).hexdigest()
    check_hash = sha256(check_path.read_bytes()).hexdigest()

    _require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "revision must be an exact lowercase Git SHA")
    _require(bool(ci_run_id), "CI run ID is required")
    _require(upstream.get("kind") == "core_1_0a_production", "upstream evidence kind changed")
    _require(upstream.get("milestone") == "CORE-1.0A", "upstream evidence milestone changed")
    _require(upstream.get("status") == "PASS", "upstream production evidence did not pass")
    _require(upstream.get("qualification_only") is True, "upstream CORE-1.0A identity is not qualification-only")
    _require(upstream.get("exact_revision") == revision, "upstream evidence revision does not match this run")
    _require(str(upstream.get("ci_run_id")) == ci_run_id, "upstream evidence CI run ID does not match this run")
    _require(upstream.get("worktree_clean") is True, "upstream evidence worktree was not clean")
    _require(upstream.get("production_default_changed") is False, "production default changed")
    _require(upstream.get("companion_remains_production_and_rollback") is True, "companion is no longer production and rollback")
    _require(upstream.get("automatic_fallback") is False, "automatic fallback appeared")
    gates = upstream.get("production_regression_gates")
    guards = upstream.get("shared_core_guards")
    _require(isinstance(gates, dict) and set(gates) == PRODUCTION_REGRESSION_GATES and all(gates.get(name) is True for name in PRODUCTION_REGRESSION_GATES), "upstream production regression gates are incomplete or failed")
    _require(isinstance(guards, dict) and set(guards) == SHARED_CORE_GUARDS and all(guards.get(name) is True for name in SHARED_CORE_GUARDS), "upstream shared-core guards are incomplete or failed")

    source = checked.get("source_evidence")
    _require(checked.get("kind") == "core_1_0a_production_check", "wrong upstream checker artifact kind")
    _require(checked.get("milestone") == "CORE-1.0A", "wrong upstream checker milestone")
    _require(checked.get("decision") == UPSTREAM_DECISION, "CORE-1.0A production checker did not qualify the evidence")
    _require(checked.get("errors") == [], "CORE-1.0A production checker reported errors")
    _require(checked.get("exact_revision") == revision, "checker revision does not match this run")
    _require(str(checked.get("ci_run_id")) == ci_run_id, "checker CI run ID does not match this run")
    _require(isinstance(source, dict) and source.get("sha256") == upstream_hash, "checker did not validate the exact upstream artifact")

    _require(installed_binding.get("qualification_only") is False, "installed binding remained qualification-only")
    _require(installed_binding.get("protocol_version") == 1, "installed binding protocol is not v1")
    _require(installed_binding.get("compiler_core_constructed") is True, "installed CompilerCore was not constructed")

    return {
        "artifact_schema_version": 1,
        "kind": "core_pkg_1_binding_smoke",
        "milestone": "CORE-PKG-1",
        "status": "PASS",
        "exact_revision": revision,
        "ci_run_id": ci_run_id,
        "installed_binding": installed_binding,
        "production_default_changed": False,
        "companion_remains_production_and_rollback": True,
        "automatic_fallback": False,
        "production_regression_gates": {name: gates[name] for name in sorted(PRODUCTION_REGRESSION_GATES)},
        "shared_core_guards": {name: guards[name] for name in sorted(SHARED_CORE_GUARDS)},
        "upstream_evidence": {
            "path": upstream_path.name,
            "artifact_schema_version": upstream.get("artifact_schema_version"),
            "kind": upstream.get("kind"),
            "milestone": upstream.get("milestone"),
            "status": upstream.get("status"),
            "qualification_only": upstream.get("qualification_only"),
            "exact_revision": upstream.get("exact_revision"),
            "ci_run_id": upstream.get("ci_run_id"),
            "worktree_clean": upstream.get("worktree_clean"),
            "sha256": upstream_hash,
        },
        "upstream_checker": {
            "path": check_path.name,
            "sha256": check_hash,
            "kind": checked.get("kind"),
            "milestone": checked.get("milestone"),
            "decision": checked.get("decision"),
            "exact_revision": checked.get("exact_revision"),
            "ci_run_id": checked.get("ci_run_id"),
            "source_evidence_sha256": source.get("sha256") if isinstance(source, dict) else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-evidence", type=Path, required=True)
    parser.add_argument("--upstream-check", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ci-run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = project(
        args.upstream_evidence,
        args.upstream_check,
        revision=args.revision,
        ci_run_id=args.ci_run_id,
        installed_binding=installed_binding_assertions(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("CORE-PKG-1 binding production guard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
