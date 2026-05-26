from __future__ import annotations

import math
from typing import Any

import sympy as sp

from ast_codegen import ast_to_python
from mathtex_ast import (
    ASTNode,
    AssignNode,
    BinOpNode,
    BlockNode,
    CallNode,
    ExprStmtNode,
    IndexAssignNode,
    IndexNode,
    ListLiteralNode,
    MatrixLiteralNode,
    NumberNode,
    RangeNode,
    SliceNode,
    SymbolNode,
    TupleLiteralNode,
    UnaryOpNode,
    VectorLiteralNode,
)


_CONST_CALL_FUNCS = {
    "abs": abs,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "exp": math.exp,
    "log": math.log,
    "sqrt": math.sqrt,
}

_LITERAL_NODE_TYPES = (MatrixLiteralNode, TupleLiteralNode, VectorLiteralNode, ListLiteralNode)


def _rebuild_literal(node: ASTNode, values: list[ASTNode]) -> ASTNode:
    if isinstance(node, MatrixLiteralNode):
        return MatrixLiteralNode(values)
    if isinstance(node, TupleLiteralNode):
        return TupleLiteralNode(values)
    if isinstance(node, VectorLiteralNode):
        return VectorLiteralNode(values)
    if isinstance(node, ListLiteralNode):
        return ListLiteralNode(values)
    raise TypeError(f"Unsupported literal node: {type(node)}")


def _is_number_node(node: ASTNode) -> bool:
    return isinstance(node, NumberNode) and isinstance(
        node.value, (int, float, complex, sp.Number)
    )


def _number_value(node: ASTNode) -> Any:
    if isinstance(node, NumberNode):
        return node.value
    raise TypeError(f"Expected NumberNode, got {type(node)}")


def _expr_key(node: ASTNode) -> tuple:
    if isinstance(node, NumberNode):
        return ("num", repr(node.value))
    if isinstance(node, SymbolNode):
        return ("sym", node.name)
    if isinstance(node, UnaryOpNode):
        return ("un", node.op, _expr_key(node.operand))
    if isinstance(node, BinOpNode):
        return ("bin", node.op, _expr_key(node.left), _expr_key(node.right))
    if isinstance(node, CallNode):
        kw_part = ()
        if node.keywords:
            kw_part = tuple((k, _expr_key(v)) for k, v in node.keywords)
        return ("call", node.func_name, tuple(_expr_key(arg) for arg in node.args), kw_part)
    if isinstance(node, IndexNode):
        return ("idx", _expr_key(node.base), tuple(_expr_key(idx) for idx in node.indices))
    if isinstance(node, RangeNode):
        return (
            "range",
            _expr_key(node.start) if node.start is not None else None,
            _expr_key(node.step) if node.step is not None else None,
            _expr_key(node.end) if node.end is not None else None,
        )
    if isinstance(node, SliceNode):
        return ("slice", _expr_key(node.value))
    if isinstance(node, MatrixLiteralNode):
        return ("mat", tuple(_expr_key(v) for v in node.values))
    if isinstance(node, TupleLiteralNode):
        return ("tuple", tuple(_expr_key(v) for v in node.values))
    if isinstance(node, VectorLiteralNode):
        return ("vec", tuple(_expr_key(v) for v in node.values))
    if isinstance(node, ListLiteralNode):
        return ("list", tuple(_expr_key(v) for v in node.values))
    if isinstance(node, ExprStmtNode):
        return ("expr", _expr_key(node.expr))
    if isinstance(node, IndexAssignNode):
        return (
            "idx_assign",
            _expr_key(node.target),
            tuple(_expr_key(idx) for idx in node.indices),
            _expr_key(node.expr),
        )
    if isinstance(node, AssignNode):
        return ("assign", _expr_key(node.target), _expr_key(node.expr))
    if isinstance(node, BlockNode):
        return ("block", tuple(_expr_key(st) for st in node.statements))
    return ("other", repr(node))


