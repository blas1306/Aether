#!/usr/bin/env python3
"""Generate or validate the deterministic RUST-2 promotion record."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_initial_ir_verifier_authority_promotion.json"


def _json(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative}: expected object")
    return value


def build_record() -> dict[str, object]:
    qualification = _json("docs/compiler/rust_initial_ir_verifier_rp3_final_qualification.json")
    parity = _json("docs/compiler/rust_initial_ir_verifier_parity_closure.json")
    cross = _json("docs/compiler/rust_verifier_cross_platform_qualification.json")
    ownership = _json("docs/architecture/implementation_language_ownership.json")
    component = next(item for item in ownership["components"] if item["component"] == "initial_ir_verification")
    source = (ROOT / "src/aether/ir/shadow_verifier.py").read_text(encoding="utf-8")
    match = re.search(r"_AUTHORITY_CONFIGURATION\s*=\s*VerifierAuthorityConfiguration\(\s*VerifierAuthorityMode\.([A-Z_]+)\s*\)", source)
    if match is None:
        raise ValueError("canonical authority configuration missing")
    historical = {
        "RUST-1.3": qualification.get("final_decision"),
        "RUST-1.2.2": cross.get("final_decision"),
    }
    gates = qualification.get("operational_gates", {})
    ready = (
        historical == {"RUST-1.3": "READY_FOR_RP3_AUTHORITY_SWITCH", "RUST-1.2.2": "CROSS_PLATFORM_COMPANION_QUALIFIED"}
        and component.get("current_authority") == "rust"
        and component.get("migration_phase") == "RP3"
        and component.get("allowed_shadows") == ["python"]
        and match.group(1) == "RUST_AUTHORITY_PYTHON_SHADOW"
        and isinstance(gates, dict)
        and all(gates.get(f"OP{i}", {}).get("status") == "PASS" for i in range(1, 11))
        and "VerifierSemanticDisagreement" in source
        and "PYTHON_AUTHORITY_RUST_SHADOW" in source
    )
    canary = qualification["full_canary"]
    return {
        "schema_version": 1,
        "revision": "RUST-2",
        "pre_promotion": {"authority": "python", "shadow": "rust", "phase": "RP2", "configuration": "PYTHON_AUTHORITY_RUST_SHADOW"},
        "post_promotion": {"authority": "rust", "shadow": "python", "phase": "RP3", "configuration": match.group(1)},
        "switch_point": "src/aether/ir/shadow_verifier.py::_AUTHORITY_CONFIGURATION",
        "semantic_parity": {"reference": "RUST-1.1", "production_rules": 150, "python_rules": 150, "rust_rules": 150, "semantic_divergences": 0, "diagnostic_only_divergences": 3},
        "operational_gates": {f"OP{i}": gates.get(f"OP{i}", {}).get("status") for i in range(1, 11)},
        "canary": {key: canary.get(key) for key in ("complete", "successful", "comparisons", "semantic_mismatches", "unexpected", "infrastructure_failures", "startup_failures", "protocol_failures", "timeouts")},
        "companion": {"product": "aether-ir-verifier", "version": "0.1.0", "discovery": "<aether-home>/libexec/aether/", "cross_platform": historical["RUST-1.2.2"]},
        "policies": {"semantic_disagreement": "fatal", "rust_infrastructure_failure": "fail_closed_no_fallback", "python_shadow": "required_during_rp3", "python_shadow_ci_failure": "fatal_migration_gate"},
        "rollback": {"configuration": "PYTHON_AUTHORITY_RUST_SHADOW", "phase": "RP2", "semantic_change": False},
        "historical_qualification": historical,
        "python_verifier_retained": "class IRVerifier" in (ROOT / "src/aether/ir/verifier.py").read_text(encoding="utf-8"),
        "protocol": {"verifier_protocol": 1, "ir_schema": 1, "changed": False},
        "future_handoff": {"RP4": "Rust authority with optional/development Python shadow", "RP5": "Rust-only production verification", "implemented": False},
        "final_decision": "RUST_INITIAL_IR_AUTHORITY_PROMOTED" if ready else "RUST_INITIAL_IR_AUTHORITY_PROMOTION_FAILED",
    }


def render(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    record = build_record()
    value = render(record)
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != value:
            print(f"stale promotion artifact: {OUTPUT.relative_to(ROOT)}")
            return 1
    else:
        OUTPUT.write_text(value, encoding="utf-8", newline="\n")
    if args.require_promoted and record["final_decision"] != "RUST_INITIAL_IR_AUTHORITY_PROMOTED":
        return 1
    print(record["final_decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
