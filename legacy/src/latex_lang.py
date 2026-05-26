import io
import ast
import math
import re
import sys
import types
import os
import keyword
import time
import tempfile
from dataclasses import dataclass
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Callable, List, Optional, Any
import numpy as np
from scipy import linalg as scipy_linalg
from scipy.optimize import newton as scipy_newton
from plot_backend import PlotBackend, PlotBackendError
from sympy import pprint, sstr, Matrix
import sympy as sp
from sympy.core.relational import Relational
from sympy.printing.pretty import pretty as sym_pretty
from sympy import (
    symbols,
    Eq,
    lambdify,
    diff,
    sin,
    cos,
    tan,
    sinh,
    cosh,
    tanh,
    asin,
    acos,
    atan,
    exp,
    log,
    ln,
    sqrt,
    pi,
    Abs,
    sign,
    floor,
    ceiling,
    Pow,
    Rational,
    integrate,
    oo,
    E,
    together,
    simplify,
    Matrix,
    Max,
    Add,
    Mul,
    I,
    re as sym_re,
    im as sym_im,
    conjugate,
    arg,
    Function,
    dsolve,
    Sum,
    Product,
)
from sympy.matrices import MatrixBase
from ast_codegen import ast_to_python
from ast_optimize import optimize_ast
from diagnostics import (
    MathTeXBlockError,
    MathTeXDiagnostic,
    MathTeXParseError,
    MathTeXRuntimeError,
    diagnostic_line_offset,
    make_block_error,
    make_runtime_error,
    parse_error_from_syntax_error,
    render_error_for_display,
    runtime_error_from_exception,
)
from mathtex_ast import (
    ASTNode,
    AssignNode,
    BlockNode,
    ExprStmtNode,
    IndexAssignNode,
    RangeNode,
    SliceNode,
    SymbolNode,
)
from parser_common import (
    _find_matching_paren,
    _has_disabled_apostrophe_operator,
    _is_apostrophe_operator,
    _replace_cmd,
    _replace_cmd_outside_strings,
    _split_top_level,
)
from parser_config import (
    GREEK_ALIAS_PREFIX,
    GREEK_CMD_TO_ALIAS,
    PARSER_TRANSFORMATIONS,
    PROTECTED_FUNCS as _PROTECTED_FUNCS,
    RESERVED_KEYWORD_ALIASES,
    build_expr_parser_config,
    greek_alias,
    greek_display,
    greek_letters_lower,
    greek_letters_upper,
    greek_symbols,
    normalize_name,
)
from parser_expr import (
    latex_to_python as _latex_to_python_impl,
    oct_expr_to_python as _oct_expr_to_python_impl,
    oct_index_code as _oct_index_code_impl,
    oct_replace_indices as _oct_replace_indices_impl,
    parse_mathtex_expr as _parse_mathtex_expr_impl,
    _replace_user_function_calls as _replace_user_function_calls_impl,
)
from parser_indices import (
    parse_index_component as _parse_index_component_impl,
    parse_indexed_assignment_lhs as _parse_indexed_assignment_lhs_impl,
)
from parser_symbols import build_parser_base_symbols, build_parser_symbol_registry
from runtime_symbols import build_runtime_shared_symbols, register_shared_symbols
from parser_statements import parse_mathtex_line as _parse_mathtex_line_impl
from numeric_format import format_value_for_display, reset_numeric_format, set_numeric_format

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _ensure_matplotlib_plot3():
    import matplotlib.pyplot as plt
    from matplotlib import cm

    return plt, cm

from parsers import (
    ParserContext,
    handle_complex_numbers,
    handle_functions,
    handle_inner_products,
    handle_integrals,
    handle_matrices,
    handle_norms,
    handle_odes,
    handle_sums_products,
    matrix_to_str,
    normalize_matrix_expr,
    solve_linear_system_octave,
)

x = symbols('x')  # Variable simbólica global

# ==========================================================
# Símbolos griegos (mayúsculas y minúsculas, estilo LaTeX)
# ==========================================================
_INTERNAL_RESERVED_NAMES = {"mathtex", "env", "env_ast", "np", "sympy", "sp"}
for name in greek_letters_lower + greek_letters_upper:
    globals()[name] = greek_symbols[name]


def _greek_alias(name: str) -> str:
    return greek_alias(name)

# ----------------------------------------------------------
# Utilidades de nombres
# ----------------------------------------------------------

def _display_name(name: str, raw: str | None = None) -> str:
    """Devuelve el nombre listo para mostrar, usando simbolos griegos solo si el usuario los escribio con '\\'."""
    source = raw if raw is not None else name
    stripped = source.strip()
    if stripped.startswith("\\"):
        base = stripped.lstrip("\\")
        return greek_display.get(base, base)
    if name.startswith(GREEK_ALIAS_PREFIX):
        base = name[len(GREEK_ALIAS_PREFIX):]
        return base
    clean = _normalize_name(source)
    if clean.startswith(GREEK_ALIAS_PREFIX):
        return clean[len(GREEK_ALIAS_PREFIX):]
    return clean


def _normalize_name(raw: str) -> str:
    """Normaliza un nombre eliminando barras inversas y espacios extra."""
    return normalize_name(raw)


def _strip_comments(line: str) -> str:
    """Elimina comentarios % o # ignorando los que estA-n dentro de cadenas."""
    buf: list[str] = []
    in_str = False
    quote = ""
    escape = False
    for idx, ch in enumerate(line):
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
            if ch == "'" and _is_apostrophe_operator(line, idx):
                buf.append(ch)
                continue
            in_str = True
            quote = ch
            buf.append(ch)
            continue
        if ch in {"%", "#"}:
            break
        buf.append(ch)
    return "".join(buf)

def _split_top_level_equation(expr: str) -> tuple[str, str] | None:
    """Detecta una igualdad a nivel tope usando '=' (no incluye ==, <=, >=, !=)."""
    depth_paren = 0
    depth_brack = 0
    depth_brace = 0
    in_str = False
    quote = ""
    escape = False
    eq_idx: int | None = None
    for i, ch in enumerate(expr):
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
            prev = expr[i - 1] if i > 0 else ""
            if ch == "'" and (prev.isalnum() or prev in {")", "]", "_"}):
                continue
            in_str = True
            quote = ch
            continue
        if ch == "(":
            depth_paren += 1
            continue
        if ch == ")":
            depth_paren = max(depth_paren - 1, 0)
            continue
        if ch == "[":
            depth_brack += 1
            continue
        if ch == "]":
            depth_brack = max(depth_brack - 1, 0)
            continue
        if ch == "{":
            depth_brace += 1
            continue
        if ch == "}":
            depth_brace = max(depth_brace - 1, 0)
            continue
        if ch != "=" or depth_paren or depth_brack or depth_brace:
            continue
        prev = expr[i - 1] if i > 0 else ""
        nxt = expr[i + 1] if i + 1 < len(expr) else ""
        if prev in {"<", ">", "!", "="} or nxt == "=":
            continue
        if eq_idx is not None:
            return None
        eq_idx = i
    if eq_idx is None:
        return None
    lhs = expr[:eq_idx].strip()
    rhs = expr[eq_idx + 1 :].strip()
    if not lhs or not rhs:
        return None
    return lhs, rhs


def _normalize_derivatives_inline(txt: str) -> str:
    txt = re.sub(r"([a-zA-Z_]\w*)\^\{\s*\((\d+)\)\s*\}\(x\)", r"diff(\1(x), x, \2)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'''\(x\)", r"diff(\1(x), x, 3)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)''\(x\)", r"diff(\1(x), x, 2)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'\(x\)", r"diff(\1(x), x)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'''\b", r"diff(\1(x), x, 3)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)''\b", r"diff(\1(x), x, 2)", txt)
    txt = re.sub(r"([a-zA-Z_]\w*)'\b", r"diff(\1(x), x)", txt)
    return txt


def _extract_ode_function_names(txt: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r"([a-zA-Z_]\w*)'+(?:\s*\(x\))?", txt):
        names.add(match.group(1))
    return names


def _rewrite_function_calls_for_ode(txt: str, names: set[str]) -> str:
    out = txt
    for name in sorted(names, key=len, reverse=True):
        pattern = rf"\b{name}\s*\(\s*x\s*\)"
        out = re.sub(pattern, f"Function('{name}')(x)", out)
    return out


def _rewrite_solve_inner(inner: str) -> str:
    args = _split_top_level(inner, ",")
    if not args:
        return inner

    ode_names = _extract_ode_function_names(args[0])
    if ode_names:
        args = [_rewrite_function_calls_for_ode(arg, ode_names) for arg in args]

    first = _normalize_derivatives_inline(args[0].strip())
    if ode_names:
        first = _rewrite_function_calls_for_ode(first, ode_names)
    bar_parts = _split_top_level(first, "|")
    if len(bar_parts) == 2 and all(part.strip() for part in bar_parts):
        first = f"_mt_bar({bar_parts[0].strip()}, {bar_parts[1].strip()})"
    else:
        eq_parts = _split_top_level_equation(first)
        if eq_parts is not None and not first.lstrip().startswith("Eq("):
            lhs, rhs = eq_parts
            first = f"Eq({lhs}, {rhs})"
    args[0] = first
    return ", ".join(args)


def _rewrite_solve_calls(text: str) -> str:
    marker = "_mt_solve("
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        idx = text.find(marker, i)
        if idx < 0:
            out.append(text[i:])
            break
        out.append(text[i:idx])
        paren_start = idx + len("_mt_solve")
        paren_end = _find_matching_paren(text, paren_start)
        if paren_end is None:
            out.append(text[idx:])
            break
        inner = text[paren_start + 1 : paren_end]
        inner = _rewrite_solve_calls(inner)
        rewritten_inner = _rewrite_solve_inner(inner)
        out.append(f"_mt_solve({rewritten_inner})")
        i = paren_end + 1
    return "".join(out)

# Diccionarios de funciones
env_ast = {}        # Funciones simbólicas
env_lambdified = {} # Funciones evaluables numéricas
user_norms = {}  # Guarda las normas definidas por el usuario
user_inners = {}
_MISSING = object()
_LOADED_MODULES: dict[str, "MathTeXModule"] = {}
_MODULE_PATH_CACHE: dict[str, "MathTeXModule"] = {}
_MODULE_LOAD_STACK: list[str] = []
_MODULE_LOAD_PATH_STACK: list[str] = []


class MathTeXImportError(Exception):
    pass


@dataclass
class MathTeXModule:
    name: str
    path: Path
    exports: dict[str, Any]
    env: dict[str, Any]

    def get_export(self, name: str) -> Any:
        normalized = _normalize_name(name)
        if normalized.startswith("_") or normalized not in self.exports:
            raise AttributeError(f"Module '{self.name}' has no attribute '{name}'")
        return self.exports[normalized]

    def __getattr__(self, name: str) -> Any:
        return self.get_export(name)


def _same_binding(left: Any, right: Any) -> bool:
    if left is right:
        return True
    try:
        result = left == right
    except Exception:
        return False
    if isinstance(result, (bool, np.bool_)):
        return bool(result)
    return False


def _matches_builtin_binding(name: str, value: Any) -> bool:
    normalized = _normalize_name(name)
    if normalized in COMMON_SYMBOLS:
        return _same_binding(value, COMMON_SYMBOLS[normalized])
    if normalized in greek_symbols:
        return _same_binding(value, greek_symbols[normalized])
    if normalized == "i":
        return _same_binding(value, I)
    return False


def _is_protected_name(name: str, value: Any = _MISSING) -> bool:
    """Indica si un nombre debe ocultarse en el workspace."""
    if not name:
        return True
    cleaned = name.strip()
    if cleaned.startswith("_"):
        return True
    normalized = _normalize_name(cleaned)
    if normalized.startswith("_"):
        return True
    if normalized.startswith(GREEK_ALIAS_PREFIX):
        return True
    if normalized in _INTERNAL_RESERVED_NAMES:
        return True
    has_value = value is not _MISSING
    if normalized in COMMON_SYMBOLS or cleaned in COMMON_SYMBOLS:
        if not has_value:
            return True
        return _matches_builtin_binding(normalized, value)
    if normalized in {"i"}:
        if not has_value:
            return True
        return _matches_builtin_binding(normalized, value)
    if normalized in greek_symbols or cleaned in greek_symbols:
        if not has_value:
            return True
        return _matches_builtin_binding(normalized, value)
    return False


def _iter_workspace_items(env: dict | None = None) -> list[tuple[str, Any]]:
    """Devuelve los pares (nombre, valor) visibles del workspace."""
    target = env if env is not None else env_ast
    visibles: list[tuple[str, Any]] = []
    for name, value in target.items():
        if _is_protected_name(name, value):
            continue
        if isinstance(value, types.ModuleType):
            continue
        visibles.append((name, value))
    visibles.sort(key=lambda item: item[0])
    return visibles


def iter_workspace_items(env: dict | None = None) -> list[tuple[str, Any]]:
    """API pública para obtener los items visibles del workspace."""
    return _iter_workspace_items(env)


def _format_user_function_signature(func: "UserFunction", include_outputs: bool = False) -> str:
    args_txt = ", ".join(func.args)
    base = f"{func.name}({args_txt})"
    if include_outputs and func.outputs:
        outs = ", ".join(func.outputs)
        return f"[{outs}] = {base}"
    return base


def _workspace_value_size(val: Any) -> str:
    if isinstance(val, MatrixBase):
        return f"{val.rows}x{val.cols}"
    if isinstance(val, UserFunction):
        return "function"
    if isinstance(val, (int, float, complex, sp.Number)):
        return "1x1"
    if isinstance(val, np.ndarray):
        try:
            shape = "x".join(str(dim) for dim in val.shape)
            return shape or "-"
        except Exception:
            return "-"
    return "–"


def _workspace_value_class(val: Any) -> str:
    if isinstance(val, MatrixBase):
        return "Matrix"
    if isinstance(val, UserFunction):
        return "UserFunction"
    if isinstance(val, sp.Symbol):
        return "Symbol"
    if isinstance(val, sp.Expr):
        return "sympy expr"
    if isinstance(val, complex):
        return "complex"
    if isinstance(val, float):
        return "float"
    if isinstance(val, int):
        return "int"
    if isinstance(val, np.ndarray):
        return "ndarray"
    if callable(val):
        return "function"
    return type(val).__name__


def _truncate_text(text: str, max_len: int = 80) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _workspace_value_summary(name: str, val: Any, max_len: int = 80) -> str:
    if isinstance(val, UserFunction):
        summary = _format_user_function_signature(val, include_outputs=True)
    elif isinstance(val, MatrixBase):
        if val.rows <= 4 and val.cols <= 4:
            try:
                summary = matrix_to_str(Matrix(val), greek_display)
            except Exception:
                summary = str(val)
        else:
            summary = f"Matrix {val.rows}x{val.cols}"
    elif isinstance(val, np.ndarray):
        summary = f"ndarray shape {val.shape}"
    else:
        summary = format_value_for_display(val)
    summary = re.sub(r"\s+", " ", summary).strip()
    return _truncate_text(summary, max_len=max_len)


def workspace_snapshot(env: dict | None = None) -> list[dict[str, str]]:
    """Devuelve un snapshot del workspace con metadatos para GUI/console."""
    snapshot: list[dict[str, str]] = []
    for name, value in _iter_workspace_items(env):
        size = _workspace_value_size(value)
        cls = _workspace_value_class(value)
        summary = _workspace_value_summary(name, value, max_len=120)
        snapshot.append(
            {
                "name": name,
                "size": size,
                "class": cls,
                "summary": summary,
            }
        )
    return snapshot


def _print_workspace_who(env: dict | None = None) -> None:
    items = _iter_workspace_items(env)
    if not items:
        print("(workspace empty)")
        return
    names = [name for name, _ in items]
    print(" ".join(names))


def _print_workspace_whos(env: dict | None = None) -> None:
    items = _iter_workspace_items(env)
    rows: list[tuple[str, str, str]] = []
    for name, value in items:
        rows.append((name, _workspace_value_size(value), _workspace_value_class(value)))
    if not rows:
        print("(workspace empty)")
        return
    headers = ("Name", "Size", "Class")
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(widths[i], len(str(col))) for i, col in enumerate(row)]
    line_fmt = " ".join(f"{{:<{w}}}" for w in widths)
    print(line_fmt.format(*headers))
    for row in rows:
        print(line_fmt.format(*row))


def _print_workspace_functions(env: dict | None = None) -> None:
    items = _iter_workspace_items(env)
    funcs = [val for _, val in items if isinstance(val, UserFunction)]
    if not funcs:
        print("There are no defined functions.")
        return
    for func in funcs:
        print(_format_user_function_signature(func, include_outputs=True))


def _clear_workspace_name(name: str, env: dict | None = None) -> None:
    target = env if env is not None else env_ast
    cleaned = _normalize_name(name)
    if cleaned in target:
        if _is_protected_name(cleaned, target[cleaned]):
            print(f"Cannot clear '{name}'.")
            return
        target.pop(cleaned, None)
        print(f"{cleaned} removed from the workspace.")
        return
    if _is_protected_name(cleaned):
        print(f"Cannot clear '{name}'.")
        return
    print(f"'{name}' does not exist in the workspace.")


def _short_doc(obj: Any) -> str | None:
    doc = getattr(obj, "__doc__", None)
    if not doc:
        return None
    for line in doc.splitlines():
        text = line.strip()
        if text:
            return text
    return None


def _print_workspace_help(raw_name: str, env: dict | None = None) -> None:
    target = env if env is not None else env_ast
    name = _normalize_name(raw_name)

    def _describe(name_ref: str, value: Any) -> None:
        if isinstance(value, UserFunction):
            print(_format_user_function_signature(value, include_outputs=True))
            return
        if callable(value):
            doc = _short_doc(value)
            if doc:
                print(f"{name_ref}: {doc}")
                return
        cls = _workspace_value_class(value)
        summary = _workspace_value_summary(name_ref, value, max_len=200)
        print(f"{name_ref}: tipo={cls}, valor={summary}")

    if name in target:
        _describe(name, target[name])
        return

    if raw_name in target:
        _describe(raw_name, target[raw_name])
        return

    if name in COMMON_SYMBOLS:
        _describe(name, COMMON_SYMBOLS[name])
        return

    candidate = globals().get(name)
    if candidate is not None and not name.startswith("_"):
        _describe(name, candidate)
        return

    print(f"No help available for '{raw_name}'.")

def _ensure_integer(value, label: str) -> int:
    try:
        sym_val = sp.sympify(value)
    except Exception as exc:
        raise ValueError(f"{label} must be an integer: {exc}") from exc
    if sym_val.is_real is False:
        raise ValueError(f"{label} must be real.")
    try:
        int_val = int(sym_val)
    except Exception as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if sp.Integer(int_val) != sym_val:
        raise ValueError(f"{label} must be an integer.")
    return int_val

def _ensure_dimension(value, label: str) -> int:
    dim = _ensure_integer(value, label)
    if dim < 0:
        raise ValueError(f"{label} must be >= 0.")
    return dim

def _rand_matrix(rows, cols):
    r = _ensure_dimension(rows, "El numero de filas")
    c = _ensure_dimension(cols, "El numero de columnas")
    if r == 0 or c == 0:
        return Matrix.zeros(r, c)
    data = np.random.rand(r, c)
    return Matrix(data.tolist())

