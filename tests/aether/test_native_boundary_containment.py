from __future__ import annotations

from dataclasses import replace

import pytest

from aether.backend.llvm import LLVMBackend, LLVMPrinter
from aether.backend.llvm.native_boundary import (
    NativeBoundaryDiagnostic,
    NativeBoundaryRequest,
    NativeBoundaryVerificationError,
    NativeBoundaryVerifier,
    RUNTIME_HELPER_FAMILY_INVENTORY,
    RUNTIME_HELPER_INVENTORY,
    RuntimeExceptionBehavior,
    RuntimeVisibility,
)
from aether.diagnostics import DiagnosticCategory, diagnostic_from_exception
from aether.ir import IRLowerer
from aether.pipeline import parse_source
from aether.ssa import GeneralSSABuilder, SSAPackException
from aether.ir.types import ExceptionEventType, IntType
from aether.ssa.model import (
    SSABasicBlock,
    SSACall,
    SSAFunction,
    SSAInvoke,
    SSAModule,
    SSAValue,
)
from aether.typechecker import TypeChecker


SOURCE = """
struct FileError implements Error {
    string text;
    string message() { return text; }
}
int main() { throw FileError("boundary"); }
"""


def _lower(source: str = SOURCE):
    program = parse_source(source)
    TypeChecker().check(program)
    return GeneralSSABuilder().build(IRLowerer().lower(program))


def _request(**changes: object) -> NativeBoundaryRequest:
    values: dict[str, object] = {
        "name": "foreign_operation",
        "kind": "external-invoke",
    }
    values.update(changes)
    return NativeBoundaryRequest(**values)


@pytest.mark.parametrize(
    ("boundary", "code"),
    [
        (_request(may_throw=True), NativeBoundaryDiagnostic.UNSUPPORTED_EXTERNAL_MAY_THROW),
        (
            _request(kind="callback", may_throw=True),
            NativeBoundaryDiagnostic.THROWING_CALLBACK,
        ),
        (
            _request(kind="raw-c", event_transport=True),
            NativeBoundaryDiagnostic.EXCEPTION_CROSSING_FOREIGN_BOUNDARY,
        ),
        (
            _request(kind="raw-c", transfers_event_ownership=True),
            NativeBoundaryDiagnostic.WRONG_OWNERSHIP_TRANSFER,
        ),
    ],
)
def test_unsupported_native_boundaries_reject_before_llvm(
    boundary: NativeBoundaryRequest,
    code: NativeBoundaryDiagnostic,
) -> None:
    with pytest.raises(NativeBoundaryVerificationError) as raised:
        NativeBoundaryVerifier(
            SSAModule(), boundary_requests=(boundary,)
        ).verify()

    assert raised.value.code is code


def test_nonthrowing_raw_c_call_has_no_event_transport() -> None:
    request = _request(kind="raw-c", may_throw=False, event_transport=False)
    assert NativeBoundaryVerifier(
        SSAModule(), boundary_requests=(request,)
    ).verify() == SSAModule()


def test_runtime_and_interface_abi_mismatch_reject() -> None:
    with pytest.raises(NativeBoundaryVerificationError, match="NBV-005"):
        NativeBoundaryVerifier(
            SSAModule(), exception_runtime_abi_version=999
        ).verify()
    with pytest.raises(NativeBoundaryVerificationError, match="NBV-011"):
        NativeBoundaryVerifier(SSAModule(), interface_abi_version=999).verify()


def test_every_runtime_helper_family_has_one_failure_mode_and_visibility() -> None:
    inventories = (RUNTIME_HELPER_INVENTORY, RUNTIME_HELPER_FAMILY_INVENTORY)
    assert all(inventory for inventory in inventories)
    for inventory in inventories:
        for name, spec in inventory.items():
            assert spec.semantic_name == name
            assert isinstance(spec.exception_behavior, RuntimeExceptionBehavior)
            assert isinstance(spec.visibility, RuntimeVisibility)
            assert spec.ownership
            if spec.exception_behavior is RuntimeExceptionBehavior.MAY_THROW_AETHER_EXCEPTION:
                assert spec.event_transport


