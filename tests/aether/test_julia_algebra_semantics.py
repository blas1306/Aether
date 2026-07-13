from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherTypeError
from aether.runner import run_aether
from aether.types import MatrixType, VectorType


def values(vector):
    return [element.value for element in vector.value]


def matrix_values(matrix):
    return [[element.value for element in row.value] for row in matrix.value]


def test_size_reports_scalar_as_zero_dimensional_shape() -> None:
    result = run_aether(
        """
s = size(5);
println(s);
println(length(s));
"""
    )

    assert result.env["s"].type_name == VectorType("int", 0)
    assert values(result.env["s"]) == []
    assert result.output == "[]\n0\n"


def test_size_reports_vector_as_one_dimensional_and_indexable() -> None:
    result = run_aether(
        """
s = size([1, 2, 3]);
n = s[1];
ok = s == [3];
println(s);
println(n);
println(ok);
"""
    )

    assert result.env["s"].type_name == VectorType("int", 1)
    assert values(result.env["s"]) == [3]
    assert result.env["n"].value == 3
    assert result.env["ok"].value is True
    assert result.output == "[3]\n3\ntrue\n"


def test_size_reports_matrix_shape_and_rows_cols_delegate_to_it() -> None:
    result = run_aether(
        """
A = [1 2 3 4; 5 6 7 8; 9 10 11 12];
s = size(A);
m = s[1];
n = s[2];
ok = s == [3, 4];
println(s);
println(m);
println(n);
println(rows(A));
println(cols(A));
println(columns(A));
println(ok);
"""
    )

    assert result.env["s"].type_name == VectorType("int", 2)
    assert values(result.env["s"]) == [3, 4]
    assert result.env["m"].value == 3
    assert result.env["n"].value == 4
    assert result.env["ok"].value is True
    assert result.output == "[3 4]\n3\n4\n3\n4\n4\ntrue\n"


def test_size_preserves_transposed_vector_identity() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
v = [1, 2, 3];
t = Math.LinearAlgebra.transpose(v);
s = size(t);
println(s);
println(s[1]);
"""
    )

    assert result.env["t"].type_name == VectorType("int", 3, "column")
    assert result.env["t"].type_name.orientation == "column"
    assert result.env["s"].type_name == VectorType("int", 1)
    assert values(result.env["s"]) == [3]
    assert result.output == "[3]\n3\n"


def test_size_scalar_shape_has_no_dimension_index() -> None:
    with pytest.raises(AetherRuntimeError):
        run_aether("println(size(5)[1]);")


def test_bracket_concat_horizontally_combines_matrix_blocks() -> None:
    result = run_aether(
        """
A = [1 2; 3 4];
B = [5 6; 7 8];
C = [A B];
println(C);
"""
    )

    assert result.env["C"].type_name == MatrixType("int", 2, 4)
    assert matrix_values(result.env["C"]) == [[1, 2, 5, 6], [3, 4, 7, 8]]
    assert result.output == "[1 2 5 6; 3 4 7 8]\n"


def test_bracket_concat_vertically_combines_matrix_blocks() -> None:
    result = run_aether(
        """
A = [1 2; 3 4];
B = [5 6; 7 8];
C = [A; B];
println(C);
"""
    )

    assert result.env["C"].type_name == MatrixType("int", 4, 2)
    assert matrix_values(result.env["C"]) == [[1, 2], [3, 4], [5, 6], [7, 8]]
    assert result.output == "[1 2; 3 4; 5 6; 7 8]\n"


def test_bracket_concat_combines_matrix_block_grid() -> None:
    result = run_aether(
        """
A = [1 2; 3 4];
B = [5; 6];
C = [7 8];
D = [9];
E = [A B; C D];
println(E);
"""
    )

    assert result.env["E"].type_name == MatrixType("int", 3, 3)
    assert matrix_values(result.env["E"]) == [[1, 2, 5], [3, 4, 6], [7, 8, 9]]
    assert result.output == "[1 2 5; 3 4 6; 7 8 9]\n"


def test_bracket_concat_row_vectors_horizontally_combines_columns() -> None:
    result = run_aether(
        """
v = [1, 2];
w = [3, 4];
C = [v w];
println(C);
"""
    )

    assert result.env["C"].type_name == MatrixType("int", 1, 4)
    assert matrix_values(result.env["C"]) == [[1, 2, 3, 4]]
    assert result.output == "[1 2 3 4]\n"


def test_bracket_concat_row_vectors_vertically_returns_matrix() -> None:
    result = run_aether(
        """
v = [1, 2];
w = [3, 4];
c = [v; w];
println(c);
"""
    )

    assert result.env["c"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["c"]) == [[1, 2], [3, 4]]
    assert result.output == "[1 2; 3 4]\n"


def test_bracket_concat_promotes_numeric_element_types() -> None:
    result = run_aether(
        """
