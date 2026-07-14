from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.ir import (
    IRInterpreter,
    IRStructDefinition,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IntType,
)
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSAStructGet, SSAStructNew, SSAStructSet
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _assert_parity(declarations: str, body: str, expected: str) -> None:
    ast_source = f"{declarations}\n{body}"
    native_source = f"{declarations}\nint main() {{\n{body}\nreturn 0;\n}}"

    assert run_aether(ast_source).output == expected

    module = IRBackend().lower_verified(_typed(native_source))
    interpreter = IRInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == expected

    if shutil.which("clang") is not None:
        stdout = StringIO()
        stderr = StringIO()
        assert LLVMRunner().run(_typed(native_source), stdout=stdout, stderr=stderr) == 0
        assert stdout.getvalue() == expected
        assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Point p = Point(1, 2); println(p.x); println(p.y);",
            "1\n2\n",
        ),
        (
            "Point p = Point(1, 2); p.x = 5; println(p.x);",
            "5\n",
        ),
        (
            "Point a = Point(1, 2); Point b = a; b.x = 5; "
            "println(a.x); println(b.x);",
            "1\n5\n",
        ),
    ],
    ids=("construction-and-read", "field-write", "independent-copy"),
)
def test_struct_construction_access_write_and_copy_match_all_backends(
    body: str,
    expected: str,
) -> None:
    _assert_parity("struct Point { int x; int y; }", body, expected)


def test_struct_parameter_and_return_are_by_value_in_all_backends() -> None:
    declarations = """
struct Point { int x; int y; }

void modify(Point p) { p.x = 100; }
Point origin() { return Point(0, 0); }
"""
    body = """
Point a = Point(1, 2);
modify(a);
Point zero = origin();
println(a.x);
println(zero);
"""
    _assert_parity(declarations, body, "1\nPoint(x=0, y=0)\n")


def test_struct_methods_and_explicit_constructor_match_all_backends() -> None:
    declarations = """
struct Counter {
    int value;

    constructor(int initial) {
        value = initial;
        increment();
    }

    void increment() { this.value = this.value + 1; }
    int get() { return value; }
}
"""
    body = """
Counter a = Counter(0);
Counter b = a;
b.increment();
println(a.get());
println(b.get());
"""
    _assert_parity(declarations, body, "1\n2\n")


def test_nested_struct_equality_and_print_match_all_backends() -> None:
    declarations = """
struct Label { string text; boolean active; }
struct Item { Label label; int count; }
"""
    body = """
Item a = Item(Label("same", true), 2);
Item b = Item(Label("same", true), 2);
Item c = Item(Label("other", true), 2);
println(a == b);
println(a != c);
println(a);
"""
    _assert_parity(
        declarations,
        body,
        "true\ntrue\nItem(label=Label(text=same, active=true), count=2)\n",
    )


def test_struct_layout_and_operations_survive_ssa_optimization() -> None:
    source = """
struct Point { int x; int y; }
int main() {
    Point point = Point(1, 2);
    point.x = 9;
    println(point.x);
    return 0;
}
"""
    typed = _typed(source)
    ir = IRBackend().lower_verified(typed)

    assert ir.structs == [
        IRStructDefinition("Point", (("x", IntType()), ("y", IntType())))
    ]
    assert any(
        isinstance(instruction, (IRStructNew, IRStructGet, IRStructSet))
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
    )

    optimized = SSAOptimizerPipeline(iterative=True).run(lower_to_verified_ssa(typed))
    assert len(optimized.structs) == 1
    assert any(
        isinstance(instruction, (SSAStructNew, SSAStructGet, SSAStructSet))
        for function in optimized.functions
        for block in function.blocks
        for instruction in block.instructions
    )

    if shutil.which("clang") is not None:
        llvm = LLVMBuilder().emit_llvm(typed)
        assert llvm.count("%struct.Point = type { i32, i32 }") == 1
