#!/usr/bin/env python3
"""Fail-closed aggregate checker for CORE-PKG-1 CI evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re


PENDING = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_PENDING_CI"
QUALIFIED = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
BLOCKED = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED"
PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
PYTHONS = {"3.11", "3.12", "3.13", "3.14"}
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


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _binding_guard(
    binding: dict[str, object],
    *,
    evidence_dir: Path,
    ci_closure: bool,
    errors: list[str],
) -> tuple[str | None, str | None]:
    revision = str(binding.get("exact_revision", ""))
    run_id = str(binding.get("ci_run_id", ""))
    _require(binding.get("milestone") == "CORE-PKG-1", "binding evidence milestone is not CORE-PKG-1", errors)
    _require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "binding evidence exact revision is missing or invalid", errors)
    _require(bool(run_id) and (not ci_closure or run_id != "LOCAL_PRE_CI"), "binding evidence CI run provenance is missing or local", errors)
    _require(binding.get("production_default_changed") is False, "production default changed", errors)
    _require(binding.get("companion_remains_production_and_rollback") is True, "companion is no longer production and rollback", errors)
    _require(binding.get("automatic_fallback") is False, "automatic fallback appeared", errors)

    installed = binding.get("installed_binding")
    _require(
        isinstance(installed, dict)
        and installed.get("qualification_only") is False
        and installed.get("protocol_version") == 1
        and installed.get("compiler_core_constructed") is True,
        "installed productive binding smoke evidence failed",
        errors,
    )
    gates = binding.get("production_regression_gates")
    _require(
        isinstance(gates, dict)
        and set(gates) == PRODUCTION_REGRESSION_GATES
        and all(gates.get(name) is True for name in PRODUCTION_REGRESSION_GATES),
        "CORE-1.0A production regression evidence is incomplete or failed",
        errors,
    )
    guards = binding.get("shared_core_guards")
    _require(
        isinstance(guards, dict)
        and set(guards) == SHARED_CORE_GUARDS
        and all(guards.get(name) is True for name in SHARED_CORE_GUARDS),
        "shared CompilerCore adapter provenance is incomplete or failed",
        errors,
    )

    upstream = binding.get("upstream_evidence")
    _require(
        isinstance(upstream, dict)
        and upstream.get("artifact_schema_version") == 1
        and upstream.get("kind") == "core_1_0a_production"
        and upstream.get("milestone") == "CORE-1.0A"
        and upstream.get("status") == "PASS"
        and upstream.get("qualification_only") is True
        and upstream.get("worktree_clean") is True
        and upstream.get("exact_revision") == revision
        and str(upstream.get("ci_run_id")) == run_id
        and re.fullmatch(r"[0-9a-f]{64}", str(upstream.get("sha256", ""))) is not None,
        "required CORE-1.0A upstream provenance is missing or inconsistent",
        errors,
    )
    checked = binding.get("upstream_checker")
    upstream_hash = upstream.get("sha256") if isinstance(upstream, dict) else None
    _require(
        isinstance(checked, dict)
        and checked.get("kind") == "core_1_0a_production_check"
        and checked.get("milestone") == "CORE-1.0A"
        and checked.get("decision") == "CORE_IN_PROCESS_PRODUCTION_GUARD_QUALIFIED"
        and checked.get("exact_revision") == revision
        and str(checked.get("ci_run_id")) == run_id
        and checked.get("source_evidence_sha256") == upstream_hash,
        "CORE-1.0A checker provenance is missing or inconsistent",
        errors,
    )

    def provenance_file(record: object, label: str) -> tuple[Path | None, dict[str, object] | None]:
        if not isinstance(record, dict):
            return None, None
        name = str(record.get("path", ""))
        if not name or Path(name).name != name:
            errors.append(f"{label} provenance path is missing or unsafe")
            return None, None
        matches = list(evidence_dir.rglob(name))
        if len(matches) != 1:
            errors.append(f"expected exactly one uploaded {label} provenance file, found {len(matches)}")
            return None, None
        path = matches[0]
        if sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
            errors.append(f"uploaded {label} provenance hash does not match")
            return path, None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"uploaded {label} provenance is invalid JSON: {error}")
            return path, None
        if not isinstance(value, dict):
            errors.append(f"uploaded {label} provenance must be an object")
            return path, None
        return path, value

    _upstream_path, uploaded_upstream = provenance_file(upstream, "CORE-1.0A production")
    if uploaded_upstream is not None:
        _require(
            uploaded_upstream.get("kind") == "core_1_0a_production"
            and uploaded_upstream.get("milestone") == "CORE-1.0A"
            and uploaded_upstream.get("status") == "PASS"
            and uploaded_upstream.get("qualification_only") is True
            and uploaded_upstream.get("worktree_clean") is True
            and uploaded_upstream.get("exact_revision") == revision
            and str(uploaded_upstream.get("ci_run_id")) == run_id
            and uploaded_upstream.get("production_default_changed") is False
            and uploaded_upstream.get("companion_remains_production_and_rollback") is True
            and uploaded_upstream.get("automatic_fallback") is False
            and uploaded_upstream.get("production_regression_gates") == gates
            and uploaded_upstream.get("shared_core_guards") == guards,
            "uploaded CORE-1.0A production evidence does not match the projected assertions",
            errors,
        )
    _check_path, uploaded_check = provenance_file(checked, "CORE-1.0A checker")
    if uploaded_check is not None:
        uploaded_source = uploaded_check.get("source_evidence")
        _require(
            uploaded_check.get("kind") == "core_1_0a_production_check"
            and uploaded_check.get("milestone") == "CORE-1.0A"
            and uploaded_check.get("decision") == "CORE_IN_PROCESS_PRODUCTION_GUARD_QUALIFIED"
            and uploaded_check.get("errors") == []
            and uploaded_check.get("exact_revision") == revision
            and str(uploaded_check.get("ci_run_id")) == run_id
            and isinstance(uploaded_source, dict)
            and uploaded_source.get("sha256") == upstream_hash,
            "uploaded CORE-1.0A checker evidence does not match the projected assertions",
            errors,
        )
    return revision or None, run_id or None


def check(evidence_dir: Path, *, ci_closure: bool = False) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    artifacts: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(evidence_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path}: invalid JSON: {error}")
            continue
        if isinstance(value, dict) and str(value.get("kind", "")).startswith("core_pkg_1_"):
            artifacts.append((path, value))

    platform_rows = [value for _, value in artifacts if value.get("matrix_role") == "platform"]
    python_rows = [value for _, value in artifacts if value.get("matrix_role") == "python_compatibility"]
    if len(platform_rows) != len(PLATFORMS) or {str(row.get("platform")) for row in platform_rows} != PLATFORMS:
        errors.append("native wheel platform matrix is incomplete")
    if len(python_rows) != len(PYTHONS) or {str(row.get("python_minor")) for row in python_rows} != PYTHONS:
        errors.append("CPython 3.11-3.14 wheel matrix is incomplete")

    for row in platform_rows + python_rows:
        native = row.get("native_wheel", {})
        language = row.get("language_wheel", {})
        consumer = row.get("clean_consumer", {})
        if row.get("decision") != PENDING:
            errors.append(f"qualification row is not pending-CI: {row.get('platform')} {row.get('python_minor')}")
        if not (
            isinstance(native, dict)
            and native.get("distribution") == "aether-compiler-core"
            and native.get("version") == "1.0.0rc4"
            and native.get("contains_binding") is True
            and native.get("contains_companion") is True
            and native.get("contains_native_manifest") is True
            and re.fullmatch(r"[0-9a-f]{64}", str(native.get("sha256", "")))
        ):
            errors.append("native wheel identity/content/hash evidence is incomplete")
        if not (
            isinstance(language, dict)
            and language.get("distribution") == "aether-language"
            and language.get("requires_exact_native_core") is True
        ):
            errors.append("aether-language exact native dependency evidence is missing")
        if not (
            isinstance(consumer, dict)
            and consumer.get("status") == "PASS"
            and consumer.get("consumer", {}).get("cargo_available") is False
            and consumer.get("consumer", {}).get("rustc_available") is False
            and consumer.get("binding", {}).get("qualification_only") is False
            and consumer.get("production_transport", {}).get("is_companion_client") is True
        ):
            errors.append("clean consumer/binding/companion/default-transport evidence failed")

    required_kinds = {
        "core_pkg_1_binding_smoke",
        "core_pkg_1_companion_smoke",
        "core_pkg_1_contract",
        "core_pkg_1_failure_campaign",
        "core_pkg_1_source_development",
    }
    required: dict[str, tuple[Path, dict[str, object]]] = {}
    for kind in sorted(required_kinds):
        selected = [(path, value) for path, value in artifacts if value.get("kind") == kind]
        if len(selected) != 1:
            errors.append(f"expected exactly one mandatory evidence kind {kind}, found {len(selected)}")
            continue
        required[kind] = selected[0]
        if selected[0][1].get("status") != "PASS":
            errors.append(f"mandatory evidence failed: {kind}")

    revision: str | None = None
    run_id: str | None = None
    binding_item = required.get("core_pkg_1_binding_smoke")
    if binding_item is not None:
        _binding_path, binding = binding_item
        revision, run_id = _binding_guard(
            binding,
            evidence_dir=evidence_dir,
            ci_closure=ci_closure,
            errors=errors,
        )

    manifest = [
        {
            "path": path.relative_to(evidence_dir).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "kind": value.get("kind"),
        }
        for path, value in artifacts
    ]
    decision = BLOCKED if errors else QUALIFIED if ci_closure else PENDING
    aggregate = {
        "artifact_schema_version": 1,
        "kind": "core_pkg_1_aggregate",
        "milestone": "CORE-PKG-1",
        "decision": decision,
        "exact_revision": revision,
        "ci_run_id": run_id,
        "production_transport": "companion",
        "production_default_changed": False,
        "companion_remains_production_and_rollback": True,
        "automatic_fallback": False,
        "in_process_promoted": False,
        "required_platforms": sorted(PLATFORMS),
        "required_python_minors": sorted(PYTHONS),
        "errors": errors,
        "artifact_manifest": manifest,
    }
    return aggregate, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ci-closure", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    aggregate, errors = check(args.evidence_dir, ci_closure=args.ci_closure)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(aggregate["decision"])
    for error in errors:
        print(f"- {error}")
    return 1 if args.require_ready and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
