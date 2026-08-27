#!/usr/bin/env python3
"""Validate the promoted, official-evidence second RUST-4.5 closure."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_promotion_closure_6274cd20.json"
)
DEFAULT_REPORT = (
    ROOT
    / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_6274CD20.md"
)
WORKFLOW = ROOT / ".github/workflows/rust-ssa-shadow.yml"

RUN_ID = 33121500789
REVISION = "6274cd2024fd012d297533d7783f7c4547feb26f"
PREVIOUS_RUN_ID = 33110365185
PREVIOUS_REVISION = "b7362b06ead8da36d3ad3a97351fd5813c258590"
PREVIOUS_DECISION = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED"
PROMOTED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED"
BLOCKED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED"
DEFAULT_MODE = "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED"
DIFFERENTIAL_MODE = "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
DIFFERENTIAL_VALUE = "rust_ssa_authority_python_shadow"
DIFFERENTIAL_DECISION = "RUST_SSA_DIFFERENTIAL_SHADOW_QUALIFIED"
SHA256 = re.compile(r"[0-9a-f]{64}")

REQUIRED_PLATFORMS = {
    "linux-x86_64",
    "windows-x86_64",
    "macos-x86_64",
    "macos-arm64",
}
REQUIRED_JOBS = {
    "rust-4.5-ci-differential-rust-refinement-python-shadow",
    "rust-4.5-production-default-no-python-shadow",
    "rust-4.5-shadow-independent-clean-install-windows-x86_64",
    "rust-stabilization-macos-arm64",
    "rust-stabilization-linux-x86_64",
    "production-stabilization-full-suite",
    "rust-4-4-full-local-qualification",
    "authority-soak",
    "rust-authority-windows-x86_64",
    "rust-stabilization-windows-x86_64",
    "rust-4.4-shadow-independent-linux-x86_64",
    "rust-authority-macos-arm64",
    "rust-4.4-shadow-independent-macos-arm64",
    "rust-authority-linux-x86_64",
    "rust-authority-macos-x86_64",
    "rust-4.4-shadow-independent-windows-x86_64",
    "historical-116",
    "production-stabilization-operational",
    "python-only",
    "production-stabilization-regressions",
    "deep-cfg",
    "promotion-fixtures",
    "rust-stabilization-macos-x86_64",
    "adversarial",
    "performance",
    "python-authority-rust-shadow",
    "rust-4.5-shadow-independent-clean-install-macos-arm64",
    "rust-4.4-shadow-independent-macos-x86_64",
    "rust-4.5-shadow-independent-clean-install-macos-x86_64",
    "full-suite-rust-default",
    "rust-4.5-shadow-independent-clean-install-linux-x86_64",
    "production-stabilization-aggregate",
    "aggregate",
}
EXPECTED_ORDERING = [
    "initial_ir_verification",
    "lifecycle_normalization",
    "rust_ssa_lowering_and_verification",
    "schema_v2_import",
    "imported_ssa_verification",
    "same_input_integrity_before_refinement",
    "independent_refinement_verification",
    "same_input_integrity_after_refinement",
    "final_generic_verification",
    "accept",
]
EXPECTED_PRODUCTION_ARCHITECTURE = [
    "initial_ir_verification",
    "lifecycle_normalization",
    "rust_ssa_lowering",
    "rust_side_verification",
    "schema_v2_import",
    "imported_ssa_verification",
    "same_input_integrity_controls",
    "independent_refinement_verification",
    "final_generic_verification",
    "optimizer_backend",
]
EXPECTED_HISTORY = [
    "RUST-3.x",
    "mandatory Python shadow",
    "RUST-4.1 independent refinement",
    "RUST-4.2 production refinement",
    "RUST-4.3 redundancy qualification",
    "RUST-4.4 shadow-independent qualification",
    "RUST-4.5 production promotion",
    "first closure BLOCKED",
    "RUST-4.5A environment isolation",
    "second official qualification",
    "final closure",
]
HISTORICAL_FILES = {
    "docs/compiler/rust_ssa_shadow_independent_production_promotion_closure.json":
        "b11bd9cbf70b199d4dc2e6b1a9d53a5d2cb15fab3bf66e8ad1e726ecc1a3af58",
    "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE.md":
        "9010190cf153c07eb25031f598fb7f1316c51cc4fef85f40917650bd623216bb",
    "scripts/check_rust_ssa_shadow_independent_production_promotion_closure.py":
        "9730a75354724667ae7318aa426094da5b2e2dcd7f047ea9b4f0493e5e5cd404",
    "tests/aether/test_rust_ssa_shadow_independent_production_promotion_closure.py":
        "ae66b8b086a9c88c98df1438ca5bd6d3922bd05344114d8b03aade09791cd823",
}

# Values below come from GitHub's artifact digest field and from SHA-256 over
# files downloaded with `gh run download 33121500789`. Keeping them here makes
# a replacement by a merely well-formed, unrelated hash fail closed.
EXPECTED_ARTIFACTS = {
    "rust-ssa-authority-promotion-v2": (
        "cc3d5cd1ea57168cf6b40358d45117bf5f7471d7f9166d587480bb60d07699e4",
        "RUST_SSA_AUTHORITY_PROMOTED_V2",
        {"qualification/rust_ssa_authority_promotion_v2.json": "c6c5c701383253d4ccde7383badf9fcad318d646e7bdb46c0c9fad255e26bb64"},
    ),
    "rust-ssa-production-stabilization": (
        "2aac49803771b68055787aeb9f799053f2b0f71010e187b5a9a45ca917df4be8",
        "RUST_SSA_PRODUCTION_STABILIZED",
        {"qualification/rust_ssa_production_stabilization.json": "bbabf9939128b798a3d2abfa8bbee38ecb73e376b1f400ce8d13f89817bc8419"},
    ),
    "platform-linux-x86_64": (
        "316c9d6286a883b39db4ab134e8423391ec1619c25b2ae698a5dbc4782ae2c6c",
        "PASS",
        {"linux-x86_64.json": "f8068b20603773bc69061c4e7b1b827d35bcbcda584927a103f72ec7d0b00d53"},
    ),
    "platform-windows-x86_64": (
        "f0235f02cbf3d354652e37043de6438f03ee21e1820c99ee99e23b6cba7579ae",
        "PASS",
        {"windows-x86_64.json": "4cd3365c3384413bd51fb0e5e0b5682fea9aeb5da709b8367d052270ce6d7403"},
    ),
    "platform-macos-x86_64": (
        "58e6b2b852cc6163d53c3addf9759cd472469e4bac1e47e7449c06b5a81d6703",
        "PASS",
        {"macos-x86_64.json": "169c5b4b6af733fbe717fd2cd8f2e9c5324f0884d29caa0dca04048cc2b04845"},
    ),
    "platform-macos-arm64": (
        "b53751d73261965543574b1e9c343e95ca6ff91c7a63d793a498585b81ebbaa9",
        "PASS",
        {"macos-arm64.json": "9eea657a2c525349074a3560c58dd735cc8d1e7932460fa93ae70217e7c2b9b4"},
    ),
    "rust-4.5-differential-shadow": (
        "65630f28d0227243e0efdf2bd097e8cdaa32d4f9c116ecc2589c1cb536ef25c2",
        DIFFERENTIAL_DECISION,
        {
            "differential.json": "703e94b71075d7d82344495014508b696510f5b4f0c855ec7f3496da59190eca",
            "differential.md": "ee12fd380d0dd0703cde98d951fedb19378f4536eef6568c95c6554702abfd3b",
        },
    ),
    "rust-4.5-clean-install-linux-x86_64": (
        "fbf9b8ed4799a3c960598f8fa83dc8f5482c65d7480cdafc432c2e15844fd01f",
        "PASS",
        {"linux-x86_64.json": "16425dbd8c6e737b6cda2aa2721d4a7510a28e41a898bd8ac1d950e056a902da"},
    ),
    "rust-4.5-clean-install-windows-x86_64": (
        "c8eb8f8656868b46a5372b946c018c370c56146813fa1f3b199954f0d54b7400",
        "PASS",
        {"windows-x86_64.json": "adebbe885539aa6bd5272bb99a2e2e23c2c76ad2332d71caa8c5e0c9a5ea5f46"},
    ),
    "rust-4.5-clean-install-macos-x86_64": (
        "a913bb364aee69f652b51d1d5ad83e28b27b64a32e3e4b3ac500c403d9318348",
        "PASS",
        {"macos-x86_64.json": "4d317e7cfa333d8c246cf61c7ab4715427c1e4a008bfb1b418b3fbce055d9e68"},
    ),
    "rust-4.5-clean-install-macos-arm64": (
        "12f70494395e3ff8bee30f1a9a4c9f4161a178e79705ba7d2617eb134bc572f0",
        "PASS",
        {"macos-arm64.json": "dff25c3dafa2be637e84888a84a2ffe68cb168a0869082f2cbc5a9473ded06de"},
    ),
    "promotion-fixtures": (
        "399d27b761fb4c91125812a30eb561b6caaf19b09224aaf247fdf27ccf28ea55",
        "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED",
        {"promotion_fixtures.json": "aa1f79fa6124bc7c391e4374563ee31b62d66bb6c5fd029f87b03f7bcdf70c7a"},
    ),
    "historical-116": (
        "b0fb2a54d8da002be16b54fc15341ae38ed6d08537fe5d406e50c4f3c660db6f",
        "RUST_SSA_AUTHORITY_HISTORICAL_PASS",
        {"historical.json": "96ea7d13d8a376de0faddc727ed92b3578e87d0d8c2932f8a0c34ebc408cde27"},
    ),
    "adversarial": (
        "d45ea68a3209136d38402979d407216b5aa1c15ed2dd9c71773cf0df0a0e53d2",
        "RUST_SSA_LOWERING_ADVERSARIAL_QUALIFIED",
        {"adversarial.json": "eabf2c370440d1fc14ed172aaf1ec5804b55db02a96b4402e0b1411ce66d039d"},
    ),
    "deep-cfg": (
        "e923b0f201d965ce8c859b79c94b1327c63542d6c816499df64b345cebeca156",
        "RUST_SSA_AUTHORITY_DEEP_CFG_PASS",
        {"deep_cfg.json": "cd285bfb8ae4193993810d4f07e283fd02921460749646d5c932c6b920624ac3"},
    ),
    "authority-soak": (
        "2dabdd906bc79955ff24ae0b3e8964b56b016713bf58e121ec6cff26cf2e3a00",
        "RUST_SSA_AUTHORITY_SOAK_PASS",
        {
            "soak.json": "2fa508662d96fbe109d463f4616e14066cc5a3dd402de93d2c4570fbae44129b",
            "operational.json": "9a8a522b14d05e79f4510617e19c89e06463b61f1a5ef63261380f35692e46c4",
        },
    ),
    "full-suite-rust-default": (
        "8470a8520bfa68c0d05399774853b2ada679acb6d277985df489b1c066a3c252",
        "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_PASS",
        {
            "full_suite.json": "18ba867cf3a3766a443c80e15b9e56e277105149d9cc98e4b30ab945d6f8a985",
            "full_suite_pytest.log": "570c71f4b25895571d8e11f3dbfa3348f58eb67347bae5520ad2767b8f70a7b0",
        },
    ),
    "production-stabilization-operational": (
        "63aa5127c4fa2ccd815269d0dcb334b78cbbc3f505c635b2b4bfadcfdf4a3234",
        "RUST_SSA_PRODUCTION_STABILIZATION_OPERATIONAL_PASS",
        {"operational.json": "0b344f9d10de37648cea2d06fcd993a5001d2a9d9974ebcc5473990acd95a999"},
    ),
    "production-stabilization-regressions": (
        "550c22713ef9d7f93747823e86b06234b58a525aed2d7c625ce5aad3fe5ff0be",
        "RUST_SSA_PRODUCTION_REGRESSIONS_PASS",
        {"regressions.json": "dbc473512d7d6759545867b0c7326e9c90775b6cd8f753c669db6bf9e00fe2ce"},
    ),
    "production-stabilization-full-suite": (
        "ccec6e0774faac8801c3fd20ffdffa66566cb28655500fc6689f1d41c7abdb5e",
        "RUST_SSA_PRODUCTION_STABILIZATION_FULL_SUITE_PASS",
        {
            "full_suite.json": "b92035adff5dc129f8035edbcf7b55646c8a3f12629264275e293ff514257a55",
            "full_suite_pytest.log": "9b25b5f3a7377bec6f5277447af1f2f260ba9ea9c7c275faa8ad19b24e08c79c",
        },
    ),
    "production-stabilization-platform-linux-x86_64": (
        "d1be64ac2ce0f39911feb59d73dd3526d3daf1dff9174e13318f5bb68ceae411",
        "PASS",
        {"linux-x86_64.json": "11011bdb016cbddf1beb85e4a58c312adb2991255053493526b00d88b3dff294"},
    ),
    "production-stabilization-platform-windows-x86_64": (
        "0dbaa45ac9d50cb90b6a478ef8a094e7b2cfb11622820b4348205c104fc6fbe0",
        "PASS",
        {"windows-x86_64.json": "53e9dc85b6d7f208df6750a6cefe30115e57e10b4d65e0668befcc39b2e1f588"},
    ),
    "production-stabilization-platform-macos-x86_64": (
        "5b167eccaff9e68523c9f44cf45d83f1d822db5a87d9c397b8c1dfc85e845c67",
        "PASS",
        {"macos-x86_64.json": "35f4d8ab4520eb8f1cc938c8de31649d5606680bbf358736b0ace5800661ffdb"},
    ),
    "production-stabilization-platform-macos-arm64": (
        "26961575bc0c1db2e40d5e301ed2e70d4efbcba6f9a5b24ff8e277da871d370f",
        "PASS",
        {"macos-arm64.json": "0482cff156241e3a45474143c32d963d1a3a03b5d6d139a3a71ce7a0703d46b5"},
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_is_exact(rows: object) -> bool:
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_ARTIFACTS):
        return False
    by_name = {
        row.get("artifact_name"): row
        for row in rows
        if isinstance(row, dict)
    }
    if by_name.keys() != EXPECTED_ARTIFACTS.keys() or len(by_name) != len(rows):
        return False
    for name, (digest, decision, expected_files) in EXPECTED_ARTIFACTS.items():
        row = by_name[name]
        files = {
            item.get("path"): item.get("sha256")
            for item in row.get("files", [])
            if isinstance(item, dict)
        }
        if not (
            row.get("source_run_id") == RUN_ID
            and row.get("source_revision") == REVISION
            and row.get("artifact_conclusion") == "success"
            and row.get("decision_or_status") == decision
            and row.get("github_artifact_digest_sha256") == digest
            and SHA256.fullmatch(digest)
            and bool(row.get("platform"))
            and bool(row.get("gate"))
            and files == expected_files
            and len(files) == len(row.get("files", []))
            and all(SHA256.fullmatch(value) for value in files.values())
        ):
            return False
    return True


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
    workflow_path: Path = WORKFLOW,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")

    old_evidence = json.loads(
        (ROOT / "docs/compiler/rust_ssa_shadow_independent_production_promotion_closure.json").read_text(encoding="utf-8")
    )
    recorded_old_files = {
        row.get("path"): row.get("sha256")
        for row in evidence.get("historical_closure_preservation", {}).get("files", [])
        if isinstance(row, dict)
    }
    historical_preserved = bool(
        evidence.get("historical_closure_preservation", {}).get("status")
        == "IMMUTABLE_BLOCKED_RECORD_PRESERVED"
        and recorded_old_files == HISTORICAL_FILES
        and all(_sha256(ROOT / path) == digest for path, digest in HISTORICAL_FILES.items())
        and old_evidence.get("source_run_id") == PREVIOUS_RUN_ID
        and old_evidence.get("exact_revision") == PREVIOUS_REVISION
        and old_evidence.get("final_decision") == PREVIOUS_DECISION
    )

    jobs = evidence.get("required_job_results", {})
    jobs_green = bool(
        isinstance(jobs, dict)
        and jobs.keys() == REQUIRED_JOBS
        and all(value == "success" for value in jobs.values())
    )
    artifact_manifest = _manifest_is_exact(evidence.get("artifact_manifest"))

    platforms = evidence.get("platform_matrix", [])
    by_platform = {
        row.get("platform"): row
        for row in platforms
        if isinstance(row, dict)
    }
    platform_pass = bool(
        by_platform.keys() == REQUIRED_PLATFORMS
        and len(by_platform) == len(platforms)
        and all(
            row.get("revision") == REVISION
            and row.get("status") == "PASS"
            and row.get("default_mode") == DEFAULT_MODE
            and row.get("shadow") == "not_executed_by_default"
            and row.get("python_shadow_executions_in_default") == 0
            and row.get("canonical_comparisons_in_default") == 0
            and row.get("clean_install_artifact")
            == f"rust-4.5-clean-install-{platform}"
            and row.get("authority_artifact") == f"platform-{platform}"
            and row.get("stabilization_artifact")
            == f"production-stabilization-platform-{platform}"
            for platform, row in by_platform.items()
        )
    )

    default = evidence.get("default_mode", {})
    default_pass = bool(
        default.get("mode") == DEFAULT_MODE
        and default.get("authority") == "rust"
        and default.get("job") == "rust-4.5-production-default-no-python-shadow"
        and default.get("job_conclusion") == "success"
        and default.get("job_environment_override") is False
        and default.get("refinement_mandatory") is True
        and default.get("python_shadow_executed") is False
        and default.get("canonical_comparison_executed") is False
        and default.get("imported_ssa_verification_executed") is True
        and default.get("independent_refinement_verification_executed") is True
        and default.get("final_generic_verification_executed") is True
        and default.get("focused_policy_tests") == {"passed": 43, "failed": 0}
        and default.get("full_repository_suite", {}).get("passed") == 5031
        and default.get("full_repository_suite", {}).get("failed") == 0
        and default.get("full_repository_suite", {}).get("skipped") == 12
        and default.get("production_ordering") == EXPECTED_ORDERING
    )

    rust_4_5a = evidence.get("rust_4_5a", {})
    production = rust_4_5a.get("production_default_observation", {})
    differential = rust_4_5a.get("differential_mode_observation", {})
    gate = rust_4_5a.get("decision_gate", {})
    rust_4_5a_pass = bool(
        rust_4_5a.get("status") == "PASS"
        and rust_4_5a.get("job")
        == "rust-4.5-ci-differential-rust-refinement-python-shadow"
        and rust_4_5a.get("job_conclusion") == "success"
        and production.get("status") == "PASS"
        and production.get("authority") == "rust"
        and production.get("mode") == DEFAULT_MODE
        and production.get("refinement_mandatory") is True
        and production.get("python_general_ssa_builder_executed") is False
        and production.get("canonical_comparison_executed") is False
        and production.get("environment_variable")
        == "AETHER_SSA_AUTHORITY_MODE"
        and production.get("environment_effective_value") is None
        and production.get("environment_isolation")
        == "explicitly_removed_from_subprocess_environment"
        and production.get("focused_policy_tests", {}).get("status") == "PASS"
        and production.get("focused_policy_tests", {}).get("returncode") == 0
        and differential.get("status") == "PASS"
        and differential.get("authority") == "rust"
        and differential.get("mode") == DIFFERENTIAL_MODE
        and differential.get("refinement_mandatory") is True
        and differential.get("python_general_ssa_builder_executed") is True
        and differential.get("canonical_comparison_executed") is True
        and differential.get("canonical_mismatch_fail_closed") is True
        and differential.get("refinement_failure_fail_closed") is True
        and differential.get("environment_override")
        == f"AETHER_SSA_AUTHORITY_MODE={DIFFERENTIAL_VALUE}"
        and differential.get("environment_effective_value") == DIFFERENTIAL_VALUE
        and differential.get("environment_isolation")
        == "explicitly_set_in_subprocess_environment"
        and differential.get("focused_differential_tests", {}).get("status")
        == "PASS"
        and differential.get("focused_differential_tests", {}).get("returncode")
        == 0
        and rust_4_5a.get("artifact_decision") == DIFFERENTIAL_DECISION
        and rust_4_5a.get("artifact_qualification_complete") is True
        and gate.get("step") == "Differential qualification decision gate"
        and gate.get("conclusion") == "success"
        and gate.get("checker") == "scripts/check_rust_ssa_differential_qualification.py"
        and gate.get("checks")
        == {
            "identity": True,
            "semantic_campaign": True,
            "production_default_observation": True,
            "differential_mode_observation": True,
            "rollback": True,
            "completion_recomputes": True,
            "decision_recomputes": True,
        }
    )

    historical = evidence.get("historical_result", {})
    mutations = evidence.get("mutation_result", {})
    deep = evidence.get("deep_cfg_result", {})
    semantic_pass = bool(
        historical
        == {
            "decision": "RUST_SSA_AUTHORITY_HISTORICAL_PASS",
            "passed": 116,
            "failed": 0,
            "denominator": 116,
        }
        and mutations
        == {
            "total": 58,
            "unique_ids": 58,
            "rejected_by_both": 58,
            "production_shadow_dependencies": 0,
            "invalid_accepted_by_both": 0,
        }
        and deep.get("status") == "PASS"
        and deep.get("blocks") == [993, 1000, 5000, 10000]
        and deep.get("production_accepts") is True
        and deep.get("qualification_accepts") is True
        and deep.get("authoritative_ssa_equal") is True
    )

    soak = evidence.get("soak_result", {})
    soak_pass = bool(
        soak.get("status") == "PASS"
        and soak.get("differential_requests_passed")
        == soak.get("differential_requests")
        == 64
        and soak.get("authority_soak_decision") == "RUST_SSA_AUTHORITY_SOAK_PASS"
        and soak.get("semantic_mismatches") == 0
        and soak.get("concurrent_requests") == 128
    )
    rollback_pass = evidence.get("rollback_modes") == {
        "rust_authority_python_differential_shadow": "PASS",
        "python_authority_rust_shadow": "PASS",
        "python_only": "PASS",
    }

    suites = evidence.get("full_suite_result", {})
    suite_pass = all(
        row.get("passed") == 5031
        and row.get("failed") == 0
        and row.get("skipped") == 12
        for row in suites.values()
        if isinstance(row, dict)
    ) and len(suites) == 3

    stabilization = evidence.get("stabilization_result", {})
    stabilization_pass = bool(
        stabilization.get("decision") == "RUST_SSA_PRODUCTION_STABILIZED"
        and stabilization.get("qualification_revision") == REVISION
        and stabilization.get("blockers") == []
        and stabilization.get("all_17_gates_passed") is True
        and set(stabilization.get("platforms", [])) == REQUIRED_PLATFORMS
    )
    aggregate = evidence.get("aggregate_result", {})
    aggregate_pass = bool(
        aggregate.get("authority_decision") == "RUST_SSA_AUTHORITY_PROMOTED_V2"
        and aggregate.get("authority_promotion_revision") == REVISION
        and aggregate.get("stabilization_decision")
        == "RUST_SSA_PRODUCTION_STABILIZED"
        and aggregate.get("stabilization_qualification_revision") == REVISION
        and set(aggregate.get("platforms", [])) == REQUIRED_PLATFORMS
    )

    default_workflow = workflow.split(
        "  rust-4-5-shadow-independent-default:", 1
    )[-1].split("  rust-4-5-mandatory-differential-shadow:", 1)[0]
    differential_workflow = workflow.split(
        "  rust-4-5-mandatory-differential-shadow:", 1
    )[-1].split("  rust-4-5-clean-install-platform:", 1)[0]
    qualifier_marker = "python scripts/qualify_rust_ssa_shadow_independent_production_promotion.py"
    gate_marker = "Differential qualification decision gate"
    upload_marker = "actions/upload-artifact@v4"
    workflow_pass = bool(
        "AETHER_SSA_AUTHORITY_MODE" not in default_workflow
        and "AETHER_SSA_AUTHORITY_MODE: rust_ssa_authority_python_shadow"
        in differential_workflow
        and qualifier_marker in differential_workflow
        and "--qualification-scope differential" in differential_workflow
        and "scripts/check_rust_ssa_differential_qualification.py"
        in differential_workflow
        and differential_workflow.index(qualifier_marker)
        < differential_workflow.index(gate_marker)
        < differential_workflow.index(upload_marker)
        and "if: always()" in differential_workflow
    )

    hashes = evidence.get("artifact_hashes", {})
    digest_pass = bool(
        hashes.get("algorithm") == "SHA-256"
        and hashes.get("manifest_entries") == len(EXPECTED_ARTIFACTS) == 24
        and hashes.get("evidence_files") == 28
    )
    policy_pass = evidence.get("evidence_policy") == {
        "official_artifacts_only": True,
        "local_evidence_regenerated": False,
        "mixed_revision_evidence_allowed": False,
    }

    eligibility_checks = {
        "four_clean_installs": platform_pass,
        "default_no_python_shadow": default_pass,
        "rust_4_5a_environment_isolation": rust_4_5a_pass,
        "differential_artifact_qualified": rust_4_5a_pass and artifact_manifest,
        "differential_decision_gate_passed": rust_4_5a_pass and workflow_pass,
        "historical_mutation_deep_cfg": semantic_pass,
        "authority_soak": soak_pass,
        "rollback_modes": rollback_pass,
        "full_default_suite": suite_pass,
        "stabilization": stabilization_pass,
        "platform_authority": platform_pass and artifact_manifest,
        "aggregate_exact_revision": aggregate_pass,
        "required_jobs_green": jobs_green,
        "required_artifacts_exact_revision": artifact_manifest,
        "github_artifact_digests_recorded": artifact_manifest and digest_pass,
        "no_relevant_skips": evidence.get("relevant_skipped_jobs") == [],
    }
    eligible = all(eligibility_checks.values())
    expected_decision = PROMOTED if eligible else BLOCKED
    recorded = evidence.get("promotion_eligibility", {})

    integrity_checks = {
        "identity": evidence.get("artifact_schema_version") == 2
        and evidence.get("milestone") == "RUST-4.5"
        and evidence.get("closure_revision") == REVISION
        and evidence.get("exact_revision") == REVISION
        and evidence.get("source_run_id") == RUN_ID
        and evidence.get("source_run_url")
        == f"https://github.com/blas1306/Aether/actions/runs/{RUN_ID}"
        and evidence.get("source_run_event") == "workflow_dispatch"
        and evidence.get("source_run_status") == "completed"
        and evidence.get("source_run_conclusion") == "success",
        "previous_closure_identity": evidence.get("previous_closure") == "BLOCKED"
        and evidence.get("previous_closure_run") == PREVIOUS_RUN_ID
        and evidence.get("previous_closure_revision") == PREVIOUS_REVISION
        and evidence.get("previous_closure_decision") == PREVIOUS_DECISION
        and evidence.get("previous_block_reason")
        == "differential qualification environment contamination / false-green qualification gate",
        "historical_integrity": evidence.get("historical_integrity")
        == EXPECTED_HISTORY,
        "previous_closure_immutable": historical_preserved,
        "job_evidence": jobs_green,
        "artifact_manifest": artifact_manifest,
        "github_artifact_digests": digest_pass,
        "platform_truth": platform_pass,
        "default_evidence": default_pass,
        "production_architecture": evidence.get("production_architecture")
        == EXPECTED_PRODUCTION_ARCHITECTURE,
        "rust_4_5a_evidence": rust_4_5a_pass,
        "semantic_evidence": semantic_pass,
        "soak_evidence": soak_pass,
        "rollback_evidence": rollback_pass,
        "full_suite_evidence": suite_pass,
        "stabilization_evidence": stabilization_pass,
        "aggregate_evidence": aggregate_pass,
        "official_evidence_policy": policy_pass,
        "workflow_permanence": workflow_pass,
        "eligibility_recomputes": recorded.get("eligible") is eligible
        and recorded.get("checks") == eligibility_checks
        and recorded.get("blockers") == [],
        "decision_recomputes": evidence.get("final_decision") == expected_decision,
        "production_freeze": evidence.get("production_code_changed") is False
        and evidence.get("python_ssa_retained") is True
        and evidence.get("differential_ci_retained") is True,
        "report": report.startswith(
            "# RUST-4.5 — shadow-independent production promotion closure (second attempt)"
        )
        and PROMOTED in report
        and REVISION in report
        and str(RUN_ID) in report
        and PREVIOUS_DECISION in report
        and "does not formally prove" in report,
    }
    return {
        "milestone": "RUST-4.5",
        "passed": all(integrity_checks.values()),
        "decision": evidence.get("final_decision"),
        "expected_decision": expected_decision,
        "promotion_eligible": eligible,
        "eligibility_checks": eligibility_checks,
        "checks": integrity_checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--workflow", type=Path, default=WORKFLOW)
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report, args.workflow)
    print(f"RUST-4.5 second closure: {record['decision']}")
    for name, passed in record["checks"].items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")
    for name, passed in record["eligibility_checks"].items():
        print(f"  {'PASS' if passed else 'BLOCK'} gate:{name}")
    if not record["passed"]:
        return 1
    if args.require_promoted and not record["promotion_eligible"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
