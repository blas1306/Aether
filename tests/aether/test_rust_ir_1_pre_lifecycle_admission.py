from __future__ import annotations

import json
from pathlib import Path

import pytest

from aether.errors import AetherRuntimeError
from aether.ir import (
    AuthoritativeVerifierRejected,
    CollectingShadowReportSink,
    DoubleFailClosedVerifierPipeline,
    IRBasicBlock,
    IRDestroy,
    IRFunction,
    IRInitDefault,
    IRModule,
    IRReturn,
    IRSourceLocation,
    IRStorage,
    IRVerificationError,
    IRVerifier,
    RustVerifierAccepted,
    RustVerifierAcceptedOutcome,
    RustVerifierClientKind,
    RustVerifierInvocation,
    RustVerifierInvocationMetadata,
    RustVerifierNormalizedDiagnostic,
    RustVerifierPhase,
    RustVerifierRejected,
    RustVerifierRejectedOutcome,
    ShadowClassification,
    ShadowVerificationStage,
    IntType,
    VerifierCategory,
    VoidType,
    expand_lifecycle,
    verify_module_with_rust,
)
from aether.ir.dto import ir_module_to_dto
from aether.ir.lifecycle import LifecycleExpander
from aether.ir.rust_verifier import PersistentSubprocessRustVerifierClient
from aether.pipeline import IRBackend, prepare_typed_program
from aether.typechecker import TypeChecker


BORROW_TO_OWNED_SOURCE = """
List<int> first(List<List<int>> values) {
    for (List<int> item in values) { return item; }
    return {};
}
int main() {
    List<List<int>> values = {{1, 2}};
    List<int> saved = first(values);
    values.clear();
    println(saved);
    return 0;
}
"""


def _accepted_module(*, location: IRSourceLocation | None = None) -> IRModule:
    instructions = (
        [
            IRInitDefault(IRStorage("slot", IntType()), location),
            IRDestroy(IRStorage("slot", IntType())),
            IRReturn(),
        ]
        if location is not None
        else [IRReturn()]
    )
    return IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("entry", instructions)],
            )
        ]
    )


