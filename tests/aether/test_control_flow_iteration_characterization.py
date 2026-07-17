from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether import ast
from aether.backend.llvm import LLVMRunner
from aether.capabilities import (
    BackendCapabilityError,
    BackendIdentity,
    validate_backend_capabilities,
)
from aether.errors import (
    AetherRuntimeError,
    AetherSyntaxError,
    AetherTypeError,
)
from aether.ir import (
    IRExecutionError,
    IRInterpreter,
    IRLowerer,
    IRVerifier,
    print_ir,
)
from aether.lexer import lex
from aether.parser import Parser
from aether.pipeline import prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker
from aether.types import RangeType


_HAS_CLANG = shutil.which("clang") is not None


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _lower(source: str):
    typed = _typed(source)
    return IRVerifier(IRLowerer().lower(typed.program)).verify()


def test_parentheses_are_required_for_all_control_flow_headers() -> None:
    program = Parser(
        lex(
            """
int main() {
    if (true) { }
    while (false) { }
    return 0;
}
"""
        )
    ).parse()

    body = program.statements[0].body
    assert isinstance(body[0], ast.IfStatement)
    assert isinstance(body[1], ast.WhileStatement)

    for source in (
        "int main() { for (i in 1:3) { } return 0; }",
        "int main() { for (int i in 1:3) { } return 0; }",
    ):
        Parser(lex(source)).parse()

    for keyword, source in (
        ("if", "if true { }"),
        ("while", "while true { }"),
        ("for", "for i in 1:3 { }"),
    ):
        with pytest.raises(AetherSyntaxError, match=rf"Expected '\(' after '{keyword}'") as caught:
            Parser(lex(source)).parse()
        assert "require parentheses in Aether 1.0" in str(caught.value)


def test_else_if_is_nested_ast_and_executes_lazily() -> None:
    program = Parser(
        lex("int main() { if (false) { } else if (true) { } else { } return 0; }")
    ).parse()
    outer = program.statements[0].body[0]
    assert isinstance(outer, ast.IfStatement)
    assert outer.else_body is not None and len(outer.else_body) == 1
    assert isinstance(outer.else_body[0], ast.IfStatement)

    result = run_aether(
        """
int main() {
    if (false) {
        println("if");
    } else if (true) {
        println("nested-if");
    } else {
        println("else");
    }
    return 0;
}
"""
    )
    assert result.output == "nested-if\n"


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("for (in 1:3) { }", "Expected loop variable after 'for'"),
        ("for (i 1:3) { }", "Expected 'in' after loop variable"),
        ("for (int i 1:3) { }", "Expected loop variable after 'for'"),
        ("for int i in { }", "Expected '\\(' after 'for'"),
    ],
)
def test_malformed_for_headers_keep_their_current_generic_diagnostics(
    header: str,
    message: str,
) -> None:
    with pytest.raises(AetherSyntaxError, match=message):
        Parser(lex(header)).parse()


def test_integer_ranges_are_inclusive_lazy_directional_sequences() -> None:
    result = run_aether(
        """
for (a in 1:3) { print(a); }
println("");
for (b in 1:2:5) { print(b); }
println("");
for (c in 5:-2:1) { print(c); }
println("");
for (d in 1:-1:3) { print(d); }
for (e in 3:1) { print(e); }
"""
    )

    assert result.output == "123\n135\n531\n"


def test_static_range_step_zero_is_a_compile_time_error() -> None:
    with pytest.raises(AetherTypeError, match="Range step cannot be zero"):
        _typed("int main() { for (i in 1:0:3) { } return 0; }")


def test_ast_dynamic_range_step_zero_is_a_runtime_iteration_error() -> None:
    with pytest.raises(AetherTypeError, match="Range step cannot be zero"):
        run_aether("int step = 0; for (i in 1:step:3) { println(i); }")


def test_ir_dynamic_zero_step_is_a_runtime_error() -> None:
    dynamic = _lower(
        """
int count(int step) {
    int result = 0;
    for (i in 1:step:3) { result = result + 1; }
    return result;
}
int main() { return count(0); }
"""
    )
    with pytest.raises(IRExecutionError, match="Range step cannot be zero"):
        IRInterpreter(dynamic).call("count", [0])


@pytest.mark.skipif(not _HAS_CLANG, reason="clang is required")
def test_native_dynamic_zero_step_matches_ast_and_ir() -> None:
    source = "int main() { int step = 0; for (i in 1:step:3) { return 9; } return 0; }"

    with pytest.raises(AetherTypeError, match="Range step cannot be zero"):
        run_aether(source)
    with pytest.raises(IRExecutionError, match="Range step cannot be zero"):
        IRInterpreter(_lower(source)).call("main")
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout) == 1
    assert stdout.getvalue() == "Aether panic: Range step cannot be zero\n"


@pytest.mark.parametrize(
    ("header", "iterable", "expected_error"),
    [
        ("int i", "1:10", None),
        ("i", "1:10", None),
        ("double i", "1:10", "type mismatch: expected 'double', got 'int'"),
        ("double i", "1:0.1:10", "Range bounds and step must be int, got 'double'"),
        ("i", "1:0.1:10", "Range bounds and step must be int, got 'double'"),
        ("int i", "1:0.1:10", "Range bounds and step must be int, got 'double'"),
    ],
)
def test_range_header_type_compatibility_matrix(
    header: str,
    iterable: str,
    expected_error: str | None,
) -> None:
    source = f"int main() {{ for ({header} in {iterable}) {{ }} return 0; }}"
    program = Parser(lex(source)).parse()
    loop = program.statements[0].body[0]
    assert isinstance(loop, ast.ForInStatement)

    checker = TypeChecker()
    if expected_error is not None:
        with pytest.raises(AetherTypeError, match=expected_error):
            checker.check(program)
        return

    checker.check(program)
    assert checker.type_of_expression(loop.iterable) == RangeType("int")
    assert loop.variable_type == ("int" if header == "int i" else None)
    IRVerifier(IRLowerer().lower(program)).verify()


