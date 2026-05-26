import unittest

from latex_lang import env_ast, ejecutar_linea, reset_environment


class FunctionConditionNearRealTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def _run(self, lines):
        for line in lines:
            ejecutar_linea(line)

    def test_while_comparison_handles_tiny_imaginary_noise(self):
        self._run([
            "function out = cmpNoise(tol)",
            "    res = 450.0 + 0.e-21*I;",
            "    it = 0;",
            "    while res > tol",
            "        it = it + 1;",
            "        res = 0;",
            "    end",
            "    out = it;",
            "end",
            "ans = cmpNoise(1);",
        ])
        self.assertEqual(int(env_ast.get("ans")), 1)


if __name__ == "__main__":
    unittest.main()
