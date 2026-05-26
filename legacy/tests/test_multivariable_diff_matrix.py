import io
import unittest
from contextlib import redirect_stdout

import sympy as sp

from latex_lang import env_ast, ejecutar_linea, reset_environment


class MultivariableDiffMatrixTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_matrix_literal_allows_diff_with_non_x_function_variables(self):
        self._run("f1(x, y) = x.^2 + y.^2 - 4;")
        output = self._run(r"J1 = [\diff(f1, x), \diff(f1, y)];")

        self.assertNotIn("Error defining matrix J1", output)
        self.assertIn("J1", env_ast)
        x, y = sp.symbols("x y")
        self.assertEqual(env_ast["J1"].tolist(), [[2 * x, 2 * y]])


if __name__ == "__main__":
    unittest.main()
