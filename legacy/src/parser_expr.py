from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any

import sympy as sp
from sympy import Function, symbols
from sympy.matrices import MatrixBase
from sympy.parsing.sympy_parser import parse_expr

from diagnostics import find_expression_issue, make_parse_error, parse_error_from_syntax_error
from mathtex_ast import ASTNode, build_ast_from_python_expr
from parser_config import ExprParserConfig
from parser_common import (
    _has_disabled_apostrophe_operator,
    _is_apostrophe_operator,
    _replace_cmd_outside_strings,
    _split_top_level,
)
from parsers import ParserContext, normalize_matrix_expr


@dataclass(frozen=True)
class _ExprToken:
    kind: str
    value: str


@dataclass(frozen=True)
class _ExprNode:
    kind: str
    value: Any
    children: tuple | None = None


def _tokenize_mathtex_expr(expr: str) -> list[_ExprToken]:
    tokens: list[_ExprToken] = []
    i = 0
    n = len(expr)

    def _push(kind: str, value: str) -> None:
        tokens.append(_ExprToken(kind, value))

    def _consume_string(quote: str, start: int) -> int:
        idx = start + 1
        escape = False
        while idx < n:
            ch = expr[idx]
            if escape:
                escape = False
                idx += 1
                continue
            if ch == "\\":
                escape = True
                idx += 1
                continue
            if ch == quote:
                idx += 1
                return idx
            idx += 1
        return idx

    def _consume_group(start: int, open_ch: str, close_ch: str) -> int:
        idx = start
        depth = 0
        while idx < n:
            ch = expr[idx]
            if ch in {"'", '"'}:
                if ch == "'" and _is_apostrophe_operator(expr, idx):
                    idx += 1
                    continue
                idx = _consume_string(ch, idx)
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return idx + 1
            idx += 1
        return idx

    def _can_end_operand_token(token: _ExprToken | None) -> bool:
        if token is None:
            return False
        if token.kind in {"NUMBER", "IDENT", "ATOM", "RPAREN"}:
            return True
        return token.kind == "OP" and token.value in {"'", ".'"}

    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "." and i + 1 < n and expr[i + 1] in {"*", "/", "^", "+", "-", "'"}:
            op = f".{expr[i + 1]}"
            if op in {".+", ".-"}:
                op = op[1]
            _push("OP", op)
            i += 2
            continue
        if ch == "'" and _can_end_operand_token(tokens[-1] if tokens else None):
            _push("OP", ch)
            i += 1
            continue
        if ch in {"'", '"'}:
            end = _consume_string(ch, i)
            _push("STRING", expr[i:end])
            i = end
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            start = i
            if ch == ".":
                i += 1
                while i < n and expr[i].isdigit():
                    i += 1
            else:
                while i < n and expr[i].isdigit():
                    i += 1
                if i < n and expr[i] == "." and i + 1 < n and expr[i + 1].isdigit():
                    i += 1
                    while i < n and expr[i].isdigit():
                        i += 1
            if i < n and expr[i] in {"e", "E"}:
                j = i + 1
                if j < n and expr[j] in {"+", "-"}:
                    j += 1
                if j < n and expr[j].isdigit():
                    i = j + 1
                    while i < n and expr[i].isdigit():
                        i += 1
            _push("NUMBER", expr[start:i])
            continue
        if ch in {"[", "{"}:
            close_ch = "]" if ch == "[" else "}"
            end = _consume_group(i, ch, close_ch)
            _push("ATOM", expr[i:end])
            i = end
            continue
        if ch.isalpha() or ch == "_" or ch == "\\":
            start = i
            if ch == "\\":
                i += 1
                start = i
            if i < n and (expr[i].isalpha() or expr[i] == "_"):
                i += 1
                while i < n and (expr[i].isalnum() or expr[i] == "_"):
                    i += 1
                ident = expr[start:i]
                while i + 1 < n and expr[i] == "." and (expr[i + 1].isalpha() or expr[i + 1] == "_"):
                    i += 1
                    seg_start = i
                    i += 1
                    while i < n and (expr[i].isalnum() or expr[i] == "_"):
                        i += 1
                    ident += "." + expr[seg_start:i]
                _push("IDENT", ident)
                continue
            _push("IDENT", expr[start:i])
            continue
        if ch in {"(", ")"}:
            _push("LPAREN" if ch == "(" else "RPAREN", ch)
            i += 1
            continue
        if ch == ",":
            _push("COMMA", ch)
            i += 1
            continue
        if ch == "*" and i + 1 < n and expr[i + 1] == "*":
            _push("OP", "**")
            i += 2
            continue
        if ch == "/" and i + 1 < n and expr[i + 1] == "/":
            _push("OP", "//")
            i += 2
            continue
        if ch in {"+", "-", "*", "/", "^"}:
            _push("OP", ch)
            i += 1
            continue
        _push("ATOM", ch)
        i += 1
    return tokens


