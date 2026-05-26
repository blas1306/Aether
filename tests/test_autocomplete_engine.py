import unittest

from autocomplete_engine import (
    AutocompleteRequest,
    build_autocomplete_suggestions,
    detect_autocomplete_match,
    detect_command_prefix,
    detect_identifier_prefix,
    filter_command_suggestions,
)
from aether.lexer import lex
from aether.tokens import KEYWORDS, TokenType
from document_symbols import extract_document_symbols


class AutocompleteEngineTests(unittest.TestCase):
    def test_detects_backslash_only_prefix(self):
        match = detect_command_prefix("\\", 1)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.kind, "command")
        self.assertEqual(match.prefix, "\\")
        self.assertEqual(match.token_start_col, 0)
        self.assertEqual(match.token_end_col, 1)

    def test_detects_partial_command_with_full_token_bounds(self):
        line = r"resultado = \plo extra"
        cursor_col = line.index(r"\plo") + len(r"\plo")
        match = detect_command_prefix(line, cursor_col)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.kind, "command")
        self.assertEqual(match.prefix, r"\plo")
        self.assertEqual(line[match.token_start_col:match.token_end_col], r"\plo")

    def test_detects_identifier_prefix(self):
        line = "res = variab"
        match = detect_identifier_prefix(line, len(line))
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.kind, "identifier")
        self.assertEqual(match.prefix, "variab")
        self.assertEqual(line[match.token_start_col:match.token_end_col], "variab")

    def test_returns_none_without_valid_prefix(self):
        self.assertIsNone(detect_autocomplete_match("   ", 2))

    def test_filters_builtin_commands_by_prefix(self):
        names = [item.name for item in filter_command_suggestions(r"\p")]
        self.assertIn(r"\pi", names)
        self.assertIn(r"\plot()", names)
        self.assertIn(r"\plot3()", names)
        self.assertNotIn(r"\sum()", names)

    def test_builtin_command_ranking_prefers_stronger_exact_prefix(self):
        names = [item.name for item in filter_command_suggestions(r"\plot")]
        self.assertLess(names.index(r"\plot()"), names.index(r"\plot3()"))

    def test_identifier_context_includes_workspace_variables(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="v",
                cursor_col=1,
                workspace_items=[
                    {"name": "value", "class": "int", "size": "1x1", "summary": "42"},
                    {"name": "vectorA", "class": "Matrix", "size": "2x1", "summary": "[1; 2]"},
                ],
            )
        )

        names = [item.name for item in suggestions]
        self.assertIn("value", names)
        self.assertIn("vectorA", names)

    def test_extract_document_symbols_finds_assignments_functions_and_for_variables(self):
        symbols = extract_document_symbols(
            "A = [1,2;3,4]\n"
            "f(x) = x^2\n"
            "for i = 1:10\n"
        )

        by_name = {item.name: item for item in symbols}
        self.assertEqual(by_name["A"].kind, "variable")
        self.assertEqual(by_name["A"].origin, "assignment")
        self.assertEqual(by_name["f"].kind, "function")
        self.assertEqual(by_name["f"].signature, "f(x)")
        self.assertEqual(by_name["i"].kind, "variable")
        self.assertEqual(by_name["i"].origin, "for_loop_variable")

    def test_document_symbols_include_ranges_types_and_imports(self):
        symbols = extract_document_symbols(
            "import Math.LinearAlgebra\n"
            "double square(double x) {\n"
            "    return x*x;\n"
            "}\n"
            "Matrix < double > A = [1 2];\n"
        )

        by_name = {item.name: item for item in symbols}

        self.assertEqual(by_name["Math.LinearAlgebra"].kind, "module")
        self.assertEqual(by_name["Math.LinearAlgebra"].origin, "import")
        self.assertEqual(by_name["Math.LinearAlgebra"].selection_range.start_character, len("import "))
        self.assertEqual(by_name["square"].kind, "function")
        self.assertEqual(by_name["square"].type_name, "double")
        self.assertEqual(by_name["square"].detail, "double square(double x)")
        self.assertEqual(by_name["square"].selection_range.start_line, 1)
        self.assertEqual(by_name["A"].type_name, "Matrix<double>")
        self.assertEqual(by_name["A"].detail, "Matrix<double> A")

    def test_document_variable_before_cursor_appears_without_runtime_state(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="A",
                cursor_col=1,
                document_text="A = [1,2;3,4]\nA",
            )
        )

        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].name, "A")
        self.assertEqual(suggestions[0].kind, "variable")
        self.assertEqual(suggestions[0].source, "document")

    def test_document_function_before_cursor_appears_with_callable_insert_text(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="so",
                cursor_col=2,
                document_text="solveIt(x) = x^2\nso",
            )
        )

        self.assertEqual(suggestions[0].name, "solveIt")
        self.assertEqual(suggestions[0].kind, "function")
        self.assertEqual(suggestions[0].source, "document")
        self.assertEqual(suggestions[0].signature, "solveIt(x)")
        self.assertEqual(suggestions[0].insert_text, "solveIt()")
        self.assertEqual(suggestions[0].cursor_backtrack, 1)

    def test_document_symbols_after_cursor_are_not_considered_in_this_stage(self):
        full_text = "late\nlaterValue = 1\n"
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="late",
                cursor_col=4,
                document_text=full_text[:4],
            )
        )

        self.assertEqual(suggestions, [])

    def test_document_symbol_extraction_ignores_comments(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="re",
                cursor_col=2,
                document_text="# fake = 1\n// bogus(x) = x\nrealValue = 2\nre",
            )
        )

        names = [item.name for item in suggestions]
        self.assertIn("realValue", names)
        self.assertNotIn("fake", names)
        self.assertNotIn("bogus", names)

    def test_identifier_context_includes_user_functions_with_callable_insert_text(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="so",
                cursor_col=2,
                workspace_items=[
                    {"name": "solveIt", "class": "UserFunction", "size": "function", "summary": "[y] = solveIt(x)"},
                ],
            )
        )

        self.assertEqual(suggestions[0].name, "solveIt")
        self.assertEqual(suggestions[0].insert_text, "solveIt()")
        self.assertEqual(suggestions[0].cursor_backtrack, 1)
        self.assertEqual(suggestions[0].kind, "function")

    def test_call_like_context_prioritizes_functions_over_variables(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="sol(",
                cursor_col=3,
                workspace_items=[
                    {"name": "solveIt", "class": "UserFunction", "size": "function", "summary": "[y] = solveIt(x)"},
                    {"name": "solverValue", "class": "float", "size": "1x1", "summary": "3.14"},
                ],
            )
        )

        self.assertEqual(suggestions[0].name, "solveIt")
        self.assertEqual(suggestions[0].kind, "function")

    def test_document_symbols_rank_ahead_of_workspace_items_for_identifiers(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="res",
                cursor_col=3,
                document_text="resDoc = 1\nres",
                workspace_items=[
                    {"name": "resRun", "class": "float", "size": "1x1", "summary": "3.14"},
                ],
            )
        )

        self.assertEqual(suggestions[0].name, "resDoc")
        self.assertEqual(suggestions[0].source, "document")
        self.assertIn("resRun", [item.name for item in suggestions])

    def test_document_for_loop_variable_can_be_suggested(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="i",
                cursor_col=1,
                document_text="for i = 1:10\ni",
            )
        )

        self.assertEqual(suggestions[0].name, "i")
        self.assertEqual(suggestions[0].source, "document")

    def test_identifier_context_falls_back_to_keywords(self):
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="fun", cursor_col=3))

        self.assertEqual(suggestions[0].name, "function")
        self.assertEqual(suggestions[0].kind, "keyword")

    def test_aether_builtins_are_suggested_by_prefix(self):
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="pri", cursor_col=3))

        names = [item.name for item in suggestions]
        self.assertIn("println", names)
        self.assertIn("print", names)
        self.assertNotIn("numel", names)

    def test_aether_global_math_builtins_are_suggested_by_prefix(self):
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="si", cursor_col=2))

        names = [item.name for item in suggestions]
        self.assertIn("sin", names)

    def test_for_prefix_includes_for_snippet_above_keyword(self):
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="for", cursor_col=3))

        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].name, "for")
        self.assertEqual(suggestions[0].kind, "snippet")
        self.assertIn("{", suggestions[0].insert_text)
        self.assertEqual(suggestions[0].cursor_selection_length, 1)

    def test_aether_control_and_function_snippets_are_available(self):
        expected = {
            "fn": ("f(x) = expression;", "Expression function snippet.", len("expression")),
            "for": ("for x in iterable {\n    \n}", "For loop snippet.", len("x")),
            "if": ("if condition {\n    \n}", "If block snippet.", len("condition")),
            "while": ("while condition {\n    \n}", "While loop snippet.", len("condition")),
            "func": ("int name() {\n    \n}", "Block function snippet.", len("name")),
            "ife": ("if condition {\n    \n} else {\n    \n}", "If/else block snippet.", len("condition")),
        }

        for prefix, (insert_text, description, selection_length) in expected.items():
            with self.subTest(prefix=prefix):
                suggestions = build_autocomplete_suggestions(
                    AutocompleteRequest(line_text=prefix, cursor_col=len(prefix))
                )

                self.assertGreaterEqual(len(suggestions), 1)
                self.assertEqual(suggestions[0].name, prefix)
                self.assertEqual(suggestions[0].kind, "snippet")
                self.assertEqual(suggestions[0].insert_text, insert_text)
                self.assertEqual(suggestions[0].description, description)
                self.assertEqual(suggestions[0].cursor_selection_length, selection_length)

    def test_fn_is_editor_snippet_only_not_a_language_keyword(self):
        self.assertNotIn("fn", KEYWORDS)
        tokens = lex("fn")

        self.assertEqual(tokens[0].type, TokenType.IDENTIFIER)

    def test_aether_types_stay_keyword_suggestions(self):
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="int", cursor_col=3))

        self.assertEqual(suggestions[0].name, "int")
        self.assertEqual(suggestions[0].kind, "keyword")

    def test_matrix_and_vector_type_completions_insert_angle_pair(self):
        matrix_suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="Mat", cursor_col=3))
        vector_suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="Vec", cursor_col=3))

        self.assertEqual(matrix_suggestions[0].name, "Matrix")
        self.assertEqual(matrix_suggestions[0].kind, "keyword")
        self.assertEqual(matrix_suggestions[0].insert_text, "Matrix<>")
        self.assertEqual(matrix_suggestions[0].cursor_backtrack, 1)
        self.assertEqual(vector_suggestions[0].name, "Vector")
        self.assertEqual(vector_suggestions[0].kind, "keyword")
        self.assertEqual(vector_suggestions[0].insert_text, "Vector<>")
        self.assertEqual(vector_suggestions[0].cursor_backtrack, 1)

    def test_math_namespace_suggests_real_submodules(self):
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="Math.", cursor_col=len("Math.")))

        self.assertEqual([item.name for item in suggestions], ["LinearAlgebra", "mod"])
        self.assertEqual(suggestions[0].kind, "module")
        self.assertEqual(suggestions[1].kind, "function")

    def test_math_linear_algebra_suggests_real_functions_only(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(line_text="Math.LinearAlgebra.", cursor_col=len("Math.LinearAlgebra."))
        )

        names = [item.name for item in suggestions]
        self.assertIn("transpose", names)
        self.assertIn("matmul", names)
        self.assertIn("inner", names)
        self.assertIn("norm", names)
        self.assertIn("solve", names)
        self.assertNotIn("det", names)
        self.assertNotIn("inv", names)

    def test_aether_variables_are_suggested_by_prefix(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="su",
                cursor_col=2,
                document_text="suma = 0;\nvectorDatos = [1, 2, 3];\nsu",
            )
        )

        self.assertEqual(suggestions[0].name, "suma")
        self.assertEqual(suggestions[0].source, "document")

    def test_aether_typed_functions_are_suggested_by_prefix(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="do",
                cursor_col=2,
                document_text="int doble(int x) { return 2 * x; }\ndo",
            )
        )

        self.assertEqual(suggestions[0].name, "doble")
        self.assertEqual(suggestions[0].kind, "function")
        self.assertEqual(suggestions[0].signature, "doble(x)")

    def test_does_not_suggest_inside_strings(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text='"pri',
                cursor_col=len('"pri'),
            )
        )

        self.assertEqual(suggestions, [])

    def test_does_not_suggest_inside_slash_comments(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="// pri",
                cursor_col=len("// pri"),
            )
        )

        self.assertEqual(suggestions, [])

    def test_mtex_document_context_avoids_keyword_noise_on_plain_text_lines(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="This paragraph mentions fu",
                cursor_col=len("This paragraph mentions fu"),
                document_kind="mtex_document",
            )
        )

        self.assertEqual(suggestions, [])

    def test_mtex_document_plain_text_lines_do_not_show_document_symbol_noise(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="This paragraph mentions fu",
                cursor_col=len("This paragraph mentions fu"),
                document_kind="mtex_document",
                document_text="funcLocal = 1\nThis paragraph mentions fu",
            )
        )

        self.assertEqual(suggestions, [])

    def test_does_not_suggest_inside_comments(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text=r"value = 1 # \pl",
                cursor_col=len(r"value = 1 # \pl"),
            )
        )

        self.assertEqual(suggestions, [])

    def test_percent_is_not_a_script_comment_for_autocomplete(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text="value = 5 % Math.",
                cursor_col=len("value = 5 % Math."),
            )
        )

        self.assertEqual([item.name for item in suggestions], ["LinearAlgebra", "mod"])

    def test_percent_remains_mtex_text_comment_for_autocomplete(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text=r"% \pl",
                cursor_col=len(r"% \pl"),
                document_kind="mtex_document",
            )
        )

        self.assertEqual(suggestions, [])

    def test_includes_spec_and_eig_but_not_removed_py_commands(self):
        names = {item.name for item in filter_command_suggestions("\\")}
        self.assertIn(r"\Spec()", names)
        self.assertIn(r"\Eig()", names)
        self.assertIn(r"\Schur()", names)
        self.assertNotIn(r"\py", names)
        self.assertNotIn(r"\endpy", names)

    def test_builtin_commands_still_work_when_document_text_is_present(self):
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text=r"\plo",
                cursor_col=4,
                document_text="plotValue = 1\n\\plo",
            )
        )

        self.assertEqual(suggestions[0].name, r"\plot()")
        self.assertEqual(suggestions[0].source, "catalog")

    def test_package_functions_suggested_by_short_name_prefix(self):
        """Test that package functions like Plots.plot are suggested when typing short prefixes."""
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="p", cursor_col=1))
        names = [item.name for item in suggestions]
        
        # Plots functions should appear
        self.assertIn("plot", names)
        self.assertIn("plot!", names)
        
        # print and println should also appear
        self.assertIn("print", names)
        self.assertIn("println", names)

    def test_linear_algebra_inner_function_suggested_by_prefix(self):
        """Test that Math.LinearAlgebra.inner is suggested when typing 'i'."""
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="i", cursor_col=1))
        names = [item.name for item in suggestions]
        
        self.assertIn("inner", names)
        # Verify it has the full qualified signature
        inner_sugg = next(s for s in suggestions if s.name == "inner")
        self.assertEqual(inner_sugg.signature, "Math.LinearAlgebra.inner(...)")

    def test_linear_algebra_norm_function_suggested_by_prefix(self):
        """Test that Math.LinearAlgebra.norm is suggested when typing 'no'."""
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="no", cursor_col=2))
        names = [item.name for item in suggestions]
        
        self.assertIn("norm", names)
        norm_sugg = next(s for s in suggestions if s.name == "norm")
        self.assertEqual(norm_sugg.signature, "Math.LinearAlgebra.norm(...)")

    def test_linear_algebra_transpose_function_suggested_by_prefix(self):
        """Test that Math.LinearAlgebra.transpose is suggested when typing 'tr'."""
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="tr", cursor_col=2))
        names = [item.name for item in suggestions]
        
        self.assertIn("transpose", names)
        transpose_sugg = next(s for s in suggestions if s.name == "transpose")
        self.assertEqual(transpose_sugg.signature, "Math.LinearAlgebra.transpose(...)")

    def test_plots_scatter_function_suggested_by_prefix(self):
        """Test that Plots.scatter is suggested when typing 'sc'."""
        suggestions = build_autocomplete_suggestions(AutocompleteRequest(line_text="sc", cursor_col=2))
        names = [item.name for item in suggestions]
        
        self.assertIn("scatter", names)
        scatter_sugg = next(s for s in suggestions if s.name == "scatter")
        self.assertEqual(scatter_sugg.signature, "Plots.scatter(...)")


if __name__ == "__main__":
    unittest.main()
