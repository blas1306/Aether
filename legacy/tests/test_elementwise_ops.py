import io
import unittest
from contextlib import redirect_stdout

import sympy as sp

from latex_lang import ejecutar_linea, reset_environment, env_ast, latex_to_python, _build_parser_context


class ElementwiseOpsTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, lines):
        for line in lines:
            ejecutar_linea(line)

    def test_vector_function_elementwise(self):
        self._run(
            [
                "x = [-2, -1, 0, 1, 2];",
                "f(x) = x.^2 + 3.*x + 1;",
                "y = f(x);",
            ]
        )
        y = env_ast.get("y")
        self.assertIsNotNone(y)
        self.assertEqual(y.tolist(), [[-1, -1, 1, 5, 11]])

    def test_vector_function_expression_statement_uses_runtime_call_path(self):
        self._run(
            [
                "v = [-2, -1, 0, 1, 2];",
                "f(z) = z.^2 + 3.*z + 1;",
            ]
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea("f(v)")
        output = buf.getvalue()
        self.assertIn("f(v) =", output)
        self.assertIn("11", output)
        self.assertNotIn("Error while evaluating", output)

    def test_matrix_ops(self):
        self._run(
            [
                "A = [1 2; 3 4];",
                "B = [5 6; 7 8];",
                "C = A*B;",
                "D = A.*B;",
                "E = A^2;",
                "F = A.^2;",
                "G = A.*B + A.*B;",
            ]
        )
        self.assertEqual(env_ast["C"].tolist(), [[19, 22], [43, 50]])
        self.assertEqual(env_ast["D"].tolist(), [[5, 12], [21, 32]])
        self.assertEqual(env_ast["E"].tolist(), [[7, 10], [15, 22]])
        self.assertEqual(env_ast["F"].tolist(), [[1, 4], [9, 16]])
        self.assertEqual(env_ast["G"].tolist(), [[10, 24], [42, 64]])

    def test_matrix_literal_preserves_scalar_expressions_with_spaces(self):
        self._run(["x0 = [1; 1 + i; 1 - i];"])
        self.assertEqual(env_ast["x0"], sp.Matrix([[1], [1 + sp.I], [1 - sp.I]]))

    def test_matrix_literal_still_splits_space_separated_negative_entries(self):
        self._run(["A = [1 -2; 3 -4];"])
        self.assertEqual(env_ast["A"].tolist(), [[1, -2], [3, -4]])

    def test_power_precedence(self):
        self._run(["p = 2.^3.^2;"])
        self.assertEqual(int(env_ast["p"]), 512)

    def test_matrix_power_requires_integer(self):
        self._run(["A = [1 2; 3 4];"])
        ctx = _build_parser_context()
        expr_py = latex_to_python("A^0.5")
        with self.assertRaises(ValueError) as cm:
            eval(expr_py, ctx.eval_context({"env_ast": env_ast}))
        self.assertIn("matrix power requires integer exponent", str(cm.exception))

    def test_vector_power_error(self):
        self._run(["v = [1, 2, 3];"])
        ctx = _build_parser_context()
        expr_py = latex_to_python("v^2")
        with self.assertRaises(Exception):
            eval(expr_py, ctx.eval_context({"env_ast": env_ast}))

    def test_apostrophe_operator_is_not_supported_for_matrices(self):
        env_ast["A"] = sp.Matrix([[1 + sp.I, 2], [3 * sp.I, 4 - sp.I]])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self._run(["B = A';"])
        self.assertNotIn("B", env_ast)
        self.assertIn(r"use \T(...) for transpose", buf.getvalue())

    def test_dot_apostrophe_operator_returns_plain_transpose(self):
        env_ast["A"] = sp.Matrix([[1 + sp.I, 2], [3 * sp.I, 4 - sp.I]])
        self._run(["B = A.';"])
        self.assertEqual(env_ast["B"], env_ast["A"].T)

    def test_apostrophe_operator_on_parenthesized_matrix_expression_is_not_supported(self):
        env_ast["A"] = sp.Matrix([[1, 2], [3, 4 + sp.I]])
        env_ast["B"] = sp.Matrix([[sp.I, 0], [1, -sp.I]])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self._run(["C = (A + B)';"])
        self.assertNotIn("C", env_ast)
        self.assertIn(r"use \T(...) for transpose", buf.getvalue())

    def test_adj_command_returns_matrix_adjoint(self):
        env_ast["A"] = sp.Matrix([[1 + sp.I, 2], [3 * sp.I, 4 - sp.I]])
        self._run([r"B = \adj(A);"])
        self.assertEqual(env_ast["B"], env_ast["A"].conjugate().T)

    def test_nullspace_command_supports_nested_matrix_expression(self):
        self._run(
            [
                "A = [1,0;0,0];",
                r"B = \N(\adj(A));",
            ]
        )
        self.assertEqual(env_ast["B"], sp.Matrix([[0], [1]]))

    def test_t_command_returns_matrix_transpose(self):
        env_ast["A"] = sp.Matrix([[1 + sp.I, 2], [3 * sp.I, 4 - sp.I]])
        self._run([r"B = \T(A);"])
        self.assertEqual(env_ast["B"], env_ast["A"].T)


if __name__ == "__main__":
    unittest.main()
