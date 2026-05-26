from __future__ import annotations

import re

import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import solve_ivp
from sympy import Eq, Function, diff, dsolve, lambdify, symbols

from .context import ParserContext


def _as_float_scalar(value, label: str) -> float:
    array = np.asarray(value)
    if array.ndim == 0:
        return float(array)
    if array.size != 1:
        raise ValueError(f"{label} must evaluate to a scalar.")
    return float(array.reshape(-1)[0])


def _build_sample_grid(a: float, b: float, n: int) -> tuple[np.ndarray, float]:
    if n <= 0:
        raise ValueError("n must be a positive integer.")
    X = np.linspace(a, b, n + 1)
    return X, abs(b - a) / n


def _make_dense_solution_func(sol, x0: float, x1: float, y0: float, y1: float):
    def y_num_func(xq):
        xq = float(xq)
        if x0 <= x1:
            if xq <= x0:
                return y0
            if xq >= x1:
                return y1
        else:
            if xq >= x0:
                return y0
            if xq <= x1:
                return y1
        return float(sol.sol(xq)[0])

    return y_num_func


def _solve_numeric_ode(rhs, a: float, b: float, y0, n: int):
    X, max_step = _build_sample_grid(a, b, n)
    kwargs = {
        "t_eval": X,
        "dense_output": True,
        "rtol": 1e-8,
        "atol": 1e-10,
    }
    if max_step > 0:
        kwargs["max_step"] = max_step
    sol = solve_ivp(rhs, (a, b), np.asarray(y0, dtype=float), **kwargs)
    if not sol.success:
        raise ValueError(sol.message or "solve_ivp failed.")
    if sol.sol is None:
        raise ValueError("solve_ivp did not return a dense solution.")
    return X, sol


def parse_ode_lhs_rhs(s: str):
    if "=" not in s:
        return s.strip(), "0"
    left, right = [p.strip() for p in s.split("=", 1)]
    return left, right


def normalize_derivatives(txt: str):
    txt = re.sub(r"([a-zA-Z_]\w*)\^\{\s*\((\d+)\)\s*\}\(x\)", r"diff(\1(x), x, \2)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'''\(x\)", r"diff(\1(x), x, 3)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)''\(x\)", r"diff(\1(x), x, 2)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'\(x\)", r"diff(\1(x), x)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'''\b", r"diff(\1(x), x, 3)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)''\b", r"diff(\1(x), x, 2)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'\b", r"diff(\1(x), x)", txt)
    return txt


def parse_ic_and_interval(args_list):
    ics = {}
    a = b = None
    n = 400
    plot_flag = False
    for token in args_list:
        t = token.strip()
        if ".." in t and t.startswith("x="):
            seg = t[2:].strip("=")
            a_str, b_str = [q.strip() for q in seg.split("..", 1)]
            a, b = a_str, b_str
        elif "=" in t and t.strip().startswith("n"):
            _, n_str = [q.strip() for q in t.split("=", 1)]
            n = int(n_str)
        elif t.lower() == "plot":
            plot_flag = True
        elif "=" in t and "(" in t and ")" in t:
            left, right = [q.strip() for q in t.split("=", 1)]
            fname = left[: left.find("(")].strip()
            aval = left[left.find("(") + 1 : left.find(")")]
            ics[(fname, aval)] = right
    return ics, a, b, n, plot_flag


