from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_rust_ssa_authority_promotion_v2.py"
ARTIFACT = ROOT / "docs/compiler/rust_ssa_authority_promotion_v2.json"


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_3_6_v2_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _characterization_performance(revision: str) -> dict[str, object]:
    metadata = {
        "id": "representative",
        "path": "benchmarks/arithmetic.ae",
        "category": "tiny/scalar",
        "source_sha256": "a" * 64,
        "input_shape": {"functions": 2, "blocks": 7, "instructions": 52},
    }
    sample_modes = {
        "python_ssa_only": "python_ssa_only",
        "diagnostic_rust_only": "diagnostic_rust_authority_without_python_shadow",
        "rust_authority_python_shadow": "rust_authority_python_shadow",
    }
    samples = {
        mode: [
            {
                "mode": recorded_mode,
                "clock": "time.perf_counter",
                "phases_seconds": {"measured_phase": 0.25},
                "measured_component_sum_seconds": 0.25,
                "residual_unattributed_seconds": 0.05,
                "total_wall_seconds": 0.30,
                "rust_phase_detail": "observational test fixture",
            }
        ]
        for mode, recorded_mode in sample_modes.items()
    }
    summaries = {
        mode: {
            "samples": 1,
            "median_seconds": 0.30,
            "min_seconds": 0.30,
            "max_seconds": 0.30,
        }
        for mode in sample_modes
    }
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.7b",
        "decision": "RUST_SSA_PERFORMANCE_CHARACTERIZED",
        "qualification_revision": revision,
        "measurement_kind": "observational; no absolute timing is a semantic gate",
        "methodology": {
            "clock": "monotonic perf_counter / Rust Instant",
            "warmup_rounds_per_workload": 1,
            "measured_rounds_per_workload": 1,
            "statistics": ["median", "min", "max"],
            "production_timing_default": "disabled",
            "diagnostic_rust_only_is_authority_mode": False,
        },
        "workload_manifest": [metadata],
        "workloads": [
            {
                **metadata,
                "canonical_ssa_sha256": "b" * 64,
                "samples": samples,
                "summary": summaries,
            }
        ],
        "aggregates": {
            mode: {"representative_suite": summary}
            for mode, summary in summaries.items()
        },
    }


def test_pv2_g15_accepts_historical_observational_artifact() -> None:
    checker = _checker_module()
    revision = "promotion-revision"
    evidence = {
        "qualification_revision": revision,
        "measurement_kind": "observational; no timing assertion or absolute gate",
        "workloads": [{"name": "representative"}],
    }

    assert checker._performance_evidence_present(evidence, revision) is True


def test_pv2_g15_accepts_current_characterization_artifact() -> None:
    checker = _checker_module()
    revision = "promotion-revision"

    assert (
        checker._performance_evidence_present(
            _characterization_performance(revision), revision
        )
        is True
    )


def test_pv2_g15_accepts_post_3_8a_characterization_artifact() -> None:
    checker = _checker_module()
    revision = "post-3-8a-revision"
    evidence = _characterization_performance(revision)
    evidence["milestone"] = "RUST-3.8b"
    evidence["decision"] = "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED"

    assert checker._performance_evidence_present(evidence, revision) is True


def test_pv2_g15_blocks_characterization_for_wrong_revision() -> None:
    checker = _checker_module()

    assert (
        checker._performance_evidence_present(
            _characterization_performance("different-revision"),
            "promotion-revision",
        )
        is False
    )


def test_pv2_g15_blocks_missing_or_empty_characterization_samples() -> None:
    checker = _checker_module()
    revision = "promotion-revision"
    missing = _characterization_performance(revision)
    del missing["workloads"][0]["samples"]["python_ssa_only"]
    empty = _characterization_performance(revision)
    empty["workloads"][0]["samples"]["rust_authority_python_shadow"] = []

    assert checker._performance_evidence_present(missing, revision) is False
    assert checker._performance_evidence_present(empty, revision) is False


def test_pv2_g15_blocks_malformed_characterization_timings() -> None:
    checker = _checker_module()
    revision = "promotion-revision"
    evidence = _characterization_performance(revision)
    evidence["workloads"][0]["samples"]["diagnostic_rust_only"][0][
        "total_wall_seconds"
    ] = 99.0

    assert checker._performance_evidence_present(evidence, revision) is False


