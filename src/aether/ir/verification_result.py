from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from .model import IRModule
    from .verifier import IRVerificationError


class VerifierSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class VerifierCategory(str, Enum):
    DEFINITIONS = "definitions"
    TYPES = "types"
    CFG = "cfg"
    INSTRUCTIONS = "instructions"
    RETURNS = "returns"
    LIFECYCLE = "lifecycle"
    DATA_FLOW = "data_flow"
    BORROWING = "borrowing"
    CALLS = "calls"
    BUILTINS = "builtins"
    CONSTANTS = "constants"
    OPERATORS = "operators"
    STRUCTS = "structs"
    METHOD_RESULTS = "method_results"
    COLLECTIONS = "collections"
    LINEAR_ALGEBRA = "linear_algebra"


@dataclass(frozen=True)
class VerifierLocation:
    """An implementation-neutral source point used by verifier comparison."""

    line: int
    column: int
    path: str | None = None


@dataclass(frozen=True)
class VerifierFailure:
    """A verifier rejection without presentation-oriented diagnostic prose."""

    invariant_id: str
    severity: VerifierSeverity
    category: VerifierCategory
    primary_location: VerifierLocation | None = None
    secondary_locations: tuple[VerifierLocation, ...] = ()

    def __post_init__(self) -> None:
        if re.fullmatch(r"IRV-[0-9]{3}", self.invariant_id) is None:
            raise ValueError(
                f"Verifier invariant IDs must have the form IRV-NNN, got {self.invariant_id!r}"
            )
        object.__setattr__(self, "secondary_locations", tuple(self.secondary_locations))


@dataclass(frozen=True)
class VerifierResult:
    accepted: bool
    failures: tuple[VerifierFailure, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "failures", _ordered_failures(self.failures))
        if self.accepted == bool(self.failures):
            raise ValueError(
                "Accepted verifier results have no failures; "
                "rejected results have at least one"
            )


def accepted_verifier_result() -> VerifierResult:
    return VerifierResult(accepted=True)


def rejected_verifier_result(
    failures: Iterable[VerifierFailure],
) -> VerifierResult:
    return VerifierResult(accepted=False, failures=tuple(failures))


def normalize_ir_verification_error(error: IRVerificationError) -> VerifierResult:
    """Convert one current fail-fast Python verifier error to the shared contract."""

    failure = getattr(error, "normalized_failure", None)
    if not isinstance(failure, VerifierFailure):
        raise ValueError("IRVerificationError does not carry normalized verifier metadata")
    return rejected_verifier_result((failure,))


def verify_module_normalized(module: IRModule) -> VerifierResult:
    """Run the Python IR verifier and return its implementation-neutral outcome."""

    from .verifier import IRVerificationError, IRVerifier

    try:
        IRVerifier(module).verify()
    except IRVerificationError as error:
        return normalize_ir_verification_error(error)
    return accepted_verifier_result()


def _ordered_failures(
    failures: Iterable[VerifierFailure],
) -> tuple[VerifierFailure, ...]:
    return tuple(sorted(failures, key=_failure_order_key))


def _failure_order_key(failure: VerifierFailure) -> tuple[object, ...]:
    primary = _location_order_key(failure.primary_location)
    secondary = tuple(_location_order_key(location) for location in failure.secondary_locations)
    return (
        int(failure.invariant_id.removeprefix("IRV-")),
        failure.severity.value,
        failure.category.value,
        primary,
        secondary,
    )


def _location_order_key(location: VerifierLocation | None) -> tuple[object, ...]:
    if location is None:
        return (1, "", 0, 0)
    return (0, location.path or "", location.line, location.column)
