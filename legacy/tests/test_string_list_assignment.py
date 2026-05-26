import unittest

from latex_lang import env_ast, ejecutar_linea, reset_environment
from mtex_executor import split_code_statements


class StringListAssignmentTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def test_string_list_assignment_keeps_strings(self):
        ejecutar_linea('modelos = ["$x_1 + x_2 t^5$", "$x_1 + x_2 t + x_3 t^2$"]')
        self.assertIn("modelos", env_ast)
        self.assertEqual(
            env_ast["modelos"],
            ["$x_1 + x_2 t^5$", "$x_1 + x_2 t + x_3 t^2$"],
        )

    def test_multiline_string_list_assignment_keeps_strings(self):
        code = """
modelos = ["$x_1 + x_2 t^5$",
  "$x_1 + x_2 t + x_3 t^2$",
  "$x_1 + x_2 t + x_3 t^3$"]
"""
        for stmt in split_code_statements(code):
            ejecutar_linea(stmt)
        self.assertEqual(
            env_ast["modelos"],
            [
                "$x_1 + x_2 t^5$",
                "$x_1 + x_2 t + x_3 t^2$",
                "$x_1 + x_2 t + x_3 t^3$",
            ],
        )


if __name__ == "__main__":
    unittest.main()