def test_unclassified_runtime_helper_rejects_fail_closed() -> None:
    module = SSAModule(
        [
            SSAFunction(
                "probe",
                [],
                IntType(),
                [
                    SSABasicBlock(
                        "entry",
                        [SSACall("foreign_helper", builtin="foreign_helper")],
                    )
                ],
            )
        ]
    )

    with pytest.raises(NativeBoundaryVerificationError) as raised:
        NativeBoundaryVerifier(module).verify()

    assert raised.value.code is NativeBoundaryDiagnostic.RUNTIME_HELPER_CLASSIFICATION


def test_panic_helpers_never_use_event_transport() -> None:
    specs = [
        *RUNTIME_HELPER_INVENTORY.values(),
        *RUNTIME_HELPER_FAMILY_INVENTORY.values(),
    ]
    assert any(
        spec.exception_behavior is RuntimeExceptionBehavior.MAY_PANIC
        for spec in specs
    )
    assert all(
        not spec.event_transport
        for spec in specs
        if spec.exception_behavior is RuntimeExceptionBehavior.MAY_PANIC
    )


def test_descriptor_mismatch_is_a_native_verifier_diagnostic() -> None:
    module = _lower()
    block = next(
        block
        for function in module.functions
        for block in function.blocks
        if any(isinstance(item, SSAPackException) for item in block.instructions)
    )
    index = next(
        index
        for index, item in enumerate(block.instructions)
        if isinstance(item, SSAPackException)
    )
    pack = block.instructions[index]
    assert isinstance(pack, SSAPackException)
    block.instructions[index] = replace(pack, dynamic_type="OtherError")

    with pytest.raises(NativeBoundaryVerificationError) as raised:
        NativeBoundaryVerifier(module).verify()

    assert raised.value.code is NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH


def test_backend_runs_boundary_verifier_before_printer() -> None:
    module = _lower()
    block = next(
        block
        for function in module.functions
        for block in function.blocks
        if any(isinstance(item, SSAPackException) for item in block.instructions)
    )
    index = next(
        index
        for index, item in enumerate(block.instructions)
        if isinstance(item, SSAPackException)
    )
    pack = block.instructions[index]
    assert isinstance(pack, SSAPackException)
    block.instructions[index] = replace(pack, dynamic_type="OtherError")

    class RecordingPrinter(LLVMPrinter):
        called = False

        def print_module(self, module, *, native_entry=False):  # type: ignore[no-untyped-def]
            self.called = True
            return super().print_module(module, native_entry=native_entry)

    printer = RecordingPrinter()
    with pytest.raises(NativeBoundaryVerificationError, match="NBV-006"):
        LLVMBackend(printer).emit(module)
    assert not printer.called


def test_backend_reports_external_invoke_before_generic_undefined_call() -> None:
    event = SSAValue("event", ExceptionEventType())
    module = SSAModule(
        [
            SSAFunction(
                "probe",
                [],
                IntType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAInvoke(
                                "foreign_throwing_function",
                                (),
                                None,
                                event,
                                "normal",
                                "exceptional",
                                (),
                                (event,),
                            )
                        ],
                    )
                ],
                may_throw=True,
            )
        ]
    )

    with pytest.raises(NativeBoundaryVerificationError) as raised:
        LLVMBackend().emit(module)

    assert raised.value.code is NativeBoundaryDiagnostic.UNSUPPORTED_EXTERNAL_MAY_THROW


def test_unhandled_event_is_consumed_by_private_root_reporter() -> None:
    llvm = LLVMBackend().emit(_lower())

    assert "define private void @__ae_exception_root_terminate_v1(ptr %event) noreturn" in llvm
    assert "call void @__ae_exception_destroy_v1(ptr %event)" in llvm
    assert "call void @__ae_exception_root_terminate_v1" in llvm
    assert "__ae_exception_out" not in llvm.split("define i32 @main", 1)[1].split("{", 1)[0]


def test_native_boundary_failure_has_specific_public_ice_diagnostic() -> None:
    error = NativeBoundaryVerificationError(
        NativeBoundaryDiagnostic.THROWING_CALLBACK,
        "callback may throw",
    )
    diagnostic = diagnostic_from_exception(error)

    assert diagnostic.category is DiagnosticCategory.INTERNAL_COMPILER_ERROR
    assert diagnostic.code == "ICE-NATIVE-BOUNDARY-001"
    assert diagnostic.phase == "native boundary verification"
    assert diagnostic.note is not None and "NBV-002" in diagnostic.note
