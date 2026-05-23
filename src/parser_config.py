from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sympy import pi, symbols
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    standard_transformations,
)


@dataclass(frozen=True)
class ExprParserConfig:
    greek_cmd_to_alias: dict[str, str]
    reserved_keyword_aliases: dict[str, str]
    parser_local_dict: dict[str, Any]
    parser_transformations: tuple[Any, ...]
    protected_funcs: dict[str, str]


greek_letters_lower = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "omicron",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "chi",
    "psi",
    "omega",
]

greek_letters_upper = [
    "Gamma",
    "Delta",
    "Theta",
    "Lambda",
    "Xi",
    "Pi",
    "Sigma",
    "Upsilon",
    "Phi",
    "Psi",
    "Omega",
]

GREEK_ALIAS_PREFIX = "_gr_"
RESERVED_KEYWORD_ALIASES = {"lambda": "lambda_kw"}
PARSER_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)
PROTECTED_FUNCS = {
    "diff": "MTDIFF",
    "_mt_min": "MTMIN",
    "_mt_max": "MTMAX",
    "_mt_length": "MTLENGTH",
    "_mt_numel": "MTNUMEL",
    "_mt_nchoosek": "MTNCHOOSEK",
    "_mt_matrix_literal": "MTMATRIXLITERAL",
    "_mt_linspace": "MTLINSPACE",
    "_mt_solve": "MTSOLVE",
    "_mt_bar": "MTBAR",
    "nthroot": "MTNTHROOT",
}

GREEK_CONSTANT_OVERRIDES = {"pi": pi}


def greek_alias(name: str) -> str:
    return f"{GREEK_ALIAS_PREFIX}{name}"


greek_symbols: dict[str, Any] = {}
for _name in greek_letters_lower + greek_letters_upper:
    _sym = GREEK_CONSTANT_OVERRIDES.get(_name, symbols(_name))
    greek_symbols[f"\\{_name}"] = _sym
    greek_symbols[_name] = _sym
    greek_symbols[greek_alias(_name)] = _sym

greek_display = {
    "alpha": "\u03b1",
    "beta": "\u03b2",
    "gamma": "\u03b3",
    "delta": "\u03b4",
    "epsilon": "\u03b5",
    "zeta": "\u03b6",
    "eta": "\u03b7",
    "theta": "\u03b8",
    "iota": "\u03b9",
    "kappa": "\u03ba",
    "lambda": "\u03bb",
    "mu": "\u03bc",
    "nu": "\u03bd",
    "xi": "\u03be",
    "omicron": "\u03bf",
    "pi": "\u03c0",
    "rho": "\u03c1",
    "sigma": "\u03c3",
    "tau": "\u03c4",
    "upsilon": "\u03c5",
    "phi": "\u03c6",
    "chi": "\u03c7",
    "psi": "\u03c8",
    "omega": "\u03c9",
    "Gamma": "\u0393",
    "Delta": "\u0394",
    "Theta": "\u0398",
    "Lambda": "\u039b",
    "Xi": "\u039e",
    "Pi": "\u03a0",
    "Sigma": "\u03a3",
    "Upsilon": "\u03a5",
    "Phi": "\u03a6",
    "Psi": "\u03a8",
    "Omega": "\u03a9",
}

GREEK_CMD_TO_ALIAS = {
    f"\\{name}": greek_alias(name)
    for name in greek_letters_lower + greek_letters_upper
}


def normalize_name(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("\\"):
        base = cleaned.lstrip("\\")
        if base in greek_display:
            return greek_alias(base)
        return base
    return cleaned.lstrip("\\")


def build_expr_parser_config(parser_local_dict: dict[str, Any]) -> ExprParserConfig:
    return ExprParserConfig(
        greek_cmd_to_alias=GREEK_CMD_TO_ALIAS,
        reserved_keyword_aliases=RESERVED_KEYWORD_ALIASES,
        parser_local_dict=dict(parser_local_dict),
        parser_transformations=PARSER_TRANSFORMATIONS,
        protected_funcs=PROTECTED_FUNCS,
    )
