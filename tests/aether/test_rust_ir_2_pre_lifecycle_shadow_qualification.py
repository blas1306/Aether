from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
CHECKER = SCRIPTS / "check_rust_ir_2_pre_lifecycle_shadow_qualification.py"
WORKFLOW = ROOT / ".github/workflows/rust-ir-pre-lifecycle-shadow-qualification.yml"
REVISION = "1" * 40
RUN_ID = "12345"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ARTIFACTS = _load("rust_ir_2_test_artifacts", SCRIPTS / "rust_ir_2_artifacts.py")
CHECK = _load("rust_ir_2_test_checker", CHECKER)


def base(kind: str) -> dict[str, object]:
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-IR-2",
        "kind": kind,
        "revision": REVISION,
        "run_id": RUN_ID,
        "status": "PASS",
        "passed": True,
    }


def trace() -> dict[str, object]:
    order = [
        "python_ir_verifier_pass",
        "rust_verify_module_executed",
        "rust_verify_module_pass",
        "python_lifecycle_expander_executed",
    ]
    return {
        "case_id": "product_valid_scalar",
        "representation_phase": "pre_lifecycle",
        "events": order,
        "expected_order": order,
        "same_python_object_reaches_lifecycle": True,
        "canonical_request_sha256": "a" * 64,
        "independently_recomputed_request_sha256": "a" * 64,
        "python_verifier_status": "PASS",
        "rust_verifier_status": "PASS",
        "lifecycle_observed_after_rust": True,
        "classification": "match_accepted",
        "stage": "initial",
        "protocol_version": 1,
        "ir_schema_version": 1,
    }


def environment(
    kind: str,
    *,
    role: str,
    platform: str,
    python_minor: str,
) -> dict[str, object]:
    target = ARTIFACTS.TARGETS[platform]
    value = {
        **base(kind),
        "role": role,
        "platform": platform,
        "python_minor": python_minor,
        "python_patch": f"{python_minor}.9",
        "implementation": "CPython",
        "native_manifest": {
            "build_identity": REVISION,
            "target": target,
            "initial_ir_verifier_binary": (
                "aether-ir-verifier.exe"
                if platform == "windows-x86_64"
                else "aether-ir-verifier"
            ),
        },
        "product_binding": True,
        "initial_ir_verifier_installed": True,
        "initial_ir_verifier_path": "/venv/native/aether-ir-verifier",
        "discovery_same_after_cwd_change": True,
        "discovery_depends_on_checkout": False,
        "discovery_depends_on_cargo_target": False,
        "checkout_importable": False,
        "cargo_available_to_consumer": False,
        "rustc_available_to_consumer": False,
        "exact_dependency_resolution": True,
        "valid_case": {
            "python_ir_verifier": "PASS",
            "rust_pre_lifecycle_verifier": "PASS",
            "lifecycle_after_rust": True,
            "full_compilation": "PASS",
        },
        "invalid_case": {
            "python_rejected": True,
            "rust_rejected": True,
            "fail_closed": True,
        },
        "next_valid_request_succeeds": True,
        "acceptance_divergences": 0,
        "wheels": [{"name": "native", "sha256": "1"}, {"name": "language", "sha256": "2"}],
    }
    return value


