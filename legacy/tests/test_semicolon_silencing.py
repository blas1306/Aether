import io
import unittest
from contextlib import redirect_stdout

from latex_lang import ejecutar_linea, reset_environment


class SemicolonSilencingTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _capture_stdout(self, line: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            ejecutar_linea(line)
        return buffer.getvalue()

    def test_assignment_with_name_containing_error_is_silenced(self):
        out = self._capture_stdout("errores = [];")
        self.assertEqual(out, "")

    def test_real_error_is_not_silenced(self):
        out = self._capture_stdout("x = y + 1;")
        self.assertIn("Error", out)

    def test_semicolon_is_preserved_inside_if_block(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            ejecutar_linea("A = [1,2;3,4];")
            ejecutar_linea("r = 1;")
            ejecutar_linea("if r < 2")
            ejecutar_linea("    U_r = A(:, 1:r);")
            ejecutar_linea("end")
        self.assertEqual(buffer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