A = [1 2];
B = [3.5 4.5];
C = [A; B];
println(C);
"""
    )

    assert result.env["C"].type_name == MatrixType("double", 2, 2)
    assert matrix_values(result.env["C"]) == [[1.0, 2.0], [3.5, 4.5]]
    assert result.output == "[1.0 2.0; 3.5 4.5]\n"


def test_bracket_concat_rejects_incompatible_block_dimensions() -> None:
    with pytest.raises(AetherTypeError, match="same number of rows"):
        run_aether("A = [1 2; 3 4]; B = [5 6]; C = [A B];")
    with pytest.raises(AetherTypeError, match="same number of columns"):
        run_aether("A = [1 2]; B = [3 4 5]; C = [A; B];")


def test_bracket_concat_rejects_single_or_comma_separated_matrix_blocks() -> None:
    with pytest.raises(AetherTypeError, match="',' is not supported"):
        run_aether("A = [1 2; 3 4]; C = [A];")
    with pytest.raises(AetherTypeError, match="',' is not supported"):
        run_aether("A = [1 2; 3 4]; B = [5 6; 7 8]; C = [A, B];")


def test_vectors_are_1d_values_and_simple_indexing_returns_scalar() -> None:
    result = run_aether("v = [1, 2, 3]; a = v[1]; println(a);")

    assert result.env["v"].type_name == VectorType("int", 3)
    assert result.env["a"].type_name == "int"
    assert result.output == "1\n"


def test_transpose_vector_flips_orientation_and_double_transpose_returns_vector() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
v = [1, 2, 3];
t = Math.LinearAlgebra.transpose(v);
w = Math.LinearAlgebra.transpose(t);
a = t[1];
println(a);
"""
    )

    assert result.env["t"].type_name == VectorType("int", 3, "column")
    assert result.env["t"].type_name.orientation == "column"
    assert result.env["w"].type_name == VectorType("int", 3, "row")
    assert result.env["w"].type_name.orientation == "row"
    assert result.env["a"].type_name == "int"
    assert result.output == "1\n"


def test_star_accepts_matrix_column_product() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2; 3 4];
y = A * [5; 6];
"""
    )

    assert result.env["y"].type_name == VectorType("int", 2, "column")
    assert values(result.env["y"]) == [17, 39]


def test_star_accepts_row_column_and_column_row_oriented_vector_products() -> None:
    outer = run_aether("import Math.LinearAlgebra\nv = [1, 2, 3]; w = [4, 5, 6]; x = Math.LinearAlgebra.transpose(v) * w;")
    result = run_aether("import Math.LinearAlgebra\nv = [1, 2, 3]; w = [4, 5, 6]; x = v * Math.LinearAlgebra.transpose(w);")

    assert outer.env["x"].type_name == MatrixType("int", 3, 3)
    assert matrix_values(outer.env["x"]) == [[4, 5, 6], [8, 10, 12], [12, 15, 18]]
    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32


def test_vector_star_vector_accepts_only_row_column_dot_product() -> None:
    result = run_aether("r = [1, 2, 3]; c = [4; 5; 6]; x = r * c;")

    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32

    with pytest.raises(AetherTypeError, match="Vector<Row> \\* Vector<Column>"):
        run_aether("v = [1, 2, 3]; w = [4, 5, 6]; x = v * w;")


def test_dot_star_is_elementwise_for_vectors_and_matrices() -> None:
    result = run_aether(
        """
v = [1, 2, 3] .* [4, 5, 6];
A = [1 2; 3 4] .* [5 6; 7 8];
"""
    )

    assert result.env["v"].type_name == VectorType("int", 3)
    assert values(result.env["v"]) == [4, 10, 18]
    assert result.env["A"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["A"]) == [[5, 12], [21, 32]]


def test_plus_minus_work_for_vectors_and_matrices() -> None:
    result = run_aether(
        """
v = [4, 5, 6] - [1, 2, 3];
w = [1, 2, 3] + [4, 5, 6];
A = [5 6; 7 8] - [1 2; 3 4];
B = [1 2; 3 4] + [5 6; 7 8];
"""
    )

    assert result.env["v"].type_name == VectorType("int", 3)
    assert values(result.env["v"]) == [3, 3, 3]
    assert values(result.env["w"]) == [5, 7, 9]
    assert matrix_values(result.env["A"]) == [[4, 4], [4, 4]]
    assert matrix_values(result.env["B"]) == [[6, 8], [10, 12]]


def test_dot_plus_minus_are_elementwise_and_broadcast_scalars() -> None:
    result = run_aether(
        """
v = [1, 2, 3] .+ 10;
w = 10 .- [1, 2, 3];
A = [1 2; 3 4] .+ 1;
B = 10 .- [1 2; 3 4];
"""
    )

    assert values(result.env["v"]) == [11, 12, 13]
    assert values(result.env["w"]) == [9, 8, 7]
    assert matrix_values(result.env["A"]) == [[2, 3], [4, 5]]
    assert matrix_values(result.env["B"]) == [[9, 8], [7, 6]]


def test_vector_subtraction_accepts_matmul_matrix_vector_product() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2; 3 4];
z = [5; 6];
p = [17; 39];
err = p - Math.LinearAlgebra.matmul(A, z);
"""
    )

    assert values(result.env["err"]) == [0, 0]


def test_matrix_indexing_slices_lower_or_preserve_dimension_like_julia() -> None:
    result = run_aether(
        """
A = [1 2 3; 4 5 6; 7 8 9];
a = A[1, 2];
col = A[:, 1];
row = A[1, :];
part = A[1:2, 2];
whole = A[:, :];
"""
    )

    assert result.env["a"].type_name == "int"
    assert result.env["a"].value == 2
    assert result.env["col"].type_name == VectorType("int", 3)
    assert values(result.env["col"]) == [1, 4, 7]
    assert result.env["row"].type_name == VectorType("int", 3)
    assert values(result.env["row"]) == [1, 2, 3]
    assert result.env["part"].type_name == VectorType("int", 2)
    assert values(result.env["part"]) == [2, 5]
    assert result.env["whole"].type_name == MatrixType("int", 3, 3)
    assert matrix_values(result.env["whole"]) == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
