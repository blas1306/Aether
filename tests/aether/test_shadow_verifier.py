from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from aether.errors import AetherRuntimeError
from aether.ir import (
    AuthorityResult,
    AuthoritativeVerifierRejected,
    AuthoritativeVerifierUnavailable,
    CanonicalRustVerifierRequest,
    CollectingShadowReportSink,
    ComparisonResult,
    ExactShadowDivergenceRegistry,
    IRBasicBlock,
    IRFunction,
    IRModule,
    IRReturn,
    IRVerificationError,
    PythonShadowAccepted,
    PythonShadowRejected,
    RustVerifierAcceptedOutcome,
    RustVerifierClientKind,
    RustVerifierInfrastructureFailure,
    RustVerifierInfrastructureFailureKind,
    RustVerifierInvocation,
    RustVerifierInvocationMetadata,
    RustVerifierNormalizedDiagnostic,
    RustVerifierPhase,
    RustVerifierProcessFailure,
    RustVerifierRejectedOutcome,
    RustVerifierRequestConstructionError,
    RustVerifierTimeout,
    ShadowClassification,
    ShadowDiagnosticKey,
    ShadowRustAccepted,
    ShadowRustInfrastructureFailure,
    ShadowRustIntegrationFailure,
    ShadowRustRejected,
    ShadowRustSkipped,
    ShadowResult,
    ShadowVerificationStage,
    ShadowVerifierCoordinator,
    VerifierAuthorityConfiguration,
    VerifierAuthorityEnvironment,
    VerifierAuthorityMode,
    VerifierAuthorityPipeline,
    VerifierSemanticDisagreement,
    VerifierImplementation,
    VerifierCategory,
    VoidType,
    compare_shadow_outcomes,
)
from aether.ir.shadow_divergences import (
    DEFAULT_SHADOW_DIVERGENCE_REGISTRY,
)
from aether.ir.verifier import IRVerifier
from aether.pipeline import IRBackend


