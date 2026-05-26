import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from latex_lang import env_ast, ejecutar_linea, reset_environment, set_plot_mode


class PlotNameArgumentTests(unittest.TestCase):
    def setUp(self):
        set_plot_mode("document")
        reset_environment()

    def tearDown(self):
        for filename in env_ast.get("plots", []):
            try:
                Path(str(filename)).unlink(missing_ok=True)
            except Exception:
                continue
        set_plot_mode("interactive")
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_plot_function_range_accepts_trailing_name_string(self):
        self._run("j(x) = x.^2 - 2;")
        out = self._run(r'\plot(j, -1, 3, "nr_plot");')
        self.assertNotIn("Error", out)
        plot_map = env_ast.get("_plot_files", {})
        self.assertIn("nr_plot", plot_map)
        self.assertTrue(Path(str(plot_map["nr_plot"])).exists())

    def test_plot_function_range_accepts_name_keyword(self):
        self._run("j(x) = x.^2 - 2;")
        out = self._run(r'\plot(j, -1, 3, name = "nr_plot_kw");')
        self.assertNotIn("Error", out)
        plot_map = env_ast.get("_plot_files", {})
        self.assertIn("nr_plot_kw", plot_map)
        self.assertTrue(Path(str(plot_map["nr_plot_kw"])).exists())

    def test_plot_legacy_multiple_functions_accepts_trailing_name_string(self):
        self._run("f(x) = x;")
        self._run("g(x) = x.^2;")
        out = self._run(r'\plot(f, g, -1, 1, "fg_plot");')
        self.assertNotIn("Error", out)
        plot_map = env_ast.get("_plot_files", {})
        self.assertIn("fg_plot", plot_map)
        self.assertTrue(Path(str(plot_map["fg_plot"])).exists())

    def test_plot_legacy_multiple_functions_accepts_name_keyword(self):
        self._run("f(x) = x;")
        self._run("g(x) = x.^2;")
        out = self._run(r'\plot(f, g, -1, 1, name = "fg_plot_kw");')
        self.assertNotIn("Error", out)
        plot_map = env_ast.get("_plot_files", {})
        self.assertIn("fg_plot_kw", plot_map)
        self.assertTrue(Path(str(plot_map["fg_plot_kw"])).exists())

    def test_plot_name_does_not_shadow_nr_command(self):
        self._run("j(x) = x.^2 - 2;")
        plot_out = self._run(r'\plot(j, -1, 3, name = "NR");')
        self.assertNotIn("Error", plot_out)

        nr_out = self._run(r"x_root = \NR(j, 1, 1e-8);")
        self.assertNotIn("Error", nr_out)
        self.assertIn("x_root", env_ast)
        self.assertAlmostEqual(float(env_ast["x_root"]), 2 ** 0.5, places=7)


if __name__ == "__main__":
    unittest.main()
