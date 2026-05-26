import io
import unittest
from contextlib import redirect_stdout

import numpy as np
import sympy as sp
from sympy import Matrix

from latex_lang import env_ast, ejecutar_linea, reset_environment


class SpectralCommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_eig_performs_general_diagonalization(self):
        self._run("A = [1,1;0,2];")
        self._run(r"\Eig(A)")

        P = Matrix(env_ast["P"])
        D = Matrix(env_ast["D"])
        A = Matrix(env_ast["A"])
        self.assertEqual(sp.simplify(P * D * P.inv() - A), Matrix.zeros(2, 2))

    def test_spec_performs_spectral_decomposition_for_symmetric_matrix(self):
        self._run("A = [2,1;1,2];")
        self._run(r"\Spec(A)")

        Q = Matrix(env_ast["Q"])
        Lambda = Matrix(env_ast["Lambda"])
        A = Matrix(env_ast["A"])
        self.assertEqual(sp.simplify(Q * Lambda * Q.T - A), Matrix.zeros(2, 2))

    def test_spec_performs_spectral_decomposition_for_unitary_matrix(self):
        self._run("A = [0,-1;1,0];")
        self._run(r"\Spec(A)")

        Q = Matrix(env_ast["Q"])
        Lambda = Matrix(env_ast["Lambda"])
        A = Matrix(env_ast["A"])
        self.assertEqual(sp.simplify(Q * Lambda * Q.conjugate().T - A), Matrix.zeros(2, 2))

    def test_spec_falls_back_to_diagonalization_for_non_normal_matrix(self):
        self._run("A = [1,1;0,2];")
        out = self._run(r"\Spec(A)")

        P = Matrix(env_ast["P"])
        D = Matrix(env_ast["D"])
        A = Matrix(env_ast["A"])
        self.assertIn("se devuelve su diagonalizacion", out)
        self.assertEqual(sp.simplify(P * D * P.inv() - A), Matrix.zeros(2, 2))
        self.assertNotIn("Q", env_ast)
        self.assertNotIn("Lambda", env_ast)

    def test_py_command_is_removed(self):
        out = self._run(r"\py print(1)")
        self.assertIn(r"Commands \py and \endpy are no longer supported.", out)

    def test_endpy_command_is_removed(self):
        out = self._run(r"\endpy")
        self.assertIn(r"Commands \py and \endpy are no longer supported.", out)

    def test_schur_returns_unitary_and_upper_triangular_factors(self):
        self._run("A = [1,2;3,4];")
        self._run(r"\Schur(A)")

        Q = np.array(Matrix(env_ast["Q"]).tolist(), dtype=np.complex128)
        T = np.array(Matrix(env_ast["T"]).tolist(), dtype=np.complex128)
        A = np.array(Matrix(env_ast["A"]).tolist(), dtype=np.complex128)

        self.assertTrue(np.allclose(Q.conjugate().T @ Q, np.eye(2), atol=1e-8))
        self.assertTrue(np.allclose(np.tril(T, -1), 0, atol=1e-8))
        self.assertTrue(np.allclose(Q @ T @ Q.conjugate().T, A, atol=1e-8))


if __name__ == "__main__":
    unittest.main()
