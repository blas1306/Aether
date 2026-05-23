from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ParserSymbolRegistry:
    common_symbols: dict[str, Any]
    parser_local_dict: dict[str, Any]


def build_parser_local_dict(common_symbols: Mapping[str, Any]) -> dict[str, Any]:
    return dict(common_symbols)


def build_parser_symbol_registry(*symbol_layers: Mapping[str, Any]) -> ParserSymbolRegistry:
    common_symbols: dict[str, Any] = {}
    for layer in symbol_layers:
        common_symbols.update(layer)
    return ParserSymbolRegistry(
        common_symbols=common_symbols,
        parser_local_dict=build_parser_local_dict(common_symbols),
    )


def build_parser_base_symbols(
    *,
    x_symbol: Any,
    eq: Any,
    diff: Any,
    greek_symbols: Mapping[str, Any],
    math_funcs: Mapping[str, Any],
    sympy_objects: Mapping[str, Any],
    public_parser_funcs: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "x": x_symbol,
        "Eq": eq,
        "diff": diff,
        "sin": math_funcs["sin"],
        "cos": math_funcs["cos"],
        "tan": math_funcs["tan"],
        "sinh": math_funcs["sinh"],
        "cosh": math_funcs["cosh"],
        "tanh": math_funcs["tanh"],
        "asin": math_funcs["asin"],
        "acos": math_funcs["acos"],
        "atan": math_funcs["atan"],
        "exp": math_funcs["exp"],
        "Exp": math_funcs["exp"],
        "ln": math_funcs["ln"],
        "log": math_funcs["log"],
        "sqrt": math_funcs["sqrt"],
        "nthroot": math_funcs["nthroot"],
        "Abs": math_funcs["abs"],
        "abs": math_funcs["abs"],
        "norm": math_funcs["norm"],
        "sign": math_funcs["sign"],
        "floor": math_funcs["floor"],
        "ceiling": math_funcs["ceiling"],
        "solve": public_parser_funcs["solve"],
        "linspace": public_parser_funcs["linspace"],
        "orth": public_parser_funcs["orth"],
        "pi": sympy_objects["pi"],
        "E": sympy_objects["E"],
        "Pow": sympy_objects["Pow"],
        "Rational": sympy_objects["Rational"],
        "oo": sympy_objects["oo"],
        "I": sympy_objects["I"],
        "Matrix": sympy_objects["Matrix"],
        "Max": sympy_objects["Max"],
        "Add": sympy_objects["Add"],
        "Mul": sympy_objects["Mul"],
        "Function": sympy_objects["Function"],
        "Sum": sympy_objects["Sum"],
        "Product": sympy_objects["Product"],
        "true": True,
        "false": False,
        "lambda_kw": greek_symbols.get("lambda"),
    }
