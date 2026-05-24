from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherTypeError
from aether.runner import run_aether
from aether.types import ArrayType, MatrixType, TransposeVectorType, VectorType


def test_inferred_assignment():
    result = run_aether("x = 5; y = x + 2;")
    assert result.env["x"].value == 5
    assert result.env["y"].value == 7


def test_typed_assignment():
    result = run_aether("int x = 5;")
    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 5


def test_type_error():
    with pytest.raises(AetherTypeError):
        run_aether('int x = "hola";')


def test_println_output():
    result = run_aether('println("Hola");')
    assert result.output == "Hola\n"


def test_if_block():
    result = run_aether("x = 5; if x > 0 { println(x); }")
    assert result.output == "5\n"


def test_while_block():
    result = run_aether("x = 0; while x < 3 { println(x); x = x + 1; }")
    assert result.output == "0\n1\n2\n"


def test_double_to_int_assignment_error():
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'double' to 'int'"):
        run_aether("double a = 4.0; double b = 3.0; int c = a / b;")


def test_explicit_double_to_int_cast():
    result = run_aether("double a = 4.0; double b = 3.0; int c = int(a / b);")
    assert result.env["c"].type_name == "int"
    assert result.env["c"].value == 1


def test_int_division_returns_double():
    result = run_aether("int a = 5; int b = 2; c = a / b;")
    assert result.env["c"].type_name == "double"
    assert result.env["c"].value == 2.5


def test_int_to_double_assignment_allowed():
    result = run_aether("double x = 5;")
    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == 5.0


def test_double_to_float_assignment_error():
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'double' to 'float'"):
        run_aether("float x = 5.2; y = 3.2; x = y;")


def test_float_to_double_assignment_allowed():
    result = run_aether("float x = 5.2; double y = x;")
    assert result.env["y"].type_name == "double"
    assert result.env["y"].value == pytest.approx(5.2)


def test_string_numeric_addition_error():
    with pytest.raises(AetherTypeError):
        run_aether('x = "value: " + 5;')


def test_boolean_numeric_addition_error():
    with pytest.raises(AetherTypeError):
        run_aether("x = true + 1;")


def test_inferred_variable_type_is_fixed():
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'string' to 'int'"):
        run_aether('x = 5; x = "hola";')


def test_if_condition_must_be_boolean():
    with pytest.raises(AetherTypeError, match="condition of 'if' must be boolean"):
        run_aether('if 1 { println("bad"); }')


def test_while_condition_must_be_boolean():
    with pytest.raises(AetherTypeError, match="condition of 'while' must be boolean"):
        run_aether('while 1 { println("bad"); }')


def test_print_multiple_arguments():
    result = run_aether('print("x = ", 5); println(" ok");')
    assert result.output == "x = 5 ok\n"


def test_function_typed_return_valid():
    result = run_aether("double doble(double x) { return 2 * x; } y = doble(3.0);")
    assert result.env["y"].type_name == "double"
    assert result.env["y"].value == 6.0


def test_function_without_function_keyword():
    result = run_aether(
        """
double doble(double x) {
    return 2*x;
}
println(doble(3));
"""
    )

    assert result.output == "6.0\n"


def test_recursive_function_without_function_keyword():
    result = run_aether(
        """
int fib(int n) {
    if n <= 1 {
        return n;
    }

    return fib(n - 1) + fib(n - 2);
}
println(fib(6));
"""
    )

    assert result.output == "8\n"


def test_legacy_function_keyword_still_works():
    result = run_aether("function int f(int x) { return x + 1; } println(f(4));")

    assert result.output == "5\n"


def test_function_typed_return_error():
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'string' to 'int'"):
        run_aether('int bad() { return "hola"; } x = bad();')


def test_block_variable_does_not_escape():
    with pytest.raises(AetherTypeError, match="Undefined variable 'y'"):
        run_aether("if true { int y = 3; } println(y);")


def test_outer_variable_can_be_updated_inside_block():
    result = run_aether("x = 1; if true { x = 2; } println(x);")
    assert result.output == "2\n"
    assert result.env["x"].value == 2


