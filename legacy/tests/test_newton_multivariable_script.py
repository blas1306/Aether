import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import sympy as sp

from latex_lang import change_working_dir, env_ast, ejecutar_linea, get_working_dir, reset_environment


class NewtonMultivariableScriptTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def test_run_script_supports_vector_function_eval_and_linear_solve_expr(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_newton_multivariable_test.mtx").resolve()
        try:
            script_path.write_text(
                "f1(x, y) = x.^2 + y.^2 - 4;\n"
                "f2(x, y) = x + y - 2;\n"
                "\n"
                "x0 = [1; 1];\n"
                "\n"
                "Fx0 = [f1(x0); f2(x0)];\n"
                "\n"
                "J1 = [\\diff(f1, x), \\diff(f1, y)];\n"
                "J2 = [\\diff(f2, x), \\diff(f2, y)];\n"
                "\n"
                "J = [J1; J2];\n"
                "\n"
                "z = J | -Fx0;\n"
                "\n"
                "x = z + x0\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        x_sym, y_sym = sp.symbols("x y")
        self.assertNotIn("Error", captured)
        self.assertEqual(env_ast["Fx0"].tolist(), [[-2], [0]])
        self.assertEqual(env_ast["J"].tolist(), [[2 * x_sym, 2 * y_sym], [1, 1]])

        expected_z = sp.Matrix([[1 / (x_sym - y_sym)], [-1 / (x_sym - y_sym)]])
        self.assertEqual((env_ast["z"] - expected_z).applyfunc(sp.simplify), sp.zeros(2, 1))

        expected_x = sp.Matrix([[1 + 1 / (x_sym - y_sym)], [1 - 1 / (x_sym - y_sym)]])
        self.assertEqual((env_ast["x"] - expected_x).applyfunc(sp.simplify), sp.zeros(2, 1))

    def test_run_script_supports_matrix_apply_with_vector_arg(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_newton_multivariable_apply_test.mtx").resolve()
        try:
            script_path.write_text(
                "f1(x, y) = x.^2 + y.^2 - 4;\n"
                "f2(x, y) = x + y - 2;\n"
                "\n"
                "F = [f1; f2];\n"
                "\n"
                "J1 = [\\diff(f1, x), \\diff(f1, y)];\n"
                "J2 = [\\diff(f2, x), \\diff(f2, y)];\n"
                "\n"
                "J = [J1; J2];\n"
                "\n"
                "x0 = [1; 1];\n"
                "Fx0 = F(x0);\n"
                "Jx0 = J(x0)\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertEqual(env_ast["Fx0"], sp.Matrix([[-2], [0]]))
        self.assertEqual(env_ast["Jx0"], sp.Matrix([[2, 2], [1, 1]]))

    def test_run_script_supports_one_newton_step_with_evaluated_matrix_and_jacobian(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_newton_multivariable_numeric_step_test.mtx").resolve()
        try:
            script_path.write_text(
                "f1(x, y) = x.^2 + y.^2 - 4;\n"
                "f2(x, y) = x + y - 2;\n"
                "\n"
                "F = [f1; f2];\n"
                "\n"
                "J1 = [\\diff(f1, x), \\diff(f1, y)];\n"
                "J2 = [\\diff(f2, x), \\diff(f2, y)];\n"
                "\n"
                "J = [J1; J2];\n"
                "\n"
                "x0 = [1.5; 0.5];\n"
                "Fx0 = F(x0);\n"
                "Jx0 = J(x0);\n"
                "z = Jx0 | (-Fx0);\n"
                "x = z + x0\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertEqual(env_ast["Fx0"], sp.Matrix([[-1.5], [0]]))
        self.assertEqual(env_ast["Jx0"], sp.Matrix([[3.0, 1.0], [1, 1]]))
        expected_z = sp.Matrix([[0.75], [-0.75]])
        expected_x = sp.Matrix([[2.25], [-0.25]])
        for got, expected in zip(env_ast["z"], expected_z):
            self.assertLess(abs(float(sp.N(got - expected))), 1e-12)
        for got, expected in zip(env_ast["x"], expected_x):
            self.assertLess(abs(float(sp.N(got - expected))), 1e-12)

    def test_run_script_supports_norm_of_evaluated_vector_expression(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_newton_multivariable_norm_test.mtx").resolve()
        try:
            script_path.write_text(
                "f1(x, y) = x.^2 + y.^2 - 4;\n"
                "f2(x, y) = x + y - 2;\n"
                "\n"
                "F = [f1; f2];\n"
                "\n"
                "x = [2.25; -0.25];\n"
                "res = \\norm(F(x));\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertEqual(sp.simplify(env_ast["res"] - sp.Rational(9, 8)), 0)

    def test_run_script_supports_top_level_while_block(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_newton_multivariable_while_test.mtx").resolve()
        try:
            script_path.write_text(
                "f1(x, y) = x.^2 + y.^2 - 4;\n"
                "f2(x, y) = x + y - 2;\n"
                "\n"
                "F = [f1; f2];\n"
                "J1 = [\\diff(f1, x), \\diff(f1, y)];\n"
                "J2 = [\\diff(f2, x), \\diff(f2, y)];\n"
                "J = [J1; J2];\n"
                "\n"
                "x = [1; 0];\n"
                "tol = 1e-8;\n"
                "maxiter = 20;\n"
                "iter = 0;\n"
                "res = \\norm(F(x));\n"
                "\n"
                "while res > tol && iter < maxiter\n"
                "    z = J(x) | (-F(x));\n"
                "    x = z + x;\n"
                "    res = \\norm(F(x));\n"
                "    iter = iter + 1;\n"
                "end\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertLess(float(sp.N(env_ast["res"])), 1e-8)
        self.assertGreater(int(env_ast["iter"]), 0)
        self.assertLessEqual(int(env_ast["iter"]), int(env_ast["maxiter"]))

    def test_run_script_supports_keyword_and_in_while_condition(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_newton_multivariable_while_and_keyword_test.mtx").resolve()
        try:
            script_path.write_text(
                "f1(x, y) = x.^2 + y.^2 - 4;\n"
                "f2(x, y) = x + y - 2;\n"
                "\n"
                "F = [f1; f2];\n"
                "J1 = [\\diff(f1, x), \\diff(f1, y)];\n"
                "J2 = [\\diff(f2, x), \\diff(f2, y)];\n"
                "J = [J1; J2];\n"
                "\n"
                "x = [1; 0];\n"
                "tol = 1e-8;\n"
                "maxiter = 20;\n"
                "iter = 0;\n"
                "res = \\norm(F(x));\n"
                "\n"
                "while res > tol and iter < maxiter\n"
                "    z = J(x) | (-F(x));\n"
                "    x = z + x;\n"
                "    res = \\norm(F(x));\n"
                "    iter = iter + 1;\n"
                "end\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertLess(float(sp.N(env_ast["res"])), 1e-8)
        self.assertLessEqual(int(env_ast["iter"]), int(env_ast["maxiter"]))

    def test_user_function_returns_expected_newton_multivariable_outputs(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_newton_multivariable_function_test.mtx").resolve()
        try:
            script_path.write_text(
                "f1(x, y) = x.^2 + y.^2 - 4;\n"
                "f2(x, y) = x + y - 2;\n"
                "x0 = [1; 0];\n"
                "tol = 1e-8;\n"
                "\n"
                "function [x, res, iter] = NewtonMultiVariable(f1, f2, x0, tol)\n"
                "    F = [f1; f2];\n"
                "    Jf1 = [\\diff(f1, x), \\diff(f1, y)];\n"
                "    Jf2 = [\\diff(f2, x), \\diff(f2, y)];\n"
                "    J = [Jf1; Jf2];\n"
                "    x = x0;\n"
                "    z = J(x) | (-F(x));\n"
                "    x = z + x;\n"
                "    iter = 0;\n"
                "    res = \\norm(F(x));\n"
                "    while res > tol\n"
                "        z = J(x) | (-F(x));\n"
                "        x = z + x;\n"
                "        res = \\norm(F(x));\n"
                "        iter = iter + 1;\n"
                "    end\n"
                "end\n"
                "\n"
                "[xr, rr, ir] = NewtonMultiVariable(f1, f2, x0, tol)\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertLess(float(sp.N(env_ast["rr"])), 1e-8)
        self.assertEqual(int(env_ast["ir"]), 4)
        self.assertAlmostEqual(float(sp.N(env_ast["xr"][0, 0])), 2.0, places=8)
        self.assertAlmostEqual(float(sp.N(env_ast["xr"][1, 0])), 0.0, places=8)

    def test_run_script_supports_three_variable_newton_with_complex_seed(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_sistema_no_lineal_test.mtx").resolve()
        try:
            script_path.write_text(
                "from NewtonMultiVariable import NewtonMultiVariable\n"
                "\n"
                "f1(x, y, z) = x + y + z + 5;\n"
                "f2(x, y, z) = x*y + y*z + x*z - 8;\n"
                "f3(x, y, z) = x*y*z - 444;\n"
                "x0 = [2; i; -i];\n"
                "tol = 1e-8;\n"
                "maxiter = 20;\n"
                "\n"
                "[x, res, iter] = NewtonMultiVariable(f1, f2, f3, x0, tol, maxiter)\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertLess(float(sp.N(env_ast["res"])), 1e-8)
        self.assertLessEqual(int(env_ast["iter"]), 20)
        self.assertAlmostEqual(float(sp.re(sp.N(env_ast["x"][0, 0]))), 6.0, places=8)

    def test_run_script_supports_logical_and_or_assignments(self):
        previous_dir = get_working_dir()
        script_path = Path("tmp_logical_ops_test.mtx").resolve()
        try:
            script_path.write_text(
                "a = 1 < 2 && 3 < 4;\n"
                "b = 1 > 2 || 3 < 4;\n"
                "c = 1 > 2 || 3 > 4;\n",
                encoding="utf-8",
            )

            self.assertTrue(change_working_dir(script_path.parent))
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    ejecutar_linea(fr"\run {script_path.name}")
                captured = out.getvalue()
            finally:
                change_working_dir(previous_dir)
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.assertNotIn("Error", captured)
        self.assertIs(env_ast["a"], True)
        self.assertIs(env_ast["b"], True)
        self.assertIs(env_ast["c"], False)


if __name__ == "__main__":
    unittest.main()
