import unittest
from typing import cast

from latex_lang import (
    _build_parser_context,
    ejecutar_linea,
    env_ast,
    parse_mathtex_line,
    reset_environment,
)
from mathtex_ast import IndexAssignNode, RangeNode, SliceNode


class AstIndexAssignTests(unittest.TestCase):
    def setUp(self):
        reset_environment()

    def test_parse_index_assign_node(self):
        ctx = _build_parser_context()
        node = parse_mathtex_line("A(1:3, k) = x + 1", ctx)
        self.assertIsInstance(node, IndexAssignNode)
        node = cast(IndexAssignNode, node)
        self.assertEqual(node.target.name, "A")
        self.assertEqual(len(node.indices), 2)
        self.assertIsInstance(node.indices[0], SliceNode)
        self.assertIsInstance(node.indices[1], SliceNode)
        self.assertIsInstance(node.indices[0].value, RangeNode)

    def test_execute_scalar_index_assignment(self):
        ejecutar_linea("A = [1 2; 3 4];")
        ejecutar_linea("A(1,2) = 9;")
        self.assertEqual(env_ast["A"].tolist(), [[1, 9], [3, 4]])

    def test_execute_vector_index_assignment(self):
        ejecutar_linea("v = [10; 20; 30];")
        ejecutar_linea("v(2) = 99;")
        self.assertEqual(env_ast["v"].tolist(), [[10], [99], [30]])

    def test_execute_slice_index_assignment(self):
        ejecutar_linea("A = [1 2; 3 4];")
        ejecutar_linea("A(1:2,1) = Matrix([7,8]);")
        self.assertEqual(env_ast["A"].tolist(), [[7, 2], [8, 4]])

    def test_invalid_index_assignment_does_not_fall_back_to_plain_assign(self):
        ejecutar_linea("A = [1 2; 3 4];")
        ejecutar_linea("A(,1) = 5;")
        self.assertEqual(env_ast["A"].tolist(), [[1, 2], [3, 4]])
        self.assertNotIn("A(,1)", env_ast)


if __name__ == "__main__":
    unittest.main()