def test_inner_inferred_variable_does_not_escape():
    with pytest.raises(AetherTypeError, match="Undefined variable 'y'"):
        run_aether("if true { y = 3; } println(y);")


def test_shadowing_is_not_allowed():
    with pytest.raises(AetherTypeError, match="shadowing is not allowed"):
        run_aether("int x = 1; if true { double x = 2.5; }")


def test_function_local_variable_does_not_escape():
    with pytest.raises(AetherTypeError, match="Undefined variable 'x'"):
        run_aether("int f() { int x = 1; return x; } f(); println(x);")


def test_function_parameter_does_not_escape():
    with pytest.raises(AetherTypeError, match="Undefined variable 'x'"):
        run_aether("int f(int x) { return x + 1; } f(2); println(x);")


def test_function_calls_have_separate_scopes():
    result = run_aether(
        """
int f(int x) {
    x = x + 1;
    return x;
}
println(f(1));
println(f(10));
"""
    )
    assert result.output == "2\n11\n"


def test_block_assignment_respects_outer_type():
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'double' to 'int'"):
        run_aether("int x = 1; if true { x = 2.5; }")


def test_while_inner_variable_does_not_escape():
    with pytest.raises(AetherTypeError, match="Undefined variable 'y'"):
        run_aether("x = 0; while x < 1 { y = 5; x = x + 1; } println(y);")


def test_undefined_variable_detected_by_typechecker():
    with pytest.raises(AetherTypeError, match="Undefined variable 'y'"):
        run_aether("println(y);")


def test_static_error_happens_before_execution():
    with pytest.raises(AetherTypeError, match="Undefined variable 'y'"):
        run_aether('println("before"); println(y);')


def test_return_outside_function_is_error():
    with pytest.raises(AetherTypeError, match="Cannot return outside of a function"):
        run_aether("return 5;")


def test_function_without_return_is_error():
    with pytest.raises(AetherTypeError, match="may not return"):
        run_aether("int f() { int x = 1; }")


def test_function_if_without_else_may_not_return_is_error():
    with pytest.raises(AetherTypeError, match="may not return"):
        run_aether("int f(int x) { if x > 0 { return x; } }")


def test_function_if_else_both_return_is_valid():
    result = run_aether(
        """
int f(int x) {
    if x > 0 {
        return x;
    } else {
        return 0;
    }
}
println(f(3));
"""
    )
    assert result.output == "3\n"


def test_function_return_type_error():
    with pytest.raises(AetherTypeError):
        run_aether("int f() { return 2.5; }")


def test_function_return_allows_widening():
    result = run_aether("double f() { return 2; } println(f());")
    assert result.output in {"2\n", "2.0\n"}


def test_function_wrong_arity_too_few():
    with pytest.raises(AetherTypeError, match="expects 2 arguments but got 1"):
        run_aether("int add(int a, int b) { return a + b; } add(1);")


def test_function_wrong_arity_too_many():
    with pytest.raises(AetherTypeError, match="expects 2 arguments but got 3"):
        run_aether("int add(int a, int b) { return a + b; } add(1, 2, 3);")


def test_function_argument_type_error():
    with pytest.raises(AetherTypeError):
        run_aether("int f(int x) { return x; } f(2.5);")


def test_function_argument_allows_widening():
    result = run_aether("double f(double x) { return x; } println(f(2));")
    assert result.output in {"2\n", "2.0\n"}


def test_duplicate_function_name_is_error():
    with pytest.raises(AetherTypeError):
        run_aether("int f() { return 1; } int f() { return 2; }")


def test_duplicate_parameter_name_is_error():
    with pytest.raises(AetherTypeError):
        run_aether("int f(int x, double x) { return 1; }")


def test_undefined_function_is_error():
    with pytest.raises(AetherTypeError, match="Undefined function 'foo'"):
        run_aether("foo();")


def test_builtin_print_is_known_to_typechecker():
    result = run_aether('println("ok");')
    assert result.output == "ok\n"