def _randi_matrix(low, high, rows, cols):
    a = _ensure_integer(low, "El limite inferior")
    b = _ensure_integer(high, "El limite superior")
    if b < a:
        raise ValueError("The upper bound must be >= the lower bound.")
    r = _ensure_dimension(rows, "El numero de filas")
    c = _ensure_dimension(cols, "El numero de columnas")
    if r == 0 or c == 0:
        return Matrix.zeros(r, c)
    data = np.random.randint(a, b + 1, size=(r, c))
    return Matrix(data.tolist())

def _orth(matrix, tol=None):
    """Aproximacion estilo Octave de orth(): base ortonormal para el espacio columna."""
    try:
        mat = Matrix(matrix)
    except Exception as exc:
        raise ValueError("orth: the argument must be a convertible matrix") from exc

    rows, cols = mat.shape
    if rows == 0 or cols == 0:
        return Matrix.zeros(rows, 0)

    try:
        U, S_diag, _ = mat.singular_value_decomposition()
    except Exception as exc:
        raise ValueError(f"orth: could not compute the SVD ({exc})") from exc

    sv_count = min(S_diag.rows, S_diag.cols)
    singular_values = [S_diag[idx, idx] for idx in range(sv_count)]

    def _sv_as_float(val):
        try:
            return float(abs(complex(sp.N(val, 50))))
        except Exception:
            try:
                return float(abs(complex(val.evalf())))
            except Exception:
                return 0.0

    sv_numeric = [_sv_as_float(val) for val in singular_values]
    if tol is None:
        max_sv = max(sv_numeric) if sv_numeric else 0.0
        tol_value = max(mat.shape) * np.finfo(float).eps * max_sv
    else:
        try:
            tol_value = float(tol)
        except Exception:
            try:
                tol_value = float(sp.N(tol))
            except Exception as exc:
                raise ValueError(f"orth: invalid tolerance ({exc})") from exc

    keep_indices = [idx for idx, sval in enumerate(sv_numeric) if sval > tol_value]
    if not keep_indices:
        return Matrix.zeros(rows, 0)

    basis_cols = [U[:, idx] for idx in keep_indices]
    return Matrix.hstack(*basis_cols)


def _oct_range(start, end, step=1):
    """Rango inclusivo estilo Octave (1-based)."""
    s = _ensure_integer(start, "inicio del for")
    e = _ensure_integer(end, "fin del for")
    st = _ensure_integer(step, "paso del for")
    if st == 0:
        raise ValueError("The for-step cannot be 0.")
    if st > 0:
        return range(s, e + 1, st)
    return range(s, e - 1, st)


def _oct_get2(name, row, col):
    if name not in env_ast:
        raise make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=f"{name}({row}, {col})",
            hint="Define the matrix before indexing it.",
        )
    mat = env_ast[name]
    if not isinstance(mat, MatrixBase):
        raise make_runtime_error(
            "invalid-index-target",
            f"{name} is not a matrix.",
            source=f"{name}({row}, {col})",
            hint="Use two indices only on matrices.",
        )
    r_idx = _ensure_integer(row, "fila") - 1
    c_idx = _ensure_integer(col, "columna") - 1
    try:
        return mat[r_idx, c_idx]
    except IndexError as exc:
        raise make_runtime_error(
            "index-out-of-range",
            f"Index ({r_idx + 1}, {c_idx + 1}) is out of range for {name}.",
            source=f"{name}({row}, {col})",
            hint=f"{name} has shape {mat.rows}x{mat.cols}.",
        ) from exc


def _oct_get1(name, idx):
    if name not in env_ast:
        raise make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=f"{name}({idx})",
            hint="Define the vector or matrix before indexing it.",
        )
    mat = env_ast[name]
    if not isinstance(mat, MatrixBase):
        raise make_runtime_error(
            "invalid-index-target",
            f"{name} is not a vector/matrix.",
            source=f"{name}({idx})",
            hint="Use single-index access only on vectors or matrices.",
        )
    pos = _ensure_integer(idx, "indice") - 1
    try:
        if mat.rows == 1:
            return mat[0, pos]
        if mat.cols == 1:
            return mat[pos, 0]
        return mat[pos, 0]
    except IndexError as exc:
        raise make_runtime_error(
            "index-out-of-range",
            f"Index {pos + 1} is out of range for {name}.",
            source=f"{name}({idx})",
            hint=f"{name} contains {mat.rows * mat.cols} element(s).",
        ) from exc


def _oct_set2(name, row, col, value):
    if name not in env_ast:
        raise make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=f"{name}({row}, {col})",
            hint="Define the matrix before assigning into it.",
        )
    mat = env_ast[name]
    if not isinstance(mat, MatrixBase):
        raise make_runtime_error(
            "invalid-index-target",
            f"{name} is not a matrix.",
            source=f"{name}({row}, {col})",
            hint="Use two indices only on matrices.",
        )
    r_idx = _ensure_integer(row, "fila") - 1
    c_idx = _ensure_integer(col, "columna") - 1
    # MatrixBase does not support item assignment; create a new matrix with the value changed
    mat_list = mat.tolist()
    try:
        mat_list[r_idx][c_idx] = value
    except IndexError as exc:
        raise make_runtime_error(
            "index-out-of-range",
            f"Index ({r_idx + 1}, {c_idx + 1}) is out of range for {name}.",
            source=f"{name}({row}, {col})",
            hint=f"{name} has shape {mat.rows}x{mat.cols}.",
        ) from exc
    new_mat = Matrix(mat_list)
    env_ast[name] = new_mat
    return new_mat

def _oct_set1(name, idx, value):
    if name not in env_ast:
        raise make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=f"{name}({idx})",
            hint="Define the vector or matrix before assigning into it.",
        )
    mat = env_ast[name]
    if not isinstance(mat, MatrixBase):
        raise make_runtime_error(
            "invalid-index-target",
            f"{name} is not a vector/matrix.",
            source=f"{name}({idx})",
            hint="Use single-index assignment only on vectors or matrices.",
        )
    pos = _ensure_integer(idx, "indice") - 1
    mat_list = mat.tolist()
    try:
        if mat.rows == 1:
            mat_list[0][pos] = value
        else:
            mat_list[pos][0] = value
    except IndexError as exc:
        raise make_runtime_error(
            "index-out-of-range",
            f"Index {pos + 1} is out of range for {name}.",
            source=f"{name}({idx})",
            hint=f"{name} contains {mat.rows * mat.cols} element(s).",
        ) from exc
    new_mat = Matrix(mat_list)
    env_ast[name] = new_mat
    return new_mat


def _normalize_column(vec: MatrixBase) -> Matrix:
    """Normaliza un vector columna (norma 1) si es posible."""
    col = Matrix(vec)
    try:
        norm_sq = sp.simplify((col.conjugate().T * col)[0])
        if norm_sq == 0:
            return col
        norm = sp.sqrt(norm_sq)
        if norm == 0:
            return col
        return Matrix(sp.simplify(col / norm))
    except Exception:
        return col


def _mat_null(matrix_like):
    """Devuelve la matriz cuyas columnas son una base del espacio nulo, normalizada."""
    try:
        mat = Matrix(matrix_like)
    except Exception:
        mat = matrix_like if isinstance(matrix_like, MatrixBase) else Matrix(matrix_like)
    nulls = [_normalize_column(v) for v in mat.nullspace()]
    return Matrix.hstack(*nulls) if nulls else Matrix.zeros(mat.rows, 0)


def _is_sympy_matrix(val: Any) -> bool:
    return isinstance(val, MatrixBase)


def _is_numpy_array(val: Any) -> bool:
    return isinstance(val, np.ndarray)


def _is_scalar(val: Any) -> bool:
    if _is_sympy_matrix(val) or _is_numpy_array(val):
        return False
    return True


def _as_int_if_integer(val: Any) -> int | None:
    if isinstance(val, (int, np.integer)):
        return int(val)
    if isinstance(val, float) and val.is_integer():
        return int(val)
    if isinstance(val, sp.Integer):
        return int(val)
    if isinstance(val, sp.Number) and getattr(val, "is_integer", False):
        try:
            return int(val)
        except Exception:
            return None
    return None


def _raise_mixed_types() -> None:
    raise ValueError("Cannot mix SymPy matrices with NumPy arrays in the same operation.")


def _mt_mul(a: Any, b: Any):
    if _is_sympy_matrix(a) and _is_numpy_array(b):
        _raise_mixed_types()
    if _is_numpy_array(a) and _is_sympy_matrix(b):
        _raise_mixed_types()
    if _is_sympy_matrix(a) and _is_sympy_matrix(b):
        try:
            return a * b
        except Exception as exc:
            raise runtime_error_from_exception(exc, source="A * B", line=None) from exc
    if _is_numpy_array(a) and _is_numpy_array(b):
        try:
            return np.matmul(a, b)
        except Exception as exc:
            raise runtime_error_from_exception(exc, source="A * B", line=None) from exc
    if _is_sympy_matrix(a):
        try:
            return a * b
        except Exception as exc:
            raise runtime_error_from_exception(exc, source="A * B", line=None) from exc
    if _is_sympy_matrix(b):
        try:
            return a * b
        except Exception as exc:
            raise runtime_error_from_exception(exc, source="A * B", line=None) from exc
    if _is_numpy_array(a) or _is_numpy_array(b):
        return np.multiply(a, b)
    return a * b


def _sympy_right_divide(A: Any, B: MatrixBase):
    if B.rows == 0 or B.cols == 0:
        raise ValueError("Cannot divide by an empty matrix.")
    if B.rows == B.cols:
        try:
            inv = B.inv()
        except Exception:
            inv = B.pinv()
    else:
        inv = B.pinv()
    return A * inv


def _numpy_right_divide(A: Any, B: np.ndarray):
    if B.ndim < 2:
        return A / B
    if np.isscalar(A):
        if B.shape[0] == B.shape[1]:
            return A * scipy_linalg.inv(B)
        return A * scipy_linalg.pinv(B)
    A_arr = np.asarray(A)
    if B.shape[0] == B.shape[1]:
        return scipy_linalg.solve(B.T, A_arr.T).T
    return scipy_linalg.lstsq(B.T, A_arr.T)[0].T


def _mt_div(a: Any, b: Any):
    if _is_sympy_matrix(a) and _is_numpy_array(b):
        _raise_mixed_types()
    if _is_numpy_array(a) and _is_sympy_matrix(b):
        _raise_mixed_types()
    if _is_sympy_matrix(b):
        if _is_sympy_matrix(a):
            return _sympy_right_divide(a, b)
        return _sympy_right_divide(a, b)
    if _is_numpy_array(b):
        return _numpy_right_divide(a, b)
    if _is_sympy_matrix(a):
        return a / b
    if _is_numpy_array(a):
        return np.divide(a, b)
    return a / b


def _mt_pow(a: Any, b: Any):
    if _is_sympy_matrix(a):
        exp = _as_int_if_integer(b)
        if exp is None:
            raise ValueError("matrix power requires integer exponent")
        if a.rows != a.cols:
            raise ValueError("matrix power requires square matrix")
        return a ** exp
    if _is_numpy_array(a):
        exp = _as_int_if_integer(b)
        if exp is None:
            raise ValueError("matrix power requires integer exponent")
        if a.ndim != 2 or a.shape[0] != a.shape[1]:
            raise ValueError("matrix power requires square matrix")
        return np.linalg.matrix_power(a, exp)
    return a ** b


def _mt_ew_mul(a: Any, b: Any):
    if _is_sympy_matrix(a) and _is_numpy_array(b):
        _raise_mixed_types()
    if _is_numpy_array(a) and _is_sympy_matrix(b):
        _raise_mixed_types()
    if _is_sympy_matrix(a) and _is_sympy_matrix(b):
        if a.shape != b.shape:
            raise make_runtime_error(
                "incompatible-dimensions",
                "Incompatible dimensions for element-wise product.",
                source="A .* B",
                line=None,
                hint="Check that both operands have the same shape.",
            )
        return a.multiply_elementwise(b)
    if _is_sympy_matrix(a):
        return a * b
    if _is_sympy_matrix(b):
        return a * b
    if _is_numpy_array(a) or _is_numpy_array(b):
        return np.multiply(a, b)
    return a * b


def _mt_ew_div(a: Any, b: Any):
    if _is_sympy_matrix(a) and _is_numpy_array(b):
        _raise_mixed_types()
    if _is_numpy_array(a) and _is_sympy_matrix(b):
        _raise_mixed_types()
    if _is_sympy_matrix(a) and _is_sympy_matrix(b):
        if a.shape != b.shape:
            raise make_runtime_error(
                "incompatible-dimensions",
                "Incompatible dimensions for element-wise division.",
                source="A ./ B",
                line=None,
                hint="Check that both operands have the same shape.",
            )
        rows, cols = a.shape
        return Matrix([[a[i, j] / b[i, j] for j in range(cols)] for i in range(rows)])
    if _is_sympy_matrix(a):
        return a / b
    if _is_sympy_matrix(b):
        rows, cols = b.shape
        return Matrix([[a / b[i, j] for j in range(cols)] for i in range(rows)])
    if _is_numpy_array(a) or _is_numpy_array(b):
        return np.divide(a, b)
    return a / b


def _mt_ew_pow(a: Any, b: Any):
    if _is_sympy_matrix(a) and _is_numpy_array(b):
        _raise_mixed_types()
    if _is_numpy_array(a) and _is_sympy_matrix(b):
        _raise_mixed_types()
    if _is_sympy_matrix(a):
        if _is_sympy_matrix(b):
            if a.shape != b.shape:
                raise make_runtime_error(
                    "incompatible-dimensions",
                    "Incompatible dimensions for element-wise power.",
                    source="A .^ B",
                    line=None,
                    hint="Check that both operands have the same shape.",
                )
            rows, cols = a.shape
            return Matrix([[a[i, j] ** b[i, j] for j in range(cols)] for i in range(rows)])
        return a.applyfunc(lambda v: v ** b)
    if _is_numpy_array(a) or _is_numpy_array(b):
        return np.power(a, b)
    return a ** b


def _mt_transpose(value: Any) -> Any:
    if _is_sympy_matrix(value):
        return value.T
    if _is_numpy_array(value):
        return np.transpose(value)
    transpose_attr = getattr(value, "T", None)
    if transpose_attr is not None and not callable(transpose_attr):
        return transpose_attr
    return value


def _mt_adj(value: Any) -> Any:
    if _is_sympy_matrix(value):
        return value.conjugate().T
    if _is_numpy_array(value):
        return np.conjugate(value).T
    adjoint = getattr(value, "adjoint", None)
    if callable(adjoint):
        try:
            return adjoint()
        except Exception:
            pass
    conjugate_method = getattr(value, "conjugate", None)
    if callable(conjugate_method):
        try:
            return conjugate_method()
        except Exception:
            pass
    return conjugate(value)


def _mt_expand_call_args(args: tuple[Any, ...]) -> list[Any]:
    if len(args) != 1:
        return list(args)
    first_arg = args[0]
    if isinstance(first_arg, (list, tuple)):
        return list(first_arg)
    if isinstance(first_arg, MatrixBase):
        if first_arg.rows == 1:
            return [first_arg[0, idx] for idx in range(first_arg.cols)]
        if first_arg.cols == 1:
            return [first_arg[idx, 0] for idx in range(first_arg.rows)]
        return list(args)
    if _is_numpy_array(first_arg):
        arr = np.array(first_arg)
        if arr.ndim == 1:
            return arr.tolist()
        if arr.ndim == 2 and 1 in arr.shape:
            return arr.reshape(-1).tolist()
    return list(args)


def _mt_ordered_symbols(symbols_iter) -> list[sp.Symbol]:
    return sorted(symbols_iter, key=sp.default_sort_key)


def _mt_apply_value(value: Any, *args: Any) -> Any:
    args_list = _mt_expand_call_args(args)

    if isinstance(value, MatrixBase):
        mat = Matrix(value)
        free_symbols: set[sp.Symbol] = set()
        has_callable_entries = False
        for cell in mat:
            if callable(cell):
                has_callable_entries = True
                continue
            cell_symbols = getattr(cell, "free_symbols", None)
            if cell_symbols:
                free_symbols.update(cell_symbols)
        ordered_symbols = _mt_ordered_symbols(free_symbols)
        if ordered_symbols and len(args_list) != len(ordered_symbols):
            raise make_runtime_error(
                "invalid-call-arity",
                f"The symbolic matrix expects {len(ordered_symbols)} argument(s).",
                line=None,
                hint="Call it with the required number of arguments.",
            )
        if not ordered_symbols and not has_callable_entries:
            raise make_runtime_error(
                "not-callable",
                "The matrix cannot be evaluated with arguments.",
                line=None,
                hint="Only matrices with symbolic entries or callable cells can be applied.",
            )
        subs_map = {var: val for var, val in zip(ordered_symbols, args_list)}
        return mat.applyfunc(
            lambda cell: cell(*args_list) if callable(cell)
            else cell.subs(subs_map) if hasattr(cell, "subs")
            else cell
        )

    if isinstance(value, sp.Expr):
        ordered_symbols = _mt_ordered_symbols(value.free_symbols)
        if len(args_list) != len(ordered_symbols):
            raise make_runtime_error(
                "not-callable" if len(ordered_symbols) == 0 else "invalid-call-arity",
                f"The expression expects {len(ordered_symbols)} argument(s).",
                line=None,
                hint="Call it with the required number of arguments, or remove the call if it is a constant value.",
            )
        subs_map = {var: val for var, val in zip(ordered_symbols, args_list)}
        return value.subs(subs_map)

    if callable(value):
        return value(*args_list)

    raise make_runtime_error(
        "not-callable",
        "The value cannot be applied as a function.",
        line=None,
        hint="Only functions or symbolic expressions with parameters can be called.",
    )


def _mt_call(name: str, *args):
    """Evalua funciones definidas por el usuario (f(x)=...)."""
    if not isinstance(name, str):
        name = str(name)
    expr = env_ast.get(name)
    vars_info = env_ast.get(f"{name}_vars")
    expr_py = env_ast.get(f"{name}_expr_py")
    if vars_info is None:
        if callable(expr):
            try:
                return expr(*args)
            except Exception as exc:
                raise runtime_error_from_exception(exc, source=f"{name}(...)") from exc
        raise make_runtime_error(
            "undefined-function",
            f"Function {name} is not defined.",
            source=f"{name}(...)",
            hint="Define the function before calling it.",
        )
    if not isinstance(vars_info, (list, tuple)):
        vars_list = [vars_info]
    else:
        vars_list = list(vars_info)
    args_list = _mt_expand_call_args(args) if len(vars_list) > 1 else list(args)
    if len(args_list) != len(vars_list):
        raise make_runtime_error(
            "invalid-call-arity",
            f"Function {name} expects {len(vars_list)} argument(s).",
            source=f"{name}(...)",
            hint="Call the function with the required number of arguments.",
        )
    if expr_py and any(_is_sympy_matrix(a) or _is_numpy_array(a) for a in args_list):
        ctx = _build_parser_context()
        scope = ctx.eval_context({"env_ast": env_ast})
        for var, val in zip(vars_list, args_list):
            scope[str(var)] = val
        try:
            expr_eval = _replace_user_function_calls(expr_py, ctx)
            return eval(expr_eval, {"__builtins__": __builtins__}, scope)
        except Exception as exc:
            raise runtime_error_from_exception(
                ValueError(f"Could not evaluate {name}(...): {exc}"),
                source=f"{name}(...)",
                line=None,
            ) from exc

    subs_map = {var: val for var, val in zip(vars_list, args_list)}
    try:
        return expr.subs(subs_map)
    except Exception as exc:
        raise runtime_error_from_exception(
            ValueError(f"Could not evaluate {name}(...): {exc}"),
            source=f"{name}(...)",
            line=None,
        ) from exc