def _insert_implicit_mul(tokens: list[_ExprToken]) -> list[_ExprToken]:
    def _is_atom(tok: _ExprToken) -> bool:
        return tok.kind in {"NUMBER", "IDENT", "STRING", "ATOM", "RPAREN"}

    def _is_start(tok: _ExprToken) -> bool:
        return tok.kind in {"NUMBER", "IDENT", "STRING", "ATOM", "LPAREN"}

    out: list[_ExprToken] = []
    for tok in tokens:
        if out:
            prev = out[-1]
            if _is_atom(prev) and _is_start(tok):
                if not (prev.kind == "IDENT" and tok.kind == "LPAREN"):
                    out.append(_ExprToken("OP", "*"))
        out.append(tok)
    return out


_OP_BINDING_POWER = {
    "+": (10, 11),
    "-": (10, 11),
    "*": (20, 21),
    "/": (20, 21),
    ".*": (20, 21),
    "./": (20, 21),
    "^": (30, 29),
    "**": (30, 29),
    ".^": (30, 29),
    "//": (20, 21),
}


class _MathtexExprParser:
    def __init__(self, tokens: list[_ExprToken]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> _ExprToken | None:
        if self.pos >= len(self.tokens):
            return None
        return self.tokens[self.pos]

    def _advance(self) -> _ExprToken:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, kind: str, value: str | None = None) -> None:
        tok = self._peek()
        if tok is None or tok.kind != kind or (value is not None and tok.value != value):
            raise SyntaxError(f"Token esperado {kind} {value or ''}".strip())
        self._advance()

    def parse(self) -> _ExprNode:
        node = self._parse_expr(0)
        if self._peek() is not None:
            raise SyntaxError("Invalid expression (remaining tokens).")
        return node

    def _parse_expr(self, min_bp: int) -> _ExprNode:
        node = self._parse_prefix()
        while True:
            tok = self._peek()
            if tok is None or tok.kind != "OP":
                break
            if tok.value not in _OP_BINDING_POWER:
                break
            lbp, rbp = _OP_BINDING_POWER[tok.value]
            if lbp < min_bp:
                break
            op = tok.value
            self._advance()
            rhs = self._parse_expr(rbp)
            node = _ExprNode("bin", op, (node, rhs))
        return node

    def _parse_prefix(self) -> _ExprNode:
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.value in {"+", "-"}:
            op = tok.value
            self._advance()
            rhs = self._parse_expr(25)
            return _ExprNode("unary", op, (rhs,))
        return self._parse_primary()

    def _parse_primary(self) -> _ExprNode:
        tok = self._peek()
        if tok is None:
            raise SyntaxError("Incomplete expression.")
        if tok.kind == "LPAREN":
            self._advance()
            node = self._parse_expr(0)
            self._expect("RPAREN")
            node = _ExprNode("group", None, (node,))
        elif tok.kind in {"NUMBER", "IDENT", "STRING", "ATOM"}:
            node = _ExprNode("atom", tok.value)
            self._advance()
        else:
            raise SyntaxError(f"Unexpected token: {tok.kind} {tok.value}")

        while True:
            next_tok = self._peek()
            if next_tok is None or next_tok.kind != "LPAREN":
                break
            self._advance()
            args: list[_ExprNode] = []
            if self._peek() is not None and self._peek().kind != "RPAREN":
                while True:
                    args.append(self._parse_expr(0))
                    if self._peek() is not None and self._peek().kind == "COMMA":
                        self._advance()
                        continue
                    break
            self._expect("RPAREN")
            node = _ExprNode("call", None, (node, tuple(args)))
        while True:
            next_tok = self._peek()
            if next_tok is None or next_tok.kind != "OP" or next_tok.value not in {"'", ".'"}:
                break
            self._advance()
            node = _ExprNode("postfix", next_tok.value, (node,))
        return node


