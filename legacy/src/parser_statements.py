from __future__ import annotations

from typing import Callable

from diagnostics import make_parse_error
from mathtex_ast import ASTNode, AssignNode, ExprStmtNode, IndexAssignNode, SymbolNode
from parser_indices import parse_indexed_assignment_lhs
from parsers import ParserContext


ParseMathtexExpr = Callable[[str, ParserContext], ASTNode]
NormalizeName = Callable[[str], str]


def parse_mathtex_line(
    line: str,
    ctx: ParserContext,
    parse_mathtex_expr: ParseMathtexExpr,
    normalize_name: NormalizeName,
) -> ASTNode | None:
    """
    Parsea una linea simple de MathTeX en un AST.
    Devuelve None si la linea esta vacia o no es una sentencia simple.
    """
    stripped = line.strip()
    if not stripped:
        return None

    is_assignment = "=" in stripped and "==" not in stripped and not stripped.startswith("\\")
    if is_assignment:
        lhs, rhs = [part.strip() for part in stripped.split("=", 1)]
        if not lhs or not rhs:
            eq_column = stripped.find("=") + 1
            if not lhs and not rhs:
                message = "Assignment is missing both the target and the value."
                hint = "Write a target on the left and an expression on the right of '='."
            elif not lhs:
                message = "Assignment is missing the target name."
                hint = "Add a variable name or indexed target before '='."
            else:
                message = "Assignment is missing the expression on the right side."
                hint = "Add an expression after '='."
            raise make_parse_error(
                "incomplete-assignment",
                message,
                source=stripped,
                column=eq_column,
                hint=hint,
            )
        indexed = parse_indexed_assignment_lhs(lhs, ctx, parse_mathtex_expr, normalize_name)
        if indexed is not None:
            target, indices = indexed
            expr_ast = parse_mathtex_expr(rhs, ctx)
            return IndexAssignNode(target, indices, expr_ast)
        if lhs.startswith("[") or "(" in lhs or ")" in lhs:
            return None
        target = SymbolNode(normalize_name(lhs))
        expr_ast = parse_mathtex_expr(rhs, ctx)
        return AssignNode(target, expr_ast)

    expr_ast = parse_mathtex_expr(stripped, ctx)
    return ExprStmtNode(expr_ast)
