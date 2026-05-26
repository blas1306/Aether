import io
import unittest
from contextlib import redirect_stdout

from sympy import Matrix

from latex_lang import env_ast, ejecutar_linea, reset_environment


class MinMaxCommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_vector_min_and_max(self):
        self._run("v = [3; 1; 2];")
        self.assertEqual(self._run(r"\min(v)").strip(), "1")
        self.assertEqual(self._run(r"\max(v)").strip(), "3")

    def test_matrix_min_and_max_return_columnwise_row_vector(self):
        self._run("A = [1, 4; 3, 2];")
        self.assertEqual(self._run(r"\min(A)").strip(), "Matrix([[1, 2]])")
        self.assertEqual(self._run(r"\max(A)").strip(), "Matrix([[3, 4]])")

    def test_min_max_work_in_assignments(self):
        self._run("A = [1, 4; 3, 2];")
        self._run(r"m = \min(A);")
        self._run(r"M = \max(A);")
        self.assertEqual(env_ast.get("m"), Matrix([[1, 2]]))
        self.assertEqual(env_ast.get("M"), Matrix([[3, 4]]))


if __name__ == "__main__":
    unittest.main()
