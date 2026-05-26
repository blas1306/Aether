from __future__ import annotations

import re
from typing import Any, List

from sympy import diff, symbols, sympify, Expr
from sympy.matrices import MatrixBase

from numeric_format import format_value_for_display, set_numeric_format
from .context import ParserContext
from .matrices import matrix_to_str


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
            arg = "".join(buf).strip()
            if arg:
                args.append(arg)
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _ensure_integer(value, label: str) -> int:
    try:
        sym_val = sympify(value)
    except Exception as exc:
        raise ValueError(f"{label} must be an integer: {exc}") from exc
    if sym_val.is_real is False:
        raise ValueError(f"{label} must be real.")
    try:
        int_val = int(sym_val)
    except Exception as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if sympify(int_val) != sym_val:
        raise ValueError(f"{label} must be an integer.")
    return int_val


def _mt_get1(value, idx):
    pos = _ensure_integer(idx, "indice") - 1
    if isinstance(value, MatrixBase):
        if value.rows == 1:
            return value[0, pos]
        if value.cols == 1:
            return value[pos, 0]
        return value[pos, 0]
    if isinstance(value, (list, tuple)):
        return value[pos]
    try:
        return value[pos]
    except Exception as exc:
        raise ValueError(f"Invalid index: {exc}") from exc


def _mt_get2(value, row, col):
    r_idx = _ensure_integer(row, "fila") - 1
    c_idx = _ensure_integer(col, "columna") - 1
    if isinstance(value, MatrixBase):
        return value[r_idx, c_idx]
    if isinstance(value, (list, tuple)):
        return value[r_idx][c_idx]
    try:
        return value[r_idx, c_idx]
    except Exception as exc:
        raise ValueError(f"Invalid index: {exc}") from exc


def _expand_function_args(raw_args: list[Any], expected_len: int) -> list[Any]:
    if len(raw_args) != 1 or expected_len <= 1:
        return raw_args

    first_arg = raw_args[0]
    if isinstance(first_arg, MatrixBase):
        if first_arg.rows == 1:
            return [first_arg[0, idx] for idx in range(first_arg.cols)]
        if first_arg.cols == 1:
            return [first_arg[idx, 0] for idx in range(first_arg.rows)]
        return raw_args
    if isinstance(first_arg, (list, tuple)):
        return list(first_arg)
    return raw_args


def _rewrite_index_calls(expr: str, ctx: ParserContext, arg_names: list[str]) -> str:
    """Reescribe llamadas estilo x(i) o A(i,j) como indexado seguro."""
    env_ast = ctx.env_ast
    common = ctx.common_symbols

    def _is_user_func(name: str) -> bool:
        return f"{name}_vars" in env_ast and isinstance(env_ast.get(name), Expr)

    def _should_rewrite(name: str) -> bool:
        if _is_user_func(name):
            return False
        if name in arg_names:
            return True
        val = env_ast.get(name)
        if isinstance(val, MatrixBase) or isinstance(val, (list, tuple)):
            return True
        if name in common and callable(common[name]):
            return False
        return False

    def _find_matching_paren(text: str, start_idx: int) -> int | None:
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
    while i < len(expr):
        match = pattern.search(expr, i)
        if not match:
            out.append(expr[i:])
            break
        start = match.start()
        name = match.group(1)
        paren_start = match.end() - 1
        if start > 0 and expr[start - 1] == ".":
            out.append(expr[i:paren_start + 1])
            i = paren_start + 1
            continue
        paren_end = _find_matching_paren(expr, paren_start)
        if paren_end is None:
            out.append(expr[i:])
            break
        args_text = expr[paren_start + 1 : paren_end]
        args = _split_args(args_text)
        args_rewritten = [_rewrite_index_calls(a, ctx, arg_names) for a in args]
        if _should_rewrite(name) and len(args_rewritten) in {1, 2}:
            if len(args_rewritten) == 1:
                repl = f"_mt_get1({name}, {args_rewritten[0]})"
            else:
                repl = f"_mt_get2({name}, {args_rewritten[0]}, {args_rewritten[1]})"
            out.append(expr[i:start])
            out.append(repl)
        else:
            rebuilt = f"{name}({', '.join(args_rewritten)})"
            out.append(expr[i:start])
            out.append(rebuilt)
        i = paren_end + 1
    return "".join(out)


