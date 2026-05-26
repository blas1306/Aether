import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from latex_lang import _PLOT_BACKEND, ejecutar_linea, reset_environment
from plot_backend import PlotBackend


class PlotBackendFiguresTests(unittest.TestCase):
    def test_state_is_isolated_between_figures(self):
        backend = PlotBackend(plot_mode="document")
        self.assertEqual(backend.get_active_figure(), 1)

        backend.set_grid("on")
        backend.title("Figura 1")

        backend.set_figure(2)
        self.assertEqual(backend.get_active_figure(), 2)
        self.assertFalse(backend.grid)
        self.assertEqual(backend.title_text, "")

        backend.set_grid("off")
        backend.title("Figura 2")

        backend.set_figure(1)
        self.assertTrue(backend.grid)
        self.assertEqual(backend.title_text, "Figura 1")

        backend.set_figure(2)
        self.assertFalse(backend.grid)
        self.assertEqual(backend.title_text, "Figura 2")

    def test_document_target_is_tracked_per_figure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = PlotBackend(plot_mode="document", output_dir=tmpdir)

            out1 = backend.plot([0, 1, 2], [0, 1, 4], output_name="f1.png")
            p1 = Path(str(out1))
            self.assertTrue(p1.exists())

            backend.set_figure(2)
            out2 = backend.plot([0, 1, 2], [0, 2, 8], output_name="f2.png")
            p2 = Path(str(out2))
            self.assertTrue(p2.exists())

            backend.set_figure(1)
            self.assertEqual(backend._last_document_target, p1)
            backend.set_figure(2)
            self.assertEqual(backend._last_document_target, p2)


class FigureCommandIntegrationTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_figure_command_switches_active_plot_state(self):
        self._run(r"\figure(1)")
        self._run(r"\grid(on)")
        self._run(r"\title('F1')")

        self._run(r"\figure(2)")
        self.assertEqual(_PLOT_BACKEND.get_active_figure(), 2)
        self.assertFalse(_PLOT_BACKEND.grid)
        self.assertEqual(_PLOT_BACKEND.title_text, "")

        self._run(r"\grid(on)")
        self._run(r"\title('F2')")

        self._run(r"\figure(1)")
        self.assertEqual(_PLOT_BACKEND.get_active_figure(), 1)
        self.assertTrue(_PLOT_BACKEND.grid)
        self.assertEqual(_PLOT_BACKEND.title_text, "F1")


if __name__ == "__main__":
    unittest.main()