def _expr_node_to_python(node: _ExprNode) -> str:
    if node.kind == "atom":
        return str(node.value)
    if node.kind == "group":
        inner = _expr_node_to_python(node.children[0])
        return f"({inner})"
    if node.kind == "call":
        func_node, args = node.children
        func_text = _expr_node_to_python(func_node)
        args_text = ", ".join(_expr_node_to_python(arg) for arg in args)
        return f"{func_text}({args_text})"
    if node.kind == "postfix":
        operand = _expr_node_to_python(node.children[0])
        if node.value == "'":
            raise SyntaxError("operator ' is not supported for matrices; use \\T(...) for transpose")
        if node.value == ".'":
            return f"_mt_transpose({operand})"
        raise ValueError(f"Unsupported postfix operator: {node.value}")
    if node.kind == "unary":
        op = node.value
        rhs = _expr_node_to_python(node.children[0])
        return f"({op}{rhs})"
    if node.kind == "bin":
        op = node.value
        left = _expr_node_to_python(node.children[0])
        right = _expr_node_to_python(node.children[1])
        if op == ".*":
            return f"_mt_ew_mul({left}, {right})"
        if op == "./":
            return f"_mt_ew_div({left}, {right})"
        if op == ".^":
            return f"_mt_ew_pow({left}, {right})"
        if op == "*":
            return f"_mt_mul({left}, {right})"
        if op == "/":
            return f"_mt_div({left}, {right})"
        if op in {"^", "**"}:
            return f"_mt_pow({left}, {right})"
        if op == "//":
            return f"({left} // {right})"
        return f"({left} {op} {right})"
    raise ValueError(f"Unsupported expression node: {node.kind}")


def _mathtex_infix_to_python(expr: str, implicit_mul: bool) -> str:
    try:
        tokens = _tokenize_mathtex_expr(expr)
        if implicit_mul:
            tokens = _insert_implicit_mul(tokens)
        parser = _MathtexExprParser(tokens)
        node = parser.parse()
        return _expr_node_to_python(node)
    except Exception:
        return expr


def _contains_dot_ops(expr: str) -> bool:
    return bool(re.search(r"\.(?:\*|/|\^|\+|-|')", expr))


