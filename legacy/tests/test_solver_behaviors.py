import io
import unittest
from contextlib import redirect_stdout

import sympy as sp
from sympy import Matrix

from latex_lang import env_ast, ejecutar_linea, reset_environment


class SolverBehaviorTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, line: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ejecutar_linea(line)
        return buf.getvalue()

    def test_solve_linear_system_returns_minimum_norm_solution_for_infinite_solutions(self):
        self._run("A = [1, 1; 2, 2];")
        self._run("b = [1; 2];")
        self._run(r"x = \solve(A | b);")
        sol = env_ast.get("x")
        self.assertIsInstance(sol, Matrix)
        expected = Matrix([[sp.Rational(1, 2)], [sp.Rational(1, 2)]])
        self.assertEqual((sol - expected).applyfunc(sp.simplify), sp.zeros(2, 1))
        residual = Matrix([[1, 1], [2, 2]]) * sol - Matrix([[1], [2]])
        self.assertEqual(residual.applyfunc(sp.simplify), sp.zeros(2, 1))

    def test_direct_linear_solve_returns_least_squares_solution_when_inconsistent(self):
        self._run("A = [1, 1; 1, 1; 1, 1];")
        self._run("b = [1; 2; 2];")
        output = self._run("x = A | b")
        sol = env_ast.get("x")
        self.assertIsInstance(sol, Matrix)
        self.assertEqual(sol, Matrix([[sp.Rational(5, 6)], [sp.Rational(5, 6)]]))
        self.assertIn("least-squares solution", output)
        residual = Matrix([[1, 1], [1, 1], [1, 1]]) * sol - Matrix([[1], [2], [2]])
        self.assertEqual(
            (Matrix([[1, 1], [1, 1], [1, 1]]).T * residual).applyfunc(sp.simplify),
            Matrix([[0], [0]]),
        )

    def test_direct_linear_solve_reports_minimum_norm_for_infinite_solutions(self):
        self._run("A = [1, 1; 2, 2];")
        self._run("b = [1; 2];")
        output = self._run("x = A | b")
        sol = env_ast.get("x")
        self.assertIsInstance(sol, Matrix)
        expected = Matrix([[sp.Rational(1, 2)], [sp.Rational(1, 2)]])
        self.assertEqual((sol - expected).applyfunc(sp.simplify), sp.zeros(2, 1))
        self.assertIn("minimum-norm solution", output)

    def test_solve_ode_general_solution(self):
        self._run(r"sol = \solve(y'(x) = y(x), y(x));")
        sol = env_ast.get("sol")
        x = sp.Symbol("x")
        y = sp.Function("y")
        self.assertEqual(sol.lhs, y(x))
        self.assertEqual(sp.simplify(sp.diff(sol.rhs, x) - sol.rhs), 0)

    def test_solve_single_variable_returns_scalars_not_singleton_tuples(self):
        self._run("h(x) = x.^2 - 5*x + 6;")
        self._run(r"xh = \solve(h);")
        xh = env_ast.get("xh")
        self.assertEqual(xh, [2, 3])


if __name__ == "__main__":
    unittest.main()
