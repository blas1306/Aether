from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMRunner
from aether.class_value import class_debug_counters, reset_class_debug_counters
from aether.errors import AetherTypeError
from aether.ir import (
    ClassRefType,
    IRCopyInit,
    IRInterpreter,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IntType,
    MethodResultType,
    VoidType,
)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSACall
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


METHOD_SOURCE = """
class Counter {
    public int value;

    constructor(int initial) {
        value = initial;
    }

    public void empty() {}

    public void increment() {
        value = value + 1;
    }

    public int add(int left, int right) {
        this.increment();
        return value + left + right;
    }

    public int factorial(int n) {
        if (n <= 1) {
            return 1;
        }
        return n * factorial(n - 1);
    }

    public boolean isEven(int n) {
        if (n == 0) {
            return true;
        }
        return isOdd(n - 1);
    }

    public boolean isOdd(int n) {
        if (n == 0) {
            return false;
        }
        return isEven(n - 1);
    }

    public Counter identity() {
        return this;
    }

    public void incrementOther(Counter other) {
        other.increment();
    }

    public int get() {
        return this.value;
    }
}

class Holder {
    public Counter child;

    constructor(Counter child) {
        this.child = child;
    }

    public void incrementChild() {
        this.child.increment();
    }

    public int readChild() {
        return this.child.get();
    }
}

int main() {
    Counter a = Counter(0);
    Counter b = a;
    b.empty();
    println(b.add(2, 3));
    println(a.value);
    println(a.factorial(5));
    println(a.isEven(8));
    println(a.identity().get());
    println(Counter(9).get());

    Holder holder = Holder(a);
    holder.incrementChild();
    a.incrementOther(b);
    println(holder.readChild());
    return 0;
}
"""

EXPECTED_OUTPUT = "6\n1\n120\ntrue\n1\n9\n3\n"


def _typed(source: str = METHOD_SOURCE):
    return prepare_typed_program(source, TypeChecker())


def test_class_methods_use_direct_borrowed_receiver_abi_and_round_trip_dto() -> None:
    module = IRBackend().lower_verified(_typed())
    methods = {
        function.name: function
        for function in module.functions
        if function.name.startswith(("Counter.", "Holder."))
        and not function.name.endswith(".__ctor")
    }

    increment = methods["Counter.increment"]
    add = methods["Counter.add"]
    identity = methods["Counter.identity"]
    assert increment.parameters[0].type == ClassRefType("Counter")
    assert increment.return_type == VoidType()
    assert add.return_type == IntType()
    assert identity.return_type == ClassRefType("Counter")
    assert all(
        not isinstance(function.return_type, MethodResultType)
        for function in methods.values()
    )

    method_instructions = [
        instruction
        for function in methods.values()
        for block in function.blocks
        for instruction in block.instructions
    ]
    assert not any(
        isinstance(instruction, IRCopyInit)
        and instruction.destination.name == "this"
        for instruction in method_instructions
    )
    assert not any(
        isinstance(
            instruction,
            (IRMethodResultNew, IRMethodResultReceiver, IRMethodResultValue),
        )
        for instruction in method_instructions
    )
    assert ir_module_from_dto(ir_module_to_dto(module)) == module


def test_class_methods_match_ast_ir_ssa_optimized_and_native_execution() -> None:
    assert run_aether(METHOD_SOURCE).output == EXPECTED_OUTPUT

    typed = _typed()
    module = IRBackend().lower_verified(typed)
    interpreter = IRInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == EXPECTED_OUTPUT

    optimized = SSAOptimizerPipeline(verify_after_each=True).run(
        lower_to_verified_ssa(module)
    )
    assert any(
        isinstance(instruction, SSACall)
        and instruction.function == "Counter.increment"
        for function in optimized.functions
        for block in function.blocks
        for instruction in block.instructions
    )

    if shutil.which("clang") is not None:
        stdout = StringIO()
        stderr = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
        assert stdout.getvalue() == EXPECTED_OUTPUT
        assert stderr.getvalue() == ""


def test_class_this_cannot_be_reassigned() -> None:
    with pytest.raises(AetherTypeError, match="Cannot assign to constant 'this'"):
        _typed(
            """
class Counter {
    int value;
    public void invalid(Counter other) {
        this = other;
    }
}
int main() { return 0; }
"""
        )


def test_imported_class_methods_keep_canonical_native_identity(tmp_path: Path) -> None:
    (tmp_path / "Counters.ae").write_text(
        """
package Counters;
public class Counter {
    int value;
    public constructor(int initial) { value = initial; }
    public void increment() { value = value + 1; }
    public int get() { return value; }
}
""",
        encoding="utf-8",
    )
    source = """
from Counters import Counter;
int main() {
    Counter counter = Counter(4);
    counter.increment();
    return counter.get();
}
"""
    typed = prepare_typed_program(source, TypeChecker(source_root=tmp_path))
    module = IRBackend().lower_verified(typed)

    assert IRInterpreter(module).call("main") == 5
    method_names = {function.name for function in module.functions}
    assert any(name.endswith(".increment") for name in method_names)
    assert any(name.endswith(".get") for name in method_names)


def test_class_method_owned_returns_and_temporary_receivers_release_once() -> None:
    typed = _typed(
        """
class Node {
    public int value;
    constructor(int value) { this.value = value; }
    public Node identity() { return this; }
    public Node make(int value) { return Node(value); }
    public int get() { return value; }
}
int main() {
    Node root = Node(1);
    root.identity();
    println(root.identity().get());
    println(root.make(2).get());
    return 0;
}
"""
    )
    reset_class_debug_counters()
    interpreter = IRInterpreter(
        expand_lifecycle(IRBackend().lower_verified(typed))
    )

    assert interpreter.call("main") == 0
    assert interpreter.output == "1\n2\n"
    counters = class_debug_counters()
    assert counters.objects_allocated == 2
    assert counters.objects_freed == 2
    assert counters.fields_destroyed == 2


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("optimization", ["-O0", "-O1", "-O2"])
def test_class_methods_survive_clang_optimization_profiles(
    tmp_path: Path,
    optimization: str,
) -> None:
    ssa = SSAOptimizerPipeline(verify_after_each=True).run(
        lower_to_verified_ssa(_typed())
    )
    llvm_path = tmp_path / "class_methods.ll"
    executable = tmp_path / "class_methods"
    llvm_path.write_text(LLVMBackend().emit(ssa, native_entry=True), encoding="utf-8")
    subprocess.run(
        [
            shutil.which("clang") or "clang",
            optimization,
            str(llvm_path),
            "-o",
            str(executable),
        ],
        check=True,
    )
    completed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout == EXPECTED_OUTPUT
    assert completed.stderr == ""
