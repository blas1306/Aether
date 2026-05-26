import io
import unittest
from contextlib import redirect_stdout

from latex_lang import env_ast, ejecutar_linea, reset_environment, workspace_snapshot


class WorkspaceClearTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run_and_capture(self, line: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            ejecutar_linea(line)
        return buffer.getvalue()

    def test_overridden_builtin_symbol_is_visible_and_clearable(self):
        self._run_and_capture("x = 2")
        names = [item["name"] for item in workspace_snapshot()]
        self.assertIn("x", names)

        out = self._run_and_capture(r"\clear x")
        self.assertIn("x removed from the workspace.", out)
        self.assertNotIn("x", env_ast)

    def test_builtin_name_without_override_stays_protected(self):
        out = self._run_and_capture(r"\clear sin")
        self.assertIn("Cannot clear 'sin'.", out)


if __name__ == "__main__":
    unittest.main()