def _expr_cost(node: ASTNode) -> int:
    if isinstance(node, NumberNode):
        return 1
    if isinstance(node, SymbolNode):
        return 1
    if isinstance(node, (MatrixLiteralNode, TupleLiteralNode, VectorLiteralNode, ListLiteralNode)):
        return 1 + sum(_expr_cost(v) for v in node.values)
    if isinstance(node, UnaryOpNode):
        return 1 + _expr_cost(node.operand)
    if isinstance(node, BinOpNode):
        return 1 + _expr_cost(node.left) + _expr_cost(node.right)
    if isinstance(node, CallNode):
        return 2 + sum(_expr_cost(arg) for arg in node.args)
    if isinstance(node, IndexNode):
        return 1 + _expr_cost(node.base) + sum(_expr_cost(i) for i in node.indices)
    if isinstance(node, RangeNode):
        return (
            1
            + (_expr_cost(node.start) if node.start is not None else 0)
            + (_expr_cost(node.step) if node.step is not None else 0)
            + (_expr_cost(node.end) if node.end is not None else 0)
        )
    if isinstance(node, SliceNode):
        return 1 + _expr_cost(node.value)
    if isinstance(node, IndexAssignNode):
        return _expr_cost(node.expr) + sum(_expr_cost(idx) for idx in node.indices)
    if isinstance(node, ExprStmtNode):
        return _expr_cost(node.expr)
    if isinstance(node, AssignNode):
        return _expr_cost(node.expr)
    if isinstance(node, BlockNode):
        return sum(_expr_cost(st) for st in node.statements)
    return 1


def pass_constant_folding(node: ASTNode, env: dict[str, Any]) -> tuple[ASTNode, bool, str]:
    changed = False

    def fold(n: ASTNode) -> ASTNode:
        nonlocal changed
        if isinstance(n, BlockNode):
            new_stmts = [fold(st) for st in n.statements]
            if any(s1 is not s2 for s1, s2 in zip(n.statements, new_stmts)):
                changed = True
                return BlockNode(new_stmts)
            return n
        if isinstance(n, AssignNode):
            new_expr = fold(n.expr)
            if new_expr is not n.expr:
                changed = True
                return AssignNode(n.target, new_expr)
            return n
        if isinstance(n, IndexAssignNode):
            new_expr = fold(n.expr)
            new_indices = [fold(idx) for idx in n.indices]
            if new_expr is not n.expr or any(i1 is not i2 for i1, i2 in zip(n.indices, new_indices)):
                changed = True
                return IndexAssignNode(n.target, new_indices, new_expr)
            return n
        if isinstance(n, ExprStmtNode):
            new_expr = fold(n.expr)
            if new_expr is not n.expr:
                changed = True
                return ExprStmtNode(new_expr)
            return n
        if isinstance(n, UnaryOpNode):
            operand = fold(n.operand)
            if operand is not n.operand:
                changed = True
                n = UnaryOpNode(n.op, operand)
            if _is_number_node(n.operand):
                try:
                    if n.op.strip() == "+":
                        val = +_number_value(n.operand)
                    elif n.op.strip() == "-":
                        val = -_number_value(n.operand)
                    elif n.op.strip() == "~":
                        val = ~int(_number_value(n.operand))
                    elif n.op.startswith("not"):
                        val = not _number_value(n.operand)
                    else:
                        return n
                    changed = True
                    return NumberNode(val)
                except Exception:
                    return n
            return n
        if isinstance(n, BinOpNode):
            left = fold(n.left)
            right = fold(n.right)
            if left is not n.left or right is not n.right:
                n = BinOpNode(n.op, left, right)
                changed = True
            if _is_number_node(left) and _is_number_node(right) and n.op in {"+", "-", "*", "/", "**", "//", "%"}:
                try:
                    lval = _number_value(left)
                    rval = _number_value(right)
                    if n.op == "+":
                        val = lval + rval
                    elif n.op == "-":
                        val = lval - rval
                    elif n.op == "*":
                        val = lval * rval
                    elif n.op == "/":
                        val = lval / rval
                    elif n.op == "//":
                        val = lval // rval
                    elif n.op == "%":
                        val = lval % rval
                    else:
                        val = lval ** rval
                    changed = True
                    return NumberNode(val)
                except Exception:
                    return n
            return n
        if isinstance(n, CallNode):
            new_args = [fold(arg) for arg in n.args]
            if any(a1 is not a2 for a1, a2 in zip(n.args, new_args)):
                n = CallNode(n.func_name, new_args, n.keywords)
                changed = True
            if n.keywords:
                return n
            if n.func_name in _CONST_CALL_FUNCS and all(_is_number_node(a) for a in n.args):
                try:
                    values = [_number_value(a) for a in n.args]
                    val = _CONST_CALL_FUNCS[n.func_name](*values)
                    changed = True
                    return NumberNode(val)
                except Exception:
                    return n
            return n
        if isinstance(n, IndexNode):
            base_new = fold(n.base)
            idx_new = [fold(i) for i in n.indices]
            if base_new is not n.base or any(i1 is not i2 for i1, i2 in zip(n.indices, idx_new)):
                changed = True
                return IndexNode(base_new, idx_new)
            return n
        if isinstance(n, SliceNode):
            value_new = fold(n.value)
            if value_new is not n.value:
                changed = True
                return SliceNode(value_new)
            return n
        if isinstance(n, RangeNode):
            start_new = fold(n.start) if n.start is not None else None
            step_new = fold(n.step) if n.step is not None else None
            end_new = fold(n.end) if n.end is not None else None
            if start_new is not n.start or step_new is not n.step or end_new is not n.end:
                changed = True
                return RangeNode(start_new, step_new, end_new)
            return n
        if isinstance(n, _LITERAL_NODE_TYPES):
            vals_new = [fold(v) for v in n.values]
            if any(v1 is not v2 for v1, v2 in zip(n.values, vals_new)):
                changed = True
                return _rebuild_literal(n, vals_new)
            return n
        return n

    result = fold(node)
    return result, changed, "constant_folding" if changed else ""


