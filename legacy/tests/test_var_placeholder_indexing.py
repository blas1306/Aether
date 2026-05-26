import unittest

import sympy as sp

from mtex_executor import reemplazar_vars


class VarPlaceholderIndexingTests(unittest.TestCase):
    def test_var_placeholder_supports_plain_variable_lookup(self):
        ctx = {"x": sp.Integer(7)}
        rendered = reemplazar_vars(r"\var{x}", ctx)
        self.assertEqual("7", rendered)

    def test_var_placeholder_supports_one_based_list_indexing_with_parentheses(self):
        ctx = {"sol_h": [2, 3]}
        rendered = reemplazar_vars(r"x_1=\var{sol_h(1)}, x_2=\var{sol_h(2)}", ctx)
        self.assertIn("x_1=2", rendered)
        self.assertIn("x_2=3", rendered)

    def test_var_placeholder_supports_one_based_list_indexing_with_brackets_for_compatibility(self):
        ctx = {"sol_h": [2, 3]}
        rendered = reemplazar_vars(r"x_1=\var{sol_h[1]}, x_2=\var{sol_h[2]}", ctx)
        self.assertIn("x_1=2", rendered)
        self.assertIn("x_2=3", rendered)

    def test_var_placeholder_supports_two_dimensional_matrix_indexing_with_parentheses(self):
        ctx = {"A": sp.Matrix([[1, 2], [3, 4]])}
        rendered = reemplazar_vars(r"\var{A(1,2)}", ctx)
        self.assertEqual("2", rendered)

    def test_var_placeholder_supports_two_dimensional_matrix_indexing_with_brackets_for_compatibility(self):
        ctx = {"A": sp.Matrix([[1, 2], [3, 4]])}
        rendered = reemplazar_vars(r"\var{A[2,1]}", ctx)
        self.assertEqual("3", rendered)

    def test_var_placeholder_reports_out_of_range_parentheses_index_cleanly(self):
        ctx = {"A": sp.Matrix([[1, 2], [3, 4]])}
        rendered = reemplazar_vars(r"\var{A(10,10)}", ctx)
        self.assertIn(
            r"\textcolor{red}{Error var A(10,10): indices (10, 10) fuera de rango para A (2x2)}",
            rendered,
        )

    def test_var_placeholder_missing_variable_is_rendered_safely(self):
        rendered = reemplazar_vars(r"\var{sol_h}", {})
        self.assertEqual(r"\textcolor{gray}{?sol\_h?}", rendered)

    def test_var_placeholder_reports_scalar_index_mismatch_cleanly(self):
        ctx = {"x_value": 7}
        rendered = reemplazar_vars(r"\var{x_value[1]}", ctx)
        self.assertIn(r"\textcolor{red}{Error var x\_value[1]: x\_value es escalar y no admite indices}", rendered)

    def test_var_placeholder_reports_matrix_scalar_index_mismatch_cleanly(self):
        ctx = {"A": sp.Matrix([[1, 2], [3, 4]])}
        rendered = reemplazar_vars(r"\var{A[1]}", ctx)
        self.assertIn(r"\textcolor{red}{Error var A[1]: A es una matriz; usa dos indices}", rendered)


if __name__ == "__main__":
    unittest.main()
