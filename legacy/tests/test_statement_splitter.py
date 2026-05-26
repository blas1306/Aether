import unittest

from mtex_executor import split_code_statements, split_code_statements_with_lines


class StatementSplitterTests(unittest.TestCase):
    def test_multiline_list_is_single_statement(self):
        block = """
f(x) = x^5 + 15x - 44;

T1 = [-1; 0; 1];
T2 = [-2; -1; 0; 1; 2];

modelos = ["$x_1 + x_2 t^5$",
  "$x_1 + x_2 t + x_3 t^2$",
  "$x_1 + x_2 t + x_3 t^3$"]
"""
        got = split_code_statements(block)
        self.assertEqual(len(got), 4)
        self.assertEqual(got[0], "f(x) = x^5 + 15x - 44;")
        self.assertEqual(got[1], "T1 = [-1; 0; 1];")
        self.assertEqual(got[2], "T2 = [-2; -1; 0; 1; 2];")
        self.assertEqual(
            got[3],
            'modelos = ["$x_1 + x_2 t^5$", "$x_1 + x_2 t + x_3 t^2$", "$x_1 + x_2 t + x_3 t^3$"]',
        )

    def test_brackets_in_string_and_comment_do_not_change_depth(self):
        block = """
a = "[[]]";
b = 1; # ] should be ignored
c = [1,
 2];
"""
        got = split_code_statements(block)
        self.assertEqual(got, ['a = "[[]]";', "b = 1; # ] should be ignored", "c = [1, 2];"])

    def test_split_code_statements_with_lines_preserves_multiline_shape(self):
        block = """
z = 1

A = [
  1,

  foo
]
"""
        got = split_code_statements_with_lines(block)

        self.assertEqual(len(got), 2)
        self.assertEqual(got[0].text, "z = 1")
        self.assertEqual(got[0].start_line, 2)
        self.assertEqual(got[0].end_line, 2)
        self.assertEqual(got[1].text, "A = [\n  1,\n\n  foo\n]")
        self.assertEqual(got[1].start_line, 4)
        self.assertEqual(got[1].end_line, 8)


if __name__ == "__main__":
    unittest.main()
