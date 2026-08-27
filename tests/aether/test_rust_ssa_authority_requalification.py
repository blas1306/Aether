from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    ROOT
    / "tests/fixtures/rust_ssa_promotion_failure/qualification_manifest.json"
)
CHECKER = ROOT / "scripts/check_rust_ssa_authority_requalification.py"


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_3_5b_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_manifest_maps_every_previous_root_cause_to_fixture_and_gate() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(
        (
            ROOT / "docs/compiler/rust_ssa_promotion_failure_root_cause_audit.json"
        ).read_text(encoding="utf-8")
    )
    causes = manifest["root_causes"]
    assert [row["id"] for row in causes] == [f"RC{number}" for number in range(1, 6)]
    assert [row["promotion_gate"] for row in causes] == [
        f"V2-L{number:02d}" for number in range(1, 6)
    ]
    fixtures = {relative for row in causes for relative in row["fixtures"]}
    historical = {
        relative
        for row in audit["root_causes"]
        if row["id"] != "RC6"
        for relative in row["minimized_reproducers"]
    }
    assert len(historical) == manifest["historical_minimized_fixture_count"] == 7
    assert historical < fixtures
    assert len(fixtures) == manifest["fixture_count"] == 8
    assert all((ROOT / relative).is_file() for relative in fixtures)
    assert "list_is_empty" in causes[0]["coverage"]


def test_requalification_is_evidence_only_and_blocks_missing_platforms(tmp_path: Path) -> None:
    _write(tmp_path / "promotion_fixtures.json", {"gates": "invalid"})
    _write(
        tmp_path / "platforms/linux-x86_64.json",
        {"checks": {}, "comparison": {"modes_exercised": None}},
    )
    report = _checker_module().build_record("revision-a", tmp_path)
    assert report["decision"] == "RUST_SSA_AUTHORITY_REQUALIFICATION_BLOCKED"
    assert len(report["expanded_gates"]) == 25
    assert [row["id"] for row in report["expanded_gates"][-5:]] == [
        f"V2-L{number:02d}" for number in range(1, 6)
    ]
    assert all(row["status"] == "BLOCKED" for row in report["platforms"].values())
    assert report["historical_preservation"]["status"] == "PASS"
    assert report["repository_default"] == "PYTHON_SSA_AUTHORITY_RUST_SHADOW"


def test_pre_promotion_checker_cannot_requalify_after_default_switch(tmp_path: Path) -> None:
    revision = "exact-revision"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixture_paths = sorted(
        {relative for row in manifest["root_causes"] for relative in row["fixtures"]}
    )
    _write(
        tmp_path / "promotion_fixtures.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED",
            "mandatory_fixture_count": 8,
            "historical_minimized_fixture_count": 7,
            "gates": [
                {"id": row["promotion_gate"], "status": "PASS"}
                for row in manifest["root_causes"]
            ],
            "fixtures": [
                {"fixture": relative, "status": "PASS"}
                for relative in fixture_paths
            ],
        },
    )
    _write(
        tmp_path / "historical.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_AUTHORITY_HISTORICAL_PASS",
            "accepted": 116,
            "expected": 116,
            "checks": {
                f"check-{index}": {"passed": 116, "failed": 0}
                for index in range(8)
            },
        },
    )
    _write(
        tmp_path / "soak.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_AUTHORITY_SOAK_PASS",
            "soak": {
                "accepted": 140,
                "shadow_compared": 140,
                "semantic_mismatches": 0,
                "infrastructure_failures": 0,
            },
        },
    )
    _write(
        tmp_path / "adversarial.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_LOWERING_ADVERSARIAL_QUALIFIED",
            "positive_case_count": 21,
            "negative_case_count": 7,
        },
    )
    _write(
        tmp_path / "deep_cfg.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_AUTHORITY_DEEP_CFG_PASS",
            "cargo_workspace": {"status": "PASS"},
            "stress": {
                str(size): {"python": "PASS", "rust": "PASS"}
                for size in (993, 1000, 5000)
            },
        },
    )
    _write(
        tmp_path / "full_suite.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_PASS",
            "mode": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
            "failed": 0,
            "real_semantic_failures": 0,
            "promotion_subset_rust_authority_failures": 0,
            "native_exception_ptrace_compatible": "54/54 PASS",
        },
    )
    _write(
        tmp_path / "operational.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_AUTHORITY_REQUALIFICATION_OPERATIONAL_PASS",
            "transport": {
                "persistent": "PASS",
                "same_input": "PASS",
                "fail_closed_semantic_mismatch": "PASS",
                "fail_closed_infrastructure": "PASS",
                "long_session": "1000 requests / 1 process",
                "concurrency": "128 requests / 1 process",
            },
            "rollback": {
                "configuration_only": True,
                "modes": [
                    "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
                    "PYTHON_SSA_ONLY",
                ],
            },
        },
    )
    _write(
        tmp_path / "performance.json",
        {
            "qualification_revision": revision,
            "measurement_kind": "observational; no timing assertion or absolute gate",
            "workloads": [{"name": "representative"}],
        },
    )
    for name, target in _checker_module().PLATFORMS.items():
        _write(
            tmp_path / "platforms" / f"{name}.json",
            {
                "milestone": "RUST-3.5b",
                "revision": revision,
                "platform": name,
                "rust_target": target,
                "execution": "clean_release_artifact_outside_checkout",
                "provenance": "executed-native-runner",
                "mandatory_promotion_fixture_count": 8,
                "checks": {"all": "PASS"},
                "comparison": {
                    "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                    "repository_default": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
                    "default_returned_ssa_origin": "python_general_ssa_builder",
                    "modes_exercised": [mode.name for mode in SSALoweringAuthorityMode],
                    "returned_ssa_origins": ["rust_schema_v2_import"],
                    "fixture_mode_matrix_checks": 14,
                    "semantic_mismatches": 0,
                    "infrastructure_failures": 0,
                },
            },
        )
    report = _checker_module().build_record(revision, tmp_path)
    assert report["decision"] == "RUST_SSA_AUTHORITY_REQUALIFICATION_BLOCKED"
    assert report["repository_default"] == "PYTHON_SSA_AUTHORITY_RUST_SHADOW"
    assert any(row["status"] == "BLOCKED" for row in report["expanded_gates"])


def test_safe_default_and_ci_directly_require_new_qualification_gates() -> None:
    assert (
        SSALoweringAuthorityConfiguration().mode
        is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED
    )
    workflow = (ROOT / ".github/workflows/rust-ssa-shadow.yml").read_text(
        encoding="utf-8"
    )
    assert "qualify_rust_ssa_authority_promotion_fixtures.py" in workflow
    assert "qualify_rust_ssa_authority_deep_cfg.py" in workflow
    assert "check_rust_ssa_authority_promotion_v2.py" in workflow
    assert "--require-promoted" in workflow
