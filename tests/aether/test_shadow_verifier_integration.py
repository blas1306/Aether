from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.ir_verifier import (
    CORPUS_MANIFEST,
    CRITICAL_DIFFERENTIAL_CASES,
    _load_manifest,
    _materialize_modules,
)
from aether.ir import (
    CollectingShadowReportSink,
    IRBasicBlock,
    IRFunction,
    IRModule,
    IRReturn,
    IRVerificationError,
    PythonShadowRejected,
    ShadowClassification,
    ShadowRustSkipped,
    ShadowVerificationStage,
    ShadowVerifierCoordinator,
    VerifierCategory,
    VoidType,
    build_canonical_rust_verifier_request,
    compare_shadow_outcomes,
)
from aether.ir.rust_verifier import (
    SubprocessRustVerifierClient,
    discover_rust_verifier_executable,
)
from aether.ir.shadow_divergences import ExactShadowDivergenceRegistry


NONTRANSPORTABLE_CASES = {
    "lifecycle-non-storage-destination": "storage_shape",
    "integer-constant-out-of-range": "signed_i32_constant",
}


@pytest.fixture(scope="module")
def rust_verifier_executable() -> Path:
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    subprocess.run(
        [cargo, "build", "-p", "aether-ir-verifier"],
        cwd=REPOSITORY_ROOT / "compiler-rs",
        check=True,
    )
    return discover_rust_verifier_executable(
        search_path=False,
        repository_root=REPOSITORY_ROOT,
    )


def _accepted_module() -> IRModule:
    return IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            )
        ]
    )


def _rejected_module() -> IRModule:
    return IRModule(
        [IRFunction("main", [], VoidType(), [IRBasicBlock("entry", [])])]
    )


def _run(
    module: IRModule,
    client: SubprocessRustVerifierClient,
) -> tuple[object, CollectingShadowReportSink]:
    sink = CollectingShadowReportSink()
    coordinator = ShadowVerifierCoordinator(client=client, sink=sink)
    try:
        result: object = coordinator.verify(module)
    except IRVerificationError as error:
        result = error
    return result, sink


def test_real_subprocess_acceptance_rejection_and_determinism(
    rust_verifier_executable: Path,
) -> None:
    client = SubprocessRustVerifierClient(executable=rust_verifier_executable)

    accepted, accepted_sink = _run(_accepted_module(), client)
    rejected, rejected_sink = _run(_rejected_module(), client)
    _, repeated_sink = _run(_rejected_module(), client)

    assert isinstance(accepted, IRModule)
    assert isinstance(rejected, IRVerificationError)
    assert (
        accepted_sink.reports[0].comparison.classification
        is ShadowClassification.MATCH_ACCEPTED
    )
    assert (
        rejected_sink.reports[0].comparison.classification
        is ShadowClassification.MATCH_REJECTED_SEMANTIC
    )
    assert (
        rejected_sink.reports[0].semantic_snapshot()
        == repeated_sink.reports[0].semantic_snapshot()
    )


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (
            "import sys; sys.stdin.buffer.read(); raise SystemExit(7)",
            ShadowClassification.RUST_INTEGRATION_FAILURE,
        ),
        (
            "import sys; sys.stdin.buffer.read(); sys.stdout.write('not json\\n')",
            ShadowClassification.RUST_INTEGRATION_FAILURE,
        ),
        (
            "import sys,time; sys.stdin.buffer.read(); time.sleep(1)",
            ShadowClassification.RUST_INTEGRATION_FAILURE,
        ),
        (
            "import sys; sys.stdin.buffer.read(); "
            "sys.stdout.write('{\"protocol_version\":1,\"status\":\"error\","
            "\"error\":{\"kind\":\"internal\",\"message\":\"safe\"}}\\n')",
            ShadowClassification.RUST_INFRASTRUCTURE_FAILURE,
        ),
    ],
)
def test_real_subprocess_failures_remain_observational(
    script: str,
    expected: ShadowClassification,
) -> None:
    client = SubprocessRustVerifierClient(
        executable=[sys.executable, "-c", script],
        timeout_seconds=0.2,
        validate_startup=False,
    )
    module = _accepted_module()

    result, sink = _run(module, client)

    assert result is module
    assert sink.reports[0].comparison.classification is expected


