from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_rust_refine_2_shadow_qualification.py"
REVISION = "1" * 40
RUN_ID = "12345"
BASELINE = "b5835a5cc3c947333e6576791149767713dd0689"
PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64")
PYTHONS = ("3.11", "3.12", "3.13", "3.14")


def load_checker():
    spec = importlib.util.spec_from_file_location("rust_refine_2_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base(kind: str) -> dict[str, object]:
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-REFINE-2",
        "kind": kind,
        "revision": REVISION,
        "run_id": RUN_ID,
        "status": "PASS",
        "passed": True,
    }


def valid_records() -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    records["rust-refine-2-contract"] = {
        **base("contract_and_baseline"),
        "baseline": {"revision": BASELINE, "branch": "main", "subject": "Implement Rust shadow SSA refinement verifier", "remote_main_at_start": BASELINE},
        "core_pkg_1": {"decision": "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"},
        "contracts": {"authority": "rust_refinement_AND_python_SSARefinementVerifier", "python_authority_retired": False, "promoted": False},
    }
    records["rust-refine-2-rust-validation"] = {
        **base("rust_unit_and_adversarial"), "current_only_count": 0,
        "decision": "RUST_REFINE_2_CLIPPY_DELTA_CLEAN", "cargo_fmt_check": "PASS",
        "cargo_test_workspace_locked": "PASS", "rust_refinement_tests": "PASS", "adversarial_tests": "PASS",
    }
    records["rust-refine-2-historical"] = {
        **base("historical_differential"), "case_count": 1, "acceptance_divergences": [],
        "rows": [{"rust_accept": True, "python_accept": True}],
    }
    mutation_rows = [
        {"mutation_id": f"semantic_{index}", "semantic": True, "rust_result": "reject", "python_result": "reject"}
        for index in range(32)
    ]
    mutation_rows.append({"mutation_id": "missing_reachable_block", "semantic": True, "rust_result": "reject", "python_result": "reject", "classification": "input_domain_divergence"})
    control = {"mutation_id": "ownership_lifecycle_corruption", "semantic": False, "rust_result": "accept", "python_result": "accept"}
    records["rust-refine-2-mutations"] = {
        **base("mutation_campaign"), "rows": [*mutation_rows, control],
        "acceptance_divergences": [], "input_domain_divergences": [mutation_rows[-1]],
    }
    coverage = ["exceptions", "lifecycle", "strings", "arrays", "lists", "matrices", "classes", "interfaces", "enums", "modules", "calls_control_flow_phi", "deep_cfg_via_dedicated_gate"]
    case = {"rust_refinement_succeeded_before_schema_v2_export": True, "python_ssa_verifier_executed": True, "python_refinement_verifier_executed": True}
    records["rust-refine-2-production-pipeline"] = {
        **base("production_pipeline_shadow"), "coverage": coverage, "cases": [case],
        "python_fail_closed_injection": {"rejected": True},
    }
    transport_rows = [
        {"requested_transport": value, "observed_transport": value, "automatic_fallback": False}
        for value in ("in_process", "companion")
    ]
    records["rust-refine-2-transport-parity"] = {**base("transport_parity"), "rows": transport_rows}
    valid_case = {"rust_refinement_succeeded_before_schema_v2_export": True, "python_refinement_verifier_executed": True}
    records["rust-refine-2-packaged-consumer"] = {
        **base("packaged_clean_consumer"), "checkout_importable": False,
        "cargo_required_by_consumer": False, "rustc_required_by_consumer": False,
        "product_binding": True, "companion_installed": True, "exact_dependency_resolution": True,
        "wheels": [{"name": "native"}, {"name": "language"}], "valid_case": valid_case,
        "native_manifest": {"build_identity": REVISION, "protocol_version": 1},
        "historical_positive_cases": [valid_case, valid_case],
        "representative_python_rejection": {"rejected": True},
    }
    records["rust-refine-2-source-install"] = {
        **base("source_development_install"), "product_binding": True, "companion_installed": True,
        "both_transports_available": True, "full_python_suite": "PASS",
        "full_python_suite_summary": {"passed": 5000, "skipped": 4, "warnings": 6},
        "native_manifest": {"build_identity": REVISION},
    }
    records["rust-refine-2-deep-cfg"] = {
        **base("deep_cfg_stress"), "initial_ir_blocks": 5000, "ssa_blocks": 5000,
        "rust_result": "accept", "python_result": "accept", "optimizer_executed": False,
    }
    records["rust-refine-2-cost"] = {
        **base("cost_characterization"), "samples": [{}, {}, {}, {}], "threshold_enforced": False,
        "rust_refinement_separately_measured_with_pair_verifier": True,
    }
    targets = {"linux-x86_64": "x86_64-unknown-linux-gnu", "windows-x86_64": "x86_64-pc-windows-msvc", "macos-x86_64": "x86_64-apple-darwin", "macos-arm64": "aarch64-apple-darwin"}
    for value in PLATFORMS:
        records[f"rust-refine-2-platform-{value}"] = {
            **base("platform_qualification"), "platform": value, "role": "platform",
            "acceptance_divergences": 0, "valid_case": valid_case,
            "native_manifest": {"target": targets[value], "build_identity": REVISION},
            "historical_positive_cases": [valid_case, valid_case],
            "representative_python_rejection": {"rejected": True},
        }
    for value in PYTHONS:
        records[f"rust-refine-2-python-{value}"] = {
            **base("python_compatibility"), "python_minor": value, "python_patch": f"{value}.9",
            "role": "python_compatibility", "acceptance_divergences": 0,
            "product_binding": True, "native_manifest": {"build_identity": REVISION},
            "valid_case": valid_case, "representative_python_rejection": {"rejected": True},
        }
    return records


