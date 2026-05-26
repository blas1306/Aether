from __future__ import annotations

import re
from typing import Any, List, cast

import numpy as np
from scipy import linalg as scipy_linalg
import sympy as sp
from sympy import Matrix, MatrixBase, Rational, Expr, default_sort_key

from numeric_format import format_value_for_display, try_format_numeric_scalar
from parser_common import _split_top_level
from .context import ParserContext

MULTI_OUTPUT_COMMANDS = {r"\LU", r"\LDU", r"\Spec", r"\Eig", r"\Schur", r"\QR", r"\QR1", r"\SVD", r"\sort", r"\size", r"\polar"}

LINEAR_SOLVE_UNIQUE = "unique"
LINEAR_SOLVE_MINIMUM_NORM = "minimum_norm"
LINEAR_SOLVE_LEAST_SQUARES = "least_squares"


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


def _split_top_level_args(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    paren = bracket = brace = 0
    in_str = False
    quote = ""
    escape = False
    for ch in text:
        if escape:
            current.append(ch)
            escape = False
            continue
        if ch == "\\":
            current.append(ch)
            escape = True
            continue
        if in_str:
            current.append(ch)
            if ch == quote:
                in_str = False
                quote = ""
            continue
        if ch in {"'", '"'}:
            current.append(ch)
            in_str = True
            quote = ch
            continue
        if ch == "(":
            paren += 1
            current.append(ch)
            continue
        if ch == ")":
            paren = max(paren - 1, 0)
            current.append(ch)
            continue
        if ch == "[":
            bracket += 1
            current.append(ch)
            continue
        if ch == "]":
            bracket = max(bracket - 1, 0)
            current.append(ch)
            continue
        if ch == "{":
            brace += 1
            current.append(ch)
            continue
        if ch == "}":
            brace = max(brace - 1, 0)
            current.append(ch)
            continue
        if ch == "," and paren == 0 and bracket == 0 and brace == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    parts.append("".join(current).strip())
    return parts


def _find_matching_bracket(text: str, start_idx: int) -> int | None:
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
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return idx
    return None


def pretty_span(vectors: List[List[Any]]) -> str:
    """Muestra vectores en formato span{(a,b); (c,d)}."""
    if not vectors:
        return "{0}"
    formatted = ["(" + ", ".join(format_value_for_display(val) for val in v) + ")" for v in vectors]
    return "span{" + "; ".join(formatted) + "}"


def matrix_to_flat_list(vec: MatrixBase) -> List[Any]:
    """Devuelve los elementos de una matriz como lista plana."""
    data = vec.tolist()
    if vec.cols == 1:
        return [row[0] for row in data]
    # Aplana en orden fila a fila para matrices generales
    return [item for row in data for item in row]


def normalize_column_vector(vec: MatrixBase) -> Matrix:
    """Devuelve un vector columna normalizado (norma 1) si es posible."""
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


def _is_hermitian_matrix(mat: MatrixBase) -> bool:
    try:
        diff = sp.simplify(Matrix(mat) - Matrix(mat).conjugate().T)
        return diff == Matrix.zeros(mat.rows, mat.cols)
    except Exception:
        try:
            return bool(mat == mat.conjugate().T)
        except Exception:
            return False


def _is_unitary_matrix(mat: MatrixBase) -> bool:
    try:
        A = Matrix(mat)
        ident = Matrix.eye(A.rows)
        left = sp.simplify(A.conjugate().T * A - ident)
        right = sp.simplify(A * A.conjugate().T - ident)
        return left == Matrix.zeros(A.rows, A.cols) and right == Matrix.zeros(A.rows, A.cols)
    except Exception:
        return False


def _is_normal_matrix(mat: MatrixBase) -> bool:
    try:
        A = Matrix(mat)
        diff = sp.simplify(A * A.conjugate().T - A.conjugate().T * A)
        return diff == Matrix.zeros(A.rows, A.cols)
    except Exception:
        return False


def _normalized_eigenvector_matrix(P: MatrixBase) -> Matrix:
    P_norm = Matrix(P)
    try:
        cols = []
        for idx in range(P_norm.shape[1]):
            cols.append(normalize_column_vector(P_norm.col(idx)))
        if cols:
            return Matrix.hstack(*cols)
    except Exception:
        pass
    return Matrix(P)


def _diagonalize_matrix(A: MatrixBase) -> tuple[Matrix, Matrix]:
    P, D = A.diagonalize(normalize=True, reals_only=False)
    return _normalized_eigenvector_matrix(P), Matrix(D)


def _matrix_to_numeric_array(A: MatrixBase) -> np.ndarray:
    mat = Matrix(A)
    if mat.rows != mat.cols:
        raise ValueError("Schur decomposition requires a square matrix.")
    data: list[list[complex]] = []
    for row in mat.tolist():
        numeric_row: list[complex] = []
        for value in row:
            expr = sp.sympify(value)
            if getattr(expr, "free_symbols", None):
                raise ValueError("Schur decomposition currently supports numeric matrices only.")
            numeric_row.append(complex(sp.N(expr)))
        data.append(numeric_row)
    return np.array(data, dtype=np.complex128)


def _cleanup_numeric_matrix(arr: np.ndarray, tol: float = 1e-10) -> Matrix:
    cleaned = arr.copy()
    cleaned[np.abs(cleaned) < tol] = 0
    return Matrix(cleaned.tolist())


def _schur_decomposition_numeric(A: MatrixBase, tol: float = 1e-10) -> tuple[Matrix, Matrix]:
    current = _matrix_to_numeric_array(A)
    T_np, Q_np = scipy_linalg.schur(current, output="complex")
    return _cleanup_numeric_matrix(Q_np, tol=tol), _cleanup_numeric_matrix(T_np, tol=tol)


def solve_linear_system_octave(A: MatrixBase, b: MatrixBase) -> tuple[Matrix, str]:
    """Resuelve A x = b con semantica estilo Octave."""
    A_mat = Matrix(A)
    b_mat = Matrix(b)
    if b_mat.rows == 1 and b_mat.cols == A_mat.rows:
        b_mat = b_mat.T
    if A_mat.rows != b_mat.rows:
        raise ValueError("the number of rows in A and b must match.")

    try:
        exact_sol, params = A_mat.gauss_jordan_solve(b_mat)
        if getattr(params, "rows", 0) == 0:
            if A_mat.is_square and A_mat.det() != 0:
                return Matrix(A_mat.LUsolve(b_mat)), LINEAR_SOLVE_UNIQUE
            return Matrix(exact_sol), LINEAR_SOLVE_UNIQUE
        return Matrix(A_mat.pinv() * b_mat), LINEAR_SOLVE_MINIMUM_NORM
    except ValueError:
        return Matrix(A_mat.pinv() * b_mat), LINEAR_SOLVE_LEAST_SQUARES
    except Exception as exc:
        raise ValueError(f"could not solve the linear system: {exc}") from exc


def _replace_user_function_calls(expr_py: str, env: dict[str, Any]) -> str:
    """Reescribe f(...) como _mt_call('f', ...) dentro de expresiones de matriz."""
    if not env:
        return expr_py

    def _is_user_func(name: str) -> bool:
        return f"{name}_vars" in env and isinstance(env.get(name), Expr)

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
            out.append(expr_py[i:paren_start + 1])
            i = paren_start + 1
            continue
        if not _is_user_func(name):
            out.append(expr_py[i:paren_start + 1])
            i = paren_start + 1
            continue
        paren_end = _find_matching_paren(expr_py, paren_start)
        if paren_end is None:
            out.append(expr_py[i:])
            break
        args_text = expr_py[paren_start + 1 : paren_end].strip()
        if args_text:
            args_text = _replace_user_function_calls(args_text, env)
            repl = f"_mt_call('{name}', {args_text})"
        else:
            repl = f"_mt_call('{name}')"
        out.append(expr_py[i:start])
        out.append(repl)
        i = paren_end + 1
    return "".join(out)


def matrix_to_str(M, greek_display=None, decimals: int = 6) -> str:
    """Representacion tipo Octave/MATLAB para matrices."""
    del decimals
    if greek_display is None:
        greek_display = {}
    if not isinstance(M, MatrixBase):
        return format_value_for_display(M)
    rows_list = M.tolist()

    formatted_rows: list[list[str]] = []
    col_widths = [0] * M.cols

    for r, row in enumerate(rows_list):
        formatted_row: list[str] = []
        for c, val in enumerate(row):
            formatted = try_format_numeric_scalar(val)
            if formatted is None:
                s = str(val)
                for name, symbol in greek_display.items():
                    s = re.sub(rf"\b{name}\b", symbol, s)
            else:
                s = formatted
            formatted_row.append(s)
            col_widths[c] = max(col_widths[c], len(s))
        formatted_rows.append(formatted_row)

    lines = []
    for row in formatted_rows:
        padded_row = [cell.rjust(col_widths[idx]) for idx, cell in enumerate(row)]
        lines.append("  ".join(padded_row))
    return "\n  " + "\n  ".join(lines)


def _extend_orthonormal_matrix(base: Matrix, target_cols: int) -> Matrix:
    """Extiende una matriz con columnas ortonormales hasta llegar a target_cols columnas."""
    rows = base.rows
    if target_cols <= base.cols:
        return Matrix(base[:, :target_cols])

    basis_cols: list[Matrix] = [base.col(i) for i in range(base.cols)]
    identity = Matrix.eye(rows)
    candidate_idx = 0

    while len(basis_cols) < target_cols:
        vec = identity.col(candidate_idx % rows)
        candidate_idx += 1
        for b in basis_cols:
            proj = (b.conjugate().T * vec)[0]
            if proj != 0:
                vec -= proj * b
        norm_sq = sp.simplify((vec.conjugate().T * vec)[0])
        if norm_sq == 0:
            continue
        vec = vec / sp.sqrt(norm_sq)
        basis_cols.append(vec)

    return Matrix.hstack(*basis_cols)


def _assign_decomposition_outputs(
    targets: list[str] | None,
    default_names: list[str],
    values: list[Any],
    env_ast: dict[str, Any],
    label: str,
) -> list[str] | None:
    """Asigna los resultados de una descomposicion y devuelve los nombres usados."""
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


def _lu_permutation_matrix(num_rows: int, swaps: Any) -> Matrix:
    """Convierte swaps de LUdecomposition() a matriz de permutacion."""
    if isinstance(swaps, MatrixBase):
        return Matrix(swaps)

    P = Matrix.eye(num_rows)
    if not isinstance(swaps, (list, tuple)):
        return P

    for item in swaps:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            i = int(item[0])
            j = int(item[1])
        except Exception:
            continue
        if i == j:
            continue
        if 0 <= i < num_rows and 0 <= j < num_rows:
            P.row_swap(i, j)
    return P


def _first_nonsingleton_dim(matrix: MatrixBase) -> int:
    """Devuelve la primera dimension con mas de un elemento (estilo Octave)."""
    if matrix.rows > 1:
        return 1
    if matrix.cols > 1:
        return 2
    return 1


def _matrix_is_numeric(mat: MatrixBase) -> bool:
    """Indica si todos los elementos son numericos (sin simbolos libres)."""
    for val in mat:
        try:
            expr = sp.sympify(val)
        except Exception:
            return False
        if not bool(expr.is_number):
            return False
    return True


def _to_python_numeric(value: Any) -> Any:
    """Convierte escalar de NumPy a Python conservando complejos cuando haga falta."""
    try:
        cval = complex(value)
    except Exception:
        return value
    if abs(cval.imag) < 1e-12:
        real = float(cval.real)
        if abs(real) < 1e-15:
            return 0.0
        return real
    return complex(cval.real, cval.imag)


def _numeric_svd_full(mat: MatrixBase) -> tuple[Matrix, Matrix, Matrix]:
    """SVD completa numerica: A = U * S * V^H."""
    rows, cols = mat.shape
    arr = np.asarray(mat.tolist(), dtype=complex)
    if np.allclose(arr.imag, 0.0, atol=1e-12):
        arr_work = arr.real.astype(float)
        complex_mode = False
    else:
        arr_work = arr
        complex_mode = True

    U_np, s_vals, Vh_np = np.linalg.svd(arr_work, full_matrices=True)
    Sigma_np = np.zeros((rows, cols), dtype=complex if complex_mode else float)
    diag_len = min(rows, cols, len(s_vals))
    for idx in range(diag_len):
        Sigma_np[idx, idx] = s_vals[idx]
    V_np = Vh_np.conj().T

    U = Matrix([[_to_python_numeric(v) for v in row] for row in U_np.tolist()])
    Sigma = Matrix([[_to_python_numeric(v) for v in row] for row in Sigma_np.tolist()])
    V = Matrix([[_to_python_numeric(v) for v in row] for row in V_np.tolist()])
    return U, Sigma, V


def _sort_with_indices(values: list[Any], descending: bool) -> tuple[list[Any], list[int]]:
    """Ordena una lista y devuelve tambien la permutacion aplicada (indices 1-based)."""
    enumerated = list(enumerate(values, start=1))
    try:
        enumerated.sort(
            key=lambda item: default_sort_key(sp.sympify(item[1])),
            reverse=descending,
        )
    except Exception as exc:  # pragma: no cover - casos patolÃ³gicos
        raise ValueError(f"could not sort the values ({exc})") from exc

    sorted_vals = [val for _, val in enumerated]
    indices = [idx for idx, _ in enumerated]
    return sorted_vals, indices


def _sort_matrix_values(matrix: MatrixBase, dim: int, descending: bool) -> tuple[Matrix, Matrix]:
    """Ordena una matriz por columnas (dim=1) o filas (dim=2) y devuelve valores+indices."""
    rows, cols = matrix.shape
    if rows == 0 or cols == 0:
        return Matrix(matrix), Matrix.zeros(rows, cols)

    if dim == 1:
        sorted_cols: list[list[Any]] = []
        idx_cols: list[list[int]] = []
        for col in range(cols):
            column_values = [matrix[row, col] for row in range(rows)]
            sorted_vals, idxs = _sort_with_indices(column_values, descending)
            sorted_cols.append(sorted_vals)
            idx_cols.append(idxs)
        sorted_matrix_rows = [
            [sorted_cols[c][r] for c in range(cols)]
            for r in range(rows)
        ]
        idx_matrix_rows = [
            [idx_cols[c][r] for c in range(cols)]
            for r in range(rows)
        ]
        return Matrix(sorted_matrix_rows), Matrix(idx_matrix_rows)

    if dim == 2:
        sorted_rows: list[list[Any]] = []
        idx_rows: list[list[int]] = []
        for row in range(rows):
            row_values = [matrix[row, col] for col in range(cols)]
            sorted_vals, idxs = _sort_with_indices(row_values, descending)
            sorted_rows.append(sorted_vals)
            idx_rows.append(idxs)
        return Matrix(sorted_rows), Matrix(idx_rows)

    raise ValueError("the sort dimension must be 1 or 2")


def _split_matrix_row(row: str) -> list[str]:
    """Separa una fila de literal de matriz en tokens sin romper parÃ©ntesis."""
    tokens: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str = False
    quote = ""
    escape = False

    n = len(row)
    i = 0

    def _last_nonspace(buffer: list[str]) -> str:
        for item in reversed(buffer):
            if not item.isspace():
                return item
        return ""

    def _starts_dot_operator(idx: int) -> bool:
        return idx + 1 < n and row[idx] == "." and row[idx + 1] in "+-*/^"

    def _can_end_expr(ch: str) -> bool:
        return ch.isalnum() or ch in "_)]}'\"."

    def _can_start_expr(ch: str, idx: int) -> bool:
        if ch.isalnum() or ch in "_\\([{\'\"":
            return True
        return ch == "." and idx + 1 < n and row[idx + 1].isdigit()

    while i < n:
        ch = row[i]
        if escape:
            buf.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            i += 1
            continue
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
                quote = ""
            i += 1
            continue
        if ch in {"'", '"'}:
            in_str = True
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(depth - 1, 0)
        if depth == 0 and ch == ",":
            token = "".join(buf).strip()
            if token:
                tokens.append(token)
            buf = []
            i += 1
            continue
        if depth == 0 and ch.isspace():
            prev_nonspace = _last_nonspace(buf)
            j = i
            while j < n and row[j].isspace():
                j += 1
            if prev_nonspace and j < n:
                next_ch = row[j]
                split_on_unary = (
                    next_ch in "+-"
                    and j + 1 < n
                    and not row[j + 1].isspace()
                    and _can_start_expr(row[j + 1], j + 1)
                )
                split_on_space = (
                    _can_end_expr(prev_nonspace)
                    and not _starts_dot_operator(j)
                    and (
                        split_on_unary
                        or (
                            next_ch not in "+-*/%^=<>:&|,"
                            and _can_start_expr(next_ch, j)
                        )
                    )
                )
                if split_on_space:
                    token = "".join(buf).strip()
                    if token:
                        tokens.append(token)
                    buf = []
                    i = j
                    continue
            if buf:
                buf.append(ch)
            i += 1
            continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        tokens.append(tail)
    return tokens


def _is_string_literal(token: str) -> bool:
    stripped = token.strip()
    if len(stripped) < 2:
        return False
    return (
        (stripped.startswith('"') and stripped.endswith('"'))
        or (stripped.startswith("'") and stripped.endswith("'"))
    )


def _rewrite_inline_semicolon_matrices(expr: str) -> str:
    def _matrix_literal_replacement(inner: str) -> str | None:
        rows = [row.strip() for row in _split_top_level(inner, ";")]
        has_row_separator = len(rows) > 1
        if not has_row_separator:
            tokens = [token.strip() for token in _split_matrix_row(inner) if token.strip()]
            top_level_commas = _split_top_level(inner, ",")
            if len(tokens) <= 1 or len(top_level_commas) > 1:
                return None
            rows = [inner.strip()]

        if not all(rows):
            return None

        matrix_rows: list[str] = []
        for row in rows:
            tokens = [token.strip() for token in _split_matrix_row(row) if token.strip()]
            if not tokens:
                return None
            matrix_rows.append("[" + ", ".join(tokens) + "]")
        return "_mt_matrix_literal([" + ", ".join(matrix_rows) + "])"

    out: list[str] = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch in {"'", '"'}:
            quote = ch
            out.append(ch)
            i += 1
            while i < len(expr):
                current = expr[i]
                out.append(current)
                if current == "\\" and i + 1 < len(expr):
                    i += 2
                    out.append(expr[i - 1])
                    continue
                if current == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch != "[":
            out.append(ch)
            i += 1
            continue

        end = _find_matching_bracket(expr, i)
        if end is None:
            out.append(ch)
            i += 1
            continue

        inner = _rewrite_inline_semicolon_matrices(expr[i + 1 : end])
        replacement = _matrix_literal_replacement(inner)
        if replacement is None:
            out.append("[" + inner + "]")
        else:
            out.append(replacement)
        i = end + 1
    return "".join(out)


def normalize_matrix_expr(expr: str, env: dict[str, Any]) -> str:
    """Convierte notaciones LaTeX de matrices en expresiones Python/SymPy."""

    def _caret_to_pow(text: str) -> str:
        """Reemplaza ^ por ** fuera de cadenas para tratarlo como potencia."""
        out = []
        in_str = False
        quote = ""
        escape = False
        last_nonspace = ""
        for ch in text:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                continue
            if in_str:
                out.append(ch)
                if ch == quote:
                    in_str = False
                    quote = ""
                continue
            if ch in {"'", '"'}:
                if ch == "'" and (last_nonspace.isalnum() or last_nonspace in {")", "]", "}", "_"}):
                    out.append(ch)
                    last_nonspace = ch
                    continue
                in_str = True
                quote = ch
                out.append(ch)
                continue
            if ch == "^":
                if last_nonspace == ".":
                    out.append("^")
                else:
                    out.append("**")
            else:
                out.append(ch)
            if not ch.isspace():
                last_nonspace = ch
        return "".join(out)
    def _adj_repl(match: re.Match[str]) -> str:
        name = match.group(1)
        value = env.get(name)
        if isinstance(value, MatrixBase):
            return f"(env_ast['{name}'].conjugate().T)"
        return match.group(0)

    def _conj_repl(match: re.Match[str]) -> str:
        name = match.group(1)
        value = env.get(name)
        if isinstance(value, MatrixBase):
            return f"(env_ast['{name}'].conjugate())"
        return match.group(0)

    expr = re.sub(
        r"\\adj\(\s*([A-Za-z_]\w*)\s*\)",
        _adj_repl,
        expr,
    )
    expr = re.sub(
        r"\\conj\(\s*([A-Za-z_]\w*)\s*\)",
        _conj_repl,
        expr,
    )
    expr = re.sub(
        r"\\T\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: f"(env_ast['{m.group(1)}'].T)" if m.group(1) in env else m.group(0),
        expr,
    )
    expr = re.sub(
        r"\\inv\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: f"(env_ast['{m.group(1)}'].inv())" if m.group(1) in env else m.group(0),
        expr,
    )
    expr = re.sub(
        r"\\Psinv\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: f"(env_ast['{m.group(1)}'].pinv())" if m.group(1) in env else m.group(0),
        expr,
    )
    expr = re.sub(
        r"\\det\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: f"(env_ast['{m.group(1)}'].det())" if m.group(1) in env else m.group(0),
        expr,
    )
    expr = re.sub(
        r"\\rg\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: f"(env_ast['{m.group(1)}'].rank())" if m.group(1) in env else m.group(0),
        expr,
    )
    expr = re.sub(
        r"\\N\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: f"(Matrix.hstack(*env_ast['{m.group(1)}'].nullspace()))"
        if m.group(1) in env
        else m.group(0),
        expr,
    )
    expr = re.sub(
        r"\\R\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: f"(Matrix.hstack(*env_ast['{m.group(1)}'].columnspace()))"
        if m.group(1) in env
        else m.group(0),
        expr,
    )
    expr = expr.replace(r"\Diag", "Matrix.diag")

    def _diag_repl(match: re.Match[str]) -> str:
        name = match.group(1)
        value = env.get(name)
        if isinstance(value, MatrixBase):
            return (
                f"(Matrix([env_ast['{name}'][i, i] for i in "
                f"range(min(env_ast['{name}'].rows, env_ast['{name}'].cols))]))"
            )
        return match.group(0)

    expr = re.sub(
        r"\\diag\(\s*([A-Za-z_]\w*)\s*\)",
        _diag_repl,
        expr,
    )

    def _sqrt_matrix_repl(match: re.Match[str]) -> str:
        name = match.group(1)
        value = env.get(name)
        if isinstance(value, MatrixBase):
            return f"(Matrix(env_ast['{name}']).applyfunc(sqrt))"
        return match.group(0)

    expr = re.sub(
        r"\\?sqrt\(\s*([A-Za-z_]\w*)\s*\)",
        _sqrt_matrix_repl,
        expr,
    )

    expr = re.sub(r"(?<![\w\"'])lambda(?!\w)", "lambda_kw", expr)

    def _rows_cols(match: re.Match[str], attr: str) -> str:
        name = match.group(1)
        value = env.get(name)
        if isinstance(value, MatrixBase):
            return f"(env_ast['{name}'].{'rows' if attr == 'rows' else 'cols'})"
        return match.group(0)

    expr = re.sub(
        r"\\rows\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: _rows_cols(m, "rows"),
        expr,
    )
    expr = re.sub(
        r"\\columns\(\s*([A-Za-z_]\w*)\s*\)",
        lambda m: _rows_cols(m, "cols"),
        expr,
    )

    def _size_repl(match: re.Match[str]) -> str:
        name = match.group(1)
        value = env.get(name)
        if isinstance(value, MatrixBase):
            return f"(env_ast['{name}'].shape)"
        return match.group(0)

    expr = re.sub(
        r"\\size\(\s*([A-Za-z_]\w*)\s*\)",
        _size_repl,
        expr,
    )

    def _fill_matrix_repl(match: re.Match[str], method: str) -> str:
        rows = match.group(1).strip()
        cols = match.group(2).strip()
        if not rows or not cols:
            return match.group(0)
        return f"(Matrix.{method}({rows}, {cols}))"

    expr = re.sub(
        r"\\zeros\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)",
        lambda m: _fill_matrix_repl(m, "zeros"),
        expr,
    )
    expr = re.sub(
        r"\\ones\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)",
        lambda m: _fill_matrix_repl(m, "ones"),
        expr,
    )

    def _rand_repl(match: re.Match[str]) -> str:
        rows = match.group(1).strip()
        cols = match.group(2).strip()
        if not rows or not cols:
            return match.group(0)
        return f"(_rand_matrix({rows}, {cols}))"

    expr = re.sub(
        r"\\rand\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)",
        _rand_repl,
        expr,
    )

    def _randi_repl(match: re.Match[str]) -> str:
        bounds = match.group(1).strip()
        rows = match.group(2).strip()
        cols = match.group(3).strip()
        if not (bounds.startswith("[") and bounds.endswith("]")):
            return match.group(0)
        inner = bounds[1:-1]
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        if len(parts) != 2:
            return match.group(0)
        low, high = parts
        if not rows or not cols:
            return match.group(0)
        return f"(_randi_matrix({low}, {high}, {rows}, {cols}))"

    expr = re.sub(
        r"\\randi\(\s*(\[[^]]+\])\s*,\s*([^,()]+)\s*,\s*([^,()]+)\s*\)",
        _randi_repl,
        expr,
    )

    def _norm_order_to_python(param_text: str) -> str:
        cleaned = param_text.strip()
        if not cleaned:
            return "2"
        if cleaned in env:
            return cleaned
        if re.fullmatch(r"[A-Za-z_]\w*", cleaned):
            return repr(cleaned)
        return normalize_matrix_expr(cleaned, env)

    def _rewrite_norm_calls(text: str) -> str:
        out: list[str] = []
        i = 0
        needle = r"\norm("
        while i < len(text):
            start = text.find(needle, i)
            if start < 0:
                out.append(text[i:])
                break
            paren_start = start + len(needle) - 1
            paren_end = _find_matching_paren(text, paren_start)
            if paren_end is None:
                out.append(text[i:])
                break
            inner = text[paren_start + 1 : paren_end]
            parts = _split_top_level_args(inner)
            if not parts or not parts[0]:
                out.append(text[i : paren_end + 1])
                i = paren_end + 1
                continue
            value_expr = normalize_matrix_expr(parts[0], env)
            order_expr = _norm_order_to_python(parts[1]) if len(parts) > 1 else "2"
            out.append(text[i:start])
            out.append(f"(_mt_norm({value_expr}, {order_expr}))")
            i = paren_end + 1
        return "".join(out)

    expr = _rewrite_norm_calls(expr)

    def _orth_repl(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if not inner:
            return match.group(0)
        return f"(_orth({inner}))"

    expr = re.sub(
        r"\\orth\(\s*([^()]*)\s*\)",
        _orth_repl,
        expr,
    )
    expr = _rewrite_inline_semicolon_matrices(expr)
    expr = re.sub(r"I_\{(\d+)\}", r"Matrix.eye(\1)", expr)
    expr = _caret_to_pow(expr)
    return expr


def full_qr_decomposition(A: Matrix):
    """Devuelve (Q_full, R_full) completando columnas/filas si hace falta."""
    Q_red, R_red = A.QRdecomposition()
    m, _ = A.shape
    if Q_red.cols < m:
        Q_aug = Q_red.row_join(Matrix.eye(m))
        Q_full = Q_aug.QRdecomposition()[0]
    else:
        Q_full = Q_red
    if R_red.rows < m:
        zeros = Matrix.zeros(m - R_red.rows, R_red.cols)
        R_full = R_red.col_join(zeros)
    else:
        R_full = R_red
    return Q_full, R_full


def _handle_matrix_expression(linea: str, ctx: ParserContext) -> bool:
    """Evalua expresiones mixtas con matrices si es posible."""
    env = ctx.env_ast
    latex_to_python = ctx.latex_to_python
    expr = normalize_matrix_expr(linea.strip(), env)

    def _conv(token: str) -> str:
        return latex_to_python(normalize_matrix_expr(token, env))

    def _index_code(expr_raw: str) -> str:
        cleaned = expr_raw.strip()
        if not cleaned or cleaned == ":":
            return "':'"
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

    def _matrix_repl_expr(match: re.Match[str]) -> str:
        name, row_expr, col_expr = match.groups()
        val = env.get(name)
        if not isinstance(val, MatrixBase):
            return match.group(0)
        row_clean = row_expr.strip()
        col_clean = col_expr.strip()
        if ":" in row_clean or ":" in col_clean:
            return f"_oct_slice('{name}', {_index_code(row_clean)}, {_index_code(col_clean)})"
        return f"_oct_get2('{name}', {_conv(row_clean)}, {_conv(col_clean)})"

    expr = re.sub(
        r"([A-Za-z_]\w*)\(\s*([^(),]+)\s*,\s*([^(),]+)\s*\)",
        _matrix_repl_expr,
        expr,
    )

    def _vector_repl_expr(match: re.Match[str]) -> str:
        name, idx_expr = match.groups()
        val = env.get(name)
        if not isinstance(val, MatrixBase):
            return match.group(0)
        idx_clean = idx_expr.strip()
        if ":" in idx_clean:
            if val.cols == 1:
                return f"_oct_slice('{name}', {_index_code(idx_clean)}, 1)"
            if val.rows == 1:
                return f"_oct_slice('{name}', 1, {_index_code(idx_clean)})"
        if val.rows == 1 or val.cols == 1:
            return f"_oct_get1('{name}', {_conv(idx_clean)})"
        return match.group(0)

    expr = re.sub(
        r"([A-Za-z_]\w*)\(\s*([^(),]+)\s*\)",
        _vector_repl_expr,
        expr,
    )

    def _format_expr_name(var_name: str) -> str:
        if var_name.startswith("_gr_"):
            base = var_name[len("_gr_"):]
            return ctx.greek_display.get(base, base)
        return var_name

    try:
        res = eval(expr, ctx.eval_context({"env_ast": ctx.env_ast}))
        if isinstance(res, MatrixBase):
            name_match = re.fullmatch(r"[A-Za-z_]\w*", linea.strip())
            if name_match and name_match.group(0) in ctx.env_ast:
                display = _format_expr_name(name_match.group(0))
                print(f"{display} = {matrix_to_str(res, ctx.greek_display)}")
            else:
                print(matrix_to_str(res, ctx.greek_display))
            return True
        if isinstance(res, (int, float, Rational)):
            print(format_value_for_display(res))
            return True
        if res is not None:
            print(format_value_for_display(res))
            return True
    except NameError:
        return False
    except SyntaxError:
        return False
    except Exception as e:
        print(f"Error in operation: {e}")
        return True
    return False


def handle_matrices(linea: str, ctx: ParserContext, allow_expression_eval: bool = True) -> bool:
    """Procesa comandos relacionados con matrices y Ã¡lgebra lineal."""
    env_ast = ctx.env_ast
    latex_to_python = ctx.latex_to_python
    greek_display = ctx.greek_display

    def _format_var(name: str) -> str:
        if name.startswith("_gr_"):
            base = name[len("_gr_"):]
            return greek_display.get(base, base)
        return name

    # Soporte para capturar salidas estilo Octave
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
        if cmd_prefix in MULTI_OUTPUT_COMMANDS:
            candidates = [v.strip() for v in vars_text.split(",") if v.strip()]
            if candidates:
                output_targets = candidates
                linea_stripped = cmd_text

    def _eval_matrix_expr(expr_text):
        expr_py = normalize_matrix_expr(expr_text, env_ast)
        expr_py = expr_py.replace(r"\N", "_mat_null")

        def _conv(token: str) -> str:
            return latex_to_python(normalize_matrix_expr(token, env_ast))

        def _index_code_local(expr_raw: str) -> str:
            cleaned = expr_raw.strip()
            if not cleaned or cleaned == ":":
                return "':'"
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

        def _matrix_repl_local(match: re.Match[str]) -> str:
            name, row_expr, col_expr = match.groups()
            val = env_ast.get(name)
            if not isinstance(val, MatrixBase):
                return match.group(0)
            row_clean = row_expr.strip()
            col_clean = col_expr.strip()
            if ":" in row_clean or ":" in col_clean:
                return f"_oct_slice('{name}', {_index_code_local(row_clean)}, {_index_code_local(col_clean)})"
            return f"_oct_get2('{name}', {_conv(row_clean)}, {_conv(col_clean)})"

        expr_py = re.sub(
            r"([A-Za-z_]\w*)\(\s*([^(),]+)\s*,\s*([^(),]+)\s*\)",
            _matrix_repl_local,
            expr_py,
        )

        def _vector_repl_local(match: re.Match[str]) -> str:
            name, idx_expr = match.groups()
            val = env_ast.get(name)
            if not isinstance(val, MatrixBase):
                return match.group(0)
            idx_clean = idx_expr.strip()
            if ":" in idx_clean:
                if val.cols == 1:
                    return f"_oct_slice('{name}', {_index_code_local(idx_clean)}, 1)"
                if val.rows == 1:
                    return f"_oct_slice('{name}', 1, {_index_code_local(idx_clean)})"
            if val.rows == 1 or val.cols == 1:
                return f"_oct_get1('{name}', {_conv(idx_clean)})"
            return match.group(0)

        expr_py = re.sub(
            r"([A-Za-z_]\w*)\(\s*([^(),]+)\s*\)",
            _vector_repl_local,
            expr_py,
        )

        try:
            res = eval(expr_py, ctx.eval_context({"env_ast": env_ast}))
        except Exception as exc:
            raise ValueError(f"could not evaluate the matrix expression ({exc})") from exc
        if not isinstance(res, MatrixBase):
            raise ValueError("the expression does not produce a matrix.")
        return res

    # AsignaciÃ³n de matrices Matlab-like con concatenaciÃ³n
    m_matrix = re.match(r"([A-Za-z_]\w*)\s*=\s*\[(.+)\]\s*(;)?$", linea_stripped)
    if m_matrix:
        name, content, silent = m_matrix.groups()
        # Si hay strings en el literal, delegamos a la ruta general de asignacion
        # para preservar listas de texto (ej: modelos = ["$x_1 + x_2 t^5$", ...]).
        rows_preview = [r.strip() for r in content.split(";")]
        if any(
            _is_string_literal(tok)
            for row in rows_preview
            if row
            for tok in _split_matrix_row(row)
        ):
            return False
        try:
            rows = [r.strip() for r in content.split(";")]
            row_mats: list[Matrix] = []
            for row in rows:
                if not row:
                    continue
                tokens = _split_matrix_row(row)
                if not tokens:
                    raise ValueError("empty row in matrix literal.")
                parts: list[Matrix] = []
                for tok in tokens:
                    expr_py = latex_to_python(normalize_matrix_expr(tok, env_ast))
                    expr_py = _replace_user_function_calls(expr_py, env_ast)
                    val = eval(expr_py, ctx.eval_context({"env_ast": env_ast}))
                    if isinstance(val, MatrixBase):
                        parts.append(Matrix(val))
                    else:
                        parts.append(Matrix([[val]]))
                base_rows = parts[0].rows
                if any(p.rows != base_rows for p in parts):
                    raise ValueError("submatrices in the same row must have the same number of rows.")
                row_mats.append(Matrix.hstack(*parts))

            if not row_mats:
                raise ValueError("empty matrix literal.")
            base_cols = row_mats[0].cols
            if any(rm.cols != base_cols for rm in row_mats):
                raise ValueError("all rows must have the same number of columns.")

            env_ast[name] = Matrix.vstack(*row_mats)
            if not silent:
                display = _format_var(name)
                print(f"{display} = {matrix_to_str(env_ast[name], greek_display)}")
        except Exception as e:
            print(f"Error defining matrix {name}: {e}")
        return True

    # Resolver sistemas lineales con operador '|', ej: x = A | b
    m_system_assign = re.match(
        r"^\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*\|\s*([A-Za-z_]\w*)\s*$",
        linea_stripped,
    )
    m_system_expr = None
    if not m_system_assign:
        m_system_expr = re.match(
            r"^\s*([A-Za-z_]\w*)\s*\|\s*([A-Za-z_]\w*)\s*$",
            linea_stripped,
        )
    if m_system_assign or m_system_expr:
        if m_system_assign is not None:
            target_name = m_system_assign.group(1)
            A_name = m_system_assign.group(2)
            b_name = m_system_assign.group(3)
        else:
            assert m_system_expr is not None
            target_name = None
            A_name = m_system_expr.group(1)
            b_name = m_system_expr.group(2)

        if A_name not in env_ast or b_name not in env_ast:
            print(f"Error: {A_name} and {b_name} must be defined first.")
            return True
        A = env_ast[A_name]
        b = env_ast[b_name]
        if not isinstance(A, MatrixBase) or not isinstance(b, MatrixBase):
            print("Error: A and b must be matrices (b may be a column vector).")
            return True
        try:
            sol, solve_mode = solve_linear_system_octave(A, b)
            if solve_mode == LINEAR_SOLVE_MINIMUM_NORM:
                print("System has infinitely many solutions: returning the minimum-norm solution.")
            elif solve_mode == LINEAR_SOLVE_LEAST_SQUARES:
                print("System has no exact solution: returning the least-squares solution.")
            if target_name:
                env_ast[target_name] = sol
                x_display = _format_var(target_name)
                print(f"{x_display} = {matrix_to_str(sol, greek_display)}")
            else:
                print(matrix_to_str(sol, greek_display))
        except Exception as e:
            print(f"Error while solving the system: {e}")
        return True

    # Matriz identidad a demanda
    m_ident = re.match(r"I_\{(\d+)\}", linea_stripped)
    if m_ident:
        n = int(m_ident.group(1))
        print(matrix_to_str(Matrix.eye(n), greek_display))
        return True

    # Determinante
    if linea_stripped.startswith(r"\det(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            if mat.rows != mat.cols:
                print(f"Error: {name} is not square.")
            else:
                print(f"det({name}) = {format_value_for_display(mat.det())}")
        except Exception as e:
            print(f"Error while computing the determinant: {e}")
        return True

    # Inversa
    if linea_stripped.startswith(r"\inv(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            invM = mat.inv()
            env_ast[f"{name}_inv"] = invM
            print(f"inv({name}) = {matrix_to_str(invM, greek_display)}")
        except Exception as e:
            print(f"Error while computing the inverse of {name}: {e}")
        return True
    
    # Pseudoinversa
    if linea_stripped.startswith(r"\Psinv(") and linea_stripped.endswith(")"):
        name = linea_stripped[7:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            pinv = mat.pinv()
            env_ast[f"{name}_psinv"] = pinv
            print(f"Psinv({name}) = {matrix_to_str(pinv, greek_display)}")
        except Exception as e:
            print(f"Error while computing the pseudoinverse of {name}: {e}")
        return True

    # Rango
    if linea_stripped.startswith(r"\rg(") and linea_stripped.endswith(")"):
        name = linea_stripped[4:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            print(f"rg({name}) = {format_value_for_display(mat.rank())}")
        except Exception as e:
            print(f"Error while computing the rank of {name}: {e}")
        return True

    # Traza
    if linea_stripped.startswith(r"\tr(") and linea_stripped.endswith(")"):
        name = linea_stripped[4:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            print(f"tr({name}) = {format_value_for_display(mat.trace())}")
        except Exception as e:
            print(f"Error while computing the trace of {name}: {e}")
        return True

    # Espacio nulo
    if linea_stripped.startswith(r"\N(") and linea_stripped.endswith(")"):
        name = linea_stripped[3:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        null_space = [normalize_column_vector(v) for v in mat.nullspace()]
        null_space_lists = [matrix_to_flat_list(v) for v in null_space]
        print(f"N({name}) = {pretty_span(null_space_lists)}")
        return True

    # Numero de filas
    if linea_stripped.startswith(r"\rows(") and linea_stripped.endswith(")"):
        name = linea_stripped[6:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        print(f"rows({name}) = {format_value_for_display(mat.rows)}")
        return True

    # Numero de columnas
    if linea_stripped.startswith(r"\columns(") and linea_stripped.endswith(")"):
        name = linea_stripped[9:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        print(f"columns({name}) = {format_value_for_display(mat.cols)}")
        return True

    if linea_stripped.startswith(r"\size(") and linea_stripped.endswith(")"):
        name = linea_stripped[6:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        rows, cols = mat.rows, mat.cols
        values = [rows, cols]
        names_used = _assign_decomposition_outputs(
            output_targets,
            ["m", "n"],
            values,
            env_ast,
            r"\size",
        )
        if names_used is not None:
            assigned_pairs = ", ".join(f"{_format_var(n)}={format_value_for_display(v)}" for n, v in zip(names_used, values))
            print(f"size({name}) -> {assigned_pairs}")
        return True

    # Espacio columna
    if linea_stripped.startswith(r"\R(") and linea_stripped.endswith(")"):
        name = linea_stripped[3:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        col_space = mat.columnspace()
        col_space_lists = [matrix_to_flat_list(v) for v in col_space]
        print(f"R({name}) = {pretty_span(col_space_lists)}")
        return True

    # Valores y vectores propios
    if linea_stripped.startswith(r"\vap(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            vals = mat.eigenvals()
            print(f"Eigenvalues of {name}: {vals}")
        except Exception as e:
            print(f"Error while computing eigenvalues of {name}: {e}")
        return True

    if linea_stripped.startswith(r"\vep(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            vecs = mat.eigenvects()
            for val, mult, vectores in vecs:
                print(f"Eigenvalor {val} (mult={mult}):")
                for v in vectores:
                    print(f"  {matrix_to_str(Matrix(v), greek_display)}")
        except Exception as e:
            print(f"Error while computing eigenvectors of {name}: {e}")
        return True

    # LU
    if linea_stripped.startswith(r"\LU(") and linea_stripped.endswith(")"):
        name = linea_stripped[4:-1].strip()
        if name in env_ast and isinstance(env_ast[name], MatrixBase):
            try:
                A_mat = env_ast[name]
                L, U, perm = A_mat.LUdecomposition()
                P = _lu_permutation_matrix(A_mat.rows, perm)
                values = [L, U, P]
                names_used = _assign_decomposition_outputs(
                    output_targets,
                    ["L", "U", "P_LU"],
                    values,
                    env_ast,
                    r"\LU",
                )
                if names_used is None:
                    return True
                print(f"{name} = L U")
                if output_targets:
                    for idx, (custom_name, value) in enumerate(zip(names_used, values)):
                        print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
                else:
                    print(f"L = {matrix_to_str(L, greek_display)}")
                    print(f"U = {matrix_to_str(U, greek_display)}")
            except Exception as e:
                print(f"Error while computing the LU decomposition of {name}: {e}")
        else:
            print(f"{name} is not a defined matrix.")
        return True

    # LDU
    if linea_stripped.startswith(r"\LDU(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        if name in env_ast and isinstance(env_ast[name], MatrixBase):
            try:
                L, D, U = env_ast[name].LUdecomposition_Simple()
                values = [L, D, U]
                names_used = _assign_decomposition_outputs(
                    output_targets,
                    ["L", "D", "U"],
                    values,
                    env_ast,
                    r"\LDU",
                )
                if names_used is None:
                    return True
                print(f"{name} = L D U")
                if output_targets:
                    for custom_name, value in zip(names_used, values):
                        print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
                else:
                    print(f"L = {matrix_to_str(L, greek_display)}")
                    print(f"D = {matrix_to_str(D, greek_display)}")
                    print(f"U = {matrix_to_str(U, greek_display)}")
            except Exception as e:
                print(f"Error while computing the LDU decomposition of {name}: {e}")
        else:
            print(f"{name} is not a defined matrix.")
        return True

    # Vector diagonal de una matriz
    if linea_stripped.startswith(r"\diag(") and linea_stripped.endswith(")"):
        name = linea_stripped[6:-1].strip()
        if not name:
            print("Error: \\diag needs one argument.")
            return True
        if name in env_ast and isinstance(env_ast[name], MatrixBase):
            mat = env_ast[name]
            diag_vec = Matrix([mat[i, i] for i in range(min(mat.rows, mat.cols))])
            env_ast[f"{name}_diag"] = diag_vec
            display_name = _format_var(name)
            print(f"diag({display_name}) = {matrix_to_str(diag_vec, greek_display)}")
        else:
            print(f"{name} is not a defined matrix.")
        return True

    # Matriz diagonal a partir de valores
    if linea_stripped.startswith(r"\Diag(") and linea_stripped.endswith(")"):
        inner = linea_stripped[6:-1].strip()
        if not inner:
            print("Error: \\Diag needs at least one argument.")
            return True
        partes = [p.strip() for p in inner.split(",") if p.strip()]
        contexto = ctx.eval_context()
        try:
            valores = [eval(latex_to_python(p), contexto) for p in partes]
            diag_matrix = Matrix.diag(*valores)
            print(matrix_to_str(diag_matrix, greek_display))
        except Exception as e:
            print(f"Error while building the diagonal matrix: {e}")
        return True

    if linea_stripped.startswith(r"\sort(") and linea_stripped.endswith(")"):
        inner = linea_stripped[6:-1].strip()
        if not inner:
            print("Error: \\sort needs at least one argument.")
            return True
        partes = [p.strip() for p in inner.split(",") if p.strip()]
        if not partes:
            print("Error: \\sort needs a target to sort.")
            return True
        matrix_name = partes[0]
        try:
            matrix = _eval_matrix_expr(matrix_name)
        except Exception as exc:
            print(f"{matrix_name} is not a defined matrix ({exc}).")
            return True
        ctx_eval = ctx.eval_context()
        dim: int | None = None
        mode = "ascend"
        for extra in partes[1:]:
            token = extra.strip()
            token_lower = token.strip("'\"").lower()
            if token_lower in {"asc", "ascend", "desc", "descend"}:
                mode = token_lower
                continue
            if dim is None:
                try:
                    dim_value = eval(latex_to_python(token), ctx_eval)
                except Exception as exc:
                    print(f"Error while parsing the \\sort dimension: {exc}")
                    return True
                try:
                    dim = int(dim_value)
                except Exception:
                    print("Error: the \\sort dimension must be an integer (1 or 2).")
                    return True
                continue
            print("Error: unrecognized \\sort arguments.")
            return True
        if dim is None:
            dim = _first_nonsingleton_dim(matrix)
        if dim not in (1, 2):
            print("Error: the \\sort dimension must be 1 or 2.")
            return True
        descending = mode in {"desc", "descend"}
        try:
            sorted_matrix, idx_matrix = _sort_matrix_values(matrix, dim, descending)
        except ValueError as exc:
            print(f"Error while sorting {matrix_name}: {exc}")
            return True
        values = [sorted_matrix, idx_matrix]
        default_names = [f"{matrix_name}_sorted", f"{matrix_name}_idx"]
        names_used = _assign_decomposition_outputs(
            output_targets,
            default_names,
            values,
            env_ast,
            r"\sort",
        )
        if names_used is None:
            return True
        display_name = _format_var(matrix_name)
        mode_label = "descendente" if descending else "ascendente"
        print(f"sort({display_name}) (dim={dim}, {mode_label})")
        for name, value in zip(names_used, values):
            print(f"{_format_var(name)} = {matrix_to_str(value, greek_display)}")
        return True

    if linea_stripped.startswith(r"\Eig(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        try:
            A = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            P_norm, D = _diagonalize_matrix(A)
            values = [P_norm, D]
            names_used = _assign_decomposition_outputs(
                output_targets,
                ["P", "D"],
                values,
                env_ast,
                r"\Eig",
            )
            if names_used is None:
                return True
            print(f"{name} es diagonalizable.")
            if output_targets:
                for custom_name, value in zip(names_used, values):
                    print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
            else:
                print(f"P = {matrix_to_str(P_norm, greek_display)}")
                print(f"D = {matrix_to_str(D, greek_display)}")
        except Exception:
            print(f"{name} is not diagonalizable (there is no complete basis of eigenvectors).")
        return True

    if linea_stripped.startswith(r"\Spec(") and linea_stripped.endswith(")"):
        name = linea_stripped[6:-1].strip()
        try:
            A = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True

        try:
            spectral_candidate = _is_hermitian_matrix(A) or _is_unitary_matrix(A) or _is_normal_matrix(A)
            P_norm, D = _diagonalize_matrix(A)
            if spectral_candidate:
                values = [P_norm, D]
                names_used = _assign_decomposition_outputs(
                    output_targets,
                    ["Q", "Lambda"],
                    values,
                    env_ast,
                    r"\Spec",
                )
                if names_used is None:
                    return True
                print(f"{name} admite descomposicion espectral.")
                if output_targets:
                    for custom_name, value in zip(names_used, values):
                        print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
                else:
                    print(f"Q = {matrix_to_str(P_norm, greek_display)}")
                    print(f"Lambda = {matrix_to_str(D, greek_display)}")
            else:
                values = [P_norm, D]
                names_used = _assign_decomposition_outputs(
                    output_targets,
                    ["P", "D"],
                    values,
                    env_ast,
                    r"\Spec",
                )
                if names_used is None:
                    return True
                print(f"{name} no es Hermitiana, unitaria ni normal; se devuelve su diagonalizacion.")
                if output_targets:
                    for custom_name, value in zip(names_used, values):
                        print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
                else:
                    print(f"P = {matrix_to_str(P_norm, greek_display)}")
                    print(f"D = {matrix_to_str(D, greek_display)}")
        except Exception:
            print(f"{name} is not diagonalizable (there is no complete basis of eigenvectors).")
        return True

    if linea_stripped.startswith(r"\Schur(") and linea_stripped.endswith(")"):
        name = linea_stripped[7:-1].strip()
        try:
            A = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True

        try:
            Q_schur, T_schur = _schur_decomposition_numeric(A)
            values = [Q_schur, T_schur]
            names_used = _assign_decomposition_outputs(
                output_targets,
                ["Q", "T"],
                values,
                env_ast,
                r"\Schur",
            )
            if names_used is None:
                return True
            print(f"{name} admite descomposicion de Schur.")
            if output_targets:
                for custom_name, value in zip(names_used, values):
                    print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
            else:
                print(f"Q = {matrix_to_str(Q_schur, greek_display)}")
                print(f"T = {matrix_to_str(T_schur, greek_display)}")
        except Exception as e:
            print(f"Error while computing the Schur decomposition of {name}: {e}")
        return True

    # QR completo
    if linea_stripped.startswith(r"\QR(") and linea_stripped.endswith(")"):
        name = linea_stripped[4:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            Q, R = full_qr_decomposition(Matrix(mat))
            values = [Q, R]
            names_used = _assign_decomposition_outputs(
                output_targets,
                ["Q", "R"],
                values,
                env_ast,
                r"\QR",
            )
            if names_used is None:
                return True
            print(f"{name} = Q R (QR completo)")
            if output_targets:
                for custom_name, value in zip(names_used, values):
                    print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
            else:
                print(f"Q = {matrix_to_str(Q, greek_display)}")
                print(f"R = {matrix_to_str(R, greek_display)}")
        except Exception as e:
            print(f"Error while computing the QR decomposition of {name}: {e}")
        return True

    # QR reducida
    if linea_stripped.startswith(r"\QR1(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        try:
            mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            Q1, R1 = mat.QRdecomposition()
            values = [Q1, R1]
            names_used = _assign_decomposition_outputs(
                output_targets,
                ["Q1", "R1"],
                values,
                env_ast,
                r"\QR1",
            )
            if names_used is None:
                return True
            print(f"{name} = Q R (QR reducida)")
            if output_targets:
                for custom_name, value in zip(names_used, values):
                    print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
            else:
                print(f"Q1 = {matrix_to_str(Q1, greek_display)}")
                print(f"R1 = {matrix_to_str(R1, greek_display)}")
        except Exception as e:
            print(f"Error while computing the reduced QR decomposition of {name}: {e}")
        return True

    # SVD
    if linea_stripped.startswith(r"\SVD(") and linea_stripped.endswith(")"):
        name = linea_stripped[5:-1].strip()
        try:
            A_mat = _eval_matrix_expr(name)
        except Exception as exc:
            print(f"{name} is not a defined matrix ({exc}).")
            return True
        try:
            rows, cols = A_mat.shape
            is_numeric = _matrix_is_numeric(A_mat)
            if is_numeric:
                U_full, Sigma, V_full = _numeric_svd_full(A_mat)
                sv_count = 0
            else:
                U, S_diag, V = A_mat.singular_value_decomposition()
                sv_count = min(S_diag.rows, S_diag.cols)

            if not is_numeric:
                singular_values: list[Expr] = []
                for diag_idx in range(sv_count):
                    try:
                        singular_values.append(cast(Expr, sp.sympify(S_diag[diag_idx, diag_idx])))
                    except Exception:
                        singular_values.append(sp.Integer(0))

                def _sv_key(idx: int) -> float:
                    val_expr = singular_values[idx]
                    try:
                        numeric_expr: Any = sp.N(val_expr, 50)
                        numeric = complex(numeric_expr)
                    except Exception:
                        try:
                            numeric_expr = val_expr.evalf()
                            numeric = complex(numeric_expr)
                        except Exception:
                            return 0.0
                    return float(abs(numeric))

                order = sorted(range(sv_count), key=_sv_key, reverse=True)
                if order != list(range(sv_count)):
                    U = U[:, order]
                    V = V[:, order]

                singular_values_sorted = [singular_values[idx] for idx in order]
                Sigma = Matrix.zeros(rows, cols)
                for diag_idx, value in enumerate(singular_values_sorted):
                    Sigma[diag_idx, diag_idx] = value

                U_full = _extend_orthonormal_matrix(U, rows)
                V_full = _extend_orthonormal_matrix(V, cols)

            values = [U_full, Sigma, V_full]
            names_used = _assign_decomposition_outputs(
                output_targets,
                ["U", "S", "V"],
                values,
                env_ast,
                r"\SVD",
            )
            if names_used is None:
                return True
            print(f"{name} = U S V^H")
            if output_targets:
                for custom_name, value in zip(names_used, values):
                    print(f"{custom_name} = {matrix_to_str(value, greek_display)}")
            else:
                print(f"U = {matrix_to_str(U_full, greek_display)}")
                print(f"S = {matrix_to_str(Sigma, greek_display)}")
                print(f"V = {matrix_to_str(V_full, greek_display)}")
        except Exception as e:
            print(f"Error while computing the SVD decomposition of {name}: {e}")
        return True

    # Traspuesta
    if linea_stripped.startswith(r"\T(") and linea_stripped.endswith(")"):
        name = linea_stripped[3:-1].strip()
        if name in env_ast and isinstance(env_ast[name], MatrixBase):
            try:
                T = env_ast[name].T
                env_ast[f"{name}_T"] = T
                print(f"T({name}) = {matrix_to_str(T, greek_display)}")
            except Exception as e:
                print(f"Error while computing the transpose of {name}: {e}")
        else:
            print(f"{name} is not a defined matrix.")
        return True

    if allow_expression_eval and _handle_matrix_expression(linea_stripped, ctx):
        return True

    return False