def matrix_values(value):
    return [[element.value for element in row.value] for row in value.value]


def vector_values(value):
    return [element.value for element in value.value]


def test_matrix_space_separated_literal():
    result = run_aether("x = [1 2 3];")
    assert result.env["x"].type_name == MatrixType("int", 1, 3)
    assert matrix_values(result.env["x"]) == [[1, 2, 3]]


def test_comma_separated_literal_is_vector():
    result = run_aether("x = [1, 2, 3];")
    assert result.env["x"].type_name == VectorType("int", 3)
    assert vector_values(result.env["x"]) == [1, 2, 3]


def test_semicolon_separated_literal_is_vector():
    result = run_aether("x = [1; 2; 3];")
    assert result.env["x"].type_name == VectorType("int", 3)
    assert vector_values(result.env["x"]) == [1, 2, 3]


def test_single_element_bracket_literal_is_vector():
    result = run_aether("x = [1];")
    assert result.env["x"].type_name == VectorType("int", 1)
    assert vector_values(result.env["x"]) == [1]


def test_matrix_2x2_literal():
    result = run_aether("A = [1 2; 3 4];")
    assert result.env["A"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["A"]) == [[1, 2], [3, 4]]


def test_matrix_rejects_ragged_rows():
    with pytest.raises(AetherTypeError):
        run_aether("A = [1 2; 3];")


def test_matrix_promotes_to_double():
    result = run_aether("A = [1 2; 3.0 4];")
    assert result.env["A"].type_name == MatrixType("double", 2, 2)
    assert matrix_values(result.env["A"]) == [[1.0, 2.0], [3.0, 4.0]]


def test_matrix_rejects_incompatible_element():
    with pytest.raises(AetherTypeError):
        run_aether('A = [1 "x"];')


def test_explicit_matrix_int():
    result = run_aether("Matrix<int> A = [1 2; 3 4];")
    assert result.env["A"].type_name == MatrixType("int", 2, 2)


def test_explicit_matrix_double_allows_ints():
    result = run_aether("Matrix<double> A = [1 2; 3.0 4];")
    assert result.env["A"].type_name == MatrixType("double", 2, 2)
    assert matrix_values(result.env["A"]) == [[1.0, 2.0], [3.0, 4.0]]


def test_explicit_matrix_int_rejects_double():
    with pytest.raises(AetherTypeError):
        run_aether("Matrix<int> A = [1 2; 3.0 4];")


def test_explicit_vector_row():
    result = run_aether("Vector<int> row = [1 2 3];")
    assert result.env["row"].type_name == VectorType("int", 3)
    assert vector_values(result.env["row"]) == [1, 2, 3]


def test_explicit_vector_column():
    result = run_aether("Vector<int> col = [1; 2; 3];")
    assert result.env["col"].type_name == VectorType("int", 3)


def test_explicit_vector_rejects_2d_matrix():
    with pytest.raises(AetherTypeError):
        run_aether("Vector<int> bad = [1 2; 3 4];")


def test_array_constructor_is_removed():
    with pytest.raises(AetherTypeError, match="Undefined function 'array'"):
        run_aether("a = array(1, 2, 3);")


def test_bracket_literal_is_matrix_not_array():
    result = run_aether("x = [1, 2, 3];")
    assert isinstance(result.env["x"].type_name, VectorType)


def test_array_constructor_empty_is_removed():
    with pytest.raises(AetherTypeError, match="Undefined function 'array'"):
        run_aether("x = array();")


def test_empty_array_with_explicit_type_is_valid():
    result = run_aether("int[] x = []; double[] y = []; string[] z = []; boolean[] b = []; float[] f = [];")
    assert result.env["x"].type_name == ArrayType("int")
    assert result.env["y"].type_name == ArrayType("double")
    assert result.env["z"].type_name == ArrayType("string")
    assert result.env["b"].type_name == ArrayType("boolean")
    assert result.env["f"].type_name == ArrayType("float")
    assert result.env["x"].value == []


