from __future__ import annotations

import pytest

from aether import ast
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.pipeline import prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker
from aether.types import InterfaceType


ERROR_TYPES = """
struct FileError implements Error {
    string text;
    string message() { return text; }
}

class NetworkError implements Error {
    string text;
    public string message() { return text; }
}
"""


def _check(source: str) -> TypeChecker:
    checker = TypeChecker()
    checker.check(Parser(lex(source)).parse())
    return checker


def test_builtin_error_is_an_ordinary_interface_symbol() -> None:
    checker = TypeChecker()

    error = checker.interfaces["Error"]
    assert error.name == "Error"
    assert error.visibility == "public"
    assert [(method.name, method.return_type, method.parameters) for method in error.methods] == [
        ("message", "string", ())
    ]


def test_struct_and_class_can_implement_builtin_error() -> None:
    checker = _check(ERROR_TYPES)

    assert checker.structs["FileError"].implements == ("Error",)
    assert checker.structs["NetworkError"].implements == ("Error",)


def test_multiple_catches_use_exact_dynamic_nominal_matching() -> None:
    result = run_aether(
        ERROR_TYPES
        + """
int main() {
    Error error = NetworkError("offline");
    try {
        throw error;
    } catch (FileError caught) {
        println("wrong concrete catch");
    } catch (NetworkError caught) {
        println(caught.message());
    } catch (Error caught) {
        println("wrong root catch");
    }
    return 0;
}
"""
    )

    assert result.output == "offline\n"


def test_error_catch_is_the_explicit_catch_all() -> None:
    result = run_aether(
        ERROR_TYPES
        + """
int main() {
    try {
        throw FileError("missing");
    } catch (NetworkError caught) {
        println("wrong");
    } catch (Error caught) {
        println(caught.message());
    }
    return 0;
}
"""
    )

    assert result.output == "missing\n"


def test_nested_rethrow_skips_sibling_catches_and_reaches_outer_handler() -> None:
    result = run_aether(
        ERROR_TYPES
        + """
int main() {
    try {
        try {
            throw FileError("original");
        } catch (FileError caught) {
            println("inner");
            if (true) {
                throw;
            }
        } catch (Error sibling) {
            println("sibling");
        }
    } catch (FileError outer) {
        println(outer.message());
    }
    return 0;
}
"""
    )

    assert result.output == "inner\noriginal\n"


def test_handler_search_propagates_through_function_calls_and_unwinds_blocks() -> None:
    result = run_aether(
        ERROR_TYPES
        + """
void fail() {
    FileError error = FileError("deep");
    if (true) {
        throw error;
    }
}

int main() {
    try {
        fail();
        println("unreachable");
    } catch (FileError caught) {
        println(caught.message());
    }
    return 0;
}
"""
    )

    assert result.output == "deep\n"


def test_explicit_throw_in_catch_creates_a_new_event_for_outer_handler() -> None:
    result = run_aether(
        ERROR_TYPES
        + """
int main() {
    try {
        try {
            throw FileError("first");
        } catch (FileError caught) {
            throw NetworkError("replacement");
        } catch (NetworkError sibling) {
            println("sibling");
        }
    } catch (NetworkError outer) {
        println(outer.message());
    }
    return 0;
}
"""
    )

    assert result.output == "replacement\n"


def test_throw_is_terminating_for_return_flow_analysis() -> None:
    _check(
        ERROR_TYPES
        + """
int fail() {
    throw FileError("no result");
}
"""
    )


def test_panic_is_not_caught_as_an_error_event() -> None:
    with pytest.raises(AetherRuntimeError, match=r"pop\(\) cannot be used on an empty List"):
        run_aether(
            ERROR_TYPES
            + """
int main() {
    try {
        List<int> values = {};
        values.pop();
    } catch (Error caught) {
        println("caught");
    }
    return 0;
}
"""
        )