def _protect_env_atoms(expr: str) -> tuple[str, dict[str, str]]:
    """Protege accesos env_ast[...] con atributos para el parser de MathTeX."""
    if "env_ast[" not in expr:
        return expr, {}

    placeholders: dict[str, str] = {}
    out: list[str] = []
    i = 0
    counter = 0
    in_str = ""
    escape = False

    while i < len(expr):
        ch = expr[i]
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = ""
            i += 1
            continue
        if ch in {"'", '"'}:
            in_str = ch
            out.append(ch)
            i += 1
            continue
        if expr.startswith("env_ast[", i):
            start = i
            i += len("env_ast[")
            depth = 1
            while i < len(expr) and depth > 0:
                c = expr[i]
                if c in {"'", '"'}:
                    quote = c
                    i += 1
                    while i < len(expr):
                        cc = expr[i]
                        if cc == "\\":
                            i += 2
                            continue
                        if cc == quote:
                            i += 1
                            break
                        i += 1
                    continue
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                i += 1

            while i < len(expr) and expr[i] == ".":
                j = i + 1
                if j < len(expr) and (expr[j].isalpha() or expr[j] == "_"):
                    j += 1
                    while j < len(expr) and (expr[j].isalnum() or expr[j] == "_"):
                        j += 1
                    i = j
                    if i < len(expr) and expr[i] == "(":
                        depth = 1
                        i += 1
                        while i < len(expr) and depth > 0:
                            c = expr[i]
                            if c in {"'", '"'}:
                                quote = c
                                i += 1
                                while i < len(expr):
                                    cc = expr[i]
                                    if cc == "\\":
                                        i += 2
                                        continue
                                    if cc == quote:
                                        i += 1
                                        break
                                    i += 1
                                continue
                            if c == "(":
                                depth += 1
                            elif c == ")":
                                depth -= 1
                            i += 1
                    continue
                break

            atom = expr[start:i]
            token = f"__mt_atom_{counter}__"
            counter += 1
            placeholders[token] = atom
            out.append(token)
            continue

        out.append(ch)
        i += 1

    return "".join(out), placeholders


def _restore_env_atoms(expr: str, placeholders: dict[str, str]) -> str:
    for token, atom in placeholders.items():
        expr = expr.replace(token, atom)
    return expr


def latex_to_python(expr: str, config: ExprParserConfig) -> str:
    expr = expr.strip()
    if not expr:
        return expr
    if _has_disabled_apostrophe_operator(expr):
        raise SyntaxError("operator ' is not supported for matrices; use \\T(...) for transpose")

    sqrt_pattern = re.compile(r"(?:\\)?sqrt(?:\[(.*?)\])?\((.*?)\)")
    while True:
        match = sqrt_pattern.search(expr)
        if not match:
            break
        index, inside = match.groups()
        if index is None:
            replacement = f"Pow({inside}, Rational(1,2))"
        else:
            replacement = f"Pow({inside}, Rational(1,{index}))"
        expr = expr[: match.start()] + replacement + expr[match.end() :]
    expr = _replace_cmd_outside_strings(expr, r"\nthroot", "nthroot")

    frac_pattern = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
    while True:
        match = frac_pattern.search(expr)
        if not match:
            break
        numerador, denominador = match.groups()
        expr = expr[: match.start()] + f"({numerador})/({denominador})" + expr[match.end() :]

    expr = expr.replace(r"\zeros", "Matrix.zeros")
    expr = expr.replace(r"\ones", "Matrix.ones")
    expr = expr.replace("{", "(").replace("}", ")")

    has_dot_ops = _contains_dot_ops(expr)
    parsed_ok = False
    parsed_expr = expr

    if not has_dot_ops:
        local_dict = dict(config.parser_local_dict)
        token_pattern = re.compile(r"[A-Za-z_]\w*")
        tokens = set(token_pattern.findall(expr))
        for token in tokens:
            if token in local_dict:
                continue
            if re.search(rf"\b{re.escape(token)}\s*\(", expr):
                try:
                    local_dict[token] = Function(token)
                except Exception:
                    pass
                else:
                    continue
            try:
                local_dict[token] = symbols(token)
            except Exception:
                continue
        from sympy import Function as SymFunction

        for original, placeholder in config.protected_funcs.items():
            local_dict[placeholder] = SymFunction(placeholder)

        def _protect(expr_text: str) -> str:
            for name, placeholder in config.protected_funcs.items():
                expr_text = re.sub(rf"\b{name}\s*\(", f"{placeholder}(", expr_text)
            return expr_text

        def _restore(expr_text: str) -> str:
            for name, placeholder in config.protected_funcs.items():
                expr_text = expr_text.replace(f"{placeholder}(", f"{name}(")
            return expr_text

        expr = _protect(expr)
        try:
            parsed = parse_expr(expr, local_dict=local_dict, transformations=config.parser_transformations)
            parsed_expr = repr(parsed)
            parsed_ok = True
        except Exception:
            parsed_expr = expr
        parsed_expr = _restore(parsed_expr)

    implicit_mul = has_dot_ops or not parsed_ok
    expr_for_parser = parsed_expr
    placeholders: dict[str, str] = {}
    if "env_ast[" in expr_for_parser:
        expr_for_parser, placeholders = _protect_env_atoms(expr_for_parser)
    expr = _mathtex_infix_to_python(expr_for_parser, implicit_mul=implicit_mul)
    if placeholders:
        expr = _restore_env_atoms(expr, placeholders)

    for reserved, alias in config.reserved_keyword_aliases.items():
        expr = re.sub(rf"(?<!\w){re.escape(reserved)}(?!\w)", alias, expr)

    return expr


