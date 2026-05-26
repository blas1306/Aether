import sympy as sp

from mtex_executor import reemplazar_exprs


def test_expr_placeholder_supports_symbolic_function_value_plus_vector_index():
    x = sp.Symbol("x")
    ctx = {
        "f1": x**2,
        "f1_vars": (x,),
        "f1_expr_py": "x**2",
        "b": sp.Matrix([5, 6]),
    }

    rendered = reemplazar_exprs(r"\expr{f1 + b(1)}", ctx)

    assert rendered == r"x^{2} + 5"


def test_expr_placeholder_supports_function_calls_and_vector_indices():
    x = sp.Symbol("x")
    ctx = {
        "f1": x**2,
        "f1_vars": (x,),
        "f1_expr_py": "x**2",
        "b": sp.Matrix([5, 6]),
    }

    rendered = reemplazar_exprs(r"\expr{f1(2) + b(1)}", ctx)

    assert rendered == "9"