def test_array_list_and_vector_accept_explicit_and_inferred_iteration_types() -> None:
    source = """
int main() {
    Array<int> array = {1, 2};
    List<int> list = {3, 4};
    Vector<int, Row> vector = [5, 6];
    int sum = 0;
    for (int a in array) { sum = sum + a; }
    for (b in list) { sum = sum + b; }
    for (int c in vector) { sum = sum + c; }
    return sum - 21;
}
"""

    assert run_aether(source).exit_code == 0
    assert IRInterpreter(_lower(source)).call("main") == 0
    if _HAS_CLANG:
        assert LLVMRunner().run(_typed(source)) == 0


def test_string_and_struct_collection_elements_support_typed_and_inferred_headers() -> None:
    source = """
struct User { int id; }
int main() {
    Array<string> strings = {"Ada", "Lin"};
    List<User> users = {User(1), User(2)};
    for (string name in strings) { println(name); }
    for (User user in users) { println(user.id); }
    for (inferred in users) { println(inferred.id); }
    return 0;
}
"""
    expected = "Ada\nLin\n1\n2\n1\n2\n"

    assert run_aether(source).output == expected
    if _HAS_CLANG:
        stdout = StringIO()
        stderr = StringIO()
        assert LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr) == 0
        assert stdout.getvalue() == expected
        assert stderr.getvalue() == ""


def test_class_collection_iteration_is_ast_only() -> None:
    source = """
class User { public int id; }
int main() {
    List<User> users = {User(1), User(2)};
    for (User user in users) { println(user.id); }
    for (inferred in users) { println(inferred.id); }
    return 0;
}
"""
    assert run_aether(source).output == "1\n2\n1\n2\n"

    with pytest.raises(BackendCapabilityError, match="classes"):
        validate_backend_capabilities(_typed(source), BackendIdentity.NATIVE)


def test_incompatible_collection_iteration_type_has_no_implicit_header_conversion() -> None:
    with pytest.raises(
        AetherTypeError,
        match="For loop variable 'value' type mismatch: expected 'double', got 'int'",
    ):
        _typed(
            "int main() { Array<int> values = {1}; "
            "for (double value in values) { } return 0; }"
        )


def test_break_continue_external_mutation_scope_and_return_are_preserved() -> None:
    source = """
int find() {
    int total = 0;
    for (i in 1:5) {
        int local = i;
        if (i == 2) { continue; }
        total = total + local;
        if (i == 4) { return total; }
    }
    return -1;
}
int main() { return find() - 8; }
"""

    assert run_aether(source).exit_code == 0
    assert IRInterpreter(_lower(source)).call("main") == 0
    if _HAS_CLANG:
        assert LLVMRunner().run(_typed(source)) == 0

    with pytest.raises(AetherTypeError, match="Undefined variable 'local'"):
        _typed(
            "int main() { for (i in 1:1) { int local = i; } return local; }"
        )


def test_ir_emits_scope_cleanup_before_continue_break_and_return() -> None:
    module = _lower(
        """
int f(boolean stop) {
    int sum = 0;
    for (i in 1:3) {
        List<int> temporary = {i};
        if (i == 1) { continue; }
        if (stop) { return temporary[0]; }
        sum = sum + temporary[0];
        break;
    }
    return sum;
}
int main() { return f(false); }
"""
    )
    ir = print_ir(module)

    assert "destroy %temporary: list<int>\n    jump for.inc0" in ir
    assert "destroy %temporary: list<int>\n    destroy %i: int" in ir
    assert "destroy %temporary: list<int>\n    jump for.exit0" in ir


@pytest.mark.skipif(not _HAS_CLANG, reason="clang is required")
def test_range_at_int_max_terminates_without_post_terminal_overflow() -> None:
    source = """
int main() {
    int count = 0;
    for (i in 2147483647:2147483647) { count = count + 1; }
    return count - 1;
}
"""

    assert run_aether(source).exit_code == 0
    assert IRInterpreter(_lower(source)).call("main") == 0

    stdout = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout) == 0
    assert stdout.getvalue() == ""


@pytest.mark.skipif(not _HAS_CLANG, reason="clang is required")
def test_range_at_int_min_terminates_without_post_terminal_overflow() -> None:
    source = """
int main() {
    int count = 0;
    for (i in -2147483648:-1:-2147483648) { count = count + 1; }
    return count - 1;
}
"""

    assert run_aether(source).exit_code == 0
    assert IRInterpreter(_lower(source)).call("main") == 0
    assert LLVMRunner().run(_typed(source)) == 0


@pytest.mark.parametrize(
    "range_expression",
    [
        "2147483646:2:2147483647",
        "-2147483647:-2:-2147483648",
    ],
)
def test_range_overflow_before_reaching_endpoint_is_preserved(
    range_expression: str,
) -> None:
    source = f"int main() {{ for (i in {range_expression}) {{ }} return 0; }}"
    with pytest.raises(AetherRuntimeError, match="Integer overflow"):
        run_aether(source)
    with pytest.raises(IRExecutionError, match="Integer overflow"):
        IRInterpreter(_lower(source)).call("main")
    if _HAS_CLANG:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(source), stdout=stdout) == 1
        assert stdout.getvalue() == "Aether panic: Integer overflow\n"