def _rejected_module() -> IRModule:
    return IRModule(
        [IRFunction("main", [], VoidType(), [IRBasicBlock("entry", [])])]
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


class _TracingAcceptedClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.module_dto: object | None = None

    def verify(self, request: object) -> RustVerifierInvocation:
        self.events.append("rust_verify_module")
        payload = json.loads(request.payload)  # type: ignore[attr-defined]
        self.module_dto = payload["module"]
        return _invocation(RustVerifierAcceptedOutcome())


class _RejectingClient:
    def verify(self, request: object) -> RustVerifierInvocation:
        del request
        return _invocation(
            RustVerifierRejectedOutcome(
                RustVerifierNormalizedDiagnostic(
                    invariant_id="IRV-018",
                    phase=RustVerifierPhase.STRUCTURE,
                    category=VerifierCategory.CFG,
                    message="missing terminator",
                    function_index=0,
                    function_name="main",
                    block_index=0,
                    block_name="entry",
                    instruction_index=0,
                    instruction_kind="init_default",
                )
            )
        )


def test_product_order_and_snapshot_provenance_are_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ir.shadow_verifier as shadow_module

    events: list[str] = []
    client = _TracingAcceptedClient(events)
    sink = CollectingShadowReportSink()
    pipeline = DoubleFailClosedVerifierPipeline(client=client, sink=sink)
    original_python_verify = IRVerifier.verify
    original_expand = LifecycleExpander.expand

    def python_verify(verifier: IRVerifier) -> IRModule:
        events.append("python_ir_verifier")
        return original_python_verify(verifier)

    def lifecycle_expand(expander: LifecycleExpander) -> IRModule:
        events.append("python_lifecycle_expander")
        return original_expand(expander)

    monkeypatch.setattr(IRVerifier, "verify", python_verify)
    monkeypatch.setattr(LifecycleExpander, "expand", lifecycle_expand)
    monkeypatch.setattr(
        shadow_module,
        "production_initial_ir_admission_pipeline",
        lambda: pipeline,
    )

    typed = prepare_typed_program("int main() { return 0; }", TypeChecker())
    admitted = IRBackend().lower_verified(typed)
    expand_lifecycle(admitted)

    assert events == [
        "python_ir_verifier",
        "rust_verify_module",
        "python_lifecycle_expander",
    ]
    assert client.module_dto == ir_module_to_dto(admitted)
    assert len(sink.reports) == 1
    report = sink.reports[0]
    assert report.metadata.stage is ShadowVerificationStage.INITIAL
    assert report.comparison.classification is ShadowClassification.MATCH_ACCEPTED


def test_double_gate_preserves_python_rejection_even_when_rust_accepts() -> None:
    events: list[str] = []
    pipeline = DoubleFailClosedVerifierPipeline(
        client=_TracingAcceptedClient(events)
    )

    with pytest.raises(IRVerificationError):
        pipeline.verify(_rejected_module(), stage=ShadowVerificationStage.INITIAL)

    assert events == ["rust_verify_module"]


def test_rust_rejection_exposes_structured_context_and_source_location() -> None:
    location = IRSourceLocation(7, 11, "example.ae")
    pipeline = DoubleFailClosedVerifierPipeline(client=_RejectingClient())

    with pytest.raises(AuthoritativeVerifierRejected) as raised:
        pipeline.verify(
            _accepted_module(location=location),
            stage=ShadowVerificationStage.INITIAL,
        )

    error = raised.value
    assert error.category == "cfg"
    assert error.phase == "structure"
    assert error.code == "IRV-018"
    assert error.function == "main"
    assert error.block == "entry"
    assert error.source_location == location


def test_product_boundary_wraps_structured_rust_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.ir.shadow_verifier as shadow_module

    monkeypatch.setattr(
        shadow_module,
        "production_initial_ir_admission_pipeline",
        lambda: DoubleFailClosedVerifierPipeline(client=_RejectingClient()),
    )
    typed = prepare_typed_program("int main() { return 0; }", TypeChecker())

    with pytest.raises(AetherRuntimeError) as raised:
        IRBackend().lower_verified(typed)

    assert isinstance(raised.value.__cause__, AuthoritativeVerifierRejected)
    assert raised.value.__cause__.code == "IRV-018"


def test_persistent_double_gate_recovers_after_semantic_rejection(
    rust_verifier_executable: Path,
) -> None:
    sink = CollectingShadowReportSink()
    with PersistentSubprocessRustVerifierClient(
        executable=rust_verifier_executable
    ) as client:
        pipeline = DoubleFailClosedVerifierPipeline(client=client, sink=sink)
        assert (
            pipeline.verify(
                _accepted_module(),
                stage=ShadowVerificationStage.INITIAL,
            )
            is not None
        )
        with pytest.raises(IRVerificationError):
            pipeline.verify(
                _rejected_module(),
                stage=ShadowVerificationStage.INITIAL,
            )
        assert (
            pipeline.verify(
                _accepted_module(),
                stage=ShadowVerificationStage.INITIAL,
            )
            is not None
        )
        assert client.process_start_count == 1

    assert len(sink.reports) == 3
    assert sink.reports[0].comparison.classification is ShadowClassification.MATCH_ACCEPTED
    assert (
        sink.reports[1].comparison.classification
        is ShadowClassification.MATCH_REJECTED_SEMANTIC
    )
    assert sink.reports[2].comparison.classification is ShadowClassification.MATCH_ACCEPTED


def test_irv_041_proves_rust_gate_must_remain_pre_lifecycle(
    rust_verifier_executable: Path,
) -> None:
    typed = prepare_typed_program(BORROW_TO_OWNED_SOURCE, TypeChecker())
    pre_lifecycle = IRBackend().lower(typed)

    assert IRVerifier(pre_lifecycle).verify() is pre_lifecycle
    assert isinstance(
        verify_module_with_rust(
            pre_lifecycle,
            executable=rust_verifier_executable,
        ),
        RustVerifierAccepted,
    )

    post_lifecycle = expand_lifecycle(pre_lifecycle)
    rejection = verify_module_with_rust(
        post_lifecycle,
        executable=rust_verifier_executable,
    )
    assert isinstance(rejection, RustVerifierRejected)
    assert rejection.diagnostic.invariant == "IRV-041"
