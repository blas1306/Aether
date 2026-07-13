from __future__ import annotations

import pytest

from aether.backend.llvm import LLVMBuilder
from aether.errors import AetherTypeError
from aether.ir import IRCall
from aether.ir.lowering import IRLowerer
from aether.lexer import lex
from aether.parser import Parser
from aether.pipeline import prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


def _check(source: str) -> TypeChecker:
    checker = TypeChecker()
    checker.check(Parser(lex(source)).parse())
    return checker


def test_function_can_be_called_before_its_declaration() -> None:
    result = run_aether(
        """
int main() {
    println(add(2, 3));
}

int add(int a, int b) {
    return a + b;
}
"""
    )

    assert result.output == "5\n"


def test_script_can_call_function_declared_later() -> None:
    result = run_aether(
        """
println(add(2, 3));

int add(int a, int b) {
    return a + b;
}
"""
    )

    assert result.output == "5\n"


def test_mutually_recursive_functions_are_order_independent() -> None:
    result = run_aether(
        """
boolean even(int n) {
    if n == 0 { return true; }
    return odd(n - 1);
}

boolean odd(int n) {
    if n == 0 { return false; }
    return even(n - 1);
}

println(even(10));
println(odd(10));
"""
    )

    assert result.output == "true\nfalse\n"


def test_method_can_call_method_declared_later() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    int next() { return incremented(); }
    int incremented() { return value + 1; }
}

println(Counter(4).next());
"""
    )

    assert result.output == "5\n"


def test_function_signature_and_body_can_use_struct_declared_later() -> None:
    result = run_aether(
        """
User createUser(string name) {
    return User(name);
}

struct User {
    string name;
}

println(createUser("Blas").name);
"""
    )

    assert result.output == "Blas\n"


def test_class_can_implement_interface_declared_later() -> None:
    _check(
        """
class Greeter implements Greeting {
    public string greet() { return "hello"; }
}

interface Greeting {
    string greet();
}
"""
    )


def test_function_signature_can_use_alias_declared_later() -> None:
    result = run_aether(
        """
UserId getId() { return 5; }
alias UserId = int;
println(getId());
"""
    )

    assert result.output == "5\n"


def test_local_variable_is_not_hoisted() -> None:
    with pytest.raises(AetherTypeError, match="Undefined variable 'value'"):
        _check(
            """
int main() {
    println(value);
    int value = 10;
}
"""
        )


def test_duplicate_functions_are_rejected_during_signature_collection() -> None:
    with pytest.raises(AetherTypeError, match="Function 'value' is already defined"):
        _check(
            """
int value() { return 1; }
int value() { return 2; }
"""
        )


def test_cyclic_aliases_have_a_semantic_diagnostic() -> None:
    with pytest.raises(AetherTypeError, match="Cyclic type alias involving 'A'"):
        _check(
            """
alias A = B;
alias B = A;
"""
        )


def test_recursive_struct_value_layout_is_rejected() -> None:
    with pytest.raises(
        AetherTypeError,
        match="Recursive value-type layout involving 'A' and 'B'",
    ):
        _check(
            """
struct A { B b; }
struct B { A a; }
"""
        )


def test_recursive_class_references_do_not_form_a_value_layout_cycle() -> None:
    _check(
        """
class A { B b; }
class B { A a; }
"""
    )


def test_ir_collects_later_function_signature_before_lowering_calls() -> None:
    typed = prepare_typed_program(
        """
int main() { return add(2, 3); }
int add(int a, int b) { return a + b; }
""",
        TypeChecker(),
    )

    module = IRLowerer().lower(typed.program)

    assert isinstance(module.functions[0].blocks[0].instructions[2], IRCall)
    assert module.functions[0].blocks[0].instructions[2].function == "add"


def test_llvm_emits_forward_calls_and_mutual_recursion() -> None:
    typed = prepare_typed_program(
        """
int main() { return even(8); }

int even(int n) {
    if n == 0 { return 1; }
    return odd(n - 1);
}

int odd(int n) {
    if n == 0 { return 0; }
    return even(n - 1);
}
""",
        TypeChecker(),
    )

    llvm = LLVMBuilder().emit_llvm(typed)

    assert "call i32 @even" in llvm
    assert "call i32 @odd" in llvm
    assert "define i32 @even" in llvm
    assert "define i32 @odd" in llvm