EMPTY_REGISTRY = ExactShadowDivergenceRegistry()
RP2_ROLLBACK = VerifierAuthorityConfiguration(
    VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW
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


def _diagnostic(
    invariant: str = "IRV-018",
    *,
    message: str = "message",
    category: VerifierCategory = VerifierCategory.CFG,
    phase: RustVerifierPhase = RustVerifierPhase.STRUCTURE,
    function_index: int | None = None,
    function_name: str | None = None,
    block_index: int | None = None,
    block_name: str | None = None,
    instruction_index: int | None = None,
    instruction_kind: str | None = None,
) -> RustVerifierNormalizedDiagnostic:
    return RustVerifierNormalizedDiagnostic(
        invariant_id=invariant,
        phase=phase,
        category=category,
        message=message,
        function_index=function_index,
        function_name=function_name,
        block_index=block_index,
        block_name=block_name,
        instruction_index=instruction_index,
        instruction_kind=instruction_kind,
    )


class FakeClient:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.requests: list[CanonicalRustVerifierRequest] = []

    def verify(
        self, request: CanonicalRustVerifierRequest
    ) -> RustVerifierInvocation:
        self.requests.append(request)
        return RustVerifierInvocation(
            outcome=self.outcome,  # type: ignore[arg-type]
            metadata=RustVerifierInvocationMetadata(
                client_kind=RustVerifierClientKind.SUBPROCESS,
                duration_seconds=123.0,
                protocol_version=request.protocol_version,
                ir_schema_version=request.ir_schema_version,
            ),
        )


class RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def verify(self, request: CanonicalRustVerifierRequest) -> RustVerifierInvocation:
        del request
        self.calls += 1
        raise self.error


def _compare(
    python: PythonShadowAccepted | PythonShadowRejected,
    rust: object,
) -> ShadowClassification:
    result = compare_shadow_outcomes(
        python,
        rust,  # type: ignore[arg-type]
        request_hash="0" * 64,
        registry=EMPTY_REGISTRY,
        protocol_version=1,
        ir_schema_version=1,
    )
    return result.classification


def test_classifier_covers_matches_and_ignores_unavailable_context() -> None:
    key = ShadowDiagnosticKey(
        "IRV-018",
        VerifierCategory.CFG,
        RustVerifierPhase.STRUCTURE,
        function_index=0,
        function_name="main",
    )

    assert (
        _compare(PythonShadowAccepted(), ShadowRustAccepted())
        is ShadowClassification.MATCH_ACCEPTED
    )
    assert (
        _compare(
            PythonShadowRejected(
                "IRV-018",
                VerifierCategory.CFG,
                RustVerifierPhase.STRUCTURE,
                function_index=0,
                function_name="main",
            ),
            ShadowRustRejected(key),
        )
        is ShadowClassification.MATCH_REJECTED_EXACT
    )
    assert (
        _compare(
            PythonShadowRejected("IRV-018", VerifierCategory.CFG),
            ShadowRustRejected(key),
        )
        is ShadowClassification.MATCH_REJECTED_SEMANTIC
    )


@pytest.mark.parametrize(
    ("python", "rust", "expected"),
    [
        (
            PythonShadowRejected(
                "IRV-018",
                VerifierCategory.CFG,
                function_name="left",
            ),
            ShadowRustRejected(
                ShadowDiagnosticKey(
                    "IRV-018",
                    VerifierCategory.CFG,
                    function_name="right",
                )
            ),
            ShadowClassification.UNEXPECTED_DIAGNOSTIC_DIVERGENCE,
        ),
        (
            PythonShadowRejected("IRV-018", VerifierCategory.CFG),
            ShadowRustRejected(
                ShadowDiagnosticKey("IRV-020", VerifierCategory.CFG)
            ),
            ShadowClassification.UNEXPECTED_DIAGNOSTIC_DIVERGENCE,
        ),
        (
            PythonShadowRejected("IRV-018", VerifierCategory.CFG),
            ShadowRustRejected(
                ShadowDiagnosticKey(
                    "IRV-018", VerifierCategory.TYPES
                )
            ),
            ShadowClassification.UNEXPECTED_DIAGNOSTIC_DIVERGENCE,
        ),
        (
            PythonShadowAccepted(),
            ShadowRustRejected(
                ShadowDiagnosticKey("IRV-018", VerifierCategory.CFG)
            ),
            ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE,
        ),
        (
            PythonShadowRejected("IRV-018", VerifierCategory.CFG),
            ShadowRustAccepted(),
            ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE,
        ),
        (
            PythonShadowAccepted(),
            ShadowRustInfrastructureFailure("internal", "bounded"),
            ShadowClassification.RUST_INFRASTRUCTURE_FAILURE,
        ),
        (
            PythonShadowAccepted(),
            ShadowRustIntegrationFailure("timeout", "bounded"),
            ShadowClassification.RUST_INTEGRATION_FAILURE,
        ),
        (
            PythonShadowAccepted(),
            ShadowRustSkipped("nontransportable"),
            ShadowClassification.SHADOW_SKIPPED,
        ),
    ],
)
def test_classifier_rejects_conflicts_and_covers_neutral_outcomes(
    python: PythonShadowAccepted | PythonShadowRejected,
    rust: object,
    expected: ShadowClassification,
) -> None:
    assert _compare(python, rust) is expected


def test_documented_registry_requires_hash_context_versions_and_direction() -> None:
    rule = DEFAULT_SHADOW_DIVERGENCE_REGISTRY.rules[0]
    arguments = {
        "request_hash": rule.request_sha256,
        "python_key": rule.expected_python_key,
        "rust_key": rule.expected_rust_key,
        "protocol_version": rule.protocol_version,
        "ir_schema_version": rule.ir_schema_version,
    }

    assert DEFAULT_SHADOW_DIVERGENCE_REGISTRY.match(**arguments) is rule
    assert DEFAULT_SHADOW_DIVERGENCE_REGISTRY.match(
        **(arguments | {"request_hash": "0" * 64})
    ) is None
    assert DEFAULT_SHADOW_DIVERGENCE_REGISTRY.match(
        **(arguments | {"protocol_version": 2})
    ) is None
    assert DEFAULT_SHADOW_DIVERGENCE_REGISTRY.match(
        **(arguments | {"ir_schema_version": 2})
    ) is None
    assert DEFAULT_SHADOW_DIVERGENCE_REGISTRY.match(
        **(
            arguments
            | {
                "python_key": rule.expected_rust_key,
                "rust_key": rule.expected_python_key,
            }
        )
    ) is None

    rust_key = rule.expected_rust_key
    assert len(rust_key) == 2
    assert isinstance(rust_key[1], ShadowDiagnosticKey)
    changed_context = (
        "rejected",
        replace(rust_key[1], function_index=999),
    )
    assert DEFAULT_SHADOW_DIVERGENCE_REGISTRY.match(
        **(arguments | {"rust_key": changed_context})
    ) is None


def test_default_registry_has_no_documented_outcome_divergences() -> None:
    assert len(DEFAULT_SHADOW_DIVERGENCE_REGISTRY.rules) == 3
    assert all(
        rule.classification
        is ShadowClassification.DOCUMENTED_DIAGNOSTIC_DIVERGENCE
        for rule in DEFAULT_SHADOW_DIVERGENCE_REGISTRY.rules
    )


def test_coordinator_acceptance_returns_python_identity_and_emits_safe_report() -> None:
    module = _accepted_module()
    client = FakeClient(RustVerifierAcceptedOutcome())
    sink = CollectingShadowReportSink()
    coordinator = ShadowVerifierCoordinator(client=client, sink=sink)

    result = coordinator.verify(module)

    assert result is module
    assert len(client.requests) == 1
    report = sink.reports[0]
    assert report.comparison.classification is ShadowClassification.MATCH_ACCEPTED
    assert report.metadata.request_sha256 == sha256(
        client.requests[0].payload
    ).hexdigest()
    assert report.metadata.stage is ShadowVerificationStage.EXTERNAL
    assert "payload" not in repr(report)
    with pytest.raises(FrozenInstanceError):
        report.comparison.reason = "changed"  # type: ignore[misc]


def test_default_authority_configuration_is_closed_and_rust_authoritative() -> None:
    pipeline = VerifierAuthorityPipeline(
        client=FakeClient(RustVerifierAcceptedOutcome())
    )
    configuration = pipeline.configuration

    assert configuration.mode is VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
    assert configuration.environment is VerifierAuthorityEnvironment.DEFAULT
    assert not configuration.is_canary
    assert configuration.authority is VerifierImplementation.RUST
    assert configuration.shadow is VerifierImplementation.PYTHON
    with pytest.raises(TypeError, match="VerifierAuthorityMode"):
        VerifierAuthorityConfiguration("python")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Python result"):
        AuthorityResult(
            VerifierImplementation.PYTHON,
            ShadowRustAccepted(),
        )
    assert VerifierAuthorityConfiguration(
        VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
    ).environment is VerifierAuthorityEnvironment.DEFAULT


def test_environment_variables_cannot_activate_rust_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AETHER_RUST_VERIFIER_AUTHORITY", "rust")
    monkeypatch.setenv("AETHER_RUST_AUTHORITY_CANARY", "1")

    pipeline = VerifierAuthorityPipeline(
        client=FakeClient(RustVerifierAcceptedOutcome())
    )

    assert (
        pipeline.configuration.mode
        is VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
    )
    assert (
        pipeline.configuration.environment
        is VerifierAuthorityEnvironment.DEFAULT
    )


def test_internal_authority_flag_is_the_pipeline_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ir.shadow_verifier as shadow_module

    rust_authority = VerifierAuthorityConfiguration(
        VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
        VerifierAuthorityEnvironment.CANARY,
    )
    monkeypatch.setattr(
        shadow_module,
        "_AUTHORITY_CONFIGURATION",
        rust_authority,
    )
    pipeline = VerifierAuthorityPipeline(
        client=FakeClient(RustVerifierAcceptedOutcome())
    )

    assert pipeline.configuration is rust_authority


def test_rust_authority_routes_results_and_preserves_default_snapshot() -> None:
    module = _accepted_module()
    default_sink = CollectingShadowReportSink()
    explicit_sink = CollectingShadowReportSink()
    default_pipeline = VerifierAuthorityPipeline(
        client=FakeClient(RustVerifierAcceptedOutcome()),
        sink=default_sink,
    )
    explicit_pipeline = VerifierAuthorityPipeline(
        client=FakeClient(RustVerifierAcceptedOutcome()),
        sink=explicit_sink,
        configuration=VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW
        ),
    )

    assert default_pipeline.verify(module) is module
    assert explicit_pipeline.verify(module) is module
    default_report = default_sink.reports[0]
    explicit_report = explicit_sink.reports[0]
    assert isinstance(default_pipeline, VerifierAuthorityPipeline)
    assert default_report.authority_result == AuthorityResult(
        VerifierImplementation.RUST,
        ShadowRustAccepted(),
    )
    assert default_report.shadow_result == ShadowResult(
        VerifierImplementation.PYTHON,
        PythonShadowAccepted(),
    )
    assert isinstance(default_report.comparison, ComparisonResult)
    assert (
        default_report.semantic_snapshot()
        == explicit_report.semantic_snapshot()
    )