def oct_index_code(expr_text: str, ctx: ParserContext, config: ExprParserConfig) -> str:
    """Convierte un texto de indice/rango estilo Octave en codigo Python."""
    cleaned = expr_text.strip()
    if not cleaned or cleaned == ":":
        return "':'"

    def _conv(token: str) -> str:
        return latex_to_python(normalize_matrix_expr(token, ctx.env_ast), config)

    parts = [p.strip() for p in cleaned.split(":")]
    if len(parts) in {2, 3} and all(parts):
        start_code = _conv(parts[0])
        if len(parts) == 2:
            end_code = _conv(parts[1])
            return f"_oct_span({start_code}, None, {end_code})"
        step_code = _conv(parts[1])
        end_code = _conv(parts[2])
        return f"_oct_span({start_code}, {step_code}, {end_code})"
    return _conv(cleaned)


def oct_replace_indices(expr_text: str, ctx: ParserContext, config: ExprParserConfig) -> str:
    """Reemplaza accesos estilo Octave con helpers 1-based."""

    def _convert_expr(expr: str) -> str:
        cleaned = expr.strip()
        if not cleaned:
            return "0"
        return latex_to_python(cleaned, config)

    def _matrix_repl(match: re.Match[str]) -> str:
        name_raw, row_expr, col_expr = match.groups()
        name = name_raw.lstrip("\\")
        value = ctx.env_ast.get(name)

        row_clean = row_expr.strip()
        col_clean = col_expr.strip()
        needs_slice = (":" in row_clean) or (":" in col_clean)
        if needs_slice:
            row_code = oct_index_code(row_clean, ctx, config)
            col_code = oct_index_code(col_clean, ctx, config)
            return f"_oct_slice('{name}', {row_code}, {col_code})"

        if isinstance(value, MatrixBase):
            row_py = _convert_expr(row_clean)
            col_py = _convert_expr(col_clean)
            return f"_oct_get2('{name}', {row_py}, {col_py})"
        return match.group(0)

    expr_text = re.sub(
        r"(\\?[A-Za-z_]\w*)\(\s*([^(),]+)\s*,\s*([^(),]+)\s*\)",
        _matrix_repl,
        expr_text,
    )

    def _vector_repl(match: re.Match[str]) -> str:
        name_raw, idx_expr = match.groups()
        name = name_raw.lstrip("\\")
        value = ctx.env_ast.get(name)

        idx_clean = idx_expr.strip()
        idx_value = ctx.env_ast.get(idx_clean.lstrip("\\"))
        if isinstance(value, MatrixBase) and isinstance(idx_value, MatrixBase):
            return match.group(0)
        if ":" in idx_clean:
            idx_code = oct_index_code(idx_clean, ctx, config)
            if isinstance(value, MatrixBase):
                if value.cols == 1:
                    return f"_oct_slice('{name}', {idx_code}, 1)"
                if value.rows == 1:
                    return f"_oct_slice('{name}', 1, {idx_code})"
            return f"_oct_slice('{name}', {idx_code}, 1)"
        if isinstance(value, MatrixBase) and (value.rows == 1 or value.cols == 1):
            idx_py = _convert_expr(idx_clean)
            return f"_oct_get1('{name}', {idx_py})"
        return match.group(0)

    expr_text = re.sub(
        r"(\\?[A-Za-z_]\w*)\(\s*([^(),]+)\s*\)",
        _vector_repl,
        expr_text,
    )
    return expr_text


