import io
import unittest
from contextlib import redirect_stdout

import sympy as sp
from sympy import Matrix

from latex_lang import env_ast, ejecutar_linea, reset_environment


class SVDCommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_svd_default_returns_only_u_s_v(self):
        self._run("A = [3,2;1,0;0,0];")
        self._run(r"\SVD(A)")

        self.assertIn("U", env_ast)
        self.assertIn("S", env_ast)
        self.assertIn("V", env_ast)
        self.assertNotIn("Vh", env_ast)

        U = Matrix(env_ast["U"])
        S = Matrix(env_ast["S"])
        V = Matrix(env_ast["V"])
        A = Matrix([[3, 2], [1, 0], [0, 0]])
        rec = U * S * V.T
        err = float(sp.N((rec - A).norm()))
        self.assertLess(err, 1e-8)

    def test_svd_accepts_three_output_assignment(self):
        self._run("A = [3,2;1,0;0,0];")
        self._run(r"[U1, S1, V1] = \SVD(A)")
        self.assertIn("U1", env_ast)
        self.assertIn("S1", env_ast)
        self.assertIn("V1", env_ast)


if __name__ == "__main__":
    unittest.main()