def test_rust_authority_accept_python_reject_disagreement_is_fatal_and_observable() -> None:
    module = _rejected_module()
    sink = CollectingShadowReportSink()
    pipeline = VerifierAuthorityPipeline(
        client=FakeClient(RustVerifierAcceptedOutcome()),
        sink=sink,
        configuration=VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
            VerifierAuthorityEnvironment.CANARY,
        ),
    )

    with pytest.raises(VerifierSemanticDisagreement) as raised:
        pipeline.verify(module)
    assert (
        raised.value.classification
        is ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE
    )
    report = sink.reports[0]
    assert report.authority_result == AuthorityResult(
        VerifierImplementation.RUST,
        ShadowRustAccepted(),
    )
    assert report.shadow_result.implementation is VerifierImplementation.PYTHON
    assert isinstance(report.shadow_result.outcome, PythonShadowRejected)
    assert (
        report.comparison.classification
        is ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE
    )


def test_rust_reject_python_accept_disagreement_is_fatal_and_observable() -> None:
    module = _accepted_module()
    sink = CollectingShadowReportSink()
    client = FakeClient(RustVerifierRejectedOutcome(_diagnostic()))
    pipeline = VerifierAuthorityPipeline(
        client=client,
        sink=sink,
        configuration=VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
            VerifierAuthorityEnvironment.CANARY,
        ),
    )

    with pytest.raises(VerifierSemanticDisagreement) as raised:
        pipeline.verify(module)

    assert (
        raised.value.classification
        is ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE
    )
    assert len(client.requests) == 1
    report = sink.reports[0]
    assert report.authority_result.implementation is VerifierImplementation.RUST
    assert isinstance(report.authority_result.outcome, ShadowRustRejected)
    assert report.shadow_result == ShadowResult(
        VerifierImplementation.PYTHON,
        PythonShadowAccepted(),
    )
    assert (
        report.comparison.classification
        is ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE
    )


