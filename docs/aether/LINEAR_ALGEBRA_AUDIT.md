# Math.LinearAlgebra Audit

## Scope

This audit compares `src/aether/stdlib/math/linear_algebra.py` and the
examples in `examples/linear_algebra/` against the intended first-class
semantics documented for:

- `Vector<T, Row>`
- `Vector<T, Column>`
- `Matrix<T>`

This document is documentation only. It does not define implementation changes.

## Semantic Target

The target model is:

- Vector orientation is part of the static type.
- `Matrix<T>` is a mathematical rectangular value, not `List<List<T>>`.
- `Vector<T, Row> * Vector<T, Column> -> T`.
- `Vector<T, Column> * Vector<T, Row> -> Matrix<T>`.
- `transpose(Vector<T, Row>) -> Vector<T, Column>`.
- `transpose(Vector<T, Column>) -> Vector<T, Row>`.
- `transpose(Matrix<T>) -> Matrix<T>`.

## Current Type Model Observed

`linear_algebra.py` imports and uses these mathematical type forms:

- `VectorType(element_type, length, orientation=None)`.
- `TransposeVectorType(element_type, length)`.
- `MatrixType(element_type, rows, cols, vector=False)`.
- `ArrayType(element_type)` for matrix rows in runtime values.

Important observations:

- `VectorType` already has an `orientation` field, but most
  `Math.LinearAlgebra` return paths construct `VectorType(...)` without
  preserving or setting orientation.
- `TransposeVectorType` is still used as the operational row-vector wrapper
  produced by `transpose(VectorType)`.
- `MatrixType` carries `rows`, `cols`, and a legacy `vector` flag. Runtime
  matrix values are represented as a list of row `AetherValue(ArrayType(...))`
  values.
- Several helpers accept "vector-like matrices" where `MatrixType.vector` is
  true or runtime shape is `1xN` / `Nx1`. That compatibility is useful for
  legacy code, but it is not the same as first-class oriented vectors.

## Existing Functions

| Function | Current behavior | Current return shape/type | New-semantics status |
| --- | --- | --- | --- |
| `transpose` | Delegates to `_transpose_value`. `VectorType` becomes `TransposeVectorType`; `TransposeVectorType` unwraps to `VectorType`; `MatrixType` swaps rows/cols. | `TransposeVectorType`, `VectorType`, or `MatrixType`. | Must migrate first. It should flip `VectorType.orientation` instead of producing `TransposeVectorType`. |
| `conjtranspose` | Same shape behavior as `transpose`, with conjugation for complex values. | `TransposeVectorType`, `VectorType`, or `MatrixType`. | Must follow the same orientation migration as `transpose`; matrix behavior can mostly stay. |
| `inner` | Accepts `VectorType`, `TransposeVectorType`, or a `MatrixType` that is runtime row/column vector-like. Ignores orientation except unwrapping `TransposeVectorType`. Uses conjugation only when the left scalar value is complex. | Numeric scalar with promoted type. | Semantics should be clarified as orientation-insensitive vector inner product, or replaced/limited by `Row * Column`. Current acceptance of matrices as vectors is legacy. |
| `norm` | Accepts the same vector inputs as `inner`; computes Euclidean norm. | `double`. | Can mostly stay if defined for any oriented vector. Legacy matrix-as-vector acceptance should be reconsidered. |
| `matmul` | Supports `MatrixType * VectorType` specially, otherwise requires both operands to be `MatrixType`. It does not accept `VectorType * VectorType`, `TransposeVectorType * VectorType`, or `VectorType * TransposeVectorType` directly through this builtin. | `VectorType` for matrix-vector, `MatrixType` for matrix-matrix. | Must be redesigned around oriented vector operands. Current builtin only covers part of the target multiplication matrix. |
| `solve` | Requires matrix left operand. Right operand may be `VectorType` or `MatrixType`; vectors are normalized to column matrices. It also treats `1xN` and `Nx1` matrices as vector-like RHS values. | `VectorType` for vector-like RHS with one solution column, else `MatrixType`. | Keep numeric algorithm, but RHS/result orientation must become explicit. Column RHS should return `Vector<T, Column>`; row-vector RHS should probably be rejected or explicitly transposed. |
| `eig` | Requires square numeric `MatrixType`; returns eigenvector matrix `S` and diagonal matrix `D`. | `TupleType(MatrixType, MatrixType)`. | Can mostly stay; depends on matrix semantics and matrix multiplication contracts for reconstruction examples. |
| `SVD` | Requires numeric `MatrixType`; returns full `U`, `S`, `V`. | `TupleType(MatrixType, MatrixType, MatrixType)`. | Can mostly stay; reconstruction depends on `transpose`/`conjtranspose` and matrix multiplication semantics. |
| `LU` | Requires square numeric `MatrixType`; returns `P`, `L`, `U`. | `TupleType(MatrixType, MatrixType, MatrixType)`. | Can mostly stay; depends on matrix-only semantics. |
| `LDU` | Requires square numeric `MatrixType`; returns `P`, `L`, `D`, `U`. | `TupleType(MatrixType, MatrixType, MatrixType, MatrixType)`. | Can mostly stay; depends on matrix-only semantics. |
| `zeros` | Builds a double matrix filled with zero. Dimensions must be positive integers. | `MatrixType("double", rows, cols)`. | Can stay as a matrix factory. |
| `ones` | Builds a double matrix filled with one. Dimensions must be positive integers. | `MatrixType("double", rows, cols)`. | Can stay as a matrix factory. |
| `N` | Computes null-space basis via SciPy, returned as basis columns. | `MatrixType(result_element_type, matrix.cols, None)`. | Can stay matrix-oriented; result shape should remain matrix basis columns. |
| `R` | Computes column-space basis via SciPy, returned as basis columns. | `MatrixType(result_element_type, matrix.rows, None)`. | Can stay matrix-oriented; result shape should remain matrix basis columns. |
| `rank` | Computes numeric matrix rank. | `int`. | Can stay. |

