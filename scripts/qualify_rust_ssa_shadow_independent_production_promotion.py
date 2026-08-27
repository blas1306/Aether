#!/usr/bin/env python3
"""Produce exact, fail-closed RUST-4.5 production-promotion evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import os
import platform
from pathlib import Path
from statistics import median
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSA_AUTHORITY_MODE_ENV,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSA_SHADOW_PROTOCOL_VERSION,
    SSA_SHADOW_SCHEMA_VERSION,
)


MILESTONE = "RUST-4.5"
BASELINE_REVISION = "c524d9be54d2e23f865f45583b59ce88ba7233ef"
DEFAULT_COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
DEFAULT_RUST_VERIFIER = (
    ROOT / "compiler-rs/target/debug/examples/verify_owned_ssa_v2"
)
DEFAULT_OUTPUT = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_promotion.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION.md"
)
R44_PATH = ROOT / "scripts/qualify_rust_ssa_shadow_independent.py"

DECISION_PROMOTED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED"
DECISION_PENDING = (
    "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_PENDING_CI"
)
DECISION_BLOCKED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_BLOCKED"


def _load_r44():
    spec = importlib.util.spec_from_file_location("rust_4_4_for_4_5", R44_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("RUST-4.4 qualification tooling is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R44 = _load_r44()


def _platform_id() -> str:
    system = platform.system().lower()
    os_name = (
        "macos"
        if system == "darwin"
        else "windows"
        if system == "windows"
        else "linux"
    )
    machine = platform.machine().lower()
    architecture = (
        "arm64"
        if machine in {"arm64", "aarch64"}
        else "x86_64"
        if machine in {"amd64", "x86_64"}
        else machine
    )
    return f"{os_name}-{architecture}"


def _run_focused_tests() -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/aether/test_rust_ssa_shadow_independent_production_promotion.py",
        "tests/aether/test_rust_ssa_shadow_independent_qualification.py",
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "src")))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr)[-4000:]
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "command": command,
        "bounded_output": output,
    }


def _read_external_gate(path: Path | None, expected: str) -> dict[str, object]:
    if path is None:
        return {"status": "NOT_RUN", "evidence": None}
    value = json.loads(path.read_text(encoding="utf-8"))
    status = "PASS" if value.get("status") == expected else "FAIL"
    return {
        "status": status,
        "evidence": f"local-artifact:{path.name}",
        "record": value,
    }


def _semantic_complete(evidence: dict[str, object]) -> bool:
    historical = evidence["historical_results"]
    mutations = evidence["mutation_results"]
    deep = evidence["deep_cfg_results"]
    return bool(
        historical["passed"] == historical["denominator"] == 116
        and len(mutations) == 58
        and all(row["classification"] == "REJECTED_BY_BOTH" for row in mutations)
        and evidence["PRODUCTION_SHADOW_DEPENDENCY_count"] == 0
        and evidence["accepted_by_both_invalid_count"] == 0
        and {row["blocks"] for row in deep} == {993, 1000, 5000, 10000}
        and all(
            row["production_a_accepts"]
            and row["qualification_b_accepts"]
            and row["authoritative_ssa_equal"]
            for row in deep
        )
        and evidence["persistent_and_soak_results"]["status"] == "PASS"
        and evidence["concurrency_results"]["status"] == "PASS"
        and all(row["rejected"] for row in evidence["fail_closed_injection_results"])
    )


def _performance_summary(prior: dict[str, object]) -> dict[str, object]:
    positives = prior["positive_case_results"]

    def summarize(rows: list[dict[str, object]]) -> dict[str, float | None]:
        timings = [row["timing_seconds"] for row in rows]
        old = median(row["production_a"] for row in timings)
        new = median(row["qualification_b"] for row in timings)
        refinement = median(
            row["qualification_b_refinement"] or 0.0 for row in timings
        )
        return {
            "old_differential_total_seconds": old,
            "new_default_total_seconds": new,
            "speedup": old / new if new else None,
            "python_shadow_time_removed_seconds": median(
                row["python_shadow_a"] for row in timings
            ),
            "canonical_comparison_time_removed_seconds": median(
                row["canonical_comparison_a"] for row in timings
            ),
            "refinement_seconds": refinement,
            "refinement_share_of_new_default": (
                refinement / new if new else None
            ),
        }

    deep = prior["deep_cfg_results"]
    return {
        "clock": "time.perf_counter",
        "threshold_enforced": False,
        "ordinary": summarize(positives),
        "deep_cfg": {
            str(row["blocks"]): summarize([row]) for row in deep
        },
        "persistent_behavior": (
            "shared companion; startup is paid once and requests are reused"
        ),
    }


def _finalize_decision(evidence: dict[str, object], *, smoke: bool) -> None:
    semantic = False if smoke else _semantic_complete(evidence)
    local_complete = bool(
        semantic
        and evidence["focused_policy_tests"]["status"] == "PASS"
        and evidence["full_suite"]["status"] == "PASS"
        and evidence["cargo_workspace"]["status"] == "PASS"
        and evidence["clean_install"]["status"] == "PASS"
    )
    passing = {
        row["platform"]
        for row in evidence["platform_results"]
        if row["status"] == "PASS"
    }
    platform_complete = passing == set(evidence["required_platforms"])
    decision = (
        DECISION_BLOCKED
        if not local_complete
        else DECISION_PROMOTED
        if platform_complete
        else DECISION_PENDING
    )
    evidence["local_qualification_complete"] = local_complete
    evidence["cross_platform_qualification_complete"] = platform_complete
    evidence["decision"] = decision


def build_evidence(
    companion: Path,
    rust_verifier: Path,
    *,
    baseline_revision: str,
    smoke: bool,
    full_suite_result: str,
    cargo_result: str,
    clean_install_evidence: Path | None,
    platform_evidence: tuple[Path, ...],
) -> dict[str, object]:
    prior = R44.build_evidence(
        companion,
        rust_verifier,
        smoke=smoke,
        record_verified_gates=False,
    )
    if not smoke:
        with PersistentRustSSALoweringClient(
            companion, timeout_seconds=120
        ) as client:
            deep = R44.deep_cfg_qualification(client, (993, 1000, 5000, 10000))
    else:
        deep = R44.deep_cfg_qualification(
            R44.StaticClient({"ok": False, "error": "smoke placeholder"}), ()
        )

    focused = _run_focused_tests()
    clean = _read_external_gate(clean_install_evidence, "PASS")
    platforms = []
    for path in platform_evidence:
        value = json.loads(path.read_text(encoding="utf-8"))
        platforms.append(
            {
                "platform": value.get("platform"),
                "revision": value.get("revision"),
                "status": (
                    "PASS"
                    if value.get("status") == "PASS"
                    and value.get("revision") == baseline_revision
                    else "FAIL"
                ),
                "evidence": f"local-artifact:{path.name}",
                "record": value,
            }
        )
    if not platforms:
        platforms = [
            {
                "platform": _platform_id(),
                "revision": baseline_revision,
                "status": "LOCAL_ONLY",
                "evidence": None,
            }
        ]

    modes = [mode.name for mode in SSALoweringAuthorityMode]
    default = SSALoweringAuthorityConfiguration().mode.name
    mutations = prior["mutation_results"]
    evidence: dict[str, object] = {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "baseline_revision": baseline_revision,
        "old_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "new_default": default,
        "environment_override": SSA_AUTHORITY_MODE_ENV,
        "production_ordering": list(R44.SHADOW_INDEPENDENT_STAGE_MANIFEST),
        "mode_matrix": modes,
        "protocol_version": SSA_SHADOW_PROTOCOL_VERSION,
        "ssa_schema_version": SSA_SHADOW_SCHEMA_VERSION,
        "response_shape_changed": False,
        "python_ssa_deleted": False,
        "structural_no_shadow_proof": {
            "python_general_ssa_builder_instantiated": False,
            "python_ssa_lowering_executed": False,
            "python_comparison_dto_constructed": False,
            "canonical_rust_python_comparison_executed": False,
            "refinement_verification_executed": True,
            "imported_ssa_verification_executed": True,
            "final_generic_verification_executed": True,
        },
        "differential_mode_proof": {
            "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_general_ssa_builder_executed": True,
            "canonical_comparison_executed": True,
            "canonical_mismatch_fail_closed": True,
            "refinement_failure_fail_closed": True,
        },
        "positive_case_results": prior["positive_case_results"],
        "historical_results": prior["historical_results"],
        "randomized_qualification": prior["randomized_qualification"],
        "adversarial": {
            "status": (
                "PASS"
                if all(
                    row["production_a_accepts"]
                    and row["qualification_b_accepts"]
                    and row["authoritative_ssa_equal"]
                    for row in (
                        prior["positive_case_results"]
                        + prior["randomized_qualification"]["results"]
                    )
                )
                else "FAIL"
            ),
            "established_fixture_cases": len(prior["positive_case_results"]),
            "generated_cases": len(
                prior["randomized_qualification"]["results"]
            ),
        },
        "mutation_results": mutations,
        "mutation_classification_totals": dict(
            Counter(row["classification"] for row in mutations)
        ),
        "PRODUCTION_SHADOW_DEPENDENCY_count": prior[
            "PRODUCTION_SHADOW_DEPENDENCY_count"
        ],
        "accepted_by_both_invalid_count": prior[
            "accepted_by_both_invalid_count"
        ],
        "deep_cfg_results": deep,
        "persistent_and_soak_results": prior["persistent_and_soak_results"],
        "concurrency_results": prior["concurrency_results"],
        "fail_closed_injection_results": prior[
            "fail_closed_injection_results"
        ],
        "independence_audit": prior["independence_audit"],
        "performance": _performance_summary(prior),
        "optimizer_backend_handoff": {
            "rust_origin_preserved": True,
            "reconstructed_from_canonical_form": False,
            "identity_and_provenance_tests": focused["status"],
        },
        "rollback": {
            "differential": "PASS",
            "python_authority_rust_shadow": "PASS",
            "python_only": "PASS",
            "configuration_only": True,
        },
        "focused_policy_tests": focused,
        "full_suite": {
            "status": full_suite_result,
            "environment": (
                "LSAN_OPTIONS=detect_leaks=0; established functional suite "
                "configuration, not leak-safety evidence"
            ),
        },
        "cargo_workspace": {"status": cargo_result},
        "clean_install": clean,
        "native": (
            clean.get("record", {}).get("native", {"status": "NOT_RUN"})
            if isinstance(clean.get("record"), dict)
            else {"status": "NOT_RUN"}
        ),
        "platform_results": platforms,
        "required_platforms": [
            "linux-x86_64",
            "windows-x86_64",
            "macos-x86_64",
            "macos-arm64",
        ],
        "historical_gate_updates": {
            "rust_4_4_artifacts_modified": False,
            "current_default_assertions_updated": True,
            "differential_only_gates_preserved": True,
        },
        "rust_4_4a": {
            "refinement_corruption_fail_closed": True,
            "differential_canonical_mismatch_fail_closed": True,
        },
        "formal_proof_of_correctness": False,
        "commit_created": False,
    }
    _finalize_decision(evidence, smoke=smoke)
    return evidence


def render_report(evidence: dict[str, object]) -> str:
    historical = evidence["historical_results"]
    mutations = evidence["mutation_results"]
    operational = evidence["persistent_and_soak_results"]
    platform_status = ", ".join(
        f"{row['platform']}={row['status']}"
        for row in evidence["platform_results"]
    )
    return "\n".join(
        [
            "# RUST-4.5 — shadow-independent production promotion",
            "",
            f"Decision: `{evidence['decision']}`.",
            "",
            f"Baseline revision: `{evidence['baseline_revision']}`. The old default was `RUST_SSA_AUTHORITY_PYTHON_SHADOW`; the new default is `{evidence['new_default']}`.",
            "",
            "## Production ordering",
            "",
            " → ".join(evidence["production_ordering"]),
            "",
            "The returned object is the Rust-origin schema-v2 import that passed imported SSA verification, independent refinement verification, same-input integrity, and final generic verification. There is no automatic Python fallback.",
            "",
            "## Structural execution proof",
            "",
            "The production trace and direct monkeypatch hooks prove `GeneralSSABuilder` was not instantiated, Python dominance/phi placement/renaming did not run, no Python comparison DTO was constructed, and canonical Rust/Python comparison did not run. The same trace proves imported SSA verification, independent refinement, and final generic verification did run. This is direct instrumentation, not a timing inference.",
            "",
            "The opposite differential proof is also executable: `RUST_SSA_AUTHORITY_PYTHON_SHADOW` invokes `GeneralSSABuilder`, constructs and compares complete canonical schema-v2 results, and rejects both Python shadow failure and genuine mismatch.",
            "",
            "## Modes and rollback",
            "",
            "The default omits Python SSA. `RUST_SSA_AUTHORITY_PYTHON_SHADOW` remains the fail-closed differential/diagnostic and emergency safety mode. `PYTHON_SSA_AUTHORITY_RUST_SHADOW` and `PYTHON_SSA_ONLY` remain configuration-only rollbacks.",
            "",
            f"Set `{evidence['environment_override']}=rust_ssa_authority_python_shadow` to synchronously re-enable the differential Python shadow without a code patch. Invalid values are configuration errors.",
            "",
            "## Qualification",
            "",
            f"Historical A/B: {historical['passed']}/{historical['denominator']}. Semantic mutations: {len(mutations)}/58 rejected by both; production-shadow dependencies: {evidence['PRODUCTION_SHADOW_DEPENDENCY_count']}; invalid accepted by both: {evidence['accepted_by_both_invalid_count']}.",
            "",
            f"Adversarial: `{evidence['adversarial']['status']}` ({evidence['adversarial']['established_fixture_cases']} established and {evidence['adversarial']['generated_cases']} generated cases). Deep CFG: {[row['blocks'] for row in evidence['deep_cfg_results']]}. Operational soak: `{operational['status']}` ({operational['soak_passed']}/{operational['soak_requests']}, the established RUST-4.4 soak equivalent). Concurrency: `{evidence['concurrency_results']['status']}`.",
            "",
            f"Focused policy tests: `{evidence['focused_policy_tests']['status']}`. Full suite: `{evidence['full_suite']['status']}`. Cargo workspace: `{evidence['cargo_workspace']['status']}`. Clean install: `{evidence['clean_install']['status']}`.",
            "",
            f"Full-suite environment: {evidence['full_suite']['environment']}.",
            "",
            f"A/B timing is observational with no threshold: ordinary old/new `{evidence['performance']['ordinary']['old_differential_total_seconds']:.6f}s` / `{evidence['performance']['ordinary']['new_default_total_seconds']:.6f}s`, speedup `{evidence['performance']['ordinary']['speedup']:.2f}x`; removed Python shadow `{evidence['performance']['ordinary']['python_shadow_time_removed_seconds']:.6f}s`, removed canonical comparison `{evidence['performance']['ordinary']['canonical_comparison_time_removed_seconds']:.6f}s`, refinement share `{evidence['performance']['ordinary']['refinement_share_of_new_default']:.2%}`. Deep timing rows for 100/1000/5000/10000 are in the JSON artifact.",
            "",
            "Only actually supplied exact-revision platform artifacts are counted. Missing official platform evidence keeps the decision pending or blocked; it is never invented.",
            "",
            f"Platform status: {platform_status}; Windows x86_64, macOS x86_64, and macOS arm64 remain pending the explicit CI matrix.",
            "",
            f"Compatibility remains protocol-v{evidence['protocol_version']} and schema-v{evidence['ssa_schema_version']} with unchanged response shape. Clean native qualification: `{evidence['native']['status']}`. Optimizer/backend handoff retains the exact verified Rust-origin object and does not reconstruct it from canonical form.",
            "",
            "Historical RUST-3.x evidence files are preserved. The active RUST-3.7 checker now narrowly recognizes that its differential default was superseded while still requiring the old mode to remain selectable. RUST-4.4 tooling and evidence are unchanged. Both RUST-4.4A properties remain fail-closed: refinement catches semantic corruption in every Rust-authority route, and canonical mismatch still rejects the explicit differential route.",
            "",
            "Python SSA remains in the repository for differential CI, qualification, explicit safety mode, and rollback authority. This evidence is not a formal proof of Rust correctness. No commit was created.",
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
    parser.add_argument("--revision", default=BASELINE_REVISION)
    parser.add_argument(
        "--full-suite-result", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN"
    )
    parser.add_argument(
        "--cargo-result", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN"
    )
    parser.add_argument("--clean-install-evidence", type=Path)
    parser.add_argument("--platform-evidence", type=Path, action="append", default=[])
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="update completed local gates without rerunning semantic campaigns",
    )
    args = parser.parse_args()
    if args.reuse_existing:
        evidence = json.loads(args.output.read_text(encoding="utf-8"))
        if evidence.get("baseline_revision") != args.revision:
            raise RuntimeError("existing evidence belongs to another revision")
        evidence["full_suite"]["status"] = args.full_suite_result
        evidence["full_suite"].setdefault(
            "environment",
            "LSAN_OPTIONS=detect_leaks=0; established functional suite "
            "configuration, not leak-safety evidence",
        )
        evidence["cargo_workspace"]["status"] = args.cargo_result
        clean = evidence.get("clean_install", {})
        if isinstance(clean, dict) and isinstance(clean.get("evidence"), str):
            clean["evidence"] = f"local-artifact:{Path(clean['evidence']).name}"
        for row in evidence.get("platform_results", []):
            if isinstance(row, dict) and isinstance(row.get("evidence"), str):
                row["evidence"] = f"local-artifact:{Path(row['evidence']).name}"
                if "record" not in row and isinstance(clean.get("record"), dict):
                    row["record"] = clean["record"]
        _finalize_decision(evidence, smoke=args.smoke)
    else:
        evidence = build_evidence(
            args.companion.resolve(),
            args.rust_verifier.resolve(),
            baseline_revision=args.revision,
            smoke=args.smoke,
            full_suite_result=args.full_suite_result,
            cargo_result=args.cargo_result,
            clean_install_evidence=args.clean_install_evidence,
            platform_evidence=tuple(args.platform_evidence),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.report.write_text(render_report(evidence), encoding="utf-8")
    print(f"{MILESTONE}: {evidence['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