def valid_records() -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    contract_checks = {
        name: True
        for name in {
            "run_revision_is_head",
            "baseline_exact",
            "baseline_subject_exact",
            "baseline_is_ancestor",
            "official_revision_is_origin_main",
            "working_tree_clean_at_start",
            "rust_ir_1_product_files_unchanged",
            "python_ir_verifier_mandatory",
            "rust_verifier_mandatory",
            "double_fail_closed_product",
            "product_gate_in_lower_verified",
            "initial_stage_at_call_site",
            "post_optimization_python_only",
            "python_lifecycle_connected",
            "installed_verifier_discovery",
            "no_checkout_or_path_fallback",
            "rust_refinement_authority_preserved",
            "python_lifecycle_in_refinement_path",
        }
    }
    records["rust-ir-2-contract"] = {
        **base("contract_and_baseline"),
        "rust_ir_1": {
            "revision": ARTIFACTS.BASELINE_REVISION,
            "subject": ARTIFACTS.BASELINE_SUBJECT,
            "branch": "main",
        },
        "origin_main": REVISION,
        "checks": contract_checks,
        "authority": {
            "initial_ir": "python_IRVerifier_AND_rust_verify_module",
            "lifecycle": "python_LifecycleExpander",
            "rust_initial_ir_exclusive_authority_promoted": False,
            "post_lifecycle_rust_gate": False,
        },
        "schema_changed": False,
        "protocol_changed": False,
        "transport_selection_changed": False,
        "pyo3_changed": False,
    }
    records["rust-ir-2-rust-validation"] = {
        **base("rust_verifier_unit"),
        "decision": "RUST_IR_2_CLIPPY_DELTA_CLEAN",
        "current_only_count": 0,
        "cargo_fmt_all_check": "PASS",
        "cargo_test_workspace_locked": "PASS",
        "rust_verify_module_tests": "PASS",
        "qualification_adversarial_tests": "PASS",
    }
    records["rust-ir-2-valid-corpus"] = {
        **base("valid_corpus_differential"),
        "case_count": 65,
        "acceptance_divergences": [],
        "rows": [
            {
                "case_id": f"valid-{index}",
                "phase": "pre_lifecycle",
                "python": {"accepted": True},
                "rust": {"accepted": True},
                "classification": "match_accepted",
            }
            for index in range(65)
        ],
    }
    covered_base_ids = [
        case_id
        for case_id in CHECK.MUTATION_COVERAGE_CASES.values()
        if not case_id.startswith("supplemental-")
    ]
    mutation_ids = [
        *covered_base_ids,
        *(f"mutation-{index}" for index in range(75 - len(covered_base_ids))),
    ]
    mutation_rows = [
        {
            "mutation_id": mutation_id,
            "representation_phase": "pre_lifecycle",
            "python": {"accepted": False},
            "rust": {"accepted": False},
            "classification": "match_rejected_semantic",
        }
        for mutation_id in mutation_ids
    ]
    records["rust-ir-2-mutations"] = {
        **base("mutation_campaign"),
        "mutation_count": 75,
        "qualified_case_count": 77,
        "acceptance_divergences": [],
        "rows": mutation_rows,
        "supplemental_rows": [
            {
                "case_id": case_id,
                "phase": "pre_lifecycle",
                "python": {"accepted": False},
                "rust": {"accepted": False},
            }
            for case_id in (
                "supplemental-structured-source-location",
                "supplemental-exception-irv149",
            )
        ],
        "coverage_cases": CHECK.MUTATION_COVERAGE_CASES,
        "known_diagnostic_differences": {
            name: {"python": pair[0], "rust": pair[1]}
            for name, pair in CHECK.KNOWN_DIAGNOSTICS.items()
        },
        "structured_error_field_counts": {
            field: 1
            for field in (
                "category",
                "phase",
                "code",
                "function",
                "block",
                "instruction",
                "source_location",
            )
        },
        "structured_error_limitations": {
            "source_location": "recovered_from_unchanged_python_snapshot_when_instruction_context_exists",
            "diagnostic_prose_is_semantic_identity": False,
            "protocol_or_schema_changed_for_qualification": False,
        },
        "representation_domain_exclusions": [
            {
                "case_id": name,
                "classification": "representation_domain_difference",
                "verifier_divergence": False,
                "product_corpus_affected": False,
            }
            for name in sorted(CHECK.DOMAIN_EXCLUSIONS)
        ],
        "product_corpus_domain_impact": False,
    }
    records["rust-ir-2-irv041"] = {
        **base("critical_irv041_regressions"),
        "pre_lifecycle_python": "ACCEPT",
        "pre_lifecycle_rust": "ACCEPT",
        "product_rust_verification_phase": "pre_lifecycle",
        "post_lifecycle_rust_observation": {
            "result": "REJECT",
            "code": "IRV-041",
            "qualification_only": True,
            "productive_gate": False,
        },
    }
    records["rust-ir-2-provenance"] = {
        **base("production_pre_lifecycle_provenance"),
        "provenance": trace(),
    }
    records["rust-ir-2-lifecycle-boundary"] = {
        **base("lifecycle_boundary_regression"),
        "cases": [
            {
                "test": test,
                "pre_lifecycle_python": "ACCEPT",
                "pre_lifecycle_rust": "ACCEPT",
                "product_execution": "PASS",
            }
            for test in sorted(CHECK.CRITICAL_TESTS)
        ],
        "productive_gate_phase": "pre_lifecycle",
        "python_lifecycle_authority": True,
        "post_lifecycle_rust_product_gate": False,
        "observed_order": CHECK.EXPECTED_ORDER,
    }
    records["rust-ir-2-packaged-consumer"] = environment(
        "packaged_clean_consumer",
        role="dedicated",
        platform="linux-x86_64",
        python_minor="3.13",
    )
    source = environment(
        "source_development_install",
        role="source",
        platform="linux-x86_64",
        python_minor="3.13",
    )
    source["full_python_suite"] = "PASS"
    source["full_python_suite_summary"] = {"passed": 5000, "skipped": 3, "warnings": 2}
    records["rust-ir-2-source-install"] = source
    records["rust-ir-2-recovery"] = {
        **base("next_request_recovery"),
        "sequence": ["valid_accept", "invalid_reject", "valid_accept"],
        "rust_results": ["accept", "reject", "accept"],
        "persistent_process_starts": 1,
        "state_contaminated": False,
    }
    records["rust-ir-2-transport"] = {
        **base("transport_continuity"),
        "rows": [
            {
                "requested_transport": name,
                "observed_transport": name,
                "pre_lifecycle_rust_verification": "PASS",
                "final_compilation_result": "PASS",
                "automatic_fallback": False,
                "initial_ir_verifier_transport": "independent_subprocess_operation",
            }
            for name in ("in_process", "companion")
        ],
        "verifier_uses_both_ssa_transports_claimed": False,
    }
    records["rust-ir-2-performance"] = {
        **base("performance_characterization"),
        "categories": [
            {
                "size": size,
                "samples": 9,
                "cold_import_median_ms": 10.0,
                "serialization_median_ms": 0.1,
                "rust_invocation_median_ms": 0.2,
                "total_gate_median_ms": 0.4,
            }
            for size in ("small", "medium", "large")
        ],
        "correctness_threshold_enforced": False,
        "operationally_pathological": False,
        "measurement_boundaries": {
            "dto_preparation": "x",
            "rust_invocation": "x",
            "verify_module": "x",
            "import": "x",
            "total_added_gate": "x",
        },
    }
    for platform in ARTIFACTS.PLATFORMS:
        records[f"rust-ir-2-platform-{platform}"] = environment(
            "platform_qualification",
            role="platform",
            platform=platform,
            python_minor="3.13",
        )
    for version in ARTIFACTS.PYTHONS:
        records[f"rust-ir-2-python-{version}"] = environment(
            "python_compatibility",
            role="python_compatibility",
            platform="linux-x86_64",
            python_minor=version,
        )
    return records