@pytest.mark.parametrize(
    ("client", "expected_classification", "expected_kind"),
    [
        (
            FakeClient(
                RustVerifierInfrastructureFailure(
                    RustVerifierInfrastructureFailureKind.INVALID_REQUEST,
                    "safe protocol failure",
                )
            ),
            ShadowClassification.RUST_INFRASTRUCTURE_FAILURE,
            "invalid_request",
        ),
        (
            RaisingClient(
                RustVerifierProcessFailure(
                    7,
                    stdout_excerpt=b"not retained",
                    stderr_excerpt=b"not retained",
                )
            ),
            ShadowClassification.RUST_INTEGRATION_FAILURE,
            "process_failure",
        ),
        (
            RaisingClient(
                RustVerifierTimeout(
                    0.01,
                    stdout_excerpt=b"not retained",
                    stderr_excerpt=b"not retained",
                )
            ),
            ShadowClassification.RUST_INTEGRATION_FAILURE,
            "timeout",
        ),
    ],
)
def test_rust_authority_operational_failures_are_fail_closed_without_fallback(
    client: object,
    expected_classification: ShadowClassification,
    expected_kind: str,
) -> None:
    sink = CollectingShadowReportSink()
    pipeline = VerifierAuthorityPipeline(
        client=client,  # type: ignore[arg-type]
        sink=sink,
        configuration=VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
            VerifierAuthorityEnvironment.CANARY,
        ),
    )

    with pytest.raises(AuthoritativeVerifierUnavailable) as raised:
        pipeline.verify(_accepted_module())

    assert raised.value.kind == expected_kind
    report = sink.reports[0]
    assert report.authority_result.implementation is VerifierImplementation.RUST
    assert report.shadow_result == ShadowResult(
        VerifierImplementation.PYTHON,
        PythonShadowAccepted(),
    )
    assert report.comparison.classification is expected_classification


