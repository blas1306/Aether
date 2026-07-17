from __future__ import annotations

import pytest

from aether import ast
from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.runner import run_aether


def _parse(source: str) -> ast.Program:
    return Parser(lex(source)).parse()


def test_parser_builds_throw_and_try_catch_nodes() -> None:
    program = _parse('try { throw "boom"; } catch (e) { println(e.message); }')

    statement = program.statements[0]
    assert isinstance(statement, ast.TryCatchStatement)
    assert statement.catch_name == "e"
    assert isinstance(statement.try_body[0], ast.ThrowStatement)


def test_uncaught_throw_string_is_runtime_error_with_message() -> None:
    with pytest.raises(AetherRuntimeError) as raised:
        run_aether('throw "boom";')

    assert raised.value.message == "boom"
    assert raised.value.kind == "Exception"


def test_try_catch_prints_exception_message() -> None:
    result = run_aether('try { throw "boom"; } catch (e) { println(e.message); }')

    assert result.output == "boom\n"


def test_catch_does_not_run_without_exception() -> None:
    result = run_aether('try { println("ok"); } catch (e) { println("caught"); }')

    assert result.output == "ok\n"


def test_catch_allows_program_to_continue() -> None:
    result = run_aether('try { throw "boom"; } catch (e) { println(e.message); } println("after");')

    assert result.output == "boom\nafter\n"


def test_throw_inside_catch_propagates() -> None:
    with pytest.raises(AetherRuntimeError) as raised:
        run_aether('try { throw "first"; } catch (e) { throw "second"; }')

    assert raised.value.message == "second"


def test_throw_inside_function_can_be_caught_outside() -> None:
    result = run_aether(
        """
void risky() {
    throw "from function";
}

try {
    risky();
} catch (e) {
    println(e.message);
}
"""
    )

    assert result.output == "from function\n"


def test_catch_variable_does_not_escape_catch_scope() -> None:
    with pytest.raises(AetherTypeError, match="Undefined variable 'e'"):
        run_aether('try { throw "boom"; } catch (e) { println(e.message); } println(e.message);')


def test_return_inside_try_works() -> None:
    result = run_aether(
        """
int f() {
    try {
        return 7;
    } catch (e) {
        return 0;
    }
}

println(f());
"""
    )

    assert result.output == "7\n"


def test_return_inside_catch_works() -> None:
    result = run_aether(
        """
int f() {
    try {
        if (true) {
            throw "boom";
        }
        return 0;
    } catch (e) {
        return 9;
    }
}

println(f());
"""
    )

    assert result.output == "9\n"


def test_break_and_continue_inside_try_still_work_in_loops() -> None:
    result = run_aether(
        """
for (i in 1:5) {
    try {
        if (i == 2) {
            continue;
        }
        if (i == 4) {
            break;
        }
        println(i);
    } catch (e) {
        println("caught");
    }
}
"""
    )

    assert result.output == "1\n3\n"


def test_throw_rejects_non_string_non_exception_values() -> None:
    with pytest.raises(AetherTypeError, match="throw expects string or Exception, got 'int'"):
        run_aether("throw 123;")


def test_exception_constructor_can_be_thrown_and_caught() -> None:
    result = run_aether('try { throw Exception("constructed"); } catch (e) { println(e.message); }')

    assert result.output == "constructed\n"


def test_exception_message_field_access_works() -> None:
    result = run_aether('Exception e = Exception("field"); println(e.message);')

    assert result.output == "field\n"


def test_try_without_catch_is_syntax_error() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected 'catch' after try block"):
        _parse("try { }")


def test_catch_without_identifier_is_syntax_error() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected catch variable name"):
        _parse("try { } catch () { }")


def test_throw_without_expression_is_syntax_error() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected expression after 'throw'"):
        _parse("throw;")


def test_try_catch_requires_both_return_paths_for_non_void_function() -> None:
    with pytest.raises(AetherTypeError, match="may not return a value on all paths"):
        run_aether(
            """
int f() {
    try {
        return 1;
    } catch (e) {
        println(e.message);
    }
}
"""
        )
