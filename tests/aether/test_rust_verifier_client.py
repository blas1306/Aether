from __future__ import annotations

import json
import sys

import pytest

from aether.ir import (
    CanonicalRustVerifierRequest,
    IRModule,
    RustVerifierAcceptedOutcome,
    RustVerifierAdapterError,
    RustVerifierClient,
    RustVerifierClientKind,
    RustVerifierInfrastructureFailure,
    RustVerifierInfrastructureFailureKind,
    RustVerifierIntegrationError,
    RustVerifierInvalidResponse,
    RustVerifierInvocation,
    RustVerifierInvocationMetadata,
    RustVerifierNormalizedDiagnostic,
    RustVerifierPhase,
    RustVerifierRejectedOutcome,
    RustVerifierRequestConstructionError,
    VerifierCategory,
    build_canonical_rust_verifier_request,
    rust_verifier_outcome_comparison_key,
    verify_module_with_rust,
)
from aether.ir import rust_verifier_client as client_module
from aether.ir.rust_verifier import (
    RustVerifierProtocolErrorKind,
    SubprocessRustVerifierClient,
    SubprocessRustVerifierInvocationMetadata,
)


ACCEPTED_RESPONSE = {"protocol_version": 1, "status": "accepted"}
REJECTED_RESPONSE = {
    "protocol_version": 1,
    "status": "rejected",
    "diagnostic": {
        "phase": "types",
        "category": "returns",
        "invariant": "IRV-026",
        "message": "bad return",
        "context": {
            "function_index": 0,
            "function_name": "main",
            "block_index": 1,
            "block_name": "exit",
            "instruction_index": 2,
            "instruction_kind": "return",
        },
    },
}


def _command(source: str) -> list[str]:
    return [sys.executable, "-c", source]


def _emit(value: object, *, stderr: bytes = b"") -> list[str]:
    stdout = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    return _command(
        "import os\n"
        f"os.write(1, {stdout!r})\n"
        f"os.write(2, {stderr!r})\n"
    )


def _diagnostic(
    *,
    invariant_id: str = "IRV-026",
    message: str = "bad return",
    block_index: int | None = 1,
) -> RustVerifierNormalizedDiagnostic:
    return RustVerifierNormalizedDiagnostic(
        invariant_id=invariant_id,
        phase=RustVerifierPhase.TYPES,
        category=VerifierCategory.RETURNS,
        message=message,
        function_index=0,
        function_name="main",
        block_index=block_index,
        block_name="exit",
        instruction_index=2,
        instruction_kind="return",
    )


class _FakePyO3StyleClient:
    def __init__(self, outcome: RustVerifierAcceptedOutcome) -> None:
        self._outcome = outcome

    def verify(
        self,
        request: CanonicalRustVerifierRequest,
    ) -> RustVerifierInvocation:
        return RustVerifierInvocation(
            outcome=self._outcome,
            metadata=RustVerifierInvocationMetadata(
                client_kind=RustVerifierClientKind.PYO3,
                duration_seconds=None,
                protocol_version=request.protocol_version,
                ir_schema_version=request.ir_schema_version,
            ),
        )


def test_request_materializes_once_and_has_deterministic_versioned_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = client_module.ir_module_to_dto

    def counting_materializer(module: IRModule, *, schema_version: int) -> object:
        nonlocal calls
        calls += 1
        return original(module, schema_version=schema_version)

    monkeypatch.setattr(
        client_module,
        "ir_module_to_dto",
        counting_materializer,
    )
    module = IRModule()

    first = build_canonical_rust_verifier_request(module)
    assert calls == 1
    second = build_canonical_rust_verifier_request(module)

    assert calls == 2
    assert first == second
    assert first.protocol_version == 1
    assert first.ir_schema_version == 1
    assert first.payload == (
        b'{"module":{"functions":[],"schema_version":1,"structs":[]},'
        b'"operation":"verify","protocol_version":1}\n'
    )


