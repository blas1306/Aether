"""Shadow-independent, refinement-verified Rust SSA acceptance.

This module deliberately does not import the Python SSA builder, its CFG or
dominance machinery, phi placement, renaming, or the Rust/Python canonical
comparison.  The production policy and its qualification API share this one
fail-closed implementation so their ordering cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import perf_counter
from typing import Callable, Mapping, Protocol

from aether.ir.dto import ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.ir.model import IRModule
from aether.ir.verifier import IRVerifier

from .dto import ssa_module_from_dto
from .model import SSAModule
from .refinement_verifier import verify_ssa_refinement
from .verifier import SSAVerifier


SHADOW_INDEPENDENT_QUALIFICATION_REVISION = 1
SHADOW_INDEPENDENT_STAGE_MANIFEST = (
    "initial_ir_verification",
    "lifecycle_normalization",
    "rust_ssa_lowering_and_verification",
    "schema_v2_import",
    "imported_ssa_verification",
    "same_input_integrity_before_refinement",
    "independent_refinement_verification",
    "same_input_integrity_after_refinement",
    "final_generic_verification",
    "accept",
)


class RustSSAQualificationClient(Protocol):
    """The minimal companion surface consumed by qualification."""

    def lower(self, payload: bytes) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class ShadowIndependentQualificationTrace:
    """Per-request structural evidence; no counters are process-global."""

    qualification_revision: int
    mode: str
    accepted: bool
    completed_stages: tuple[str, ...]
    failed_stage: str | None
    failure_classification: str | None
    stage_execution_counts: Mapping[str, int]
    stage_seconds: Mapping[str, float]
    rust_ssa_lowering_executed: bool
    rust_side_verification_succeeded: bool
    refinement_verification_executed: bool
    final_generic_verification_executed: bool
    python_general_ssa_builder_instantiated: bool
    python_ssa_lowering_executed: bool
    canonical_rust_python_comparison_executed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "qualification_revision": self.qualification_revision,
            "mode": self.mode,
            "accepted": self.accepted,
            "completed_stages": list(self.completed_stages),
            "failed_stage": self.failed_stage,
            "failure_classification": self.failure_classification,
            "stage_execution_counts": dict(self.stage_execution_counts),
            "stage_seconds": dict(self.stage_seconds),
            "rust_ssa_lowering_executed": self.rust_ssa_lowering_executed,
            "rust_side_verification_succeeded": (
                self.rust_side_verification_succeeded
            ),
            "refinement_verification_executed": (
                self.refinement_verification_executed
            ),
            "final_generic_verification_executed": (
                self.final_generic_verification_executed
            ),
            "python_general_ssa_builder_instantiated": (
                self.python_general_ssa_builder_instantiated
            ),
            "python_ssa_lowering_executed": self.python_ssa_lowering_executed,
            "canonical_rust_python_comparison_executed": (
                self.canonical_rust_python_comparison_executed
            ),
        }


class ShadowIndependentRustAuthorityFailure(RuntimeError):
    """Fail-closed rejection with the trace completed before the failure."""

    def __init__(self, trace: ShadowIndependentQualificationTrace, detail: str):
        self.trace = trace
        self.detail = detail[:240]
        super().__init__(
            json.dumps(
                {"trace": trace.to_dict(), "detail": self.detail},
                sort_keys=True,
            )
        )


@dataclass(frozen=True)
class _QualificationHooks:
    """Private, request-local fault-injection hooks used by qualification."""

    after_imported_verification: (
        Callable[[SSAModule], SSAModule | None] | None
    ) = None
    after_refinement: Callable[[SSAModule], SSAModule | None] | None = None
    after_normalization: Callable[[IRModule], None] | None = None


class _TraceRecorder:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.completed: list[str] = []
        self.counts = {stage: 0 for stage in SHADOW_INDEPENDENT_STAGE_MANIFEST}
        self.seconds: dict[str, float] = {}
        self.rust_executed = False
        self.rust_verified = False
        self.refinement_executed = False
        self.final_verification_executed = False

    def run(self, stage: str, operation: Callable[[], object]) -> object:
        started = perf_counter()
        value = operation()
        self.seconds[stage] = perf_counter() - started
        self.counts[stage] += 1
        self.completed.append(stage)
        return value

    def trace(
        self,
        *,
        accepted: bool,
        failed_stage: str | None = None,
        classification: str | None = None,
    ) -> ShadowIndependentQualificationTrace:
        return ShadowIndependentQualificationTrace(
            qualification_revision=SHADOW_INDEPENDENT_QUALIFICATION_REVISION,
            mode=self.mode,
            accepted=accepted,
            completed_stages=tuple(self.completed),
            failed_stage=failed_stage,
            failure_classification=classification,
            stage_execution_counts=dict(self.counts),
            stage_seconds=dict(self.seconds),
            rust_ssa_lowering_executed=self.rust_executed,
            rust_side_verification_succeeded=self.rust_verified,
            refinement_verification_executed=self.refinement_executed,
            final_generic_verification_executed=(
                self.final_verification_executed
            ),
            python_general_ssa_builder_instantiated=False,
            python_ssa_lowering_executed=False,
            canonical_rust_python_comparison_executed=False,
        )


def _raise_failure(
    recorder: _TraceRecorder,
    stage: str,
    classification: str,
    exception: BaseException,
) -> None:
    raise ShadowIndependentQualificationFailure(
        recorder.trace(
            accepted=False,
            failed_stage=stage,
            classification=classification,
        ),
        str(exception),
    ) from exception


def _lower_shadow_independent_rust_ssa(
    module: IRModule,
    client: RustSSAQualificationClient,
    *,
    mode: str,
    _hooks: _QualificationHooks | None = None,
) -> tuple[SSAModule, ShadowIndependentQualificationTrace]:
    """Accept Rust SSA without executing or consuming a Python SSA result."""

    recorder = _TraceRecorder(mode)
    hooks = _hooks or _QualificationHooks()

    try:
        verified = recorder.run(
            "initial_ir_verification", lambda: IRVerifier(module).verify()
        )
    except Exception as exc:
        _raise_failure(
            recorder,
            "initial_ir_verification",
            "initial_ir_verifier_failure",
            exc,
        )
    assert isinstance(verified, IRModule)
    source_snapshot = ir_module_to_dto(verified)

    try:
        normalized = recorder.run(
            "lifecycle_normalization", lambda: expand_lifecycle(verified)
        )
    except Exception as exc:
        _raise_failure(
            recorder,
            "lifecycle_normalization",
            "lifecycle_normalization_failure",
            exc,
        )
    assert isinstance(normalized, IRModule)
    normalized_snapshot = ir_module_to_dto(normalized)
    if hooks.after_normalization is not None:
        hooks.after_normalization(normalized)
    payload = json.dumps(normalized_snapshot, separators=(",", ":")).encode()

    try:
        recorder.rust_executed = True
        response = recorder.run(
            "rust_ssa_lowering_and_verification", lambda: client.lower(payload)
        )
        if not isinstance(response, Mapping):
            raise TypeError("Rust companion response is not an object")
        if response.get("ok") is not True:
            raise RuntimeError(str(response.get("error", "Rust lowering rejected")))
        response_ssa = response.get("ssa")
        if not isinstance(response_ssa, dict):
            raise TypeError("Rust companion response has no schema-v2 SSA object")
        recorder.rust_verified = True
    except Exception as exc:
        _raise_failure(
            recorder,
            "rust_ssa_lowering_and_verification",
            "rust_lowering_or_verifier_failure",
            exc,
        )

    try:
        imported = recorder.run(
            "schema_v2_import", lambda: ssa_module_from_dto(response_ssa)
        )
    except Exception as exc:
        _raise_failure(recorder, "schema_v2_import", "schema_v2_import_failure", exc)
    assert isinstance(imported, SSAModule)

    try:
        recorder.run(
            "imported_ssa_verification",
            lambda: SSAVerifier(imported).verify(),
        )
    except Exception as exc:
        _raise_failure(
            recorder,
            "imported_ssa_verification",
            "imported_ssa_verifier_failure",
            exc,
        )
    if hooks.after_imported_verification is not None:
        replacement = hooks.after_imported_verification(imported)
        if replacement is not None:
            imported = replacement

    def verify_integrity() -> None:
        if ir_module_to_dto(verified) != source_snapshot:
            raise RuntimeError("source Initial IR changed during qualification")
        if ir_module_to_dto(normalized) != normalized_snapshot:
            raise RuntimeError("normalized Initial IR changed during qualification")

    try:
        recorder.run("same_input_integrity_before_refinement", verify_integrity)
    except Exception as exc:
        _raise_failure(
            recorder,
            "same_input_integrity_before_refinement",
            "same_input_integrity_failure",
            exc,
        )

    try:
        recorder.refinement_executed = True
        recorder.run(
            "independent_refinement_verification",
            lambda: verify_ssa_refinement(normalized, imported),
        )
    except Exception as exc:
        _raise_failure(
            recorder,
            "independent_refinement_verification",
            "refinement_verifier_failure",
            exc,
        )
    if hooks.after_refinement is not None:
        replacement = hooks.after_refinement(imported)
        if replacement is not None:
            imported = replacement

    try:
        recorder.run("same_input_integrity_after_refinement", verify_integrity)
    except Exception as exc:
        _raise_failure(
            recorder,
            "same_input_integrity_after_refinement",
            "same_input_integrity_failure",
            exc,
        )

    try:
        recorder.final_verification_executed = True
        recorder.run(
            "final_generic_verification",
            lambda: SSAVerifier(imported).verify(),
        )
    except Exception as exc:
        _raise_failure(
            recorder,
            "final_generic_verification",
            "final_generic_verifier_failure",
            exc,
        )

    recorder.run("accept", lambda: None)
    return imported, recorder.trace(accepted=True)


def lower_with_shadow_independent_rust_authority(
    module: IRModule,
    client: RustSSAQualificationClient,
) -> tuple[SSAModule, ShadowIndependentQualificationTrace]:
    """Execute the RUST-4.5 production ordering with no Python fallback."""
    return _lower_shadow_independent_rust_ssa(
        module,
        client,
        mode="rust_ssa_authority_refinement_verified",
    )


def qualify_shadow_independent_rust_ssa(
    module: IRModule,
    client: RustSSAQualificationClient,
    *,
    _hooks: _QualificationHooks | None = None,
) -> tuple[SSAModule, ShadowIndependentQualificationTrace]:
    """Run the preserved RUST-4.4 qualification entry point."""
    return _lower_shadow_independent_rust_ssa(
        module,
        client,
        mode="qualification_only_shadow_independent",
        _hooks=_hooks,
    )


# Backward-compatible RUST-4.4 name.  The implementation now also serves the
# production mode, so the primary class name no longer implies test-only use.
ShadowIndependentQualificationFailure = ShadowIndependentRustAuthorityFailure