def test_length_empty_array_returns_int():
    result = run_aether("int[] xs = []; n = length(xs);")
    assert result.env["n"].type_name == "int"
    assert result.env["n"].value == 0


def test_length_matrix_is_error():
    with pytest.raises(AetherTypeError):
        run_aether("length([1 2 3]);")


def test_matrix_rows_cols_builtin():
    result = run_aether("A = [1 2; 3 4]; println(rows(A)); println(cols(A));")
    assert result.output == "2\n2\n"


def test_matrix_index_reads_zero_based():
    result = run_aether("A = [1 2; 3 4]; println(A[0, 1]); println(A[1, 0]);")
    assert result.output == "2\n3\n"


def test_vector_index_reads_zero_based_element():
    result = run_aether("v = [10, 20, 30]; println(v[0]); println(v[2]);")
    assert result.output == "10\n30\n"


def test_matrix_index_assignment_updates_element():
    result = run_aether("A = [1 2; 3 4]; A[1, 0] = 99; println(A);")
    assert result.output == "[1 2; 99 4]\n"


def test_vector_index_assignment_updates_element():
    result = run_aether("v = [10, 20, 30]; v[1] = 99; println(v);")
    assert result.output == "[10, 99, 30]\n"


def test_matrix_index_assignment_respects_element_type():
    with pytest.raises(AetherTypeError):
        run_aether("A = [1 2; 3 4]; A[0, 0] = 2.5;")
    result = run_aether("A = [1 2.5; 3 4]; A[0, 0] = 2.5; println(A[0, 0]);")
    assert result.output == "2.5\n"


def test_print_row_vector_pretty():
    result = run_aether("println([1 2 3]);")
    assert result.output == "[1 2 3]\n"


def test_print_column_vector_pretty():
    result = run_aether("println([1; 2; 3]);")
    assert result.output == "[1, 2, 3]\n"


def test_print_matrix_pretty():
    result = run_aether("println([1 2; 3 4]);")
    assert result.output == "[1 2; 3 4]\n"


def test_print_one_by_one_matrix_as_scalar():
    result = run_aether("println(Math.LinearAlgebra.matmul([1 2], [3; 4]));")
    assert result.output == "[11]\n"


def test_print_double_matrix_pretty():
    result = run_aether("println([1.0 2.5; 3 4]);")
    assert result.output == "[1.0 2.5; 3.0 4.0]\n"


def test_print_string_matrix_pretty_if_supported():
    result = run_aether('println(["a" "b"; "c" "d"]);')
    assert result.output == '["a" "b"; "c" "d"]\n'


def test_print_boolean_matrix_pretty_if_supported():
    result = run_aether("println([true false; false true]);")
    assert result.output == "[true false; false true]\n"


def test_matrix_addition_still_works():
    result = run_aether("println([1 2; 3 4] + [5 6; 7 8]);")
    assert result.output == "[6 8; 10 12]\n"


def test_matrix_scalar_multiplication_still_works():
    result = run_aether("println([1 2; 3 4] * 2); println(2 * [1 2; 3 4]);")
    assert result.output == "[2 4; 6 8]\n[2 4; 6 8]\n"


def test_matrix_vector_like_addition_same_shape():
    result = run_aether("println([1 2 3] + [4 5 6]);")
    assert result.output == "[5 7 9]\n"


def test_vector_row_plus_vector_column_shape_error():
    with pytest.raises(AetherTypeError):
        run_aether("[1 2 3] + [1; 2; 3];")


def test_matrix_multiplication_uses_algebraic_product():
    result = run_aether("C = [1 2; 3 4] * [1 2; 3 4]; println(C);")
    assert result.output == "[7 10; 15 22]\n"
    assert result.env["C"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["C"]) == [[7, 10], [15, 22]]


def test_matrix_negative_index_runtime_error():
    with pytest.raises(AetherRuntimeError):
        run_aether("A = [1 2; 3 4]; println(A[-1, 0]);")
    with pytest.raises(AetherRuntimeError):
        run_aether("A = [1 2; 3 4]; println(A[0, -1]);")