def pass_simplify(node: ASTNode, env: dict[str, Any]) -> tuple[ASTNode, bool, str]:
    changed = False

    def is_zero(n: ASTNode) -> bool:
        return _is_number_node(n) and _number_value(n) == 0

    def is_one(n: ASTNode) -> bool:
        return _is_number_node(n) and _number_value(n) == 1

    def simplify(n: ASTNode) -> ASTNode:
        nonlocal changed
        if isinstance(n, BlockNode):
            new_stmts = [simplify(st) for st in n.statements]
            if any(s1 is not s2 for s1, s2 in zip(n.statements, new_stmts)):
                changed = True
                return BlockNode(new_stmts)
            return n
        if isinstance(n, AssignNode):
            new_expr = simplify(n.expr)
            if new_expr is not n.expr:
                changed = True
                return AssignNode(n.target, new_expr)
            return n
        if isinstance(n, IndexAssignNode):
            new_expr = simplify(n.expr)
            new_indices = [simplify(idx) for idx in n.indices]
            if new_expr is not n.expr or any(i1 is not i2 for i1, i2 in zip(n.indices, new_indices)):
                changed = True
                return IndexAssignNode(n.target, new_indices, new_expr)
            return n
        if isinstance(n, ExprStmtNode):
            new_expr = simplify(n.expr)
            if new_expr is not n.expr:
                changed = True
                return ExprStmtNode(new_expr)
            return n
        if isinstance(n, UnaryOpNode):
            operand = simplify(n.operand)
            if operand is not n.operand:
                n = UnaryOpNode(n.op, operand)
                changed = True
            if n.op.strip() == "-" and isinstance(operand, UnaryOpNode) and operand.op.strip() == "-":
                changed = True
                return operand.operand
            return n
        if isinstance(n, BinOpNode):
            left = simplify(n.left)
            right = simplify(n.right)
            if left is not n.left or right is not n.right:
                n = BinOpNode(n.op, left, right)
                changed = True
            op = n.op
            if op == "+":
                if is_zero(right):
                    changed = True
                    return left
                if is_zero(left):
                    changed = True
                    return right
            if op == "-":
                if is_zero(right):
                    changed = True
                    return left
            if op == "*":
                if is_one(right):
                    changed = True
                    return left
                if is_one(left):
                    changed = True
                    return right
                if is_zero(right):
                    changed = True
                    return NumberNode(0)
                if is_zero(left):
                    changed = True
                    return NumberNode(0)
            if op == "/":
                if is_one(right):
                    changed = True
                    return left
            if op == "**":
                if is_one(right):
                    changed = True
                    return left
                if is_zero(right) and isinstance(left, (NumberNode, SymbolNode)):
                    changed = True
                    return NumberNode(1)
            return n
        if isinstance(n, CallNode):
            new_args = [simplify(arg) for arg in n.args]
            if any(a1 is not a2 for a1, a2 in zip(n.args, new_args)):
                changed = True
                return CallNode(n.func_name, new_args, n.keywords)
            return n
        if isinstance(n, IndexNode):
            base_new = simplify(n.base)
            idx_new = [simplify(i) for i in n.indices]
            if base_new is not n.base or any(i1 is not i2 for i1, i2 in zip(n.indices, idx_new)):
                changed = True
                return IndexNode(base_new, idx_new)
            return n
        if isinstance(n, SliceNode):
            value_new = simplify(n.value)
            if value_new is not n.value:
                changed = True
                return SliceNode(value_new)
            return n
        if isinstance(n, RangeNode):
            start_new = simplify(n.start) if n.start is not None else None
            step_new = simplify(n.step) if n.step is not None else None
            end_new = simplify(n.end) if n.end is not None else None
            if start_new is not n.start or step_new is not n.step or end_new is not n.end:
                changed = True
                return RangeNode(start_new, step_new, end_new)
            return n
        if isinstance(n, _LITERAL_NODE_TYPES):
            vals_new = [simplify(v) for v in n.values]
            if any(v1 is not v2 for v1, v2 in zip(n.values, vals_new)):
                changed = True
                return _rebuild_literal(n, vals_new)
            return n
        return n

    result = simplify(node)
    return result, changed, "algebraic_simplify" if changed else ""


