from __future__ import annotations

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


def ast_to_python(node: ASTNode) -> str:
    if isinstance(node, NumberNode):
        return repr(node.value)
    if isinstance(node, SymbolNode):
        return node.name
    if isinstance(node, TupleLiteralNode):
        inner = ", ".join(ast_to_python(val) for val in node.values)
        if len(node.values) == 1:
            inner += ","
        return f"({inner})"
    if isinstance(node, VectorLiteralNode):
        inner = ", ".join(ast_to_python(val) for val in node.values)
        return f"Matrix([[{inner}]])"
    if isinstance(node, ListLiteralNode):
        inner = ", ".join(ast_to_python(val) for val in node.values)
        return f"[{inner}]"
    if isinstance(node, MatrixLiteralNode):
        rows: list[str] = []
        for val in node.values:
            if isinstance(val, (VectorLiteralNode, ListLiteralNode, MatrixLiteralNode)):
                row_inner = ", ".join(ast_to_python(item) for item in val.values)
                rows.append(f"[{row_inner}]")
            else:
                rows.append(f"[{ast_to_python(val)}]")
        inner = ", ".join(rows)
        return f"Matrix([{inner}])"
    if isinstance(node, UnaryOpNode):
        return f"({node.op}{ast_to_python(node.operand)})"
    if isinstance(node, BinOpNode):
        left = ast_to_python(node.left)
        right = ast_to_python(node.right)
        return f"({left} {node.op} {right})"
    if isinstance(node, IndexNode):
        base_code = ast_to_python(node.base)
        if isinstance(node.base, SymbolNode):
            base_code = repr(node.base.name)
        indices_code = [ast_to_python(idx) for idx in node.indices]
        if len(indices_code) == 1:
            return f"_oct_get_any({base_code}, {indices_code[0]})"
        if len(indices_code) == 2:
            return f"_oct_get2({base_code}, {indices_code[0]}, {indices_code[1]})"
        joined = ", ".join(indices_code)
        return f"_oct_get_any({base_code}, {joined})"
    if isinstance(node, RangeNode):
        if node.start is None and node.step is None and node.end is None:
            return "':'"
        if node.start is None or node.end is None:
            raise ValueError(f"Rango incompleto no soportado: {node}")
        start = ast_to_python(node.start)
        end = ast_to_python(node.end)
        if node.step is None:
            return f"_oct_span({start}, None, {end})"
        step = ast_to_python(node.step)
        return f"_oct_span({start}, {step}, {end})"
    if isinstance(node, SliceNode):
        return ast_to_python(node.value)
    if isinstance(node, CallNode):
        def _arg_to_python(arg: ASTNode) -> str:
            if node.func_name == "Matrix" and isinstance(arg, (VectorLiteralNode, ListLiteralNode)):
                inner = ", ".join(ast_to_python(val) for val in arg.values)
                return f"[{inner}]"
            return ast_to_python(arg)

        args_code = [_arg_to_python(arg) for arg in node.args]
        if node.keywords:
            for kw_name, kw_val in node.keywords:
                args_code.append(f"{kw_name}={ast_to_python(kw_val)}")
        joined = ", ".join(args_code)
        return f"{node.func_name}({joined})"
    if isinstance(node, IndexAssignNode):
        value_code = ast_to_python(node.expr)
        idx_code = [ast_to_python(idx) for idx in node.indices]
        target = repr(node.target.name)
        has_range = any(isinstance(idx.value, RangeNode) for idx in node.indices)
        if len(idx_code) == 1:
            if has_range:
                return f"_oct_set_slice({target}, {idx_code[0]}, 1, {value_code})"
            return f"_oct_set1({target}, {idx_code[0]}, {value_code})"
        if len(idx_code) == 2:
            if has_range:
                return f"_oct_set_slice({target}, {idx_code[0]}, {idx_code[1]}, {value_code})"
            return f"_oct_set2({target}, {idx_code[0]}, {idx_code[1]}, {value_code})"
        raise ValueError(f"No se soportan {len(idx_code)} indices en IndexAssignNode.")
    if isinstance(node, AssignNode):
        return f"{ast_to_python(node.target)} = {ast_to_python(node.expr)}"
    if isinstance(node, ExprStmtNode):
        return ast_to_python(node.expr)
    if isinstance(node, BlockNode):
        return "\n".join(ast_to_python(stmt) for stmt in node.statements)
    raise ValueError(f"No se puede convertir el nodo a Python: {node}")
