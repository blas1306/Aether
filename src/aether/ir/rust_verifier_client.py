"""Transport-neutral client contract for Rust Initial IR verification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Protocol, TypeAlias, runtime_checkable

from .dto import IR_SCHEMA_VERSION, ir_module_to_dto
from .model import IRModule
from .verification_result import VerifierCategory


RUST_VERIFIER_PROTOCOL_VERSION = 1
_INVARIANT_PATTERN = re.compile(r"IRV-[0-9]{3}")


class RustVerifierIntegrationError(RuntimeError):
    """Base class for failures at a Rust verifier integration boundary."""


class RustVerifierAdapterError(RustVerifierIntegrationError):
    """Base class for subprocess adapter failures without a trusted response."""


class RustVerifierRequestConstructionError(RustVerifierIntegrationError):
    """Raised when an IR module cannot become one canonical request."""


class RustVerifierClientKind(str, Enum):
    """Stable identifiers for transport implementations."""

    SUBPROCESS = "subprocess"
    PYO3 = "pyo3"


class RustVerifierPhase(str, Enum):
    """Verification phases shared by verifier clients."""

    STRUCTURE = "structure"
    TYPES = "types"
    SSA = "ssa"
    DOMINANCE = "dominance"
    LIFECYCLE = "lifecycle"
    RETURNS = "returns"


class RustVerifierInfrastructureFailureKind(str, Enum):
    """Transport-neutral infrastructure failure classifications."""

    INVALID_REQUEST = "invalid_request"
    INCOMPATIBLE_VERSION = "incompatible_version"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    INVALID_MODULE = "invalid_module"
    INPUT_IO = "input_io"
    INTERNAL = "internal"


@dataclass(frozen=True)
class CanonicalRustVerifierRequest:
    """One deterministic request reusable by every verifier transport."""

    payload: bytes
    protocol_version: int
    ir_schema_version: int

    def __post_init__(self) -> None:
        if type(self.payload) is not bytes:
            raise TypeError("payload must be bytes")
        for name, value in (
            ("protocol_version", self.protocol_version),
            ("ir_schema_version", self.ir_schema_version),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class RustVerifierDiagnosticComparisonKey:
    """Message-free semantic identity for one verifier diagnostic."""

    invariant_id: str
    phase: RustVerifierPhase
    category: VerifierCategory
    function_index: int | None
    function_name: str | None
    block_index: int | None
    block_name: str | None
    instruction_index: int | None
    instruction_kind: str | None


@dataclass(frozen=True)
class RustVerifierNormalizedDiagnostic:
    """Transport-neutral diagnostic retaining prose outside its identity."""

    invariant_id: str
    phase: RustVerifierPhase
    category: VerifierCategory
    message: str
    function_index: int | None
    function_name: str | None
    block_index: int | None
    block_name: str | None
    instruction_index: int | None
    instruction_kind: str | None

    def __post_init__(self) -> None:
        if _INVARIANT_PATTERN.fullmatch(self.invariant_id) is None:
            raise ValueError("invariant_id must have the form IRV-NNN")

    def comparison_key(self) -> RustVerifierDiagnosticComparisonKey:
        """Return semantic identity without presentation-oriented prose."""

        return RustVerifierDiagnosticComparisonKey(
            invariant_id=self.invariant_id,
            phase=self.phase,
            category=self.category,
            function_index=self.function_index,
            function_name=self.function_name,
            block_index=self.block_index,
            block_name=self.block_name,
            instruction_index=self.instruction_index,
            instruction_kind=self.instruction_kind,
        )


@dataclass(frozen=True)
class RustVerifierAcceptedOutcome:
    """The verifier accepted the request semantically."""


@dataclass(frozen=True)
class RustVerifierRejectedOutcome:
    """The verifier rejected the request with a normalized diagnostic."""

    diagnostic: RustVerifierNormalizedDiagnostic


@dataclass(frozen=True)
class RustVerifierInfrastructureFailure:
    """The verifier returned a trusted non-semantic failure."""

    kind: RustVerifierInfrastructureFailureKind
    message: str


RustVerifierOutcome: TypeAlias = (
    RustVerifierAcceptedOutcome
    | RustVerifierRejectedOutcome
    | RustVerifierInfrastructureFailure
)
RustVerifierOutcomeComparisonKey: TypeAlias = (
    tuple[str]
    | tuple[str, RustVerifierDiagnosticComparisonKey]
    | tuple[str, RustVerifierInfrastructureFailureKind]
)


@dataclass(frozen=True)
class RustVerifierInvocationTransportMetadata:
    """Marker base for optional client-specific invocation metadata."""


@dataclass(frozen=True)
class RustVerifierInvocationMetadata:
    """Metadata meaningful independently from semantic outcome equality."""

    client_kind: RustVerifierClientKind
    duration_seconds: float | None
    protocol_version: int
    ir_schema_version: int
    transport_metadata: RustVerifierInvocationTransportMetadata | None = None


@dataclass(frozen=True)
class RustVerifierInvocation:
    """One verifier outcome and separately inspectable invocation metadata."""

    outcome: RustVerifierOutcome
    metadata: RustVerifierInvocationMetadata


@runtime_checkable
class RustVerifierClient(Protocol):
    """Structural interface implemented by every Rust verifier transport."""

    def verify(
        self,
        request: CanonicalRustVerifierRequest,
    ) -> RustVerifierInvocation:
        ...


def build_canonical_rust_verifier_request(
    module: IRModule,
) -> CanonicalRustVerifierRequest:
    """Materialize and encode ``module`` exactly once as protocol-v1 JSON."""

    try:
        module_dto = ir_module_to_dto(
            module,
            schema_version=IR_SCHEMA_VERSION,
        )
        envelope = {
            "protocol_version": RUST_VERIFIER_PROTOCOL_VERSION,
            "operation": "verify",
            "module": module_dto,
        }
        text = json.dumps(
            envelope,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload = (text + "\n").encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as error:
        raise RustVerifierRequestConstructionError(
            "Cannot construct canonical Rust verifier request"
        ) from error
    return CanonicalRustVerifierRequest(
        payload=payload,
        protocol_version=RUST_VERIFIER_PROTOCOL_VERSION,
        ir_schema_version=IR_SCHEMA_VERSION,
    )


def rust_verifier_outcome_comparison_key(
    outcome: RustVerifierOutcome,
) -> RustVerifierOutcomeComparisonKey:
    """Return the explicit message- and metadata-free outcome identity."""

    if isinstance(outcome, RustVerifierAcceptedOutcome):
        return ("accepted",)
    if isinstance(outcome, RustVerifierRejectedOutcome):
        return ("rejected", outcome.diagnostic.comparison_key())
    return ("infrastructure_failure", outcome.kind)


__all__ = [
    "CanonicalRustVerifierRequest",
    "RUST_VERIFIER_PROTOCOL_VERSION",
    "RustVerifierAcceptedOutcome",
    "RustVerifierAdapterError",
    "RustVerifierClient",
    "RustVerifierClientKind",
    "RustVerifierDiagnosticComparisonKey",
    "RustVerifierInfrastructureFailure",
    "RustVerifierInfrastructureFailureKind",
    "RustVerifierIntegrationError",
    "RustVerifierInvocation",
    "RustVerifierInvocationMetadata",
    "RustVerifierInvocationTransportMetadata",
    "RustVerifierNormalizedDiagnostic",
    "RustVerifierOutcome",
    "RustVerifierOutcomeComparisonKey",
    "RustVerifierPhase",
    "RustVerifierRejectedOutcome",
    "RustVerifierRequestConstructionError",
    "build_canonical_rust_verifier_request",
    "rust_verifier_outcome_comparison_key",
]
