from __future__ import annotations

from dataclasses import fields, is_dataclass
import re

import pytest

from aether import ast
from aether.capabilities import Capability, detect_required_capabilities
from aether.errors import AetherSyntaxError
from aether.lexer import lex
from aether.parser import Parser
from aether.pipeline import prepare_typed_program
from aether.source_formatter import format_source
from aether.tokens import TokenType
from aether.typechecker import TypeChecker


def _parse(source: str) -> ast.Program:
    return Parser(lex(source)).parse()


def _walk(node: object):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
        return
    if isinstance(node, (list, tuple)):
        for value in node:
            yield from _walk(value)
        return
    if not is_dataclass(node):
        return
    for field in fields(node):
        yield from _walk(getattr(node, field.name))


def test_lexer_reuses_exception_keywords_and_recognizes_error_as_a_type() -> None:
    tokens = lex("try catch throw Error")

    assert [token.type for token in tokens[:-1]] == [
        TokenType.TRY,
        TokenType.CATCH,
        TokenType.THROW,
        TokenType.TYPE,
    ]


def test_parser_builds_single_typed_catch() -> None:
    program = _parse(
        """
try {
    throw error;
}
catch (FileError caught) {
    handle(caught);
}
"""
    )

    statement = program.statements[0]
    assert isinstance(statement, ast.TryCatchStatement)
    assert isinstance(statement.try_body[0], ast.ThrowStatement)
    assert statement.catch_clauses == [
        ast.CatchClause(
            "FileError",
            "caught",
            [
                ast.ExpressionStatement(
                    ast.CallExpression(
                        "handle",
                        [ast.Identifier("caught", 6, 12)],
                        {},
                        6,
                        5,
                    )
                )
            ],
            5,
            1,
        )
    ]


def test_untyped_catch_sugar_records_error_as_the_declared_type() -> None:
    statement = _parse("try { work(); } catch (error) { recover(error); }").statements[0]

    assert isinstance(statement, ast.TryCatchStatement)
    assert statement.catch_clauses[0].type_name == "Error"
    assert statement.catch_clauses[0].binder_name == "error"


def test_parser_preserves_multiple_catches_in_source_order() -> None:
    statement = _parse(
        """
try {
    work();
}
catch (FileError file_error) {
    recoverFile(file_error);
}
catch (NetworkError network_error) {
    recoverNetwork(network_error);
}
catch (Error error) {
    report(error);
}
"""
    ).statements[0]

    assert isinstance(statement, ast.TryCatchStatement)
    assert [clause.type_name for clause in statement.catch_clauses] == [
        "FileError",
        "NetworkError",
        "Error",
    ]
    assert [clause.binder_name for clause in statement.catch_clauses] == [
        "file_error",
        "network_error",
        "error",
    ]


def test_nested_try_catch_retains_lexical_structure() -> None:
    outer = _parse(
        """
try {
    try {
        throw inner;
    } catch (InnerError error) {
        throw;
    }
} catch (OuterError error) {
    throw error;
}
"""
    ).statements[0]

    assert isinstance(outer, ast.TryCatchStatement)
    inner = outer.try_body[0]
    assert isinstance(inner, ast.TryCatchStatement)
    assert isinstance(inner.catch_clauses[0].body[0], ast.RethrowStatement)
    assert isinstance(outer.catch_clauses[0].body[0], ast.ThrowStatement)


def test_throw_expression_and_bare_rethrow_have_distinct_ast_nodes() -> None:
    program = _parse("throw error;\nthrow;")

    assert isinstance(program.statements[0], ast.ThrowStatement)
    assert program.statements[0].expression == ast.Identifier("error", 1, 7)
    assert program.statements[0].line == 1
    assert program.statements[0].column == 1
    assert program.statements[1] == ast.RethrowStatement(2, 1)


def test_parser_records_try_and_each_catch_source_location() -> None:
    statement = _parse(
        """

  try {
  }
    catch (FirstError first) {
    }
      catch (Error error) {
      }
"""
    ).statements[0]

    assert isinstance(statement, ast.TryCatchStatement)
    assert (statement.line, statement.column) == (3, 3)
    assert [(clause.line, clause.column) for clause in statement.catch_clauses] == [
        (5, 5),
        (7, 7),
    ]


def test_ast_equality_includes_catch_order_type_binder_body_and_rethrow_identity() -> None:
    first = _parse(
        "try { throw value; } "
        "catch (FirstError first) { throw; } "
        "catch (SecondError second) { throw second; }"
    )
    same = _parse(
        "try { throw value; } "
        "catch (FirstError first) { throw; } "
        "catch (SecondError second) { throw second; }"
    )
    reordered = _parse(
        "try { throw value; } "
        "catch (SecondError second) { throw second; } "
        "catch (FirstError first) { throw; }"
    )

    assert first == same
    assert first != reordered
    assert ast.ThrowStatement(ast.Identifier("error")) != ast.RethrowStatement()


