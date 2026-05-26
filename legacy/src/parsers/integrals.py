from __future__ import annotations

import re

from sympy import integrate, simplify, symbols, together

from .context import ParserContext


def _format_frac(expr):
    num, denom = expr.as_numer_denom()
    if denom == 1:
        return str(num)
    return f"\\frac{{{num}}}{{{denom}}}"


def handle_integrals(linea: str, ctx: ParserContext) -> bool:
    """Procesa comandos de integrales simbólicas."""
    stripped = linea.strip()
    asignacion = None
    match = re.match(r"([a-zA-Z_]\w*)\s*=\s*(\\int\(.*\))$", stripped)
    if match:
        asignacion = match.group(1)
        stripped = match.group(2)

    if not (stripped.startswith(r"\int(") and stripped.endswith(")")):
        return False

    latex_to_python = ctx.latex_to_python
    partes = [p.strip() for p in stripped[5:-1].split(",")]
    if len(partes) < 2:
        print("Error: expected format \\int(f,x) or \\int(f,x,a,b)")
        return True

    f_str, var_str = partes[0], partes[1]
    var_sym = symbols(var_str)

    try:
        f_expr = eval(latex_to_python(f_str), ctx.eval_context())
    except Exception as e:
        print(f"Error while parsing the function: {e}")
        return True

    try:
        if len(partes) == 2:
            res = simplify(together(integrate(f_expr, var_sym)))
            texto_res = f"{_format_frac(res)} + C"
            if asignacion:
                ctx.env_ast[asignacion] = res
                print(f"{asignacion} = {texto_res}")
            else:
                print(f"Int {f_str} d{var_str} = {texto_res}")
        elif len(partes) == 4:
            contexto = ctx.eval_context()
            a = eval(latex_to_python(partes[2]), contexto)
            b = eval(latex_to_python(partes[3]), contexto)
            res = simplify(together(integrate(f_expr, (var_sym, a, b))))
            if asignacion:
                ctx.env_ast[asignacion] = res
                print(f"{asignacion} = {_format_frac(res)}")
            else:
                print(f"Int_[{a},{b}] {f_str} d{var_str} = {_format_frac(res)}")
        else:
            print("Error: incorrect number of arguments in \\int().")
    except Exception as e:
        print(f"Error while computing the integral: {e}")
    return True