def handle_odes(linea: str, ctx: ParserContext) -> bool:
    """Procesa comandos \\dsolve y \\ode."""
    env_ast = ctx.env_ast
    greek_symbols = ctx.greek_symbols
    latex_to_python = ctx.latex_to_python
    x_sym = ctx.common_symbols.get("x")

    if linea.startswith(r"\dsolve(") and linea.endswith(")"):
        inner = linea[8:-1].strip()
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) < 2:
            print("Error: use \\dsolve( equation , y(x) , [ics...] )")
            return True

        eq_str = normalize_derivatives(parts[0])
        y_str = parts[1]
        ic_tokens = parts[2:] if len(parts) > 2 else []

        try:
            y_name = y_str[: y_str.find("(")].strip()
            y = Function(y_name)
            lhs_str, rhs_str = parse_ode_lhs_rhs(eq_str)

            contexto_dsolve = ctx.eval_context(
                {
                    "x": x_sym,
                    "Function": Function,
                    "diff": diff,
                    y_name: y,
                }
            )

            lhs = eval(latex_to_python(lhs_str), contexto_dsolve)
            rhs = eval(latex_to_python(rhs_str), contexto_dsolve)
            ode_eq = Eq(lhs, rhs)

            ics = {}
            for tok in ic_tokens:
                t = normalize_derivatives(tok)
                if "=" in t and "(" in t and ")" in t:
                    left, right = [q.strip() for q in t.split("=", 1)]
                    f_name = left[: left.find("(")].strip()
                    a_str = left[left.find("(") + 1 : left.find(")")]
                    base_ctx = ctx.eval_context({"x": x_sym})
                    a_val = eval(latex_to_python(a_str), base_ctx)
                    if f_name == y_name:
                        ics[y(a_val)] = eval(latex_to_python(right), ctx.eval_context())
                    else:
                        left_expr = eval(
                            latex_to_python(left),
                            ctx.eval_context({"x": x_sym, "Function": Function, "diff": diff}),
                        )
                        ics[left_expr] = eval(latex_to_python(right), ctx.eval_context())
            dsolve_kwargs = {"ics": ics} if ics else {}
            sol = dsolve(ode_eq, y(x_sym), **dsolve_kwargs)
            print(f"Solution: {sol}")
        except Exception as e:
            print(f"Error in dsolve: {e}")
        return True

    if linea.startswith(r"\ode(") and linea.endswith(")"):
        inner = linea[5:-1].strip()
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) < 2:
            print("Error: use \\ode( equation , y(a)=y0 , x=a..b , [n=400] , [plot] )")
            return True

        eq_str = normalize_derivatives(parts[0])
        rest = parts[1:]
        try:
            lhs_str, rhs_str = parse_ode_lhs_rhs(eq_str)
        except Exception as e:
            print(f"Error in the equation: {e}")
            return True

        ics_raw, a_str, b_str, n_steps, do_plot = parse_ic_and_interval(rest)
        mfun = re.search(r"([a-zA-Z_]\w*)\s*\(x\)", eq_str)
        if not mfun:
            print("Error: specify the function as y(x) in the equation.")
            return True
        y_name = mfun.group(1)
        y = Function(y_name)

        lhs_norm = normalize_derivatives(lhs_str)
        order2 = "diff(" in lhs_norm and ", x, 2)" in lhs_norm

        try:
            if not a_str or not b_str:
                print("Error: specify the interval as x=a..b")
                return True
            a_val = float(eval(latex_to_python(a_str), ctx.eval_context()))
            b_val = float(eval(latex_to_python(b_str), ctx.eval_context()))
        except Exception:
            print("Error: invalid interval (x=a..b).")
            return True

        try:
            if not order2:
                rhs_expr = eval(
                    latex_to_python(rhs_str),
                    ctx.eval_context({"x": x_sym, y_name: y}),
                )
                ic_pair = None
                for (fname, aval), y0 in ics_raw.items():
                    if fname == y_name:
                        a_chk = float(eval(latex_to_python(aval), ctx.eval_context()))
                        if abs(a_chk - a_val) < 1e-12:
                            ic_pair = float(eval(latex_to_python(y0), ctx.eval_context()))
                            break
                if ic_pair is None:
                    print("Error: provide an IC like y(a)=y0 with a equal to the interval start.")
                    return True

                Xsym, Ysym = symbols("Xsym Ysym")
                Fnum = lambdify((Xsym, Ysym), rhs_expr.subs({x_sym: Xsym, y(x_sym): Ysym}), "numpy")

                def rhs_scalar(xq, y_vec):
                    return np.array([_as_float_scalar(Fnum(xq, y_vec[0]), "ODE RHS")], dtype=float)

                X, sol = _solve_numeric_ode(rhs_scalar, a_val, b_val, [ic_pair], n_steps)
                Y = sol.y[0]
                y_num_func = _make_dense_solution_func(sol, a_val, b_val, float(Y[0]), float(Y[-1]))

                env_ast[f"{y_name}_num"] = y_num_func
                print(f"Sol numerica: {y_name}({b_val}) ~ {Y[-1]} (guardada como {y_name}_num(x))")
                if do_plot:
                    plt.plot(X, Y, label=f"{y_name}(x) numerica")
                    plt.grid(True)
                    plt.legend()
                    plt.show()

            else:
                lhs_expr = eval(
                    latex_to_python(lhs_str),
                    ctx.eval_context({"x": x_sym, y_name: y, "diff": diff}),
                )
                rhs_expr = eval(
                    latex_to_python(rhs_str),
                    ctx.eval_context({"x": x_sym, y_name: y, "diff": diff}),
                )
                y2 = diff(y(x_sym), x_sym, 2)
                G = (rhs_expr - (lhs_expr - y2)).subs({y2: 0})
                y0 = None
                v0 = None
                for (fname, aval), yv in ics_raw.items():
                    aval_num = float(eval(latex_to_python(aval), ctx.eval_context()))
                    if fname == y_name and abs(aval_num - a_val) < 1e-12:
                        y0 = float(eval(latex_to_python(yv), ctx.eval_context()))
                    elif fname.startswith("diff") and abs(aval_num - a_val) < 1e-12:
                        v0 = float(eval(latex_to_python(yv), ctx.eval_context()))
                if y0 is None or v0 is None:
                    print("Error: for order 2 provide y(a)=y0 and y'(a)=v0 with a equal to the interval start.")
                    return True

                Xsym, Y1, Y2 = symbols("Xsym Y1 Y2")
                Gnum = lambdify(
                    (Xsym, Y1, Y2),
                    G.subs({x_sym: Xsym, y(x_sym): Y1, diff(y(x_sym), x_sym): Y2}),
                    "numpy",
                )

                def rhs_system(xq, state):
                    y1_val, y2_val = state
                    return np.array(
                        [
                            float(y2_val),
                            _as_float_scalar(Gnum(xq, y1_val, y2_val), "ODE RHS"),
                        ],
                        dtype=float,
                    )

                X, sol = _solve_numeric_ode(rhs_system, a_val, b_val, [y0, v0], n_steps)
                Y1_arr = sol.y[0]
                y_num_func1 = _make_dense_solution_func(sol, a_val, b_val, float(Y1_arr[0]), float(Y1_arr[-1]))

                env_ast[f"{y_name}_num"] = y_num_func1
                print(f"Sol numerica: {y_name}({b_val}) ~ {Y1_arr[-1]} (guardada como {y_name}_num)")
                if do_plot:
                    plt.plot(X, Y1_arr, label=f"{y_name}(x) numerica")
                    plt.grid(True)
                    plt.legend()
                    plt.show()

        except Exception as e:
            print(f"Error in \\ode: {e}")
        return True

    return False
