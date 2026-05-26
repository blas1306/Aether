import io
import unittest
from contextlib import redirect_stdout

from latex_lang import env_ast, ejecutar_linea, reset_environment


class NRCommandTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_nr_command_updates_last_root(self):
        self._run("j(x) = x.^2 - 2;")
        self._run(r"\NR(j, 1, 1e-8);")
        root = env_ast.get("nr_last_root")
        self.assertIsNotNone(root)
        self.assertAlmostEqual(float(root), 2 ** 0.5, places=7)

    def test_nr_assignment_stores_root_in_target_variable(self):
        self._run("j(x) = x.^2 - 2;")
        self._run(r"x = \NR(j, 1, 1e-8);")
        self.assertIn("x", env_ast)
        self.assertAlmostEqual(float(env_ast["x"]), 2 ** 0.5, places=7)
        self.assertAlmostEqual(float(env_ast["x"]), float(env_ast["nr_last_root"]), places=12)

    def test_nr_assignment_accepts_seed_and_tolerance_from_variables(self):
        self._run("j(x) = x.^2 - 2;")
        self._run("x0 = 1;")
        self._run("tol = 1e-8;")
        out = self._run(r"root = \NR(j, x0, tol);")
        self.assertNotIn("Did not converge", out)
        self.assertIn("root", env_ast)
        self.assertAlmostEqual(float(env_ast["root"]), 2 ** 0.5, places=7)


if __name__ == "__main__":
    unittest.main()
