from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import sympy as sp
from sympy.matrices import MatrixBase


@dataclass(frozen=True)
class NumericFormatSpec:
    name: str
    decimals: int
    notation: str
    preserve_integer: bool = False


_FORMAT_SPECS: dict[str, NumericFormatSpec] = {
    "short": NumericFormatSpec("short", decimals=4, notation="fixed", preserve_integer=True),
    "long": NumericFormatSpec("long", decimals=15, notation="fixed", preserve_integer=True),
    "shorte": NumericFormatSpec("shorte", decimals=4, notation="scientific", preserve_integer=False),
    "longe": NumericFormatSpec("longe", decimals=15, notation="scientific", preserve_integer=False),
    "bank": NumericFormatSpec("bank", decimals=2, notation="fixed", preserve_integer=False),
}
_DEFAULT_NUMERIC_FORMAT = "short"
_active_numeric_format = _DEFAULT_NUMERIC_FORMAT


def supported_numeric_formats() -> tuple[str, ...]:
    return tuple(_FORMAT_SPECS.keys())


def get_numeric_format() -> str:
    return _active_numeric_format


def set_numeric_format(name: str) -> str:
    global _active_numeric_format

    cleaned = str(name).strip().lower()
    if cleaned not in _FORMAT_SPECS:
        valid = ", ".join(supported_numeric_formats())
        raise ValueError(f"Unknown numeric format '{name}'. Expected one of: {valid}.")
    _active_numeric_format = cleaned
    return cleaned


def reset_numeric_format() -> None:
    global _active_numeric_format
    _active_numeric_format = _DEFAULT_NUMERIC_FORMAT


def _spec_for(mode: str | None = None) -> NumericFormatSpec:
    key = get_numeric_format() if mode is None else str(mode).strip().lower()
    return _FORMAT_SPECS[key]


def _numeric_expr(value: Any) -> sp.Basic | None:
    if isinstance(value, (str, bytes, bool, MatrixBase)):
        return None
    if isinstance(value, np.generic):
        try:
            return _numeric_expr(value.item())
        except Exception:
            return None
    if isinstance(value, (int, float, complex)):
        try:
            return sp.sympify(value)
        except Exception:
            return None
    if isinstance(value, sp.Basic):
        free_symbols = getattr(value, "free_symbols", None)
        if free_symbols:
            return None
        if getattr(value, "is_number", False):
            return value
    return None


def value_is_fully_numeric(value: Any) -> bool:
    return _numeric_expr(value) is not None


def _to_complex(expr: sp.Basic) -> complex | None:
    try:
        numeric = complex(sp.N(expr, 50))
    except Exception:
        return None
    if not math.isfinite(numeric.real) or not math.isfinite(numeric.imag):
        return None
    return numeric


def _is_effectively_zero(value: float, tol: float = 1e-12) -> bool:
    return abs(value) <= tol


def _normalize_zero(value: float, tol: float = 1e-12) -> float:
    return 0.0 if _is_effectively_zero(value, tol=tol) else value


def _format_real_component(value: float, spec: NumericFormatSpec, *, preserve_integer: bool | None = None) -> str:
    real = _normalize_zero(float(value))
    keep_integer = spec.preserve_integer if preserve_integer is None else preserve_integer

    if keep_integer and float(real).is_integer():
        return str(int(round(real)))

    if spec.notation == "scientific":
        return f"{real:.{spec.decimals}e}"

    return f"{real:.{spec.decimals}f}"


def try_format_numeric_scalar(value: Any, *, mode: str | None = None) -> str | None:
    expr = _numeric_expr(value)
    if expr is None:
        return None

    spec = _spec_for(mode)
    numeric = _to_complex(expr)
    if numeric is None:
        return None

    real = _normalize_zero(numeric.real)
    imag = _normalize_zero(numeric.imag)

    if _is_effectively_zero(imag):
        return _format_real_component(real, spec)

    imag_abs = abs(imag)
    imag_text = _format_real_component(imag_abs, spec, preserve_integer=spec.preserve_integer)
    if _is_effectively_zero(real):
        prefix = "-" if imag < 0 else ""
        return f"{prefix}{imag_text}i"

    real_text = _format_real_component(real, spec, preserve_integer=spec.preserve_integer)
    sign = "+" if imag >= 0 else "-"
    return f"{real_text}{sign}{imag_text}i"


def format_value_for_display(value: Any, *, mode: str | None = None) -> str:
    formatted = try_format_numeric_scalar(value, mode=mode)
    if formatted is not None:
        return formatted
    return str(value)


def _matrix_entry_to_latex(value: Any) -> str:
    formatted = try_format_numeric_scalar(value)
    if formatted is not None:
        return formatted
    if isinstance(value, sp.Basic):
        return sp.latex(value)
    return str(value)


def matrix_to_latex(value: Any) -> str:
    try:
        if isinstance(value, MatrixBase):
            mat = sp.Matrix(value)
        elif isinstance(value, (list, np.ndarray)):
            mat = sp.Matrix(value)
        else:
            return format_value_for_display(value)
    except Exception:
        return format_value_for_display(value)

    rows: list[str] = []
    for r in range(mat.rows):
        cells = [_matrix_entry_to_latex(mat[r, c]) for c in range(mat.cols)]
        rows.append(" & ".join(cells))
    body = r"\\ ".join(rows)
    return rf"\left[\begin{{matrix}}{body}\end{{matrix}}\right]"
