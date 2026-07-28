from __future__ import annotations

from collections import Counter
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
    CorpusComparison,
    _load_manifest,
    _materialize_modules,
    compare_verifier_observations,
)
from aether.ir import (
    IRBasicBlock,
    IRFunction,
    IRModule,
    IRReturn,
    IntType,
    MethodResultType,
    RustVerifierAcceptedOutcome,
    RustVerifierAccepted,
    RustVerifierAdapterError,
    RustVerifierInfrastructureFailure,
    RustVerifierProtocolError,
    RustVerifierProtocolErrorKind,
    RustVerifierRejectedOutcome,
    RustVerifierRejected,
    VoidType,
    build_canonical_rust_verifier_request,
    discover_rust_verifier_executable,
    verify_module_with_rust,
)
from aether.ir.dto import ir_module_to_dto
from aether.ir.rust_verifier import SubprocessRustVerifierClient


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


def _import_failure_module() -> IRModule:
    invalid_method_result = MethodResultType(IntType(), IntType())  # type: ignore[arg-type]
    return IRModule([IRFunction("main", [], invalid_method_result, [])])


def test_real_executable_accepts_rejects_and_returns_protocol_errors(
    rust_verifier_executable: Path,
) -> None:
    accepted = verify_module_with_rust(
        _accepted_module(), executable=rust_verifier_executable
    )
    rejected = verify_module_with_rust(
        _rejected_module(), executable=rust_verifier_executable
    )
    protocol_error = verify_module_with_rust(
        _import_failure_module(), executable=rust_verifier_executable
    )

    assert accepted == RustVerifierAccepted()
    assert isinstance(rejected, RustVerifierRejected)
    assert rejected.diagnostic.invariant == "IRV-018"
    assert protocol_error == RustVerifierProtocolError(
        RustVerifierProtocolErrorKind.MODULE_IMPORT,
        "canonical Initial IR module cannot be imported by the Rust IR model",
    )
    assert accepted.transport.stderr == b""
    assert rejected.transport.stderr == b""
    assert protocol_error.transport.stderr == b""


def test_real_executable_results_are_deterministic(
    rust_verifier_executable: Path,
) -> None:
    module = _rejected_module()

    first = verify_module_with_rust(module, executable=rust_verifier_executable)
    second = verify_module_with_rust(module, executable=rust_verifier_executable)

    assert first == second


def test_all_transportable_corpus_cases_cross_the_adapter_with_expected_parity(
    rust_verifier_executable: Path,
) -> None:
    schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    modules = _materialize_modules(entries)
    by_id = {entry.id: module for entry, module in modules}
    excluded = {
        entry.id: by_id[entry.id]
        for entry in entries
        if entry.id in NONTRANSPORTABLE_CASES
    }
    transportable = [
        (entry, by_id[entry.id])
        for entry in entries
        if entry.id not in NONTRANSPORTABLE_CASES
    ]

    assert schema_version == 2
    assert set(excluded) == set(NONTRANSPORTABLE_CASES)
    for module in excluded.values():
        with pytest.raises((TypeError, ValueError)):
            ir_module_to_dto(module)

    client = SubprocessRustVerifierClient(executable=rust_verifier_executable)
    compatibility_counts: Counter[str] = Counter()
    client_counts: Counter[str] = Counter()
    expectation_mismatches: list[str] = []
    for entry, module in transportable:
        try:
            result = verify_module_with_rust(
                module,
                executable=rust_verifier_executable,
            )
        except RustVerifierAdapterError:
            compatibility_counts["adapter_failures"] += 1
            continue
        if isinstance(result, RustVerifierProtocolError):
            compatibility_counts["protocol_errors"] += 1
            continue

        rust_accepted = isinstance(result, RustVerifierAccepted)
        rust_invariant = (
            result.diagnostic.invariant
            if isinstance(result, RustVerifierRejected)
            else None
        )
        comparison = compare_verifier_observations(
            entry,
            python_accepted=entry.accepted,
            python_invariant=entry.expected_invariant,
            rust_accepted=rust_accepted,
            rust_invariant=rust_invariant,
        )
        if comparison is None:
            compatibility_counts["accepted_by_both"] += 1
        else:
            compatibility_counts[comparison.value] += 1

        try:
            invocation = client.verify(
                build_canonical_rust_verifier_request(module)
            )
        except RustVerifierAdapterError:
            client_counts["adapter_failures"] += 1
            continue
        if isinstance(invocation.outcome, RustVerifierInfrastructureFailure):
            client_counts["infrastructure_failures"] += 1
            continue

        client_accepted = isinstance(
            invocation.outcome,
            RustVerifierAcceptedOutcome,
        )
        client_invariant = (
            invocation.outcome.diagnostic.invariant_id
            if isinstance(invocation.outcome, RustVerifierRejectedOutcome)
            else None
        )
        client_comparison = compare_verifier_observations(
            entry,
            python_accepted=entry.accepted,
            python_invariant=entry.expected_invariant,
            rust_accepted=client_accepted,
            rust_invariant=client_invariant,
        )
        if client_comparison is None:
            client_counts["accepted_by_both"] += 1
        else:
            client_counts[client_comparison.value] += 1
        assert (client_accepted, client_invariant) == (
            rust_accepted,
            rust_invariant,
        )

        expected_rust_accepted = (
            entry.expected_rust_outcome == "accepted"
            if entry.expected_rust_outcome is not None
            else entry.accepted
        )
        expected_rust_invariant = (
            entry.expected_rust_invariant or entry.expected_invariant
        )
        if (
            rust_accepted != expected_rust_accepted
            or (
                not rust_accepted
                and rust_invariant != expected_rust_invariant
            )
        ):
            expectation_mismatches.append(entry.id)

    assert len(transportable) == 140
    expected_counts = Counter(
        {
            "accepted_by_both": 65,
            CorpusComparison.EXACT_DIAGNOSTIC_MATCH.value: 72,
            CorpusComparison.DOCUMENTED_DIAGNOSTIC_DIVERGENCE.value: 3,
        }
    )
    assert compatibility_counts == expected_counts
    assert client_counts == expected_counts
    assert (
        compatibility_counts[
            CorpusComparison.UNEXPECTED_DIAGNOSTIC_DIVERGENCE.value
        ]
        == 0
    )
    assert compatibility_counts["adapter_failures"] == 0
    assert compatibility_counts["protocol_errors"] == 0
    assert (
        client_counts[
            CorpusComparison.UNEXPECTED_DIAGNOSTIC_DIVERGENCE.value
        ]
        == 0
    )
    assert client_counts["adapter_failures"] == 0
    assert client_counts["infrastructure_failures"] == 0
    assert expectation_mismatches == []