def write_fixture(
    root: Path,
    records: dict[str, dict[str, object]],
    *,
    claim: str = "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFIED",
) -> Path:
    entries = []
    for index, (name, (job, kind)) in enumerate(ARTIFACTS.expected().items(), 1):
        evidence = root / "downloaded" / name / "evidence.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(records[name], sort_keys=True) + "\n", encoding="utf-8")
        archive = root / "zips" / f"{name}.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.write(evidence, "evidence.json")
        zip_hash = sha256(archive.read_bytes()).hexdigest()
        role = "platform" if kind == "platform_qualification" else "python_compatibility" if kind == "python_compatibility" else "dedicated"
        entries.append(
            {
                "artifact_id": index,
                "name": name,
                "source_job": job,
                "run_id": RUN_ID,
                "revision": REVISION,
                "kind": kind,
                "role": role,
                "status": "PASS",
                "github_digest": f"sha256:{zip_hash}",
                "downloaded_zip": f"zips/{name}.zip",
                "downloaded_zip_sha256": zip_hash,
                "extracted_evidence": f"downloaded/{name}/evidence.json",
                "extracted_evidence_sha256": sha256(evidence.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "artifact_schema_version": 1,
        "milestone": "RUST-IR-2",
        "kind": "official_artifact_manifest",
        "revision": REVISION,
        "run_id": RUN_ID,
        "job_results": {job: "success" for job in ARTIFACTS.mandatory_jobs()},
        "artifacts": entries,
        "aggregate_claim": claim,
    }
    path = root / "artifact-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_complete_official_artifact_set_qualifies(tmp_path: Path) -> None:
    result = CHECK.check(write_fixture(tmp_path, valid_records()))
    assert result["passed"] is True
    assert result["decision"] == "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFIED"
    assert result["rust_initial_ir_authority_promoted"] is False


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_contract",
        "missing_provenance",
        "wrong_phase",
        "post_lifecycle_product_gate",
        "python_absent",
        "rust_absent",
        "acceptance_divergence",
        "critical_irv041_rejection",
        "mutation_accepted",
        "missing_package_executable",
        "checkout_dependency",
        "missing_platform",
        "missing_python_version",
        "wrong_revision",
        "wrong_run",
        "wrong_kind",
        "incomplete_source_install",
        "aggregate_inconsistent",
        "job_skipped",
        "digest_mismatch",
    ],
)
def test_checker_blocks_all_mandatory_adversarial_corruptions(
    tmp_path: Path,
    corruption: str,
) -> None:
    records = deepcopy(valid_records())
    claim = ARTIFACTS.QUALIFIED
    if corruption == "missing_provenance":
        records["rust-ir-2-provenance"]["provenance"] = {}
    elif corruption == "wrong_phase":
        records["rust-ir-2-valid-corpus"]["rows"][0]["phase"] = "post_lifecycle"
    elif corruption == "post_lifecycle_product_gate":
        records["rust-ir-2-lifecycle-boundary"]["post_lifecycle_rust_product_gate"] = True
    elif corruption == "python_absent":
        records["rust-ir-2-packaged-consumer"]["valid_case"]["python_ir_verifier"] = "ABSENT"
    elif corruption == "rust_absent":
        records["rust-ir-2-packaged-consumer"]["valid_case"]["rust_pre_lifecycle_verifier"] = "ABSENT"
    elif corruption == "acceptance_divergence":
        records["rust-ir-2-valid-corpus"]["rows"][0]["rust"]["accepted"] = False
    elif corruption == "critical_irv041_rejection":
        records["rust-ir-2-irv041"]["pre_lifecycle_rust"] = "REJECT"
    elif corruption == "mutation_accepted":
        records["rust-ir-2-mutations"]["rows"][0]["rust"]["accepted"] = True
    elif corruption == "missing_package_executable":
        records["rust-ir-2-packaged-consumer"]["initial_ir_verifier_installed"] = False
    elif corruption == "checkout_dependency":
        records["rust-ir-2-packaged-consumer"]["checkout_importable"] = True
    elif corruption == "missing_python_version":
        records["rust-ir-2-python-3.14"]["python_minor"] = "3.13"
    elif corruption == "incomplete_source_install":
        records["rust-ir-2-source-install"]["full_python_suite_summary"] = None
    elif corruption == "aggregate_inconsistent":
        claim = ARTIFACTS.BLOCKED
    manifest_path = write_fixture(tmp_path, records, claim=claim)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if corruption == "missing_contract":
        manifest["artifacts"] = [row for row in manifest["artifacts"] if row["name"] != "rust-ir-2-contract"]
    elif corruption == "missing_platform":
        manifest["artifacts"] = [row for row in manifest["artifacts"] if row["name"] != "rust-ir-2-platform-macos-arm64"]
    elif corruption == "wrong_revision":
        manifest["artifacts"][0]["revision"] = "0" * 40
    elif corruption == "wrong_run":
        manifest["artifacts"][0]["run_id"] = "999"
    elif corruption == "wrong_kind":
        manifest["artifacts"][0]["kind"] = "wrong"
    elif corruption == "job_skipped":
        manifest["job_results"]["contract-and-baseline"] = "skipped"
    elif corruption == "digest_mismatch":
        manifest["artifacts"][0]["github_digest"] = "sha256:" + "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = CHECK.check(manifest_path)
    assert result["passed"] is False
    assert result["decision"] == "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFICATION_BLOCKED"


