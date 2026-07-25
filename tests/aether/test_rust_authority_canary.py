from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from benchmarks.ir_verifier import (
    CORPUS_MANIFEST,
    CRITICAL_DIFFERENTIAL_CASES,
    _load_manifest,
    _materialize_modules,
)
from aether.ir import (
    AuthoritativeVerifierRejected,
    PythonShadowAccepted,
    ShadowClassification,
    ShadowComparison,
    ShadowOperationalMetadata,
    ShadowRustAccepted,
    ShadowRustInfrastructureFailure,
    ShadowRustIntegrationFailure,
    ShadowVerificationReport,
    ShadowVerificationStage,
    VerifierAuthorityEnvironment,
    VerifierAuthorityMode,
)
from aether.pipeline import IRBackend, prepare_typed_program
from aether.typechecker import TypeChecker
from rust_authority_canary_harness import (
    RustAuthorityCanaryConfiguration,
    RustAuthorityCanaryHarness,
)


REPOSITORY_ROOT = Path(__file__).parents[2]
CANARY_CONFIGURATION = (
    REPOSITORY_ROOT / "tests" / "canary" / "rust_verifier_canary.json"
)
NONTRANSPORTABLE_CASES = frozenset(
    {
        "lifecycle-non-storage-destination",
        "integer-constant-out-of-range",
    }
)


def _verify_canary_module(
    harness: RustAuthorityCanaryHarness,
    module: object,
) -> None:
    try:
        harness.pipeline.verify(module)  # type: ignore[arg-type]
    except AuthoritativeVerifierRejected:
        pass


def test_canary_configuration_is_explicit_closed_and_deterministic(
    tmp_path: Path,
) -> None:
    first = RustAuthorityCanaryConfiguration.load(CANARY_CONFIGURATION)
    second = RustAuthorityCanaryConfiguration.load(CANARY_CONFIGURATION)

    assert first == second
    assert first.snapshot() == second.snapshot()
    assert (
        first.authority_configuration.mode
        is VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
    )
    assert (
        first.authority_configuration.environment
        is VerifierAuthorityEnvironment.CANARY
    )
    assert first.authority_configuration.is_canary

    invalid = first.snapshot()
    invalid["environment"] = "default"
    invalid_path = tmp_path / "invalid-canary.json"
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match="requires environment='canary'",
    ):
        RustAuthorityCanaryConfiguration.load(invalid_path)


def test_canary_monitoring_summary_counts_all_required_failure_classes(
    tmp_path: Path,
) -> None:
    configuration = RustAuthorityCanaryConfiguration.load(
        CANARY_CONFIGURATION
    )
    harness = RustAuthorityCanaryHarness(
        configuration=configuration,
        executable=tmp_path / "not-executed",
    )
    observations = (
        (
            ShadowRustAccepted(),
            ShadowClassification.MATCH_ACCEPTED,
            None,
        ),
        (
            ShadowRustIntegrationFailure("timeout", "bounded"),
            ShadowClassification.RUST_INTEGRATION_FAILURE,
            "timeout",
        ),
        (
            ShadowRustInfrastructureFailure("invalid_request", "bounded"),
            ShadowClassification.RUST_INFRASTRUCTURE_FAILURE,
            "invalid_request",
        ),
        (
            ShadowRustIntegrationFailure(
                "incompatible_executable",
                "bounded",
            ),
            ShadowClassification.RUST_INTEGRATION_FAILURE,
            "incompatible_executable",
        ),
    )
    for index, (rust_outcome, classification, failure_kind) in enumerate(
        observations
    ):
        harness.sink.emit(
            ShadowVerificationReport(
                authoritative=rust_outcome,
                shadow=PythonShadowAccepted(),
                comparison=ShadowComparison(
                    classification,
                    ("accepted",),
                    ("accepted",),
                ),
                metadata=ShadowOperationalMetadata(
                    request_sha256=f"{index:064x}",
                    client_kind="subprocess",
                    protocol_version=1,
                    ir_schema_version=1,
                    stage=ShadowVerificationStage.EXTERNAL,
                    serialization_duration_seconds=None,
                    rust_invocation_duration_seconds=None,
                    total_shadow_duration_seconds=None,
                    failure_kind=failure_kind,
                    failure_summary=None,
                ),
            )
        )

    first = harness.summary(population="migration_corpus")
    second = harness.summary(population="migration_corpus")

    assert first == second
    assert first["modules"] == {
        "total": 4,
        "accepted": 1,
        "rejected": 0,
        "unavailable": 3,
        "distinct_request_hashes": 4,
    }
    assert first["comparisons"]["total"] == 4  # type: ignore[index]
    assert first["failures"] == {
        "timeout_count": 1,
        "infrastructure_failures": 3,
        "protocol_failures": 1,
        "startup_failures": 1,
        "integration_failures": 2,
        "by_kind": {
            "incompatible_executable": 1,
            "invalid_request": 1,
            "timeout": 1,
        },
    }


def test_canary_migration_corpus_uses_real_rust_authority(
    rust_authority_canary: RustAuthorityCanaryHarness,
) -> None:
    schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    materialized = [
        (entry, module)
        for entry, module in _materialize_modules(entries)
        if entry.id not in NONTRANSPORTABLE_CASES
    ]
    start = len(rust_authority_canary.sink.reports)

    for _entry, module in materialized:
        _verify_canary_module(rust_authority_canary, module)

    reports = rust_authority_canary.sink.reports[start:]
    classifications = Counter(
        report.comparison.classification for report in reports
    )
    assert schema_version == 2
    assert len(reports) == 141
    assert classifications == Counter(
        {
            ShadowClassification.MATCH_ACCEPTED: 65,
            ShadowClassification.MATCH_REJECTED_SEMANTIC: 73,
            ShadowClassification.DOCUMENTED_DIAGNOSTIC_DIVERGENCE: 3,
        }
    )


def test_canary_differential_corpus_uses_real_rust_authority(
    rust_authority_canary: RustAuthorityCanaryHarness,
) -> None:
    _schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    critical_entries = [
        entry for entry in entries if entry.id in CRITICAL_DIFFERENTIAL_CASES
    ]
    start = len(rust_authority_canary.sink.reports)

    for _entry, module in _materialize_modules(critical_entries):
        _verify_canary_module(rust_authority_canary, module)

    reports = rust_authority_canary.sink.reports[start:]
    assert len(reports) == len(CRITICAL_DIFFERENTIAL_CASES)
    assert all(
        report.comparison.classification
        is ShadowClassification.MATCH_REJECTED_SEMANTIC
        for report in reports
    )


def test_canary_compiler_examples_use_real_rust_authority(
    rust_authority_canary: RustAuthorityCanaryHarness,
) -> None:
    example_paths = sorted((REPOSITORY_ROOT / "examples" / "ir").glob("*.ae"))
    start = len(rust_authority_canary.sink.reports)

    for path in example_paths:
        source = path.read_text(encoding="utf-8")
        typed = prepare_typed_program(
            source,
            TypeChecker(source_root=path.parent, entry_path=path),
        )
        backend = IRBackend(shadow_verifier=rust_authority_canary.pipeline)
        backend.run(typed)

    reports = rust_authority_canary.sink.reports[start:]
    assert [path.name for path in example_paths] == [
        "constant_fold.ae",
        "local_const.ae",
        "sumTo.ae",
    ]
    assert len(reports) == len(example_paths)
    assert all(
        report.comparison.classification
        is ShadowClassification.MATCH_ACCEPTED
        for report in reports
    )