def test_full_transportable_corpus_shadow_baseline(
    rust_verifier_executable: Path,
) -> None:
    schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    materialized = _materialize_modules(entries)
    client = SubprocessRustVerifierClient(executable=rust_verifier_executable)
    sink = CollectingShadowReportSink()
    coordinator = ShadowVerifierCoordinator(client=client, sink=sink)

    for entry, module in materialized:
        if entry.id in NONTRANSPORTABLE_CASES:
            continue
        try:
            coordinator.verify(module, stage=ShadowVerificationStage.EXTERNAL)
        except IRVerificationError:
            pass

    counts = Counter(
        report.comparison.classification for report in sink.reports
    )
    assert schema_version == 2
    assert len(sink.reports) == 140
    assert counts == Counter(
        {
            ShadowClassification.MATCH_ACCEPTED: 65,
            ShadowClassification.MATCH_REJECTED_SEMANTIC: 72,
            ShadowClassification.DOCUMENTED_DIAGNOSTIC_DIVERGENCE: 3,
        }
    )


def test_irv_024_transport_and_shadow_snapshot_are_deterministic(
    rust_verifier_executable: Path,
) -> None:
    _, entries = _load_manifest(CORPUS_MANIFEST)
    entry = next(
        entry for entry in entries if entry.id == "non-void-path-without-return"
    )
    [(materialized_entry, module)] = _materialize_modules([entry])
    client = SubprocessRustVerifierClient(executable=rust_verifier_executable)
    first_request = build_canonical_rust_verifier_request(module)
    second_request = build_canonical_rust_verifier_request(module)
    request_hash = sha256(first_request.payload).hexdigest()
    snapshots = []

    assert materialized_entry.accepted
    assert first_request == second_request
    assert first_request.protocol_version == 1
    assert first_request.ir_schema_version == 1

    for _attempt in range(2):
        result, sink = _run(module, client)
        report = sink.reports[0]
        assert result is module
        assert (
            report.comparison.classification
            is ShadowClassification.MATCH_ACCEPTED
        )
        assert report.metadata.request_sha256 == request_hash
        snapshots.append(report.semantic_snapshot())

    assert snapshots[0] == snapshots[1]


def test_critical_differential_corpus_is_transportable_semantic_and_deterministic(
    rust_verifier_executable: Path,
) -> None:
    schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    critical_entries = [
        entry for entry in entries if entry.id in CRITICAL_DIFFERENTIAL_CASES
    ]
    materialized = _materialize_modules(critical_entries)
    client = SubprocessRustVerifierClient(executable=rust_verifier_executable)
    request_hashes: set[str] = set()

    assert schema_version == 2
    assert {entry.id for entry in critical_entries} == set(
        CRITICAL_DIFFERENTIAL_CASES
    )
    for entry, module in materialized:
        first_request = build_canonical_rust_verifier_request(module)
        second_request = build_canonical_rust_verifier_request(module)
        request_hash = sha256(first_request.payload).hexdigest()
        request_hashes.add(request_hash)

        assert first_request == second_request
        assert first_request.protocol_version == 1
        assert first_request.ir_schema_version == 1

        snapshots = []
        for _attempt in range(2):
            sink = CollectingShadowReportSink()
            coordinator = ShadowVerifierCoordinator(client=client, sink=sink)
            with pytest.raises(IRVerificationError) as raised:
                coordinator.verify(
                    module,
                    stage=ShadowVerificationStage.EXTERNAL,
                )
            failure = raised.value.normalized_failure
            assert failure is not None
            assert (
                failure.invariant_id
                == CRITICAL_DIFFERENTIAL_CASES[entry.id]
            )
            report = sink.reports[0]
            assert (
                report.comparison.classification
                is ShadowClassification.MATCH_REJECTED_SEMANTIC
            )
            assert report.metadata.request_sha256 == request_hash
            snapshots.append(report.semantic_snapshot())

        assert snapshots[0] == snapshots[1]

    assert len(request_hashes) == len(CRITICAL_DIFFERENTIAL_CASES)


def test_nontransportable_cases_are_explicit_harness_skips() -> None:
    registry = ExactShadowDivergenceRegistry()
    classifications = []
    cases = (
        (
            PythonShadowRejected("IRV-043", VerifierCategory.LIFECYCLE),
            NONTRANSPORTABLE_CASES["lifecycle-non-storage-destination"],
        ),
        (
            PythonShadowRejected("IRV-069", VerifierCategory.CONSTANTS),
            NONTRANSPORTABLE_CASES["integer-constant-out-of-range"],
        ),
    )
    for authoritative, reason in cases:
        comparison = compare_shadow_outcomes(
            authoritative,
            ShadowRustSkipped(reason),
            request_hash="",
            registry=registry,
            protocol_version=1,
            ir_schema_version=1,
        )
        classifications.append(comparison.classification)

    assert classifications == [
        ShadowClassification.SHADOW_SKIPPED,
        ShadowClassification.SHADOW_SKIPPED,
    ]
