from __future__ import annotations

from typing import cast

import pytest

from latex_lang import _build_parser_context, parse_mathtex_line, reset_environment
from mathtex_ast import (
    AssignNode,
    BinOpNode,
    BlockNode,
    ExprStmtNode,
    IndexAssignNode,
    NumberNode,
    RangeNode,
    SliceNode,
    SymbolNode,
    ast_to_python,
    optimize_ast,
)


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_environment()
    yield
    reset_environment()


def _eval_expr(expr_code: str):
    ctx = _build_parser_context()
    return eval(expr_code, {"__builtins__": __builtins__}, ctx.eval_context())


def test_build_ast_from_simple_assignment_returns_assign_node():
    ctx = _build_parser_context()

    node = parse_mathtex_line("x = 2 + 3 * 4", ctx)

    assert isinstance(node, AssignNode)
    node = cast(AssignNode, node)
    assert node.target == SymbolNode("x")
    assert isinstance(node.expr, BinOpNode)
    assert node.expr.op == "+"
    assert node.expr.left == NumberNode(2)
    assert isinstance(node.expr.right, BinOpNode)
    assert node.expr.right.op == "*"
    assert node.expr.right.left == NumberNode(3)
    assert node.expr.right.right == NumberNode(4)


def test_build_ast_from_expression_statement_returns_expr_stmt_node():
    ctx = _build_parser_context()

    node = parse_mathtex_line("f(2) + 3", ctx)

    assert isinstance(node, ExprStmtNode)
    node = cast(ExprStmtNode, node)
    assert isinstance(node.expr, BinOpNode)
    assert node.expr.op == "+"
    assert ast_to_python(node.expr.left) == "f(2)"
    assert node.expr.right == NumberNode(3)


def test_build_ast_from_slice_expression_creates_slice_structure():
    ctx = _build_parser_context()

    node = parse_mathtex_line("A(i + 1:2:j + 3, :) = x + 1", ctx)

    assert isinstance(node, IndexAssignNode)
    node = cast(IndexAssignNode, node)
    assert node.target == SymbolNode("A")
    assert len(node.indices) == 2
    assert isinstance(node.indices[0], SliceNode)
    assert isinstance(node.indices[0].value, RangeNode)
    first_range = cast(RangeNode, node.indices[0].value)
    assert first_range.start == BinOpNode("+", SymbolNode("i"), NumberNode(1))
    assert first_range.step == NumberNode(2)
    assert first_range.end == BinOpNode("+", SymbolNode("j"), NumberNode(3))
    assert node.indices[1] == SliceNode(RangeNode(None, None, None))
    assert ast_to_python(node) == "_oct_set_slice('A', _oct_span((i + 1), 2, (j + 3)), ':', (x + 1))"


def test_ast_to_python_preserves_basic_arithmetic_structure():
    ctx = _build_parser_context()
    node = cast(AssignNode, parse_mathtex_line("x = 2 + 3 * 4", ctx))

    expr_code = ast_to_python(node.expr)

    assert expr_code == "(2 + (3 * 4))"
    assert _eval_expr(expr_code) == 14


def test_optimize_ast_does_not_change_simple_expression_semantics():
    ctx = _build_parser_context()
    node = cast(ExprStmtNode, parse_mathtex_line("2 + 3 * 4", ctx))

    original_code = ast_to_python(node)
    optimized = optimize_ast(node, {})
    optimized_code = ast_to_python(optimized)

    assert isinstance(optimized, ExprStmtNode)
    assert _eval_expr(original_code) == 14
    assert _eval_expr(optimized_code) == 14
    assert optimized_code == "14"


def test_block_node_preserves_statement_order():
    block = BlockNode(
        [
            AssignNode(SymbolNode("x"), NumberNode(1)),
            AssignNode(SymbolNode("y"), BinOpNode("+", SymbolNode("x"), NumberNode(2))),
            ExprStmtNode(SymbolNode("y")),
        ]
    )

    rendered = ast_to_python(block).splitlines()

    assert rendered == ["x = 1", "y = (x + 2)", "y"]
