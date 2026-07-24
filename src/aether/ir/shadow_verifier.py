"""Authority-ready Initial IR verification with continuous shadow comparison.

The repository-wide internal feature flag remains Python-authoritative.  The
pipeline always runs both configured verifier engines, compares their semantic
outcomes, emits one bounded report, and only then resolves the selected
authority.  Rust authority is available for focused tests and future rollout;
it is not enabled by this phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, unique
from hashlib import sha256
import re
from time import perf_counter
from types import TracebackType
from typing import Protocol, TypeAlias, runtime_checkable

from .dto import IR_SCHEMA_VERSION
from .model import IRModule
from .rust_verifier_client import (
    RUST_VERIFIER_PROTOCOL_VERSION,
    RustVerifierAcceptedOutcome,
    RustVerifierClient,
    RustVerifierInfrastructureFailure,
    RustVerifierIntegrationError,
    RustVerifierInvocation,
    RustVerifierPhase,
    RustVerifierRejectedOutcome,
    build_canonical_rust_verifier_request,
)
from .verification_result import VerifierCategory, VerifierFailure
from .verifier import IRVerificationError, IRVerifier


_SUMMARY_LIMIT = 240
_WHITESPACE = re.compile(r"\s+")


@unique
class ShadowClassification(str, Enum):
    """Closed classification taxonomy for one shadow observation."""

    MATCH_ACCEPTED = "match_accepted"
    MATCH_REJECTED_EXACT = "match_rejected_exact"
    MATCH_REJECTED_SEMANTIC = "match_rejected_semantic"
    DOCUMENTED_DIAGNOSTIC_DIVERGENCE = "documented_diagnostic_divergence"
    DOCUMENTED_OUTCOME_DIVERGENCE = "documented_outcome_divergence"
    UNEXPECTED_DIAGNOSTIC_DIVERGENCE = "unexpected_diagnostic_divergence"
    UNEXPECTED_OUTCOME_DIVERGENCE = "unexpected_outcome_divergence"
    RUST_INFRASTRUCTURE_FAILURE = "rust_infrastructure_failure"
    RUST_INTEGRATION_FAILURE = "rust_integration_failure"
    SHADOW_SKIPPED = "shadow_skipped"
    SHADOW_COORDINATOR_FAILURE = "shadow_coordinator_failure"


@unique
class ShadowVerificationStage(str, Enum):
    """Compiler boundary at which an observation was made."""

    INITIAL = "initial"
    POST_OPTIMIZATION = "post_optimization"
    EXTERNAL = "external"


@unique
class VerifierImplementation(str, Enum):
    """The two Initial IR verifier implementations."""

    PYTHON = "python"
    RUST = "rust"


@unique
class VerifierAuthorityMode(str, Enum):
    """Closed authority/shadow pairings; no partial mode is representable."""

    PYTHON_AUTHORITY_RUST_SHADOW = "python_authority_rust_shadow"
    RUST_AUTHORITY_PYTHON_SHADOW = "rust_authority_python_shadow"


@dataclass(frozen=True)
class VerifierAuthorityConfiguration:
    """One immutable authority selection consumed by the verification pipeline."""

    mode: VerifierAuthorityMode

    def __post_init__(self) -> None:
        if not isinstance(self.mode, VerifierAuthorityMode):
            raise TypeError("mode must be a VerifierAuthorityMode")

    @property
    def authority(self) -> VerifierImplementation:
        if self.mode is VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW:
            return VerifierImplementation.PYTHON
        return VerifierImplementation.RUST

    @property
    def shadow(self) -> VerifierImplementation:
        if self.mode is VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW:
            return VerifierImplementation.RUST
        return VerifierImplementation.PYTHON


# Internal feature flag.  A future authority phase changes this one assignment;
# no environment variable or user-facing selector participates in the policy.
_AUTHORITY_CONFIGURATION = VerifierAuthorityConfiguration(
    VerifierAuthorityMode.PYTHON_AUTHORITY_RUST_SHADOW
)


@dataclass(frozen=True)
class ShadowDiagnosticKey:
    """Message- and path-free semantic identity for one rejection."""

    invariant_id: str
    category: VerifierCategory | None = None
    phase: RustVerifierPhase | None = None
    function_index: int | None = None
    function_name: str | None = None
    block_index: int | None = None
    block_name: str | None = None
    instruction_index: int | None = None
    instruction_kind: str | None = None


@dataclass(frozen=True)
class PythonShadowAccepted:
    """Normalized authoritative Python acceptance."""


@dataclass(frozen=True)
class PythonShadowRejected:
    """Normalized authoritative Python rejection without diagnostic prose."""

    invariant_id: str
    category: VerifierCategory | None = None
    phase: RustVerifierPhase | None = None
    function_index: int | None = None
    function_name: str | None = None
    block_index: int | None = None
    block_name: str | None = None
    instruction_index: int | None = None
    instruction_kind: str | None = None

    def comparison_key(self) -> ShadowDiagnosticKey:
        return ShadowDiagnosticKey(
            invariant_id=self.invariant_id,
            category=self.category,
            phase=self.phase,
            function_index=self.function_index,
            function_name=self.function_name,
            block_index=self.block_index,
            block_name=self.block_name,
            instruction_index=self.instruction_index,
            instruction_kind=self.instruction_kind,
        )


PythonShadowOutcome: TypeAlias = PythonShadowAccepted | PythonShadowRejected


@dataclass(frozen=True)
class ShadowRustAccepted:
    """Rust accepted the canonical request."""


@dataclass(frozen=True)
class ShadowRustRejected:
    """Rust rejected the canonical request with a normalized key."""

    diagnostic: ShadowDiagnosticKey


@dataclass(frozen=True)
class ShadowRustInfrastructureFailure:
    """Rust returned a trusted, non-semantic protocol failure."""

    kind: str
    summary: str


@dataclass(frozen=True)
class ShadowRustIntegrationFailure:
    """The configured Rust integration did not yield a trusted response."""

    kind: str
    summary: str


@dataclass(frozen=True)
class ShadowRustSkipped:
    """A harness explicitly skipped a nontransportable shadow observation."""

    reason: str


ShadowRustObservation: TypeAlias = (
    ShadowRustAccepted
    | ShadowRustRejected
    | ShadowRustInfrastructureFailure
    | ShadowRustIntegrationFailure
    | ShadowRustSkipped
)
VerifierObservation: TypeAlias = PythonShadowOutcome | ShadowRustObservation
ShadowOutcomeKey: TypeAlias = (
    tuple[str]
    | tuple[str, ShadowDiagnosticKey]
    | tuple[str, str]
)


@runtime_checkable
class ShadowDivergenceRegistry(Protocol):
    """Narrow registry boundary consumed by the pure classifier."""

    def match(
        self,
        *,
        request_hash: str,
        python_key: ShadowOutcomeKey,
        rust_key: ShadowOutcomeKey,
        protocol_version: int,
        ir_schema_version: int,
    ) -> object | None:
        ...


@dataclass(frozen=True)
class ShadowComparison:
    """Pure Python/Rust comparison, independent of which side is authoritative."""

    classification: ShadowClassification
    python_key: ShadowOutcomeKey
    rust_key: ShadowOutcomeKey
    documented_rule_id: str | None = None
    reason: str = ""


# Authority-ready name; the existing class identity and representation remain.
ComparisonResult = ShadowComparison


def _validate_result_implementation(
    implementation: VerifierImplementation,
    outcome: VerifierObservation,
) -> None:
    if not isinstance(implementation, VerifierImplementation):
        raise TypeError("implementation must be a VerifierImplementation")
    if implementation is VerifierImplementation.PYTHON:
        if not isinstance(outcome, (PythonShadowAccepted, PythonShadowRejected)):
            raise TypeError("Python result must carry a Python verifier outcome")
        return
    if not isinstance(
        outcome,
        (
            ShadowRustAccepted,
            ShadowRustRejected,
            ShadowRustInfrastructureFailure,
            ShadowRustIntegrationFailure,
            ShadowRustSkipped,
        ),
    ):
        raise TypeError("Rust result must carry a Rust verifier observation")


def _implementation_for_outcome(
    outcome: VerifierObservation,
) -> VerifierImplementation:
    if isinstance(outcome, (PythonShadowAccepted, PythonShadowRejected)):
        return VerifierImplementation.PYTHON
    return VerifierImplementation.RUST


@dataclass(frozen=True)
class AuthorityResult:
    """The selected verifier result that controls compilation."""

    implementation: VerifierImplementation
    outcome: VerifierObservation

    def __post_init__(self) -> None:
        _validate_result_implementation(self.implementation, self.outcome)


@dataclass(frozen=True)
class ShadowResult:
    """The non-authoritative verifier result retained for observation."""

    implementation: VerifierImplementation
    outcome: VerifierObservation

    def __post_init__(self) -> None:
        _validate_result_implementation(self.implementation, self.outcome)


@dataclass(frozen=True)
class ShadowOperationalMetadata:
    """Safe operational details kept separate from semantic parity."""

    request_sha256: str | None
    client_kind: str
    protocol_version: int
    ir_schema_version: int
    stage: ShadowVerificationStage
    serialization_duration_seconds: float | None = field(compare=False)
    rust_invocation_duration_seconds: float | None = field(compare=False)
    total_shadow_duration_seconds: float | None = field(compare=False)
    documented_rule_id: str | None = None
    failure_kind: str | None = None
    failure_summary: str | None = None

    def semantic_snapshot(self) -> dict[str, object]:
        """Return deterministic metadata with all timings omitted."""

        return {
            "request_sha256": self.request_sha256,
            "client_kind": self.client_kind,
            "protocol_version": self.protocol_version,
            "ir_schema_version": self.ir_schema_version,
            "stage": self.stage.value,
            "documented_rule_id": self.documented_rule_id,
            "failure_kind": self.failure_kind,
            "failure_summary": self.failure_summary,
        }


@dataclass(frozen=True)
class ShadowVerificationReport:
    """One immutable authority/shadow verification report."""

    authoritative: VerifierObservation
    shadow: VerifierObservation
    comparison: ComparisonResult
    metadata: ShadowOperationalMetadata

    @property
    def authority_result(self) -> AuthorityResult:
        """Return the explicit implementation-tagged authority result."""

        return AuthorityResult(
            _implementation_for_outcome(self.authoritative),
            self.authoritative,
        )

    @property
    def shadow_result(self) -> ShadowResult:
        """Return the explicit implementation-tagged shadow result."""

        return ShadowResult(
            _implementation_for_outcome(self.shadow),
            self.shadow,
        )

    def semantic_snapshot(self) -> dict[str, object]:
        """Return a deterministic, timing-free representation."""

        return {
            "authoritative": _snapshot_outcome(self.authoritative),
            "shadow": _snapshot_outcome(self.shadow),
            "comparison": {
                "classification": self.comparison.classification.value,
                "python_key": _snapshot_key(self.comparison.python_key),
                "rust_key": _snapshot_key(self.comparison.rust_key),
                "documented_rule_id": self.comparison.documented_rule_id,
                "reason": self.comparison.reason,
            },
            "metadata": self.metadata.semantic_snapshot(),
        }


@runtime_checkable
class ShadowReportSink(Protocol):
    """Explicit destination for immutable reports."""

    def emit(self, report: ShadowVerificationReport) -> None:
        ...


@dataclass(frozen=True)
class NullShadowReportSink:
    """Sink that deliberately discards reports."""

    def emit(self, report: ShadowVerificationReport) -> None:
        del report


class CollectingShadowReportSink:
    """In-memory sink intended for tests and local development."""

    def __init__(self) -> None:
        self._reports: list[ShadowVerificationReport] = []

    @property
    def reports(self) -> tuple[ShadowVerificationReport, ...]:
        return tuple(self._reports)

    def emit(self, report: ShadowVerificationReport) -> None:
        self._reports.append(report)


def normalize_python_rejection(error: IRVerificationError) -> PythonShadowRejected:
    """Normalize one ordinary Python verifier rejection without inventing context."""

    failure = getattr(error, "normalized_failure", None)
    if not isinstance(failure, VerifierFailure):
        raise ValueError("IRVerificationError lacks normalized verifier metadata")
    return PythonShadowRejected(
        invariant_id=failure.invariant_id,
        category=failure.category,
    )


def python_shadow_outcome_key(outcome: PythonShadowOutcome) -> ShadowOutcomeKey:
    if isinstance(outcome, PythonShadowAccepted):
        return ("accepted",)
    return ("rejected", outcome.comparison_key())


def rust_shadow_outcome_key(outcome: ShadowRustObservation) -> ShadowOutcomeKey:
    if isinstance(outcome, ShadowRustAccepted):
        return ("accepted",)
    if isinstance(outcome, ShadowRustRejected):
        return ("rejected", outcome.diagnostic)
    if isinstance(outcome, ShadowRustInfrastructureFailure):
        return ("infrastructure_failure", outcome.kind)
    if isinstance(outcome, ShadowRustIntegrationFailure):
        return ("integration_failure", outcome.kind)
    return ("skipped", outcome.reason)


def compare_shadow_outcomes(
    authoritative: PythonShadowOutcome,
    shadow: ShadowRustObservation,
    *,
    request_hash: str,
    registry: ShadowDivergenceRegistry,
    protocol_version: int,
    ir_schema_version: int,
) -> ShadowComparison:
    """Purely compare one authoritative outcome and one Rust observation."""

    python_key = python_shadow_outcome_key(authoritative)
    rust_key = rust_shadow_outcome_key(shadow)

    if isinstance(shadow, ShadowRustInfrastructureFailure):
        return ShadowComparison(
            ShadowClassification.RUST_INFRASTRUCTURE_FAILURE,
            python_key,
            rust_key,
            reason="Rust returned a neutral infrastructure failure",
        )
    if isinstance(shadow, ShadowRustIntegrationFailure):
        return ShadowComparison(
            ShadowClassification.RUST_INTEGRATION_FAILURE,
            python_key,
            rust_key,
            reason="Rust integration produced no trusted observation",
        )
    if isinstance(shadow, ShadowRustSkipped):
        return ShadowComparison(
            ShadowClassification.SHADOW_SKIPPED,
            python_key,
            rust_key,
            reason="Shadow observation was explicitly skipped",
        )
    if isinstance(authoritative, PythonShadowAccepted) and isinstance(
        shadow, ShadowRustAccepted
    ):
        return ShadowComparison(
            ShadowClassification.MATCH_ACCEPTED,
            python_key,
            rust_key,
            reason="Both verifiers accepted",
        )

    if isinstance(authoritative, PythonShadowRejected) and isinstance(
        shadow, ShadowRustRejected
    ):
        python_diagnostic = authoritative.comparison_key()
        rust_diagnostic = shadow.diagnostic
        if python_diagnostic == rust_diagnostic:
            return ShadowComparison(
                ShadowClassification.MATCH_REJECTED_EXACT,
                python_key,
                rust_key,
                reason="Rejection keys are exactly equal",
            )
        if _diagnostics_are_semantically_compatible(
            python_diagnostic, rust_diagnostic
        ):
            return ShadowComparison(
                ShadowClassification.MATCH_REJECTED_SEMANTIC,
                python_key,
                rust_key,
                reason="Shared rejection fields agree; one side lacks context",
            )

    rule = registry.match(
        request_hash=request_hash,
        python_key=python_key,
        rust_key=rust_key,
        protocol_version=protocol_version,
        ir_schema_version=ir_schema_version,
    )
    if rule is not None:
        classification = getattr(rule, "classification")
        rule_id = getattr(rule, "rule_id")
        return ShadowComparison(
            classification,
            python_key,
            rust_key,
            documented_rule_id=rule_id,
            reason=f"Matched hash-scoped divergence rule {rule_id}",
        )

    outcome_mismatch = isinstance(authoritative, PythonShadowAccepted) != isinstance(
        shadow, ShadowRustAccepted
    )
    if outcome_mismatch:
        classification = ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE
        reason = "Python and Rust acceptance outcomes differ"
    else:
        classification = ShadowClassification.UNEXPECTED_DIAGNOSTIC_DIVERGENCE
        reason = "Rejected diagnostics contradict on a shared field"
    return ShadowComparison(
        classification,
        python_key,
        rust_key,
        reason=reason,
    )


class AuthoritativeVerificationError(RuntimeError):
    """Base failure raised when the selected authority cannot accept a module."""


class AuthoritativeVerifierRejected(AuthoritativeVerificationError):
    """A non-Python authority rejected the module semantically."""

    def __init__(
        self,
        implementation: VerifierImplementation,
        diagnostic: ShadowDiagnosticKey,
    ) -> None:
        self.implementation = implementation
        self.diagnostic = diagnostic
        super().__init__(
            f"{implementation.value} verifier rejected module "
            f"({diagnostic.invariant_id})"
        )


class AuthoritativeVerifierUnavailable(AuthoritativeVerificationError):
    """The selected non-Python authority produced no semantic result."""

    def __init__(
        self,
        implementation: VerifierImplementation,
        *,
        kind: str,
        summary: str,
    ) -> None:
        self.implementation = implementation
        self.kind = kind
        self.summary = summary
        super().__init__(
            f"{implementation.value} authoritative verifier failed: {kind}"
        )


@dataclass(frozen=True)
class _PythonVerifierExecution:
    module: IRModule
    outcome: PythonShadowOutcome
    error: IRVerificationError | None = None
    traceback: TracebackType | None = None

    def resolve(self) -> IRModule:
        if self.error is not None:
            raise self.error.with_traceback(self.traceback)
        return self.module


@dataclass(frozen=True)
class _RustVerifierExecution:
    module: IRModule
    outcome: ShadowRustObservation
    failure_cause: RustVerifierIntegrationError | None = None

    def resolve(self) -> IRModule:
        if isinstance(self.outcome, ShadowRustAccepted):
            return self.module
        if isinstance(self.outcome, ShadowRustRejected):
            raise AuthoritativeVerifierRejected(
                VerifierImplementation.RUST,
                self.outcome.diagnostic,
            )
        if isinstance(
            self.outcome,
            (
                ShadowRustInfrastructureFailure,
                ShadowRustIntegrationFailure,
            ),
        ):
            error = AuthoritativeVerifierUnavailable(
                VerifierImplementation.RUST,
                kind=self.outcome.kind,
                summary=self.outcome.summary,
            )
            if self.failure_cause is not None:
                raise error from self.failure_cause
            raise error
        raise AuthoritativeVerifierUnavailable(
            VerifierImplementation.RUST,
            kind="shadow_skipped",
            summary="Rust authority cannot use a skipped observation",
        )


def _execute_python_verifier(module: IRModule) -> _PythonVerifierExecution:
    try:
        verified_module = IRVerifier(module).verify()
    except IRVerificationError as error:
        return _PythonVerifierExecution(
            module=module,
            outcome=normalize_python_rejection(error),
            error=error,
            traceback=error.__traceback__,
        )
    return _PythonVerifierExecution(
        module=verified_module,
        outcome=PythonShadowAccepted(),
    )


class VerifierAuthorityPipeline:
    """Run both verifiers, compare them, report, then resolve one authority."""

    def __init__(
        self,
        *,
        client: RustVerifierClient,
        sink: ShadowReportSink | None = None,
        registry: ShadowDivergenceRegistry | None = None,
        strict_sink_errors: bool = False,
        client_kind: str | None = None,
        configuration: VerifierAuthorityConfiguration | None = None,
    ) -> None:
        if registry is None:
            from .shadow_divergences import DEFAULT_SHADOW_DIVERGENCE_REGISTRY

            registry = DEFAULT_SHADOW_DIVERGENCE_REGISTRY
        if configuration is None:
            configuration = _AUTHORITY_CONFIGURATION
        if not isinstance(configuration, VerifierAuthorityConfiguration):
            raise TypeError(
                "configuration must be a VerifierAuthorityConfiguration"
            )
        self._client = client
        self._sink = sink if sink is not None else NullShadowReportSink()
        self._registry = registry
        self._strict_sink_errors = strict_sink_errors
        self._configuration = configuration
        self._client_kind = _bounded_summary(
            client_kind if client_kind is not None else type(client).__name__
        )

    @property
    def configuration(self) -> VerifierAuthorityConfiguration:
        """Return the single immutable authority policy used by this pipeline."""

        return self._configuration

    def verify(
        self,
        module: IRModule,
        *,
        stage: ShadowVerificationStage = ShadowVerificationStage.EXTERNAL,
    ) -> IRModule:
        """Execute both engines once and resolve only the configured authority."""

        python_execution = _execute_python_verifier(module)

        started_at = perf_counter()
        serialization_started_at = perf_counter()
        request_hash = ""
        protocol_version = RUST_VERIFIER_PROTOCOL_VERSION
        ir_schema_version = IR_SCHEMA_VERSION
        serialization_duration: float | None = None
        invocation_duration: float | None = None
        invocation_client_kind = self._client_kind
        rust_failure_cause: RustVerifierIntegrationError | None = None
        try:
            request = build_canonical_rust_verifier_request(module)
        except RustVerifierIntegrationError as error:
            serialization_duration = perf_counter() - serialization_started_at
            rust_outcome: ShadowRustObservation = _integration_failure(error)
            rust_failure_cause = error
        else:
            serialization_duration = perf_counter() - serialization_started_at
            request_hash = sha256(request.payload).hexdigest()
            protocol_version = request.protocol_version
            ir_schema_version = request.ir_schema_version
            invocation_started_at = perf_counter()
            try:
                invocation = self._client.verify(request)
            except RustVerifierIntegrationError as error:
                invocation_duration = perf_counter() - invocation_started_at
                rust_outcome = _integration_failure(error)
                rust_failure_cause = error
            else:
                invocation_duration = perf_counter() - invocation_started_at
                rust_outcome = _normalize_rust_invocation(invocation)
                invocation_client_kind = invocation.metadata.client_kind.value

        comparison = compare_shadow_outcomes(
            python_execution.outcome,
            rust_outcome,
            request_hash=request_hash,
            registry=self._registry,
            protocol_version=protocol_version,
            ir_schema_version=ir_schema_version,
        )
        rust_execution = _RustVerifierExecution(
            module=module,
            outcome=rust_outcome,
            failure_cause=rust_failure_cause,
        )
        executions = {
            VerifierImplementation.PYTHON: python_execution,
            VerifierImplementation.RUST: rust_execution,
        }
        authority_implementation = self._configuration.authority
        shadow_implementation = self._configuration.shadow
        authority_execution = executions[authority_implementation]
        shadow_execution = executions[shadow_implementation]
        failure_kind, failure_summary = _failure_metadata(rust_outcome)
        report = ShadowVerificationReport(
            authoritative=authority_execution.outcome,
            shadow=shadow_execution.outcome,
            comparison=comparison,
            metadata=ShadowOperationalMetadata(
                request_sha256=request_hash or None,
                client_kind=invocation_client_kind,
                protocol_version=protocol_version,
                ir_schema_version=ir_schema_version,
                stage=stage,
                serialization_duration_seconds=serialization_duration,
                rust_invocation_duration_seconds=invocation_duration,
                total_shadow_duration_seconds=perf_counter() - started_at,
                documented_rule_id=comparison.documented_rule_id,
                failure_kind=failure_kind,
                failure_summary=failure_summary,
            ),
        )

        sink_error: Exception | None = None
        try:
            self._sink.emit(report)
        except Exception as error:
            if self._strict_sink_errors:
                sink_error = error

        verified_module = authority_execution.resolve()
        if sink_error is not None:
            raise sink_error
        return verified_module


class ShadowVerifierCoordinator(VerifierAuthorityPipeline):
    """Compatibility name for the default Python-authoritative pipeline."""


def _normalize_rust_invocation(
    invocation: RustVerifierInvocation,
) -> ShadowRustObservation:
    if not isinstance(invocation, RustVerifierInvocation):
        raise TypeError("Rust verifier client returned an invalid invocation")
    outcome = invocation.outcome
    if isinstance(outcome, RustVerifierAcceptedOutcome):
        return ShadowRustAccepted()
    if isinstance(outcome, RustVerifierRejectedOutcome):
        diagnostic = outcome.diagnostic
        return ShadowRustRejected(
            ShadowDiagnosticKey(
                invariant_id=diagnostic.invariant_id,
                category=diagnostic.category,
                phase=diagnostic.phase,
                function_index=diagnostic.function_index,
                function_name=diagnostic.function_name,
                block_index=diagnostic.block_index,
                block_name=diagnostic.block_name,
                instruction_index=diagnostic.instruction_index,
                instruction_kind=diagnostic.instruction_kind,
            )
        )
    if isinstance(outcome, RustVerifierInfrastructureFailure):
        kind = outcome.kind.value
        return ShadowRustInfrastructureFailure(
            kind=kind,
            summary=_bounded_summary(
                f"Rust verifier reported infrastructure failure {kind}"
            ),
        )
    raise TypeError("Rust verifier invocation carried an unknown outcome")


def _integration_failure(
    error: RustVerifierIntegrationError,
) -> ShadowRustIntegrationFailure:
    kind = _stable_exception_kind(error)
    return ShadowRustIntegrationFailure(
        kind=kind,
        summary=_bounded_summary(f"Rust verifier integration failed: {kind}"),
    )


def _failure_metadata(
    outcome: ShadowRustObservation,
) -> tuple[str | None, str | None]:
    if isinstance(
        outcome,
        (ShadowRustInfrastructureFailure, ShadowRustIntegrationFailure),
    ):
        return outcome.kind, outcome.summary
    return None, None


def _diagnostics_are_semantically_compatible(
    left: ShadowDiagnosticKey,
    right: ShadowDiagnosticKey,
) -> bool:
    if left.invariant_id != right.invariant_id:
        return False
    fields = (
        "category",
        "phase",
        "function_index",
        "function_name",
        "block_index",
        "block_name",
        "instruction_index",
        "instruction_kind",
    )
    missing_context = False
    for name in fields:
        left_value = getattr(left, name)
        right_value = getattr(right, name)
        if left_value is not None and right_value is not None:
            if left_value != right_value:
                return False
        elif left_value is not right_value:
            missing_context = True
    return missing_context


def _stable_exception_kind(error: Exception) -> str:
    name = type(error).__name__
    words = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return words.removeprefix("rust_verifier_")


def _bounded_summary(message: str) -> str:
    normalized = _WHITESPACE.sub(" ", message).strip()
    if len(normalized) <= _SUMMARY_LIMIT:
        return normalized
    return normalized[: _SUMMARY_LIMIT - 1] + "…"


def _snapshot_outcome(outcome: object) -> object:
    if isinstance(outcome, PythonShadowAccepted | ShadowRustAccepted):
        return {"status": "accepted"}
    if isinstance(outcome, PythonShadowRejected):
        return {
            "status": "rejected",
            "diagnostic": _snapshot_diagnostic(outcome.comparison_key()),
        }
    if isinstance(outcome, ShadowRustRejected):
        return {
            "status": "rejected",
            "diagnostic": _snapshot_diagnostic(outcome.diagnostic),
        }
    if isinstance(outcome, ShadowRustInfrastructureFailure):
        return {
            "status": "infrastructure_failure",
            "kind": outcome.kind,
            "summary": outcome.summary,
        }
    if isinstance(outcome, ShadowRustIntegrationFailure):
        return {
            "status": "integration_failure",
            "kind": outcome.kind,
            "summary": outcome.summary,
        }
    if isinstance(outcome, ShadowRustSkipped):
        return {"status": "skipped", "reason": outcome.reason}
    raise TypeError(f"Unknown shadow outcome: {type(outcome).__name__}")


def _snapshot_key(key: ShadowOutcomeKey) -> object:
    if len(key) == 2 and isinstance(key[1], ShadowDiagnosticKey):
        return [key[0], _snapshot_diagnostic(key[1])]
    return list(key)


def _snapshot_diagnostic(key: ShadowDiagnosticKey) -> dict[str, object]:
    return {
        "invariant_id": key.invariant_id,
        "category": key.category.value if key.category is not None else None,
        "phase": key.phase.value if key.phase is not None else None,
        "function_index": key.function_index,
        "function_name": key.function_name,
        "block_index": key.block_index,
        "block_name": key.block_name,
        "instruction_index": key.instruction_index,
        "instruction_kind": key.instruction_kind,
    }


__all__ = [
    "AuthorityResult",
    "AuthoritativeVerificationError",
    "AuthoritativeVerifierRejected",
    "AuthoritativeVerifierUnavailable",
    "CollectingShadowReportSink",
    "ComparisonResult",
    "NullShadowReportSink",
    "PythonShadowAccepted",
    "PythonShadowOutcome",
    "PythonShadowRejected",
    "ShadowClassification",
    "ShadowComparison",
    "ShadowDiagnosticKey",
    "ShadowOperationalMetadata",
    "ShadowOutcomeKey",
    "ShadowReportSink",
    "ShadowRustAccepted",
    "ShadowRustInfrastructureFailure",
    "ShadowRustIntegrationFailure",
    "ShadowRustObservation",
    "ShadowRustRejected",
    "ShadowRustSkipped",
    "ShadowResult",
    "ShadowVerificationReport",
    "ShadowVerificationStage",
    "ShadowVerifierCoordinator",
    "VerifierAuthorityConfiguration",
    "VerifierAuthorityMode",
    "VerifierAuthorityPipeline",
    "VerifierImplementation",
    "VerifierObservation",
    "compare_shadow_outcomes",
    "normalize_python_rejection",
    "python_shadow_outcome_key",
    "rust_shadow_outcome_key",
]
