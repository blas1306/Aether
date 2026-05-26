from __future__ import annotations

import re

from typing import cast

from sympy import Abs, Matrix, Rational, sqrt, symbols, N

from .context import ParserContext


def handle_inner_products(linea: str, ctx: ParserContext) -> bool:
    """Procesa definición y evaluación de productos internos."""
    user_inners = ctx.user_inners
    latex_to_python = ctx.latex_to_python
    greek_display = ctx.greek_display

    if linea.startswith(r"\definner(") and linea.endswith(")"):
        inner = linea[10:-1].strip()
        try:
            name, expr_str = [a.strip() for a in inner.split(",", 1)]
        except ValueError:
            print("Error: formato esperado \\definner(nombre, expresion)")
            return True
        user_inners[name] = latex_to_python(expr_str)
        print(f"Producto interno '{name}' definido.")
        return True

    if linea.strip() == r"\listinners":
        if not user_inners:
            print("No hay productos internos definidos.")
        else:
            print("Productos internos definidos:")
            for k, v in user_inners.items():
                print(f" - {k}: {v}")
        return True

    if linea.startswith(r"\inner(") and linea.endswith(")"):
        inner = linea[7:-1].strip()
        args = [a.strip() for a in inner.split(",")]
        if len(args) < 2:
            print("Error: formato esperado \\inner(u,v) o \\inner(u,v,tipo)")
            return True

        u_name, v_name = args[0], args[1]
        tipo = args[2] if len(args) > 2 else "usual"
        if u_name not in ctx.env_ast or v_name not in ctx.env_ast:
            print(f"Error: los vectores {u_name} y {v_name} deben estar definidos.")
            return True
        u = ctx.env_ast[u_name]
        v = ctx.env_ast[v_name]
        if not isinstance(u, Matrix) or not isinstance(v, Matrix):
            print("Error: el producto interno solo se aplica a vectores columna o fila.")
            return True
        u_mat = cast(Matrix, u)
        v_mat = cast(Matrix, v)
        if not (u_mat.shape[0] == v_mat.shape[0] and u_mat.shape[1] == v_mat.shape[1] == 1):
            print("Error: los vectores deben tener la misma dimension y ser columna.")
            return True

        try:
            if tipo in ["usual", "std", "standard"]:
                # Ensure entries are evaluated to numeric SymPy Floats before casting to Python float
                val = sum(float(N(u_mat[i, 0])) * float(N(v_mat[i, 0])) for i in range(u_mat.shape[0]))
            elif tipo in user_inners:
                expr_str = user_inners[tipo]
                n = u_mat.shape[0]
                x_vars = symbols(f"x_1:{n+1}")
                y_vars = symbols(f"y_1:{n+1}")
                contexto_local = ctx.eval_context({"Abs": Abs, "sqrt": sqrt, "Rational": Rational})
                for i, sym in enumerate(x_vars, start=1):
                    contexto_local[f"x_{i}"] = sym
                for i, sym in enumerate(y_vars, start=1):
                    contexto_local[f"y_{i}"] = sym
                expr = eval(expr_str, contexto_local)
                subs_map = {x_vars[i]: u_mat[i, 0] for i in range(n)}
                subs_map.update({y_vars[i]: v_mat[i, 0] for i in range(n)})
                val = expr.subs(subs_map)
            else:
                print(f"Tipo de producto interno no reconocido: {tipo}")
                return True

            s = str(val)
            for g, symb in greek_display.items():
                s = re.sub(rf"\b{g}\b", symb, s)
            print(f"<{u_name},{v_name}>_{tipo} = {s}")
        except Exception as e:
            print(f"Error al calcular el producto interno: {e}")
        return True

    return False
