from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
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


def test_inventory_accounts_for_exact_revision_tracked_programs() -> None:
    producer = _module(PRODUCER, "rust_3_7a_producer")
    accepted, rows = producer.inventory("HEAD")
    tracked = [producer._relative(path) for path in producer.discover_programs("HEAD")]
    assert len(rows) == 169
    assert [row["path"] for row in rows] == tracked
    assert len(rows) == len(accepted) + sum(row["status"] == "REJECTED_BEFORE_SSA" for row in rows)
    assert [row["path"] for row in rows] == sorted(row["path"] for row in rows)
    assert all(not row["path"].startswith("scrap/") for row in rows)
    rejected = [row for row in rows if row["status"] == "REJECTED_BEFORE_SSA"]
    assert all(row["stage"] and row["reason"] for row in rejected)


def test_untracked_and_ignored_sources_do_not_change_qualification_evidence(
    tmp_path: Path, monkeypatch,
) -> None:
    producer = _module(PRODUCER, "rust_3_7a_producer_reproducible")
    repository = tmp_path / "repository"
    tracked_source = (ROOT / "benchmarks/arithmetic.ae").read_text(encoding="utf-8")
    (repository / "benchmarks").mkdir(parents=True)
    (repository / "scripts").mkdir()
    (repository / ".gitignore").write_text("scrap/\n", encoding="utf-8")
    (repository / "benchmarks/arithmetic.ae").write_text(tracked_source, encoding="utf-8")
    (repository / producer.HISTORICAL_CORPUS_MANIFEST).write_text(
        "benchmarks/arithmetic.ae\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(repository), "-c", "user.name=Qualification Test",
            "-c", "user.email=qualification@example.invalid", "commit", "-qm", "fixture",
        ],
        check=True,
    )
    monkeypatch.setattr(producer, "ROOT", repository)

    def serial(programs, _executable, requests, *, expected=None, observe_rss=False):
        observed = dict(expected or {})
        for program in programs:
            observed.setdefault(producer._relative(program.path), program.source_sha256)
        return _phase(requests), observed

    def concurrent(_programs, _executable, requests, workers, _expected):
        return {**_phase(requests), "callers": workers, "serialized_transport": True}

    monkeypatch.setattr(producer, "_run_serial", serial)
    monkeypatch.setattr(producer, "_run_concurrent", concurrent)
    arguments = {
        "revision": "HEAD",
        "executable": repository / "unused-companion",
        "rounds": 3,
        "long_requests": 5_000,
        "concurrent_requests": 256,
        "callers": 16,
    }
    before = producer.generate(**arguments)

    # The qualification is tied to the requested commit, not working-tree blobs.
    (repository / "benchmarks/arithmetic.ae").write_text(
        "locally modified and intentionally invalid\n", encoding="utf-8"
    )
    (repository / "examples").mkdir()
    (repository / "examples/local-untracked.ae").write_text(tracked_source, encoding="utf-8")
    (repository / "scrap").mkdir()
    (repository / "scrap/local-ignored.ae").write_text(tracked_source, encoding="utf-8")
    after = producer.generate(**arguments)

    assert before == after
    assert before["corpus"]["discovered_programs"] == 1
    assert before["corpus"]["accepted_before_ssa"] + before["corpus"]["rejected_before_ssa"] == 1
    assert before["corpus"]["programs"] == after["corpus"]["programs"]


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
    revision = checker._resolved_revision("HEAD")
    tracked_paths = checker._tracked_program_paths(revision)
    assert len(tracked_paths) == 169
    programs = [
        {"path": path, "status": "ACCEPTED_BEFORE_SSA", "stage": "verified_initial_ir"}
        for path in tracked_paths[:140]
    ] + [
        {"path": path, "status": "REJECTED_BEFORE_SSA", "stage": "typecheck_or_module_resolution", "reason": "unsupported"}
        for path in tracked_paths[140:]
    ]
    repeated = {**_phase(420), "rounds": 3, "programs_per_round": 140}
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
                "discovery_roots": list(checker.DISCOVERY_ROOTS),
                "discovery_mechanism": "git_tree_exact_revision",
                "discovery_revision": revision,
                "ignored_and_untracked_excluded": True,
                "historical_manifest": checker.HISTORICAL_CORPUS_MANIFEST.as_posix(),
                "historical_discovered": 169,
                "historical_programs_included": 169,
                "missing_historical_programs": [],
                "eligible_tracked_programs": 169,
                "discovered_programs": 169,
                "accepted_before_ssa": 140,
                "rejected_before_ssa": 29,
                "source_set_gate": "PASS",
                "coverage_contract": "PASS",
                "unaccounted_tracked_programs": [],
                "unexpected_programs": [],
                "category_gate": "PASS",
                "missing_categories": [],
                "accepted_category_paths": {
                    category: [tracked_paths[0]]
                    for category in checker.REQUIRED_CORPUS_CATEGORIES
                },
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
