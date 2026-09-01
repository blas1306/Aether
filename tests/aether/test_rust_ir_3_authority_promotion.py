from __future__ import annotations

import json

import pytest

from aether.errors import AetherRuntimeError
from aether.ir import (
    AuthoritativeVerifierRejected,
    IRBasicBlock,
    IRFunction,
    IRModule,
    IRReturn,
    IRVerifier,
    LifecycleExpander,
    ProductInitialIRAuthorityProvenance,
    RustInitialIRProductAuthorityPipeline,
    RustVerifierAcceptedOutcome,
    RustVerifierClientKind,
    RustVerifierInvocation,
    RustVerifierInvocationMetadata,
    RustVerifierNormalizedDiagnostic,
    RustVerifierPhase,
    RustVerifierRejectedOutcome,
    ShadowVerificationStage,
    VerifierCategory,
    VoidType,
)
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program
from aether.typechecker import TypeChecker


def _module(*, valid: bool = True) -> IRModule:
    instructions = [IRReturn(None)] if valid else []
    return IRModule(
        [IRFunction("main", [], VoidType(), [IRBasicBlock("entry", instructions)])]
    )


def _invocation(outcome: object) -> RustVerifierInvocation:
    return RustVerifierInvocation(
        outcome=outcome,  # type: ignore[arg-type]
        metadata=RustVerifierInvocationMetadata(
            client_kind=RustVerifierClientKind.SUBPROCESS,
            duration_seconds=0.0,
            protocol_version=1,
            ir_schema_version=1,
        ),
    )


class _SequenceClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def verify(self, request: object) -> RustVerifierInvocation:
        assert json.loads(request.payload)["operation"] == "verify"  # type: ignore[attr-defined]
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return _invocation(outcome)


def _rejection() -> RustVerifierRejectedOutcome:
    return RustVerifierRejectedOutcome(
        RustVerifierNormalizedDiagnostic(
            invariant_id="IRV-018",
            phase=RustVerifierPhase.STRUCTURE,
            category=VerifierCategory.CFG,
            message="missing terminator",
            function_index=0,
            function_name="main",
            block_index=0,
            block_name="entry",
            instruction_index=None,
            instruction_kind=None,
        )
    )


def test_product_authority_accepts_without_consulting_python_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_verifier: IRVerifier) -> IRModule:
        raise AssertionError("Python IRVerifier entered product acceptance")

    monkeypatch.setattr(IRVerifier, "verify", forbidden)
    pipeline = RustInitialIRProductAuthorityPipeline(
        client=_SequenceClient([RustVerifierAcceptedOutcome()])
    )
    module = _module()

    assert pipeline.verify(module) is module
    provenance = pipeline.last_provenance
    assert isinstance(provenance, ProductInitialIRAuthorityProvenance)
    assert provenance.semantic_snapshot() == {
        "product_authority": "rust",
        "python_ir_verifier_role": "oracle_only",
        "representation_phase": "pre_lifecycle",
        "stage": "initial",
        "rust_verify_module_executed": True,
        "rust_verify_module_accepted": True,
        "python_ir_verifier_consulted": False,
        "request_sha256": provenance.request_sha256,
        "client_kind": "subprocess",
        "protocol_version": 1,
        "ir_schema_version": 1,
        "failure_kind": None,
    }
    assert provenance.request_sha256 is not None


def test_rust_rejection_is_final_and_next_request_recovers() -> None:
    client = _SequenceClient([_rejection(), RustVerifierAcceptedOutcome()])
    pipeline = RustInitialIRProductAuthorityPipeline(client=client)

    with pytest.raises(AuthoritativeVerifierRejected) as caught:
        pipeline.verify(_module(valid=False))
    assert caught.value.code == "IRV-018"
    assert pipeline.last_provenance is not None
    assert pipeline.last_provenance.rust_verify_module_accepted is False
    assert pipeline.verify(_module()) is not None
    assert client.calls == 2


def test_product_authority_rejects_post_lifecycle_phase() -> None:
    pipeline = RustInitialIRProductAuthorityPipeline(
        client=_SequenceClient([RustVerifierAcceptedOutcome()])
    )
    with pytest.raises(ValueError, match="pre-lifecycle only"):
        pipeline.verify(
            _module(), stage=ShadowVerificationStage.POST_OPTIMIZATION
        )


def test_backend_order_is_rust_then_python_lifecycle_with_no_python_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ir.shadow_verifier as shadow_module

    events: list[str] = []

    class RecordingClient(_SequenceClient):
        def verify(self, request: object) -> RustVerifierInvocation:
            events.append("rust_verify_module")
            return super().verify(request)

    client = RecordingClient([RustVerifierAcceptedOutcome()])
    pipeline = RustInitialIRProductAuthorityPipeline(client=client)
    original_expand = LifecycleExpander.expand

    def forbidden(_verifier: IRVerifier) -> IRModule:
        raise AssertionError("Python IRVerifier entered product path")

    def expand(expander: LifecycleExpander) -> IRModule:
        events.append("python_lifecycle_expander")
        return original_expand(expander)

    monkeypatch.setattr(IRVerifier, "verify", forbidden)
    monkeypatch.setattr(LifecycleExpander, "expand", expand)
    monkeypatch.setattr(
        shadow_module,
        "production_initial_ir_admission_pipeline",
        lambda: pipeline,
    )
    backend = IRBackend()
    typed = prepare_typed_program("int main() { return 0; }", TypeChecker())
    initial = backend.lower_verified(typed)
    backend.optimize_verified(initial)

    assert events == ["rust_verify_module", "python_lifecycle_expander"]
    assert backend.last_initial_ir_authority_provenance is pipeline.last_provenance


def test_rejection_stops_lifecycle_and_ssa_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ir.shadow_verifier as shadow_module

    pipeline = RustInitialIRProductAuthorityPipeline(
        client=_SequenceClient([_rejection()])
    )
    lifecycle_calls = 0
    ssa_build_calls = 0

    def lifecycle_forbidden(_expander: LifecycleExpander) -> IRModule:
        nonlocal lifecycle_calls
        lifecycle_calls += 1
        raise AssertionError("lifecycle ran after Rust rejection")

    def ssa_forbidden(_pipeline: SSAPipeline, _module: IRModule):
        nonlocal ssa_build_calls
        ssa_build_calls += 1
        raise AssertionError("SSA construction ran after Rust rejection")

    monkeypatch.setattr(LifecycleExpander, "expand", lifecycle_forbidden)
    monkeypatch.setattr(SSAPipeline, "build", ssa_forbidden)
    monkeypatch.setattr(
        shadow_module,
        "production_initial_ir_admission_pipeline",
        lambda: pipeline,
    )
    with pytest.raises(AetherRuntimeError):
        SSAPipeline().run(_module(valid=False))
    assert lifecycle_calls == 0
    assert ssa_build_calls == 0
