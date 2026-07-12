# Aether Collections Design

## Status

This document records the intended collection semantics for `List<T>`,
`Array<T>`, and the boundary between collection literals and mathematical
literals. It is design documentation only.

`List<T>` exists as the dynamic collection type. `Array<T>` has active
implementation support as the fixed-size collection type. This document does
not require parser, typechecker, runtime, LLVM backend, or standard-library
changes in this step. The static-orientation `Vector<T, Row>` /
`Vector<T, Column>` literal semantics below are also design documentation only
and do not require changes to the existing `Vector`/`Matrix` implementation in
this step.

The detailed first-class mathematical design for vectors and matrices lives in
[`AETHER_VECTOR_MATRIX_DESIGN.md`](AETHER_VECTOR_MATRIX_DESIGN.md). This
document only records the collection side of that boundary.

The future common sorting semantics for lists and arrays are defined once in
[`AETHER_SEQUENCE_SORT_DESIGN.md`](AETHER_SEQUENCE_SORT_DESIGN.md). That
document is design-only and does not make array sorting available today.

The future dynamic-capacity contract for `List<T>`, including stable headers,
growth, `push`, `pop`, `insert`, `removeAt`, and `clear`, is defined in
[`AETHER_LIST_GROWTH_DESIGN.md`](AETHER_LIST_GROWTH_DESIGN.md). It is
design-only and does not mark those operations as implemented in the backend.

## Collection Roles

Aether separates general-purpose collections from mathematical vectors and
matrices:

- `List<T>` is the default general-purpose collection.
- `List<T>` has dynamic length.
- `Array<T>` is a fixed-size general-purpose collection.
- `Array<T>` is selected only when an explicit expected type requires it.
- `[ ... ]` remains reserved for mathematical `Vector<T, Orientation>` and
  `Matrix<T>` literals.
- `{ ... }` is the collection literal syntax shared by `List<T>` and the
  `Array<T>`.

## Mathematical Literal Boundary

General-purpose collections use braces. Mathematical vectors and matrices use
brackets:

```aether
xs = {1, 2, 3}; // List<int>

r = [1, 2, 3];      // Vector<int, Row>
c = [1; 2; 3];      // Vector<int, Column>
A = [1, 2; 3, 4];   // Matrix<int>
```

`Vector` orientation is part of the static type:

```aether
Vector<int, Row> r = [1, 2, 3];
Vector<int, Column> c = [1; 2; 3];
```

The orientation is not merely runtime metadata. A row vector and a column
vector with the same element type and length have different static types.

Bracket literals are target-typed mathematical literals. If a compatible
expected type exists, the literal is constructed as that type:

```aether
Vector<int, Row> r = [1, 2, 3];
Vector<int, Column> c = [1, 2, 3];

Matrix<int> A = [1, 2, 3]; // Matrix 1x3
Matrix<int> B = [1; 2; 3]; // Matrix 3x1
```

If there is no expected type, Aether infers by literal form:

- `{...}` infers `List<T>`.
- `[a, b, c]` infers `Vector<T, Row>`.
- `[a; b; c]` infers `Vector<T, Column>`.
- `[a, b; c, d]` infers `Matrix<T>`.

Precedence rule: a compatible expected type wins. Without one, the syntactic
form determines the mathematical container.

Future vector/matrix multiplication must preserve this orientation distinction:

```aether
[1, 2, 3] * [4; 5; 6] // Vector<T, Row> * Vector<T, Column> -> T
[1; 2; 3] * [4, 5, 6] // Vector<T, Column> * Vector<T, Row> -> Matrix<T>
```

These expressions are not equivalent: row-by-column is an inner product, while
column-by-row is an outer product.

## List<T>

`List<T>` is dynamic: operations such as `push`, `pop`, `insert`, `remove_at`,
and `clear` may change the container length, while `reverse` and `sort` change
only element order. In particular, the future shared `sort()` contract
preserves both length and capacity.

`List<T>` follows the mutable-reference and aliasing rules documented in
[`MUTABLE_AGGREGATES.md`](../compiler/MUTABLE_AGGREGATES.md): assigning a list
copies the reference, not the elements, and mutating through one alias is
observable through other aliases to the same list object.

When a collection literal has no expected type, Aether infers `List<T>`:

```aether
xs = {1, 2, 3}; // List<int>
ys = {1.0, 2.0}; // List<double>
```

This makes `List<T>` the default collection for local inference and unannotated
collection literals.

## Array<T>

`Array<T>` is fixed-size: after construction, its length cannot change.
Index assignment may update existing elements, but operations that add or remove
elements are not part of the array model.

Like `List<T>`, `Array<T>` is a mutable aggregate reference. Assignment aliases
the same array object rather than copying elements; future indexed assignment
must preserve that observable aliasing behavior.

`Array<T>` is not inferred from an unannotated literal. A brace literal
produces `Array<T>` only when the expected type is explicitly `Array<T>`:

```aether
Array<int> xs = {1, 2, 3}; // Array<int>
```

`Array<T>` and `List<T>` are distinct types. Aether should not implicitly
convert between them merely because their element types match.

## Brace Literal Typing

Brace literals are target-typed collection literals.

Rules:

- With no expected type, `{...}` infers `List<T>`.
- With expected type `List<T>`, `{...}` produces `List<T>`.
- With expected type `Array<T>`, `{...}` produces `Array<T>`.
- All elements must have one homogeneous element type after ordinary assignment
  compatibility and numeric widening rules are applied.
- Narrowing remains invalid. For example, `Array<int> xs = {1, 2.5};` is an
  error.
- The empty literal `{}` requires an expected type or an explicit annotation.

Examples:

```aether
xs = {1, 2, 3};              // List<int>
List<int> ys = {1, 2, 3};    // List<int>
Array<int> zs = {1, 2, 3};   // Array<int>

values = {1.0, 2.0};         // List<double>
mixed = {1, 2.5};            // List<double>

List<int> emptyList = {};    // valid: expected type is List<int>
Array<int> emptyArray = {};  // valid: expected type is Array<int>
empty = {};                  // error: cannot infer element/container type
```

The expected type may come from an explicit local declaration, assignment to an
existing typed variable, a function argument, a function return, or a typed
field initializer.

## Local Inference Remains Static

Local inference gives a variable a fixed type when the variable is first
introduced. Later assignments must be compatible with that fixed type:

```aether
x = 3;   // int
x = 5.3; // error
```

The same rule applies to collections:

```aether
xs = {1, 2, 3};   // List<int>
xs = {4, 5};      // valid
xs = {1.0, 2.0};  // error: List<double> is not assignable to List<int>

ys = {1.0, 2.0};  // List<double>
```

`Array<T>` follows the same static assignment model. Once a variable has type
`Array<int>`, later assignments must also be compatible with
`Array<int>`; a `List<int>` literal without an `Array<int>` expected type is not
an implicit replacement for that array type.

## Explicit Non-Goals For This Design Step

This design note does not implement:

- parser changes
- typechecker changes
- runtime changes
- LLVM backend changes
- new collection methods or builtins