def test_pv2_g15_blocks_timings_without_workload_corpus_evidence() -> None:
    checker = _checker_module()
    revision = "promotion-revision"
    evidence = deepcopy(_characterization_performance(revision))
    evidence["workload_manifest"] = []
    evidence["workloads"] = []

    assert evidence["aggregates"]
    assert checker._performance_evidence_present(evidence, revision) is False


def test_promotion_v2_blocks_absent_or_pre_promotion_platform_evidence(
    tmp_path: Path,
) -> None:
    report = _checker_module().build_record("promotion-revision", tmp_path)
    assert report["decision"] == "RUST_SSA_AUTHORITY_PROMOTION_V2_FAILED"
    assert report["new_default"] == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
    assert all(row["status"] == "BLOCKED" for row in report["platforms"].values())
    assert report["scope"]["historical_artifacts_modified"] is False


def test_checked_in_local_evidence_reports_only_missing_native_runners() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert report["decision"] == "RUST_SSA_AUTHORITY_PROMOTION_V2_FAILED"
    assert report["blockers"] == ["PV2-G14"]
    assert report["platforms"]["linux-x86_64"]["status"] == "PASS"
    assert {
        name
        for name, row in report["platforms"].items()
        if row["status"] == "BLOCKED"
    } == {"windows-x86_64", "macos-arm64", "macos-x86_64"}
    assert report["full_suite"]["failed"] == 0
    assert report["scope"]["silent_fallback"] is False


def test_exact_revision_complete_evidence_promotes_v2(tmp_path: Path) -> None:
    checker = _checker_module()
    revision = "promotion-revision"
    _write(
        tmp_path / "promotion_fixtures.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED",
            "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "mandatory_fixture_count": 8,
            "gates": [
                {"id": f"V2-L{number:02d}", "status": "PASS"}
                for number in range(1, 6)
            ],
            "fixtures": [
                {"fixture": f"fixture-{number}", "status": "PASS"}
                for number in range(8)
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
                f"check-{number}": {"passed": 116, "failed": 0}
                for number in range(8)
            },
        },
    )
    _write(
        tmp_path / "soak.json",
        {
            "qualification_revision": revision,
            "decision": "RUST_SSA_AUTHORITY_SOAK_PASS",
            "authority": {
                "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
            },
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
            "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "failed": 0,
            "semantic_mismatches": 0,
            "infrastructure_failures": 0,
            "environmental_failures": 0,
            "unclassified_test_failures": 0,
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
            "authority_probe": {
                "production_default_origin": "rust_schema_v2_import",
                "python_authority_rollback_origin": "python_general_ssa_builder",
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
    categories = [
        "scalar",
        "numerical",
        "collections",
        "aggregate",
        "class_interface",
        "exception",
        "constructor_ownership",
        "function_value_indirect_call",
    ]
    for name, target in checker.PLATFORMS.items():
        _write(
            tmp_path / "platforms" / f"{name}.json",
            {
                "milestone": "RUST-3.6-V2",
                "revision": revision,
                "platform": name,
                "rust_target": target,
                "execution": "clean_release_artifact_outside_checkout",
                "provenance": "executed-native-runner",
                "mandatory_promotion_fixture_count": 8,
                "representative_categories": categories,
                "checks": {"all": "PASS"},
                "comparison": {
                    "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                    "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                    "default_returned_ssa_origin": "rust_schema_v2_import",
                    "modes_exercised": [
                        "PYTHON_SSA_ONLY",
                        "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
                        "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                    ],
                    "returned_ssa_origins": ["rust_schema_v2_import"],
                    "fixture_mode_matrix_checks": 16,
                    "native_baseline_comparisons": 8,
                    "semantic_mismatches": 0,
                    "infrastructure_failures": 0,
                },
            },
        )
    report = checker.build_record(revision, tmp_path)
    assert report["decision"] == "RUST_SSA_AUTHORITY_PROMOTED_V2"
    assert all(gate["status"] == "PASS" for gate in report["gates"])
