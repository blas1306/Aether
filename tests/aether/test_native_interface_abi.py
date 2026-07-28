from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from aether.backend.llvm import LLVMBuilder
from aether.capabilities import BackendCapabilityError
from aether.interface_abi import interface_type_symbol, witness_symbol
from aether.ir import (
    ClassRefType,
    IRInterfaceConstruct,
    IRVerificationError,
    IRVerifier,
    InterfaceType,
    RustVerifierAcceptedOutcome,
    build_canonical_rust_verifier_request,
)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.ir.model import IRCall
from aether.ir.optimizer import OptimizerPipeline
from aether.ir.rust_verifier import SubprocessRustVerifierClient
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.ssa import SSAInterfaceConstruct, SSAPhi
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


SOURCE = """
interface Readable {
    int zeta(int value);
    int alpha();
}

class Box implements Readable {
    public int zeta(int value) { return value; }
    public int alpha() { return 1; }
}

Readable choose(boolean flag, Box first, Box second) {
    Readable result = first;
    if (flag) {
        result = second;
    }
    return result;
}

Readable identity(Readable value) {
    return value;
}

int main() {
    Box box = Box();
    Readable value = box;
    Readable? maybe = value;
    Array<Readable> array = {value};
    List<Readable> list = {value};
    return 0;
}
"""


def _typed(source: str = SOURCE):
    return prepare_typed_program(source, TypeChecker())


def _constructs(module) -> list[IRInterfaceConstruct]:
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRInterfaceConstruct)
    ]


def test_interface_abi_construction_metadata_and_stable_mangling() -> None:
    first = IRBackend().lower_verified(_typed())
    second = IRBackend().lower_verified(_typed())
    constructs = _constructs(first)

    assert constructs
    assert all(item.must_preserve for item in constructs)
    assert all(isinstance(item.result.type, InterfaceType) for item in constructs)
    assert all(isinstance(item.carrier.type, ClassRefType) for item in constructs)
    witness = constructs[0].witness
    assert witness.symbol == witness_symbol("Readable", "Box")
    assert witness == _constructs(second)[0].witness
    assert witness.interface_id == "Readable"
    assert witness.concrete_type_id == "Box"
    assert witness.carrier_kind == "class"
    assert witness.abi_version == 1
    assert [(slot.index, slot.method_id) for slot in witness.method_slots] == [
        (0, "Readable.zeta"),
        (1, "Readable.alpha"),
    ]
    assert witness_symbol("Readable", "Box") != witness_symbol("Readable", "Other")
    assert interface_type_symbol("Readable") == interface_type_symbol("Readable")


def test_interface_values_round_trip_through_dto_ssa_phis_and_optimizers() -> None:
    ir = IRBackend().lower_verified(_typed())
    assert ir_module_from_dto(ir_module_to_dto(ir)) == ir

    optimized_ir = OptimizerPipeline().run(ir)
    assert [item.witness for item in _constructs(optimized_ir)]

    ssa = lower_to_verified_ssa(ir)
    witnesses = [
        instruction.witness
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAInterfaceConstruct)
    ]
    assert witnesses
    assert any(
        isinstance(instruction, SSAPhi)
        and isinstance(instruction.result.type, InterfaceType)
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
    )

    optimized_ssa = SSAOptimizerPipeline().run(ssa)
    assert any(
        isinstance(instruction, SSAInterfaceConstruct)
        and instruction.witness == witnesses[0]
        for function in optimized_ssa.functions
        for block in function.blocks
        for instruction in block.instructions
    )


def test_interface_ownership_retains_and_releases_only_interface_values() -> None:
    expanded = expand_lifecycle(IRBackend().lower_verified(_typed()))
    lifecycle_calls = [
        instruction
        for function in expanded.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall)
        and instruction.function in {"__aether_retain", "__aether_release"}
    ]

    assert lifecycle_calls
    assert any(
        isinstance(call.arguments[0].type, InterfaceType) for call in lifecycle_calls
    )
    assert not any(
        "witness" in argument.name
        for call in lifecycle_calls
        for argument in call.arguments
    )


def test_llvm_uses_two_pointer_values_and_immutable_placeholder_tables() -> None:
    llvm = LLVMBuilder().emit_llvm(_typed())
    symbol = witness_symbol("Readable", "Box")

    assert f"{interface_type_symbol('Readable')} = type {{ ptr, ptr }}" in llvm
    assert "%AetherWitnessHeader = type { ptr, ptr, i32, i32, ptr, ptr }" in llvm
    assert "%AetherWitnessSlot = type { i32, ptr, ptr }" in llvm
    assert f"@{symbol} = private constant" in llvm
    assert "Readable.zeta\\00" in llvm
    assert "Readable.alpha\\00" in llvm
    assert llvm.index("Readable.zeta\\00") < llvm.index("Readable.alpha\\00")
    assert "ptr null" in llvm
    assert "insertvalue" in llvm
    assert "extractvalue" in llvm


def test_witness_globals_are_sorted_independently_of_construction_order() -> None:
    typed = _typed(
        """
interface Zeta { int z(); }
interface Alpha { int a(); }
class Zed implements Zeta { public int z() { return 1; } }
class Able implements Alpha { public int a() { return 2; } }
int main() {
    Zed zed = Zed();
    Zeta zeta = zed;
    Able able = Able();
    Alpha alpha = able;
    return 0;
}
"""
    )
    llvm = LLVMBuilder().emit_llvm(typed)
    alpha = f"@{witness_symbol('Alpha', 'Able')} = private constant"
    zeta = f"@{witness_symbol('Zeta', 'Zed')} = private constant"

    assert llvm.index(alpha) < llvm.index(zeta)


def test_python_and_rust_verifiers_accept_interface_construction(
    rust_verifier_executable: Path,
) -> None:
    module = IRBackend().lower_verified(_typed())
    assert IRVerifier(module).verify() == module

    invocation = SubprocessRustVerifierClient(
        executable=rust_verifier_executable
    ).verify(build_canonical_rust_verifier_request(module))
    assert isinstance(invocation.outcome, RustVerifierAcceptedOutcome)


def test_python_verifier_rejects_noncanonical_witness_identity() -> None:
    module = IRBackend().lower_verified(_typed())
    target = _constructs(module)[0]
    invalid = replace(
        target,
        witness=replace(target.witness, symbol="unstable-witness-name"),
    )
    function = next(
        function
        for function in module.functions
        if any(target in block.instructions for block in function.blocks)
    )
    block = next(block for block in function.blocks if target in block.instructions)
    invalid_block = replace(
        block,
        instructions=[
            invalid if instruction is target else instruction
            for instruction in block.instructions
        ],
    )
    invalid_function = replace(
        function,
        blocks=[
            invalid_block if candidate is block else candidate
            for candidate in function.blocks
        ],
    )
    invalid_module = replace(
        module,
        functions=[
            invalid_function if candidate is function else candidate
            for candidate in module.functions
        ],
    )

    with pytest.raises(IRVerificationError, match="witness identity"):
        IRVerifier(invalid_module).verify()


def test_struct_boxing_still_fails_explicitly_as_phase_5_4c() -> None:
    source = (
        "interface I { int get(); } "
        "struct S implements I { int get() { return 1; } } "
        "int main() { S s = S(); I i = s; return 0; }"
    )
    with pytest.raises(BackendCapabilityError, match="Phase 5.4C"):
        LLVMBuilder().emit_llvm(_typed(source))
