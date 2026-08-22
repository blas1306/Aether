from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from aether.ssa.shadow import SSALoweringAuthorityConfiguration, SSALoweringAuthorityMode


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_rust_ssa_production_stabilization.py"
PRODUCER = ROOT / "scripts/qualify_rust_ssa_production_stabilization.py"
REGRESSION_PRODUCER = ROOT / "scripts/qualify_rust_ssa_production_regressions.py"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Python 3.14's dataclass resolver requires an importable module entry.
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _phase(requests: int) -> dict[str, object]:
    return {
        "requested": requests,
        "completed": requests,
        "client_requests": requests,
        "process_startups": 1,
        "semantic_mismatches": 0,
        "infrastructure_failures": 0,
        "unclassified_failures": 0,
        "deterministic_output_mismatches": 0,
        "process_crashes_or_timeouts": 0,
        "poisoned_client_failures": 0,
        "rss_assessment": "STABLE",
    }


def test_inventory_expands_and_accounts_for_every_repository_program() -> None:
    producer = _module(PRODUCER, "rust_3_7a_producer")
    accepted, rows = producer.inventory()
    assert len(rows) > 169
    assert len(rows) == len(accepted) + sum(row["status"] == "REJECTED_BEFORE_SSA" for row in rows)
    assert [row["path"] for row in rows] == sorted(row["path"] for row in rows)
    assert any(row["path"] == "scrap/PFmio2.ae" for row in rows)
    rejected = [row for row in rows if row["status"] == "REJECTED_BEFORE_SSA"]
    assert all(row["stage"] and row["reason"] for row in rejected)


def test_aggregate_blocks_missing_evidence_and_preserves_authority_contract(tmp_path: Path) -> None:
    checker = _module(CHECKER, "rust_3_7a_checker_missing")
    regression_producer = _module(
        REGRESSION_PRODUCER, "rust_3_7a_regression_producer"
    )
    report = checker.build_record("revision", tmp_path)
    assert report["decision"] == "RUST_SSA_PRODUCTION_STABILIZATION_BLOCKED"
    assert report["historical_preservation"]["status"] == "PASS"
    assert report["schema_policy_freeze"]["status"] == "PASS"
    assert SSALoweringAuthorityConfiguration().mode is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
    # Pytest 9 may omit ``file`` and expose only a dotted classname in JUnit.
    # This minimized regression prevents all passing families being misreported
    # as uncollected, which was found during the first stabilization run.
    testcase = ET.fromstring(
        '<testcase classname="tests.aether.test_ssa_aggregate_ownership" name="test_one" />'
    )
    assert regression_producer._path(testcase) == (
        "tests/aether/test_ssa_aggregate_ownership.py"
    )


def test_exact_revision_complete_evidence_stabilizes(tmp_path: Path) -> None:
    checker = _module(CHECKER, "rust_3_7a_checker_complete")
    revision = "stabilization-revision"
    programs = [
        {"path": f"accepted-{index}.ae", "status": "ACCEPTED_BEFORE_SSA", "stage": "verified_initial_ir"}
        for index in range(141)
    ] + [
        {"path": f"rejected-{index}.ae", "status": "REJECTED_BEFORE_SSA", "stage": "typecheck_or_module_resolution", "reason": "unsupported"}
        for index in range(35)
    ]
    repeated = {**_phase(423), "rounds": 3, "programs_per_round": 141}
    concurrency = {**_phase(256), "callers": 16, "serialized_transport": True}
    _write(
        tmp_path / "operational.json",
        {
            "milestone": "RUST-3.7a",
            "qualification_revision": revision,
            "decision": "RUST_SSA_PRODUCTION_STABILIZATION_OPERATIONAL_PASS",
            "authority": {
                "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                "python_shadow": "synchronous_mandatory",
                "automatic_retries": False,
            },
            "corpus": {
                "discovered_programs": 176,
                "accepted_before_ssa": 141,
                "rejected_before_ssa": 35,
                "category_gate": "PASS",
                "missing_categories": [],
                "programs": programs,
            },
            "repeated_soak": repeated,
            "long_session": _phase(5000),
            "concurrency": concurrency,
        },
    )
    _write(
        tmp_path / "promotion_fixtures.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED",
            "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "gates": [{"id": f"V2-L{number:02d}", "status": "PASS"} for number in range(1, 6)],
        },
    )
    _write(
        tmp_path / "deep_cfg.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_AUTHORITY_DEEP_CFG_PASS",
            "cargo_workspace": {"status": "PASS"},
            "stress": {str(size): {"python": "PASS", "rust": "PASS"} for size in (993, 1000, 5000)},
        },
    )
    _write(
        tmp_path / "regressions.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_PRODUCTION_REGRESSIONS_PASS",
            "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "families": {name: {"status": "PASS", "tests": 1} for name in checker.REGRESSION_FAMILIES},
        },
    )
    _write(
        tmp_path / "full_suite.json",
        {
            "milestone": "RUST-3.7a",
            "qualification_revision": revision,
            "decision": "RUST_SSA_PRODUCTION_STABILIZATION_FULL_SUITE_PASS",
            "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "failed": 0,
            "semantic_mismatches": 0,
            "infrastructure_failures": 0,
            "environmental_failures": 0,
            "unclassified_test_failures": 0,
        },
    )
    for name, target in checker.PLATFORMS.items():
        _write(
            tmp_path / "platforms" / f"{name}.json",
            {
                "milestone": "RUST-3.7a",
                "revision": revision,
                "platform": name,
                "rust_target": target,
                "execution": "clean_release_artifact_outside_checkout",
                "provenance": "executed-native-runner",
                "representative_categories": sorted(checker.REPRESENTATIVE_CATEGORIES),
                "checks": {"all": "PASS"},
                "comparison": {
                    "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                    "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                    "default_returned_ssa_origin": "rust_schema_v2_import",
                    "modes_exercised": [mode.name for mode in SSALoweringAuthorityMode],
                    "returned_ssa_origins": ["rust_schema_v2_import"],
                    "fixture_mode_matrix_checks": 17,
                    "native_baseline_comparisons": 9,
                    "semantic_mismatches": 0,
                    "infrastructure_failures": 0,
                    "process_startups": 1,
                },
            },
        )
    report = checker.build_record(revision, tmp_path)
    assert report["decision"] == "RUST_SSA_PRODUCTION_STABILIZED"
    assert report["blockers"] == []
    assert all(gate["status"] == "PASS" for gate in report["gates"])
