import tempfile
import unittest
from pathlib import Path

import matplotlib
import sympy as sp

matplotlib.use("Agg")

from latex_lang import _PLOT_BACKEND, plot, reset_environment, set_document_output_dir, set_plot_mode
from plot_backend import PlotBackend


class PlotBackendDocumentModeTests(unittest.TestCase):
    def test_updates_after_plot_rewrite_same_png(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = PlotBackend(plot_mode="document", output_dir=tmpdir)
            output = backend.plot([0, 1, 2], [0, 1, 4], output_name="demo.png")
            self.assertIsInstance(output, str)

            target = Path(output)  # type: ignore[arg-type]
            self.assertTrue(target.exists())
            before = target.read_bytes()

            backend.title("Parabola")
            backend.xlabel("x")
            backend.ylabel("y")
            backend.set_grid("on")
            backend.legend("serie")

            self.assertEqual(backend._last_document_target, target)
            after = target.read_bytes()
            self.assertNotEqual(before, after)


class LatexPlotDefaultTitleTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def tearDown(self):
        set_plot_mode("interactive")
        set_document_output_dir(".")

    def test_expression_plot_has_no_automatic_title_without_title_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_plot_mode("document")
            set_document_output_dir(tmpdir)

            x = sp.Symbol("x")
            plot(x**2, -1, 1)

            self.assertIsNotNone(_PLOT_BACKEND.current_axes)
            self.assertEqual(_PLOT_BACKEND.current_axes.get_title(), "")

    def test_named_function_plot_has_no_automatic_title_without_title_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_plot_mode("document")
            set_document_output_dir(tmpdir)

            x = sp.Symbol("x")
            from latex_lang import env_ast

            env_ast["f"] = x**2
            env_ast["f_vars"] = [x]
            plot("f")

            self.assertIsNotNone(_PLOT_BACKEND.current_axes)
            self.assertEqual(_PLOT_BACKEND.current_axes.get_title(), "")


if __name__ == "__main__":
    unittest.main()