def test_catch_binder_has_declared_type_and_only_catch_scope() -> None:
    typed = prepare_typed_program(
        ERROR_TYPES
        + """
int main() {
    try {
        throw FileError("x");
    } catch (FileError caught) {
        println(caught.message());
    }
    return 0;
}
""",
        TypeChecker(),
    )
    main = next(
        statement
        for statement in typed.program.statements
        if isinstance(statement, ast.FunctionDeclaration) and statement.name == "main"
    )
    try_statement = next(
        statement
        for statement in main.body
        if isinstance(statement, ast.TryCatchStatement)
    )
    call = try_statement.catch_clauses[0].body[0]
    assert isinstance(call, ast.ExpressionStatement)
    assert isinstance(call.expression, ast.CallExpression)
    dotted_call = call.expression.arguments[0]
    assert isinstance(dotted_call, ast.CallExpression)
    method_call = typed.checker.desugared_method_call(dotted_call)
    assert method_call is not None
    assert typed.checker.type_of_expression(method_call.target) == "FileError"

    with pytest.raises(AetherTypeError, match="Undefined variable 'caught'"):
        _check(
            ERROR_TYPES
            + """
int main() {
    try { throw FileError("x"); } catch (FileError caught) { }
    println(caught);
    return 0;
}
"""
        )


def test_root_catch_binder_is_typed_as_error_interface() -> None:
    typed = prepare_typed_program(
        ERROR_TYPES
        + """
int main() {
    try { throw FileError("x"); }
    catch (Error caught) { println(caught.message()); }
    return 0;
}
""",
        TypeChecker(),
    )
    main = next(
        statement
        for statement in typed.program.statements
        if isinstance(statement, ast.FunctionDeclaration) and statement.name == "main"
    )
    try_statement = next(
        statement
        for statement in main.body
        if isinstance(statement, ast.TryCatchStatement)
    )
    call = try_statement.catch_clauses[0].body[0]
    assert isinstance(call, ast.ExpressionStatement)
    dotted_call = call.expression.arguments[0]
    assert isinstance(dotted_call, ast.CallExpression)
    method_call = typed.checker.desugared_method_call(dotted_call)
    assert method_call is not None
    assert typed.checker.type_of_expression(method_call.target) == InterfaceType("Error")


@pytest.mark.parametrize(
    ("source", "message", "line"),
    [
        ("throw 1;", "does not implement Error", 1),
        ("throw null;", "Cannot throw null or a nullable value", 1),
        ("try { } catch (int error) { }", "does not implement Error", 1),
        (
            "try { } catch (MissingError error) { }",
            "Unknown type 'MissingError'",
            1,
        ),
        (
            ERROR_TYPES
            + "try { } catch (FileError first) { } catch (FileError second) { }",
            "Duplicate catch for exact type 'FileError'",
            11,
        ),
        (
            ERROR_TYPES
            + "try { } catch (Error root) { } catch (FileError late) { }",
            "is unreachable because Error is already caught",
            11,
        ),
        ("throw;", "only valid inside an active catch body", 1),
        (
            ERROR_TYPES
            + """
int main() {
    FileError caught = FileError("outer");
    try { throw caught; } catch (FileError caught) { }
    return 0;
}
""",
            "shadowing is not allowed",
            14,
        ),
        (
            ERROR_TYPES
            + """
int main() {
    try { throw FileError("x"); }
    catch (FileError caught) {
        void nested() { throw; }
        nested();
    }
    return 0;
}
""",
            "only valid inside an active catch body",
            15,
        ),
        (
            'int main() { Exception error = Exception("old"); return 0; }',
            "Unknown type 'Exception'",
            1,
        ),
    ],
)
def test_exception_diagnostics_have_source_locations(
    source: str,
    message: str,
    line: int,
) -> None:
    with pytest.raises(AetherTypeError, match=message) as raised:
        _check(source)

    assert raised.value.line == line
    assert isinstance(raised.value.column, int)
    assert raised.value.column >= 1


def test_missing_builtin_error_has_a_specific_diagnostic() -> None:
    checker = TypeChecker()
    del checker.interfaces["Error"]
    program = Parser(lex("throw 1;")).parse()

    with pytest.raises(AetherTypeError, match="Built-in Error interface is undefined") as raised:
        checker.check(program)

    assert (raised.value.line, raised.value.column) == (1, 1)


def test_catch_binder_is_immutable() -> None:
    with pytest.raises(AetherTypeError, match="Cannot assign to constant 'caught'"):
        _check(
            ERROR_TYPES
            + """
int main() {
    try { throw FileError("x"); }
    catch (FileError caught) {
        caught = FileError("replacement");
    }
    return 0;
}
"""
        )


def test_unhandled_event_reports_original_throw_location_and_error_message() -> None:
    with pytest.raises(AetherRuntimeError) as raised:
        run_aether(
            ERROR_TYPES
            + """
int main() {
    throw FileError("unhandled");
}
"""
        )

    assert raised.value.message == "unhandled"
    assert raised.value.kind == "FileError"
    assert (raised.value.line, raised.value.column) == (13, 5)
