from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts import check_rust_ir_3_authority_promotion as check


REVISION = "a" * 40
RUN_ID = "123456789"


def _product() -> dict[str, object]:
    return {
        "product_authority_provenance": {
            "product_authority": "rust",
            "rust_verify_module_executed": True,
            "rust_verify_module_accepted": True,
            "python_ir_verifier_consulted": False,
            "python_ir_verifier_calls": 0,
            "python_lifecycle_calls": 1,
            "post_lifecycle_rust_product_gate": False,
        },
        "no_python_rescue": {
            "python_rescue_attempted": False,
            "automatic_fallback": False,
            "lifecycle_calls_during_admission": 0,
            "ssa_construction_calls_after_rejection": 0,
            "next_valid_request_succeeds": True,
        },
        "explicit_python_oracle": {
            "role": "qualification_oracle",
            "affected_product_decision": False,
        },
        "full_compile": {"python_lifecycle_authority_observed": True},
    }


def _evidence(kind: str, role: str, name: str) -> dict[str, object]:
    result: dict[str, object] = {
        "artifact_schema_version": 1,
        "milestone": "RUST-IR-3",
        "kind": kind,
        "revision": REVISION,
        "run_id": RUN_ID,
        "status": "PASS",
        "passed": True,
    }
    if kind == "prerequisite_rust_ir_2":
        result.update(checks={"official": True}, official={"run_id": "33465504645"})
    elif kind == "authority_contract_and_invariant_audit":
        result.update(
            python_only_semantic_invariants=[],
            desired_authority="rust_verify_module",
            lifecycle_authority="python_LifecycleExpander",
            rows=[{} for _ in range(22)],
        )
    elif kind == "directed_false_negative_search":
        result.update(case_count=150, false_negatives=[])
    elif kind == "directed_rust_stricter_search":
        result.update(case_count=130, rust_stricter_rejections=[])
    elif kind == "positive_regression":
        result.update(case_count=65, acceptance_divergences=[])
    elif kind == "mutation_campaign_post_switch_differential":
        result.update(mutation_count=75, acceptance_divergences=[])
    elif kind == "critical_irv041":
        result.update(pre_lifecycle_python="ACCEPT", pre_lifecycle_rust="ACCEPT")
    elif kind in {"product_authority_provenance", "no_python_rescue", "lifecycle_boundary", "next_request_recovery"}:
        result.update(_product())
    elif kind in {"packaged_clean_consumer", "source_development_install", "platform_qualification", "python_compatibility"}:
        result.update(
            verifier_installed=True,
            checkout_imported=False,
            cargo_available=False,
            rustc_available=False,
            python_implementation="CPython",
            evidence={"passed": True, **_product()},
        )
    elif kind == "transport_continuity":
        result["rows"] = [
            {"requested_ssa_transport": value, "final_result": "PASS"}
            for value in ("in_process", "companion")
        ]
    elif kind == "deep_stress":
        result["exact_sizes"] = {"cases": 130}
    elif kind == "performance_characterization":
        result["correction_gate"] = False
    return result


def _write_manifest(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    records = []
    for index, (name, (job, kind, role)) in enumerate(check.EXPECTED.items(), 1):
        evidence = _evidence(kind, role, name)
        evidence_path = tmp_path / f"{name}.json"
        evidence_path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
        digest = sha256(evidence_path.read_bytes()).hexdigest()
        records.append({
            "id": index,
            "name": name,
            "source_job": job,
            "kind": kind,
            "role": role,
            "run_id": RUN_ID,
            "revision": REVISION,
            "github_digest": "sha256:" + f"{index:064x}",
            "zip_sha256": f"{index:064x}",
            "evidence_path": evidence_path.name,
            "evidence_sha256": digest,
        })
    manifest: dict[str, object] = {
        "artifact_schema_version": 1,
        "milestone": "RUST-IR-3",
        "workflow": check.WORKFLOW,
        "run_id": RUN_ID,
        "revision": REVISION,
        "run_conclusion": "success",
        "job_conclusions": {name: "success" for name in check.EXPECTED_JOBS},
        "artifacts": records,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path, manifest


def _rewrite(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _mutate_evidence(path: Path, manifest: dict[str, object], name: str, mutate) -> None:
    record = next(item for item in manifest["artifacts"] if item["name"] == name)  # type: ignore[index,union-attr]
    evidence_path = path.parent / record["evidence_path"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    mutate(evidence)
    evidence_path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
    record["evidence_sha256"] = sha256(evidence_path.read_bytes()).hexdigest()
    _rewrite(path, manifest)


def test_checker_accepts_complete_official_manifest(tmp_path: Path) -> None:
    path, _manifest = _write_manifest(tmp_path)
    result = check.check_manifest(path)
    assert result["decision"] == check.PROMOTED
    assert len(result["checked_artifacts"]) == 24


@pytest.mark.parametrize(
    ("name", "mutation"),
    [
        ("rust-ir-3-prerequisite", lambda value: value["checks"].update(official=False)),
        ("rust-ir-3-contract", lambda value: value.update(python_only_semantic_invariants=["IRV-X"])),
        ("rust-ir-3-false-negative", lambda value: value.update(false_negatives=[{"case_id": "bad"}])),
        ("rust-ir-3-rust-stricter", lambda value: value.update(rust_stricter_rejections=[{"case_id": "bad"}])),
        ("rust-ir-3-positive", lambda value: value.update(acceptance_divergences=[{"case_id": "bad"}])),
        ("rust-ir-3-mutations", lambda value: value.update(mutation_count=74)),
        ("rust-ir-3-irv041", lambda value: value.update(pre_lifecycle_rust="REJECT")),
        ("rust-ir-3-provenance", lambda value: value["product_authority_provenance"].update(product_authority="python")),
        ("rust-ir-3-no-rescue", lambda value: value["no_python_rescue"].update(python_rescue_attempted=True)),
        ("rust-ir-3-lifecycle", lambda value: value["product_authority_provenance"].update(python_lifecycle_calls=0)),
        ("rust-ir-3-packaged", lambda value: value.update(checkout_imported=True)),
        ("rust-ir-3-source", lambda value: value.update(verifier_installed=False)),
        ("rust-ir-3-recovery", lambda value: value["no_python_rescue"].update(next_valid_request_succeeds=False)),
        ("rust-ir-3-transport", lambda value: value.update(rows=[])),
        ("rust-ir-3-deep", lambda value: value.update(exact_sizes={"cases": 129})),
    ],
)
def test_checker_blocks_adversarial_semantic_evidence(
    tmp_path: Path,
    name: str,
    mutation,
) -> None:
    path, manifest = _write_manifest(tmp_path)
    _mutate_evidence(path, manifest, name, mutation)
    with pytest.raises(check.CheckFailure):
        check.check_manifest(path)


def test_checker_blocks_wrong_revision_kind_digest_and_missing_gate(tmp_path: Path) -> None:
    for field in ("revision", "kind", "zip_sha256"):
        directory = tmp_path / field
        directory.mkdir()
        path, manifest = _write_manifest(directory)
        record = manifest["artifacts"][0]  # type: ignore[index]
        record[field] = "wrong"
        _rewrite(path, manifest)
        with pytest.raises(check.CheckFailure):
            check.check_manifest(path)
    directory = tmp_path / "missing"
    directory.mkdir()
    path, manifest = _write_manifest(directory)
    manifest["artifacts"].pop()  # type: ignore[union-attr]
    _rewrite(path, manifest)
    with pytest.raises(check.CheckFailure):
        check.check_manifest(path)