def test_ir_backend_fails_when_rust_authority_is_unavailable() -> None:
    sink = CollectingShadowReportSink()
    pipeline = VerifierAuthorityPipeline(
        client=RaisingClient(
            RustVerifierTimeout(
                0.01,
                stdout_excerpt=b"",
                stderr_excerpt=b"",
            )
        ),
        sink=sink,
        configuration=VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
            VerifierAuthorityEnvironment.CANARY,
        ),
    )
    backend = IRBackend(shadow_verifier=pipeline)

    with pytest.raises(AetherRuntimeError) as raised:
        backend.verify(_accepted_module())

    assert isinstance(raised.value.__cause__, AuthoritativeVerifierUnavailable)
    assert len(sink.reports) == 1


def test_rust_rejection_and_request_construction_failure_do_not_change_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _accepted_module()
    rejection_sink = CollectingShadowReportSink()
    result = ShadowVerifierCoordinator(
        client=FakeClient(
            RustVerifierRejectedOutcome(_diagnostic("IRV-018"))
        ),
        sink=rejection_sink,
        configuration=RP2_ROLLBACK,
    ).verify(module)

    assert result is module
    assert (
        rejection_sink.reports[0].comparison.classification
        is ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE
    )

    import aether.ir.shadow_verifier as shadow_module

    def fail_request(module: IRModule) -> CanonicalRustVerifierRequest:
        del module
        raise RustVerifierRequestConstructionError("construction failed")

    monkeypatch.setattr(
        shadow_module,
        "build_canonical_rust_verifier_request",
        fail_request,
    )
    construction_sink = CollectingShadowReportSink()
    client = FakeClient(RustVerifierAcceptedOutcome())

    assert (
        ShadowVerifierCoordinator(
            client=client,
            sink=construction_sink,
            configuration=RP2_ROLLBACK,
        ).verify(module)
        is module
    )
    assert client.requests == []
    assert (
        construction_sink.reports[0].comparison.classification
        is ShadowClassification.RUST_INTEGRATION_FAILURE
    )
    assert construction_sink.reports[0].metadata.request_sha256 is None