def _rewrite_octave_list_comprehensions(expr: str) -> str:
    """
    Convierte comprensiones estilo Octave:
      [ ... for i = a:b ] / [ ... for i = a:step:b ]
    a la forma Python:
      [ ... for i in _oct_range(a, b, step) ]
    """
    pattern = re.compile(
        r"\bfor\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*:\s*(.+?)(?:\s*:\s*(.+?))?(?=\s*(?:if\b|\]))",
        re.IGNORECASE,
    )

    def repl(match: re.Match[str]) -> str:
        var = match.group(1)
        first = match.group(2).strip()
        second = match.group(3).strip()
        third = match.group(4)
        if third is None:
            start_text = first
            step_text = "1"
            end_text = second
        else:
            start_text = first
            step_text = second
            end_text = third.strip()
        return f"for {var} in _oct_range({start_text}, {end_text}, {step_text})"

    return pattern.sub(repl, expr)


def oct_expr_to_python(expr: str, ctx: ParserContext, config: ExprParserConfig) -> str:
    """Convierte una expresion estilo Octave en codigo Python utilizable."""
    expr_clean = expr
    for cmd, alias in config.greek_cmd_to_alias.items():
        expr_clean = _replace_cmd_outside_strings(expr_clean, cmd, alias)
    expr_norm = normalize_matrix_expr(expr_clean, ctx.env_ast)
    expr_norm = oct_replace_indices(expr_norm, ctx, config)
    expr_norm = _rewrite_octave_list_comprehensions(expr_norm)
    or_parts = _split_top_level(expr_norm, "||")
    if len(or_parts) > 1 and all(part.strip() for part in or_parts):
        joined = " or ".join(oct_expr_to_python(part.strip(), ctx, config) for part in or_parts)
        return f"({joined})"
    and_parts = _split_top_level(expr_norm, "&&")
    if len(and_parts) > 1 and all(part.strip() for part in and_parts):
        joined = " and ".join(oct_expr_to_python(part.strip(), ctx, config) for part in and_parts)
        return f"({joined})"
    bar_parts = _split_top_level(expr_norm, "|")
    if len(bar_parts) == 2 and all(part.strip() for part in bar_parts):
        left_py = oct_expr_to_python(bar_parts[0].strip(), ctx, config)
        right_py = oct_expr_to_python(bar_parts[1].strip(), ctx, config)
        return f"_mt_bar({left_py}, {right_py})"
    should_force_mathtex = _contains_dot_ops(expr_norm) or "^" in expr_norm or "\\" in expr_norm
    try:
        if should_force_mathtex:
            raise SyntaxError("force MathTeX expression translation")
        ast.parse(expr_norm, mode="eval")
        expr_py = expr_norm
    except Exception:
        expr_py = latex_to_python(expr_norm, config)
    expr_py = _replace_user_function_calls(expr_py, ctx)
    return expr_py