def test_generic_ast_traversal_reaches_every_catch_and_rethrow() -> None:
    program = _parse(
        "try { work(); } "
        "catch (FirstError first) { firstHandler(); } "
        "catch (Error error) { throw; }"
    )
    visited = list(_walk(program))

    assert sum(isinstance(node, ast.CatchClause) for node in visited) == 2
    assert any(
        isinstance(node, ast.CallExpression) and node.callee == "firstHandler"
        for node in visited
    )
    assert any(isinstance(node, ast.RethrowStatement) for node in visited)


def test_capability_visitor_reaches_later_catches_and_rethrow() -> None:
    typed = prepare_typed_program(
        """
struct FirstError implements Error {
    string message() { return "first"; }
}

int main() {
    try {
        println("try");
    } catch (FirstError first) {
        println("first");
    } catch (Error error) {
        throw;
    }
    return 0;
}
""",
        TypeChecker(),
    )

    required = {
        requirement.capability
        for requirement in detect_required_capabilities(typed)
    }
    assert Capability.ERROR_HANDLING in required
    assert Capability.PRINT in required


def test_parser_leaves_semantic_catch_and_rethrow_validation_for_milestone_2() -> None:
    program = _parse(
        "throw; "
        "try { work(); } "
        "catch (FileError first) { } "
        "catch (FileError duplicate) { } "
        "catch (Error error) { } "
        "catch (NetworkError unreachable) { }"
    )

    assert isinstance(program.statements[0], ast.RethrowStatement)
    statement = program.statements[1]
    assert isinstance(statement, ast.TryCatchStatement)
    assert len(statement.catch_clauses) == 4


def test_finally_is_not_reserved_as_a_new_keyword() -> None:
    statement = _parse("finally();").statements[0]

    assert statement == ast.ExpressionStatement(
        ast.CallExpression("finally", [], {}, 1, 1)
    )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("try { }", "Expected at least one 'catch' after try block"),
        ("try catch (Error error) { }", "Expected '{' before block"),
        ("try { } catch", "Expected '(' after 'catch'"),
        ("try { } catch () { }", "Expected a catch type and binder"),
        ("try { } catch (123 error) { }", "Expected catch type"),
        ("try { } catch (Error) { }", "Expected catch binder name"),
        ("try { } catch (Error error { }", "Expected ')' after catch binder"),
        ("try { } catch (Error error)", "Expected '{' before block"),
        ("throw error", "Expected ';' after throw statement"),
        ("throw", "Expected an expression or ';' after 'throw'"),
        ("int value = throw error;", "Expected expression"),
        ("catch (Error error) { }", "must immediately follow a try block"),
        ("try { } finally { }", "'finally' is not part of Aether 1.x"),
    ],
)
def test_invalid_exception_syntax_has_specific_diagnostics(source: str, message: str) -> None:
    with pytest.raises(AetherSyntaxError, match=re.escape(message)):
        _parse(source)


def test_recovery_reports_malformed_multiple_catches_and_reaches_following_statement() -> None:
    parser = Parser(
        lex(
            """
try {
    work();
}
catch (FirstError first)
catch (SecondError second) {
    recover(second);
}
throw;
"""
        )
    )

    program, errors = parser.parse_with_recovery()

    assert errors
    assert "Expected '{' before block" in errors[0].message
    assert any("must immediately follow a try block" in error.message for error in errors)
    assert isinstance(program.statements[-1], ast.RethrowStatement)


def test_formatter_handles_multiple_nested_catches_and_both_throw_forms() -> None:
    source = (
        "try{try {throw   error;}catch ( InnerError inner ){throw ;}}"
        "catch(OuterError outer){throw    outer;}"
        "catch ( Error error ) {throw;}"
    )

    formatted = format_source(source)

    assert formatted == (
        "try {try {throw error;} catch (InnerError inner) {throw;}} "
        "catch (OuterError outer) {throw outer;} "
        "catch (Error error) {throw;}"
    )
    assert format_source(formatted) == formatted
    assert _parse(format_source(formatted)) == _parse(formatted)


def test_formatter_parse_round_trip_preserves_order_and_node_kinds() -> None:
    formatted = format_source(
        "try{throw value;}catch(FileError file){throw file;}"
        "catch(Error error){throw;}"
    )
    reparsed = _parse(formatted)
    statement = reparsed.statements[0]

    assert isinstance(statement, ast.TryCatchStatement)
    assert [clause.type_name for clause in statement.catch_clauses] == [
        "FileError",
        "Error",
    ]
    assert isinstance(statement.try_body[0], ast.ThrowStatement)
    assert isinstance(statement.catch_clauses[1].body[0], ast.RethrowStatement)