def _parse_plot_args(inner: str | list[str], ctx: ParserContext) -> tuple[List[str], float, float]:
    if isinstance(inner, str):
        parts = [p.strip() for p in inner.split(",") if p.strip()]
    else:
        parts = [p.strip() for p in inner if str(p).strip()]
    if len(parts) < 3:
        raise ValueError("Expected format \\plot(f1,f2,...,a,b)")
    *funcs, a_str, b_str = parts
    contexto = ctx.eval_context()

    def _as_float(raw: str) -> float:
        expr_py = ctx.latex_to_python(raw)
        try:
            value = eval(expr_py, contexto)
        except Exception as exc:  # pragma: no cover - invalid input only
            raise ValueError(f"Error while evaluating limit '{raw}': {exc}") from exc
        try:
            return float(value)
        except Exception as exc:  # pragma: no cover
            raise ValueError(f"The limit '{raw}' is not numeric (got {value!r}).") from exc

    return funcs, _as_float(a_str), _as_float(b_str)


def handle_functions(linea: str, ctx: ParserContext) -> bool:
    """Procesa comandos relacionados con funciones, derivadas y gráficos."""
    env_ast = ctx.env_ast
    latex_to_python = ctx.latex_to_python
    expr_to_python = ctx.expr_to_python or latex_to_python
    greek_display = ctx.greek_display
    x_sym = ctx.common_symbols.get("x")

    # \error(mensaje)
    if linea.startswith(r"\error(") and linea.endswith(")"):
        inner = linea[linea.find("(") + 1 : linea.rfind(")")]
        msg = inner.strip() or "error"
        try:
            msg_val = eval(latex_to_python(inner), ctx.eval_context())
            msg = str(msg_val)
        except Exception:
            msg = inner.strip() or "error"
        print(f"error: {msg}")
        return True

    # \print(...) - similar a disp/printf/fprintf de Octave
    if linea.startswith(r"\print"):
        inner = linea[linea.find("(") + 1 : linea.rfind(")")]
        parts = _split_args(inner)
        if not parts:
            print()
            return True
        values: list[Any] = []
        for part in parts:
            try:
                values.append(eval(latex_to_python(part), ctx.eval_context()))
            except Exception:
                values.append(part)

        def _fmt(val: Any) -> str:
            if isinstance(val, MatrixBase):
                return matrix_to_str(val, greek_display)
            return format_value_for_display(val)

        if isinstance(values[0], str) and len(values) > 1:
            fmt = values[0]
            args = tuple(values[1:])
            try:
                out_text = fmt % args
            except Exception:
                out_text = fmt + " " + " ".join(_fmt(v) for v in args)
        else:
            out_text = " ".join(_fmt(v) for v in values)
        print(out_text)
        return True

    # Definición de funciones
    m_format = re.match(r"^\\format\(([^()]*)\)\s*$", linea, re.IGNORECASE)
    if m_format:
        raw_mode = m_format.group(1).strip()
        if not raw_mode:
            print(r"Usage: \format(short|long|shorte|longe|bank)")
            return True
        try:
            set_numeric_format(raw_mode)
        except ValueError as exc:
            print(exc)
        return True

    def _expand_derivatives(expr: str) -> str:
        def repl(match: re.Match[str]) -> str:
            fname = match.group(1)
            vars_part = match.group(2)
            if not vars_part:
                return f"diff({fname})"
            args = ", ".join(a.strip() for a in vars_part.split(",") if a.strip())
            if not args:
                return f"diff({fname})"
            return f"diff({fname}, {args})"

        return re.sub(r"\b([a-zA-Z_]\w*)'(?:\(([^()]*)\))?", repl, expr)

    m_figure = re.match(r"^\\figure\((.*)\)\s*$", linea, re.IGNORECASE)
    if m_figure:
        if ctx.plot_backend is None:
            print("Internal error: plot backend is unavailable.")
            return True
        raw_idx = m_figure.group(1).strip()
        if not raw_idx:
            print("Usage: \\figure(n)")
            return True
        try:
            idx_value = eval(latex_to_python(raw_idx), ctx.eval_context())
        except Exception:
            idx_value = raw_idx
        try:
            ctx.plot_backend.set_figure(idx_value)
        except Exception as exc:
            print(f"Error en \\figure: {exc}")
        return True

    m_plot_label = re.match(r"^\\(title|xlabel|ylabel)\((.*)\)\s*$", linea, re.IGNORECASE)
    if m_plot_label:
        if ctx.plot_backend is None:
            print("Internal error: plot backend is unavailable.")
            return True
        cmd, raw_value = m_plot_label.groups()
        try:
            value = eval(latex_to_python(raw_value), ctx.eval_context())
        except Exception:
            value = raw_value.strip().strip("\"'")
        value_str = str(value)
        if cmd.lower() == "title":
            ctx.plot_backend.title(value_str)
        elif cmd.lower() == "xlabel":
            ctx.plot_backend.xlabel(value_str)
        else:
            ctx.plot_backend.ylabel(value_str)
        return True

    m_plot_toggle = re.match(r"^\\(hold|grid)\((.*)\)\s*$", linea, re.IGNORECASE)
    if m_plot_toggle:
        if ctx.plot_backend is None:
            print("Internal error: plot backend is unavailable.")
            return True
        cmd, raw_state = m_plot_toggle.groups()
        token = raw_state.strip().strip("\"'").lower()
        if token not in {"on", "off"}:
            print(f"Error: {cmd.lower()} expects on/off.")
            return True
        if cmd.lower() == "hold":
            ctx.plot_backend.set_hold(token)
        else:
            ctx.plot_backend.set_grid(token)
        return True

    if linea.strip().lower() == r"\legend":
        if ctx.plot_backend is None:
            print("Internal error: plot backend is unavailable.")
            return True
        try:
            ctx.plot_backend.legend()
        except Exception as exc:
            print(f"Error en \\legend: {exc}")
        return True

    m_legend = re.match(r"^\\legend\((.*)\)\s*$", linea, re.IGNORECASE)
    if m_legend:
        if ctx.plot_backend is None:
            print("Internal error: plot backend is unavailable.")
            return True
        inner = m_legend.group(1).strip()
        if not inner:
            args_legend: list[Any] = []
        else:
            args_legend = []
            for raw_arg in _split_args(inner):
                token = raw_arg.strip()
                if not token:
                    continue
                try:
                    value = eval(latex_to_python(token), ctx.eval_context())
                except Exception:
                    value = token.strip().strip("\"'")
                args_legend.append(value)
        try:
            ctx.plot_backend.legend(*args_legend)
        except Exception as exc:
            print(f"Error en \\legend: {exc}")
        return True

    m_func = re.match(r"([a-zA-Z_]\w*)\(([^)]*)\)\s*=\s*(.+)", linea)
    if m_func:
        fname, args_str, expr_str = m_func.groups()
        existing = env_ast.get(fname)
        if isinstance(existing, (MatrixBase, list, tuple)):
            return False
        expr_str = _expand_derivatives(expr_str)
        args = [a.strip() for a in args_str.split(",") if a.strip()]
        if not args:
            print("Error: variables must be specified, e.g. f(x) or f(x,y)")
            return True
        try:
            expr_str = _rewrite_index_calls(expr_str, ctx, args)
            vars_syms = symbols(",".join(args))
            if not isinstance(vars_syms, (tuple, list)):
                vars_syms = (vars_syms,)
            expr_parsed = latex_to_python(expr_str)
            env_ast.setdefault("_mt_get1", _mt_get1)
            env_ast.setdefault("_mt_get2", _mt_get2)
            contexto_func = ctx.eval_context({"_mt_get1": _mt_get1, "_mt_get2": _mt_get2})
            for v in vars_syms:
                contexto_func[str(v)] = v
            f_expr = eval(expr_parsed, contexto_func)
            env_ast[fname] = f_expr
            env_ast[f"{fname}_vars"] = vars_syms
            env_ast[f"{fname}_expr_py"] = expr_parsed
            print(f"Function {fname} defined with variables {args}.")
        except Exception as e:
            print(f"Error al definir {fname}: {e}")
        return True

    # Gráfico 3D
    if linea.startswith(r"\plot3(") and linea.endswith(")"):
        if ctx.plot3_func is None:
            print("Internal error: 3D plotter is unavailable.")
            return True
        inner = linea[7:-1].strip()
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        if len(parts) not in {1, 5, 7}:
            print("Usage: \\plot3(f) or \\plot3(f, a, b, c, d) or \\plot3(f, x, y, a, b, c, d)")
            return True

        fname = parts[0]
        if fname not in env_ast:
            print(f"Function {fname} is not defined.")
            return True

        f_expr = env_ast[fname]
        vars_info = env_ast.get(f"{fname}_vars", [])
        if len(vars_info) < 2:
            print(f"Function {fname} must have at least two variables to plot in 3D.")
            return True

        def _eval_bound(raw: str) -> float:
            try:
                return float(eval(latex_to_python(raw), ctx.eval_context()))
            except Exception as exc:
                raise ValueError(f"Could not evaluate '{raw}' as a number: {exc}") from exc

        try:
            if len(parts) == 1:
                a = -5
                b = 5
                c = -5
                d = 5
                ctx.plot3_func(f_expr, vars_info[0], vars_info[1], a, b, c, d)
                return True
            if len(parts) == 5:
                a, b, c, d = [_eval_bound(p) for p in parts[1:]]
                ctx.plot3_func(f_expr, vars_info[0], vars_info[1], a, b, c, d)
                return True
            x_var, y_var, a_str, b_str, c_str, d_str = parts[1:]
            try:
                x_local = symbols(x_var)
                y_local = symbols(y_var)
            except Exception:
                print("Invalid variables for \\plot3.")
                return True
            a = _eval_bound(a_str)
            b = _eval_bound(b_str)
            c = _eval_bound(c_str)
            d = _eval_bound(d_str)
            ctx.plot3_func(f_expr, x_local, y_local, a, b, c, d)
        except Exception as e:
            print(f"Error while plotting: {e}")
        return True

    # Graficar funciones 1D/2D
    if linea.startswith(r"\plot(") and linea.endswith(")"):
        if ctx.plot_func is None:
            print("Internal error: plotting function is unavailable.")
            return True
        inner = linea[6:-1].strip()
        raw_args = _split_args(inner) if inner else []
        if not raw_args:
            print("Usage: \\plot(y), \\plot(x,y), \\plot(x,y,fmt).")
            return True

        plot_name: str | None = None
        plot_args: list[str] = []
        for raw_arg in raw_args:
            token = raw_arg.strip()
            m_name = re.match(r"^name\s*=\s*(.+)$", token, re.IGNORECASE)
            if m_name:
                if plot_name is not None:
                    print("Error in \\plot: repeated name argument.")
                    return True
                rhs = m_name.group(1).strip()
                if not rhs:
                    print("Error in \\plot: name cannot be empty.")
                    return True
                if (rhs.startswith("'") and rhs.endswith("'")) or (rhs.startswith('"') and rhs.endswith('"')):
                    plot_name = rhs[1:-1]
                else:
                    try:
                        name_val = eval(latex_to_python(rhs), ctx.eval_context())
                    except Exception as exc:
                        print(f"Error in \\plot: could not evaluate name ({exc}).")
                        return True
                    plot_name = str(name_val)
                continue
            plot_args.append(token)

        # Compatibilidad: ultimo argumento string como nombre del plot
        if plot_name is None and len(plot_args) >= 4:
            maybe_name = plot_args[-1].strip()
            if (
                (maybe_name.startswith("'") and maybe_name.endswith("'"))
                or (maybe_name.startswith('"') and maybe_name.endswith('"'))
            ):
                plot_name = maybe_name[1:-1]
                plot_args = plot_args[:-1]

        # Compatibilidad con sintaxis legacy: \plot(f1,f2,...,a,b)
        if len(plot_args) > 3:
            try:
                funcs, a, b = _parse_plot_args(plot_args, ctx)
            except ValueError as e:
                print(e)
                return True
            ctx.plot_func(*funcs, a=a, b=b, name=plot_name)
            return True

        resolved_args: list[Any] = []
        for raw_arg in plot_args:
            token = raw_arg.strip()
            if not token:
                continue
            try:
                resolved = eval(latex_to_python(token), ctx.eval_context())
            except Exception:
                if (token.startswith("'") and token.endswith("'")) or (token.startswith('"') and token.endswith('"')):
                    resolved = token[1:-1]
                else:
                    print(f"Error while evaluating \\plot argument: '{token}'.")
                    return True
            resolved_args.append(resolved)
        try:
            ctx.plot_func(*resolved_args, name=plot_name)
        except Exception as exc:
            print(f"Error in \\plot: {exc}")
        return True

    # Newton-Raphson
    if linea.startswith(r"\NR"):
        if ctx.nr_func is None:
            print("Internal error: NR routine is unavailable.")
            return True
        inner = linea[linea.find("(") + 1 : linea.rfind(")")]
        expr_str, x0_str, tol_str = [p.strip() for p in inner.split(",")]
        expr_str = re.sub(r"(\w+)'", r"diff(\1)", expr_str)
        expr_str = latex_to_python(expr_str)
        try:
            F_sym = eval(expr_str, ctx.eval_context())
        except Exception as e:
            print(f"Error while evaluating {expr_str}: {e}")
            return True
        ctx_eval = ctx.eval_context()

        def _resolve_numeric(token: str) -> float:
            token = token.strip()
            if token in ctx_eval:
                return float(ctx_eval[token])
            return float(eval(latex_to_python(token), ctx_eval))

        try:
            x0_num = _resolve_numeric(x0_str)
            tol_num = _resolve_numeric(tol_str)
        except Exception as e:
            print(f"Error al interpretar x0 o la tolerancia: {e}")
            return True
        ctx.nr_func(F_sym, x0_num, tol_num)
        return True

    # Evaluación directa de derivadas en un punto: f'(valor)
    m_deriv_eval = re.match(r"([a-zA-Z_]\w*)'\((.+)\)", linea)
    if m_deriv_eval:
        fname, val_str = m_deriv_eval.groups()
        if fname not in env_ast:
            print(f"Function {fname} is not defined.")
            return True
        try:
            val_expr = eval(val_str, ctx.eval_context())
            deriv_sym = diff(env_ast[fname])
            res = deriv_sym.subs(x_sym, val_expr)
            print(f"{fname}'({val_str}) = {format_value_for_display(res)}")
        except Exception as e:
            print(f"Error while evaluating the derivative of {fname} at {val_str}: {e}")
        return True

    # Derivadas f'(x) y diff(f, ...)
    if (linea.startswith(r"\diff(") or linea.startswith("diff(")) and linea.endswith(")"):
        inner = linea[linea.find("(") + 1 : linea.rfind(")")]
        parts = _split_args(inner)
        if not parts:
            print("Usage: \\diff(f[, x[, y...]]).")
            return True

        fname, *raw_vars = parts
        if fname not in env_ast:
            print(f"Function {fname} is not defined.")
            return True

        f_expr = env_ast[fname]
        ctx_eval = ctx.eval_context()
        deriv_args: list[Any] = []

        def _append_arg(token: str) -> None:
            token = token.strip()
            if not token:
                return
            try:
                deriv_args.append(eval(latex_to_python(token), ctx_eval))
            except Exception:
                deriv_args.append(symbols(token))

        for rv in raw_vars:
            rv = rv.strip()
            if not rv:
                continue
            if rv.startswith("[") and rv.endswith("]"):
                for nested in _split_args(rv[1:-1]):
                    _append_arg(nested)
            else:
                _append_arg(rv)

        if not deriv_args:
            deriv_args = [x_sym]

        try:
            deriv_sym = diff(f_expr, *deriv_args)
            printed_vars = ", ".join(raw_vars) if raw_vars else "x"
            print(f"diff({fname}, {printed_vars}) = {format_value_for_display(deriv_sym)}")
        except Exception as e:
            print(f"Error al derivar {fname}: {e}")
        return True

    # Evaluación de funciones f(arg1, arg2, ...)
    m_eval = re.match(r"([a-zA-Z_]\w*)\(([^)]*)\)", linea)
    if m_eval:
        fname, args_str = m_eval.groups()
        if fname in env_ast and isinstance(env_ast[fname], MatrixBase):
            # Dejar que el parser de matrices maneje llamadas tipo A(i,j)
            return False
        if fname not in env_ast:
            try:
                res_generic = eval(expr_to_python(linea), ctx.eval_context())
                s_generic = str(res_generic)
                for g, symb in greek_display.items():
                    s_generic = re.sub(rf"\b{g}\b", symb, s_generic)
                print(s_generic)
            except Exception as exc:
                if fname in ctx.common_symbols:
                    print(f"Error while evaluating {fname}: {exc}")
                else:
                    print(f"Function {fname} is not defined.")
            return True

        f_expr = env_ast[fname]
        vars_info = env_ast.get(f"{fname}_vars", [x_sym])
        args = _split_args(args_str)
        if len(args) != len(vars_info) and not (len(args) == 1 and len(vars_info) > 1):
            print(f"Error: function {fname} expects {len(vars_info)} argument(s).")
            return True

        try:
            contexto_eval = ctx.eval_context()
            arg_exprs: List[Any] = []
            for a in args:
                try:
                    val = eval(expr_to_python(a), contexto_eval)
                except Exception:
                    val = symbols(a)
                arg_exprs.append(val)

            mt_call = contexto_eval.get("_mt_call")
            if callable(mt_call):
                res = mt_call(fname, *arg_exprs)
            else:
                arg_exprs = _expand_function_args(arg_exprs, len(vars_info))
                if len(arg_exprs) != len(vars_info):
                    print(f"Error: function {fname} expects {len(vars_info)} argument(s).")
                    return True
                subs_map = {vars_info[i]: arg_exprs[i] for i in range(len(vars_info))}
                res = f_expr.subs(subs_map)

            if all(isinstance(v, (int, float)) or getattr(v, "is_number", False) for v in arg_exprs):
                res = res.evalf()

            if any(getattr(v, "is_symbol", False) for v in arg_exprs):
                name_suffix = "_of_" + "_".join(a.replace("\\", "") for a in args)
                env_ast[f"{fname}{name_suffix}"] = res

            s = str(res)
            for g, symb in greek_display.items():
                s = re.sub(rf"\b{g}\b", symb, s)
            print(f"{fname}({', '.join(args)}) = {format_value_for_display(s)}")
        except Exception as e:
            print(f"Error while evaluating {fname}({args_str}): {e}")
        return True

    return False