def test_matrix_out_of_bounds_runtime_error():
    with pytest.raises(AetherRuntimeError):
        run_aether("A = [1 2; 3 4]; println(A[2, 0]);")
    with pytest.raises(AetherRuntimeError):
        run_aether("A = [1 2; 3 4]; println(A[0, 2]);")


def test_matrix_cannot_be_if_condition():
    with pytest.raises(AetherTypeError):
        run_aether('if [true] { println("bad"); }')


def test_matrix_single_index_is_rejected():
    with pytest.raises(AetherTypeError, match="A\\[i, j\\]"):
        run_aether("A = [1 2 3; 4 5 6]; println(A[0]);")


def test_length_accepts_explicit_array():
    result = run_aether("int[] xs = []; println(length(xs));")
    assert result.output == "0\n"


def test_length_rejects_row_vector():
    with pytest.raises(AetherTypeError):
        run_aether("println(length([1 2 3]));")


def test_length_accepts_vector_literal():
    result = run_aether("println(length([1; 2; 3])); println(length([1, 2, 3]));")
    assert result.output == "3\n3\n"


def test_length_rejects_matrix():
    with pytest.raises(AetherTypeError):
        run_aether("println(length([1 2; 3 4]));")


def test_rows_cols_row_vector():
    result = run_aether("println(rows([1 2 3])); println(cols([1 2 3]));")
    assert result.output == "1\n3\n"


def test_rows_cols_reject_1d_vector():
    with pytest.raises(AetherTypeError):
        run_aether("println(rows([1; 2; 3]));")
    with pytest.raises(AetherTypeError):
        run_aether("println(cols([1; 2; 3]));")


def test_rows_cols_matrix():
    result = run_aether("println(rows([1 2; 3 4])); println(cols([1 2; 3 4]));")
    assert result.output == "2\n2\n"


def test_rows_rejects_array():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; rows(xs);")


def test_cols_rejects_array():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; cols(xs);")


def test_array_plus_matrix_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; xs + [1 2];")


def test_matrix_plus_array_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; [1 2] + xs;")


def test_array_minus_matrix_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; xs - [1 2];")


def test_matrix_minus_array_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; [1 2] - xs;")


def test_array_times_matrix_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; xs * [1 2];")


def test_matrix_times_array_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; [1 2] * xs;")


def test_array_eq_matrix_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; xs == [1 2];")


def test_matrix_eq_array_error():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; [1 2] == xs;")


def test_explicit_matrix_int_valid():
    result = run_aether("Matrix<int> A = [1 2; 3 4];")
    assert result.env["A"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["A"]) == [[1, 2], [3, 4]]


def test_explicit_matrix_double_valid():
    result = run_aether("Matrix<double> B = [1 2; 3.0 4];")
    assert result.env["B"].type_name == MatrixType("double", 2, 2)
    assert matrix_values(result.env["B"]) == [[1.0, 2.0], [3.0, 4.0]]


def test_explicit_matrix_int_rejects_double():
    with pytest.raises(AetherTypeError):
        run_aether("Matrix<int> A = [1 2; 3.0 4];")


def test_explicit_matrix_string_rejects_ints():
    with pytest.raises(AetherTypeError):
        run_aether("Matrix<string> A = [1 2; 3 4];")


def test_explicit_vector_row_valid():
    result = run_aether("Vector<int> row = [1 2 3];")
    assert result.env["row"].type_name == VectorType("int", 3)
    assert vector_values(result.env["row"]) == [1, 2, 3]


def test_explicit_vector_column_valid():
    result = run_aether("Vector<int> col = [1; 2; 3];")
    assert result.env["col"].type_name == VectorType("int", 3)
    assert vector_values(result.env["col"]) == [1, 2, 3]


def test_explicit_vector_double_valid():
    result = run_aether("Vector<double> v = [1 2.5 3];")
    assert result.env["v"].type_name == VectorType("double", 3)
    assert vector_values(result.env["v"]) == [1.0, 2.5, 3.0]


