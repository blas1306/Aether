import tempfile
import unittest
from pathlib import Path

from mtex_executor import reemplazar_plots


class PlotPlaceholderReplacementTests(unittest.TestCase):
    def test_plot_placeholder_uses_default_width_when_no_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plot_last_plot.png"
            target.write_bytes(b"png")
            ctx = {"_plot_files": {"last_plot": target.as_posix()}}

            rendered = reemplazar_plots(r"\plot{last_plot}", ctx)

            self.assertIn(r"\includegraphics[width=0.6\linewidth]{", rendered)
            self.assertIn(target.as_posix(), rendered)

    def test_plot_placeholder_accepts_custom_includegraphics_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plot_last_plot.png"
            target.write_bytes(b"png")
            ctx = {"_plot_files": {"last_plot": target.as_posix()}}

            rendered = reemplazar_plots(r"\plot[width=0.95\linewidth,height=7cm]{last_plot}", ctx)

            self.assertIn(r"\includegraphics[width=0.95\linewidth,height=7cm]{", rendered)
            self.assertIn(target.as_posix(), rendered)

    def test_plot_placeholder_empty_options_fall_back_to_default_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plot_last_plot.png"
            target.write_bytes(b"png")
            ctx = {"_plot_files": {"last_plot": target.as_posix()}}

            rendered = reemplazar_plots(r"\plot[   ]{last_plot}", ctx)

            self.assertIn(r"\includegraphics[width=0.6\linewidth]{", rendered)
            self.assertIn(target.as_posix(), rendered)

    def test_plot_placeholder_resolves_relative_plot_names_in_document_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mincuad_plot.png"
            target.write_bytes(b"png")
            ctx = {
                "_plot_files": {"mincuad_plot": "mincuad_plot.png"},
                "_document_output_dir": tmp,
            }

            rendered = reemplazar_plots(r"\plot{mincuad_plot}", ctx)

            self.assertIn(r"\includegraphics[width=0.6\linewidth]{mincuad_plot.png}", rendered)


if __name__ == "__main__":
    unittest.main()