def test_workflow_has_dedicated_fail_closed_gates_and_no_historical_reuse() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for job in ARTIFACTS.mandatory_jobs() | {"aggregate-fail-closed"}:
        assert f"  {job}:" in workflow
    for artifact in ARTIFACTS.BASE:
        assert f"name: {artifact}" in workflow
    assert "name: rust-ir-2-platform-${{ matrix.platform }}" in workflow
    assert "name: rust-ir-2-python-${{ matrix.python }}" in workflow
    assert "workflow_dispatch:" in workflow
    assert "if: always()" in workflow
    assert "rust-refine-shadow-qualification.yml" not in workflow
    assert "core-native-packaging.yml" not in workflow
    assert "RUST_INITIAL_IR_AUTHORITY_PROMOTED" not in workflow
    assert "pattern: rust-ir-2-*" in workflow
    assert "cargo fmt --all --check" in workflow
    assert "cargo test --workspace --locked" in workflow
    assert "python -m pytest -q tests" in workflow
    packaged = workflow[
        workflow.index("  packaged-clean-consumer:") : workflow.index("  source-development-install:")
    ]
    assert "python -m build --wheel" in packaged
    assert "python -m pip install -e ." not in packaged
    assert "target/" not in packaged


def test_workflow_installs_corpus_and_lifecycle_test_prerequisites() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    valid = workflow[
        workflow.index("  valid-corpus-differential:") : workflow.index("  mutation-campaign:")
    ]
    mutations = workflow[
        workflow.index("  mutation-campaign:") : workflow.index("  critical-irv041-regressions:")
    ]
    lifecycle = workflow[
        workflow.index("  lifecycle-boundary-regression:") : workflow.index("  packaged-clean-consumer:")
    ]
    for section in (valid, mutations):
        assert (
            "python -m pip install compiler-rs/distributions/aether-compiler-core"
            in section
        )
        assert "pytest" in section
        assert "maturin>=1.9.4,<2" in section
    assert "pytest" in lifecycle


def test_source_install_builds_binaries_required_by_full_repository_suite() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    source = workflow[
        workflow.index("  source-development-install:") : workflow.index("  next-request-recovery:")
    ]
    assert "--package aether-verifier --bin aether-ssa-shadow" in source
    assert "--release --package aether-ir-verifier" in source
    full_suite = source.index("python -m pytest -q tests")
    assert source.index("--package aether-verifier --bin aether-ssa-shadow") < full_suite
    assert source.index("--release --package aether-ir-verifier") < full_suite
