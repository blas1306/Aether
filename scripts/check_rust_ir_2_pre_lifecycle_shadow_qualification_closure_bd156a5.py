#!/usr/bin/env python3
"""Fail-closed checker for the official RUST-IR-2 closure at bd156a5."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ir_2_pre_lifecycle_shadow_qualification_closure_bd156a5.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_IR_2_PRE_LIFECYCLE_SHADOW_QUALIFICATION_CLOSURE_BD156A5.md"
DEFAULT_WORKFLOW = ROOT / ".github/workflows/rust-ir-pre-lifecycle-shadow-qualification.yml"

RUN_ID = 33465504645
REVISION = "bd156a52757721fba552231fa88ac7083b715b6d"
RUST_IR_1_REVISION = "b563054f5f94ab373089f4d9dd9ae7629f242a59"
QUALIFIED = "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFIED"
BLOCKED = "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFICATION_BLOCKED"
WORKFLOW_SHA256 = "18d4d1a427dee73a5884927b9652b3300cd553943ac0c1aaa716ecfbd494ff94"
MANIFEST_SHA256 = "3984605a7a81377e74012a17717b0c1a82f17f27ee800b7ee5dfec02cd1a1b77"
DECISION_SHA256 = "458cc9f371ee470c414eafc94b911308282fdf6a4488280e8300e3a9ff218f7a"
QUALIFICATION_CHECKER_SHA256 = "80b5e45efb269e552c1d821cf77ebb0dec8102ee5e6cac59636095ca8397ba32"

EXPECTED_JOBS = {
    "production-pre-lifecycle-provenance": 99724395171,
    "critical-irv041-regressions": 99724395302,
    "next-request-recovery": 99724395317,
    "rust-verifier-unit": 99724395355,
    "mutation-campaign": 99724395409,
    "contract-and-baseline": 99724395412,
    "source-development-install": 99724395422,
    "python-3.14": 99724395430,
    "performance-characterization": 99724395452,
    "platform-windows-x86_64": 99724395466,
    "lifecycle-boundary-regression": 99724395473,
    "valid-corpus-differential": 99724395495,
    "packaged-clean-consumer": 99724395499,
    "python-3.13": 99724395506,
    "platform-linux-x86_64": 99724395508,
    "platform-macos-arm64": 99724395515,
    "transport-continuity": 99724395524,
    "python-3.12": 99724395533,
    "platform-macos-x86_64": 99724395545,
    "python-3.11": 99724395586,
    "aggregate-fail-closed": 99726011145,
}

# artifact id, source job, archive SHA-256, evidence file, evidence SHA-256
EXPECTED_ARTIFACTS = {
    "rust-ir-2-contract": (9784685066, "contract-and-baseline", "1bb2ff8861cc609876c158d8f20ad59fc3feefb64e9f9f6e614aeafdcd308e20", "contract.json", "aa1e4cc144506616777e94abe5a3b54ab1da24d41f8222116e158fe94dc61191"),
    "rust-ir-2-rust-validation": (9784723914, "rust-verifier-unit", "1c62a60be33b704a99ce3e2223f52c55b7827af77d7319027eebe249b0969342", "rust-validation.json", "6b4543dc65f22da29d054f0394d781206fc246054a1e28477f36fdf323ad8c39"),
    "rust-ir-2-valid-corpus": (9784747561, "valid-corpus-differential", "0fb632b02a8ff41e2d083b0e708e3efb46d2e0868cd4fb8a46ed2316ae6b09ba", "valid-corpus.json", "b0df6fb4b075523f77355903e73d0c2d8b4f03ec3e77f5d4c22987cdcfa9df67"),
    "rust-ir-2-mutations": (9784744946, "mutation-campaign", "60611eb90fc9d928902e477fb8a99cd40bcdadd12251f2d38c090ded216f5192", "mutations.json", "98b25c38a236a841aa245636b427126f1346a682862293dd6df231565e1a0d3a"),
    "rust-ir-2-irv041": (9784700749, "critical-irv041-regressions", "650251cf83d4bd2c058c735b19a02722898b3c6de0347f9c669c51a966c64197", "irv041.json", "3df92ff88d6b55e0166fbd3bd3d914b4973ad6c3d7fd0528ff5672cd4dee8b8e"),
    "rust-ir-2-provenance": (9784732096, "production-pre-lifecycle-provenance", "59d4390b606016f9490f8ca547e9c96ac99a1b5f89e30e320153c302be37a7fd", "provenance.json", "da883010c5693ca0150c2694397e2ecf9f71dba09e2e0c480f4498ba5c550c85"),
    "rust-ir-2-lifecycle-boundary": (9784742405, "lifecycle-boundary-regression", "8d056170cd5c649877549a69c02bedea34aa9b73cad726c7b4efee7d5d2d7bd1", "lifecycle-boundary.json", "ae017eead1e9d046b62e81c4ad1d7d668d334e8ae5b74aeddd906368ebf63753"),
    "rust-ir-2-packaged-consumer": (9784740884, "packaged-clean-consumer", "d7f7910d1da1b28eef51a98a838d0f60947603abb9b6c4e4c80c92198da8d8f3", "packaged.json", "3f8750ba53e4c76d7f122214b5d960a6d762023623b2decbb325136f1ed373f5"),
    "rust-ir-2-source-install": (9784827518, "source-development-install", "1438e8bbc7ecb70ad5c5f2b4c88cdc1526843a34e9e8941463acb1fc4cf06208", "source.json", "07ed79ff463aa2c581ba01506121b4ae9557000909d223143af793ce15ded208"),
    "rust-ir-2-recovery": (9784740654, "next-request-recovery", "a79be026f360a00a570704337abf4a2c93cbbee8fb77a549a05a93dabdd2a4cb", "recovery.json", "f241d4294c2314bd69e1a72c2a8d4211dddaebf0867e5fe9de5a3d08014fb581"),
    "rust-ir-2-transport": (9784741855, "transport-continuity", "bb66957da35e09c1a9be02381ddb0a345c05508d19fec1d2214a9f9f5f59dc40", "transport.json", "0ab7ddfe1fe7cc5739dd8e084fc8c21bea0dc99a37c285d21f662c9b6b5c7830"),
    "rust-ir-2-performance": (9784703136, "performance-characterization", "a79b4269c5ddfb40523b4e842265d04a7e0fa50bfea3d67a5e09412d301e4671", "performance.json", "8f54aa0086297fb8f72f225cdb5abce96b668f0e3f926da5a44ad87f23474f65"),
    "rust-ir-2-platform-linux-x86_64": (9784741409, "platform-qualification", "fd725bc91cea5814d4edefe6dbf2e41a0f0aadbaf15e3fe4da38b60edbfdb715", "platform-linux-x86_64.json", "6eaaf1855f4172f94f3f48f7b93adcdd2219f986a9cdeebeb30d8ca3161c877d"),
    "rust-ir-2-platform-windows-x86_64": (9784803370, "platform-qualification", "1e8cfd66f9dfb13f28239fcdf0eaa00721fd9d078c58be6254c309549e297645", "platform-windows-x86_64.json", "e644c88a4fe1b2f87755058fc161857425290d5f2da0eec2c0e4775abe2d1b7e"),
    "rust-ir-2-platform-macos-x86_64": (9784867564, "platform-qualification", "42b8c67458b6da8aa8be447d99c7d17c5ad18847948e1460ab347f9cb24aced2", "platform-macos-x86_64.json", "833d40ee60a8ce1c6bef01b82ef9577b49591c7fca35310f0fedc8bd7396ba51"),
    "rust-ir-2-platform-macos-arm64": (9784762193, "platform-qualification", "ae42eb5aa2df75d680c0ca7e572f30a297bf319fee451b62f0f3e3e55871ff5f", "platform-macos-arm64.json", "e96e95e903023fe48bcc163e03168dd2f6b87120dd62fb54146c8dd229c8ae11"),
    "rust-ir-2-python-3.11": (9784740416, "python-compatibility", "cd9639aa7853d720826d299dd938ca1948a4dbb59c1d2bcf1ba4eeb65820b333", "python-3.11.json", "000ae06ee9a91c7173d176c09d721ee27a6dda3f57c5b48da647ab751031c5ab"),
    "rust-ir-2-python-3.12": (9784743563, "python-compatibility", "55b362ff5ae61fca37dadf93ecbf2e575ec04c61f414474669c0e13398fe6b4d", "python-3.12.json", "a8894f3b9f58cb4c4b8ebe81612d7dc8eb0cc79d0beee1844132c9681462727f"),
    "rust-ir-2-python-3.13": (9784743587, "python-compatibility", "d007665e3073d962879a545ab76294a7d7bc26441ef98446d5470714cd33c0e0", "python-3.13.json", "a4a1bc03672cada5f6f69a8d011281fadc547a68a6a4010330e99eb7c485b86a"),
    "rust-ir-2-python-3.14": (9784744078, "python-compatibility", "1f2e9a73c2b9e10565dfe7e8453d67cafa0c6e7fe9f73baa3f354ffb13c68dd2", "python-3.14.json", "38f87eabc5ae9b99a4e013570e3a1198166ff8f66eccd64d7298910e96698df8"),
}

EXPECTED_HISTORICAL_RUNS = [
    (33462871203, "630ff5fdbd2ee21a67f0018c9392e8d4d9330e8b"),
    (33464649897, "1acc48bae5aa8ed5366c1647613b48929caddcff"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("closure evidence must be a JSON object")
    return value


def _all_true(value: object) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _check_jobs(evidence: dict[str, object]) -> bool:
    rows = evidence.get("run_jobs")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_JOBS):
        return False
    actual = {
        str(row.get("name")): (row.get("id"), row.get("conclusion"))
        for row in rows
        if isinstance(row, dict)
    }
    return actual == {name: (job_id, "success") for name, job_id in EXPECTED_JOBS.items()}


def _check_artifacts(evidence: dict[str, object]) -> bool:
    rows = evidence.get("artifact_manifest")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_ARTIFACTS):
        return False
    actual = {str(row.get("name")): row for row in rows if isinstance(row, dict)}
    if set(actual) != set(EXPECTED_ARTIFACTS):
        return False
    for name, (artifact_id, job, archive_hash, file_name, evidence_hash) in EXPECTED_ARTIFACTS.items():
        row = actual[name]
        if not (
            row.get("id") == artifact_id
            and row.get("source_job") == job
            and row.get("github_digest_sha256") == archive_hash
            and row.get("downloaded_zip_sha256") == archive_hash
            and row.get("evidence_file") == file_name
            and row.get("evidence_sha256") == evidence_hash
            and row.get("status") == "PASS"
        ):
            return False
    return True


def _check_aggregate(evidence: dict[str, object]) -> bool:
    row = evidence.get("official_aggregate")
    return isinstance(row, dict) and row == {
        "artifact_name": "rust-ir-2-aggregate",
        "artifact_id": 9784875877,
        "source_job": "aggregate-fail-closed",
        "source_job_id": 99726011145,
        "github_digest_sha256": "3cb149b90d3a657e09136cd2e17ff817f3e4db616b311ba80be237e10709c281",
        "downloaded_zip_sha256": "3cb149b90d3a657e09136cd2e17ff817f3e4db616b311ba80be237e10709c281",
        "manifest_sha256": MANIFEST_SHA256,
        "decision_sha256": DECISION_SHA256,
        "checker_sha256": QUALIFICATION_CHECKER_SHA256,
        "decision": QUALIFIED,
        "local_replay": "PASS",
    }


def _check_independent(evidence: dict[str, object]) -> bool:
    row = evidence.get("independent_recomposition")
    return isinstance(row, dict) and (
        row.get("producer_artifact_count") == 20
        and row.get("total_artifact_count") == 21
        and row.get("job_results_rebuilt") is True
        and row.get("all_github_digests_match_zip_sha256") is True
        and row.get("all_evidence_sha256_match") is True
        and row.get("all_official_artifact_records_match") is True
        and row.get("manifest_byte_identical") is True
        and row.get("manifest_sha256") == MANIFEST_SHA256
        and row.get("decision_byte_identical") is True
        and row.get("decision_sha256") == DECISION_SHA256
        and row.get("decision") == QUALIFIED
    )


def _check_historical(evidence: dict[str, object]) -> bool:
    rows = evidence.get("historical_runs")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_HISTORICAL_RUNS):
        return False
    return all(
        isinstance(row, dict)
        and row.get("run_id") == run_id
        and row.get("revision") == revision
        and row.get("status") == "FAILED"
        and row.get("decision") == "BLOCKED"
        and row.get("immutable") is True
        and row.get("artifacts_reused") is False
        for row, (run_id, revision) in zip(rows, EXPECTED_HISTORICAL_RUNS, strict=True)
    )


def _check_gates(evidence: dict[str, object]) -> dict[str, bool]:
    gates = evidence.get("gates")
    if not isinstance(gates, dict):
        return {"gate_evidence": False}
    contract = gates.get("contract_and_authority")
    provenance = gates.get("production_provenance")
    irv041 = gates.get("critical_irv041")
    corpus = gates.get("valid_corpus")
    mutations = gates.get("mutation_campaign")
    packaged = gates.get("packaged_clean_consumer")
    source = gates.get("source_development_install")
    transport = gates.get("transport_continuity")
    recovery = gates.get("recovery")
    rust = gates.get("rust_validation")
    performance = gates.get("performance")
    platforms = gates.get("platform_matrix")
    pythons = gates.get("python_matrix")
    return {
        "authority_scope": isinstance(contract, dict) and contract == {
            "all_contract_checks_true": True,
            "python_ir_verifier_mandatory": True,
            "rust_verify_module_shadow_pre_lifecycle": True,
            "python_lifecycle_expander_after_rust_gate": True,
            "rust_initial_ir_authority_promoted": False,
            "python_ir_verifier_removed": False,
            "lifecycle_expander_modified": False,
            "rust_ir_3_started": False,
            "ssa_refinement_preserved": True,
        },
        "pre_lifecycle_provenance": isinstance(provenance, dict)
        and provenance.get("phase") == "pre_lifecycle"
        and provenance.get("observed_events") == [
            "python_ir_verifier_pass",
            "rust_verify_module_executed",
            "rust_verify_module_pass",
            "python_lifecycle_expander_executed",
        ]
        and provenance.get("request_hash") == "ce4e14e06583eba662b968c42f54dcab71381077aa575270094d13e209027dba"
        and provenance.get("independent_request_hash_matches") is True
        and provenance.get("same_object_reaches_lifecycle") is True
        and provenance.get("post_lifecycle_product_rust_gate") is False,
        "critical_irv041": isinstance(irv041, dict)
        and irv041.get("cases") == 2
        and irv041.get("python_pre_lifecycle_accepts") is True
        and irv041.get("rust_pre_lifecycle_accepts") is True
        and irv041.get("qualification_only_post_lifecycle_rejects_irv041") is True
        and irv041.get("post_lifecycle_check_is_product_gate") is False,
        "valid_corpus": isinstance(corpus, dict)
        and corpus.get("cases") == 65
        and corpus.get("minimum") == 65
        and corpus.get("acceptance_divergences") == 0
        and corpus.get("phase") == "pre_lifecycle"
        and corpus.get("persistent_processes") == 1,
        "mutation_campaign": isinstance(mutations, dict)
        and mutations.get("required_mutations") == 75
        and mutations.get("total_cases") == 77
        and mutations.get("families_covered") == 17
        and mutations.get("acceptance_divergences") == 0
        and mutations.get("structured_category_count") == 77
        and mutations.get("structured_phase_count") == 77
        and mutations.get("structured_code_count") == 77,
        "packaged_clean_consumer": isinstance(packaged, dict)
        and packaged.get("native_verifier_discovered_from_installed_distribution") is True
        and packaged.get("checkout_available") is False
        and packaged.get("cargo_available") is False
        and packaged.get("rustc_available") is False
        and packaged.get("discovery_from_checkout_or_target") is False
        and packaged.get("discovery_stable_across_working_directories") is True
        and packaged.get("valid_invalid_valid_recovery") is True
        and packaged.get("full_compile") == "PASS"
        and packaged.get("acceptance_divergences") == 0,
        "source_development_install": isinstance(source, dict)
        and source.get("source_owned_components_built_in_job") is True
        and source.get("verify_owned_ssa_refinement_built_in_job") is True
        and source.get("copied_binary_from_other_artifact_or_target") is False
        and source.get("native_verifier_discovered_from_installed_distribution") is True
        and source.get("discovery_from_checkout_or_target") is False
        and source.get("valid_invalid_valid_recovery") is True
        and source.get("full_compile") == "PASS"
        and source.get("acceptance_divergences") == 0
        and source.get("pytest_passed") == 5260
        and source.get("pytest_skipped") == 12
        and source.get("leak_sanitizer_or_ptrace_failures") == 0,
        "transport_continuity": isinstance(transport, dict)
        and transport.get("in_process") == "PASS"
        and transport.get("companion") == "PASS"
        and transport.get("fallbacks") == 0
        and transport.get("rust_ir_verifier_transport") == "independent_subprocess",
        "next_request_recovery": isinstance(recovery, dict)
        and recovery.get("sequence") == ["accept", "reject", "accept"]
        and recovery.get("persistent_processes") == 1
        and recovery.get("uncontaminated") is True,
        "platform_matrix": isinstance(platforms, dict)
        and platforms == {
            "linux-x86_64": {"python": "3.13.15", "status": "PASS"},
            "windows-x86_64": {"python": "3.13.15", "status": "PASS"},
            "macos-x86_64": {"python": "3.13.15", "status": "PASS"},
            "macos-arm64": {"python": "3.13.14", "status": "PASS"},
        },
        "python_matrix": isinstance(pythons, dict)
        and pythons == {
            "3.11": {"python": "3.11.16", "status": "PASS"},
            "3.12": {"python": "3.12.14", "status": "PASS"},
            "3.13": {"python": "3.13.15", "status": "PASS"},
            "3.14": {"python": "3.14.7", "status": "PASS"},
        },
        "rust_validation": isinstance(rust, dict)
        and rust.get("fmt") == "PASS"
        and rust.get("test") == "PASS"
        and rust.get("current_only_clippy_findings") == 0
        and rust.get("clippy_delta") == "RUST_IR_2_CLIPPY_DELTA_CLEAN"
        and rust.get("global_clippy_claimed") is False,
        "performance_characterization": isinstance(performance, dict)
        and performance.get("pathology_threshold_ms") == 1000
        and performance.get("correction_gate") is False
        and all(float(performance.get(name, 1001)) < 1000 for name in ("small_total_ms", "medium_total_ms", "large_total_ms")),
    }


def _check_report(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    required = {
        QUALIFIED,
        str(RUN_ID),
        REVISION,
        RUST_IR_1_REVISION,
        "33462871203",
        "33464649897",
        "IRV-041",
        "verify_owned_ssa_refinement",
        "5260 passed",
        "Python IRVerifier",
        "LifecycleExpander",
        "RUST-IR-3",
    }
    return all(token in text for token in required)


def build_record(evidence_path: Path, report_path: Path, workflow_path: Path) -> dict[str, object]:
    evidence = _load(evidence_path)
    run = evidence.get("run")
    checks: dict[str, bool] = {
        "closure_identity": evidence.get("artifact_schema_version") == 1
        and evidence.get("kind") == "rust_ir_2_pre_lifecycle_shadow_qualification_closure"
        and evidence.get("milestone") == "RUST-IR-2"
        and evidence.get("rust_ir_1_revision") == RUST_IR_1_REVISION
        and evidence.get("qualification_revision") == REVISION,
        "run_identity": isinstance(run, dict)
        and run.get("id") == RUN_ID
        and run.get("workflow") == ".github/workflows/rust-ir-pre-lifecycle-shadow-qualification.yml"
        and run.get("event") == "workflow_dispatch"
        and run.get("branch") == "main"
        and run.get("revision") == REVISION
        and run.get("conclusion") == "success",
        "required_jobs": _check_jobs(evidence),
        "producer_artifacts": _check_artifacts(evidence),
        "official_aggregate": _check_aggregate(evidence),
        "independent_recomposition": _check_independent(evidence),
        "historical_runs_immutable": _check_historical(evidence),
        "eligibility_checks": _all_true(evidence.get("eligibility_checks")),
        "workflow_hash": workflow_path.is_file() and _sha256(workflow_path) == WORKFLOW_SHA256,
        "closure_report": _check_report(report_path),
    }
    checks.update(_check_gates(evidence))
    eligible = all(checks.values())
    recomputed_decision = QUALIFIED if eligible else BLOCKED
    checks["decision_recomputes"] = evidence.get("final_decision") == recomputed_decision
    passed = all(checks.values())
    return {
        "artifact_schema_version": 1,
        "kind": "rust_ir_2_pre_lifecycle_shadow_qualification_closure_check",
        "run_id": RUN_ID,
        "revision": REVISION,
        "checks": checks,
        "qualification_eligible": eligible,
        "decision": QUALIFIED if passed else BLOCKED,
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        record = build_record(args.evidence, args.report, args.workflow)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        record = {
            "artifact_schema_version": 1,
            "kind": "rust_ir_2_pre_lifecycle_shadow_qualification_closure_check",
            "run_id": RUN_ID,
            "revision": REVISION,
            "checks": {"load_evidence": False},
            "qualification_eligible": False,
            "decision": BLOCKED,
            "passed": False,
            "errors": [str(exc)],
        }
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    print(record["decision"])
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