def test_explicit_vector_rejects_2x2_matrix():
    with pytest.raises(AetherTypeError):
        run_aether("Vector<int> bad = [1 2; 3 4];")


def test_explicit_vector_int_rejects_double():
    with pytest.raises(AetherTypeError):
        run_aether("Vector<int> v = [1 2.5 3];")


def test_matrix_vector_array_printing_stable():
    result = run_aether(
        """
println([1 2 3]);
    println([1; 2; 3]);
    println([1 2; 3 4]);
    """
    )
    assert result.output == "[1 2 3]\n[1, 2, 3]\n[1 2; 3 4]\n"


def test_matrix_row_extraction_uses_two_dimensional_indexing_now():
    with pytest.raises(AetherTypeError, match="A\\[i, j\\]"):
        run_aether("A = [1 2; 3 4]; println(A[0]);")


def test_inner_row_vectors():
    result = run_aether("u = [1 2 3]; v = [4 5 6]; x = Math.LinearAlgebra.inner(u, v); println(x);")
    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32
    assert result.output == "32\n"


def test_inner_column_vectors():
    result = run_aether("u = [1; 2; 3]; v = [4; 5; 6]; x = Math.LinearAlgebra.inner(u, v);")
    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32


def test_inner_row_column_vectors():
    result = run_aether("x = Math.LinearAlgebra.inner([1 2 3], [4; 5; 6]);")
    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32


def test_inner_promotes_to_double():
    result = run_aether("x = Math.LinearAlgebra.inner([1 2 3], [4.0 5 6]);")
    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == pytest.approx(32.0)


def test_inner_rejects_matrix():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.inner([1 2; 3 4], [1 2; 3 4]);")


def test_inner_rejects_array():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; Math.LinearAlgebra.inner(xs, xs);")


def test_inner_rejects_length_mismatch():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.inner([1 2 3], [1 2]);")


def test_inner_rejects_non_numeric():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.inner([true false], [true false]);")


def test_norm_basic():
    result = run_aether("x = Math.LinearAlgebra.norm([3 4]); println(x);")
    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == pytest.approx(5.0)
    assert result.output == "5.0\n"


def test_norm_column_vector():
    result = run_aether("x = Math.LinearAlgebra.norm([1; 2; 2]);")
    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == pytest.approx(3.0)


def test_norm_promotes_to_double():
    result = run_aether("x = Math.LinearAlgebra.norm([1.5 2]);")
    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == pytest.approx(2.5)


def test_norm_rejects_matrix():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.norm([1 2; 3 4]);")


def test_norm_rejects_array():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; Math.LinearAlgebra.norm(xs);")


def test_norm_rejects_non_numeric():
    with pytest.raises(AetherTypeError):
        run_aether('Math.LinearAlgebra.norm(["a" "b"]);')


def test_transpose_row_vector():
    result = run_aether("x = Math.LinearAlgebra.transpose([1 2 3]); println(x);")
    assert result.env["x"].type_name == MatrixType("int", 3, 1)
    assert matrix_values(result.env["x"]) == [[1], [2], [3]]
    assert result.output == "[1; 2; 3]\n"


def test_print_transpose_pretty():
    result = run_aether("println(Math.LinearAlgebra.transpose([1 2; 3 4]));")

    assert result.output == "[1 3; 2 4]\n"


def test_transpose_column_vector():
    result = run_aether("x = Math.LinearAlgebra.transpose([1; 2; 3]); println(x);")
    assert result.env["x"].type_name == TransposeVectorType("int", 3)
    assert vector_values(result.env["x"].value) == [1, 2, 3]
    assert result.output == "[1 2 3]\n"


def test_transpose_matrix():
    result = run_aether("x = Math.LinearAlgebra.transpose([1 2; 3 4]); println(x);")
    assert result.env["x"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["x"]) == [[1, 3], [2, 4]]
    assert result.output == "[1 3; 2 4]\n"


