from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether import ast
from aether.backend.llvm import LLVMBackend, LLVMRunner
from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.interpreter import Interpreter
from aether.ir import (
    BoolType,
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInterpreter,
    IRModule,
    IRReturn,
    IRUnaryOp,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    print_ir,
)
from aether.ir.optimizer import ConstantFolder, DeadCodeEliminator
from aether.lexer import lex
from aether.parser import Parser
from aether.pipeline import (
    IRBackend,
    lower_to_verified_ssa,
    parse_source,
    prepare_typed_program,
)
from aether.runner import run_aether
from aether.ssa import (
    SSABasicBlock,
    SSAConst,
    SSAFunction,
    SSAModule,
    SSAReturn,
    SSAUnaryOp,
    SSAValue,
    SSAVerificationError,
    SSAVerifier,
    print_ssa,
)
from aether.ssa.optimizer import SCCPPass, SSAConstantFolder, SSADeadCodeEliminator
from aether.tokens import TokenType
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def test_lexer_distinguishes_logical_not_from_inequality() -> None:
    tokens = lex("!value != false")

    assert [token.type for token in tokens] == [
        TokenType.BANG,
        TokenType.IDENTIFIER,
        TokenType.BANG_EQUAL,
        TokenType.BOOLEAN_LITERAL,
        TokenType.EOF,
    ]


def test_parser_builds_prefix_not_with_unary_precedence() -> None:
    expression = Parser(lex("!a == b;")).parse().statements[0].expression

    assert isinstance(expression, ast.BinaryExpression)
    assert expression.operator == "=="
    assert isinstance(expression.left, ast.UnaryExpression)
    assert expression.left.operator == "!"
    assert isinstance(expression.left.operand, ast.Identifier)
    assert expression.left.operand.name == "a"


@pytest.mark.parametrize("source", ["5!;", "x!;", "!x!;"])
def test_postfix_bang_is_invalid(source: str) -> None:
    with pytest.raises(AetherSyntaxError):
        parse_source(source)


def test_ast_interpreter_supports_not_variables_repetition_precedence_and_if() -> None:
    result = run_aether(
        """
println(!true);
println(!false);
boolean value = true;
println(!value);
println(!!value);
boolean a = true;
boolean b = false;
println(!a && b);
println(!(a && b));
if !b { println("not ready"); }
println(1 != 2);
println(true != false);
"""
    )

    assert result.output == (
        "false\ntrue\nfalse\ntrue\nfalse\ntrue\nnot ready\ntrue\ntrue\n"
    )


@pytest.mark.parametrize("expression", ["!1", "!1.0", '!"text"'])
def test_logical_not_rejects_non_boolean_operands(expression: str) -> None:
    with pytest.raises(
        AetherTypeError,
        match=r"Unary operator '!' requires a boolean operand\.",
    ):
        run_aether(f"println({expression});")


def test_ast_interpreter_defensively_rejects_non_boolean_not_without_typecheck() -> None:
    program = parse_source("println(!1);")

    with pytest.raises(
        AetherRuntimeError,
        match=r"Unary operator '!' requires a boolean operand\.",
    ):
        Interpreter().interpret(program)


def test_ir_and_ssa_lower_not_as_pure_explicit_instructions() -> None:
    source = "boolean flip(boolean value) { return !value; }"
    typed = _typed(source)

    ir_module = IRBackend().lower_verified(typed)
    ir_not = ir_module.functions[0].blocks[0].instructions[0]

    assert isinstance(ir_not, IRUnaryOp)
    assert ir_not.operator == "not"
    assert ir_not.result.type == BoolType()
    assert ir_not.effects.has_side_effects is False
    assert ir_not.effects.may_trap is False
    assert ir_not.effects.reads_memory is False
    assert ir_not.effects.writes_memory is False
    assert ir_not.effects.allocates is False
    assert "bool = not %value" in print_ir(ir_module)

    ssa_module = lower_to_verified_ssa(typed)
    ssa_not = ssa_module.functions[0].blocks[0].instructions[0]

    assert isinstance(ssa_not, SSAUnaryOp)
    assert ssa_not.operator == "not"
    assert ssa_not.result.type == BoolType()
    assert ssa_not.effects == ir_not.effects
    assert "bool = not %value" in print_ssa(ssa_module)
    assert SSAVerifier(ssa_module).verify() is ssa_module

    llvm = LLVMBackend().emit(ssa_module)
    assert "xor i1 %value, true" in llvm


