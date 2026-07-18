from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether import AetherSession
from aether.backend.llvm import LLVMBackendError, LLVMRunner, print_llvm
from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.integer_arithmetic import INTEGER_OVERFLOW_MESSAGE, INT_MAX, INT_MIN
from aether.interpreter import Interpreter
from aether.ir import (
    IRBasicBlock,
    IRConst,
    IRExecutionError,
    IRFunction,
    IRInterpreter,
    IRModule,
    IRReturn,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
)
from aether.lexer import lex
from aether.pipeline import (
    IRBackend,
    lower_to_verified_ssa,
    parse_source,
    prepare_typed_program,
)
from aether.runner import run_aether
from aether.source_formatter import format_source
from aether.ssa import (
    SSABasicBlock,
    SSAConst,
    SSAFunction,
    SSAModule,
    SSAReturn,
    SSAValue,
    SSAVerificationError,
    SSAVerifier,
)
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _main(body: str) -> str:
    return f"int main() {{ {body} return 0; }}"


@pytest.mark.parametrize("value", ["0", "1", "-1", str(INT_MAX), str(INT_MIN)])
def test_signed_i32_boundary_literals_are_accepted_everywhere(value: str) -> None:
    source = _main(f"println({value});")
    expected = f"{value}\n"

    assert run_aether(f"println({value});").output == expected

    typed = _typed(source)
    module = IRBackend().lower_verified(typed)
    interpreter = IRInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == expected
    llvm = print_llvm(lower_to_verified_ssa(typed))
    assert "define i32 @main()" in llvm
    assert "i32 2147483648" not in llvm


def test_int_min_magnitude_is_only_admitted_under_immediate_unary_minus() -> None:
    for expression in ("-2147483648", "-(2147483648)"):
        assert run_aether(f"println({expression});").output == f"{INT_MIN}\n"
        typed = _typed(_main(f"println({expression});"))
        llvm = print_llvm(lower_to_verified_ssa(typed))
        assert "i32 -2147483648" in llvm
        assert "i32 2147483648" not in llvm

    with pytest.raises(AetherTypeError, match="Integer literal 2147483648"):
        _typed(_main("println(2147483648);"))
    with pytest.raises(AetherSyntaxError):
        parse_source("int value = +2147483648;")


@pytest.mark.parametrize(
    ("source", "rendered"),
    [
        ("int value = 2147483648;", "2147483648"),
        ("int value = -2147483649;", "-2147483649"),
        ("int value = 999999999999999999999;", "999999999999999999999"),
        ("const int VALUE = 2147483648;", "2147483648"),
        ("int bad() { return 2147483648; }", "2147483648"),
        ("void take(int value) {} take(2147483648);", "2147483648"),
        ("struct Box { int value; } Box box = Box(2147483648);", "2147483648"),
        ("Array<int> values = {2147483648};", "2147483648"),
        ("List<int> values = {2147483648};", "2147483648"),
        ("Matrix<int> values = [2147483648];", "2147483648"),
    ],
)
def test_out_of_range_literals_are_rejected_in_every_source_context(
    source: str,
    rendered: str,
) -> None:
    with pytest.raises(AetherTypeError) as raised:
        _typed(source)

    error = raised.value
    assert error.message == (
        f"Integer literal {rendered} is outside the range of Aether int "
        f"[{INT_MIN}, {INT_MAX}]."
    )
    assert error.line == 1
    assert isinstance(error.column, int) and error.column > 1
    assert error.kind == "integer-literal"


def test_repl_rejects_out_of_range_literal_and_rolls_back_state() -> None:
    session = AetherSession()
    session.run("int kept = 7;")

    with pytest.raises(AetherTypeError, match="Integer literal 2147483648"):
        session.run("int rejected = 2147483648;")

    assert session.run("println(kept);").output == "7\n"
    with pytest.raises(AetherTypeError, match="Undefined variable 'rejected'"):
        session.run("println(rejected);")


@pytest.mark.parametrize("expression", ["--2147483648", "-(-2147483648)"])
def test_negating_int_min_remains_checked_overflow(expression: str) -> None:
    source = _main(f"println({expression});")

    # This is an operation overflow, not an invalid-literal diagnostic.
    typed = _typed(source)
    with pytest.raises(AetherRuntimeError, match=INTEGER_OVERFLOW_MESSAGE):
        run_aether(f"println({expression});")
    with pytest.raises(IRExecutionError, match=INTEGER_OVERFLOW_MESSAGE):
        IRInterpreter(IRBackend().lower_verified(typed)).call("main")


def test_computed_overflow_is_not_reported_as_an_invalid_literal() -> None:
    source = "int result = 2147483647 + 1;"
    _typed(source)

    with pytest.raises(AetherRuntimeError, match=INTEGER_OVERFLOW_MESSAGE) as raised:
        run_aether(source)
    assert "outside the range" not in str(raised.value)


def test_lexer_and_formatter_preserve_magnitude_without_defining_bigint_semantics() -> None:
    source = "int value = 999999999999999999999;\n"
    token = next(token for token in lex(source) if token.lexeme.startswith("999"))

    assert token.literal == 999999999999999999999
    assert format_source(source) == source
    with pytest.raises(AetherTypeError, match="outside the range of Aether int"):
        _typed(source)


def test_raw_ast_interpreter_refuses_invalid_host_integer() -> None:
    program = parse_source("println(2147483648);")

    with pytest.raises(AetherRuntimeError, match="Invalid|outside the range"):
        Interpreter().interpret(program)


def test_ir_and_ssa_verifiers_reject_out_of_range_int_constants() -> None:
    int_type = IntType()
    ir_value = IRValue("value", int_type)
    ir_module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(ir_value, INT_MAX + 1), IRReturn(ir_value)],
                    )
                ],
            )
        ]
    )
    with pytest.raises(IRVerificationError, match="outside signed i32 range"):
        IRVerifier(ir_module).verify()
    with pytest.raises(IRExecutionError, match="Invalid internal int constant"):
        IRInterpreter(ir_module).call("main")

    ssa_value = SSAValue("value", int_type)
    ssa_module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [SSAConst(ssa_value, INT_MAX + 1), SSAReturn(ssa_value)],
                    )
                ],
            )
        ]
    )
    with pytest.raises(SSAVerificationError, match="outside signed i32 range"):
        SSAVerifier(ssa_module).verify()
    with pytest.raises(LLVMBackendError, match="refuses out-of-range i32 constant"):
        print_llvm(ssa_module)


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_int_boundary_output_matches_ast_and_ir() -> None:
    source = _main("println(2147483647); println(-2147483648);")
    expected = f"{INT_MAX}\n{INT_MIN}\n"
    typed = _typed(source)

    ast_output = run_aether("println(2147483647); println(-2147483648);").output
    ir = IRInterpreter(IRBackend().lower_verified(typed))
    assert ir.call("main") == 0

    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
    assert ast_output == ir.output == stdout.getvalue() == expected
    assert stderr.getvalue() == ""
