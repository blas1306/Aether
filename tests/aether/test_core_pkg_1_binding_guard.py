from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REVISION = "b219d60d1afe38bea560495536401e9997a4ea5a"


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _production(ci_run_id: str = "LOCAL_PRE_CI") -> dict[str, object]:
    return {
        "artifact_schema_version": 1,
        "kind": "core_1_0a_production",
        "milestone": "CORE-1.0A",
        "status": "PASS",
        "exact_revision": REVISION,
        "ci_run_id": ci_run_id,
        "worktree_clean": True,
        "qualification_only": True,
        "production_default_changed": False,
        "companion_remains_production_and_rollback": True,
        "automatic_fallback": False,
        "production_regression_gates": {
            "differential_python_shadow": True,
            "lifecycle": True,
            "persistent_companion": True,
            "protocol_v1": True,
            "rollback_modes": True,
            "rust_4_5_default_policy": True,
            "rust_ssa_output": True,
            "structured_failure_and_locations": True,
            "verification_and_refinement": True,
        },
        "shared_core_guards": {
            "companion_calls_compiler_core": True,
            "core_not_coupled_to_pyo3": True,
            "in_process_not_in_default_selector": True,
            "pyo3_calls_compiler_core": True,
        },
        "default_companion": {
            "identity_and_protocol_v1": "PASS",
            "response_shape_preserved": True,
            "persistent_process_starts": 1,
            "repeated_result_equal": True,
        },
    }


def _checked(
    tmp_path: Path, ci_run_id: str = "LOCAL_PRE_CI"
) -> tuple[Path, Path, dict[str, object]]:
    checker = _load("core_1_0a_production_checker", "scripts/check_core_1_0a_in_process.py")
    upstream_path = tmp_path / "core-1-0a-production.json"
    upstream_path.write_text(
        json.dumps(_production(ci_run_id), sort_keys=True) + "\n", encoding="utf-8"
    )
    checked, errors = checker.check_production(upstream_path)
    assert errors == []
    check_path = tmp_path / "core-1-0a-production-check.json"
    check_path.write_text(json.dumps(checked, sort_keys=True) + "\n", encoding="utf-8")
    return upstream_path, check_path, checked


def test_production_checker_validates_without_relabeling_core_1_0a(tmp_path: Path) -> None:
    upstream_path, _check_path, checked = _checked(tmp_path)
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    assert upstream["kind"] == "core_1_0a_production"
    assert upstream["milestone"] == "CORE-1.0A"
    assert upstream["qualification_only"] is True
    assert checked["kind"] == "core_1_0a_production_check"
    assert checked["decision"] == "CORE_IN_PROCESS_PRODUCTION_GUARD_QUALIFIED"
    assert checked["ci_run_id"] == "LOCAL_PRE_CI"


def test_projection_creates_core_pkg_1_evidence_with_upstream_provenance(tmp_path: Path) -> None:
    projector = _load("core_pkg_1_binding_projector", "scripts/project_core_pkg_1_binding_guard.py")
    upstream_path, check_path, _checked_value = _checked(tmp_path)
    binding = projector.project(
        upstream_path,
        check_path,
        revision=REVISION,
        ci_run_id="LOCAL_PRE_CI",
        installed_binding={
            "qualification_only": False,
            "protocol_version": 1,
            "compiler_core_constructed": True,
        },
    )
    assert binding["kind"] == "core_pkg_1_binding_smoke"
    assert binding["milestone"] == "CORE-PKG-1"
    assert binding["status"] == "PASS"
    assert binding["upstream_evidence"]["kind"] == "core_1_0a_production"
    assert binding["upstream_evidence"]["milestone"] == "CORE-1.0A"
    assert binding["upstream_evidence"]["qualification_only"] is True
    assert binding["production_default_changed"] is False
    assert binding["automatic_fallback"] is False


def test_projection_rejects_revision_mismatch(tmp_path: Path) -> None:
    projector = _load("core_pkg_1_binding_projector_mismatch", "scripts/project_core_pkg_1_binding_guard.py")
    upstream_path, check_path, _checked_value = _checked(tmp_path)
    with pytest.raises(ValueError, match="revision does not match"):
        projector.project(
            upstream_path,
            check_path,
            revision="0" * 40,
            ci_run_id="LOCAL_PRE_CI",
            installed_binding={
                "qualification_only": False,
                "protocol_version": 1,
                "compiler_core_constructed": True,
            },
        )


