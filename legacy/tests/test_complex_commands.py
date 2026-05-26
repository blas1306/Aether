import io
import unittest
from contextlib import redirect_stdout

import sympy as sp

from latex_lang import env_ast, ejecutar_linea, reset_environment


class ComplexCommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_polar_assigns_default_r_and_theta(self):
        output = self._run(r"\polar(-1 + sqrt(3)*i)")

        self.assertIn("r=", output)
        self.assertIn("theta=", output)
        self.assertIn("r", env_ast)
        self.assertIn("theta", env_ast)
        self.assertEqual(sp.simplify(env_ast["r"] - 2), 0)
        self.assertEqual(sp.simplify(env_ast["theta"] - 2 * sp.pi / 3), 0)

    def test_polar_accepts_custom_output_names(self):
        self._run(r"[r2, theta2] = \polar(-1 - i)")

        self.assertIn("r2", env_ast)
        self.assertIn("theta2", env_ast)
        self.assertEqual(sp.simplify(env_ast["r2"] - sp.sqrt(2)), 0)
        self.assertEqual(sp.simplify(env_ast["theta2"] + sp.pi / 4 * 3), 0)

    def test_angle_works_inside_assignments(self):
        self._run(r"ang = \angle(-1 - i)")

        self.assertIn("ang", env_ast)
        self.assertAlmostEqual(float(env_ast["ang"]), float(-3 * sp.pi / 4), places=12)


if __name__ == "__main__":
    unittest.main()