def test_transpose_does_not_mutate_original():
    result = run_aether(
        """
A = [1 2; 3 4];
B = Math.LinearAlgebra.transpose(A);
B[0, 1] = 99;
println(A);
println(B);
"""
    )
    assert matrix_values(result.env["A"]) == [[1, 2], [3, 4]]
    assert matrix_values(result.env["B"]) == [[1, 99], [2, 4]]
    assert result.output == "[1 2; 3 4]\n[1 99; 2 4]\n"


def test_transpose_rejects_array():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; Math.LinearAlgebra.transpose(xs);")


def test_transpose_rejects_scalar():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.transpose(1);")


def test_transpose_rejects_string_or_boolean_matrix_if_applicable():
    with pytest.raises(AetherTypeError):
        run_aether('Math.LinearAlgebra.transpose(["a" "b"]);')
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.transpose([true false]);")


def test_matmul_matrix_matrix():
    result = run_aether(
        """
A = [1 2; 3 4];
B = [5 6; 7 8];
C = Math.LinearAlgebra.matmul(A, B);
println(C);
"""
    )
    assert result.env["C"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["C"]) == [[19, 22], [43, 50]]
    assert result.output == "[19 22; 43 50]\n"


def test_matmul_row_column():
    result = run_aether(
        """
u = [1 2 3];
v = [4; 5; 6];
C = Math.LinearAlgebra.matmul(u, v);
println(C);
"""
    )
    assert result.env["C"].type_name == VectorType("int", 1)
    assert vector_values(result.env["C"]) == [32]
    assert result.output == "[32]\n"


def test_print_matmul_pretty():
    result = run_aether("println(Math.LinearAlgebra.matmul([1 2; 3 4], [5; 6]));")

    assert result.output == "[17, 39]\n"


def test_matmul_rejects_vector_matrix_without_orientation():
    with pytest.raises(AetherTypeError):
        run_aether(
        """
u = [1; 2; 3];
v = [4 5 6];
C = Math.LinearAlgebra.matmul(u, v);
println(C);
"""
        )


def test_matmul_matrix_column_vector():
    result = run_aether(
        """
A = [1 2; 3 4];
v = [5; 6];
C = Math.LinearAlgebra.matmul(A, v);
println(C);
"""
    )
    assert result.env["C"].type_name == VectorType("int", 2)
    assert vector_values(result.env["C"]) == [17, 39]
    assert result.output == "[17, 39]\n"


def test_matmul_row_vector_matrix():
    result = run_aether(
        """
u = [1 2];
A = [3 4; 5 6];
C = Math.LinearAlgebra.matmul(u, A);
println(C);
"""
    )
    assert result.env["C"].type_name == MatrixType("int", 1, 2)
    assert matrix_values(result.env["C"]) == [[13, 16]]
    assert result.output == "[13 16]\n"


def test_matmul_promotes_to_double():
    result = run_aether("C = Math.LinearAlgebra.matmul([1 2.0], [3; 4]);")
    assert result.env["C"].type_name == VectorType("double", 1)
    assert vector_values(result.env["C"])[0] == pytest.approx(11.0)


def test_matmul_does_not_mutate_operands():
    result = run_aether(
        """
A = [1 2; 3 4];
B = [5 6; 7 8];
C = Math.LinearAlgebra.matmul(A, B);
C[0, 0] = 99;
println(A);
println(B);
println(C);
"""
    )
    assert matrix_values(result.env["A"]) == [[1, 2], [3, 4]]
    assert matrix_values(result.env["B"]) == [[5, 6], [7, 8]]
    assert matrix_values(result.env["C"]) == [[99, 22], [43, 50]]
    assert result.output == "[1 2; 3 4]\n[5 6; 7 8]\n[99 22; 43 50]\n"


def test_matmul_rejects_incompatible_shapes():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.matmul([1 2], [3 4]);")


def test_matmul_rejects_array():
    with pytest.raises(AetherTypeError):
        run_aether("int[] xs = []; Math.LinearAlgebra.matmul(xs, xs);")


