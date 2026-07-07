# Aether Collections Design

## Status

This document records the intended collection semantics for `List<T>` and the
future `Array<T>` type. It is design documentation only.

`List<T>` already exists. `Array<T>` is reserved for a later implementation and
this document does not require parser, typechecker, runtime, LLVM backend, or
standard-library changes yet.

## Collection Roles

Aether separates general-purpose collections from mathematical vectors and
matrices:

- `List<T>` is the default general-purpose collection.
- `List<T>` has dynamic length.
- `Array<T>` will be a fixed-size general-purpose collection.
- `Array<T>` will be selected only when an explicit expected type requires it.
- `[ ... ]` remains reserved for mathematical `Vector<T>` and `Matrix<T>`
  literals.
- `{ ... }` is the collection literal syntax shared by `List<T>` and the
  future `Array<T>`.

## List<T>

`List<T>` is dynamic: operations such as `push`, `pop`, `insert`, `remove_at`,
`clear`, `reverse`, and `sort` may change the container length or order.

When a collection literal has no expected type, Aether infers `List<T>`:

```aether
xs = {1, 2, 3}; // List<int>
ys = {1.0, 2.0}; // List<double>
```

This makes `List<T>` the default collection for local inference and unannotated
collection literals.

## Future Array<T>

`Array<T>` will be fixed-size: after construction, its length cannot change.
Index assignment may update existing elements, but operations that add or remove
elements are not part of the array model.

`Array<T>` will not be inferred from an unannotated literal. A brace literal
will produce `Array<T>` only when the expected type is explicitly `Array<T>`:

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
Array<int> zs = {1, 2, 3};   // future Array<int>

values = {1.0, 2.0};         // List<double>
mixed = {1, 2.5};            // List<double>

List<int> emptyList = {};    // valid: expected type is List<int>
Array<int> emptyArray = {};  // future valid: expected type is Array<int>
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

Future `Array<T>` should follow the same static assignment model. Once a
variable has type `Array<int>`, later assignments must also be compatible with
`Array<int>`; a `List<int>` literal without an `Array<int>` expected type is not
an implicit replacement for that array type.

## Explicit Non-Goals For This Design Step

This design note does not implement:

- `Array<T>`
- parser changes
- typechecker changes
- runtime changes
- LLVM backend changes
- new collection methods or builtins
