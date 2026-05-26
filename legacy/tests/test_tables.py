import unittest

from latex_lang import env_ast, ejecutar_linea, reset_environment, table as make_table
from mtex_executor import reemplazar_tablas


class TableRuntimeTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def test_table_registration_and_placeholder_replacement(self):
        ejecutar_linea("A = [[1,2],[3,4]];")
        ejecutar_linea('T = table(A, name="miTabla", headers=["a","b"], caption="Ejemplo", label="tab:ej");')

        self.assertEqual(env_ast.get("T"), "miTabla")
        self.assertEqual(env_ast.get("last_table"), "miTabla")
        self.assertIn("miTabla", env_ast.get("_table_blocks", {}))

        block = env_ast["_table_blocks"]["miTabla"]
        self.assertIn(r"\begin{table}[h]", block)
        self.assertIn(r"\caption{Ejemplo}", block)
        self.assertIn(r"\label{tab:ej}", block)
        self.assertIn(r"\begin{tabular}{|c|c|}", block)
        self.assertIn(r"\hline", block)
        self.assertNotIn(r"\toprule", block)

        rendered, missing = reemplazar_tablas("Aca va:\n\\table{miTabla}\n", env_ast)
        self.assertFalse(missing)
        self.assertIn(r"\begin{table}[h]", rendered)
        self.assertNotIn(r"\table{miTabla}", rendered)

    def test_table_missing_placeholder_warning_block(self):
        rendered, missing = reemplazar_tablas("X \\table{noExiste} Y", env_ast)
        self.assertTrue(missing)
        self.assertIn(r"\textcolor{red}{[Table noExiste not found]}", rendered)

    def test_alignment_repeat_and_hline_mode(self):
        table_id = make_table([[1, 2, 3]], name="tAlign", align="r")
        self.assertEqual(table_id, "tAlign")
        block = env_ast["_table_blocks"]["tAlign"]
        self.assertIn(r"\begin{tabular}{|r|r|r|}", block)
        self.assertIn(r"\hline", block)
        self.assertNotIn(r"\toprule", block)

    def test_headers_length_validation(self):
        with self.assertRaises(ValueError):
            make_table([[1, 2]], headers=["a"])

    def test_ragged_rows_validation(self):
        with self.assertRaises(ValueError):
            make_table([[1, 2], [3]])

    def test_escape_strings(self):
        make_table([["a&b", "x_y", r"a\b"]], name="tEsc", booktabs=False, escape_strings=True)
        block = env_ast["_table_blocks"]["tEsc"]
        self.assertIn(r"a\&b", block)
        self.assertIn(r"x\_y", block)
        self.assertIn(r"a\textbackslash{}b", block)

    def test_empty_data_with_headers(self):
        make_table([], name="emptyT", headers=["h1", "h2"])
        block = env_ast["_table_blocks"]["emptyT"]
        self.assertIn(r"\begin{tabular}{|c|c|}", block)
        self.assertIn(r"h1 & h2 \\", block)

    def test_booktabs_can_be_enabled_explicitly(self):
        make_table([[1, 2]], name="tBook", headers=["a", "b"], booktabs=True)
        block = env_ast["_table_blocks"]["tBook"]
        self.assertIn(r"\toprule", block)
        self.assertIn(r"\midrule", block)
        self.assertIn(r"\bottomrule", block)


if __name__ == "__main__":
    unittest.main()
