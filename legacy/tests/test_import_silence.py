import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from uuid import uuid4

from latex_lang import change_working_dir, env_ast, ejecutar_linea, get_working_dir, reset_environment


class ImportSilenceTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def test_from_import_does_not_print_function_defined_or_import_banner(self):
        previous_dir = get_working_dir()
        tmpdir = Path(get_working_dir()) / f"_tmp_import_{uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            mod_path = tmpdir / "modtmp.mtx"
            mod_path.write_text(
                "function y = Nr(x)\n"
                "    y = x;\n"
                "end\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(tmpdir))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea("from modtmp import Nr")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                for child in tmpdir.iterdir():
                    child.unlink()
                tmpdir.rmdir()
            except OSError:
                pass
        self.assertIn("Nr", env_ast)
        self.assertNotIn("Function Nr defined.", captured)
        self.assertNotIn("[import]", captured)
        self.assertNotIn(">> modtmp.mtx", captured)

    def test_from_import_supports_subdirectories_with_python_style_dots(self):
        previous_dir = get_working_dir()
        tmpdir = Path(get_working_dir()) / f"_tmp_import_pkg_{uuid4().hex}"
        pkg_dir = tmpdir / "funciones"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        try:
            mod_path = pkg_dir / "NR.mtx"
            mod_path.write_text(
                "function y = NewtonRaphson(x)\n"
                "    y = x;\n"
                "end\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(tmpdir))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea("from funciones.NR import NewtonRaphson")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                mod_path.unlink()
                pkg_dir.rmdir()
                tmpdir.rmdir()
            except OSError:
                pass

        self.assertIn("NewtonRaphson", env_ast)
        self.assertNotIn("Function NewtonRaphson defined.", captured)
        self.assertNotIn("[import]", captured)
        self.assertNotIn(">> NR.mtx", captured)

    def test_from_import_executes_multiline_statements_in_mtx_files(self):
        previous_dir = get_working_dir()
        tmpdir = Path(get_working_dir()) / f"_tmp_import_multiline_{uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            mod_path = tmpdir / "tablas.mtx"
            mod_path.write_text(
                'T = table(\n'
                '  [[1, 2], [3, 4]],\n'
                '  name = "TablaDemo",\n'
                '  headers = ["A", "B"],\n'
                '  caption = "Demo"\n'
                ');\n',
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(tmpdir))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea("from tablas import T")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                mod_path.unlink()
                tmpdir.rmdir()
            except OSError:
                pass

        self.assertIn("T", env_ast)
        self.assertEqual(env_ast["T"], "TablaDemo")
        self.assertIn("TablaDemo", env_ast.get("_table_blocks", {}))
        self.assertNotIn("Warning: T not defined", captured)
        self.assertNotIn(">> tablas.mtx", captured)


if __name__ == "__main__":
    unittest.main()
