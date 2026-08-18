#!/usr/bin/env python3
"""Generate or check the deterministic RUST-1.2 readiness record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_initial_ir_verifier_rp3_operational_readiness.json"


def build_record() -> dict[str, object]:
    parity_path = "docs/compiler/rust_initial_ir_verifier_parity_closure.json"
    parity = json.loads((ROOT / parity_path).read_text(encoding="utf-8"))
    ownership = json.loads(
        (ROOT / "docs/architecture/implementation_language_ownership.json").read_text(
            encoding="utf-8"
        )
    )
    component = next(
        item
        for item in ownership["components"]
        if item["component"] == "initial_ir_verification"
    )
    workflow = (ROOT / ".github/workflows/rust-verifier-operational.yml").read_text(
        encoding="utf-8"
    )
    rust_authority_gate = (
        "rust-authority-canary:" in workflow
        and "continue-on-error: true" not in workflow
        and "target/release/aether-ir-verifier" in workflow
    )
    companion_gate = "companion-package:" in workflow
    gates = [
        {"id": "OP1", "name": "binary_availability", "status": "BLOCKED", "evidence": "No versioned companion artifacts have yet been published for every claimed platform."},
        {"id": "OP2", "name": "discovery", "status": "PASS", "evidence": "discover_packaged_rust_verifier resolves only an explicit manifest directory; developer PATH/repository lookup is opt-in."},
        {"id": "OP3", "name": "version_protocol_match", "status": "PASS", "evidence": "The --identity handshake requires identity schema 1, package 0.0.0, protocol 1, IR schema 1, and verify capability."},
        {"id": "OP4", "name": "startup_failure_policy", "status": "PASS", "evidence": "Rust authority fails closed with typed missing, permission, identity, spawn, crash, malformed-output, and timeout failures."},
        {"id": "OP5", "name": "packaging", "status": "BLOCKED", "evidence": "Model B tooling exists, but the release process does not yet publish or declare the companion as an installation requirement."},
        {"id": "OP6", "name": "platform_readiness", "status": "BLOCKED", "evidence": "Linux, Windows, and macOS CI is configured, but checked-in completed release-package evidence for all three is absent."},
        {"id": "OP7", "name": "ci_rp3_coverage", "status": "PASS" if rust_authority_gate and companion_gate else "BLOCKED", "evidence": "CI gates release Rust-authority/Python-shadow canary and companion packaging on Linux, Windows, and macOS."},
        {"id": "OP8", "name": "rollback", "status": "PASS", "evidence": "One VerifierAuthorityConfiguration change restores PYTHON_AUTHORITY_RUST_SHADOW; the rollback rehearsal tests both transitions."},
        {"id": "OP9", "name": "diagnostics_reporting", "status": "PASS", "evidence": "Reports retain authority/shadow roles, comparison, request hash, versions, and bounded failure kind/summary."},
        {"id": "OP10", "name": "clean_install", "status": "BLOCKED", "evidence": "Clean companion resolution is tested, but no released Python-plus-companion installation contract can yet be qualified."},
    ]
    blockers = [gate["id"] for gate in gates if gate["status"] == "BLOCKED"]
    assert not any(gate["status"] == "UNKNOWN" for gate in gates)
    assert component["current_authority"] == "python"
    assert component["migration_phase"] == "RP2"
    assert parity["semantic_parity_decision"] == "RUST_VERIFIER_SEMANTIC_PARITY_COMPLETE"
    return {
        "schema_version": 1,
        "revision": "RUST-1.2",
        "current_authority": "python",
        "current_migration_phase": "RP2",
        "semantic_parity_evidence": parity_path,
        "semantic_parity_status": "complete",
        "discovery_policy": ["explicit_test_or_development_path", "explicit_versioned_companion_package_directory", "otherwise_fail"],
        "path_lookup_policy": "disabled unless explicitly requested by development code",
        "packaging_model": "B_separate_versioned_platform_companion_artifact",
        "wheel_strategy": "Python wheel remains platform-independent; it does not silently bundle native bytes.",
        "sdist_strategy": "Source/development distribution only; installation does not implicitly invoke Cargo.",
        "installed_binary_location": "<companion-root>/0.0.0/<sysconfig-platform>/aether-ir-verifier[.exe]",
        "protocol_policy": {"identity_schema": 1, "protocol": 1, "ir_schema": 1, "capabilities": ["verify"], "revision_match": "compatible_contract_not_git_sha"},
        "failure_policy": {"rust_authority_infrastructure": "FAIL_CLOSED", "semantic_disagreement": "FATAL_INTERNAL_ERROR", "python_shadow_failure": "FAIL_CLOSED_DURING_RP3_MIGRATION"},
        "timeout_seconds": 5.0,
        "release_canary": {"total": 404, "accepted_matches": 316, "semantic_reject_matches": 85, "documented_diagnostic_divergences": 3, "semantic_mismatches": 0, "unexpected": 0, "infrastructure_failures": 0, "timeouts": 0, "complete": True, "successful": True},
        "clean_install": {"companion_resolution_outside_checkout": "PASS", "released_python_plus_companion_contract": "BLOCKED", "source_tree_leakage": "PASS"},
        "performance_sanity": {"status": "NO_PATHOLOGICAL_OVERHEAD", "subprocess_remains_canonical": True, "timings_are_host_local_not_promotion_evidence": True},
        "platforms": ["linux", "windows", "macos"],
        "operational_gates": gates,
        "blockers": blockers,
        "final_decision": "RP3_OPERATIONAL_READINESS_BLOCKED",
        "rust_2_scope": None,
    }


def render(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render(build_record())
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"stale readiness artifact: {OUTPUT.relative_to(ROOT)}")
            return 1
        print("RUST-1.2 operational readiness artifact is deterministic and current")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
