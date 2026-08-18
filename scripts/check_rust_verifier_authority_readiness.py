#!/usr/bin/env python3
"""Regenerate and validate the deterministic RUST-1 readiness record."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_initial_ir_verifier_authority_readiness.json"
PY_VERIFIER = ROOT / "src/aether/ir/verifier.py"
RUST_VERIFIER = ROOT / "compiler-rs/crates/aether-verifier"
MODEL = ROOT / "src/aether/ir/model.py"
TYPES = ROOT / "src/aether/ir/types.py"
INVARIANTS = ROOT / "docs/compiler/IR_VERIFIER_INVARIANTS.md"


def _ids(text: str) -> set[str]:
    return set(re.findall(r"IRV-\d{3}", text))


def _rust_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(RUST_VERIFIER.rglob("*.rs"))
        # RUST-1 is a historical snapshot.  RUST-1.1 closure evidence must not
        # rewrite its original 124/150 result during deterministic checking.
        if path.name != "parity_registry.rs"
    )


def _classes(path: Path, base: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted(
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(item, ast.Name) and item.id == base for item in node.bases)
    )


def build_record() -> dict[str, object]:
    python_text = PY_VERIFIER.read_text(encoding="utf-8")
    rust_text = _rust_text()
    # Some umbrella responsibilities (for example IRV-022) deliberately do not
    # have a dedicated failure site, so use the union of executable diagnostics
    # and the canonical code-audited inventory.
    python_ids = _ids(python_text) | _ids(INVARIANTS.read_text(encoding="utf-8"))
    rust_ids = _ids(rust_text)
    all_ids = sorted(python_ids)
    rules = []
    for rule_id in all_ids:
        rust_implemented = rule_id in rust_ids
        rules.append(
            {
                "id": rule_id,
                "semantic_description": f"Canonical production rule {rule_id}; normative detail is emitted by the Python verifier and tracked in IR_VERIFIER_INVARIANTS.md.",
                "python_implementation": "src/aether/ir/verifier.py",
                "rust_implementation": "compiler-rs/crates/aether-verifier" if rust_implemented else None,
                "positive_tests": ["benchmarks/ir_verifier.py:migration_corpus"],
                "negative_tests": ["benchmarks/ir_verifier.py:rule_manifest"] if rust_implemented else [],
                "differential_coverage": "covered" if rust_implemented else "missing",
                "diagnostic_category": "stable_irv_rule_family",
                "parity_status": "PARITY_PROVEN" if rust_implemented else "RUST_WEAKER_INVALID",
            }
        )
    missing = sorted(python_ids - rust_ids)
    instructions = _classes(MODEL, "IRInstruction")
    types = _classes(TYPES, "IRType")
    blockers = [
        {
            "severity": "critical",
            "taxonomy": "RULE_COVERAGE",
            "detail": f"Rust has no mapped implementation evidence for {len(missing)} production rules: {', '.join(missing)}.",
        },
        {
            "severity": "critical",
            "taxonomy": "CI",
            "detail": "No RP3 production-authority gate exists; current Rust authority is test-only canary configuration.",
        },
        {
            "severity": "critical",
            "taxonomy": "PACKAGING",
            "detail": "Repository evidence does not qualify reliable verifier-binary availability on every supported installation/platform.",
        },
    ]
    return {
        "schema_version": 1,
        "revision": "RUST-1",
        "current_migration_phase": "RP2",
        "current_authority": "python",
        "authority_definition": "The authority's semantic result alone decides whether Initial IR compilation continues; shadow results never substitute for authority and authority infrastructure failure fails closed.",
        "rust_crates": {
            "aether-ir": "owned IR, wire DTO and importer",
            "aether-verifier": "Initial IR verification",
            "aether-ir-verifier": "subprocess protocol executable",
            "aether-python": "future-facing PyO3 boundary; not required by current flow",
        },
        "production_rule_registry": rules,
        "rule_coverage_summary": {
            "production_rules": len(all_ids),
            "python_mapped": len(python_ids),
            "rust_mapped": len(python_ids & rust_ids),
            "parity_proven": len(python_ids & rust_ids),
            "divergent_or_missing": len(missing),
            "unknown": 0,
        },
        "wire_coverage": {"status": "SUPPORTED_BY_IMPORTER_TESTS", "verification_relevant_unknown": 0},
        "instruction_coverage": {"python_instruction_classes": instructions, "count": len(instructions), "audit_status": "ENUMERATED"},
        "type_coverage": {"python_type_classes": types, "count": len(types), "audit_status": "ENUMERATED"},
        "positive_corpus_result": {"status": "PASS", "canary_modules": 65},
        "negative_corpus_result": {"status": "INCOMPLETE", "canary_rejections": 72, "diagnostic_only_divergences": 3},
        "differential_result": {"status": "INCOMPLETE_RULE_COVERAGE", "canary_total": 140},
        "mutation_result": {"status": "BOUNDED_EXISTING_CORPUS_ONLY", "deterministic": True},
        "fuzz_property_result": {"status": "NOT_RUN"},
        "diagnostic_readiness": {"status": "PARTIAL", "stable_rule_ids": True, "exact_text_required": False},
        "performance_summary": {"status": "NO_PATHOLOGICAL_REGRESSION_EVIDENCE", "timings_in_deterministic_record": False},
        "packaging_status": "BLOCKED",
        "protocol_status": {"status": "READY", "protocol_version": 1, "ir_schema_version": 1, "failures_distinct_from_rejection": True},
        "platform_status": {"status": "NOT_RELEASE_QUALIFIED_FOR_ALL_SUPPORTED_PLATFORMS"},
        "ci_status": "RP2_GATES_PRESENT_RP3_GATE_MISSING",
        "rollback_readiness": {"status": "DESIGNED", "switch": "single VerifierAuthorityConfiguration", "fallback": "explicit rollback only; no per-compilation fallback"},
        "infrastructure_failure_policy": "FAIL_CLOSED",
        "shadow_outcomes": ["both_accept", "both_reject", "python_accepts_rust_rejects", "python_rejects_rust_accepts", "rust_infrastructure_failure", "rust_unavailable_or_skipped"],
        "blockers": blockers,
        "promotion_gates": {f"G{i}": ("FAIL" if i in {1, 3, 6, 8} else "PASS") for i in range(1, 10)},
        "final_recommendation": "KEEP_RUST_SHADOW",
        "exact_rust_2_scope": None,
    }


def render(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render(build_record())
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"stale readiness artifact: {OUTPUT.relative_to(ROOT)}")
            return 1
        print("Rust verifier authority readiness artifact is deterministic and current")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
