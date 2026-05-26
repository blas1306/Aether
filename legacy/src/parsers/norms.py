from __future__ import annotations

import re

from .context import ParserContext
from .matrices import _split_top_level_args


def handle_norms(linea: str, ctx: ParserContext) -> bool:
    """Procesa definición/listado/cálculo de normas."""
    user_norms = ctx.user_norms
    latex_to_python = ctx.latex_to_python
    greek_display = ctx.greek_display

    if linea.startswith(r"\defnorm(") and linea.endswith(")"):
        inner = linea[9:-1].strip()
        try:
            name, expr_str = [a.strip() for a in inner.split(",", 1)]
        except ValueError:
            print("Error: formato esperado \\defnorm(nombre, expresion)")
            return True
        user_norms[name] = latex_to_python(expr_str)
        print(f"Norma '{name}' definida.")
        return True

    if linea.strip() == r"\listnorms":
        if not user_norms:
            print("No hay normas definidas.")
        else:
            print("Normas definidas:")
            for k, v in user_norms.items():
                print(f" - {k}: {v}")
        return True

    if linea.startswith(r"\norm(") and linea.endswith(")"):
        inner = linea[6:-1].strip()
        args = _split_top_level_args(inner)
        if not args or not args[0]:
            print("Error: formato esperado \\norm(A) o \\norm(A,p)")
            return True

        expr_text = linea.strip()
        label = args[0]
        p = args[1] if len(args) > 1 and args[1] else "2"
        temp_name = "__mathtex_norm_tmp__"
        while temp_name in ctx.env_ast:
            temp_name += "_"
        try:
            if ctx.run_line is None:
                print("Error interno: no hay ejecutor disponible para evaluar la norma.")
                return True
            ctx.run_line(f"{temp_name} = {expr_text};")
            if temp_name not in ctx.env_ast:
                print("Error al calcular la norma.")
                return True
            val = ctx.env_ast[temp_name]
            s = str(val)
            for g, symb in greek_display.items():
                s = re.sub(rf"\b{g}\b", symb, s)
            print(f"||{label}||_{p} = {s}")
        except Exception as e:
            print(f"Error al calcular la norma: {e}")
        finally:
            ctx.env_ast.pop(temp_name, None)
        return True

    return False