def test_coordinator_reraises_the_original_python_error_after_rust_disagrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _rejected_module()
    original_verify = IRVerifier.verify
    captured: list[IRVerificationError] = []

    def recording_verify(verifier: IRVerifier) -> IRModule:
        try:
            return original_verify(verifier)
        except IRVerificationError as error:
            captured.append(error)
            raise

    monkeypatch.setattr(IRVerifier, "verify", recording_verify)
    sink = CollectingShadowReportSink()
    coordinator = ShadowVerifierCoordinator(
        client=FakeClient(RustVerifierAcceptedOutcome()),
        sink=sink,
        configuration=RP2_ROLLBACK,
    )

    with pytest.raises(IRVerificationError) as raised:
        coordinator.verify(module)

    assert raised.value is captured[0]
    assert raised.value.__traceback__ is not None
    assert (
        sink.reports[0].comparison.classification
        is ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE
    )


def test_infrastructure_and_integration_failures_never_change_python_result() -> None:
    infrastructure = RustVerifierInfrastructureFailure(
        RustVerifierInfrastructureFailureKind.INTERNAL,
        "safe failure",
    )
    infrastructure_sink = CollectingShadowReportSink()
    module = _accepted_module()

    assert (
        ShadowVerifierCoordinator(
            client=FakeClient(infrastructure),
            sink=infrastructure_sink,
            configuration=RP2_ROLLBACK,
        ).verify(module)
        is module
    )
    assert (
        infrastructure_sink.reports[0].comparison.classification
        is ShadowClassification.RUST_INFRASTRUCTURE_FAILURE
    )

    timeout = RustVerifierTimeout(
        0.01,
        stdout_excerpt=b"not retained",
        stderr_excerpt=b"not retained",
    )
    integration_sink = CollectingShadowReportSink()
    assert (
        ShadowVerifierCoordinator(
            client=RaisingClient(timeout),
            sink=integration_sink,
            configuration=RP2_ROLLBACK,
        ).verify(module)
        is module
    )
    report = integration_sink.reports[0]
    assert (
        report.comparison.classification
        is ShadowClassification.RUST_INTEGRATION_FAILURE
    )
    assert b"not retained" not in repr(report).encode()


def test_sink_failure_policy_preserves_rejection_and_is_nonstrict_by_default() -> None:
    class FailingSink:
        def emit(self, report: object) -> None:
            del report
            raise LookupError("sink failed")

    module = _accepted_module()
    assert (
        ShadowVerifierCoordinator(
            client=FakeClient(RustVerifierAcceptedOutcome()),
            sink=FailingSink(),
            configuration=RP2_ROLLBACK,
        ).verify(module)
        is module
    )

    with pytest.raises(IRVerificationError):
        ShadowVerifierCoordinator(
            client=FakeClient(RustVerifierAcceptedOutcome()),
            sink=FailingSink(),
            strict_sink_errors=True,
            configuration=RP2_ROLLBACK,
        ).verify(_rejected_module())
    with pytest.raises(LookupError, match="sink failed"):
        ShadowVerifierCoordinator(
            client=FakeClient(RustVerifierAcceptedOutcome()),
            sink=FailingSink(),
            strict_sink_errors=True,
            configuration=RP2_ROLLBACK,
        ).verify(module)


def test_unexpected_python_and_coordinator_bugs_propagate_without_reclassification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(RustVerifierAcceptedOutcome())

    def broken_python(verifier: IRVerifier) -> IRModule:
        del verifier
        raise AssertionError("python verifier bug")

    monkeypatch.setattr(IRVerifier, "verify", broken_python)
    with pytest.raises(AssertionError, match="python verifier bug"):
        ShadowVerifierCoordinator(client=client).verify(_accepted_module())
    assert client.requests == []

    monkeypatch.undo()

    class BrokenRegistry:
        def match(self, **kwargs: object) -> object:
            del kwargs
            raise RuntimeError("classifier registry bug")

    with pytest.raises(RuntimeError, match="classifier registry bug"):
        ShadowVerifierCoordinator(
            client=FakeClient(
                RustVerifierRejectedOutcome(_diagnostic("IRV-999"))
            ),
            registry=BrokenRegistry(),
        ).verify(_accepted_module())


