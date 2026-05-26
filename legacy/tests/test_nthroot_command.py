import unittest

import sympy as sp
from sympy import Matrix

from latex_lang import env_ast, ejecutar_linea, reset_environment


class NthRootCommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, lines):
        for line in lines:
            ejecutar_linea(line)

    def test_nthroot_inline_expression(self):
        self._run([
            "a = 28;",
            r"x = \nthroot(a - 1, 3);",
        ])
        self.assertEqual(sp.simplify(env_ast.get("x") - 3), 0)

    def test_nthroot_variable_expression(self):
        self._run([
            "a = 28;",
            "r = a - 1;",
            r"y = \nthroot(r, 3);",
        ])
        self.assertEqual(sp.simplify(env_ast.get("y") - 3), 0)

    def test_nthroot_matrix_elementwise(self):
        self._run([
            "A = [1 8; 27 64];",
            r"B = \nthroot(A, 3);",
        ])
        B = env_ast.get("B")
        self.assertIsInstance(B, Matrix)
        self.assertEqual(B.tolist(), [[1, 2], [3, 4]])


if __name__ == "__main__":
    unittest.main()
