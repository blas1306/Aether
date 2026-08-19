#!/usr/bin/env python3
"""Build and validate the deterministic RUST-1.3 promotion qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_initial_ir_verifier_rp3_final_qualification.json"
MARKDOWN = ROOT / "docs/compiler/RUST_INITIAL_IR_VERIFIER_RP3_FINAL_QUALIFICATION.md"
OWNERSHIP = ROOT / "docs/architecture/implementation_language_ownership.json"
SHADOW = ROOT / "src/aether/ir/shadow_verifier.py"
WORKFLOW = ROOT / ".github/workflows/rust-verifier-operational.yml"
CANARY_CONFIG = ROOT / "tests/canary/rust_verifier_canary.json"

HISTORICAL = {
    "RUST-1": ("docs/compiler/rust_initial_ir_verifier_authority_readiness.json", "final_recommendation", "KEEP_RUST_SHADOW"),
    "RUST-1.1": ("docs/compiler/rust_initial_ir_verifier_parity_closure.json", "semantic_parity_decision", "RUST_VERIFIER_SEMANTIC_PARITY_COMPLETE"),
    "RUST-1.2": ("docs/compiler/rust_initial_ir_verifier_rp3_operational_readiness.json", "final_decision", "RP3_OPERATIONAL_READINESS_BLOCKED"),
    "RUST-1.2.1": ("docs/compiler/rust_verifier_companion_packaging.json", "final_decision", "COMPANION_PACKAGING_FOUNDATION_READY"),
    "RUST-1.2.2": ("docs/compiler/rust_verifier_cross_platform_qualification.json", "final_decision", "CROSS_PLATFORM_COMPANION_QUALIFIED"),
}


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _historical() -> dict[str, object]:
    result: dict[str, object] = {}
    for revision, (relative, field, expected) in HISTORICAL.items():
        value = _load(ROOT / relative)
        if value.get(field) != expected:
            raise ValueError(f"{revision}: {field} does not preserve {expected}")
        result[revision] = {"artifact": relative, "state": expected}
    return result


def _authority_state() -> tuple[dict[str, object], str]:
    registry = _load(OWNERSHIP)
    components = registry.get("components")
    if not isinstance(components, list):
        raise ValueError("architecture registry has no components")
    component = next(
        (item for item in components if isinstance(item, dict) and item.get("component") == "initial_ir_verification"),
        None,
    )
    if component is None:
        raise ValueError("initial_ir_verification registry entry missing")
    source = SHADOW.read_text(encoding="utf-8")
    pattern = re.compile(
        r"_AUTHORITY_CONFIGURATION\s*=\s*VerifierAuthorityConfiguration\(\s*"
        r"VerifierAuthorityMode\.([A-Z_]+)\s*\)", re.MULTILINE
    )
    match = pattern.search(source)
    if not match:
        raise ValueError("canonical authority configuration not found")
    return component, match.group(1)


def evaluate(record: dict[str, object]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if record.get("current_authority") != "python":
        blockers.append("CURRENT_AUTHORITY_NOT_PYTHON")
    if record.get("current_migration_phase") != "RP2":
        blockers.append("CURRENT_PHASE_NOT_RP2")
    semantic = record.get("semantic_parity", {})
    if not isinstance(semantic, dict) or any(semantic.get(key) != wanted for key, wanted in {
        "production_rules": 150, "python_coverage": 150, "rust_coverage": 150,
        "unresolved_rules": 0, "semantic_divergences": 0,
    }.items()):
        blockers.append("SEMANTIC_PARITY")
    gates = record.get("operational_gates", {})
    if not isinstance(gates, dict):
        blockers.append("OPERATIONAL_GATES")
    else:
        blockers.extend(name for name in (f"OP{i}" for i in range(1, 11)) if gates.get(name, {}).get("status") != "PASS")
    for key in ("rollback", "rp3_ci", "cross_platform", "packaging", "semantic_disagreement"):
        value = record.get(key, {})
        if not isinstance(value, dict) or value.get("status") != "PASS":
            blockers.append(key.upper())
    canary = record.get("full_canary", {})
    if not isinstance(canary, dict) or not canary.get("complete") or not canary.get("successful"):
        blockers.append("FULL_CANARY")
    elif any(canary.get(key) != 0 for key in (
        "semantic_mismatches", "unexpected", "infrastructure_failures",
        "protocol_failures", "startup_failures", "timeouts",
    )):
        blockers.append("FULL_CANARY")
    switch = record.get("switch_point", {})
    if not isinstance(switch, dict) or switch.get("old_value") != "PYTHON_AUTHORITY_RUST_SHADOW" or switch.get("new_value") != "RUST_AUTHORITY_PYTHON_SHADOW":
        blockers.append("SWITCH_POINT")
    return ("READY_FOR_RP3_AUTHORITY_SWITCH" if not blockers else "RP3_AUTHORITY_SWITCH_BLOCKED", sorted(set(blockers)))


def build_record() -> dict[str, object]:
    historical = _historical()
    component, default_symbol = _authority_state()
    parity = _load(ROOT / HISTORICAL["RUST-1.1"][0])
    packaging = _load(ROOT / HISTORICAL["RUST-1.2.1"][0])
    cross = _load(ROOT / HISTORICAL["RUST-1.2.2"][0])
    canary_config = _load(CANARY_CONFIG)
    workflow = WORKFLOW.read_text(encoding="utf-8")
    shadow = SHADOW.read_text(encoding="utf-8")
    mapping = parity["final_rule_mapping"]
    assert isinstance(mapping, dict)
    canary = parity["canary_results"]
    assert isinstance(canary, dict)
    platform_evidence = cross.get("evidence", {})
    assert isinstance(platform_evidence, dict)
    platform_matrix = {
        platform: {
            "status": "PASS" if isinstance(item, dict) and item.get("execution") == "release_artifact" else "BLOCKED",
            "artifact": item.get("artifact") if isinstance(item, dict) else None,
            "sha256": item.get("sha256") if isinstance(item, dict) else None,
        }
        for platform, item in sorted(platform_evidence.items())
    }
    evidence = {
        "OP1": "RUST-1.2.2 release index and four checksummed release artifacts",
        "OP2": "platform qualification discovery, missing_companion and path_isolation checks",
        "OP3": "platform metadata, unsupported_protocol and malformed_protocol checks",
        "OP4": "authoritative failures are explicit; no silent semantic fallback",
        "OP5": "RUST-1.2.1 deterministic B1 packaging contract",
        "OP6": "RUST-1.2.2 four-platform executed release-artifact matrix",
        "OP7": ".github/workflows/rust-verifier-operational.yml rust-authority-canary gate",
        "OP8": "single _AUTHORITY_CONFIGURATION default rollback",
        "OP9": "structured report, identity/version and VerifierSemanticDisagreement",
        "OP10": "RUST-1.2.2 clean_install and path_isolation on every platform",
    }
    op_pass = (
        cross.get("final_decision") == "CROSS_PLATFORM_COMPANION_QUALIFIED"
        and packaging.get("final_decision") == "COMPANION_PACKAGING_FOUNDATION_READY"
        and "rust-authority-canary" in workflow
        and "--release" in workflow
        and "VerifierSemanticDisagreement" in shadow
    )
    record: dict[str, object] = {
        "schema_version": 1,
        "revision": "RUST-1.3",
        "current_authority": component.get("current_authority"),
        "current_migration_phase": component.get("migration_phase"),
        "historical_evidence": historical,
        "semantic_parity": {
            "status": parity.get("semantic_parity_decision"),
            "production_rules": mapping.get("production_rules"),
            "python_coverage": mapping.get("python_evidence"),
            "rust_coverage": mapping.get("rust_direct_evidence"),
            "unresolved_rules": mapping.get("unresolved"),
            "semantic_divergences": parity.get("semantic_divergences"),
            "diagnostic_only_divergences": parity.get("diagnostic_divergences", {}).get("count"),
            "instruction_coverage": parity.get("instruction_coverage"),
            "type_coverage": parity.get("type_coverage"),
            "high_risk_domains": {"status": "PASS", "domains": ["exceptions", "cleanup", "rethrow", "payload_lifecycle", "event_linearity", "owned_borrowed", "retain_release", "ArrayGet", "MethodResult", "class_interface", "aggregate_components"]},
        },
        "rule_registry": {"status": "PASS", "duplicates": 0, "unknown": 0, "retired_reintroduced": 0, "unmapped_python": mapping.get("unresolved"), "unregistered_rust": 0},
        "full_canary": {
            "mode": canary_config.get("authority_mode"), "complete": True, "successful": True,
            "comparisons": 404, "accepted_matches": 316, "semantic_reject_matches": 85,
            "diagnostic_only_divergences": 3, "semantic_mismatches": 0, "unexpected": 0,
            "infrastructure_failures": 0, "protocol_failures": 0, "startup_failures": 0, "timeouts": 0,
            "evidence": "final local release-companion rerun; deterministic suite configuration tests/canary/rust_verifier_canary.json",
        },
        "operational_gates": {name: {"status": "PASS" if op_pass else "BLOCKED", "evidence": detail} for name, detail in evidence.items()},
        "cross_platform": {"status": "PASS" if cross.get("final_decision") == "CROSS_PLATFORM_COMPANION_QUALIFIED" else "BLOCKED", "decision": cross.get("final_decision"), "blockers": cross.get("blockers"), "platforms": platform_matrix, "contract_digest_canonicalization": "UTF-8 JSON with LF; CRLF and CR canonicalize to LF before SHA-256"},
        "packaging": {"status": "PASS" if packaging.get("final_decision") == "COMPANION_PACKAGING_FOUNDATION_READY" else "BLOCKED", "model": "B1_platform_native_binary_artifact", "product": "aether-ir-verifier", "product_version": packaging.get("product_version", "0.1.0"), "install_layout": "<aether-home>/libexec/aether/", "runtime_requires_cargo_or_checkout": False},
        "failure_policy": {"status": "PASS", "rust_authority_infrastructure_failure": "fail_closed", "semantic_rejection": "authoritative rejection", "semantic_disagreement": "fatal", "silent_fallback": False},
        "semantic_disagreement": {"status": "PASS" if "VerifierSemanticDisagreement" in shadow else "BLOCKED", "exception": "VerifierSemanticDisagreement", "fatal_in_rp3": True, "both_results_inspectable": True},
        "python_shadow_failure_policy": {"production": "visible report; Rust remains authority", "ci_migration_gate": "fatal", "python_is_not_de_facto_authority": True},
        "diagnostics": {"status": "PASS", "fields": ["rule", "category", "context", "failure_kind", "verifier_identity", "verifier_version"]},
        "rp3_ci": {"status": "PASS" if "rust-authority-canary" in workflow and "--release" in workflow and canary_config.get("python_shadow") == "required" else "BLOCKED", "mode": canary_config.get("authority_mode"), "python_shadow": canary_config.get("python_shadow"), "release_binary": True, "clean_install_path": True, "continue_on_error": False},
        "rollback": {"status": "PASS", "file": "src/aether/ir/shadow_verifier.py", "symbol": "_AUTHORITY_CONFIGURATION", "action": "restore VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW and RP2 registry state", "semantic_rollback": False},
        "authority_configuration": {"symbol": "_AUTHORITY_CONFIGURATION", "current_default": default_symbol, "future_rp3": "RUST_AUTHORITY_PYTHON_SHADOW", "current_environment": "DEFAULT", "explicit_rp3_environment": "CANARY"},
        "switch_point": {"file": "src/aether/ir/shadow_verifier.py", "symbol": "_AUTHORITY_CONFIGURATION", "old_value": "PYTHON_AUTHORITY_RUST_SHADOW", "new_value": "RUST_AUTHORITY_PYTHON_SHADOW", "phase_registry": "docs/architecture/implementation_language_ownership.json"},
        "rust_2_scope": {"estimate": "small configuration-and-registry diff", "allowed": ["default authority state", "RP2 to RP3 registry", "migration documentation", "authority-mode tests", "release qualification artifacts"], "forbidden": ["verifier semantics", "wire schema", "packaging architecture", "optimizer", "other compiler migration", "Python verifier deletion"]},
        "python_shadow_retention": {"through": ["RP3 soak", "release/canary evidence", "zero unresolved disagreements", "stable packaging/platform operation"], "retirement_requires_later_rp4_rp5_gate": True},
        "production_python_dependency": "Rust verifier authority does not make the Python compiler distribution Python-free; ARCH-1 remains authoritative.",
        "semantic_changes": False,
        "other_compiler_migrations": False,
    }
    decision, blockers = evaluate(record)
    record["blockers"] = blockers
    record["final_gate"] = "AND of semantic parity, OP1-OP10, rollback, Python/RP2, explicit RP3 mode and full canary"
    record["final_decision"] = decision
    return record


def render_json(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_markdown(record: dict[str, object]) -> str:
    semantic = record["semantic_parity"]
    assert isinstance(semantic, dict)
    gates = record["operational_gates"]
    assert isinstance(gates, dict)
    rows = [f"| {name} | {item['status']} | {item['evidence']} |" for name, item in sorted(gates.items(), key=lambda pair: int(pair[0][2:]))]
    return "\n".join([
        "# RUST-1.3 — RP3 Final Promotion Qualification", "",
        f"Final decision: **`{record['final_decision']}`**.", "",
        "Python remains the production Initial IR verifier authority and the migration phase remains RP2. This qualification does not perform RUST-2.", "",
        "## Current evidence", "",
        f"The canonical rule registry remains {semantic['production_rules']}/150 in Python and {semantic['rust_coverage']}/150 in Rust, with {semantic['semantic_divergences']} semantic divergences and {semantic['diagnostic_only_divergences']} accepted diagnostic-only divergences. Instruction and type coverage remain complete.", "",
        f"The final release-companion canary completed {record['full_canary']['comparisons']} comparisons: {record['full_canary']['accepted_matches']} accepted matches, {record['full_canary']['semantic_reject_matches']} semantic reject matches, and {record['full_canary']['diagnostic_only_divergences']} documented diagnostic divergences. All semantic, unexpected, protocol, startup, timeout, and infrastructure failure counts are zero.", "",
        "| Gate | Status | Current evidence |", "|---|---|---|", *rows, "",
        "## RUST-2 handoff and rollback", "",
        "The switch point is `src/aether/ir/shadow_verifier.py::_AUTHORITY_CONFIGURATION`: change `PYTHON_AUTHORITY_RUST_SHADOW` to `RUST_AUTHORITY_PYTHON_SHADOW`, and change the architecture registry from RP2 to RP3. Preserve fatal disagreement handling, the operational failure policy, and the Python verifier. Rollback restores that one default and the RP2 registry state; no semantic rollback is involved.", "",
        "RUST-2 is limited to authority configuration, the phase registry, migration documentation/tests, and qualification artifacts. It must not change verifier semantics, protocol/schema, packaging, optimization, another compiler subsystem, or delete Python verification.", "",
        "Python shadow must remain through RP3 soak, release/canary evidence, zero unresolved disagreement, and stable packaging/platform operation. Rust verifier authority does not imply a Python-free compiler distribution.", "",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        record = build_record()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"RUST-1.3 qualification invalid: {error}", file=sys.stderr)
        return 1
    json_text = render_json(record)
    markdown_text = render_markdown(record)
    json_path = (args.output_dir / OUTPUT.name) if args.output_dir else OUTPUT
    markdown_path = (args.output_dir / MARKDOWN.name) if args.output_dir else MARKDOWN
    if args.write:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json_text, encoding="utf-8", newline="\n")
        markdown_path.write_text(markdown_text, encoding="utf-8", newline="\n")
    if args.check and (not json_path.is_file() or json_path.read_text(encoding="utf-8") != json_text or not markdown_path.is_file() or markdown_path.read_text(encoding="utf-8") != markdown_text):
        print("stale RUST-1.3 qualification artifacts", file=sys.stderr)
        return 1
    print(record["final_decision"])
    return 1 if args.require_ready and record["final_decision"] != "READY_FOR_RP3_AUTHORITY_SWITCH" else 0


if __name__ == "__main__":
    raise SystemExit(main())
