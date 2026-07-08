# Mutable Aggregate Semantics

## Status

This document records the intended mutability and aliasing semantics for
aggregate values in Aether. It is design documentation only. It does not require
parser, typechecker, IR, SSA, LLVM, runtime, or standard-library changes in this
step.

## Mutable Aggregate Types

The following aggregate types are treated as mutable references:

- `List<T>`
- `Array<T>`
- `Vector<T, Row>`
- `Vector<T, Column>`
- `Matrix<T>`

Values of these types denote aggregate objects. A variable of one of these
types holds a reference to an object, not an inline copy of all of its elements.

## Assignment And Aliasing

Assigning an aggregate copies the reference. It does not copy the elements and
does not perform an implicit deep copy.

```aether
v = [1, 2, 3];
a = v;
a[0] = 9;
```

After this mutation, `v[0]` also observes `9`, because `a` and `v` refer to the
same vector object.

The same rule applies to matrices:

```aether
A = [1, 2; 3, 4];
B = A;
B[0, 0] = 9;
```

After this mutation, `A[0, 0]` also observes `9`, because `A` and `B` refer to
the same matrix object.

## Indexed Mutation

The planned indexed assignment forms are:

```aether
v[i] = value;
A[i, j] = value;
```

These operations mutate an existing aggregate object. They are side effects, not
pure expressions, and their correctness depends on aliasing. Mutating through
one reference may change the value observed through another reference to the
same aggregate object.

## Future IR And SSA

The intended future IR operations are:

- `IRVectorSet`
- `IRMatrixSet`

The intended future SSA operations are:

- `SSAVectorSet`
- `SSAMatrixSet`

These instructions should not be modeled as pure value producers. They mutate
aggregate storage and must be considered side-effecting, even if the instruction
format later has an internal result field for sequencing, diagnostics, or
backend convenience.

## Optimizer Rules

Until Aether has specific alias analysis for mutable aggregates, optimizations
must be conservative:

- Do not eliminate indexed set operations merely because their result is unused.
- Do not reorder aggregate reads and writes around possible aliases without
  specific analysis proving the transformation is valid.
- Do not assume that two aggregate references are independent.

For example, after `a = v`, a write through `a[i]` may affect a later read of
`v[i]`. A dead-code pass, constant propagation pass, or common-subexpression
pass must preserve that observable behavior.

## Relationship With Const

If `const` exists for a binding in Aether, `const v` blocks mutation through
that reference. It does not necessarily freeze the underlying aggregate object
when other non-const aliases exist.

```aether
v = [1, 2, 3];
const c = v;
c[0] = 9; // error
v[0] = 9; // permitted
```

In this model, `const` constrains the reference through which the operation is
performed. It is not a deep immutability guarantee for the object itself.

## Future Explicit Copies

Aether may later add explicit copy operations for aggregate objects, for
example:

```aether
w = v.copy();
```

Such an operation would create an independent aggregate object according to the
copy operation's documented depth and element semantics. No implicit deep copy
is part of assignment in the current design.

## Future Runtime And GC

Mutable aggregate objects will probably live in heap/runtime-managed storage.
That representation will affect future runtime ownership, lifetime, and garbage
collection design. The semantic rule in this document is independent of the
exact representation: aggregate variables are references, assignment aliases
objects, and indexed mutation changes the referenced object.
