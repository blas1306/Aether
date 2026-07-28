from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBuilder
from aether.interface_abi import ERASED_BOX_HEADER_SIZE
from aether.ir import (
    IRInterfaceConstruct,
    IRVerificationError,
    IRVerifier,
    RustVerifierAcceptedOutcome,
    build_canonical_rust_verifier_request,
)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.optimizer import OptimizerPipeline
from aether.ir.rust_verifier import SubprocessRustVerifierClient
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


SOURCE = """
interface Value {
    void set(int value);
    int get();
}

struct Point : Value {
    int x;

    constructor(int x) {
        this.x = x;
    }

    void set(int value) {
        this.x = value;
    }

    int get() {
        return x;
    }
}

interface Named {
    string text();
}

struct Node : Named {
    string name;
    Array<int> data;
    int? next;

    constructor(string name, Array<int> data, int? next) {
        this.name = name;
        this.data = data;
        this.next = next;
    }

    string text() {
        return name;
    }
}

int main() {
    Point point = Point(1);
    Value first = point;
    Value second = first;
    first.set(9);
    println(first.get());
    println(second.get());

    Array<Value> array = {first};
    List<Value> list = {second};
    Value fromArray = array[0];
    Value fromList = list[0];
    fromArray.set(20);
    fromList.set(30);
    println(fromArray.get());
    println(array[0].get());
    println(fromList.get());
    println(list[0].get());

    Value? maybe = first;

    Node node = Node("owned", {1, 2, 3}, null);
    Named named = node;
    Named copied = named;
    println(named.text());
    println(copied.text());
    return 0;
}
"""


def _typed():
    return prepare_typed_program(SOURCE, TypeChecker())


def _constructs(module) -> list[IRInterfaceConstruct]:
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRInterfaceConstruct)
    ]


def test_box_layout_dto_verifiers_and_optimizers_preserve_metadata() -> None:
    module = IRBackend().lower_verified(_typed())
    constructs = _constructs(module)
    assert constructs
    for construct in constructs:
        layout = construct.witness.box_layout
        assert construct.witness.carrier_kind == "box"
        assert layout is not None
        assert layout.payload_size >= 0
        assert layout.payload_alignment in {1, 2, 4, 8}
        assert layout.payload_offset >= ERASED_BOX_HEADER_SIZE
        assert layout.payload_offset % layout.payload_alignment == 0
        assert layout.ownership == "owned_value"

    assert ir_module_from_dto(ir_module_to_dto(module)) == module
    assert _constructs(OptimizerPipeline().run(module))
    ssa = lower_to_verified_ssa(module)
    assert SSAOptimizerPipeline().run(ssa).functions


def test_python_verifier_rejects_tampered_erased_payload_layout() -> None:
    module = IRBackend().lower_verified(_typed())
    target = _constructs(module)[0]
    assert target.witness.box_layout is not None
    invalid = replace(
        target,
        witness=replace(
            target.witness,
            box_layout=replace(
                target.witness.box_layout,
                payload_offset=target.witness.box_layout.payload_offset + 1,
            ),
        ),
    )
    functions = []
    for function in module.functions:
        blocks = [
            replace(
                block,
                instructions=[
                    invalid if instruction is target else instruction
                    for instruction in block.instructions
                ],
            )
            for block in function.blocks
        ]
        functions.append(replace(function, blocks=blocks))
    with pytest.raises(IRVerificationError, match="payload layout"):
        IRVerifier(replace(module, functions=functions)).verify()


def test_rust_verifier_accepts_struct_box_layout(
    rust_verifier_executable: Path,
) -> None:
    module = IRBackend().lower_verified(_typed())
    invocation = SubprocessRustVerifierClient(
        executable=rust_verifier_executable
    ).verify(build_canonical_rust_verifier_request(module))
    assert isinstance(invocation.outcome, RustVerifierAcceptedOutcome)


@pytest.mark.parametrize("optimization", ["0", "1", "2"])
def test_struct_backed_interfaces_execute_with_value_semantics(
    tmp_path: Path,
    optimization: str,
) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")
    llvm = LLVMBuilder().emit_llvm(_typed())
    assert "%AetherWitnessHeader = type { ptr, ptr, i32, i32, ptr, ptr }" in llvm
    assert "%AetherBox." in llvm
    assert ".copy_owned(ptr %carrier)" in llvm
    assert ".drop_owned(ptr %carrier)" in llvm
    assert "getelementptr %AetherWitnessSlot" in llvm

    llvm_path = tmp_path / f"struct-interface-o{optimization}.ll"
    executable = tmp_path / f"struct-interface-o{optimization}"
    llvm_path.write_text(llvm, encoding="utf-8")
    subprocess.run(
        [clang, f"-O{optimization}", str(llvm_path), "-o", str(executable)],
        check=True,
        capture_output=True,
    )
    completed = subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == "9\n1\n20\n9\n30\n1\nowned\nowned\n"
