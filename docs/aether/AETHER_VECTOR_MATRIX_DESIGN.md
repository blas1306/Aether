# Aether Vector/Matrix Design

## Status

This document defines the intended operational design for `Vector<T,
Orientation>` and `Matrix<T>` as first-class mathematical types in Aether. It
is design documentation only. It does not require parser, typechecker, runtime,
LLVM, or standard-library changes in this step.

## Motivation

Aether should keep general-purpose collections separate from mathematical
objects:

- `List<T>` is the dynamic, general-purpose collection type.
- `Array<T>` is the fixed-size, general-purpose collection type.
- `Vector<T, Orientation>` and `Matrix<T>` are mathematical objects.

`Matrix<T>` is not `List<List<T>>`. A nested list can represent ragged or
irregular data, while a matrix must be rectangular and must support
matrix-specific dimensions and operations.

`Vector<T, Row>` and `Vector<T, Column>` are not equivalent. They may contain
the same element type and the same number of elements, but their orientation is
part of their static type and changes the meaning of multiplication,
transposition, and shape compatibility.

## Types

The first-class mathematical types are:

```aether
Vector<T, Row>
Vector<T, Column>
Matrix<T>
```

The orientation of a vector is part of the static type. A value of type
`Vector<T, Row>` is not assignable to `Vector<T, Column>` merely because its
length and element type match.

## Literals

### Without Expected Type

When no expected type is available, Aether infers the container from the
literal form:

```aether
xs = {1, 2, 3};       // List<int>
r  = [1, 2, 3];       // Vector<int, Row>
c  = [1; 2; 3];       // Vector<int, Column>
A  = [1, 2; 3, 4];    // Matrix<int>
```

Braces are collection literals. Brackets are mathematical literals.

### With Expected Type

If an expected mathematical type is available, the expected type wins when it
is compatible with the literal contents:

```aether
Vector<int, Row> r = [1, 2, 3];
Vector<int, Column> c = [1, 2, 3];

Matrix<int> A = [1, 2, 3]; // 1x3
Matrix<int> B = [1; 2; 3]; // 3x1
```

In particular, `[1, 2, 3]` may construct either `Vector<int, Row>` or
`Vector<int, Column>` when an explicit expected vector type is present and the
literal is otherwise compatible.

Explicit orientation conflicts should be errors unless Aether later adds an
explicit conversion form:

```aether
Vector<int, Row> r = [1; 2; 3]; // error: orientation conflict
```

This keeps accidental row/column transposition visible at the type boundary.
A future explicit conversion or transpose operation may provide a deliberate
way to change orientation.

### Separators

Commas separate elements within one row:

```aether
[1, 2, 3]
```

Semicolons separate rows:

```aether
[1, 2; 3, 4]
```

For vector literals with an explicit expected type, `[1, 2, 3]` may construct
either a row vector or a column vector according to the expected type. Without
an expected type, `[1, 2, 3]` is `Vector<T, Row>` and `[1; 2; 3]` is
`Vector<T, Column>`.

## Homogeneity

All elements of a `Vector<T, Orientation>` or `Matrix<T>` must have a
homogeneous element type after applying the same assignment compatibility and
numeric promotion rules used elsewhere in Aether.

For example, a `Matrix<double>` may accept `int` and `double` elements when
ordinary numeric widening permits it. A `Matrix<int>` must reject a `double`
element when that would require narrowing.

## Dimensions

A vector has a `length`.

A matrix has `rows` and `columns`.

Matrices must be rectangular: every row must have the same number of columns.
Ragged matrix literals are errors:

```aether
[1, 2; 3] // error: rows have different lengths
```

## Future Indexing

The intended mathematical indexing forms are:

```aether
v[i]
A[i, j]
```

`A[i][j]` is not matrix indexing. That form belongs to nested structures such
as `List<List<T>>`, `Array<Array<T>>`, or similar container compositions.
`Matrix<T>` uses two-dimensional indexing because it is a rectangular
mathematical object, not a list of rows.

## Future Operations

Matrix/vector multiplication should preserve static orientation and shape:

```aether
Vector<T, Row> * Vector<T, Column> -> T
Vector<T, Column> * Vector<T, Row> -> Matrix<T>
Matrix<T> * Matrix<T> -> Matrix<T>
Matrix<T> * Vector<T, Column> -> Vector<T, Column>
Vector<T, Row> * Matrix<T> -> Vector<T, Row>
```

Expected errors:

```aether
Vector<T, Row> * Vector<T, Row>       // error
Vector<T, Column> * Vector<T, Column> // error
Vector<T, Column> * Matrix<T>         // error, unless explicitly designed later
Matrix<T> * Vector<T, Row>            // error, unless explicitly designed later
```

These rules make row-by-column multiplication an inner product and
column-by-row multiplication an outer product. They are intentionally not
interchangeable.

## Transpose

Transpose should preserve the element type and flip vector orientation:

```aether
r.transpose(); // Vector<T, Column>
c.transpose(); // Vector<T, Row>
A.transpose(); // Matrix<T>
```

For matrices, transpose swaps rows and columns. For vectors, transpose changes
orientation without changing length.

## Relationship With Array/List

`Vector<T, Orientation>` and `Matrix<T>` may use contiguous storage internally.
That is an implementation detail, not their semantic identity.

Semantically, vectors and matrices are neither arrays nor lists:

- `List<T>` is a dynamic general-purpose collection.
- `Array<T>` is a fixed-size general-purpose collection.
- `Vector<T, Orientation>` is an oriented mathematical vector.
- `Matrix<T>` is a rectangular mathematical matrix.

`List<List<T>>` can represent irregular nested data. `Matrix<T>` must be
rectangular and mathematically operable.

Aether should not implicitly convert between general-purpose collections and
mathematical objects merely because their element types match.

## Future Runtime

Aether may use a specialized runtime representation for vectors and matrices.
Heavy operations may be delegated to a runtime library or to an optimized
backend.

This document does not implement that runtime. It only fixes the semantic
target so future parser, typechecker, IR, LLVM, runtime, and standard-library
work can line up behind the same model.