def _mt_apply_symbol(name: str, *args: Any) -> Any:
    if not isinstance(name, str):
        name = str(name)
    if f"{name}_vars" in env_ast:
        return _mt_call(name, *args)
    if name not in env_ast:
        raise make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=f"{name}(...)",
            hint="Define the symbol before applying it.",
        )
    value = env_ast[name]
    try:
        return _mt_apply_value(value, *args)
    except MathTeXRuntimeError as exc:
        if exc.kind == "not-callable":
            raise make_runtime_error(
                "not-callable",
                f"{name} is not callable.",
                source=f"{name}(...)",
                hint="Only functions or symbolic expressions with parameters can be called.",
            ) from exc
        if exc.kind == "invalid-call-arity":
            message = exc.diagnostic.message
            if message.startswith("The expression expects") or message.startswith("The symbolic matrix expects"):
                match = re.search(r"(\d+) argument\(s\)", message)
                expected = match.group(1) if match else "the required number of"
                raise make_runtime_error(
                    "invalid-call-arity",
                    f"{name} expects {expected} argument(s).",
                    source=f"{name}(...)",
                    hint="Call it with the required number of arguments.",
                ) from exc
        raise exc
    except Exception as exc:
        raise runtime_error_from_exception(
            ValueError(f"Could not evaluate {name}(...): {exc}"),
            source=f"{name}(...)",
            line=None,
        ) from exc


def _oct_set_slice(name, row_spec, col_spec, value):
    if name not in env_ast:
        raise make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=f"{name}(...)",
            hint="Define the matrix before assigning into it.",
        )
    mat = env_ast[name]
    if not isinstance(mat, MatrixBase):
        raise make_runtime_error(
            "invalid-index-target",
            f"{name} is not a matrix.",
            source=f"{name}(...)",
            hint="Slice assignment requires a matrix target.",
        )
    row_indices = _oct_eval_indices(row_spec, mat.rows, "fila")
    col_indices = _oct_eval_indices(col_spec, mat.cols, "columna")
    if not row_indices or not col_indices:
        return mat

    if isinstance(value, MatrixBase):
        val_mat = value
    else:
        try:
            val_mat = Matrix(value)
        except Exception:
            val_mat = Matrix([[value]])

    if val_mat.rows == 1 and val_mat.cols == 1:
        val_mat = Matrix([[val_mat[0, 0] for _ in col_indices] for _ in row_indices])

    if val_mat.rows != len(row_indices) or val_mat.cols != len(col_indices):
        raise make_runtime_error(
            "incompatible-dimensions",
            "Incompatible dimensions in slice assignment.",
            source=f"{name}(...)",
            line=None,
            hint="Match the slice shape with the assigned value shape.",
        )

    # Create a copy of the matrix as a list of lists
    mat_list = mat.tolist()
    try:
        for r_idx, real_r in enumerate(row_indices):
            for c_idx, real_c in enumerate(col_indices):
                mat_list[real_r - 1][real_c - 1] = val_mat[r_idx, c_idx]
    except IndexError as exc:
        raise make_runtime_error(
            "index-out-of-range",
            f"Slice index is out of range for {name}.",
            source=f"{name}(...)",
            hint=f"{name} has shape {mat.rows}x{mat.cols}.",
        ) from exc

    new_mat = Matrix(mat_list)
    env_ast[name] = new_mat
    return new_mat

def _oct_span(start, step, end):
    step_value = 1 if step is None else step
    return list(_oct_range(start, end, step_value))


def _oct_eval_indices(spec, length, label):
    if spec == ":":
        return list(range(1, length + 1))
    value = spec
    if isinstance(value, range):
        items = list(value)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    elif isinstance(value, MatrixBase):
        items = [value[row, col] for row in range(value.rows) for col in range(value.cols)]
    else:
        items = [value]
    return [_ensure_integer(item, label) for item in items]


def _oct_slice(name, row_spec, col_spec):
    if name not in env_ast:
        raise make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=f"{name}(...)",
            hint="Define the matrix before indexing it.",
        )
    mat = env_ast[name]
    if not isinstance(mat, MatrixBase):
        raise make_runtime_error(
            "invalid-index-target",
            f"{name} is not a matrix.",
            source=f"{name}(...)",
            hint="Slice access requires a matrix target.",
        )
    row_indices = _oct_eval_indices(row_spec, mat.rows, "fila")
    col_indices = _oct_eval_indices(col_spec, mat.cols, "columna")
    if not row_indices or not col_indices:
        return Matrix.zeros(len(row_indices), len(col_indices))
    try:
        data = [
            [mat[r - 1, c - 1] for c in col_indices]
            for r in row_indices
        ]
    except IndexError as exc:
        raise make_runtime_error(
            "index-out-of-range",
            f"Slice index is out of range for {name}.",
            source=f"{name}(...)",
            hint=f"{name} has shape {mat.rows}x{mat.cols}.",
        ) from exc
    return Matrix(data)
_MATRIX_ADD_ORIG = MatrixBase.__add__
_MATRIX_RADD_ORIG = MatrixBase.__radd__
_MATRIX_RSUB_ORIG = MatrixBase.__rsub__

def _oct_get_any(name, idx):
    """Acceso 1-based seguro para matrices, listas o tuplas."""
    val = name
    if isinstance(name, str):
        if name not in env_ast:
            raise ValueError(f"{name} is not defined.")
        val = env_ast[name]
    if isinstance(val, MatrixBase):
        return val[idx - 1]
    if isinstance(val, np.ndarray):
        return val[idx - 1]
    if isinstance(val, (list, tuple)):
        return val[idx - 1]
    return val


def _mt_reduce_columns(value: Any, reducer: Callable[..., Any], label: str) -> Any:
    if isinstance(value, MatrixBase):
        mat = Matrix(value)
        if mat.rows == 0 or mat.cols == 0:
            raise ValueError(f"{label} does not accept empty matrices.")
        if mat.rows == 1 or mat.cols == 1:
            return reducer(*list(mat))
        col_values = [reducer(*[mat[r, c] for r in range(mat.rows)]) for c in range(mat.cols)]
        return Matrix([col_values])

    if isinstance(value, np.ndarray):
        arr = np.asarray(value, dtype=object)
        if arr.ndim == 0:
            return sp.sympify(arr.item())
        if arr.ndim == 1:
            vals = [sp.sympify(v) for v in arr.tolist()]
            if not vals:
                raise ValueError(f"{label} does not accept empty vectors.")
            return reducer(*vals)
        if arr.ndim == 2:
            mat = Matrix(arr.tolist())
            if mat.rows == 0 or mat.cols == 0:
                raise ValueError(f"{label} does not accept empty matrices.")
            if mat.rows == 1 or mat.cols == 1:
                return reducer(*list(mat))
            col_values = [reducer(*[mat[r, c] for r in range(mat.rows)]) for c in range(mat.cols)]
            return Matrix([col_values])
        raise ValueError(f"{label} only accepts scalars, vectors, or 2D matrices.")

    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError(f"{label} does not accept empty vectors.")
        try:
            mat = Matrix(value)
        except Exception:
            vals = [sp.sympify(v) for v in value]
            return reducer(*vals)
        if mat.rows == 0 or mat.cols == 0:
            raise ValueError(f"{label} does not accept empty matrices.")
        if mat.rows == 1 or mat.cols == 1:
            return reducer(*list(mat))
        col_values = [reducer(*[mat[r, c] for r in range(mat.rows)]) for c in range(mat.cols)]
        return Matrix([col_values])

    return sp.sympify(value)


def _mt_vector_measure_from_shape(
    rows: int,
    cols: int,
    *,
    label: str,
    allow_matrix: bool,
) -> Any:
    if rows <= 0 or cols <= 0:
        raise ValueError(f"{label} does not accept empty arrays.")

    if rows == 1 and cols == 1:
        return sp.Integer(1)
    if rows == 1 or cols == 1:
        return sp.Integer(max(rows, cols))
    if allow_matrix:
        return sp.Integer(rows * cols)
    raise ValueError(f"{label} only accepts scalars or vectors.")


def _mt_nested_sequence(item: Any) -> bool:
    return isinstance(item, (list, tuple, np.ndarray, MatrixBase))


def _mt_length(value: Any) -> Any:
    if isinstance(value, MatrixBase):
        mat = Matrix(value)
        return _mt_vector_measure_from_shape(mat.rows, mat.cols, label="length", allow_matrix=False)

    if isinstance(value, np.ndarray):
        arr = np.asarray(value, dtype=object)
        if arr.size == 0:
            raise ValueError("length does not accept empty arrays.")
        if arr.ndim == 0:
            return sp.Integer(1)
        if arr.ndim == 1:
            return sp.Integer(arr.shape[0])
        if arr.ndim == 2:
            return _mt_vector_measure_from_shape(arr.shape[0], arr.shape[1], label="length", allow_matrix=False)
        raise ValueError("length only accepts scalars or vectors.")

    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError("length does not accept empty arrays.")
        try:
            mat = Matrix(value)
        except Exception:
            if any(_mt_nested_sequence(item) for item in value):
                raise ValueError("length only accepts scalars or vectors.")
            return sp.Integer(len(value))
        return _mt_length(mat)

    return sp.Integer(1)


def _mt_numel(value: Any) -> Any:
    if isinstance(value, MatrixBase):
        mat = Matrix(value)
        return _mt_vector_measure_from_shape(mat.rows, mat.cols, label="numel", allow_matrix=True)

    if isinstance(value, np.ndarray):
        arr = np.asarray(value, dtype=object)
        if arr.size == 0:
            raise ValueError("numel does not accept empty arrays.")
        if arr.ndim <= 2:
            if arr.ndim == 0:
                return sp.Integer(1)
            if arr.ndim == 1:
                return sp.Integer(arr.size)
            return _mt_vector_measure_from_shape(arr.shape[0], arr.shape[1], label="numel", allow_matrix=True)
        return sp.Integer(arr.size)

    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError("numel does not accept empty arrays.")
        try:
            mat = Matrix(value)
        except Exception:
            if any(_mt_nested_sequence(item) for item in value):
                raise ValueError("numel only accepts scalars, vectors, or matrices.")
            return sp.Integer(len(value))
        return _mt_numel(mat)

    return sp.Integer(1)


def _mt_nchoosek(n: Any, k: Any) -> Any:
    error_message = "nchoosek only accepts nonnegative integers n and k with k <= n."

    def _coerce_exact_integer(value: Any) -> int:
        if isinstance(value, (str, bytes, complex, MatrixBase, np.ndarray, list, tuple, dict, set)):
            raise ValueError(error_message)
        if isinstance(value, (float, np.floating, sp.Float)):
            raise ValueError(error_message)
        try:
            sym_val = sp.sympify(value)
        except Exception as exc:
            raise ValueError(error_message) from exc
        if sym_val.is_real is False:
            raise ValueError(error_message)
        free_symbols = getattr(sym_val, "free_symbols", None)
        if free_symbols:
            raise ValueError(error_message)
        if getattr(sym_val, "is_integer", None) is not True:
            raise ValueError(error_message)
        try:
            int_val = int(sym_val)
        except Exception as exc:
            raise ValueError(error_message) from exc
        if sp.Integer(int_val) != sym_val:
            raise ValueError(error_message)
        return int_val

    n_int = _coerce_exact_integer(n)
    k_int = _coerce_exact_integer(k)
    if n_int < 0 or k_int < 0 or k_int > n_int:
        raise ValueError(error_message)
    return sp.Integer(math.comb(n_int, k_int))


def _mt_min(*args: Any) -> Any:
    if not args:
        raise ValueError("min requires at least one argument.")
    reducer = sp.Min
    if len(args) > 1:
        return reducer(*[sp.sympify(v) for v in args])
    return _mt_reduce_columns(args[0], reducer, "min")


def _mt_max(*args: Any) -> Any:
    if not args:
        raise ValueError("max requires at least one argument.")
    reducer = sp.Max
    if len(args) > 1:
        return reducer(*[sp.sympify(v) for v in args])
    return _mt_reduce_columns(args[0], reducer, "max")


def _mt_apply_unary(value: Any, func: Callable[[Any], Any], label: str) -> Any:
    if isinstance(value, MatrixBase):
        mat = Matrix(value)
        return mat.applyfunc(func)

    if isinstance(value, np.ndarray):
        arr = np.asarray(value, dtype=object)
        if arr.ndim == 0:
            return func(sp.sympify(arr.item()))
        if arr.ndim in {1, 2}:
            return Matrix(arr.tolist()).applyfunc(func)
        raise ValueError(f"{label} only accepts scalars, vectors, or 2D matrices.")

    if isinstance(value, (list, tuple)):
        try:
            return Matrix(value).applyfunc(func)
        except Exception:
            return [func(sp.sympify(v)) for v in value]

    return func(sp.sympify(value))


def _mt_sin(value: Any) -> Any:
    return _mt_apply_unary(value, sp.sin, "sin")


def _mt_cos(value: Any) -> Any:
    return _mt_apply_unary(value, sp.cos, "cos")


def _mt_tan(value: Any) -> Any:
    return _mt_apply_unary(value, sp.tan, "tan")


def _mt_sinh(value: Any) -> Any:
    return _mt_apply_unary(value, sp.sinh, "sinh")


def _mt_cosh(value: Any) -> Any:
    return _mt_apply_unary(value, sp.cosh, "cosh")


def _mt_tanh(value: Any) -> Any:
    return _mt_apply_unary(value, sp.tanh, "tanh")


def _mt_asin(value: Any) -> Any:
    return _mt_apply_unary(value, sp.asin, "asin")


def _mt_acos(value: Any) -> Any:
    return _mt_apply_unary(value, sp.acos, "acos")


def _mt_atan(value: Any) -> Any:
    return _mt_apply_unary(value, sp.atan, "atan")


def _mt_exp(value: Any) -> Any:
    return _mt_apply_unary(value, sp.exp, "exp")


def _mt_ln(value: Any) -> Any:
    return _mt_apply_unary(value, sp.log, "ln")


def _mt_log(value: Any, base: Any | None = None) -> Any:
    if base is None:
        return _mt_apply_unary(value, sp.log, "log")
    return _mt_apply_unary(value, lambda v: sp.log(v, sp.sympify(base)), "log")


def _mt_sqrt(value: Any) -> Any:
    return _mt_apply_unary(value, sp.sqrt, "sqrt")


def _mt_nthroot(value: Any, degree: Any) -> Any:
    degree_expr = sp.sympify(degree)
    if degree_expr == 0:
        raise ValueError("nthroot does not accept degree 0.")
    exponent = sp.Integer(1) / degree_expr
    return _mt_apply_unary(value, lambda v: sp.Pow(v, exponent), "nthroot")


def _mt_abs(value: Any) -> Any:
    def _abs_scalar(v: Any) -> Any:
        sym_v = sp.sympify(v)
        # Mantiene forma simbolica cuando aun hay variables libres.
        if getattr(sym_v, "free_symbols", None):
            if sym_v.free_symbols:
                return sp.Abs(sym_v)
        if getattr(sym_v, "is_real", None) is True:
            return sp.Abs(sym_v)
        # Para valores numericos complejos, usa magnitud numerica directa
        # para evitar ramas/ruido imaginario en evaluaciones de alta complejidad.
        try:
            return sp.Float(abs(complex(sp.N(sym_v, 50))))
        except Exception:
            abs_expr = sp.Abs(sym_v)
            try:
                abs_num = _mt_coerce_near_real(sp.N(abs_expr, 50))
                if isinstance(abs_num, complex):
                    return sp.Float(abs(abs_num))
                return abs_num
            except Exception:
                return abs_expr

    return _mt_apply_unary(value, _abs_scalar, "abs")


def _mt_norm(value: Any, p: Any = 2) -> Any:
    if not isinstance(value, MatrixBase):
        return _mt_abs(value)

    mat = Matrix(value)
    order = "" if p is None else str(p).strip()
    order_lower = order.lower()

    def _eval_user_norm(expr_name: str) -> Any:
        expr_str = user_norms[expr_name]
        vars_syms = symbols(f"x_1:{len(mat)+1}")
        scope: dict[str, Any] = dict(greek_symbols)
        scope.update(COMMON_SYMBOLS)
        scope.update(env_ast)
        scope["env"] = env_ast
        scope["env_ast"] = env_ast
        lambda_alias = env_ast.get("lambda", greek_symbols.get("lambda"))
        if lambda_alias is not None:
            scope["lambda_kw"] = lambda_alias
        for i, sym in enumerate(vars_syms, start=1):
            scope[f"x_{i}"] = sym
        expr = eval(expr_str, scope)
        subs_map = {vars_syms[i]: mat[i, 0] for i in range(len(mat))}
        return expr.subs(subs_map)

    if mat.rows == 1 or mat.cols == 1:
        comps = [_mt_abs(cell) for cell in mat]
        if order in {"", "2"}:
            return sp.sqrt(sum(cell**2 for cell in comps))
        if order == "1":
            return sum(comps)
        if order_lower in {"oo", "inf"}:
            return sp.Max(*comps) if comps else sp.Integer(0)
        if order_lower in {"fro", "f", "frobenius"}:
            return sp.sqrt(sum(cell**2 for cell in comps))
        if order.isdigit() and int(order) >= 1:
            k = int(order)
            return sp.Pow(sum(cell**k for cell in comps), sp.Rational(1, k))
        if order in user_norms:
            return _eval_user_norm(order)
        raise ValueError(f"Unrecognized norm type for vector: {p}")

    if order in {"", "2"}:
        return mat.norm(2)
    if order == "1":
        return mat.norm(1)
    if order_lower in {"oo", "inf"}:
        return mat.norm("inf")
    if order_lower in {"fro", "f", "frobenius"}:
        return mat.norm("fro")
    raise ValueError(f"Unrecognized norm type for matrix: {p}")


def _mt_sign(value: Any) -> Any:
    return _mt_apply_unary(value, sp.sign, "sign")


def _mt_floor(value: Any) -> Any:
    return _mt_apply_unary(value, sp.floor, "floor")


def _mt_ceiling(value: Any) -> Any:
    return _mt_apply_unary(value, sp.ceiling, "ceiling")


def _mt_linspace(a: Any, b: Any, n: Any = 100) -> Matrix:
    count = _ensure_dimension(n, "linspace n")
    if count <= 0:
        raise ValueError("linspace n must be greater than 0.")
    if count == 1:
        start = sp.N(a)
        return Matrix([[start]])
    start = float(sp.N(a))
    end = float(sp.N(b))
    values = np.linspace(start, end, count)
    return Matrix(values.tolist())


@dataclass(frozen=True)
class _LinearSolveSpec:
    A: Any
    b: Any


def _mt_bar(left: Any, right: Any) -> _LinearSolveSpec:
    return _LinearSolveSpec(A=left, b=right)