def test_matmul_rejects_non_numeric():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.matmul([true false], [true; false]);")


def test_matmul_rejects_scalar():
    with pytest.raises(AetherTypeError):
        run_aether("Math.LinearAlgebra.matmul(1, [2]);")


def test_matmul_returns_correct_shape():
    result = run_aether(
        """
C = Math.LinearAlgebra.matmul([1 2 3; 4 5 6], [7 8; 9 10; 11 12]);
println(rows(C));
println(cols(C));
"""
    )
    assert result.env["C"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["C"]) == [[58, 64], [139, 154]]
    assert result.output == "2\n2\n"


def test_linear_algebra_zeros_matrix():
    result = run_aether("Z = Math.LinearAlgebra.zeros(2, 3); println(Z);")

    assert result.env["Z"].type_name == MatrixType("double", 2, 3)
    assert matrix_values(result.env["Z"]) == [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    assert result.output == "[0.0 0.0 0.0; 0.0 0.0 0.0]\n"


def test_linear_algebra_ones_matrix():
    result = run_aether("O = Math.LinearAlgebra.ones(3, 2); println(O);")

    assert result.env["O"].type_name == MatrixType("double", 3, 2)
    assert matrix_values(result.env["O"]) == [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
    assert result.output == "[1.0 1.0; 1.0 1.0; 1.0 1.0]\n"


def test_linear_algebra_zeros_and_ones_aliases_after_import():
    result = run_aether(
        """
import Math.LinearAlgebra
Z = zeros(1, 2);
O = ones(2, 1);
println(Z);
println(O);
"""
    )

    assert result.env["Z"].type_name == MatrixType("double", 1, 2)
    assert result.env["O"].type_name == MatrixType("double", 2, 1)
    assert result.output == "[0.0 0.0]\n[1.0; 1.0]\n"


def test_linear_algebra_matrix_factory_dimensions_must_be_int():
    with pytest.raises(AetherTypeError, match="expects integer dimensions"):
        run_aether("Math.LinearAlgebra.zeros(2.0, 3);")
    with pytest.raises(AetherTypeError, match="expects integer dimensions"):
        run_aether("Math.LinearAlgebra.ones(2, 3.0);")


def test_linear_algebra_matrix_factory_dimensions_must_be_positive():
    with pytest.raises(AetherTypeError, match="expects positive dimensions"):
        run_aether("Math.LinearAlgebra.zeros(0, 3);")
    with pytest.raises(AetherTypeError, match="expects positive dimensions"):
        run_aether("Math.LinearAlgebra.ones(2, -1);")


def test_math_linear_algebra_namespace_call():
    result = run_aether("println(Math.LinearAlgebra.inner([1 2 3], [4 5 6]));")
    assert result.output == "32\n"


def test_sqrt_basic():
    result = run_aether("x = sqrt(25); println(x);")
    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == pytest.approx(5.0)
    assert result.output == "5.0\n"


def test_sqrt_rejects_negative():
    with pytest.raises(AetherRuntimeError):
        run_aether("sqrt(-1);")


def test_sqrt_rejects_non_numeric():
    with pytest.raises(AetherTypeError):
        run_aether('sqrt("no");')


def test_stdlib_core_println_still_works():
    result = run_aether('println("stdlib");')
    assert result.output == "stdlib\n"


def test_stdlib_rows_cols_still_work():
    result = run_aether("A = [1 2; 3 4]; println(rows(A)); println(cols(A));")
    assert result.output == "2\n2\n"


def test_stdlib_sqrt_still_works():
    result = run_aether("println(sqrt(9));")
    assert result.output == "3.0\n"


def test_stdlib_linear_algebra_inner_still_works():
    result = run_aether("println(Math.LinearAlgebra.inner([1 2 3], [4 5 6]));")
    assert result.output == "32\n"


def test_stdlib_linear_algebra_norm_still_works():
    result = run_aether("println(Math.LinearAlgebra.norm([3 4]));")
    assert result.output == "5.0\n"
