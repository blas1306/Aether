import io
import math
import unittest
from contextlib import redirect_stdout

from latex_lang import env_ast, ejecutar_linea, reset_environment


class ODECommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_ode_stores_dense_numeric_solution(self):
        output = self._run(r"\ode(y'(x)=y(x), y(0)=1, x=0..1, n=20)")
        self.assertIn("Sol numerica", output)
        self.assertIn("y_num", env_ast)

        y_num = env_ast["y_num"]
        self.assertAlmostEqual(float(y_num(0.0)), 1.0, places=8)
        self.assertAlmostEqual(float(y_num(0.5)), math.exp(0.5), places=5)
        self.assertAlmostEqual(float(y_num(1.0)), math.e, places=5)


if __name__ == "__main__":
    unittest.main()