def _mt_to_matrix(value: Any, label: str) -> Matrix:
    if isinstance(value, MatrixBase):
        return Matrix(value)
    if isinstance(value, np.ndarray):
        arr = np.asarray(value, dtype=object)
        if arr.ndim == 1:
            return Matrix(arr.tolist())
        if arr.ndim == 2:
            return Matrix(arr.tolist())
        raise ValueError(f"{label} must be a vector or 2D matrix.")
    if isinstance(value, (list, tuple)):
        try:
            return Matrix(value)
        except Exception as exc:
            raise ValueError(f"{label} cannot be converted to a matrix: {exc}") from exc
    raise ValueError(f"{label} must be a matrix/vector.")


def _mt_matrix_literal(rows: Any) -> Matrix:
    return Matrix(rows)


def _mt_solve_linear_system(spec: _LinearSolveSpec) -> Matrix:
    sol, _mode = _mt_solve_linear_system_with_mode(spec)
    return sol


def _mt_solve_linear_system_with_mode(spec: _LinearSolveSpec) -> tuple[Matrix, str]:
    A = _mt_to_matrix(spec.A, "A")
    b = _mt_to_matrix(spec.b, "b")
    try:
        sol, _mode = solve_linear_system_octave(A, b)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"could not solve the linear system: {exc}") from exc
    try:
        entries = list(A) + list(b)
        if all(not sp.sympify(entry).free_symbols for entry in entries):
            sol = Matrix(sol).applyfunc(lambda value: _mt_coerce_near_real(sp.N(value, 50)))
    except Exception:
        pass
    return Matrix(sol), _mode


def _mt_linear_solve_message(mode: str) -> str | None:
    if mode == "minimum_norm":
        return "System has infinitely many solutions: returning the minimum-norm solution."
    if mode == "least_squares":
        return "System has no exact solution: returning the least-squares solution."
    return None


def _mt_flatten_targets(targets: tuple[Any, ...]) -> list[Any]:
    flat: list[Any] = []
    for target in targets:
        if isinstance(target, (list, tuple)):
            flat.extend(_mt_flatten_targets(tuple(target)))
        else:
            flat.append(target)
    return flat


def _mt_is_matrix_like(value: Any) -> bool:
    if isinstance(value, MatrixBase):
        return True
    if isinstance(value, np.ndarray):
        return value.ndim in {1, 2}
    return isinstance(value, (list, tuple))


def _mt_to_equations(eqs: Any) -> list[Any]:
    if isinstance(eqs, (list, tuple, set)):
        raw_items = list(eqs)
    else:
        raw_items = [eqs]
    equations: list[Any] = []
    for item in raw_items:
        if isinstance(item, Relational):
            equations.append(item)
            continue
        expr = sp.sympify(item)
        equations.append(Eq(expr, 0))
    return equations


def _mt_solve_ode(eq_like: Any, target: Any | None = None) -> Any:
    ode_eq = eq_like if isinstance(eq_like, Relational) else Eq(sp.sympify(eq_like), 0)
    if target is None:
        return dsolve(ode_eq)
    return dsolve(ode_eq, target)


def _mt_solve(*args: Any) -> Any:
    if not args:
        raise ValueError("solve requires at least one argument.")

    first = args[0]
    if isinstance(first, _LinearSolveSpec):
        if len(args) > 1:
            raise ValueError("solve(A|b) does not accept additional arguments.")
        return _mt_solve_linear_system(first)

    if len(args) == 2 and _mt_is_matrix_like(first) and _mt_is_matrix_like(args[1]):
        return _mt_solve_linear_system(_LinearSolveSpec(first, args[1]))

    targets = _mt_flatten_targets(args[1:])

    try:
        equations = _mt_to_equations(first)
    except Exception as exc:
        raise ValueError(f"invalid input for solve: {exc}") from exc

    if len(equations) == 1 and equations[0].has(sp.Derivative):
        try:
            ode_target = targets[0] if targets else None
            return _mt_solve_ode(equations[0], ode_target)
        except Exception as exc:
            raise ValueError(f"could not solve the differential equation: {exc}") from exc

    if targets:
        try:
            result = sp.solve(equations, *targets)
        except Exception as exc:
            raise ValueError(f"could not solve symbolically: {exc}") from exc
        if len(targets) == 1 and isinstance(result, list):
            scalar_list: list[Any] = []
            is_singleton_tuples = True
            for item in result:
                if isinstance(item, tuple) and len(item) == 1:
                    scalar_list.append(item[0])
                else:
                    is_singleton_tuples = False
                    break
            if is_singleton_tuples:
                return scalar_list
        return result

    all_symbols: set[sp.Symbol] = set()
    for eq in equations:
        all_symbols.update(eq.free_symbols)
    ordered_symbols = sorted(all_symbols, key=lambda s: s.name)
    try:
        if len(equations) == 1 and len(ordered_symbols) == 1:
            return sp.solve(equations[0], ordered_symbols[0])
        if ordered_symbols:
            result = sp.solve(equations, *ordered_symbols)
            if len(ordered_symbols) == 1 and isinstance(result, list):
                scalar_list: list[Any] = []
                is_singleton_tuples = True
                for item in result:
                    if isinstance(item, tuple) and len(item) == 1:
                        scalar_list.append(item[0])
                    else:
                        is_singleton_tuples = False
                        break
                if is_singleton_tuples:
                    return scalar_list
            return result
        return sp.solve(equations)
    except Exception as exc:
        raise ValueError(f"could not solve symbolically: {exc}") from exc


def _coerce_scalar_to_matrix(base_matrix, other):
    if isinstance(other, MatrixBase):
        return other
    try:
        expr = sp.sympify(other)
    except Exception:
        return other
    if getattr(expr, "is_number", False):
        return Matrix.ones(base_matrix.rows, base_matrix.cols) * expr
    return other


def _matrix_add_patched(self, other):
    return _MATRIX_ADD_ORIG(self, _coerce_scalar_to_matrix(self, other))


def _matrix_radd_patched(self, other):
    return _MATRIX_RADD_ORIG(self, _coerce_scalar_to_matrix(self, other))


def _matrix_rsub_patched(self, a):
    return _MATRIX_RSUB_ORIG(self, _coerce_scalar_to_matrix(self, a))


MatrixBase.__add__ = _matrix_add_patched
MatrixBase.__radd__ = _matrix_radd_patched
MatrixBase.__rsub__ = _matrix_rsub_patched


_PARSER_BASE_SYMBOLS = build_parser_base_symbols(
    x_symbol=x,
    eq=Eq,
    diff=diff,
    greek_symbols=greek_symbols,
    math_funcs={
        "sin": _mt_sin,
        "cos": _mt_cos,
        "tan": _mt_tan,
        "sinh": _mt_sinh,
        "cosh": _mt_cosh,
        "tanh": _mt_tanh,
        "asin": _mt_asin,
        "acos": _mt_acos,
        "atan": _mt_atan,
        "exp": _mt_exp,
        "ln": _mt_ln,
        "log": _mt_log,
        "sqrt": _mt_sqrt,
        "nthroot": _mt_nthroot,
        "abs": _mt_abs,
        "norm": _mt_norm,
        "sign": _mt_sign,
        "floor": _mt_floor,
        "ceiling": _mt_ceiling,
    },
    sympy_objects={
        "pi": pi,
        "E": E,
        "Pow": Pow,
        "Rational": Rational,
        "oo": oo,
        "I": I,
        "Matrix": Matrix,
        "Max": Max,
        "Add": Add,
        "Mul": Mul,
        "Function": Function,
        "Sum": Sum,
        "Product": Product,
    },
    public_parser_funcs={
        "solve": _mt_solve,
        "linspace": _mt_linspace,
        "orth": _orth,
    },
)
_RUNTIME_SHARED_SYMBOLS = build_runtime_shared_symbols(
    math_aliases={
        "sin": _mt_sin,
        "cos": _mt_cos,
        "tan": _mt_tan,
        "sinh": _mt_sinh,
        "cosh": _mt_cosh,
        "tanh": _mt_tanh,
        "asin": _mt_asin,
        "acos": _mt_acos,
        "atan": _mt_atan,
        "exp": _mt_exp,
        "ln": _mt_ln,
        "log": _mt_log,
        "sqrt": _mt_sqrt,
        "nthroot": _mt_nthroot,
        "abs": _mt_abs,
        "norm": _mt_norm,
        "sign": _mt_sign,
        "floor": _mt_floor,
        "ceiling": _mt_ceiling,
    },
    runtime_helpers={
        "mt_min": _mt_min,
        "mt_max": _mt_max,
        "mt_length": _mt_length,
        "mt_numel": _mt_numel,
        "mt_nchoosek": _mt_nchoosek,
        "mt_solve": _mt_solve,
        "mt_bar": _mt_bar,
        "mt_linspace": _mt_linspace,
        "rand_matrix": _rand_matrix,
        "randi_matrix": _randi_matrix,
        "orth": _orth,
        "mat_null": _mat_null,
        "mt_mul": _mt_mul,
        "mt_div": _mt_div,
        "mt_pow": _mt_pow,
        "mt_ew_mul": _mt_ew_mul,
        "mt_ew_div": _mt_ew_div,
        "mt_ew_pow": _mt_ew_pow,
        "mt_transpose": _mt_transpose,
        "mt_adj": _mt_adj,
        "mt_call": _mt_call,
        "mt_apply_symbol": _mt_apply_symbol,
        "mt_matrix_literal": _mt_matrix_literal,
    },
    octave_helpers={
        "range": _oct_range,
        "get1": _oct_get1,
        "get2": _oct_get2,
        "get_any": _oct_get_any,
        "set1": _oct_set1,
        "set2": _oct_set2,
        "set_slice": _oct_set_slice,
        "slice": _oct_slice,
        "span": _oct_span,
    },
)
_COMMON_SYMBOL_REGISTRY = build_parser_symbol_registry(
    _PARSER_BASE_SYMBOLS,
    _RUNTIME_SHARED_SYMBOLS,
)
COMMON_SYMBOLS = _COMMON_SYMBOL_REGISTRY.common_symbols
PARSER_LOCAL_DICT = _COMMON_SYMBOL_REGISTRY.parser_local_dict
register_shared_symbols(COMMON_SYMBOLS, PARSER_LOCAL_DICT, {"arg": arg})
_EXPR_PARSER_CONFIG = build_expr_parser_config(PARSER_LOCAL_DICT)


def latex_to_python(expr: str) -> str:
    return _latex_to_python_impl(expr, _EXPR_PARSER_CONFIG)


def _oct_index_code(expr_text: str, ctx: ParserContext) -> str:
    return _oct_index_code_impl(expr_text, ctx, _EXPR_PARSER_CONFIG)


def _oct_replace_indices(expr_text: str, ctx: ParserContext) -> str:
    return _oct_replace_indices_impl(expr_text, ctx, _EXPR_PARSER_CONFIG)


def _oct_expr_to_python(expr: str, ctx: ParserContext) -> str:
    return _oct_expr_to_python_impl(expr, ctx, _EXPR_PARSER_CONFIG)


def _parse_mathtex_expr(expr: str, ctx: ParserContext) -> ASTNode:
    return _parse_mathtex_expr_impl(expr, ctx, _EXPR_PARSER_CONFIG)


def _replace_user_function_calls(expr_py: str, ctx: ParserContext) -> str:
    return _replace_user_function_calls_impl(expr_py, ctx)


def _parse_index_component(component: str, ctx: ParserContext) -> SliceNode:
    return _parse_index_component_impl(component, ctx, _parse_mathtex_expr)


def _parse_indexed_assignment_lhs(lhs: str, ctx: ParserContext) -> tuple[SymbolNode, list[SliceNode]] | None:
    return _parse_indexed_assignment_lhs_impl(lhs, ctx, _parse_mathtex_expr, _normalize_name)


def parse_mathtex_line(line: str, ctx: ParserContext) -> ASTNode | None:
    return _parse_mathtex_line_impl(line, ctx, _parse_mathtex_expr, _normalize_name)


def _is_recoverable_parse_error(exc: SyntaxError | None) -> bool:
    return isinstance(exc, MathTeXParseError) and exc.recoverable


def _runtime_error(exc: Exception, *, source: str | None = None) -> MathTeXRuntimeError:
    return runtime_error_from_exception(exc, source=source)


def _message_with_context(prefix: str | None, detail: str) -> str:
    clean_detail = detail.strip()
    if not prefix:
        return clean_detail
    clean_prefix = prefix.rstrip(": ").strip()
    if not clean_prefix:
        return clean_detail
    if not clean_detail:
        return clean_prefix
    return f"{clean_prefix}: {clean_detail}"


def _render_user_error(error: MathTeXDiagnostic | Exception | str, *, prefix: str | None = None) -> str:
    return _message_with_context(prefix, render_error_for_display(error))


def _print_runtime_error(prefix: str, exc: Exception, *, source: str | None = None) -> None:
    print(_render_user_error(_runtime_error(exc, source=source), prefix=prefix))

_OCT_BLOCK_ACTIVE = False
_OCT_BLOCK_LINES: list[str] = []
_OCT_NEST_LEVEL = 0
_FUNC_BLOCK_ACTIVE = False
_FUNC_DEF: dict[str, Any] | None = None
_FUNC_NEST_LEVEL = 0
_WORKING_DIR = Path.cwd()

EARLY_PARSERS = [
    handle_functions,
    handle_integrals,
    handle_sums_products,
    handle_complex_numbers,
]

LATE_PARSERS = [
    handle_norms,
    handle_inner_products,
    handle_odes,
]


def _print_expr_result(value: Any, expr_source: str, ctx: ParserContext) -> None:
    """Imprime el resultado de evaluar una expresion, respetando formatos existentes."""
    expr_clean = expr_source.strip()
    if isinstance(value, MatrixBase):
        name_match = re.fullmatch(r"[A-Za-z_]\w*", expr_clean)
        if name_match and name_match.group(0) in ctx.env_ast:
            display = _display_name(name_match.group(0), expr_clean)
            print(f"{display} = {matrix_to_str(value, ctx.greek_display)}")
        else:
            print(matrix_to_str(value, ctx.greek_display))
        return
    if isinstance(value, (int, float, complex, sp.Number)):
        print(format_value_for_display(value))
        return
    if value is not None:
        print(format_value_for_display(value))


def _eval_ast_expr_node(node: ASTNode, scope: dict[str, Any]) -> Any:
    expr_py = ast_to_python(node)
    return eval(expr_py, {"__builtins__": __builtins__}, scope)


def _eval_slice_node(node: SliceNode, scope: dict[str, Any]) -> tuple[Any, bool]:
    value_node = node.value
    if isinstance(value_node, RangeNode):
        if value_node.start is None and value_node.step is None and value_node.end is None:
            return ":", True
        if value_node.start is None or value_node.end is None:
            raise ValueError("Incomplete range in index.")
        start_val = _eval_ast_expr_node(value_node.start, scope)
        end_val = _eval_ast_expr_node(value_node.end, scope)
        step_val = _eval_ast_expr_node(value_node.step, scope) if value_node.step is not None else None
        return _oct_span(start_val, step_val, end_val), True
    return _eval_ast_expr_node(value_node, scope), False


def _execute_ast_node(node: ASTNode, ctx: ParserContext, raw_original: str) -> bool:
    """
    Evalua y ejecuta un nodo AST simple (asignacion o expresion).
    Devuelve True si se proceso la linea (exito o error controlado).
    """
    scope = ctx.eval_context({"env_ast": env_ast})

    if isinstance(node, AssignNode):
        expr_py = ast_to_python(node.expr)
        try:
            val = eval(expr_py, {"__builtins__": __builtins__}, scope)
        except Exception as exc:
            _print_runtime_error("Error defining variable", exc, source=raw_original)
            return True
        try:
            val = _mt_normalize_value(val, env_ast)
        except Exception as exc:
            _print_runtime_error("Error defining variable", exc, source=raw_original)
            return True
        env_ast[node.target.name] = val
        target_raw = raw_original.split("=", 1)[0].strip() if "=" in raw_original else node.target.name
        display_name = _display_name(node.target.name, target_raw)
        if not node.target.name.startswith("_"):
            if isinstance(val, MatrixBase):
                print(f"{display_name} = {matrix_to_str(val, ctx.greek_display)}")
            else:
                print(f"{display_name} = {format_value_for_display(val)}")
        return True

    if isinstance(node, IndexAssignNode):
        target_name = node.target.name
        try:
            val = _eval_ast_expr_node(node.expr, scope)
        except Exception as exc:
            _print_runtime_error(f"Error defining {target_name}", exc, source=raw_original)
            return True
        try:
            val = _mt_normalize_value(val, env_ast)
        except Exception as exc:
            _print_runtime_error(f"Error defining {target_name}", exc, source=raw_original)
            return True

        try:
            evaluated = [_eval_slice_node(idx, scope) for idx in node.indices]
            idx_values = [pair[0] for pair in evaluated]
            has_slice = any(pair[1] for pair in evaluated)
            if len(idx_values) == 1:
                if has_slice:
                    _oct_set_slice(target_name, idx_values[0], 1, val)
                else:
                    _oct_set1(target_name, idx_values[0], val)
            elif len(idx_values) == 2:
                if has_slice:
                    _oct_set_slice(target_name, idx_values[0], idx_values[1], val)
                else:
                    _oct_set2(target_name, idx_values[0], idx_values[1], val)
            else:
                print(f"Error defining {target_name}: unsupported number of indices.")
        except Exception as exc:
            _print_runtime_error(f"Error defining {target_name}", exc, source=raw_original)
        return True

    if isinstance(node, ExprStmtNode):
        expr_py = ast_to_python(node.expr)
        try:
            res = eval(expr_py, {"__builtins__": __builtins__}, scope)
        except NameError:
            return False
        except SyntaxError:
            return False
        except Exception as exc:
            _print_runtime_error("Error in operation", exc, source=raw_original)
            return True
        _print_expr_result(res, raw_original, ctx)
        return True

    if isinstance(node, BlockNode):
        handled_all = True
        for idx, stmt in enumerate(node.statements):
            is_last = idx == len(node.statements) - 1
            raw_ref = raw_original if is_last else ""
            handled = _execute_ast_node(stmt, ctx, raw_ref)
            handled_all = handled_all and handled
        return handled_all

    return False


def _oct_parse_for_header(line: str, ctx: ParserContext, line_no: int | None = None) -> str:
    m = re.match(r"for\s+([A-Za-z_]\w*)\s*=\s*(.+)", line, re.IGNORECASE)
    if not m:
        raise make_block_error(
            "invalid-for-syntax",
            "Invalid for syntax.",
            source=line,
            line=line_no,
            hint="Expected usage: for i = a:b or for i = a:step:b",
        )
    var = m.group(1)
    range_text = m.group(2).strip()
    parts = [p.strip() for p in _split_top_level(range_text, ":")]
    if len(parts) == 2 and all(parts):
        start_text, end_text = parts
        step_text = "1"
    elif len(parts) == 3 and all(parts):
        start_text, step_text, end_text = parts
    else:
        raise make_block_error(
            "invalid-for-syntax",
            "Invalid for syntax.",
            source=line,
            line=line_no,
            hint="Expected usage: for i = a:b or for i = a:step:b",
        )

    start_py = _oct_expr_to_python(start_text, ctx)
    end_py = _oct_expr_to_python(end_text, ctx)
    step_py = _oct_expr_to_python(step_text, ctx)
    return f"for {var} in _oct_range({start_py}, {end_py}, {step_py}):"


