import unittest

from sympy import MatrixBase, pi

from latex_lang import env_ast, ejecutar_linea, reset_environment


class LinspaceParametricTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def test_linspace_creates_column_vector(self):
        ejecutar_linea(r"t = \linspace(0, 2*\pi, 300);")
        t = env_ast.get("t")
        self.assertIsInstance(t, MatrixBase)
        self.assertEqual(t.shape, (300, 1))
        self.assertAlmostEqual(float(t[0, 0]), 0.0, places=12)
        self.assertAlmostEqual(float(t[299, 0]), float(2 * pi), places=9)

    def test_linspace_default_points(self):
        ejecutar_linea(r"t = \linspace(0, 1);")
        t = env_ast.get("t")
        self.assertIsInstance(t, MatrixBase)
        self.assertEqual(t.shape, (100, 1))

    def test_parametric_vectorized_trig_assignment(self):
        ejecutar_linea(r"t = \linspace(0, 2*\pi, 300);")
        ejecutar_linea(r"x = \cos(3*t);")
        ejecutar_linea(r"y = \sin(2*t);")

        x = env_ast.get("x")
        y = env_ast.get("y")
        self.assertIsInstance(x, MatrixBase)
        self.assertIsInstance(y, MatrixBase)
        self.assertEqual(x.shape, (300, 1))
        self.assertEqual(y.shape, (300, 1))
        self.assertAlmostEqual(float(x[0, 0]), 1.0, places=12)
        self.assertAlmostEqual(float(y[0, 0]), 0.0, places=12)

    def test_vectorization_works_for_other_scalar_functions(self):
        ejecutar_linea(r"t = \linspace(0, 1, 50);")
        ejecutar_linea(r"a = \tan(t);")
        ejecutar_linea(r"b = \exp(t);")
        ejecutar_linea(r"c = \sqrt(t);")

        a = env_ast.get("a")
        b = env_ast.get("b")
        c = env_ast.get("c")
        self.assertIsInstance(a, MatrixBase)
        self.assertIsInstance(b, MatrixBase)
        self.assertIsInstance(c, MatrixBase)
        self.assertEqual(a.shape, (50, 1))
        self.assertEqual(b.shape, (50, 1))
        self.assertEqual(c.shape, (50, 1))

    def test_user_defined_function_can_be_evaluated_on_vector(self):
        ejecutar_linea(r"t = \linspace(0, 2*\pi, 120);")
        ejecutar_linea(r"f(x) = \cos(x) + \sin(2*x);")
        ejecutar_linea(r"z = f(t);")
        z = env_ast.get("z")
        self.assertIsInstance(z, MatrixBase)
        self.assertEqual(z.shape, (120, 1))


if __name__ == "__main__":
    unittest.main()
