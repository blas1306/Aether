#!/usr/bin/env python3
"""Generate or validate the evidence-only RUST-3.6 promotion record."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_ssa_authority_promotion.json"
DEFAULT_PLATFORM_EVIDENCE = ROOT / "docs/compiler/rust_ssa_authority_platform_evidence"
DEFAULT_SOAK_EVIDENCE = ROOT / "docs/compiler/rust_ssa_authority_soak.json"
PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    return value


def _platform_evidence(directory: Path | None) -> tuple[dict[str, object], list[str]]:
    records: dict[str, object] = {}
    blockers: list[str] = []
    for platform, target in PLATFORMS.items():
        path = directory / f"{platform}.json" if directory is not None else None
        try:
            value = _json(path) if path is not None else {}
            comparison = value.get("comparison", {})
            checks = value.get("checks", {})
            valid = (
                value.get("revision") == "RUST-3.6"
                and value.get("platform") == platform
                and value.get("rust_target") == target
                and value.get("authority") == "rust"
                and value.get("shadow") == "python_synchronous"
                and value.get("returned_ssa_origin") == "rust_schema_v2_import"
                and value.get("execution") == "clean_release_artifact_outside_checkout"
                and isinstance(checks, dict)
                and checks
                and set(checks.values()) == {"PASS"}
                and isinstance(comparison, dict)
                and comparison.get("mode") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
                and comparison.get("process_startups") == 1
                and comparison.get("semantic_mismatches") == 0
                and comparison.get("infrastructure_failures") == 0
                and set(comparison.get("returned_ssa_origins", []))
                == {"rust_schema_v2_import"}
                and set(comparison.get("rollback_modes", []))
                == {"PYTHON_SSA_AUTHORITY_RUST_SHADOW", "PYTHON_SSA_ONLY"}
            )
        except (OSError, ValueError, json.JSONDecodeError):
            value, valid = {}, False
        if valid:
            records[platform] = {
                "status": "PASS",
                "sha256": sha256(path.read_bytes()).hexdigest(),  # type: ignore[union-attr]
            }
        else:
            records[platform] = {"status": "BLOCKED", "reason": "fresh RUST-3.6 native evidence missing or invalid"}
            blockers.append(platform)
    return records, blockers


def build_record(
    platform_evidence: Path | None = None,
    soak_evidence: Path | None = None,
) -> dict[str, object]:
    historical = _json(ROOT / "docs/compiler/rust_ssa_authority_promotion_qualification.json")
    authority_historical = _json(ROOT / "docs/compiler/rust_ssa_authority_historical_qualification.json")
    operational = _json(ROOT / "docs/compiler/rust_ssa_shadow_operational_qualified.json")
    ownership = _json(ROOT / "docs/architecture/implementation_language_ownership.json")
    performance = _json(ROOT / "docs/compiler/rust_ssa_authority_production_performance.json")
    full_regression = _json(ROOT / "docs/compiler/rust_ssa_authority_full_regression.json")
    source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    pipeline = (ROOT / "src/aether/pipeline.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/rust-ssa-shadow.yml").read_text(encoding="utf-8")
    platforms, platform_blockers = _platform_evidence(platform_evidence)

    default_rust = re.search(
        r"mode:\s*SSALoweringAuthorityMode\s*=\s*SSALoweringAuthorityMode\.RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        source,
    ) is not None
    components = {row["component"]: row for row in ownership["components"]}
    registry_ok = all(
        components[name].get("current_authority") == "rust"
        and components[name].get("migration_phase") == "RP3"
        and components[name].get("allowed_shadows") == ["python"]
        for name in ("ssa_construction", "ssa_verification")
    )
    fresh_checks = authority_historical.get("checks", {})
    historical_ok = (
        historical.get("decision") == "READY_FOR_RUST_SSA_AUTHORITY_SWITCH"
        and authority_historical.get("decision") == "RUST_SSA_AUTHORITY_HISTORICAL_PASS"
        and authority_historical.get("accepted") == 116
        and isinstance(fresh_checks, dict)
        and len(fresh_checks) == 8
        and all(row.get("passed") == 116 and row.get("failed") == 0 for row in fresh_checks.values())
    )
    pre_promotion_soak = operational.get("soak", {})
    try:
        post_soak_record = _json(soak_evidence) if soak_evidence is not None else {}
    except (OSError, ValueError, json.JSONDecodeError):
        post_soak_record = {}
    soak = post_soak_record.get("soak", {})
    soak_ok = (
        post_soak_record.get("milestone") == "RUST-3.6"
        and post_soak_record.get("decision") == "RUST_SSA_AUTHORITY_SOAK_PASS"
        and isinstance(soak, dict)
        and soak.get("accepted", 0) >= 116
        and soak.get("shadow_compared") == soak.get("accepted")
        and soak.get("semantic_mismatches") == 0
        and soak.get("infrastructure_failures") == 0
    )
    platform_ok = not platform_blockers

    checks = [
        ("production default is Rust authority", default_rust),
        ("Python shadow is synchronous and mandatory", "python_ssa = run_python()" in source and "rust_ssa = run_rust()" in source),
        ("returned SSA is the imported Rust result", "authoritative = rust_ssa if rust_authoritative else python_ssa" in source and "rust_schema_v2_import" in pipeline),
        ("authority failures are fail closed with no fallback", "SSAShadowFailure" in source and "fallback" not in pipeline.lower()),
        ("both Python rollback modes remain configuration selections", all(name in source for name in ("PYTHON_SSA_ONLY", "PYTHON_SSA_AUTHORITY_RUST_SHADOW"))),
        ("Initial IR schema-v1 and SSA schema-v2 are unchanged", "SSA_SHADOW_SCHEMA_VERSION = 2" in source and "IR_SCHEMA_VERSION" in source),
        ("post-promotion historical authority corpus is 116/116", historical_ok),
        ("qualified adversarial and deep-CFG evidence remains PASS", historical.get("semantic_qualification", {}).get("rust_deep_cfg") == "PASS"),
        ("post-promotion expanded soak has zero failures", soak_ok),
        ("Rust Owned SSA and Python SSA verification remain required", "verify_owned_ssa" in (ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs").read_text(encoding="utf-8") and source.count("SSAVerifier(") >= 2),
        (
            "optimizer/backend and full repository regressions pass",
            (ROOT / "src/aether/ssa/authority_probe.py").is_file()
            and full_regression.get("decision") == "RUST_SSA_AUTHORITY_FULL_REGRESSION_PASS",
        ),
        ("clean-install RUST-3.6 evidence exists on every platform", platform_ok),
        ("all four native platform executions pass", platform_ok),
        (
            "persistent production transport is retained",
            "_PRODUCTION_RUST_SSA_CLIENT" in source
            and operational.get("transport", {}).get("persistent") == "PASS"
            and operational.get("transport", {}).get("long_session_requests") == 1000
            and operational.get("transport", {}).get("long_session_process_startups") == 1,
        ),
        ("CI exercises authority and both rollback modes", all(token in workflow for token in ("rust-authority", "python-authority-rust-shadow", "python-only"))),
        ("architecture registry records Rust RP3 authority", registry_ok),
    ]
    gates = [
        {"id": f"P{index:02d}", "name": name, "status": "PASS" if passed else "BLOCKED"}
        for index, (name, passed) in enumerate(checks, 1)
    ]
    promoted = all(gate["status"] == "PASS" for gate in gates)
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.6",
        "decision": "RUST_SSA_AUTHORITY_PROMOTED" if promoted else "RUST_SSA_AUTHORITY_PROMOTION_FAILED",
        "authority": {
            "old": "PYTHON_SSA_ONLY",
            "new": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "production_configuration": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "returned_ssa_origin": "rust_schema_v2_import",
            "shadow": "python_synchronous_mandatory",
        },
        "fail_closed_policy": {
            "all_rust_python_comparison_and_transport_failures": "abort compilation; return no SSA",
            "silent_python_fallback": False,
            "timeout": "terminate affected companion session; do not retry request",
        },
        "rollback": {
            "primary": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
            "independent": "PYTHON_SSA_ONLY",
            "source_or_schema_change_required": False,
        },
        "historical_qualification": {
            "readiness_decision": historical.get("decision"),
            "post_promotion_decision": authority_historical.get("decision"),
            "post_promotion_checks": fresh_checks,
            "readiness_artifact_sha256": sha256((ROOT / "docs/compiler/rust_ssa_authority_promotion_qualification.json").read_bytes()).hexdigest(),
            "post_promotion_artifact_sha256": sha256((ROOT / "docs/compiler/rust_ssa_authority_historical_qualification.json").read_bytes()).hexdigest(),
        },
        "pre_promotion_soak": pre_promotion_soak,
        "post_promotion_soak": soak if soak_ok else {"status": "BLOCKED", "reason": "fresh RUST-3.6 authority soak missing or invalid"},
        "post_promotion_platforms": platforms,
        "performance": performance,
        "full_regression": full_regression,
        "gates": gates,
        "unresolved_blockers": (
            {"operational": [], "semantic": []}
            if promoted
            else {
                "operational": (
                    (["fresh RUST-3.6 authority soak"] if not soak_ok else [])
                    + [f"fresh native authority evidence: {name}" for name in platform_blockers]
                ),
                "semantic": (
                    []
                    if full_regression.get("decision") == "RUST_SSA_AUTHORITY_FULL_REGRESSION_PASS"
                    else [
                        f"{name}: Rust/Python authority parity or Rust boundary verification"
                        for name in full_regression.get("failure_groups", {})
                    ]
                ),
            }
        ),
        "scope": {
            "production_authority": "rust",
            "rust_ssa_reaches_optimizer_or_backend": True,
            "python_implementation_preserved": (ROOT / "src/aether/ssa/general_builder.py").is_file(),
            "schemas_changed": False,
            "policies_changed": False,
            "optimizer_or_backend_semantics_changed": False,
            "historical_artifacts_modified": False,
            "commit_created": False,
        },
    }


def render(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--platform-evidence", type=Path, default=DEFAULT_PLATFORM_EVIDENCE)
    parser.add_argument("--soak-evidence", type=Path, default=DEFAULT_SOAK_EVIDENCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    record = build_record(args.platform_evidence, args.soak_evidence)
    rendered = render(record)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            print(f"stale promotion artifact: {args.output}")
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(record["decision"])
    return 1 if args.require_promoted and record["decision"] != "RUST_SSA_AUTHORITY_PROMOTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
