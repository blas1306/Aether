from __future__ import annotations

import re
from typing import Any

from sympy import Integer, Product, Sum, symbols, sympify

from .context import ParserContext
from .functions import _mt_get1, _mt_get2, _rewrite_index_calls


def _split_args(raw: str) -> list[str]:
    args: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str = False
    quote = ""
    escape = False

    for ch in raw:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            continue
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
                quote = ""
            continue
        if ch in {"'", '"'}:
            in_str = True
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            token = "".join(buf).strip()
            if token:
                args.append(token)
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _parse_bounds(parts: list[str], ctx: ParserContext):
    if len(parts) != 4:
        raise ValueError("formato esperado \\sum(expr, var, a, b)")

    expr_str, var_str, a_str, b_str = [p.strip() for p in parts]
    var_name = var_str.replace("\\", "")
    if not re.match(r"^[A-Za-z_]\w*$", var_name):
        raise ValueError(f"variable invalida en sumatoria/productoria: '{var_str}'.")

    eval_ctx = ctx.eval_context()
    latex_to_python = ctx.latex_to_python
    a_val = eval(latex_to_python(a_str), {"__builtins__": __builtins__}, eval_ctx)
    b_val = eval(latex_to_python(b_str), {"__builtins__": __builtins__}, eval_ctx)
    return expr_str, var_name, a_val, b_val


def _as_integer(value: Any, label: str) -> int:
    try:
        sym_val = sympify(value)
    except Exception as exc:
        raise ValueError(f"{label} debe ser entero: {exc}") from exc
    if sym_val.is_integer is False:
        raise ValueError(f"{label} debe ser entero (obtuve {value!r}).")
    try:
        int_val = int(sym_val)
    except Exception as exc:
        raise ValueError(f"{label} debe ser entero (obtuve {value!r}).") from exc
    if sympify(int_val) != sym_val:
        raise ValueError(f"{label} debe ser entero (obtuve {value!r}).")
    return int_val


def _iterative_series(expr_str: str, var_name: str, a_val: Any, b_val: Any, ctx: ParserContext, keyword: str):
    a_i = _as_integer(a_val, "limite inferior")
    b_i = _as_integer(b_val, "limite superior")
    expr_rewritten = _rewrite_index_calls(expr_str, ctx, [var_name])
    expr_py = ctx.latex_to_python(expr_rewritten)
    op_sum = keyword == r"\sum"
    acc = Integer(0) if op_sum else Integer(1)
    step = 1 if a_i <= b_i else -1
    for idx in range(a_i, b_i + step, step):
        eval_ctx = ctx.eval_context(
            {
                var_name: idx,
                "_mt_get1": _mt_get1,
                "_mt_get2": _mt_get2,
            }
        )
        term = eval(expr_py, {"__builtins__": __builtins__}, eval_ctx)
        acc = acc + term if op_sum else acc * term
    return acc


def _symbolic_series(expr_str: str, var_name: str, a_val: Any, b_val: Any, ctx: ParserContext, keyword: str):
    var_sym = symbols(var_name)
    eval_ctx = ctx.eval_context({var_name: var_sym})
    expr = eval(ctx.latex_to_python(expr_str), {"__builtins__": __builtins__}, eval_ctx)
    op_cls = Sum if keyword == r"\sum" else Product
    return op_cls(expr, (var_sym, a_val, b_val)).doit()


def _evaluate_series(inner: str, ctx: ParserContext, keyword: str):
    parts = _split_args(inner)
    expr_str, var_name, a_val, b_val = _parse_bounds(parts, ctx)
    try:
        result = _iterative_series(expr_str, var_name, a_val, b_val, ctx, keyword)
    except Exception:
        # Fallback simbólico para expresiones puramente simbólicas.
        result = _symbolic_series(expr_str, var_name, a_val, b_val, ctx, keyword)
    return result, expr_str, var_name, a_val, b_val


def _handle_series_command(linea: str, ctx: ParserContext, keyword: str):
    prefix = f"{keyword}("
    if not (linea.startswith(prefix) and linea.endswith(")")):
        return False
    inner = linea[len(prefix) : -1].strip()
    try:
        result, expr_str, var_name, a_val, b_val = _evaluate_series(inner, ctx, keyword)
    except ValueError as exc:
        print(f"Error: {exc}")
        return True
    except Exception as exc:
        print(f"Error al evaluar {keyword}: {exc}")
        return True

    op_label = "Sumatoria" if keyword == r"\sum" else "Productoria"
    print(f"{op_label} ({var_name}={a_val}..{b_val}) de {expr_str} = {result}")
    return True


def _handle_series_assignment(linea: str, ctx: ParserContext):
    match = re.match(r"^(\\?[A-Za-z_]\w*)\s*=\s*(\\sum|\\prod)\((.*)\)\s*$", linea)
    if not match:
        return False

    target_raw, keyword, inner = match.groups()
    try:
        result, _expr_str, _var_name, _a_val, _b_val = _evaluate_series(inner, ctx, keyword)
    except ValueError as exc:
        print(f"Error: {exc}")
        return True
    except Exception as exc:
        print(f"Error al evaluar {keyword}: {exc}")
        return True

    target_name = target_raw.lstrip("\\")
    ctx.env_ast[target_name] = result
    print(f"{target_name} = {result}")
    return True


def handle_sums_products(linea: str, ctx: ParserContext) -> bool:
    if _handle_series_assignment(linea, ctx):
        return True
    if linea.startswith(r"\sum("):
        return _handle_series_command(linea, ctx, r"\sum")
    if linea.startswith(r"\prod("):
        return _handle_series_command(linea, ctx, r"\prod")
    return False
