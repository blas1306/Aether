from __future__ import annotations

import pytest

from aether import ast
from aether.errors import AetherSyntaxError, AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.runner import run_aether


def _parse(source: str) -> ast.Program:
    return Parser(lex(source)).parse()


def test_parse_void_function_return_type() -> None:
    program = _parse("void emit(int x) { println(x); }")

    declaration = program.statements[0]
    assert isinstance(declaration, ast.FunctionDeclaration)
    assert declaration.return_type == "void"


def test_void_function_can_end_without_returning_value() -> None:
    result = run_aether(
        """
void emit(int x) {
    println(x);
}
emit(3);
"""
    )

    assert result.output == "3\n"


def test_void_function_accepts_bare_return() -> None:
    result = run_aether(
        """
void maybeLog(int x) {
    if x > 0 {
        println("positive");
        return;
    }
    println("other");
}
maybeLog(1);
maybeLog(0);
"""
    )

    assert result.output == "positive\nother\n"


def test_void_function_does_not_require_return_on_all_paths() -> None:
    result = run_aether(
        """
void maybePrint(boolean flag) {
    if flag {
        println("yes");
    }
}
maybePrint(true);
maybePrint(false);
"""
    )

    assert result.output == "yes\n"


def test_void_function_cannot_return_value() -> None:
    with pytest.raises(AetherTypeError, match="Void function f cannot return a value"):
        run_aether("void f() { return 1; }")


def test_non_void_function_cannot_use_bare_return() -> None:
    with pytest.raises(AetherTypeError, match="Function f declares return type int but returned void"):
        run_aether("int f() { return; }")


def test_void_call_can_only_be_used_as_statement() -> None:
    with pytest.raises(AetherTypeError, match="Cannot use void value in assignment"):
        run_aether("void f() { } x = f();")


def test_void_call_cannot_be_used_as_argument() -> None:
    with pytest.raises(AetherTypeError, match=r"Cannot use void value in argument to println\(\.\.\.\)"):
        run_aether("void f() { } println(f());")


def test_side_effect_builtins_return_void() -> None:
    with pytest.raises(AetherTypeError, match="Cannot use void value in assignment"):
        run_aether('x = println("hi");')


def test_void_is_not_valid_variable_or_parameter_type() -> None:
    with pytest.raises(AetherSyntaxError, match="'void' is only valid as a function return type"):
        _parse("void x = 1;")

    with pytest.raises(AetherSyntaxError, match="'void' is only valid as a function return type"):
        _parse("int f(void x) { return 1; }")


def test_void_is_not_valid_tuple_or_array_return_element() -> None:
    with pytest.raises(AetherSyntaxError, match="'void' is only valid as a function return type"):
        _parse("(void, int) f() { return (1, 2); }")

    with pytest.raises(AetherSyntaxError, match="'void' cannot be used as an array type"):
        _parse("void[] f() { return; }")
