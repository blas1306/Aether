from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBuilder
from aether.interface_abi import dispatch_thunk_symbol, witness_symbol
from aether.ir import (
    IRInterfaceCall,
    IRVerificationError,
    IRVerifier,
    RustVerifierAcceptedOutcome,
    build_canonical_rust_verifier_request,
)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.rust_verifier import SubprocessRustVerifierClient
from aether.pipeline import IRBackend, prepare_typed_program
from aether.typechecker import TypeChecker


SOURCE = """
interface CounterLike {
    void inc();
    int get();
}

class Counter implements CounterLike {
    int value;

    constructor(int initial) {
        value = initial;
    }

    public void inc() {
        value = value + 1;
    }

    public int get() {
        return value;
    }
}

class Fixed implements CounterLike {
    int value;

    constructor(int initial) {
        value = initial;
    }

    public void inc() {
        value = value + 10;
    }

    public int get() {
        return value;
    }
}

CounterLike identity(CounterLike value) {
    return value;
}

int nested(CounterLike value) {
    return identity(value).get();
}

int main() {
    Counter counter = Counter(0);
    CounterLike first = identity(counter);
    first.inc();
    println(counter.get());
    println(nested(first));

    Fixed fixed = Fixed(5);
    CounterLike second = fixed;
    second.inc();
    println(second.get());

    Array<CounterLike> values = {first, second};
    println(values[0].get());
    println(values[1].get());
    return 0;
}
"""


def _typed(source: str = SOURCE, *, source_root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=source_root))


def _interface_calls(module) -> list[IRInterfaceCall]:
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRInterfaceCall)
    ]


def test_dispatch_round_trips_and_is_verified_by_python_and_rust(
    rust_verifier_executable: Path,
) -> None:
    module = IRBackend().lower_verified(_typed())
    calls = _interface_calls(module)

    assert calls
    assert all(call.must_preserve for call in calls)
    assert {
        (call.slot.index, call.slot.method_id) for call in calls
    } == {
        (0, "CounterLike.inc"),
        (1, "CounterLike.get"),
    }
    assert ir_module_from_dto(ir_module_to_dto(module)) == module
    assert IRVerifier(module).verify() == module
    invocation = SubprocessRustVerifierClient(
        executable=rust_verifier_executable
    ).verify(build_canonical_rust_verifier_request(module))
    assert isinstance(invocation.outcome, RustVerifierAcceptedOutcome)


def test_witness_slots_use_stable_native_thunks_and_calls_are_indirect() -> None:
    llvm = LLVMBuilder().emit_llvm(_typed())
    first_thunk = dispatch_thunk_symbol(
        "CounterLike", "Counter", 0, "CounterLike.inc"
    )
    second_thunk = dispatch_thunk_symbol(
        "CounterLike", "Fixed", 1, "CounterLike.get"
    )

    assert f"ptr @{first_thunk}" in llvm
    assert f"define private void @{first_thunk}(ptr %carrier)" in llvm
    assert f"ptr @{second_thunk}" in llvm
    assert "getelementptr %AetherWitnessSlot" in llvm
    assert "load ptr, ptr %interface.call.thunk.ptr" in llvm
    assert "call void %interface.call.thunk" in llvm
    assert "call i32 %interface.call.thunk" in llvm
    assert llvm.index(f"@{witness_symbol('CounterLike', 'Counter')}") < llvm.index(
        f"@{witness_symbol('CounterLike', 'Fixed')}"
    )


def test_python_verifier_rejects_a_mismatched_thunk_signature() -> None:
    module = IRBackend().lower_verified(_typed())
    target = next(
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if instruction.__class__.__name__ == "IRInterfaceConstruct"
    )
    invalid_slot = replace(
        target.witness.method_slots[0],
        receiver_ownership="owned",
    )
    invalid_witness = replace(
        target.witness,
        method_slots=(invalid_slot, *target.witness.method_slots[1:]),
    )
    invalid_construct = replace(target, witness=invalid_witness)
    invalid_functions = []
    for function in module.functions:
        invalid_blocks = []
        for block in function.blocks:
            invalid_blocks.append(
                replace(
                    block,
                    instructions=[
                        invalid_construct if item is target else item
                        for item in block.instructions
                    ],
                )
            )
        invalid_functions.append(replace(function, blocks=invalid_blocks))

    with pytest.raises(IRVerificationError, match="erased ABI or thunk signature"):
        IRVerifier(replace(module, functions=invalid_functions)).verify()


@pytest.mark.parametrize("optimization", ["0", "1", "2"])
def test_native_dispatch_preserves_alias_visible_mutation_and_collections(
    tmp_path: Path,
    optimization: str,
) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")
    llvm_path = tmp_path / f"dispatch-o{optimization}.ll"
    executable = tmp_path / f"dispatch-o{optimization}"
    llvm_path.write_text(LLVMBuilder().emit_llvm(_typed()), encoding="utf-8")
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

    assert completed.stdout == "1\n1\n15\n1\n15\n"


def test_imported_class_implementation_dispatches_through_its_witness(
    tmp_path: Path,
) -> None:
    (tmp_path / "Shapes.ae").write_text(
        """
package Shapes;

public interface Shape {
    int area();
}

public class Square implements Shape {
    int side;

    public constructor(int value) {
        side = value;
    }

    public int area() {
        return side * side;
    }
}
""",
        encoding="utf-8",
    )
    source = """
from Shapes import Shape;
from Shapes import Square;

int main() {
    Square square = Square(4);
    Shape shape = square;
    println(shape.area());
    return 0;
}
"""
    llvm = LLVMBuilder().emit_llvm(_typed(source, source_root=tmp_path))

    assert "call i32 %interface.call.thunk" in llvm
    assert "define private i32 @__ae_interface_thunk_" in llvm


def test_mutually_recursive_interface_dispatch_executes_natively(
    tmp_path: Path,
) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")
    source = """
interface Recur {
    int step(Recur other, int n);
}

class Even implements Recur {
    public int step(Recur other, int n) {
        if (n == 0) {
            return 0;
        }
        return other.step(this, n - 1);
    }
}

class Odd implements Recur {
    public int step(Recur other, int n) {
        if (n == 0) {
            return 1;
        }
        return other.step(this, n - 1);
    }
}

int main() {
    Even even = Even();
    Odd odd = Odd();
    Recur first = even;
    Recur second = odd;
    println(first.step(second, 4));
    return 0;
}
"""
    llvm_path = tmp_path / "recursive-dispatch.ll"
    executable = tmp_path / "recursive-dispatch"
    llvm_path.write_text(LLVMBuilder().emit_llvm(_typed(source)), encoding="utf-8")
    subprocess.run(
        [clang, "-O2", str(llvm_path), "-o", str(executable)],
        check=True,
        capture_output=True,
    )
    completed = subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == "0\n"