def test_ir_backend_disabled_mode_does_not_touch_shadow_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ir.shadow_verifier as shadow_module

    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("disabled backend touched shadow mode")

    monkeypatch.setattr(
        shadow_module,
        "build_canonical_rust_verifier_request",
        forbidden,
    )
    monkeypatch.setattr(shadow_module, "sha256", forbidden)
    module = _accepted_module()
    backend = IRBackend()

    assert backend.verify(module) is module
    with pytest.raises(AetherRuntimeError) as raised:
        backend.verify(_rejected_module())
    assert isinstance(raised.value.__cause__, IRVerificationError)


def test_enabled_backend_preserves_python_rendered_diagnostic_and_cause() -> None:
    module = _rejected_module()
    sink = CollectingShadowReportSink()
    backend = IRBackend(
        shadow_verifier=ShadowVerifierCoordinator(
            client=FakeClient(RustVerifierAcceptedOutcome()),
            sink=sink,
            configuration=RP2_ROLLBACK,
        )
    )

    with pytest.raises(AetherRuntimeError) as enabled:
        backend.verify(module)
    with pytest.raises(AetherRuntimeError) as disabled:
        IRBackend().verify(module)

    assert str(enabled.value) == str(disabled.value)
    assert type(enabled.value.__cause__) is type(disabled.value.__cause__)
    assert isinstance(enabled.value.__cause__, IRVerificationError)
    assert isinstance(disabled.value.__cause__, IRVerificationError)
    assert (
        enabled.value.__cause__.normalized_failure
        == disabled.value.__cause__.normalized_failure
    )


def test_ir_backend_never_sends_post_lifecycle_ir_to_initial_rust_verifier() -> None:
    class IdentityOptimizer:
        def run(self, module: IRModule) -> IRModule:
            return module

    sink = CollectingShadowReportSink()
    coordinator = ShadowVerifierCoordinator(
        client=FakeClient(RustVerifierAcceptedOutcome()),
        sink=sink,
    )
    backend = IRBackend(shadow_verifier=coordinator)
    module = _accepted_module()

    assert backend.verify(module) is module
    backend.optimize_verified(module, optimizer=IdentityOptimizer())

    assert [report.metadata.stage for report in sink.reports] == [
        ShadowVerificationStage.INITIAL,
    ]


def test_semantic_snapshot_ignores_timings_and_rust_metadata() -> None:
    module = _accepted_module()
    first_sink = CollectingShadowReportSink()
    second_sink = CollectingShadowReportSink()

    ShadowVerifierCoordinator(
        client=FakeClient(RustVerifierAcceptedOutcome()),
        sink=first_sink,
    ).verify(module)
    ShadowVerifierCoordinator(
        client=FakeClient(RustVerifierAcceptedOutcome()),
        sink=second_sink,
    ).verify(module)

    assert (
        first_sink.reports[0].semantic_snapshot()
        == second_sink.reports[0].semantic_snapshot()
    )


def test_rust_diagnostic_message_prose_does_not_affect_reports() -> None:
    snapshots = []
    for message in ("first wording", "completely different wording"):
        sink = CollectingShadowReportSink()
        coordinator = ShadowVerifierCoordinator(
            client=FakeClient(
                RustVerifierRejectedOutcome(
                    _diagnostic("IRV-018", message=message)
                )
            ),
            sink=sink,
            configuration=RP2_ROLLBACK,
        )
        with pytest.raises(IRVerificationError):
            coordinator.verify(_rejected_module())
        snapshots.append(sink.reports[0].semantic_snapshot())

    assert snapshots[0] == snapshots[1]