def write_fixture(root: Path, records: dict[str, dict[str, object]], *, claim: str = "RUST_REFINEMENT_SHADOW_QUALIFIED") -> Path:
    checker = load_checker()
    entries = []
    for index, (name, (job, kind)) in enumerate(checker.expected().items(), 1):
        evidence = root / "downloaded" / name / "evidence.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(records[name], sort_keys=True) + "\n", encoding="utf-8")
        archive = root / "zips" / f"{name}.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.write(evidence, "evidence.json")
        zip_hash = sha256(archive.read_bytes()).hexdigest()
        entries.append({
            "artifact_id": index, "name": name, "source_job": job, "run_id": RUN_ID,
            "revision": REVISION, "kind": kind, "status": "PASS",
            "github_digest": f"sha256:{zip_hash}",
            "downloaded_zip": f"zips/{name}.zip", "downloaded_zip_sha256": zip_hash,
            "extracted_evidence": f"downloaded/{name}/evidence.json",
            "extracted_evidence_sha256": sha256(evidence.read_bytes()).hexdigest(),
        })
    jobs = {job for job, _kind in checker.BASE.values()} | {"platform-qualification", "python-compatibility"}
    manifest = {
        "artifact_schema_version": 1, "milestone": "RUST-REFINE-2", "kind": "official_artifact_manifest",
        "revision": REVISION, "run_id": RUN_ID, "job_results": {job: "success" for job in jobs},
        "artifacts": entries, "aggregate_claim": claim,
    }
    path = root / "artifact-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_complete_official_artifact_set_qualifies(tmp_path: Path) -> None:
    checker = load_checker()
    result = checker.check(write_fixture(tmp_path, valid_records()))
    assert result["passed"] is True
    assert result["decision"] == "RUST_REFINEMENT_SHADOW_QUALIFIED"


@pytest.mark.parametrize(
    "corruption",
    [
        "artifact_absent", "wrong_kind", "wrong_revision", "wrong_run",
        "acceptance_divergence", "mutation_accepted", "python_absent", "rust_absent",
        "packaged_absent", "platform_absent", "python_version_absent", "aggregate_inconsistent",
    ],
)
def test_checker_blocks_adversarial_evidence(tmp_path: Path, corruption: str) -> None:
    checker = load_checker()
    records = deepcopy(valid_records())
    claim = "RUST_REFINEMENT_SHADOW_QUALIFIED"
    if corruption == "acceptance_divergence": records["rust-refine-2-historical"]["rows"][0]["python_accept"] = False
    elif corruption == "mutation_accepted": records["rust-refine-2-mutations"]["rows"][0]["rust_result"] = "accept"
    elif corruption == "python_absent": records["rust-refine-2-production-pipeline"]["cases"][0]["python_refinement_verifier_executed"] = False
    elif corruption == "rust_absent": records["rust-refine-2-production-pipeline"]["cases"][0]["rust_refinement_succeeded_before_schema_v2_export"] = False
    elif corruption == "packaged_absent": records["rust-refine-2-packaged-consumer"]["product_binding"] = False
    elif corruption == "platform_absent": records["rust-refine-2-platform-macos-arm64"]["platform"] = "missing"
    elif corruption == "python_version_absent": records["rust-refine-2-python-3.14"]["python_minor"] = "3.13"
    elif corruption == "aggregate_inconsistent": claim = "RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED"
    manifest_path = write_fixture(tmp_path, records, claim=claim)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if corruption == "artifact_absent": manifest["artifacts"].pop()
    elif corruption == "wrong_kind": manifest["artifacts"][0]["kind"] = "wrong"
    elif corruption == "wrong_revision": manifest["artifacts"][0]["revision"] = "0" * 40
    elif corruption == "wrong_run": manifest["artifacts"][0]["run_id"] = "999"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = checker.check(manifest_path)
    assert result["passed"] is False
    assert result["decision"] == "RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED"