def pass_cse(node: ASTNode, env: dict[str, Any]) -> tuple[ASTNode, bool, str]:
    temp_counter = 0

    def fresh_temp() -> str:
        nonlocal temp_counter
        temp_counter += 1
        name = f"_t{temp_counter}"
        while name in env:
            temp_counter += 1
            name = f"_t{temp_counter}"
        return name

    def is_costly(n: ASTNode) -> bool:
        if isinstance(n, BinOpNode) and n.op in {"*", "**", "/", "@", "%", "//"}:
            return True
        if isinstance(n, CallNode):
            return n.func_name not in {"abs", "int", "float", "complex"}
        return False

    def cse_expr(expr: ASTNode) -> tuple[ASTNode, list[AssignNode], bool]:
        counts: dict[tuple, int] = {}
        samples: dict[tuple, ASTNode] = {}

        def collect(n: ASTNode) -> None:
            key = _expr_key(n)
            counts[key] = counts.get(key, 0) + 1
            samples.setdefault(key, n)
            if isinstance(n, UnaryOpNode):
                collect(n.operand)
            elif isinstance(n, BinOpNode):
                collect(n.left)
                collect(n.right)
            elif isinstance(n, CallNode):
                for arg in n.args:
                    collect(arg)
            elif isinstance(n, IndexNode):
                collect(n.base)
                for idx in n.indices:
                    collect(idx)
            elif isinstance(n, SliceNode):
                collect(n.value)
            elif isinstance(n, RangeNode):
                if n.start is not None:
                    collect(n.start)
                if n.step is not None:
                    collect(n.step)
                if n.end is not None:
                    collect(n.end)
            elif isinstance(n, _LITERAL_NODE_TYPES):
                for v in n.values:
                    collect(v)

        collect(expr)

        candidates = [
            (key, samples[key])
            for key, count in counts.items()
            if count > 1 and is_costly(samples[key])
        ]
        if not candidates:
            return expr, [], False
        candidates.sort(key=lambda item: -_expr_cost(item[1]))

        key_to_temp: dict[tuple, str] = {}
        assignments: list[AssignNode] = []

        def replace(n: ASTNode, allow_root_replace: bool = True) -> ASTNode:
            key = _expr_key(n)
            root_replace = allow_root_replace and key in key_to_temp

            if root_replace:
                return SymbolNode(key_to_temp[key])

            if isinstance(n, UnaryOpNode):
                operand = replace(n.operand, True)
                if operand is not n.operand:
                    return UnaryOpNode(n.op, operand)
                return n
            if isinstance(n, BinOpNode):
                left = replace(n.left, True)
                right = replace(n.right, True)
                if left is not n.left or right is not n.right:
                    return BinOpNode(n.op, left, right)
                return n
            if isinstance(n, CallNode):
                new_args = [replace(arg, True) for arg in n.args]
                if any(a1 is not a2 for a1, a2 in zip(n.args, new_args)):
                    return CallNode(n.func_name, new_args, n.keywords)
                return n
            if isinstance(n, IndexNode):
                base_new = replace(n.base, True)
                idx_new = [replace(i, True) for i in n.indices]
                if base_new is not n.base or any(i1 is not i2 for i1, i2 in zip(n.indices, idx_new)):
                    return IndexNode(base_new, idx_new)
                return n
            if isinstance(n, SliceNode):
                value_new = replace(n.value, True)
                if value_new is not n.value:
                    return SliceNode(value_new)
                return n
            if isinstance(n, RangeNode):
                start_new = replace(n.start, True) if n.start is not None else None
                step_new = replace(n.step, True) if n.step is not None else None
                end_new = replace(n.end, True) if n.end is not None else None
                if start_new is not n.start or step_new is not n.step or end_new is not n.end:
                    return RangeNode(start_new, step_new, end_new)
                return n
            if isinstance(n, _LITERAL_NODE_TYPES):
                vals_new = [replace(v, True) for v in n.values]
                if any(v1 is not v2 for v1, v2 in zip(n.values, vals_new)):
                    return _rebuild_literal(n, vals_new)
                return n
            return n

        for key, sample in candidates:
            temp_name = fresh_temp()
            key_to_temp[key] = temp_name
            rhs = replace(sample, allow_root_replace=False)
            assignments.append(AssignNode(SymbolNode(temp_name), rhs))

        new_expr = replace(expr, allow_root_replace=True)
        return new_expr, assignments, True

    if isinstance(node, AssignNode):
        expr_opt, temps, applied = cse_expr(node.expr)
        if applied and temps:
            return BlockNode(temps + [AssignNode(node.target, expr_opt)]), True, "cse"
        if applied and expr_opt is not node.expr:
            return AssignNode(node.target, expr_opt), True, "cse"
        return node, False, ""

    if isinstance(node, IndexAssignNode):
        expr_opt, temps, applied = cse_expr(node.expr)
        if applied and temps:
            return BlockNode(temps + [IndexAssignNode(node.target, node.indices, expr_opt)]), True, "cse"
        if applied and expr_opt is not node.expr:
            return IndexAssignNode(node.target, node.indices, expr_opt), True, "cse"
        return node, False, ""

    if isinstance(node, ExprStmtNode):
        expr_opt, temps, applied = cse_expr(node.expr)
        if applied and temps:
            return BlockNode(temps + [ExprStmtNode(expr_opt)]), True, "cse"
        if applied and expr_opt is not node.expr:
            return ExprStmtNode(expr_opt), True, "cse"
        return node, False, ""

    if isinstance(node, BlockNode):
        new_stmts: list[ASTNode] = []
        block_changed = False
        for st in node.statements:
            st_new, st_changed, _ = pass_cse(st, env)
            new_stmts.append(st_new)
            block_changed = block_changed or st_changed
        if block_changed:
            return BlockNode(new_stmts), True, "cse"
        return node, False, ""

    return node, False, ""


def optimize_ast(node: ASTNode, env: dict[str, Any]) -> ASTNode:
    debug = bool(env.get("_opt_debug"))
    passes = [pass_constant_folding, pass_simplify, pass_cse, pass_constant_folding]
    current = node
    for iteration in range(5):
        any_change = False
        for func in passes:
            new_node, changed, name = func(current, env)
            if changed:
                any_change = True
                if debug and name:
                    print(f"[opt] pass {name} applied (iter {iteration + 1})")
            current = new_node
        if not any_change:
            break
    if debug:
        try:
            before_py = ast_to_python(node)
            after_py = ast_to_python(current)
            print(f"[opt] before: {before_py}")
            print(f"[opt] after : {after_py}")
        except Exception:
            print("[opt] debug: no se pudo imprimir AST optimizado.")
    return current
