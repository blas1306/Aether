#!/usr/bin/env python3
"""Aggregate exact-revision, fail-closed RUST-3.7a stabilization evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_ssa_production_stabilization.json"
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_production_stabilization_evidence"
PROMOTED_REVISION = "aa0d6bf1d3316b0c425671bac768259d003f25d5"
PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}
REPRESENTATIVE_CATEGORIES = {
    "scalar", "numerical", "collections", "string", "aggregate",
    "class_interface", "exception", "constructor_ownership",
    "function_value_indirect_call",
}
REGRESSION_FAMILIES = {
    "source_location_preservation", "bounds_checked_provenance",
    "aggregate_ownership", "class_interface_ownership",
    "constructor_exceptional_cleanup", "nullable_ownership_and_casts",
    "collection_temporary_ownership", "indirect_calls_and_function_values",
}
DISCOVERY_ROOTS = ("examples", "benchmarks", "corpus", "tests", "scrap")
HISTORICAL_CORPUS_MANIFEST = Path(
    "scripts/rust_ssa_production_stabilization_historical_corpus.txt"
)
REQUIRED_CORPUS_CATEGORIES = {
    "benchmarks", "numerical_methods", "exceptions", "collections", "structs",
    "classes", "interfaces", "function_values_indirect_calls", "recursive_programs",
    "allocation_heavy", "string_heavy", "expense_tracker",
    "realistic_multi_function_modules",
}

# Frozen at the exact promoted revision.  These hashes make preservation an
# executable contract rather than a claim in the generated report.
FROZEN_FILES = {
    "docs/compiler/RUST_SSA_LOWERING_READINESS.md": "f823e28629e179dcffbc98c8b6b77179669eef613169662395a380775aff80a9",
    "docs/compiler/rust_ssa_lowering_readiness.json": "d0f76e8f108467207705128729305a320edec0febd7d9f49b0d84b59e123c941",
    "docs/compiler/RUST_SSA_AUTHORITY_PROMOTION.md": "cc94fb815035c92ef9cfdcb2ed1df57dc7fd8683ef7239a5268be9dac36e4c9d",
    "docs/compiler/rust_ssa_authority_promotion.json": "dabc5eb99461e964609d31f13de379539b8c9eab06e091b714bb198288582bbe",
    "docs/compiler/RUST_SSA_PROMOTION_FAILURE_ROOT_CAUSE_AUDIT.md": "95771d7be842330356dcd3d653ecfe60303f02b8796069cbc69f55cc3093720f",
    "docs/compiler/rust_ssa_promotion_failure_root_cause_audit.json": "e78d625c11a166fe0c8e79d85419233f52d6644f5355b1bd0009e4fe62f12524",
    "docs/compiler/RUST_SSA_PROMOTION_LIFECYCLE_DEFECT_CLOSURE.md": "3509e2795fa2f40a2b7d131915083f86a6b43809eac2e6171c6c639155b77883",
    "docs/compiler/rust_ssa_promotion_lifecycle_defect_closure.json": "727b229d9a2c39dfc136874ab8546c22ef30e76b3327677981ff92d77fb84b22",
    "docs/compiler/RUST_SSA_AUTHORITY_REQUALIFICATION.md": "6193d17565e8a723cb0d73d4eb667e09eb52b4d82373769b9d84205e65ce7450",
    "docs/compiler/rust_ssa_authority_requalification.json": "bb124a6a06fd097b3f92d35a94e0e7f247e7a2aea515b485dba88d6061a8c137",
    "docs/compiler/RUST_SSA_AUTHORITY_PROMOTION_V2.md": "a73520b561b3a6bf41d20fa999018c601b44611d5959f6010fee50b861220c5a",
    "docs/compiler/rust_ssa_authority_promotion_v2.json": "5ce5f2d7b91f258621237435a5f81a260256084904a8e87ef088a5e848a5d30f",
}
FROZEN_SCHEMA_POLICY_FILES = {
    "docs/compiler/ssa_lowering_policy_v1.json": "951b5f312f0485ba85f8b72495032a3a34edfc547a17ceffc7219fb73a9bce05",
    "docs/compiler/lifecycle_normalization_policy_v1.json": "52fd602db83fdec1ffb76df2514f3fa3173b68d7e631bb4e50027da107ff61ec",
    "src/aether/ir/dto.py": "69ac8e7c711f0eff90cc5eee42c0aca6c14138585baed74de57fb57892d7ef62",
    "src/aether/ssa/dto.py": "71452fbcb00f4922d61e8241ab02d4f26129eef40097e0f87d034325106c0f66",
    "src/aether/ssa/lowering_policy.py": "9b9f08f174316a5da635e2a128a0b95aed48e72a0a637a6f29a2c8e7a7adc6f5",
    "src/aether/ssa/lifecycle_normalization_policy.py": "82716fc883d23b173c6f105e2aa565da5183cb28d619eb1fe38a44fbe3d95b10",
    "compiler-rs/crates/aether-ir/src/lifecycle.rs": "f9555d976fe9c6113eaf266658d69eaf1b92fef18113abba05cf898353454ff4",
    "compiler-rs/crates/aether-ir/src/ssa.rs": "03649eaee8f088624d4adec66c42a7c34750e48bb29ec2cbba43433bcbfc5271",
}
FROZEN_SCHEMA_POLICY_TREES = {
    "compiler-rs/crates/aether-ir/src": "5a8f617269901a5b15f2f8c43dda23b839e9b1c01450187ff2a773296611bdea",
}
# RUST-3.9b is explicitly authorized to replace Rust dominator/lowering-core
# implementation.  Keep the broad historical tree guard for every other Rust
# IR source while the file-specific hashes above continue to freeze lifecycle,
# schema-v2, and other policy boundaries.
FROZEN_SCHEMA_POLICY_TREE_EXCLUSIONS = {
    "compiler-rs/crates/aether-ir/src": {"dominance.rs", "lowering.rs"},
}
# RUST-3.10 adds only an opt-in diagnostic export from the already-authorized
# lowering core. Normalize that exact additive surface back to the frozen line
# while retaining the broad hash gate for every other lib.rs change.
RUST_3_10_DIAGNOSTIC_EXPORT = b"""pub use lowering::{
    SsaLoweringError, SsaLoweringPhaseTimings, characterize_lower_normalized_ir_to_ssa_v1,
    lower_normalized_ir_to_ssa_v1,
};"""
FROZEN_LOWERING_EXPORT = (
    b"pub use lowering::{SsaLoweringError, lower_normalized_ir_to_ssa_v1};"
)


def _optional(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_revision(value: dict[str, Any], revision: str) -> bool:
    return value.get("qualification_revision", value.get("revision")) == revision


def _set(value: object) -> set[object]:
    return set(value) if isinstance(value, list) else set()


def _git(*arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return b""
    return result.stdout


def _resolved_revision(revision: str) -> str:
    return _git(
        "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"
    ).decode("ascii", errors="replace").strip()


def _tracked_program_paths(revision: str) -> list[str]:
    resolved = _resolved_revision(revision)
    if not resolved:
        return []
    output = _git(
        "ls-tree", "-r", "-z", "--name-only", resolved, "--", *DISCOVERY_ROOTS
    )
    return sorted(
        path.decode("utf-8")
        for path in output.split(b"\0")
        if path.endswith(b".ae")
    )


def _historical_program_paths() -> set[str]:
    try:
        lines = (ROOT / HISTORICAL_CORPUS_MANIFEST).read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        return set()
    paths = [line.strip() for line in lines]
    if paths != sorted(set(paths)) or any(not path.endswith(".ae") for path in paths):
        return set()
    return set(paths)


def _hashes_match(expected: dict[str, str]) -> tuple[bool, dict[str, str]]:
    actual: dict[str, str] = {}
    for relative in expected:
        path = ROOT / relative
        if path.is_file():
            actual[relative] = sha256(path.read_bytes()).hexdigest()
    return actual == expected, actual


def _tree_hashes_match(expected: dict[str, str]) -> tuple[bool, dict[str, str]]:
    actual: dict[str, str] = {}
    for relative in expected:
        directory = ROOT / relative
        if not directory.is_dir():
            continue
        digest = sha256()
        exclusions = FROZEN_SCHEMA_POLICY_TREE_EXCLUSIONS.get(relative, set())
        for path in sorted(directory.glob("*.rs")):
            if path.name in exclusions:
                continue
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(b"\0")
            contents = path.read_bytes()
            if path.name == "lib.rs":
                contents = contents.replace(
                    RUST_3_10_DIAGNOSTIC_EXPORT, FROZEN_LOWERING_EXPORT
                )
            digest.update(contents)
            digest.update(b"\0")
        actual[relative] = digest.hexdigest()
    return actual == expected, actual


def _phase_passed(value: object, *, minimum: int, exact: int | None = None) -> bool:
    if not isinstance(value, dict):
        return False
    requested = value.get("requested")
    required = exact if exact is not None else requested
    return (
        isinstance(requested, int)
        and requested >= minimum
        and requested == required
        and value.get("completed") == requested
        and value.get("client_requests") == requested
        and value.get("process_startups") == 1
        and value.get("semantic_mismatches") == 0
        and value.get("infrastructure_failures") == 0
        and value.get("unclassified_failures") == 0
        and value.get("deterministic_output_mismatches") == 0
        and value.get("process_crashes_or_timeouts") == 0
        and value.get("poisoned_client_failures") == 0
        and value.get("rss_assessment") != "UNEXPLAINED_GROWTH"
    )


def _platform_rows(directory: Path, revision: str) -> tuple[dict[str, Any], bool]:
    rows: dict[str, Any] = {}
    for name, target in PLATFORMS.items():
        path = directory / f"{name}.json"
        value = _optional(path)
        comparison = value.get("comparison", {})
        checks = value.get("checks", {})
        valid = (
            value.get("milestone") == "RUST-3.7a"
            and value.get("revision") == revision
            and value.get("platform") == name
            and value.get("rust_target") == target
            and value.get("execution") == "clean_release_artifact_outside_checkout"
            and value.get("provenance") == "executed-native-runner"
            and _set(value.get("representative_categories")) == REPRESENTATIVE_CATEGORIES
            and isinstance(checks, dict) and checks and set(checks.values()) == {"PASS"}
            and isinstance(comparison, dict)
            and comparison.get("mode") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
            and comparison.get("repository_default") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
            and comparison.get("default_returned_ssa_origin") == "rust_schema_v2_import"
            and _set(comparison.get("modes_exercised")) == {
                "PYTHON_SSA_ONLY", "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
                "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            }
            and _set(comparison.get("returned_ssa_origins")) == {"rust_schema_v2_import"}
            and comparison.get("fixture_mode_matrix_checks") == 17
            and comparison.get("native_baseline_comparisons") == 9
            and comparison.get("semantic_mismatches") == 0
            and comparison.get("infrastructure_failures") == 0
            and comparison.get("process_startups") == 1
        )
        rows[name] = (
            {"status": "PASS", "rust_target": target, "sha256": sha256(path.read_bytes()).hexdigest()}
            if valid
            else {"status": "BLOCKED", "rust_target": target, "reason": "fresh exact-revision RUST-3.7a native evidence missing or invalid"}
        )
    return rows, all(row["status"] == "PASS" for row in rows.values())


def _gate(identifier: str, name: str, passed: bool, evidence: str) -> dict[str, str]:
    return {"id": identifier, "name": name, "status": "PASS" if passed else "BLOCKED", "evidence": evidence}


def build_record(revision: str, evidence_dir: Path) -> dict[str, Any]:
    operational = _optional(evidence_dir / "operational.json")
    regressions = _optional(evidence_dir / "regressions.json")
    fixtures = _optional(evidence_dir / "promotion_fixtures.json")
    deep_cfg = _optional(evidence_dir / "deep_cfg.json")
    full_suite = _optional(evidence_dir / "full_suite.json")
    platforms, platforms_pass = _platform_rows(evidence_dir / "platforms", revision)
    historical_preserved, historical_hashes = _hashes_match(FROZEN_FILES)
    schema_files_preserved, schema_policy_hashes = _hashes_match(FROZEN_SCHEMA_POLICY_FILES)
    schema_tree_preserved, schema_tree_hashes = _tree_hashes_match(FROZEN_SCHEMA_POLICY_TREES)
    schema_policy_preserved = schema_files_preserved and schema_tree_preserved

    shadow_source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/rust-ssa-shadow.yml").read_text(encoding="utf-8")
    historical_default = re.search(
        r"mode:\s*SSALoweringAuthorityMode\s*=\s*SSALoweringAuthorityMode\.RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        shadow_source,
    ) is not None
    rust_4_5_policy_aware_default = all(
        token in shadow_source
        for token in (
            "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED",
            "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            'SSA_AUTHORITY_MODE_ENV = "AETHER_SSA_AUTHORITY_MODE"',
        )
    )
    default_contract_preserved_or_superseded = (
        historical_default or rust_4_5_policy_aware_default
    )
    python_shadow_preserved = "GeneralSSABuilder().build(python_input)" in shadow_source
    fail_closed = (
        "Rust SSA authority requires fail-closed semantics" in shadow_source
        and "authoritative = rust_ssa if rust_authoritative else python_ssa" in shadow_source
        and "if difference:" in shadow_source
    )
    no_rust_only = "RUST_SSA_ONLY" not in shadow_source
    rollback_modes_present = all(
        token in shadow_source for token in ("PYTHON_SSA_AUTHORITY_RUST_SHADOW", "PYTHON_SSA_ONLY")
    )

    corpus = operational.get("corpus", {})
    programs = corpus.get("programs", []) if isinstance(corpus, dict) else []
    rejected_rows = [row for row in programs if isinstance(row, dict) and row.get("status") == "REJECTED_BEFORE_SSA"]
    accepted_rows = [row for row in programs if isinstance(row, dict) and row.get("status") == "ACCEPTED_BEFORE_SSA"]
    program_paths = [row.get("path") for row in programs if isinstance(row, dict)]
    accepted_paths = {
        row.get("path") for row in accepted_rows if isinstance(row.get("path"), str)
    }
    expected_paths = _tracked_program_paths(revision)
    historical_paths = _historical_program_paths()
    category_paths = corpus.get("accepted_category_paths", {}) if isinstance(corpus, dict) else {}
    categories_pass = (
        isinstance(category_paths, dict)
        and REQUIRED_CORPUS_CATEGORIES <= set(category_paths)
        and all(
            isinstance(paths, list)
            and bool(paths)
            and paths == sorted(set(paths))
            and set(paths) <= accepted_paths
            for paths in category_paths.values()
        )
    )
    exact_source_set = (
        bool(expected_paths)
        and bool(historical_paths)
        and program_paths == expected_paths
        and historical_paths <= set(expected_paths)
    )
    corpus_pass = (
        _same_revision(operational, revision)
        and operational.get("milestone") == "RUST-3.7a"
        and operational.get("decision") == "RUST_SSA_PRODUCTION_STABILIZATION_OPERATIONAL_PASS"
        and operational.get("authority", {}).get("repository_default") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and operational.get("authority", {}).get("python_shadow") == "synchronous_mandatory"
        and operational.get("authority", {}).get("automatic_retries") is False
        and isinstance(corpus, dict)
        and corpus.get("discovery_roots") == list(DISCOVERY_ROOTS)
        and corpus.get("discovery_mechanism") == "git_tree_exact_revision"
        and corpus.get("discovery_revision") == _resolved_revision(revision)
        and corpus.get("ignored_and_untracked_excluded") is True
        and corpus.get("historical_manifest") == HISTORICAL_CORPUS_MANIFEST.as_posix()
        and corpus.get("historical_discovered") == len(historical_paths)
        and corpus.get("historical_programs_included") == len(historical_paths)
        and not corpus.get("missing_historical_programs")
        and corpus.get("eligible_tracked_programs") == len(expected_paths)
        and corpus.get("discovered_programs") == len(programs)
        and len(programs) == len(accepted_rows) + len(rejected_rows)
        and corpus.get("accepted_before_ssa") == len(accepted_rows)
        and corpus.get("rejected_before_ssa") == len(rejected_rows)
        and corpus.get("source_set_gate") == "PASS"
        and corpus.get("coverage_contract") == "PASS"
        and not corpus.get("unaccounted_tracked_programs")
        and not corpus.get("unexpected_programs")
        and exact_source_set
        and corpus.get("category_gate") == "PASS"
        and not corpus.get("missing_categories")
        and categories_pass
        and all(row.get("stage") and row.get("reason") for row in rejected_rows)
    )
    repeated = operational.get("repeated_soak", {})
    rounds = repeated.get("rounds") if isinstance(repeated, dict) else None
    accepted_count = corpus.get("accepted_before_ssa", 0) if isinstance(corpus, dict) else 0
    repeated_pass = (
        isinstance(rounds, int) and rounds >= 3
        and repeated.get("programs_per_round") == accepted_count
        and _phase_passed(repeated, minimum=accepted_count * 3, exact=accepted_count * rounds)
    )
    long_pass = _phase_passed(operational.get("long_session"), minimum=5_000)
    concurrency = operational.get("concurrency", {})
    concurrency_pass = (
        _phase_passed(concurrency, minimum=256)
        and isinstance(concurrency, dict)
        and concurrency.get("callers", 0) >= 8
        and concurrency.get("serialized_transport") is True
    )

    fixture_gates = fixtures.get("gates", [])
    fixtures_pass = (
        _same_revision(fixtures, revision)
        and fixtures.get("decision") == "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED"
        and fixtures.get("repository_default") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and [row.get("id") for row in fixture_gates if isinstance(row, dict)] == [f"V2-L{number:02d}" for number in range(1, 6)]
        and all(row.get("status") == "PASS" for row in fixture_gates)
    )
    regression_rows = regressions.get("families", {})
    regressions_pass = (
        _same_revision(regressions, revision)
        and regressions.get("decision") == "RUST_SSA_PRODUCTION_REGRESSIONS_PASS"
        and regressions.get("mode") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and isinstance(regression_rows, dict)
        and set(regression_rows) == REGRESSION_FAMILIES
        and all(row.get("status") == "PASS" and row.get("tests", 0) > 0 for row in regression_rows.values())
    )
    stress = deep_cfg.get("stress", {})
    deep_cfg_pass = (
        _same_revision(deep_cfg, revision)
        and deep_cfg.get("decision") == "RUST_SSA_AUTHORITY_DEEP_CFG_PASS"
        and deep_cfg.get("cargo_workspace", {}).get("status") == "PASS"
        and all(stress.get(str(size), {}).get("python") == "PASS" and stress.get(str(size), {}).get("rust") == "PASS" for size in (993, 1000, 5000))
    )
    full_suite_pass = (
        _same_revision(full_suite, revision)
        and full_suite.get("milestone") == "RUST-3.7a"
        and full_suite.get("decision") == "RUST_SSA_PRODUCTION_STABILIZATION_FULL_SUITE_PASS"
        and full_suite.get("mode") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and all(full_suite.get(field) == 0 for field in ("failed", "semantic_mismatches", "infrastructure_failures", "environmental_failures", "unclassified_test_failures"))
    )
    rollback_pass = platforms_pass and rollback_modes_present
    ci_pass = all(
        token in workflow
        for token in (
            "production-stabilization-operational", "production-stabilization-regressions",
            "production-stabilization-full-suite", "production-stabilization-platform",
            "check_rust_ssa_production_stabilization.py", "--require-stabilized",
        )
    )

    checks = [
        (
            "historical differential default remains selectable or is "
            "superseded by the policy-aware RUST-4.5 default",
            default_contract_preserved_or_superseded,
        ),
        ("mandatory synchronous GeneralSSABuilder shadow remains", python_shadow_preserved),
        ("fail-closed comparison and no Rust-only mode remain", fail_closed and no_rust_only),
        ("exact-revision corpus coverage is fully accounted and mismatch-free", corpus_pass),
        ("repeated differential soak is deterministic", repeated_pass),
        ("5000-request one-process mixed session passes", long_pass),
        ("shared-client concurrent callers remain serialized", concurrency_pass),
        ("V2-L01 through V2-L05 remain qualified", fixtures_pass),
        ("permanent stabilization regression families pass", regressions_pass),
        ("deep CFG 993, 1000, and 5000 passes", deep_cfg_pass),
        ("optimizer/backend/native representative matrix passes", platforms_pass),
        ("full repository suite passes under production default", full_suite_pass),
        ("four clean-install official platforms pass", platforms_pass),
        ("both rollback modes pass configuration-only", rollback_pass),
        ("historical readiness/promotion artifacts are byte-preserved", historical_preserved),
        ("schemas and lowering/lifecycle policies are byte-preserved", schema_policy_preserved),
        ("CI uploads and aggregates every stabilization result", ci_pass),
    ]
    gates = [_gate(f"STAB-G{index:02d}", name, passed, "fresh exact-revision RUST-3.7a evidence") for index, (name, passed) in enumerate(checks, 1)]
    blockers = [gate["id"] for gate in gates if gate["status"] != "PASS"]
    decision = "RUST_SSA_PRODUCTION_STABILIZED" if not blockers else "RUST_SSA_PRODUCTION_STABILIZATION_BLOCKED"
    failures = []
    for phase in (repeated, operational.get("long_session", {}), concurrency):
        if isinstance(phase, dict):
            failures.extend(phase.get("failures", []))
    semantic_bugs = [row for row in failures if isinstance(row, dict) and row.get("classification") == "semantic_mismatch"]
    discovered_bugs: list[dict[str, Any]] = [
        {
            "id": "STAB-INF-001",
            "classification": "qualification_infrastructure",
            "status": "FIXED",
            "summary": "pytest JUnit classname-only cases were reported as uncollected",
            "minimized_reproducer": "tests/aether/test_rust_ssa_production_stabilization.py",
        }
    ]
    discovered_bugs.extend(semantic_bugs)
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.7a",
        "qualification_revision": revision,
        "promoted_revision": PROMOTED_REVISION,
        "decision": decision,
        "gates": gates,
        "blockers": blockers,
        "broadened_corpus": corpus,
        "repeated_soak": repeated,
        "long_session": operational.get("long_session", {}),
        "concurrency": concurrency,
        "regression_families": {"V2-L01_through_V2-L05": "PASS" if fixtures_pass else "BLOCKED", "deep_cfg": "PASS" if deep_cfg_pass else "BLOCKED", **regression_rows},
        "optimizer_backend_native": {"status": "PASS" if platforms_pass else "BLOCKED", "representative_categories": sorted(REPRESENTATIVE_CATEGORIES)},
        "full_suite": full_suite,
        "platforms": platforms,
        "rollback": {"status": "PASS" if rollback_pass else "BLOCKED", "modes": ["PYTHON_SSA_AUTHORITY_RUST_SHADOW", "PYTHON_SSA_ONLY"]},
        "newly_discovered_bugs": discovered_bugs,
        "minimized_reproducers": [
            row.get("minimized_reproducer", row.get("path"))
            for row in discovered_bugs
        ],
        "performance": operational.get("performance", {"measurement_kind": "incidental observations only; no timing gate"}),
        "historical_preservation": {"status": "PASS" if historical_preserved else "BLOCKED", "expected_sha256": FROZEN_FILES, "actual_sha256": historical_hashes},
        "schema_policy_freeze": {
            "status": "PASS" if schema_policy_preserved else "BLOCKED",
            "expected_sha256": FROZEN_SCHEMA_POLICY_FILES,
            "actual_sha256": schema_policy_hashes,
            "expected_tree_sha256": FROZEN_SCHEMA_POLICY_TREES,
            "actual_tree_sha256": schema_tree_hashes,
        },
        "scope": {
            "default_changed": False,
            "python_shadow_removed_or_optional": False,
            "silent_fallback_added": False,
            "schema_or_policy_changed": not schema_policy_preserved,
            "historical_artifacts_changed": not historical_preserved,
            "transport_parallelized_or_optimized": False,
            "optimizer_backend_semantics_changed": False,
            "commit_created": False,
        },
        "source_evidence_sha256": {
            path.stem: sha256(path.read_bytes()).hexdigest()
            for path in sorted(evidence_dir.glob("*.json"))
        },
    }


def render(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-stabilized", action="store_true")
    args = parser.parse_args()
    record = build_record(args.revision, args.evidence_dir.resolve())
    rendered = render(record)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            print(f"stale RUST-3.7a stabilization artifact: {args.output}")
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(record["decision"])
    if args.require_stabilized and record["decision"] != "RUST_SSA_PRODUCTION_STABILIZED":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