def _oct_translate_statement(line: str, ctx: ParserContext) -> str:
    """Traduce una sentencia simple estilo Octave a Python."""
    m_if = re.match(r"if\s+(.+)", line, re.IGNORECASE)
    if m_if:
        cond_py = _oct_expr_to_python(m_if.group(1), ctx)
        return f"if {cond_py}:"

    m_elif = re.match(r"(elseif|elif)\s+(.+)", line, re.IGNORECASE)
    if m_elif:
        cond_py = _oct_expr_to_python(m_elif.group(2), ctx)
        return f"elif {cond_py}:"

    if re.match(r"else\b", line, re.IGNORECASE):
        return "else:"

    m_mat = re.match(r"(\\?[A-Za-z_]\w*)\(\s*(.+?)\s*,\s*(.+?)\s*\)\s*=\s*(.+)", line)
    if m_mat:
        name, row_expr, col_expr, value_expr = m_mat.groups()
        clean_name = _normalize_name(name)
        row_clean = row_expr.strip()
        col_clean = col_expr.strip()
        val_expr = _oct_replace_indices(value_expr.replace("\\", ""), ctx)

        def _call_repl(match: re.Match[str]) -> str:
            name_raw, args_text = match.groups()
            name_clean = _normalize_name(name_raw)
            if name_clean in ctx.env_ast and isinstance(ctx.env_ast[name_clean], MatrixBase):
                return f"_oct_get_any('{name_clean}', {_oct_expr_to_python(args_text, ctx)})"
            return match.group(0)

        val_expr = re.sub(
            r"(?<!\w)(\\?(?!_oct_)[A-Za-z_]\w*)\(\s*([^()]+)\s*\)",
            _call_repl,
            val_expr,
        )
        val_py = _oct_expr_to_python(val_expr, ctx)
        if ":" in row_clean or ":" in col_clean:
            row_code = _oct_index_code(row_clean, ctx)
            col_code = _oct_index_code(col_clean, ctx)
            return f"{clean_name} = _oct_set_slice('{clean_name}', {row_code}, {col_code}, {val_py})"

        row_py = latex_to_python(normalize_matrix_expr(row_expr, ctx.env_ast))
        col_py = latex_to_python(normalize_matrix_expr(col_expr, ctx.env_ast))
        return f"{clean_name} = _oct_set2('{clean_name}', {row_py}, {col_py}, {val_py})"

    m_vec = re.match(r"(\\?[A-Za-z_]\w*)\(\s*(.+?)\s*\)\s*=\s*(.+)", line)
    if m_vec:
        name, idx_expr, value_expr = m_vec.groups()
        clean_name = _normalize_name(name)
        idx_py = latex_to_python(normalize_matrix_expr(idx_expr, ctx.env_ast))
        val_expr = _oct_replace_indices(value_expr.replace("\\", ""), ctx)
        def _call_repl_vec(match: re.Match[str]) -> str:
            name_raw, args_text = match.groups()
            name_clean = _normalize_name(name_raw)
            if name_clean in ctx.env_ast and isinstance(ctx.env_ast[name_clean], MatrixBase):
                return f"_oct_get_any('{name_clean}', {_oct_expr_to_python(args_text, ctx)})"
            return match.group(0)

        val_expr = re.sub(
            r"(?<!\w)(\\?(?!_oct_)[A-Za-z_]\w*)\(\s*([^()]+)\s*\)",
            _call_repl_vec,
            val_expr,
        )
        val_py = _oct_expr_to_python(val_expr, ctx)
        return f"{clean_name} = _oct_set1('{clean_name}', {idx_py}, {val_py})"


    m_assign = re.match(r"(\\?[A-Za-z_]\w*)\s*=\s*(.+)", line)
    if m_assign:
        name, value_expr = m_assign.groups()
        clean_name = _normalize_name(name)
        val_py = _oct_expr_to_python(value_expr, ctx)
        return f"{clean_name} = {val_py}"

    raise ValueError("Unsupported statement inside a for/end block.")


def _run_oct_block(lines: list[str]) -> None:
    """Ejecuta bloques estilo Octave a nivel script: for/if/while ... end."""
    ctx = _build_parser_context()
    py_lines: list[str] = []
    indent = 0
    block_stack: list[dict[str, Any]] = []

    def _bool_literal(text: str) -> str | None:
        lowered = text.strip().lower()
        if lowered == "true":
            return "True"
        if lowered == "false":
            return "False"
        return None

    try:
        for line_no, raw in enumerate(lines, start=1):
            raw_line = raw
            raw_clean = raw
            while raw_clean.rstrip().endswith(";"):
                raw_clean = raw_clean.rstrip()
                raw_clean = raw_clean[:-1]
            stripped = raw_clean.strip()
            if not stripped:
                continue

            if re.match(r"^for\b", stripped, re.IGNORECASE):
                py_for = _oct_parse_for_header(stripped, ctx, line_no=line_no)
                m_for = re.match(r"for\s+([A-Za-z_]\w*)\s*=", stripped, re.IGNORECASE)
                py_lines.append("    " * indent + py_for)
                block_stack.append({"kind": "for", "line": line_no, "raw": stripped, "else_seen": False})
                indent += 1
                if m_for:
                    loop_var = m_for.group(1)
                    py_lines.append("    " * indent + f"env_ast['{loop_var}'] = {loop_var}")
                continue

            m_while = re.match(r"while\s+(.+)", stripped, re.IGNORECASE)
            if m_while:
                cond_text = m_while.group(1)
                bool_literal = _bool_literal(cond_text)
                cond_py = bool_literal if bool_literal is not None else _oct_expr_to_python(cond_text, ctx)
                py_lines.append("    " * indent + f"while _mt_eval_cond({cond_py!r}, env_ast):")
                block_stack.append({"kind": "while", "line": line_no, "raw": stripped, "else_seen": False})
                indent += 1
                continue

            m_if = re.match(r"if\s+(.+)", stripped, re.IGNORECASE)
            if m_if:
                cond_text = m_if.group(1)
                bool_literal = _bool_literal(cond_text)
                cond_py = bool_literal if bool_literal is not None else _oct_expr_to_python(cond_text, ctx)
                py_lines.append("    " * indent + f"if _mt_eval_cond({cond_py!r}, env_ast):")
                block_stack.append({"kind": "if", "line": line_no, "raw": stripped, "else_seen": False})
                indent += 1
                continue

            m_elif = re.match(r"(elseif|elif)\s+(.+)", stripped, re.IGNORECASE)
            if m_elif:
                if not block_stack or block_stack[-1]["kind"] != "if":
                    raise make_block_error(
                        "invalid-block-nesting",
                        "'elseif' must appear inside an if block.",
                        source=stripped,
                        line=line_no,
                        hint="Add a matching 'if' before this branch.",
                    )
                if block_stack[-1]["else_seen"]:
                    raise make_block_error(
                        "invalid-block-nesting",
                        "'elseif' cannot appear after 'else'.",
                        source=stripped,
                        line=line_no,
                        hint="Move this branch before 'else' or convert it to a nested if.",
                    )
                cond_text = m_elif.group(2)
                bool_literal = _bool_literal(cond_text)
                cond_py = bool_literal if bool_literal is not None else _oct_expr_to_python(cond_text, ctx)
                indent = max(indent - 1, 0)
                py_lines.append("    " * indent + f"elif _mt_eval_cond({cond_py!r}, env_ast):")
                indent += 1
                continue

            if re.match(r"else\b", stripped, re.IGNORECASE):
                if not block_stack or block_stack[-1]["kind"] != "if":
                    raise make_block_error(
                        "invalid-block-nesting",
                        "'else' must appear inside an if block.",
                        source=stripped,
                        line=line_no,
                        hint="Add a matching 'if' before this branch.",
                    )
                if block_stack[-1]["else_seen"]:
                    raise make_block_error(
                        "invalid-block-nesting",
                        "Only one 'else' branch is allowed for an if block.",
                        source=stripped,
                        line=line_no,
                        hint="Remove the extra 'else' or restructure the block.",
                    )
                block_stack[-1]["else_seen"] = True
                indent = max(indent - 1, 0)
                py_lines.append("    " * indent + "else:")
                indent += 1
                continue

            if stripped.lower() == "end":
                if not block_stack:
                    raise make_block_error(
                        "invalid-block-nesting",
                        "Unexpected 'end' without an open block.",
                        source=stripped,
                        line=line_no,
                        hint="Remove 'end' or add a matching if/for/while block.",
                    )
                block_stack.pop()
                indent = max(indent - 1, 0)
                continue

            py_lines.append("    " * indent + f"ejecutar_linea({raw_line!r})")
            py_lines.append("    " * indent + "_mt_sync_exec_locals(locals(), env_ast)")
    except MathTeXBlockError as exc:
        print(render_error_for_display(exc))
        return
    except MathTeXParseError as exc:
        print(render_error_for_display(exc))
        return
    except Exception as exc:
        print(_render_user_error(exc, prefix="Error in Octave block"))
        return

    if block_stack:
        opener = block_stack[-1]
        missing_end = make_block_error(
            "missing-end",
            f"Block starting with '{opener['kind']}' is missing 'end'.",
            source=opener["raw"],
            line=opener["line"],
            hint="Add 'end' to close the block.",
        )
        print(render_error_for_display(missing_end))
        return

    code = "\n".join(py_lines)
    scope = ctx.eval_context()
    scope.setdefault("np", np)
    scope.setdefault("sympy", sp)
    scope.setdefault("sp", sp)
    scope.setdefault("ejecutar_linea", ejecutar_linea)
    scope.setdefault("env_ast", ctx.env_ast)
    scope.setdefault("_mt_eval_cond", _mt_eval_cond)
    scope.setdefault("_mt_sync_exec_locals", _mt_sync_exec_locals)
    try:
        exec(code, {"__builtins__": __builtins__}, scope)
    except SyntaxError as exc:
        block_exc = parse_error_from_syntax_error(
            exc,
            source=code,
            kind="invalid-block-syntax",
            message="Generated block code is invalid.",
            hint="Check block nesting and statement syntax inside the block.",
        )
        print(render_error_for_display(block_exc))
        return
    scope.update(ctx.env_ast)
    _sync_scope_to_env(scope, ctx)


def _run_function_lines(lines: list[str]) -> None:
    """Traduce y ejecuta un bloque de funcion con if/for/end estilo Octave."""
    ctx = _build_parser_context()
    py_lines: list[str] = []
    indent = 0

    def _bool_literal(text: str) -> str | None:
        lowered = text.strip().lower()
        if lowered == "true":
            return "True"
        if lowered == "false":
            return "False"
        return None

    try:
        for raw in lines:
            raw_line = raw
            raw_clean = raw
            while raw_clean.rstrip().endswith(";"):
                raw_clean = raw_clean.rstrip()
                raw_clean = raw_clean[:-1]
            stripped = raw_clean.strip()
            # Normaliza comandos LaTeX bA-sicos en las condiciones/headers
            latex_cmds = {
                r"\pi": "pi",
                r"\sin": "sin",
                r"\cos": "cos",
                r"\tan": "tan",
                r"\exp": "exp",
                r"\ln": "ln",
                r"\sqrt": "sqrt",
                r"\nthroot": "nthroot",
                r"\sinh": "sinh",
                r"\cosh": "cosh",
                r"\tanh": "tanh",
                r"\arcsin": "asin",
                r"\arccos": "acos",
                r"\arctan": "atan",
                r"\angle": "arg",
                r"\abs": "Abs",
                r"\sign": "sign",
                r"\floor": "floor",
                r"\ceil": "ceiling",
                r"\infty": "oo",
                r"\e": "E",
            }
            for k, v in latex_cmds.items():
                stripped = _replace_cmd(stripped, k, v)
            if not stripped:
                continue

            if re.match(r"^for\b", stripped, re.IGNORECASE):
                py_for = _oct_parse_for_header(stripped, ctx)
                m_for = re.match(r"for\s+([A-Za-z_]\w*)\s*=", stripped, re.IGNORECASE)
                py_lines.append("    " * indent + py_for)
                indent += 1
                if m_for:
                    loop_var = m_for.group(1)
                    py_lines.append("    " * indent + f"env_ast['{loop_var}'] = {loop_var}")
                continue

            m_while = re.match(r"while\s+(.+)", stripped, re.IGNORECASE)
            if m_while:
                cond_text = m_while.group(1)
                bool_literal = _bool_literal(cond_text)
                cond_py = bool_literal if bool_literal is not None else _oct_expr_to_python(cond_text, ctx)
                py_lines.append("    " * indent + f"while _mt_eval_cond({cond_py!r}, env_ast):")
                indent += 1
                continue

            m_if = re.match(r"if\s+(.+)", stripped, re.IGNORECASE)
            if m_if:
                cond_text = m_if.group(1)
                bool_literal = _bool_literal(cond_text)
                cond_py = bool_literal if bool_literal is not None else _oct_expr_to_python(cond_text, ctx)
                py_lines.append("    " * indent + f"if _mt_eval_cond({cond_py!r}, env_ast):")
                indent += 1
                continue

            m_elif = re.match(r"(elseif|elif)\s+(.+)", stripped, re.IGNORECASE)
            if m_elif:
                cond_text = m_elif.group(2)
                bool_literal = _bool_literal(cond_text)
                cond_py = bool_literal if bool_literal is not None else _oct_expr_to_python(cond_text, ctx)
                indent = max(indent - 1, 0)
                py_lines.append("    " * indent + f"elif _mt_eval_cond({cond_py!r}, env_ast):")
                indent += 1
                continue

            if re.match(r"else\b", stripped, re.IGNORECASE):
                indent = max(indent - 1, 0)
                py_lines.append("    " * indent + "else:")
                indent += 1
                continue

            if stripped.lower() == "end":
                indent = max(indent - 1, 0)
                continue

            if stripped.lower() == "return":
                py_lines.append("    " * indent + "raise _FunctionReturn()")
                continue

            if stripped.startswith(r"\error"):
                inner = stripped[stripped.find("(") + 1 : stripped.rfind(")")]
                msg = inner.strip() or "error"
                try:
                    msg_val = eval(ctx.latex_to_python(inner), ctx.eval_context())
                    msg = str(msg_val)
                except Exception:
                    msg = inner.strip() or "error"
                py_lines.append("    " * indent + f"raise RuntimeError('error: {msg}')")
                continue

            # Comandos que no son control: intento traducir, si falla ejecuto directo
            # Resto de sentencias: ejecuto via ejecutar_linea para respetar ";" y el parser propio
            py_lines.append("    " * indent + f"ejecutar_linea({raw_line!r})")
            py_lines.append("    " * indent + "_mt_sync_exec_locals(locals(), env_ast)")
            continue
    except Exception as exc:
        raise RuntimeError(f"Error in function block: {exc}") from exc

    if indent != 0:
        raise RuntimeError("Error: unclosed blocks in function (missing 'end').")

    code = "\n".join(py_lines)

    scope = ctx.eval_context()
    scope.setdefault("np", np)
    scope.setdefault("sympy", sp)
    scope.setdefault("sp", sp)
    scope.setdefault("ejecutar_linea", ejecutar_linea)
    scope.setdefault("env_ast", ctx.env_ast)
    scope.setdefault("_mt_eval_cond", _mt_eval_cond)
    scope.setdefault("_mt_sync_exec_locals", _mt_sync_exec_locals)
    scope.setdefault("_FunctionReturn", _FunctionReturn)

    try:
        exec(code, {"__builtins__": __builtins__}, scope)
    except _FunctionReturn:
        pass
    scope.update(ctx.env_ast)
    _sync_scope_to_env(scope, ctx)
# Función auxiliar para convertir a \frac y \sqrt si es posible
def format_frac(expr):
    num, denom = expr.as_numer_denom()

    def format_term(t):
        from sympy import Pow, Rational
        if isinstance(t, Pow):
            if isinstance(t.exp, Rational):
                if t.exp == Rational(1,2):
                    return f"\\sqrt{{{t.base}}}"
                elif t.exp.q != 1:
                    return f"{t.base}^{{{t.exp}}}"
                else:
                    return f"{t.base}^{t.exp.p}"
            else:
                return f"{t.base}^{{{t.exp}}}"
        else:
            return str(t)

    # Formatear numerador y denominador
    if denom == 1:
        return format_term(num)
    else:
        return f"\\frac{{{format_term(num)}}}{{{format_term(denom)}}}"

# ---------------------------
# Función principal
# ---------------------------

def _should_show_silenced_output(output: str) -> bool:
    """Return True if captured output looks like an error/warning."""
    alert_prefixes = (
        "error",
        "parse error",
        "block error",
        "runtime error",
        "build error",
        "syntax error",
        "usage",
        "warning",
        "invalid",
        "warning",
        "there is no",
        "could not",
    )
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Evita falsos positivos: "errores = []" contiene "error" pero no es un aviso.
        if re.match(r"^[A-Za-z_]\w*\s*=", stripped):
            continue
        lowered = stripped.lower()
        if any(lowered.startswith(prefix) for prefix in alert_prefixes):
            return True
        if "error:" in lowered:
            return True
    return False


def _mt_coerce_near_real(value: Any, tol: float = 1e-12) -> Any:
    """Si un valor complejo tiene parte imaginaria numericamente despreciable, lo proyecta a real."""
    if isinstance(value, complex):
        if abs(value.imag) <= tol:
            real_val = value.real
            if float(real_val).is_integer():
                return int(real_val)
            return float(real_val)
        return value
    if isinstance(value, np.generic):
        try:
            as_complex = complex(value.item())
            return float(as_complex.real) if abs(as_complex.imag) <= tol else as_complex
        except Exception:
            return value
    try:
        orig_sym = sp.sympify(value)
        sym_val = sp.N(orig_sym, 50)
    except Exception:
        return value
    if getattr(sym_val, "is_real", None) is True:
        if getattr(orig_sym, "is_integer", None) is True:
            try:
                return sp.Integer(orig_sym)
            except Exception:
                return orig_sym
        if isinstance(orig_sym, sp.Float):
            return sp.Float(float(sym_val))
        return orig_sym
    try:
        imag_part = sp.N(sym_im(sym_val), 50)
        if abs(complex(imag_part)) <= tol:
            return sp.Float(float(sp.N(sym_re(sym_val), 50)))
    except Exception:
        pass
    return value


def _mt_eval_cond_value(node: ast.AST, scope: dict[str, Any]) -> Any:
    compiled = compile(ast.Expression(node), "<mathtex-cond>", "eval")
    return eval(compiled, {"__builtins__": __builtins__}, scope)


def _mt_compare_values(left: Any, right: Any, op: ast.cmpop) -> bool:
    left_val = _mt_coerce_near_real(left)
    right_val = _mt_coerce_near_real(right)

    try:
        left_sym = sp.sympify(left_val)
        right_sym = sp.sympify(right_val)
    except Exception:
        left_sym = left_val
        right_sym = right_val

    if isinstance(op, ast.Eq):
        try:
            return bool(sp.simplify(left_sym - right_sym) == 0)
        except Exception:
            return bool(left_sym == right_sym)
    if isinstance(op, ast.NotEq):
        try:
            return bool(sp.simplify(left_sym - right_sym) != 0)
        except Exception:
            return bool(left_sym != right_sym)

    diff = _mt_coerce_near_real(sp.N(left_sym - right_sym))
    diff_sym = sp.sympify(diff)
    if getattr(diff_sym, "is_real", None) is False:
        raise ValueError(f"Invalid comparison of non-real {left_sym}")
    diff_num = float(sp.N(diff_sym))

    if isinstance(op, ast.Gt):
        return diff_num > 0.0
    if isinstance(op, ast.GtE):
        return diff_num >= 0.0
    if isinstance(op, ast.Lt):
        return diff_num < 0.0
    if isinstance(op, ast.LtE):
        return diff_num <= 0.0
    if isinstance(op, ast.Is):
        return left_sym is right_sym
    if isinstance(op, ast.IsNot):
        return left_sym is not right_sym
    raise ValueError(f"Unsupported comparator: {type(op).__name__}")