def test_aggregate_rejects_local_or_tampered_binding_provenance_in_ci(tmp_path: Path) -> None:
    projector = _load("core_pkg_1_binding_projector_for_aggregate", "scripts/project_core_pkg_1_binding_guard.py")
    aggregate_checker = _load("core_pkg_1_checker_binding", "scripts/check_core_pkg_1_native_distribution.py")
    upstream_path, check_path, _checked_value = _checked(tmp_path)
    binding = projector.project(
        upstream_path,
        check_path,
        revision=REVISION,
        ci_run_id="LOCAL_PRE_CI",
        installed_binding={
            "qualification_only": False,
            "protocol_version": 1,
            "compiler_core_constructed": True,
        },
    )
    errors: list[str] = []
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding, sort_keys=True) + "\n", encoding="utf-8")
    aggregate_checker._binding_guard(
        binding, evidence_dir=tmp_path, ci_closure=True, errors=errors
    )
    assert "binding evidence CI run provenance is missing or local" in errors

    binding["ci_run_id"] = "33188797944"
    binding["upstream_evidence"]["ci_run_id"] = "33188797944"
    binding["production_default_changed"] = True
    errors = []
    aggregate_checker._binding_guard(
        binding, evidence_dir=tmp_path, ci_closure=True, errors=errors
    )
    assert "production default changed" in errors


def test_complete_ci_aggregate_requires_and_accepts_exact_binding_provenance(
    tmp_path: Path,
) -> None:
    ci_run_id = "NEXT_RUN_TEST"
    projector = _load("core_pkg_1_binding_projector_complete", "scripts/project_core_pkg_1_binding_guard.py")
    aggregate_checker = _load("core_pkg_1_checker_complete", "scripts/check_core_pkg_1_native_distribution.py")
    upstream_path, check_path, _checked_value = _checked(tmp_path, ci_run_id)
    binding = projector.project(
        upstream_path,
        check_path,
        revision=REVISION,
        ci_run_id=ci_run_id,
        installed_binding={
            "qualification_only": False,
            "protocol_version": 1,
            "compiler_core_constructed": True,
        },
    )
    (tmp_path / "binding.json").write_text(
        json.dumps(binding, sort_keys=True) + "\n", encoding="utf-8"
    )
    for filename, kind in {
        "companion.json": "core_pkg_1_companion_smoke",
        "contract.json": "core_pkg_1_contract",
        "failures.json": "core_pkg_1_failure_campaign",
        "source.json": "core_pkg_1_source_development",
    }.items():
        (tmp_path / filename).write_text(
            json.dumps({"kind": kind, "status": "PASS"}) + "\n",
            encoding="utf-8",
        )

    def matrix_row(*, platform: str, python_minor: str, role: str) -> dict[str, object]:
        return {
            "kind": "core_pkg_1_platform",
            "matrix_role": role,
            "platform": platform,
            "python_minor": python_minor,
            "decision": "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_PENDING_CI",
            "native_wheel": {
                "distribution": "aether-compiler-core",
                "version": "1.0.0rc4",
                "contains_binding": True,
                "contains_companion": True,
                "contains_native_manifest": True,
                "sha256": "a" * 64,
            },
            "language_wheel": {
                "distribution": "aether-language",
                "requires_exact_native_core": True,
            },
            "clean_consumer": {
                "status": "PASS",
                "consumer": {"cargo_available": False, "rustc_available": False},
                "binding": {"qualification_only": False},
                "production_transport": {"is_companion_client": True},
            },
        }

    for platform in sorted(aggregate_checker.PLATFORMS):
        row = matrix_row(platform=platform, python_minor="3.13", role="platform")
        (tmp_path / f"platform-{platform}.json").write_text(
            json.dumps(row) + "\n", encoding="utf-8"
        )
    for python_minor in sorted(aggregate_checker.PYTHONS):
        row = matrix_row(
            platform="linux-x86_64",
            python_minor=python_minor,
            role="python_compatibility",
        )
        (tmp_path / f"python-{python_minor}.json").write_text(
            json.dumps(row) + "\n", encoding="utf-8"
        )

    aggregate, errors = aggregate_checker.check(tmp_path, ci_closure=True)
    assert errors == []
    assert aggregate["decision"] == "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
    assert aggregate["exact_revision"] == REVISION
    assert aggregate["ci_run_id"] == ci_run_id
    assert aggregate["production_transport"] == "companion"
    assert aggregate["in_process_promoted"] is False


def test_binding_workflow_checks_upstream_before_uploading_core_pkg_evidence() -> None:
    workflow = (ROOT / ".github/workflows/core-native-packaging.yml").read_text(encoding="utf-8")
    binding_job = workflow[workflow.index("  binding-installed-smoke:"):workflow.index("  source-development-install:")]
    assert "pip install 'maturin>=1.9.4,<2' pytest -r requirements.txt" in binding_job
    assert "--production-only" in binding_job
    assert "--revision \"${{ github.sha }}\"" in binding_job
    assert "--ci-run-id \"${{ github.run_id }}\"" in binding_job
    assert "--production-evidence" in binding_job
    assert "project_core_pkg_1_binding_guard.py" in binding_job
    assert binding_job.index("--production-evidence") < binding_job.index("project_core_pkg_1_binding_guard.py")
    assert binding_job.index("project_core_pkg_1_binding_guard.py") < binding_job.index("actions/upload-artifact@v4")
