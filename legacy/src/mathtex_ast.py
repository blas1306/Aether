from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple


class ASTNode:
    """Base de todos los nodos AST de MathTeX."""


@dataclass
class NumberNode(ASTNode):
    value: Any


@dataclass
class SymbolNode(ASTNode):
    name: str


@dataclass
class MatrixLiteralNode(ASTNode):
    values: Sequence[ASTNode]


@dataclass
class TupleLiteralNode(ASTNode):
    values: Sequence[ASTNode]


@dataclass
class VectorLiteralNode(ASTNode):
    values: Sequence[ASTNode]


@dataclass
class ListLiteralNode(ASTNode):
    values: Sequence[ASTNode]


@dataclass
class UnaryOpNode(ASTNode):
    op: str
    operand: ASTNode


@dataclass
class BinOpNode(ASTNode):
    op: str
    left: ASTNode
    right: ASTNode


@dataclass
class CallNode(ASTNode):
    func_name: str
    args: List[ASTNode]
    keywords: List[Tuple[str, ASTNode]] | None = None


@dataclass
class IndexNode(ASTNode):
    base: ASTNode
    indices: List[ASTNode]


@dataclass
class RangeNode(ASTNode):
    start: ASTNode | None
    step: ASTNode | None
    end: ASTNode | None


@dataclass
class SliceNode(ASTNode):
    value: ASTNode


@dataclass
class IndexAssignNode(ASTNode):
    target: SymbolNode
    indices: List[SliceNode]
    expr: ASTNode


@dataclass
class AssignNode(ASTNode):
    target: SymbolNode
    expr: ASTNode


@dataclass
class ExprStmtNode(ASTNode):
    expr: ASTNode


@dataclass
class BlockNode(ASTNode):
    statements: Sequence[ASTNode]


_BIN_OP_SYMBOLS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Pow: "**",
    ast.MatMult: "@",
    ast.Mod: "%",
    ast.FloorDiv: "//",
}

_UNARY_OP_SYMBOLS = {
    ast.UAdd: "+",
    ast.USub: "-",
    ast.Invert: "~",
    ast.Not: "not ",
}

_CMP_OP_SYMBOLS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Is: "is",
    ast.IsNot: "is not",
}