@pytest.mark.parametrize(("value", "expected"), [(True, False), (False, True)])
def test_ir_and_ssa_constant_folding_handle_not(value: bool, expected: bool) -> None:
    bool_type = BoolType()
    operand = IRValue("operand", bool_type)
    result = IRValue("result", bool_type)
    ir_module = IRModule(
        [
            IRFunction(
                "main",
                [],
                bool_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(operand, value),
                            IRUnaryOp(result, "not", operand),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )
    folded_ir = ConstantFolder().run(ir_module).module
    assert folded_ir.functions[0].blocks[0].instructions[1] == IRConst(result, expected)

    ssa_operand = SSAValue("operand", bool_type)
    ssa_result = SSAValue("result", bool_type)
    ssa_module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(ssa_operand, value),
                            SSAUnaryOp(ssa_result, "not", ssa_operand),
                            SSAReturn(ssa_result),
                        ],
                    )
                ],
            )
        ]
    )
    folded_ssa = SSAConstantFolder().run(ssa_module).module
    assert folded_ssa.functions[0].blocks[0].instructions[1] == SSAConst(
        ssa_result, expected
    )
    sccp_ssa = SCCPPass().run(ssa_module).module
    assert sccp_ssa.functions[0].blocks[0].instructions[1] == SSAConst(
        ssa_result, expected
    )


def test_dead_not_is_removed_by_ir_and_ssa_dce() -> None:
    bool_type = BoolType()
    int_type = IntType()
    operand = IRValue("operand", bool_type)
    unused = IRValue("unused", bool_type)
    returned = IRValue("returned", int_type)
    ir_module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(operand, True),
                            IRUnaryOp(unused, "not", operand),
                            IRConst(returned, 0),
                            IRReturn(returned),
                        ],
                    )
                ],
            )
        ]
    )
    optimized_ir = DeadCodeEliminator().run(ir_module).module
    assert not any(
        isinstance(instruction, IRUnaryOp)
        for instruction in optimized_ir.functions[0].blocks[0].instructions
    )

    ssa_operand = SSAValue("operand", bool_type)
    ssa_unused = SSAValue("unused", bool_type)
    ssa_returned = SSAValue("returned", int_type)
    ssa_module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(ssa_operand, True),
                            SSAUnaryOp(ssa_unused, "not", ssa_operand),
                            SSAConst(ssa_returned, 0),
                            SSAReturn(ssa_returned),
                        ],
                    )
                ],
            )
        ]
    )
    optimized_ssa = SSADeadCodeEliminator().run(ssa_module).module
    assert not any(
        isinstance(instruction, SSAUnaryOp)
        for instruction in optimized_ssa.functions[0].blocks[0].instructions
    )


def test_ir_interpreter_executes_not() -> None:
    source = "boolean flip(boolean value) { return !value; }"

    module = IRBackend().lower_verified(_typed(source))
    interpreter = IRInterpreter(module)

    assert interpreter.call("flip", [True]) is False
    assert interpreter.call("flip", [False]) is True


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is unavailable")
def test_native_execution_matches_logical_not_semantics() -> None:
    source = "int main() { boolean ready = false; println(!ready); return 0; }"
    stdout = StringIO()
    stderr = StringIO()

    exit_code = LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr)

    assert exit_code == 0
    assert stdout.getvalue() == "true\n"
    assert stderr.getvalue() == ""


def test_ir_and_ssa_verifiers_reject_non_boolean_not() -> None:
    int_type = IntType()
    bool_type = BoolType()
    operand = IRValue("operand", int_type)
    result = IRValue("result", bool_type)
    ir_module = IRModule(
        [
            IRFunction(
                "main",
                [],
                bool_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(operand, 1),
                            IRUnaryOp(result, "not", operand),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )
    with pytest.raises(IRVerificationError, match="requires bool operand"):
        IRVerifier(ir_module).verify()

    ssa_operand = SSAValue("operand", int_type)
    ssa_result = SSAValue("result", bool_type)
    ssa_module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(ssa_operand, 1),
                            SSAUnaryOp(ssa_result, "not", ssa_operand),
                            SSAReturn(ssa_result),
                        ],
                    )
                ],
            )
        ]
    )
    with pytest.raises(SSAVerificationError, match="requires bool operand"):
        SSAVerifier(ssa_module).verify()
