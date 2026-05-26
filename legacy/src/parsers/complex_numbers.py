from __future__ import annotations

import re

from sympy import Abs, arg, conjugate, im as sym_im, re as sym_re

from numeric_format import format_value_for_display

from .context import ParserContext


def handle_complex_numbers(linea: str, ctx: ParserContext) -> bool:
    """Procesa comandos de numeros complejos."""
    env_ast = ctx.env_ast
    latex_to_python = ctx.latex_to_python
    expr_to_python = ctx.expr_to_python or latex_to_python
    greek_display = ctx.greek_display

    def _format_var(name: str) -> str:
        if name.startswith("_gr_"):
            base = name[len("_gr_"):]
            return greek_display.get(base, base)
        return name

    def _assign_outputs(
        targets: list[str] | None,
        default_names: list[str],
        values: list[object],
        label: str,
    ) -> list[str] | None:
        if targets:
            requested = len(targets)
            available = len(values)
            if requested > available:
                print(f"Error: {label} returns {available} values, but you requested {requested}.")
                return None
            assigned = targets[:available]
            for idx, name in enumerate(assigned):
                env_ast[name] = values[idx]
            return assigned

        assigned = default_names[: len(values)]
        for name, value in zip(assigned, values):
            env_ast[name] = value
        return assigned

    linea_stripped = linea.strip()
    output_targets: list[str] | None = None
    multi_assign = re.match(
        r"^\[(?P<vars>[^\]]+)\]\s*=\s*(?P<cmd>\\[A-Za-z][\w\d]*\(.*\))\s*$",
        linea_stripped,
    )
    if multi_assign:
        vars_text = multi_assign.group("vars")
        cmd_text = multi_assign.group("cmd").strip()
        cmd_prefix = cmd_text.split("(", 1)[0]
        if cmd_prefix == r"\polar":
            candidates = [v.strip() for v in vars_text.split(",") if v.strip()]
            if candidates:
                output_targets = candidates
                linea_stripped = cmd_text

    if linea_stripped.startswith(r"\conj(") and linea_stripped.endswith(")"):
        inner = linea_stripped[6:-1].strip()
        try:
            expr = eval(expr_to_python(inner), ctx.eval_context({"I": ctx.common_symbols.get("I")}))
            res = conjugate(expr)
            print(f"conj({inner}) = {res}")
        except Exception:
            try:
                expr = eval(expr_to_python(inner), ctx.eval_context())
                res = conjugate(expr)
                print(f"conj({inner}) = {res}")
            except Exception as e:
                print(f"Error while computing the conjugate: {e}")
        return True

    if linea_stripped.startswith(r"\Re(") and linea_stripped.endswith(")"):
        inner = linea_stripped[4:-1].strip()
        try:
            expr = eval(expr_to_python(inner), ctx.eval_context())
            print(f"Re({inner}) = {sym_re(expr)}")
        except Exception as e:
            print(f"Error while computing the real part: {e}")
        return True

    if linea_stripped.startswith(r"\Im(") and linea_stripped.endswith(")"):
        inner = linea_stripped[4:-1].strip()
        try:
            expr = eval(expr_to_python(inner), ctx.eval_context())
            print(f"Im({inner}) = {sym_im(expr)}")
        except Exception as e:
            print(f"Error while computing the imaginary part: {e}")
        return True

    if (
        (linea_stripped.startswith(r"\abs(") and linea_stripped.endswith(")"))
        or (linea_stripped.startswith("abs(") and linea_stripped.endswith(")"))
    ):
        inner = linea_stripped[linea_stripped.index("(") + 1:-1].strip()
        try:
            expr = eval(expr_to_python(inner), ctx.eval_context())
            print(f"|{inner}| = {Abs(expr)}")
        except Exception as e:
            print(f"Error while computing the modulus: {e}")
        return True

    if linea_stripped.startswith(r"\polar(") and linea_stripped.endswith(")"):
        inner = linea_stripped[7:-1].strip()
        try:
            expr = eval(expr_to_python(inner), ctx.eval_context())
            values = [Abs(expr), arg(expr)]
            names_used = _assign_outputs(output_targets, ["r", "theta"], values, r"\polar")
            if names_used is not None:
                assigned_pairs = ", ".join(
                    f"{_format_var(name)}={format_value_for_display(value)}"
                    for name, value in zip(names_used, values)
                )
                print(f"polar({inner}) -> {assigned_pairs}")
        except Exception as e:
            print(f"Error while computing the polar form: {e}")
        return True

    if linea_stripped.startswith(r"\angle(") and linea_stripped.endswith(")"):
        inner = linea_stripped[7:-1].strip()
        try:
            expr = eval(expr_to_python(inner), ctx.eval_context())
            print(f"angle({inner}) = {format_value_for_display(arg(expr))}")
        except Exception as e:
            print(f"Error while computing the angle: {e}")
        return True

    return False