def _attr_to_str(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attr_to_str(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        if hasattr(ast, "unparse"):
            try:
                return ast.unparse(node)
            except Exception:
                pass

        def _simple_to_str(n: ast.AST) -> str:
            if isinstance(n, ast.Constant):
                return repr(n.value)
            if isinstance(n, ast.Name):
                return n.id
            if isinstance(n, ast.Attribute):
                return _attr_to_str(n)
            raise ValueError(f"Nombre de atributo no soportado: {ast.dump(n)}")

        base = _simple_to_str(node.value)
        if isinstance(node.slice, ast.Tuple):
            idx = ", ".join(_simple_to_str(elt) for elt in node.slice.elts)
        else:
            if isinstance(node.slice, ast.Constant):
                idx = repr(node.slice.value)
            elif isinstance(node.slice, ast.Name):
                idx = node.slice.id
            elif isinstance(node.slice, ast.Attribute):
                idx = _attr_to_str(node.slice)
            else:
                raise ValueError(f"Indice no soportado en subscript: {ast.dump(node.slice)}")
        return f"{base}[{idx}]"
    raise ValueError(f"Nombre de atributo no soportado: {ast.dump(node)}")


def _convert_python_ast(node: ast.AST) -> ASTNode:
    if isinstance(node, ast.Constant):
        return NumberNode(node.value)
    if isinstance(node, ast.Name):
        return SymbolNode(node.id)
    if isinstance(node, ast.Attribute):
        return SymbolNode(_attr_to_str(node))
    if isinstance(node, ast.List):
        values = [_convert_python_ast(elt) for elt in node.elts]
        if values and all(isinstance(value, (VectorLiteralNode, ListLiteralNode)) for value in values):
            return MatrixLiteralNode(values)
        if any(isinstance(value, NumberNode) and isinstance(value.value, str) for value in values):
            return ListLiteralNode(values)
        return VectorLiteralNode(values)
    if isinstance(node, ast.Tuple):
        return TupleLiteralNode([_convert_python_ast(elt) for elt in node.elts])
    if isinstance(node, ast.UnaryOp):
        op_cls = type(node.op)
        if op_cls not in _UNARY_OP_SYMBOLS:
            raise ValueError(f"Operador unario no soportado: {op_cls}")
        return UnaryOpNode(_UNARY_OP_SYMBOLS[op_cls], _convert_python_ast(node.operand))
    if isinstance(node, ast.BinOp):
        op_cls = type(node.op)
        if op_cls not in _BIN_OP_SYMBOLS:
            raise ValueError(f"Operador binario no soportado: {op_cls}")
        return BinOpNode(
            _BIN_OP_SYMBOLS[op_cls],
            _convert_python_ast(node.left),
            _convert_python_ast(node.right),
        )
    if isinstance(node, ast.BoolOp):
        op_str = "and" if isinstance(node.op, ast.And) else "or"
        values = [_convert_python_ast(val) for val in node.values]
        current = values[0]
        for val in values[1:]:
            current = BinOpNode(op_str, current, val)
        return current
    if isinstance(node, ast.Compare):
        if len(node.ops) != len(node.comparators):
            raise ValueError("Comparacion invalida.")
        left = _convert_python_ast(node.left)
        combined: ASTNode | None = None
        prev = left
        for op, comp in zip(node.ops, node.comparators):
            op_cls = type(op)
            if op_cls not in _CMP_OP_SYMBOLS:
                raise ValueError(f"Comparador no soportado: {op_cls}")
            right = _convert_python_ast(comp)
            comp_node = BinOpNode(_CMP_OP_SYMBOLS[op_cls], prev, right)
            combined = comp_node if combined is None else BinOpNode("and", combined, comp_node)
            prev = right
        return combined if combined is not None else left
    if isinstance(node, ast.Call):
        func_name = _attr_to_str(node.func)
        if func_name == "_mt_matrix_literal" and len(node.args) == 1 and isinstance(node.args[0], ast.List):
            rows = [_convert_python_ast(elt) for elt in node.args[0].elts]
            return MatrixLiteralNode(rows)
        args = [_convert_python_ast(arg) for arg in node.args]
        keywords: list[tuple[str, ASTNode]] = []
        for kw in node.keywords:
            if kw.arg is None:
                raise ValueError("No se soportan kwargs tipo ** en MathTeX AST.")
            keywords.append((kw.arg, _convert_python_ast(kw.value)))
        if func_name in {"_oct_get1", "_oct_get2", "_oct_get_any"} and args:
            base = args[0]
            indices = args[1:]
            if isinstance(base, NumberNode) and isinstance(base.value, str):
                base = SymbolNode(base.value)
            return IndexNode(base, indices)
        return CallNode(func_name, args, keywords or None)
    if isinstance(node, ast.Subscript):
        base = _convert_python_ast(node.value)
        if isinstance(node.slice, ast.Tuple):
            indices = [_convert_python_ast(elt) for elt in node.slice.elts]
        else:
            indices = [_convert_python_ast(node.slice)]
        return IndexNode(base, indices)
    raise ValueError(f"Tipo de nodo Python AST no soportado: {ast.dump(node)}")


def build_ast_from_python_expr(expr_py: str) -> ASTNode:
    """Parses a Python expression and la devuelve como AST MathTeX."""
    parsed = ast.parse(expr_py, mode="eval")
    return _convert_python_ast(parsed.body)


def ast_to_python(node: ASTNode) -> str:
    from ast_codegen import ast_to_python as _impl

    return _impl(node)


def pass_constant_folding(node: ASTNode, env: dict[str, Any]) -> tuple[ASTNode, bool, str]:
    from ast_optimize import pass_constant_folding as _impl

    return _impl(node, env)


def pass_simplify(node: ASTNode, env: dict[str, Any]) -> tuple[ASTNode, bool, str]:
    from ast_optimize import pass_simplify as _impl

    return _impl(node, env)


def pass_cse(node: ASTNode, env: dict[str, Any]) -> tuple[ASTNode, bool, str]:
    from ast_optimize import pass_cse as _impl

    return _impl(node, env)


def optimize_ast(node: ASTNode, env: dict[str, Any]) -> ASTNode:
    from ast_optimize import optimize_ast as _impl

    return _impl(node, env)