def _replace_user_function_calls(expr_py: str, ctx: ParserContext) -> str:
    """Reemplaza llamadas a funciones definidas por el usuario por _mt_call()."""
    env = ctx.env_ast
    if not env:
        return expr_py

    def _is_user_func(name: str) -> bool:
        if f"{name}_vars" not in env:
            return False
        return isinstance(env.get(name), sp.Expr)

    def _is_apply_target(name: str) -> bool:
        value = env.get(name)
        return isinstance(value, (MatrixBase, sp.Expr)) or callable(value)

    def _find_local_matching_paren(text: str, start_idx: int) -> int | None:
        depth = 0
        in_str = False
        quote = ""
        escape = False
        for idx in range(start_idx, len(text)):
            ch = text[idx]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if in_str:
                if ch == quote:
                    in_str = False
                    quote = ""
                continue
            if ch in {"'", '"'}:
                in_str = True
                quote = ch
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return idx
        return None

    out: list[str] = []
    i = 0
    pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
    while i < len(expr_py):
        match = pattern.search(expr_py, i)
        if not match:
            out.append(expr_py[i:])
            break
        start = match.start()
        name = match.group(1)
        paren_start = match.end() - 1
        if start > 0 and expr_py[start - 1] == ".":
            out.append(expr_py[i : paren_start + 1])
            i = paren_start + 1
            continue
        if not _is_user_func(name):
            if _is_apply_target(name):
                paren_end = _find_local_matching_paren(expr_py, paren_start)
                if paren_end is None:
                    out.append(expr_py[i:])
                    break
                args_text = expr_py[paren_start + 1 : paren_end].strip()
                if args_text:
                    args_text = _replace_user_function_calls(args_text, ctx)
                    repl = f"_mt_apply_symbol('{name}', {args_text})"
                else:
                    repl = f"_mt_apply_symbol('{name}')"
                out.append(expr_py[i:start])
                out.append(repl)
                i = paren_end + 1
                continue
            out.append(expr_py[i : paren_start + 1])
            i = paren_start + 1
            continue
        paren_end = _find_local_matching_paren(expr_py, paren_start)
        if paren_end is None:
            out.append(expr_py[i:])
            break
        args_text = expr_py[paren_start + 1 : paren_end].strip()
        if args_text:
            args_text = _replace_user_function_calls(args_text, ctx)
            repl = f"_mt_call('{name}', {args_text})"
        else:
            repl = f"_mt_call('{name}')"
        out.append(expr_py[i:start])
        out.append(repl)
        i = paren_end + 1
    return "".join(out)


def parse_mathtex_expr(expr: str, ctx: ParserContext, config: ExprParserConfig) -> ASTNode:
    """Convierte una expresion MathTeX a AST usando el pipeline actual."""
    expr_clean = expr.strip()
    if not expr_clean:
        raise make_parse_error(
            "empty-expression",
            "Expression is empty.",
            source=expr,
            hint="Write an expression after the assignment or statement.",
        )

    expr_issue = find_expression_issue(expr_clean)
    if expr_issue is not None:
        raise make_parse_error(
            expr_issue.kind,
            expr_issue.message,
            source=expr_clean,
            line=expr_issue.line,
            column=expr_issue.column,
            start=expr_issue.start,
            end=expr_issue.end,
            hint=expr_issue.hint,
        )

    try:
        expr_py = oct_expr_to_python(expr_clean, ctx, config)
    except SyntaxError as exc:
        raise parse_error_from_syntax_error(
            exc,
            source=expr_clean,
            kind="invalid-expression",
            hint="Check the expression syntax and supported postfix operators.",
        ) from exc

    try:
        return build_ast_from_python_expr(expr_py)
    except SyntaxError as exc:
        raise parse_error_from_syntax_error(
            exc,
            source=expr_clean,
            kind="invalid-expression",
            hint="Check the expression syntax near the reported token.",
        ) from exc
    except ValueError as exc:
        raise make_parse_error(
            "unsupported-ast",
            f"Expression uses syntax that the MathTeX AST does not model yet: {exc}",
            source=expr_clean,
            hint="The runtime fallback may still be able to evaluate this expression.",
            recoverable=True,
        ) from exc
    except Exception as exc:
        raise make_parse_error(
            "invalid-expression",
            f"Could not parse expression: {exc}",
            source=expr_clean,
        ) from exc
