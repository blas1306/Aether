import io
import unittest
from contextlib import redirect_stdout

from sympy import Matrix

from latex_lang import env_ast, ejecutar_linea, reset_environment


class LUCommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_lu_sets_identity_permutation_when_no_swaps(self):
        self._run("A = [2, 1; 1, 3];")
        self._run(r"\LU(A)")

        P = env_ast.get("P_LU")
        self.assertEqual(P, Matrix.eye(2))
        self.assertEqual(P * env_ast["A"], env_ast["L"] * env_ast["U"])

    def test_lu_sets_permutation_matrix_when_pivoting_is_needed(self):
        self._run("A = [0, 1; 1, 0];")
        self._run(r"\LU(A)")

        P = env_ast.get("P_LU")
        self.assertEqual(P, Matrix([[0, 1], [1, 0]]))
        self.assertEqual(P * env_ast["A"], env_ast["L"] * env_ast["U"])


if __name__ == "__main__":
    unittest.main()