def _mt_eval_cond_ast(node: ast.AST, scope: dict[str, Any]) -> bool:
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_mt_eval_cond_ast(v, scope) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(_mt_eval_cond_ast(v, scope) for v in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _mt_eval_cond_ast(node.operand, scope)
    if isinstance(node, ast.Compare):
        left_value = _mt_eval_cond_value(node.left, scope)
        for op, comp in zip(node.ops, node.comparators):
            right_value = _mt_eval_cond_value(comp, scope)
            if not _mt_compare_values(left_value, right_value, op):
                return False
            left_value = right_value
        return True

    value = _mt_eval_cond_value(node, scope)
    value = _mt_coerce_near_real(value)
    return bool(value)


def _mt_eval_cond(expr, scope_or_env: dict | None = None, env: dict | None = None) -> bool:
    """Evalua condiciones en if/while dentro de funciones, tolerando ruido imaginario numerico."""
    try:
        local_scope: dict[str, Any] = {}
        env_scope: dict[str, Any] = {}

        if env is None and isinstance(scope_or_env, dict):
            env_scope = scope_or_env
        else:
            if isinstance(scope_or_env, dict):
                local_scope = scope_or_env
            if isinstance(env, dict):
                env_scope = env

        if isinstance(expr, str):
            expr_text = expr.strip()
            if not expr_text:
                return False
            scope: dict[str, Any] = {}
            scope.update(COMMON_SYMBOLS)
            scope.update(greek_symbols)
            scope.update(env_scope)
            scope.update(local_scope)
            scope.setdefault("env_ast", env_scope)
            scope.setdefault("env", env_scope)
            scope.setdefault("sp", sp)
            scope.setdefault("sympy", sp)
            scope.setdefault("np", np)
            parsed = ast.parse(expr_text, mode="eval")
            return _mt_eval_cond_ast(parsed.body, scope)

        if isinstance(expr, bool):
            return expr
        subs_map = {}
        for name, val in env_scope.items():
            if callable(val):
                continue
            if isinstance(name, str):
                try:
                    subs_map[sp.Symbol(name)] = val
                except Exception:
                    continue
        if isinstance(expr, Relational):
            expr_rel = expr
            try:
                expr_rel = expr_rel.subs(subs_map)
            except Exception:
                pass
            try:
                return bool(expr_rel)
            except Exception:
                try:
                    return bool(expr_rel.doit())
                except Exception:
                    pass
        if hasattr(expr, "subs"):
            try:
                expr = expr.subs(subs_map)
            except Exception:
                pass
        try:
            expr = sp.N(expr)
        except Exception:
            pass
        expr = _mt_coerce_near_real(expr)
        return bool(expr)
    except Exception:
        return False


def _mt_resolve_expr(val, env: dict):
    """Intenta evaluar expresiones SymPy usando los valores numA(c) del entorno."""
    if isinstance(val, _LinearSolveSpec):
        return _mt_solve_linear_system(val)
    if isinstance(val, sp.Expr):
        subs_map = {}
        for name, v in env.items():
            if isinstance(name, str) and isinstance(v, (int, float, complex, sp.Number)):
                try:
                    subs_map[sp.Symbol(name)] = v
                except Exception:
                    continue
        if subs_map and val.free_symbols.issubset(set(subs_map.keys())):
            try:
                val_num = val.subs(subs_map)
                return _mt_coerce_near_real(sp.N(val_num))
            except Exception:
                pass
        if not val.free_symbols:
            try:
                if getattr(val, "is_integer", None) is True:
                    return sp.Integer(val)
                if isinstance(val, (sp.Integer, sp.Rational)):
                    return val
                return _mt_coerce_near_real(sp.N(val))
            except Exception:
                pass
    return val


def _mt_normalize_value(val: Any, env: dict) -> Any:
    """Normaliza resultados numericos para remover ruido imaginario despreciable."""
    resolved = _mt_resolve_expr(val, env)
    if isinstance(resolved, (str, bytes)):
        return resolved
    if isinstance(resolved, MatrixBase):
        return Matrix(resolved).applyfunc(_mt_coerce_near_real)
    if isinstance(resolved, np.ndarray):
        arr = np.asarray(resolved, dtype=object)
        vectorized = np.vectorize(_mt_coerce_near_real, otypes=[object])
        return vectorized(arr)
    if isinstance(resolved, list):
        return [_mt_normalize_value(item, env) for item in resolved]
    if isinstance(resolved, tuple):
        return tuple(_mt_normalize_value(item, env) for item in resolved)
    return _mt_coerce_near_real(resolved)


def _mt_sync_exec_locals(scope: dict[str, Any], env: dict[str, Any]) -> None:
    """Sincroniza variables creadas por MathTeX hacia el scope de exec."""
    for name, value in env.items():
        if not isinstance(name, str) or name.startswith("__"):
            continue
        scope[name] = value




class _FunctionReturn(Exception):
    """Se usa internamente para simular 'return' en funciones de usuario."""
    pass


def _execute_line_core(linea: str) -> None:
    global _OCT_BLOCK_ACTIVE, _OCT_BLOCK_LINES, _OCT_NEST_LEVEL, _FUNC_BLOCK_ACTIVE, _FUNC_DEF, _FUNC_NEST_LEVEL

    raw_line = linea.rstrip("\n")
    raw_line = _strip_comments(raw_line)
    stripped_raw = raw_line.strip()
    if re.fullmatch(r"\\?[A-Za-z_]\w*'", stripped_raw):
        stripped_raw = stripped_raw + "(x)"

    if not stripped_raw:
        return

    if stripped_raw.lower() == "pwd":
        print(_WORKING_DIR)
        return

    m_opt = re.match(r"^\\opt\s+(on|off)\s*$", stripped_raw, re.IGNORECASE)
    if m_opt:
        env_ast["_opt_debug"] = m_opt.group(1).lower() == "on"
        print(f"Optimizaciones en modo debug: {'activado' if env_ast['_opt_debug'] else 'desactivado'}.")
        return

    m_import = re.match(r"^import\s+([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*$", stripped_raw)
    if m_import:
        module = m_import.group(1)
        try:
            _handle_import(module)
        except MathTeXImportError as exc:
            if _MODULE_LOAD_STACK:
                raise
            print(exc)
        return

    m_from = re.match(r"^from\s+([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s+import\s+(.+)$", stripped_raw)
    if m_from:
        module = m_from.group(1)
        names_raw = m_from.group(2)
        try:
            _handle_from_import(module, names_raw)
        except MathTeXImportError as exc:
            if _MODULE_LOAD_STACK:
                raise
            print(exc)
        return

    if stripped_raw.lower().startswith("cd "):
        destino = stripped_raw[3:].strip()
        if not destino:
            print("Usage: cd <directory>")
            return
        _set_working_dir(_resolve_path(destino))
        return

    if stripped_raw.startswith(r"\run") or stripped_raw.startswith("@run"):
        partes = stripped_raw.split(maxsplit=1)
        if len(partes) < 2:
            print(r"Usage: \run file.mtx")
            return
        destino_txt = partes[1].strip()
        destino_path = Path(destino_txt)
        if destino_path.suffix == "":
            destino_path = destino_path.with_suffix(".mtx")
        elif destino_path.suffix.lower() == ".mtex":
            print(r"This file looks like an .mtex document (LaTeX+MathTeX). Use @compile instead of \run.")
            return
        ruta = _resolve_path(str(destino_path))
        _run_script_file(ruta)
        return

    if stripped_raw.startswith("@compilar") or stripped_raw.startswith("@compile"):
        from mtex_executor import ejecutar_mtex
        partes = stripped_raw.split()
        if len(partes) > 1:
            archivo_txt = partes[1].strip()
            archivo_path = Path(archivo_txt)
            if archivo_path.suffix == "":
                archivo_path = archivo_path.with_suffix(".mtex")
            elif archivo_path.suffix.lower() == ".mtx":
                print(r"This file looks like an .mtx script. Use \run instead of @compile.")
                return
            archivo = _resolve_path(str(archivo_path))
            try:
                ejecutar_mtex(str(archivo), env_ast)  # usa tu mismo entorno global
            except Exception as e:
                print(f"Error while compiling {archivo}: {e}")
        else:
            print("Usage: @compile file.mtex")
        return

    m_time = re.match(r"^\\time\s+(.+)$", stripped_raw, re.IGNORECASE)
    if m_time:
        inner_code = m_time.group(1).strip()
        if not inner_code:
            print("Usage: \\time <code>")
            return

        # Fuerza silencio de salida agregando ';' si el usuario no lo puso
        if not inner_code.rstrip().endswith(";"):
            inner_code = inner_code + ";"

        start = time.perf_counter()
        try:
            ejecutar_linea(inner_code)
        except Exception as exc:
            print(f"Execution aborted due to error: {exc}")
            return
        elapsed = time.perf_counter() - start
        print(f"Elapsed time: {elapsed:.6f} s")
        return

    m_bench = re.match(r"^\\benchmark(?:\[(\d+)\])?\s+(.+)$", stripped_raw, re.IGNORECASE)
    if m_bench:
        loops_raw = m_bench.group(1)
        inner_code = m_bench.group(2).strip()
        if not inner_code:
            print("Usage: \\benchmark[loops] <code>")
            return
        try:
            loops = int(loops_raw) if loops_raw else 10
        except Exception:
            loops = 10
        if loops <= 0:
            loops = 1
        times_sec: list[float] = []
        for idx in range(loops):
            start = time.perf_counter()
            try:
                ejecutar_linea(inner_code)
            except Exception as exc:
                print(f"Benchmark aborted due to error after {idx} run(s): {exc}")
                return
            elapsed = time.perf_counter() - start
            times_sec.append(elapsed)
        if not times_sec:
            print("Benchmark aborted: no runs executed.")
            return
        avg = sum(times_sec) / len(times_sec)
        min_t = min(times_sec)
        max_t = max(times_sec)
        print(f"Benchmark: {len(times_sec)} runs")
        print(f"avg: {avg:.6f} s")
        print(f"min: {min_t:.6f} s")
        print(f"max: {max_t:.6f} s")
        return

    if stripped_raw in {r"\who", r"\vars"}:
        _print_workspace_who(env_ast)
        return

    m_format = re.match(r"^\\format\(([^()]*)\)\s*$", stripped_raw, re.IGNORECASE)
    if m_format:
        raw_mode = m_format.group(1).strip()
        if not raw_mode:
            print(r"Usage: \format(short|long|shorte|longe|bank)")
            return
        try:
            set_numeric_format(raw_mode)
        except ValueError as exc:
            print(exc)
        return

    if stripped_raw == r"\whos":
        _print_workspace_whos(env_ast)
        return

    if stripped_raw == r"\functions":
        _print_workspace_functions(env_ast)
        return

    if stripped_raw == r"\clean":
        if not _notify_console_clear_listeners():
            # Fallback para la REPL tradicional en terminal.
            print("\033[2J\033[H", end="")
        return

    m_clear = re.match(r"^\\clear(?:\s+(.*))?$", stripped_raw, re.IGNORECASE)
    if m_clear:
        target = (m_clear.group(1) or "").strip()
        if not target:
            print("Usage: \\clear <name>|all")
            return
        if target.lower() == "all":
            reset_environment(env_ast)
            print("Workspace reset.")
            return
        _clear_workspace_name(target, env_ast)
        return

    if stripped_raw == r"\reset":
        reset_environment(env_ast)
        print("Workspace reset.")
        return

    m_help = re.match(r"^\\help\s+(.+)$", stripped_raw, re.IGNORECASE)
    if m_help:
        query = m_help.group(1).strip()
        if not query:
            print("Usage: \\help <name>")
        else:
            _print_workspace_help(query, env_ast)
        return

    if _FUNC_BLOCK_ACTIVE:
        if stripped_raw.lower() == "end":
            if _FUNC_NEST_LEVEL > 0:
                _FUNC_NEST_LEVEL -= 1
                if _FUNC_DEF is not None:
                    _FUNC_DEF["body"].append(raw_line)
                return
            if not _FUNC_DEF:
                print("Internal error: function definition was lost.")
                _FUNC_BLOCK_ACTIVE = False
                return
            func_obj = UserFunction(
                name=_FUNC_DEF["name"],
                args=_FUNC_DEF["args"],
                outputs=_FUNC_DEF["outputs"],
                body=_FUNC_DEF["body"],
                working_dir=_FUNC_DEF["working_dir"],
                defining_env=env_ast,
            )
            env_ast[func_obj.name] = func_obj
            _FUNC_BLOCK_ACTIVE = False
            _FUNC_DEF = None
            _FUNC_NEST_LEVEL = 0
            return

        opens_block = bool(re.match(r"^(for|if|while)\b", stripped_raw, re.IGNORECASE))
        if opens_block:
            _FUNC_NEST_LEVEL += 1
        if _FUNC_DEF is not None:
            _FUNC_DEF["body"].append(raw_line)
        return

    if stripped_raw.lower().startswith("function"):
        header = stripped_raw
        m_multi = re.match(r"function\s*\[\s*(.+?)\s*\]\s*=\s*([A-Za-z_][\w]*)\s*\((.*?)\)\s*$", header, re.IGNORECASE)
        m_single = re.match(r"function\s+([A-Za-z_][\w]*)\s*=\s*([A-Za-z_][\w]*)\s*\((.*?)\)\s*$", header, re.IGNORECASE)
        m_no_out = re.match(r"function\s+([A-Za-z_][\w]*)\s*\((.*?)\)\s*$", header, re.IGNORECASE)
        outputs: list[str] = []
        func_name = ""
        args_part = ""
        if m_multi:
            outputs_raw, func_name, args_part = m_multi.groups()
            outputs = [_normalize_name(p) for p in outputs_raw.split(",") if p.strip()]
        elif m_single:
            out_raw, func_name, args_part = m_single.groups()
            outputs = [_normalize_name(out_raw)]
        elif m_no_out:
            func_name, args_part = m_no_out.groups()
            outputs = []
        else:
            print("Invalid function syntax.")
            return
        args = [_normalize_name(a) for a in args_part.split(",") if a.strip()]
        _FUNC_BLOCK_ACTIVE = True
        _FUNC_DEF = {
            "name": func_name,
            "args": args,
            "outputs": outputs,
            "body": [],
            "working_dir": _WORKING_DIR,
        }
        _FUNC_NEST_LEVEL = 0
        return

    if _OCT_BLOCK_ACTIVE:
        if re.match(r"^(for|if|while)\b", stripped_raw, re.IGNORECASE):
            _OCT_NEST_LEVEL += 1
            _OCT_BLOCK_LINES.append(raw_line)
            return
        if stripped_raw.lower() == "end":
            _OCT_NEST_LEVEL = max(_OCT_NEST_LEVEL - 1, 0)
            _OCT_BLOCK_LINES.append(raw_line)
            if _OCT_NEST_LEVEL == 0:
                block_lines = list(_OCT_BLOCK_LINES)
                _OCT_BLOCK_LINES = []
                _OCT_BLOCK_ACTIVE = False
                _OCT_NEST_LEVEL = 0
                _run_oct_block(block_lines)
            return
        _OCT_BLOCK_LINES.append(raw_line)
        return

    if re.match(r"^(elseif|elif|else|end)\b", stripped_raw, re.IGNORECASE):
        block_error = make_block_error(
            "invalid-block-nesting",
            f"Unexpected block keyword '{stripped_raw.split()[0]}' outside an open block.",
            source=stripped_raw,
            line=1,
            hint="Use else/elseif/end only inside an if/for/while block.",
        )
        print(render_error_for_display(block_error))
        return

    if stripped_raw == r"\py" or stripped_raw.startswith(r"\py ") or stripped_raw == r"\endpy":
        print(r"Commands \py and \endpy are no longer supported.")
        return

    if re.match(r"^(for|if|while)\b", stripped_raw, re.IGNORECASE):
        _OCT_BLOCK_ACTIVE = True
        _OCT_NEST_LEVEL = 1
        _OCT_BLOCK_LINES = [raw_line]
        return

    linea = stripped_raw
    linea_original = linea  # Guarda la linea sin reemplazos para determinar nombres mostrados
    linea = _replace_cmd_outside_strings(linea, r"\infty", "oo")
    linea = _replace_cmd_outside_strings(linea, r"\e", "E")

    env_ast.setdefault("i", I)
    env_ast.setdefault("I", I)

    linea = re.sub(r'(\d+)\s*i\b', r'\1*I', linea)
    linea = re.sub(r'(\d+)i\b', r'\1*I', linea)

    for cmd, alias in GREEK_CMD_TO_ALIAS.items():
        linea = _replace_cmd_outside_strings(linea, cmd, alias)

    if not linea or linea.startswith("#"):
        return

    latex_to_sympy = {
        r"\pi": "pi",
        r"\sin": "sin", r"\cos": "cos", r"\tan": "tan",
        r"\exp": "exp", r"\ln": "ln", r"\sqrt": "sqrt", r"\nthroot": "nthroot",
        r"\sinh": "sinh", r"\cosh": "cosh", r"\tanh": "tanh",
        r"\arcsin": "asin", r"\arccos": "acos", r"\arctan": "atan",
        r"\angle": "arg",
        r"\abs": "abs", r"\sign": "sign", r"\floor": "floor", r"\ceil": "ceiling",
        r"\min": "_mt_min", r"\max": "_mt_max",
        r"\length": "_mt_length", r"\numel": "_mt_numel", r"\nchoosek": "_mt_nchoosek",
        r"\solve": "_mt_solve",
        r"\linspace": "_mt_linspace",
        r"\infty": "oo", r"\e": "E"
    }

    for key, val in latex_to_sympy.items():
        linea = _replace_cmd_outside_strings(linea, key, val)

    linea = _rewrite_solve_calls(linea)

    ctx = _build_parser_context()

    for parser in EARLY_PARSERS:
        if parser(linea, ctx):
            return

    if "[[" not in linea and handle_matrices(linea, ctx, allow_expression_eval=False):
        return

    for parser in LATE_PARSERS:
        if parser(linea, ctx):
            return
    parse_error: SyntaxError | None = None
    try:
        ast_line = parse_mathtex_line(linea, ctx)
    except SyntaxError as exc:
        ast_line = None
        parse_error = exc
    fatal_parse_error = None if _is_recoverable_parse_error(parse_error) else parse_error

    if ast_line is not None:
        ast_opt = optimize_ast(ast_line, env_ast)
        handled = _execute_ast_node(ast_opt, ctx, linea_original)
        if handled:
            return


    if "=" in linea and not linea.strip().startswith("\\") and "==" not in linea:
        try:
            name, expr_str = [a.strip() for a in linea.split("=", 1)]
        except ValueError:
            print("Error: invalid assignment.")
            return
        if fatal_parse_error is not None:
            print(_render_user_error(fatal_parse_error, prefix="Error defining variable"))
            return
        if "(" in name or ")" in name:
            if fatal_parse_error is not None:
                print(render_error_for_display(fatal_parse_error))
            else:
                print("Syntax error: invalid indexed assignment.")
            return
        raw_lhs = linea_original.split("=", 1)[0].strip()

        try:
            expr_python = _oct_expr_to_python(expr_str, ctx)
        except Exception as e:
            _print_runtime_error("Error defining variable", e, source=linea_original)
            return
        expr_python = expr_python.replace(r"\N", "_mat_null")
        try:
            val = eval(expr_python, ctx.eval_context({"env_ast": env_ast}))
        except Exception as e:
            _print_runtime_error("Error defining variable", e, source=linea_original)
            return
        linear_solve_msg = None
        if isinstance(val, _LinearSolveSpec):
            try:
                val, solve_mode = _mt_solve_linear_system_with_mode(val)
                linear_solve_msg = _mt_linear_solve_message(solve_mode)
            except Exception as e:
                _print_runtime_error("Error defining variable", e, source=linea_original)
                return
        else:
            try:
                val = _mt_normalize_value(val, env_ast)
            except Exception as e:
                _print_runtime_error("Error defining variable", e, source=linea_original)
                return

        multi_match = re.match(r"^\[(.*)\]$", name)
        if multi_match:
            raw_multi_match = re.match(r"^\[(.*)\]$", raw_lhs)
            raw_targets_source = raw_multi_match.group(1) if raw_multi_match else multi_match.group(1)
            raw_targets = [t.strip() for t in raw_targets_source.split(",") if t.strip()]
            if not raw_targets:
                print("Error: invalid assignment.")
                return
            targets = [_normalize_name(t) for t in raw_targets]
            if isinstance(val, (list, tuple)):
                values = list(val)
            else:
                if len(targets) == 1:
                    values = [val]
                else:
                    try:
                        # Check if val is a Matrix or iterable (but not a string or Expr)
                        if isinstance(val, MatrixBase):
                            values = [val[i, 0] if val.cols == 1 else val[i] for i in range(val.rows)]
                        elif hasattr(val, '__iter__') and not isinstance(val, (str, sp.Basic)):
                            values = list(val)
                        else:
                            values = [val]
                    except Exception:
                        print("Error: the expression does not return multiple values.")
                        return
            if len(values) < len(targets):
                print("Error: there are not enough values to assign.")
                return
            for idx, tname in enumerate(targets):
                try:
                    current = _mt_normalize_value(values[idx], env_ast)
                except Exception as e:
                    _print_runtime_error("Error defining variable", e, source=linea_original)
                    return
                env_ast[tname] = current
                display_name = _display_name(tname, raw_targets[idx])
                if idx == 0 and linear_solve_msg:
                    print(linear_solve_msg)
                if isinstance(current, Matrix):
                    print(f"{display_name} = {matrix_to_str(current, greek_display)}")
                else:
                    print(f"{display_name} = {format_value_for_display(current)}")
            return

        name_clean = _normalize_name(name)
        try:
            val = _mt_normalize_value(val, env_ast)
        except Exception as e:
            _print_runtime_error("Error defining variable", e, source=linea_original)
            return
        env_ast[name_clean] = val
        display_name = _display_name(name_clean, raw_lhs)
        if linear_solve_msg:
            print(linear_solve_msg)

        if isinstance(val, Matrix):
            print(f"{display_name} = {matrix_to_str(val, greek_display)}")
        else:
            print(f"{display_name} = {format_value_for_display(val)}")
        return

    if fatal_parse_error is not None:
        print(render_error_for_display(fatal_parse_error))
        return


def ejecutar_linea(linea: str) -> None:
    """Ejecuta una linea de MathTeX, suprimiendo la salida si termina en ';'."""
    raw_line = linea.rstrip("\n")
    trimmed_line = raw_line.rstrip()
    silence_output = trimmed_line.endswith(";")

    # Mientras se esta acumulando un bloque Octave o el cuerpo de una funcion,
    # hay que preservar el ';' original para que el bloque reejecute cada linea
    # con el mismo comportamiento de silenciamiento que escribio el usuario.
    if _OCT_BLOCK_ACTIVE or _FUNC_BLOCK_ACTIVE:
        _execute_line_core(raw_line)
        return

    if silence_output:
        cleaned_line = trimmed_line[:-1].rstrip()
        while cleaned_line.endswith(";"):
            cleaned_line = cleaned_line[:-1].rstrip()
    else:
        cleaned_line = raw_line

    if not silence_output:
        _execute_line_core(cleaned_line)
        return

    out_buffer = io.StringIO()
    err_buffer = io.StringIO()
    with redirect_stdout(out_buffer), redirect_stderr(err_buffer):
        _execute_line_core(cleaned_line)

    stdout_text = out_buffer.getvalue()
    stderr_text = err_buffer.getvalue()

    if stderr_text:
        sys.stderr.write(stderr_text)
    if stdout_text and _should_show_silenced_output(stdout_text):
        sys.stdout.write(stdout_text)


# ---------------------------
# Graficador mejorado (simbólico o por nombre)
# ---------------------------

# ---------------------------
# Estado global de gráficos
# ---------------------------

# ---------------------------
# Generador de tablas LaTeX
# ---------------------------

_LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(text: str) -> str:
    """Escapa caracteres especiales de LaTeX en strings literales."""
    return "".join(_LATEX_ESCAPE_MAP.get(ch, ch) for ch in str(text))


def _table_rows_from_data(data: Any) -> list[list[Any]]:
    if isinstance(data, MatrixBase):
        if data.rows == 1:
            packed_rows: list[list[Any]] = []
            unpackable = True
            for c in range(data.cols):
                cell = data[0, c]
                if isinstance(cell, MatrixBase):
                    if cell.rows == 1:
                        packed_rows.append([cell[0, j] for j in range(cell.cols)])
                    elif cell.cols == 1:
                        packed_rows.append([cell[i, 0] for i in range(cell.rows)])
                    else:
                        unpackable = False
                        break
                    continue
                if isinstance(cell, np.ndarray):
                    if cell.ndim == 1:
                        packed_rows.append(cell.tolist())
                    elif cell.ndim == 2 and 1 in cell.shape:
                        packed_rows.append(cell.reshape(-1).tolist())
                    else:
                        unpackable = False
                        break
                    continue
                if isinstance(cell, (list, tuple)):
                    packed_rows.append(list(cell))
                    continue
                unpackable = False
                break
            if unpackable and packed_rows:
                widths = {len(row) for row in packed_rows}
                if len(widths) == 1:
                    return packed_rows
        return [[data[r, c] for c in range(data.cols)] for r in range(data.rows)]

    if isinstance(data, np.ndarray):
        if data.ndim == 0:
            return [[data.item()]]
        if data.ndim == 1:
            return [data.tolist()]
        if data.ndim == 2:
            return data.tolist()
        raise ValueError("table(): numpy array must be 1D or 2D.")

    if isinstance(data, (list, tuple)):
        if not data:
            return []
        if all(isinstance(row, (list, tuple, np.ndarray, MatrixBase)) for row in data):
            rows: list[list[Any]] = []
            for row in data:
                if isinstance(row, MatrixBase):
                    if row.rows == 1:
                        rows.append([row[0, c] for c in range(row.cols)])
                    elif row.cols == 1:
                        rows.append([row[r, 0] for r in range(row.rows)])
                    else:
                        raise ValueError("table(): each Matrix row must be a row or column vector.")
                    continue
                if isinstance(row, np.ndarray):
                    if row.ndim == 0:
                        rows.append([row.item()])
                    elif row.ndim == 1:
                        rows.append(row.tolist())
                    elif row.ndim == 2 and 1 in row.shape:
                        rows.append(row.reshape(-1).tolist())
                    else:
                        raise ValueError("table(): each numpy row must be 1D.")
                    continue
                rows.append(list(row))
            return rows
        return [list(data)]

    raise ValueError("table(): data must be a list of rows, a numpy.ndarray, or a SymPy Matrix.")


def _table_cell_to_latex(value: Any, escape_strings: bool = True) -> str:
    if isinstance(value, str):
        math_text = value.strip()
        # Permite insertar expresiones matematicas LaTeX en strings, ej: "$\\sigma_i$"
        if escape_strings and len(math_text) >= 2 and math_text.startswith("$") and math_text.endswith("$"):
            return math_text
        return escape_latex(value) if escape_strings else value

    if isinstance(value, (sp.Basic, np.number, int, float, complex)):
        try:
            if isinstance(value, (int, float, complex, np.number)):
                return str(value)
            return f"${sp.latex(value)}$"
        except Exception:
            return str(value)

    if isinstance(value, (sp.MatrixBase, np.ndarray, list, tuple)):
        try:
            return f"${sp.latex(sp.Matrix(value))}$"
        except Exception:
            return str(value)

    return str(value)


def _normalize_table_align(align: Any, ncols: int) -> str:
    if ncols <= 0:
        raise ValueError("table(): invalid number of columns.")
    if align is None:
        return "c" * ncols
    align_spec = str(align).strip().replace(" ", "")
    if not align_spec:
        raise ValueError("table(): align cannot be empty.")
    if len(align_spec) == 1:
        align_spec = align_spec * ncols
    elif len(align_spec) != ncols:
        raise ValueError(f"table(): align debe tener longitud 1 o {ncols}.")
    invalid = [ch for ch in align_spec if ch not in {"l", "c", "r"}]
    if invalid:
        raise ValueError("table(): align solo permite caracteres l, c o r.")
    return align_spec


def table(
    data,
    name=None,
    headers=None,
    align=None,
    caption=None,
    label=None,
    style="tabular",
    booktabs=False,
    grid=True,
    escape_strings=True,
) -> str:
    rows = _table_rows_from_data(data)
    headers_list = list(headers) if headers is not None else None

    if rows:
        ncols = len(rows[0])
        for idx, row in enumerate(rows, start=1):
            if len(row) != ncols:
                raise ValueError(f"table(): la fila {idx} tiene {len(row)} columnas, esperado {ncols}.")
    else:
        ncols = len(headers_list) if headers_list else 1

    if headers_list is not None and len(headers_list) != ncols:
        raise ValueError(f"table(): headers tiene {len(headers_list)} columnas, esperado {ncols}.")

    align_spec = _normalize_table_align(align, ncols)
    env_name = str(style).strip() or "tabular"
    use_booktabs = bool(booktabs)
    use_grid = bool(grid)
    if use_booktabs:
        use_grid = False
    col_spec = align_spec
    if use_grid:
        col_spec = "|" + "|".join(list(align_spec)) + "|"

    lines: list[str] = [f"\\begin{{{env_name}}}{{{col_spec}}}"]
    lines.append(r"\toprule" if use_booktabs else r"\hline")

    if headers_list is not None:
        header_tex = " & ".join(_table_cell_to_latex(cell, escape_strings=escape_strings) for cell in headers_list)
        lines.append(f"{header_tex} \\\\")
        lines.append(r"\midrule" if use_booktabs else r"\hline")

    for row in rows:
        row_tex = " & ".join(_table_cell_to_latex(cell, escape_strings=escape_strings) for cell in row)
        lines.append(f"{row_tex} \\\\")
        if use_grid:
            lines.append(r"\hline")

    if use_booktabs:
        lines.append(r"\bottomrule")
    elif not use_grid:
        lines.append(r"\hline")
    lines.append(f"\\end{{{env_name}}}")
    block = "\n".join(lines)

    if caption is not None or label is not None:
        wrapped: list[str] = [
            r"\begin{table}[h]",
            r"\centering",
            block,
        ]
        if caption is not None:
            wrapped.append(f"\\caption{{{_table_cell_to_latex(caption, escape_strings=escape_strings)}}}")
        if label is not None:
            wrapped.append(f"\\label{{{str(label)}}}")
        wrapped.append(r"\end{table}")
        block = "\n".join(wrapped)

    if name is None or not str(name).strip():
        next_idx = int(env_ast.get("_table_count", 0)) + 1
        env_ast["_table_count"] = next_idx
        table_id = f"table{next_idx}"
    else:
        table_id = str(name).strip()

    env_ast.setdefault("_table_blocks", {})[table_id] = block
    env_ast["last_table"] = table_id

    if use_booktabs:
        required = env_ast.setdefault("_required_packages", set())
        if not isinstance(required, set):
            required = set(required if isinstance(required, (list, tuple, set)) else [required])
            env_ast["_required_packages"] = required
        required.add("booktabs")

    return table_id


register_shared_symbols(COMMON_SYMBOLS, PARSER_LOCAL_DICT, {"table": table})


_PLOT_COUNTER = 0
_PLOT_MODE = "interactive"
_DOCUMENT_PLOT_OUTPUT_DIR = "."
_PLOT_LISTENERS: list[Callable[[str, str], None]] = []
_CONSOLE_CLEAR_LISTENERS: list[Callable[[], None]] = []
_PLOT_BACKEND = PlotBackend(plot_mode=_PLOT_MODE, output_dir=".")


def _sanitize_plot_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    base = str(raw).strip().replace(" ", "_")
    if base.endswith(".png"):
        base = base[:-4]
    return base or None


def _next_plot_name(custom_name: str | None = None) -> str:
    global _PLOT_COUNTER
    sanitized = _sanitize_plot_name(custom_name)
    if sanitized:
        return sanitized
    _PLOT_COUNTER += 1
    return f"plot{_PLOT_COUNTER}"


def _register_plot_file(plot_name: str, filepath: str) -> str:
    filename_local = os.path.basename(filepath)
    plot_files = env_ast.setdefault("_plot_files", {})
    plot_files[plot_name] = filename_local
    plot_files["last_plot"] = filename_local
    env_ast["last_plot"] = filename_local
    existing_binding = env_ast.get(plot_name)
    if plot_name not in COMMON_SYMBOLS and plot_name not in PARSER_LOCAL_DICT:
        if existing_binding is None or isinstance(existing_binding, str):
            env_ast[plot_name] = filename_local
    env_ast.setdefault("plots", []).append(filename_local)
    return filename_local


def _emit_plot_to_listeners(fig, plot_name: str) -> str:
    temp_dir = Path(tempfile.gettempdir()) / "mathtex_plots"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{plot_name}_{time.time_ns()}.png"
    fig.savefig(temp_path, bbox_inches="tight")
    _notify_plot_listeners(str(temp_path), plot_name)
    return str(temp_path)


def _is_vector_plot_call(args: tuple[Any, ...]) -> bool:
    if len(args) not in {1, 2, 3}:
        return False
    if len(args) == 1:
        return not isinstance(args[0], str)
    if len(args) == 2:
        if isinstance(args[1], str):
            return not isinstance(args[0], str)
        return not isinstance(args[0], str) and not isinstance(args[1], str)
    return (
        not isinstance(args[0], str)
        and not isinstance(args[1], str)
        and isinstance(args[2], str)
    )


def set_plot_mode(mode: str) -> None:
    """Define el modo actual del subsistema de graficos."""
    global _PLOT_MODE
    if mode not in {"interactive", "document"}:
        mode = "interactive"
    _PLOT_MODE = mode
    _PLOT_BACKEND.set_mode(_PLOT_MODE)


def get_plot_mode() -> str:
    return _PLOT_MODE


def set_document_output_dir(path: str | Path) -> None:
    global _DOCUMENT_PLOT_OUTPUT_DIR
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    _DOCUMENT_PLOT_OUTPUT_DIR = str(target)
    if _PLOT_MODE == "document":
        _PLOT_BACKEND.set_output_dir(target)


def get_document_output_dir() -> str:
    return _DOCUMENT_PLOT_OUTPUT_DIR


def register_plot_listener(callback: Callable[[str, str], None]) -> None:
    if callback and callback not in _PLOT_LISTENERS:
        _PLOT_LISTENERS.append(callback)


def unregister_plot_listener(callback: Callable[[str, str], None]) -> None:
    if callback in _PLOT_LISTENERS:
        _PLOT_LISTENERS.remove(callback)


def _notify_plot_listeners(filepath: str, plot_name: str) -> None:
    if not _PLOT_LISTENERS:
        return
    for callback in list(_PLOT_LISTENERS):
        try:
            callback(filepath, plot_name)
        except Exception:
            continue


def register_console_clear_listener(callback: Callable[[], None]) -> None:
    if callback and callback not in _CONSOLE_CLEAR_LISTENERS:
        _CONSOLE_CLEAR_LISTENERS.append(callback)


def unregister_console_clear_listener(callback: Callable[[], None]) -> None:
    if callback in _CONSOLE_CLEAR_LISTENERS:
        _CONSOLE_CLEAR_LISTENERS.remove(callback)


def _notify_console_clear_listeners() -> bool:
    if not _CONSOLE_CLEAR_LISTENERS:
        return False
    notified = False
    for callback in list(_CONSOLE_CLEAR_LISTENERS):
        try:
            callback()
            notified = True
        except Exception:
            continue
    return notified


def plot(*args, a: float = -5.0, b: float = 5.0, n: int = 400, name: str | None = None) -> str | None:
    """plot 2D minimo compatible + compatibilidad legacy."""
    try:
        _PLOT_BACKEND.set_mode(_PLOT_MODE)
        output_dir = _DOCUMENT_PLOT_OUTPUT_DIR if _PLOT_MODE == "document" else "."
        _PLOT_BACKEND.set_output_dir(output_dir)

        if _is_vector_plot_call(args):
            plot_name = _next_plot_name(name)
            output_name = f"{plot_name}.png" if _PLOT_MODE == "document" else plot_name
            result = _PLOT_BACKEND.plot(*args, output_name=output_name)
            if _PLOT_MODE == "document" and isinstance(result, str):
                return _register_plot_file(plot_name, result)
            if isinstance(result, str):
                return result
            return None

        def _render_backend(custom_name: str | None = None) -> str | None:
            if _PLOT_MODE == "document":
                plot_name = _next_plot_name(custom_name)
                output_name = f"{plot_name}.png"
                rendered = _PLOT_BACKEND._render(output_name=output_name)
                if isinstance(rendered, str):
                    return _register_plot_file(plot_name, rendered)
                return None
            _PLOT_BACKEND._render()
            return None

        if len(args) == 3 and isinstance(args[0], sp.Basic):
            expr, a_val, b_val = args
            a_val = float(sp.N(a_val))
            b_val = float(sp.N(b_val))
            X = np.linspace(a_val, b_val, n)
            Y = [float(sp.N(expr.subs(x, xi))) for xi in X]

            ax = _PLOT_BACKEND._ensure_axes()
            if not _PLOT_BACKEND.hold:
                ax.cla()
            ax.plot(X, Y)
            if not _PLOT_BACKEND.xlabel_text:
                ax.set_xlabel("$x$")
            if not _PLOT_BACKEND.ylabel_text:
                ax.set_ylabel("$f(x)$")
            _PLOT_BACKEND._apply_axes_state()
            return _render_backend(name)

        X = np.linspace(a, b, n)
        ax = _PLOT_BACKEND._ensure_axes()
        if not _PLOT_BACKEND.hold:
            ax.cla()
        plotted = False
        plotted_names: list[str] = []
        var_label = None
        var_mismatch = False
        for fname in args:
            if fname not in env_ast:
                print(f"Function {fname} is not defined.")
                continue

            F_sym = env_ast[fname]
            var_sym = x
            vars_info = env_ast.get(f"{fname}_vars")
            if isinstance(vars_info, (list, tuple)):
                if len(vars_info) == 1:
                    var_sym = vars_info[0]
                else:
                    print(f"Function {fname} is not univariate; it cannot be plotted in 1D.")
                    continue
            Y = []
            for xi in X:
                val = F_sym.subs(var_sym, xi).evalf()
                Y.append(float(val) if val.is_real else np.nan)
            ax.plot(X, Y, label=fname)
            plotted = True
            plotted_names.append(fname)
            if var_label is None:
                var_label = var_sym
            elif var_label != var_sym:
                var_mismatch = True

        if not plotted:
            print("No valid function was plotted.")
            return None

        if not _PLOT_BACKEND.xlabel_text:
            if var_label is not None and not var_mismatch:
                ax.set_xlabel(f"${sp.latex(var_label)}$")
            else:
                ax.set_xlabel("$x$")
        if not _PLOT_BACKEND.ylabel_text:
            ax.set_ylabel("$f(x)$")
        if plotted_names:
            ax.legend()
        _PLOT_BACKEND._apply_axes_state()
        return _render_backend(name)

    except PlotBackendError as e:
        print(f"Error in plot: {e}")
        return None
    except Exception as e:
        print(f"Error in plot(): {e}")
        return None


def title(text: Any) -> None:
    _PLOT_BACKEND.title(text)


def xlabel(text: Any) -> None:
    _PLOT_BACKEND.xlabel(text)


def ylabel(text: Any) -> None:
    _PLOT_BACKEND.ylabel(text)


def grid(state: Any) -> None:
    _PLOT_BACKEND.set_grid(state)


def hold(state: Any) -> None:
    _PLOT_BACKEND.set_hold(state)


def legend(*args: Any) -> None:
    _PLOT_BACKEND.legend(*args)


def reset_plot_state(env: dict | None = None) -> None:
    global _PLOT_COUNTER
    _PLOT_COUNTER = 0
    _PLOT_BACKEND.reset()
    _PLOT_BACKEND.set_mode(_PLOT_MODE)
    target = env if env is not None else env_ast
    if target is None:
        return
    target.pop("_plot_files", None)
    target.pop("plots", None)
    target.pop("last_plot", None)


def reset_environment(env: dict | None = None) -> None:
    """Limpia el entorno de variables y restablece estados transitorios."""
    global _OCT_BLOCK_ACTIVE, _OCT_BLOCK_LINES, _OCT_NEST_LEVEL, _FUNC_BLOCK_ACTIVE, _FUNC_DEF, _FUNC_NEST_LEVEL

    target = env_ast if env is None else env
    target.clear()
    env_lambdified.clear()
    user_norms.clear()
    user_inners.clear()
    _LOADED_MODULES.clear()
    _MODULE_PATH_CACHE.clear()
    _MODULE_LOAD_STACK.clear()
    _MODULE_LOAD_PATH_STACK.clear()
    reset_numeric_format()
    reset_plot_state(target)

    _OCT_BLOCK_ACTIVE = False
    _OCT_BLOCK_LINES = []
    _OCT_NEST_LEVEL = 0
    _OCT_NEST_LEVEL = 0
    _FUNC_BLOCK_ACTIVE = False
    _FUNC_DEF = None
    _FUNC_NEST_LEVEL = 0

    if target is not env_ast:
        env_ast.clear()
        env_ast.update(target)


def _infer_packed_function_vars(values: tuple[Any, ...]) -> Matrix | None:
    free_symbols: set[sp.Symbol] = set()
    for value in values:
        try:
            current_symbols = getattr(value, "free_symbols", None)
        except Exception:
            current_symbols = None
        if current_symbols:
            free_symbols.update(current_symbols)
    if not free_symbols:
        return None
    ordered = _mt_ordered_symbols(free_symbols)
    if not ordered:
        return None
    return Matrix([ordered])


class UserFunction:
    """Representa una función definida por el usuario en sintaxis MathTeX/Octave."""

    def __init__(
        self,
        name: str,
        args: list[str],
        outputs: list[str],
        body: list[str],
        working_dir: Path,
        defining_env: dict[str, Any] | None = None,
    ):
        self.name = _normalize_name(name)
        self.args = [_normalize_name(a) for a in args]
        self.outputs = [_normalize_name(o) for o in outputs]
        self.body = body
        self.working_dir = working_dir
        self.defining_env = defining_env if defining_env is not None else env_ast

    def __call__(self, *call_args):
        if len(call_args) != len(self.args):
            if len(call_args) > len(self.args) and self.args and self.args[0].lower() == "f":
                if len(self.args) >= 2 and self.args[1].lower() in {"vars", "variables"}:
                    packed_count = len(call_args) - len(self.args) + 2
                    if packed_count > 1:
                        derived_vars = _infer_packed_function_vars(call_args[:packed_count])
                        if derived_vars is not None:
                            call_args = (Matrix(list(call_args[:packed_count])), derived_vars) + call_args[packed_count:]
                if len(call_args) != len(self.args):
                    packed_count = len(call_args) - len(self.args) + 1
                    call_args = (Matrix(list(call_args[:packed_count])),) + call_args[packed_count:]
            if len(call_args) != len(self.args):
                raise ValueError(f"{self.name} espera {len(self.args)} argumento(s), recibio {len(call_args)}.")

        global env_ast, _WORKING_DIR
        local_env = dict(self.defining_env)
        for arg_name, value in zip(self.args, call_args):
            local_env[arg_name] = value

        prev_env = env_ast
        prev_dir = _WORKING_DIR
        env_ast = local_env
        _WORKING_DIR = self.working_dir
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        try:
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                _run_function_lines(self.body)
        finally:
            stdout_text = out_buf.getvalue()
            stderr_text = err_buf.getvalue()
            if stderr_text:
                sys.stderr.write(stderr_text)
            env_ast = prev_env
            _WORKING_DIR = prev_dir

        if not self.outputs:
            return None
        results = []
        for out_name in self.outputs:
            if out_name not in local_env:
                raise ValueError(f"{self.name}: la salida '{out_name}' no fue asignada.")
            results.append(_mt_normalize_value(local_env[out_name], local_env))
        if len(results) == 1:
            return results[0]
        return tuple(results)


@contextmanager
def _temporary_runtime_env(temp_env: dict[str, Any], working_dir: Path | None = None):
    global env_ast, _WORKING_DIR
    previous_env = env_ast
    previous_dir = _WORKING_DIR
    env_ast = temp_env
    if working_dir is not None:
        _set_working_dir(working_dir)
    try:
        yield
    finally:
        env_ast = previous_env
        if working_dir is not None:
            _set_working_dir(previous_dir)


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _WORKING_DIR / path
    return path


def _set_working_dir(path: Path) -> bool:
    global _WORKING_DIR
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        print(f"Error resolving path: {exc}")
        return False
    if not resolved.exists() or not resolved.is_dir():
        print(f"Directory does not exist: {resolved}")
        return False
    try:
        os.chdir(resolved)
    except OSError as exc:
        print(f"Could not change to directory {resolved}: {exc}")
        return False
    _WORKING_DIR = resolved
    return True


def _run_script_file(path: Path, silent: bool = False) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Could not open {path}: {exc}")
        return

    # Reuse the same statement splitter used by .mtex code blocks so imports
    # can handle multiline calls such as table(...) or long vector literals.
    from mtex_executor import split_code_statements_with_lines

    statements = split_code_statements_with_lines(content)
    previous_dir = _WORKING_DIR
    _set_working_dir(path.parent)
    try:
        if not silent:
            print(f">> {path.name}")
            for statement in statements:
                with diagnostic_line_offset(statement.start_line - 1):
                    ejecutar_linea(statement.text)
            return
        out_buffer = io.StringIO()
        err_buffer = io.StringIO()
        with redirect_stdout(out_buffer), redirect_stderr(err_buffer):
            for statement in statements:
                with diagnostic_line_offset(statement.start_line - 1):
                    ejecutar_linea(statement.text)
        stdout_text = out_buffer.getvalue()
        err_text = err_buffer.getvalue()
        if err_text:
            sys.stderr.write(err_text)
        if stdout_text and _should_show_silenced_output(stdout_text):
            sys.stdout.write(stdout_text)
    finally:
        _set_working_dir(previous_dir)


def change_working_dir(path: str | Path) -> bool:
    """API publica para cambiar el directorio de trabajo."""
    return _set_working_dir(Path(path))


def get_working_dir() -> Path:
    return _WORKING_DIR


def list_working_dir_files(pattern: str | None = None) -> list[Path]:
    try:
        entries = list(_WORKING_DIR.iterdir())
    except OSError:
        return []
    files = [p for p in entries if p.is_file()]
    if pattern:
        files = [p for p in files if p.match(pattern)]
    return sorted(files)


def _find_project_root(start_dir: Path) -> Path | None:
    try:
        current = start_dir.expanduser().resolve()
    except OSError:
        return None
    for candidate in [current, *current.parents]:
        if (candidate / ".mtexproj").exists():
            return candidate
    return None


def _module_relative_path(module_name: str) -> Path:
    parts = [part for part in module_name.split(".") if part]
    return Path(*parts) if parts else Path(module_name)


def _module_search_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    candidates = [_WORKING_DIR]
    project_root = _find_project_root(_WORKING_DIR)
    if project_root is not None:
        candidates.append(project_root)
    candidates.append(Path.cwd())
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _resolve_module_file(module_name: str) -> tuple[Path | None, Path | None]:
    relative_path = _module_relative_path(module_name)
    found_mtex: Path | None = None
    for root in _module_search_roots():
        candidate_mtx = (root / relative_path).with_suffix(".mtx")
        if candidate_mtx.exists() and candidate_mtx.is_file():
            return candidate_mtx.resolve(), None
        candidate_mtex = (root / relative_path).with_suffix(".mtex")
        if found_mtex is None and candidate_mtex.exists() and candidate_mtex.is_file():
            found_mtex = candidate_mtex.resolve()

    project_root = _find_project_root(_WORKING_DIR)
    if project_root is not None and len(relative_path.parts) == 1:
        filename_mtx = f"{relative_path.name}.mtx"
        matches_mtx = sorted(project_root.rglob(filename_mtx), key=lambda path: (len(path.parts), str(path)))
        if matches_mtx:
            return matches_mtx[0].resolve(), None
        filename_mtex = f"{relative_path.name}.mtex"
        matches_mtex = sorted(project_root.rglob(filename_mtex), key=lambda path: (len(path.parts), str(path)))
        if matches_mtex:
            found_mtex = matches_mtex[0].resolve()
    return None, found_mtex


def _is_module_export(name: str, value: Any) -> bool:
    normalized = _normalize_name(name)
    if normalized.endswith("_vars") or normalized.endswith("_expr_py"):
        return False
    return not _is_protected_name(normalized, value)


def _collect_module_exports(module_env: dict[str, Any]) -> dict[str, Any]:
    exports: dict[str, Any] = {}
    for name, value in module_env.items():
        normalized = _normalize_name(name)
        if not _is_module_export(normalized, value):
            continue
        exports[normalized] = value
    return exports


def _merge_module_runtime_artifacts(module_obj: MathTeXModule, target_env: dict[str, Any]) -> None:
    table_blocks = module_obj.env.get("_table_blocks")
    if isinstance(table_blocks, dict) and table_blocks:
        target_env.setdefault("_table_blocks", {}).update(table_blocks)
    last_table = module_obj.env.get("last_table")
    if last_table is not None:
        target_env["last_table"] = last_table

    plot_files = module_obj.env.get("_plot_files")
    if isinstance(plot_files, dict) and plot_files:
        target_env.setdefault("_plot_files", {}).update(plot_files)
    plots = module_obj.env.get("plots")
    if isinstance(plots, list) and plots:
        target_env.setdefault("plots", []).extend(plots)
    last_plot = module_obj.env.get("last_plot")
    if last_plot is not None:
        target_env["last_plot"] = last_plot


def _load_module(module_name: str) -> MathTeXModule:
    normalized_name = module_name.strip()
    cached = _LOADED_MODULES.get(normalized_name)
    if cached is not None:
        return cached

    target_path, blocked_mtex = _resolve_module_file(normalized_name)
    if target_path is None:
        if blocked_mtex is not None:
            raise MathTeXImportError(
                f"ImportError: Cannot import document module '{normalized_name}'; only .mtx files are importable"
            )
        raise MathTeXImportError(f"ImportError: Module '{normalized_name}' not found")

    cache_key = str(target_path)
    cached_by_path = _MODULE_PATH_CACHE.get(cache_key)
    if cached_by_path is not None:
        _LOADED_MODULES[normalized_name] = cached_by_path
        return cached_by_path

    if cache_key in _MODULE_LOAD_PATH_STACK:
        if normalized_name in _MODULE_LOAD_STACK:
            cycle = _MODULE_LOAD_STACK[_MODULE_LOAD_STACK.index(normalized_name) :] + [normalized_name]
        else:
            cycle = _MODULE_LOAD_STACK + [normalized_name]
        raise MathTeXImportError(f"ImportError: Circular import detected: {' -> '.join(cycle)}")

    module_env: dict[str, Any] = {}
    _MODULE_LOAD_STACK.append(normalized_name)
    _MODULE_LOAD_PATH_STACK.append(cache_key)
    try:
        with _temporary_runtime_env(module_env, target_path.parent):
            _run_script_file(target_path, silent=True)
    finally:
        _MODULE_LOAD_STACK.pop()
        _MODULE_LOAD_PATH_STACK.pop()

    module_obj = MathTeXModule(
        name=normalized_name,
        path=target_path,
        exports=_collect_module_exports(module_env),
        env=module_env,
    )
    _LOADED_MODULES[normalized_name] = module_obj
    _MODULE_PATH_CACHE[cache_key] = module_obj
    return module_obj


def _parse_from_import_names(names_raw: str) -> list[str]:
    raw_names = [name.strip() for name in names_raw.split(",") if name.strip()]
    if not raw_names:
        raise MathTeXImportError("ImportError: Missing imported symbol name")
    if any(name == "*" for name in raw_names):
        raise MathTeXImportError("ImportError: 'from module import *' is not supported")
    normalized: list[str] = []
    for raw_name in raw_names:
        if not re.fullmatch(r"[A-Za-z_]\w*", raw_name):
            raise MathTeXImportError(f"ImportError: Invalid imported symbol '{raw_name}'")
        normalized.append(_normalize_name(raw_name))
    return normalized


def _handle_import(module: str) -> None:
    module_obj = _load_module(module)
    _merge_module_runtime_artifacts(module_obj, env_ast)
    binding_name = _normalize_name(module.split(".")[-1])
    env_ast[binding_name] = module_obj


def _handle_from_import(module: str, names_raw: str) -> None:
    module_obj = _load_module(module)
    _merge_module_runtime_artifacts(module_obj, env_ast)
    names = _parse_from_import_names(names_raw)
    missing = [name for name in names if name not in module_obj.exports]
    if missing:
        raise MathTeXImportError(f"ImportError: Module '{module_obj.name}' does not export '{missing[0]}'")
    for name in names:
        env_ast[name] = module_obj.exports[name]

# ---------------------------
# Graficador 3D
# ---------------------------

def plot3(f_expr, x_sym, y_sym, a, b, c, d, n=100):
    """Grafica f(x,y) en el dominio [a,b]×[c,d]."""

    plt, cm = _ensure_matplotlib_plot3()

    # Crear malla
    X = np.linspace(float(a), float(b), n)
    Y = np.linspace(float(c), float(d), n)
    X, Y = np.meshgrid(X, Y)

    # Convertir función simbólica a función NumPy
    f_num = lambdify((x_sym, y_sym), f_expr, "numpy")

    try:
        Z = f_num(X, Y)
    except Exception as e:
        print(f"Error while evaluating f(x,y) numerically: {e}")
        return

    # Gráfico 3D
    fig = plt.figure()
    ax = fig.add_subplot(111, projection="3d")
    surf = ax.plot_surface(X, Y, Z, cmap=cm.get_cmap('viridis'), linewidth=0, antialiased=True)
    ax.set_xlabel(str(x_sym))
    ax.set_ylabel(str(y_sym))
    ax.set_zlabel("f(x,y)")
    fig.colorbar(surf, shrink=0.5, aspect=10)
    plt.show()

# ---------------------------
# Newton-Raphson simbólico
# ---------------------------

def NR(F_sym, x0: float, tol: float = 1e-8, max_iter: int = 1000) -> float | None:
    global env_ast
    def _coerce_float(value: Any, label: str) -> float:
        coerced = _mt_coerce_near_real(value)
        if isinstance(coerced, complex):
            raise ValueError(f"{label} must be real.")
        try:
            return float(coerced)
        except Exception:
            try:
                return float(sp.N(coerced))
            except Exception as exc:
                raise ValueError(f"Invalid {label}: {exc}") from exc

    try:
        x0_num = _coerce_float(x0, "initial guess")
        tol_num = _coerce_float(tol, "tolerance")
    except Exception as exc:
        print(f"Did not converge: {exc}")
        return None

    x_symbol = symbols("x")
    F_l = lambdify(x_symbol, F_sym, "numpy")
    dF_l = lambdify(x_symbol, diff(F_sym, x_symbol), "numpy")
    env_ast.setdefault("nr_roots", [])
    try:
        root = scipy_newton(F_l, x0_num, fprime=dF_l, tol=tol_num, maxiter=max_iter)
    except RuntimeError:
        print("Did not converge.")
        return None
    except OverflowError as exc:
        print(f"Did not converge: {exc}")
        return None
    except ZeroDivisionError:
        print("Zero derivative. Cannot continue.")
        return None
    except Exception as exc:
        print(f"Did not converge: {exc}")
        return None

    root_value = _mt_coerce_near_real(root)
    print(f"Root found: x = {root_value}")
    env_ast["nr_last_root"] = root_value
    env_ast["nr_roots"].append(root_value)
    idx = env_ast.get("_nr_counter", 0) + 1
    env_ast["_nr_counter"] = idx
    env_ast[f"nr_root_{idx}"] = root_value
    return root_value


# Expone NR como funcion disponible en expresiones/asignaciones (ej: x = \NR(...)).
register_shared_symbols(COMMON_SYMBOLS, PARSER_LOCAL_DICT, {"NR": NR, "nr": NR})
# Expone N como alias del espacio nulo tambien en el runtime AST
# para soportar expresiones anidadas como \N(\adj(A)).
register_shared_symbols(COMMON_SYMBOLS, PARSER_LOCAL_DICT, {"N": _mat_null})


def _build_parser_context() -> ParserContext:
    ctx = ParserContext(
        env_ast=env_ast,
        greek_symbols=greek_symbols,
        greek_display=greek_display,
        user_norms=user_norms,
        user_inners=user_inners,
        latex_to_python=latex_to_python,
        common_symbols={**COMMON_SYMBOLS},
        plot_func=plot,
        plot_backend=_PLOT_BACKEND,
        plot3_func=plot3,
        nr_func=NR,
        run_line=ejecutar_linea,
    )
    ctx.expr_to_python = lambda expr: _oct_expr_to_python(expr, ctx)
    return ctx


def _sync_scope_to_env(scope: dict, ctx: ParserContext) -> None:
    reserved = set(_INTERNAL_RESERVED_NAMES)
    reserved.update(ctx.common_symbols.keys())
    reserved.update(ctx.greek_symbols.keys())
    for name, value in scope.items():
        if name.startswith("__") or name in reserved:
            continue
        if isinstance(value, types.ModuleType):
            continue
        ctx.env_ast[name] = value