## Current Helper Semantics

Helpers that encode old semantics:

- `_transpose_value` creates and unwraps `TransposeVectorType`.
- `_transpose_like_type` returns `TransposeVectorType` for `VectorType` and
  `VectorType` for `TransposeVectorType`.
- `_vector_elements` accepts `VectorType`, `TransposeVectorType`, and
  `MatrixType` values with `1xN` / `Nx1` runtime shape.
- `_require_numeric_vector_type` accepts both `VectorType` and
  `TransposeVectorType`, then falls back to vector-like `MatrixType`.
- `_matrix_vector_multiply` returns a `VectorType` without setting an
  orientation.
- `_vector_to_column_matrix` treats every `VectorType` as a column RHS.
- `_is_runtime_vector_like`, `_normalized_rhs_type_shape`, and `_vector_length`
  preserve legacy compatibility with `MatrixType.vector` and `1xN` / `Nx1`
  matrices.
- `_numeric_array_to_vector_value` returns `VectorType(..., orientation=None)`.

Helpers that can mostly survive with updated type construction:

- `_runtime_shape`.
- `_matrix_to_numeric_array`.
- `_numeric_array_to_matrix_value`.
- `_clean_numeric_array`.
- `_array_element_type`.
- `_decomposition_result_element_type`.
- `_promote_numeric_types`.
- `_coerced_numeric_result`.
- `_require_numeric_matrix_type`.

## Dependencies On Old `VectorType`

The current module depends on `VectorType` as an unoriented or weakly oriented
vector in these ways:

- `inner` and `norm` treat any `VectorType` as a plain sequence of numeric
  elements.
- `matmul(MatrixType, VectorType)` assumes the vector is a compatible column
  vector, regardless of `VectorType.orientation`.
- `solve(MatrixType, VectorType)` normalizes any vector into an `Nx1` column
  matrix.
- Matrix-vector conversion helpers create `VectorType` without specifying
  `"row"` or `"column"`.
- Type inference returns `VectorType(..., rows)` or `VectorType(..., cols)`
  without orientation for `matmul` and `solve`.

Under the target model, each of these should explicitly preserve or require
orientation.

## Dependencies On Old `TransposeVectorType`

`TransposeVectorType` is still a semantic participant, not just a compatibility
alias:

- `transpose(VectorType)` returns `TransposeVectorType`.
- `transpose(TransposeVectorType)` returns the wrapped `VectorType`.
- `conjtranspose` mirrors this behavior.
- `inner` and `norm` accept it by unwrapping `value.value`.
- Type inference accepts it in `_require_numeric_vector_type`.

This conflicts with the target model because row/column state should live in
`VectorType.orientation`, not in a separate transposed wrapper type. The wrapper
also makes `transpose` depend on value nesting instead of a static orientation
flip.

## What Must Migrate

The following should move to `Vector<T, Row>` / `Vector<T, Column>` semantics:

- `transpose` and `conjtranspose` return types and runtime values.
- Every `VectorType(...)` construction in this module should set or preserve
  orientation when the result is a vector.
- `inner` should decide whether it is a general vector operation or a
  compatibility alias for `Row * Column`.
- `norm` should operate on oriented vectors directly and avoid using matrix
  shape as vector identity unless compatibility is intentionally retained.
- `matmul` should support the target combinations:
  - row vector times column vector returns scalar.
  - column vector times row vector returns matrix.
  - matrix times column vector returns column vector.
  - row vector times matrix returns row vector.
  - matrix times matrix returns matrix.
- `solve` should treat RHS orientation explicitly and return an oriented vector
  when the RHS is a vector.
- Any public examples that rely on implicit vector-like matrices or orientation
  erasure should be updated after the implementation migrates.

## What Can Be Preserved

These behaviors are compatible with the target model:

- Numeric promotion across `int`, `float`, `double`, and `complex`.
- Matrix rectangularity and shape checks.
- Matrix transpose for `MatrixType`.
- Matrix factories `zeros` and `ones`.
- Matrix-only decomposition algorithms: `eig`, `SVD`, `LU`, `LDU`.
- Matrix subspace/rank operations: `N`, `R`, `rank`.
- SciPy/NumPy-backed algorithms as runtime implementation details, provided
  their type boundaries are first-class Aether vector/matrix values.