@pytest.mark.parametrize(
    "cause",
    [TypeError("unsupported module"), ValueError("invalid DTO")],
)
def test_request_construction_wraps_and_preserves_original_cause(
    cause: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_materializer(module: IRModule, *, schema_version: int) -> object:
        raise cause

    monkeypatch.setattr(
        client_module,
        "ir_module_to_dto",
        failing_materializer,
    )

    with pytest.raises(RustVerifierRequestConstructionError) as raised:
        build_canonical_rust_verifier_request(IRModule())

    assert str(raised.value) == "Cannot construct canonical Rust verifier request"
    assert raised.value.__cause__ is cause
    assert isinstance(raised.value, RustVerifierIntegrationError)


def test_public_compatibility_entry_wraps_request_construction_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cause = TypeError("unsupported module")

    def failing_materializer(module: IRModule, *, schema_version: int) -> object:
        raise cause

    monkeypatch.setattr(
        client_module,
        "ir_module_to_dto",
        failing_materializer,
    )

    with pytest.raises(RustVerifierIntegrationError) as raised:
        verify_module_with_rust(
            IRModule(),
            executable=_emit(ACCEPTED_RESPONSE),
        )

    assert type(raised.value) is RustVerifierRequestConstructionError
    assert raised.value.__cause__ is cause


def test_existing_adapter_exception_catches_remain_valid() -> None:
    assert issubclass(RustVerifierInvalidResponse, RustVerifierAdapterError)
    assert issubclass(RustVerifierAdapterError, RustVerifierIntegrationError)


def test_public_compatibility_entry_materializes_module_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = client_module.ir_module_to_dto

    def counting_materializer(module: IRModule, *, schema_version: int) -> object:
        nonlocal calls
        calls += 1
        return original(module, schema_version=schema_version)

    monkeypatch.setattr(
        client_module,
        "ir_module_to_dto",
        counting_materializer,
    )

    verify_module_with_rust(
        IRModule(),
        executable=_emit(ACCEPTED_RESPONSE),
    )

    assert calls == 1


def test_canonical_json_failure_is_wrapped_with_original_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cause = ValueError("encoding detail")

    def failing_json_dumps(*args: object, **kwargs: object) -> str:
        raise cause

    monkeypatch.setattr(client_module.json, "dumps", failing_json_dumps)

    with pytest.raises(RustVerifierRequestConstructionError) as raised:
        build_canonical_rust_verifier_request(IRModule())

    assert str(raised.value) == "Cannot construct canonical Rust verifier request"
    assert raised.value.__cause__ is cause


def test_fake_pyo3_style_client_satisfies_structural_contract_without_process_data(
) -> None:
    client = _FakePyO3StyleClient(RustVerifierAcceptedOutcome())
    request = build_canonical_rust_verifier_request(IRModule())

    assert isinstance(client, RustVerifierClient)
    invocation = client.verify(request)
    assert invocation.outcome == RustVerifierAcceptedOutcome()
    assert invocation.metadata.client_kind is RustVerifierClientKind.PYO3
    assert invocation.metadata.transport_metadata is None
    assert not hasattr(invocation.metadata, "stderr")
    assert not hasattr(invocation.metadata, "exit_code")
    assert not hasattr(invocation.metadata, "executable")


def test_fake_pyo3_style_client_and_subprocess_return_same_neutral_outcome(
) -> None:
    request = build_canonical_rust_verifier_request(IRModule())
    fake_invocation = _FakePyO3StyleClient(
        RustVerifierAcceptedOutcome()
    ).verify(request)
    process_invocation = SubprocessRustVerifierClient(
        executable=_emit(ACCEPTED_RESPONSE)
    ).verify(request)

    assert fake_invocation.outcome == process_invocation.outcome
    assert rust_verifier_outcome_comparison_key(
        fake_invocation.outcome
    ) == rust_verifier_outcome_comparison_key(process_invocation.outcome)
    assert fake_invocation.metadata != process_invocation.metadata


def test_metadata_can_differ_without_changing_outcome_comparison() -> None:
    outcome = RustVerifierRejectedOutcome(_diagnostic())
    first = RustVerifierInvocation(
        outcome=outcome,
        metadata=RustVerifierInvocationMetadata(
            client_kind=RustVerifierClientKind.SUBPROCESS,
            duration_seconds=0.1,
            protocol_version=1,
            ir_schema_version=1,
        ),
    )
    second = RustVerifierInvocation(
        outcome=outcome,
        metadata=RustVerifierInvocationMetadata(
            client_kind=RustVerifierClientKind.PYO3,
            duration_seconds=None,
            protocol_version=1,
            ir_schema_version=1,
        ),
    )

    assert first != second
    assert rust_verifier_outcome_comparison_key(
        first.outcome
    ) == rust_verifier_outcome_comparison_key(second.outcome)


def test_diagnostic_comparison_excludes_message_and_preserves_context() -> None:
    first = _diagnostic(message="Rust prose")
    same_semantics = _diagnostic(message="Python prose")
    other_invariant = _diagnostic(invariant_id="IRV-027")
    other_context = _diagnostic(block_index=3)

    assert first != same_semantics
    assert first.comparison_key() == same_semantics.comparison_key()
    assert first.comparison_key() != other_invariant.comparison_key()
    assert first.comparison_key() != other_context.comparison_key()


def test_comparison_keys_represent_documented_divergence_without_prose() -> None:
    divergence = {
        _diagnostic(
            invariant_id="IRV-026",
            message="implementation A",
        ).comparison_key(): _diagnostic(
            invariant_id="IRV-027",
            message="implementation B",
        ).comparison_key()
    }

    assert _diagnostic(
        invariant_id="IRV-026",
        message="new presentation",
    ).comparison_key() in divergence


def test_subprocess_client_translates_accepted_and_keeps_stderr_in_metadata(
) -> None:
    client = SubprocessRustVerifierClient(
        executable=_emit(ACCEPTED_RESPONSE, stderr=b"debug note\n")
    )

    invocation = client.verify(build_canonical_rust_verifier_request(IRModule()))

    assert invocation.outcome == RustVerifierAcceptedOutcome()
    assert not hasattr(invocation.outcome, "transport")
    assert invocation.metadata.client_kind is RustVerifierClientKind.SUBPROCESS
    assert invocation.metadata.duration_seconds is not None
    details = invocation.metadata.transport_metadata
    assert isinstance(details, SubprocessRustVerifierInvocationMetadata)
    assert details.stderr == b"debug note\n"
    assert details.exit_code == 0
    assert details.protocol_error_kind is None


def test_subprocess_client_translates_rejected_to_normalized_diagnostic() -> None:
    client = SubprocessRustVerifierClient(executable=_emit(REJECTED_RESPONSE))

    invocation = client.verify(build_canonical_rust_verifier_request(IRModule()))

    assert isinstance(invocation.outcome, RustVerifierRejectedOutcome)
    assert invocation.outcome.diagnostic == _diagnostic()
    assert not hasattr(invocation.outcome, "transport")


@pytest.mark.parametrize(
    ("protocol_kind", "neutral_kind"),
    [
        (
            RustVerifierProtocolErrorKind.EMPTY_INPUT,
            RustVerifierInfrastructureFailureKind.INVALID_REQUEST,
        ),
        (
            RustVerifierProtocolErrorKind.MALFORMED_JSON,
            RustVerifierInfrastructureFailureKind.INVALID_REQUEST,
        ),
        (
            RustVerifierProtocolErrorKind.REQUEST_SCHEMA,
            RustVerifierInfrastructureFailureKind.INVALID_REQUEST,
        ),
        (
            RustVerifierProtocolErrorKind.UNSUPPORTED_PROTOCOL_VERSION,
            RustVerifierInfrastructureFailureKind.INCOMPATIBLE_VERSION,
        ),
        (
            RustVerifierProtocolErrorKind.UNSUPPORTED_IR_SCHEMA_VERSION,
            RustVerifierInfrastructureFailureKind.INCOMPATIBLE_VERSION,
        ),
        (
            RustVerifierProtocolErrorKind.UNSUPPORTED_OPERATION,
            RustVerifierInfrastructureFailureKind.UNSUPPORTED_OPERATION,
        ),
        (
            RustVerifierProtocolErrorKind.MODULE_SCHEMA,
            RustVerifierInfrastructureFailureKind.INVALID_MODULE,
        ),
        (
            RustVerifierProtocolErrorKind.MODULE_IMPORT,
            RustVerifierInfrastructureFailureKind.INVALID_MODULE,
        ),
        (
            RustVerifierProtocolErrorKind.NORMALIZATION,
            RustVerifierInfrastructureFailureKind.INVALID_MODULE,
        ),
        (
            RustVerifierProtocolErrorKind.INPUT_IO,
            RustVerifierInfrastructureFailureKind.INPUT_IO,
        ),
        (
            RustVerifierProtocolErrorKind.INTERNAL,
            RustVerifierInfrastructureFailureKind.INTERNAL,
        ),
    ],
)
def test_every_protocol_error_kind_has_an_explicit_neutral_mapping(
    protocol_kind: RustVerifierProtocolErrorKind,
    neutral_kind: RustVerifierInfrastructureFailureKind,
) -> None:
    response = {
        "protocol_version": 1,
        "status": "error",
        "error": {"kind": protocol_kind.value, "message": "wire prose"},
    }
    client = SubprocessRustVerifierClient(executable=_emit(response))

    invocation = client.verify(build_canonical_rust_verifier_request(IRModule()))

    assert invocation.outcome == RustVerifierInfrastructureFailure(
        kind=neutral_kind,
        message="wire prose",
    )
    assert not hasattr(invocation.outcome, "transport")
    details = invocation.metadata.transport_metadata
    assert isinstance(details, SubprocessRustVerifierInvocationMetadata)
    assert details.protocol_error_kind is protocol_kind