## Examples Audit

Files reviewed:

- `examples/linear_algebra/basic_operations.ae`
- `examples/linear_algebra/primes_check.ae`
- `examples/linear_algebra/primes_advanced.ae`

Observed compatibility points:

- `basic_operations.ae` uses `A = [1 2; 3 4]`, `transpose(A)`, `U = [1 2]`,
  `V = [3; 4]`, and `matmul(U, V)`. Under the target semantics, `U` should be a
  row vector and `V` a column vector; `matmul(U, V)` should return a scalar if
  `matmul` is kept as a function for vector multiplication.
- `basic_operations.ae` iterates over `V`. That depends on vector iteration,
  not linear algebra itself, but the vector orientation should remain visible
  in the value type.
- `primes_check.ae` uses `A = [3 2; 1 0; 0 0]`, `b = [5; 3; 0]`, `A \ b`,
  `N(A)`, and `R(A)`. The solve RHS is naturally a column vector.
- `primes_advanced.ae` uses column vectors `n` and `p`, a matrix from
  `ones(12, 2)`, least-squares solve `z = A \ p`, matrix-vector expression
  `A*z`, and `norm(p - A*z)^2`. This should continue to typecheck if `p`,
  `z`, and `A*z` are all column vectors.

The examples are conceptually aligned with the new model, but they rely on the
implementation to infer and preserve vector orientation consistently.

## Backend/LLVM Exposure Gate

Before exposing these operations through LLVM/runtime contracts, the following
should be true:

- `VectorType` orientation is required at all public vector boundaries.
- `TransposeVectorType` is removed from public stdlib results or made a
  temporary parser/typechecker compatibility shim only.
- Matrix values are lowered as first-class rectangular matrix values, not as
  nested list semantics.
- `matmul` and `*` share one orientation-aware shape contract.
- Runtime helpers preserve orientation in returned vector values.
- Error messages distinguish row vectors, column vectors, and matrices.
- Tests cover `Row * Column`, `Column * Row`, `Matrix * Column`,
  `Row * Matrix`, and invalid orientation pairs.
- `solve` has explicit RHS orientation rules and stable result orientation.

## Risks

- Silent orientation loss: current `VectorType(...)` construction often leaves
  orientation as `None`.
- Compatibility ambiguity: `MatrixType.vector` and `1xN` / `Nx1` matrices can
  mask whether a value is truly a vector or a matrix.
- API split: `matmul` currently implements a narrower set of cases than the
  `*` operator paths in the interpreter/typechecker.
- `TransposeVectorType` nesting may leak into runtime values and formatting
  while the new model expects a flat oriented vector value.
- Existing examples and tests may pass because matrices are accepted as
  vector-like, hiding missing vector orientation.
- LLVM lowering could bake in the wrong ABI if it sees vectors as generic
  arrays or transposed wrappers before the semantic cleanup is complete.
- Complex inner-product behavior should be specified exactly before migration;
  the current implementation conjugates left elements conditionally by runtime
  Python value type.

## Migration Plan

### Phase 1: Transpose Orientation

Status: Implemented.

- Change `transpose` and `conjtranspose` type inference to return
  `VectorType(element, length, flipped_orientation)` for vector inputs.
- Change runtime transpose to return an oriented `VectorType`, not a
  `TransposeVectorType`.
- Decide the compatibility story for existing `TransposeVectorType` values:
  reject, normalize, or keep only as a temporary internal shim. Implemented as
  rejection for `transpose` and `conjtranspose`.

### Phase 2: `inner` and `norm`

- Make `norm` accept `VectorType` with `row` or `column` orientation and return
  `double`.
- Decide whether `inner(u, v)` remains orientation-insensitive or becomes an
  explicit `Row, Column` operation.
- Remove or quarantine implicit matrix-as-vector acceptance from public type
  inference.

### Phase 3: `matmul`

- Implement the full orientation-aware multiplication table.
- Preserve result orientation:
  - `Matrix * Column -> Column`
  - `Row * Matrix -> Row`
- Return scalar for `Row * Column`.
- Return matrix for `Column * Row`.
- Reject `Row * Row`, `Column * Column`, `Column * Matrix`, and
  `Matrix * Row` unless explicitly designed later.

### Phase 4: `solve`, `eig`, `SVD`, `LU`, `LDU`

- Update `solve` to require or normalize RHS orientation deliberately.
- Return column-vector solutions for column-vector RHS values.
- Keep matrix RHS returning matrix solutions.
- Recheck decomposition return contracts after matrix multiplication and
  transpose semantics are stable.
- Keep matrix-only decompositions matrix-only.

### Phase 5: LLVM/Runtime Integration

- Lower oriented vectors and matrices through explicit runtime/IR types.
- Ensure runtime calls receive orientation and shape metadata where needed.
- Align LLVM ABI with the final first-class vector/matrix representation.
- Add backend tests only after the interpreter/typechecker semantics are stable.
