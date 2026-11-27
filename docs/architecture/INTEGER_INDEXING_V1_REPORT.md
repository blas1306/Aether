# INTEGER-INDEXING-V1 — Qualification Report

**Date:** 2026-11-26
**Status:** CLOSED
**Authority:** `compiler-next`

## 1. Implemented contract

Scalar collection indexing accepts every native Aether integer type:

- signed: `int8`, `int16`, `int32`, `int64`, `isize`;
- unsigned: `uint8`, `uint16`, `uint32`, `uint64`, `usize`.

`int` remains an alias of `int64`. This admission is contextual to scalar
subscripts: it does not add general implicit signed/unsigned conversions or
change ordinary numeric coercion rules. `float32`, `float64`, `bool`, `char`,
`string`, and all other non-integer types remain invalid scalar indices.

The existing logical domains are preserved:

- Array, List, and Buffer are zero-based;
- Vector and Matrix are one-based;
- views retain the domain of their current view contract.

The change covers scalar reads and writes, direct and computed indices,
multidimensional accesses, supported Copy elements, and owning elements where
element access was already legal. It does not extend the available element
reference surface.

## 2. Components modified

- `aether-frontend/src/hir.rs`: scalar-subscript typing now admits any integer
  type without imposing an expected `usize`; slice selectors retain their
  existing `usize` contract. The independent HIR verifier accepts only native
  integer scalar operands. Existing constant out-of-bounds diagnostics were
  retained and made base-aware for negative/zero constants.
- `aether-middle/src/mir.rs`: the independent MIR verifier validates that every
  scalar row/column projection operand has an integer type.
- `aether-middle/src/ssa.rs`: the independent SSA verifier applies the same
  integer-only projection contract.
- `aether-backend-llvm/src/lib.rs`: scalar operands are normalized to the
  backend's 64-bit index representation with sign-preserving extension for
  narrow signed types and zero extension for narrow unsigned types.
- `aether-driver/tests/integer_indexing_v1.rs`: end-to-end and IR-corruption
  coverage for the new contract.
- `aether-driver/tests/vertical.rs`: historical negative cases that encoded the
  former exact-`usize` rule were reconciled; non-integer and ownership
  rejections remain covered.
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`: normative contract updated
  with the INTEGER-INDEXING-V1 amendment.

No runtime indexed-access API or IR representation needed to change. HIR, MIR,
and SSA already preserve the original index `TypeId`, so signedness and width
remain available through LLVM lowering. No resolver or parallel type system was
introduced.

## 3. Validation strategy

Each scalar index is validated against the collection's existing logical
domain before address/offset arithmetic. Existing checks and the abortive
`IndexOutOfBounds` trap are reused; checks are not duplicated.

- Signed negative values fail the unsigned bounds comparison and trap before
  offset computation.
- Values at or above a zero-based length trap.
- Values below one or above a one-based extent trap.
- Empty collections reject every scalar index.
- Nested and multidimensional accesses validate each logical projection before
  its corresponding address computation.

Direct constant indices continue to receive the existing static
out-of-bounds diagnostic when provably invalid. Dynamic failures continue to
trap at runtime. No general static range analysis was added.

## 4. Preservation of single evaluation

The subscript expression remains one HIR expression, one MIR/SSA value, and one
LLVM value. Width/sign normalization is applied to that already-evaluated
value; it does not re-emit the source expression. Existing left-to-right
projection lowering is unchanged.

Tests exercise side-effecting index functions and multiple matrix indices,
checking both exactly-once evaluation and observable left-to-right ordering at
`-O0` and `-O2`.

## 5. Signed and unsigned treatment

Narrow signed indices use sign extension; narrow unsigned indices use zero
extension. The 64-bit families (`int64`, `uint64`, `isize`, and `usize`) retain
their complete bit pattern and do not pass through a truncating conversion.

Consequently:

- a negative signed value cannot wrap into an in-range positive offset;
- a large `uint64`/`usize` value cannot truncate into range;
- bounds validation happens before one-based adjustment, byte scaling, or
  multidimensional offset arithmetic;
- existing checked allocation/offset behavior and `IndexOutOfBounds` policy are
  unchanged.

## 6. Interaction with ownership

Only index operand admissibility changed. Borrowing, mutability, aliasing,
move/copy, partial replacement, and cleanup rules are unchanged. Tests cover
reads and writes through Array, List, Buffer, Vector, Matrix, their applicable
mutable views, and a nested owning collection. Existing restrictions on
references to elements remain in force.

## 7. Behavior at O0 and O2

The focused execution suite compiles and runs the same programs through LLVM
at `-O0` and `-O2` and compares their observable output and trap behavior. All
cases passed equivalently, including calculated indices, side effects,
negative signed indices, maximum unsigned indices, empty collections,
arithmetic overflow, mutation, and matrices.

The requested range-loop case works without a cast:

```aether
for (int i in 0:2) {
    println(lista[i]);
}
```

This does not alter range syntax, range types, or iterator types; only the
scalar use of the loop's existing `int` value is admitted by `[]`.

## 8. Tests and qualification

Final results:

| Check | Result |
| --- | --- |
| INTEGER-INDEXING-V1 focused integration suite | PASS, 6/6 |
| HIR non-integer corruption test | PASS |
| MIR/SSA independent corruption tests | PASS |
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | PASS |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS |
| differential harness self-tests | PASS |
| official differential qualification | PASS, 96/96 |
| `git diff --check` | PASS |

Coverage includes all ten integer families, the `int` alias, read/write,
Array/List/Buffer/Vector/Matrix, applicable views, nested and multidimensional
access, calculated and side-effecting indices, empty collections, signed
negative values, maximum unsigned values, overflow, and rejection of bool,
float, string, and char indices. Slice selectors with `int` endpoints remain
rejected under their existing contract.

The first full workspace run exposed six historical negative tests whose sole
expectation was rejection of `int` scalar indices. Those expectations were
updated to the new normative contract, then the complete workspace suite was
rerun successfully. Tests were not weakened for non-integer indices or for
ownership, mutability, aliasing, ranges, or slices.

Pre-existing warnings observed during qualification were kept separate from
the change: Clippy reports existing large-enum, long-function, match-style,
pass-by-reference, and raw-string warnings in unrelated/current baseline code;
existing clang ASan tests report target-triple override warnings; and the
differential script reports an ignored NUL byte in command substitution. No
new warning remains attributable to INTEGER-INDEXING-V1.

## 9. Limitations

- This milestone implements scalar indexing only.
- Slice endpoints and slice semantics are unchanged.
- Range and iterator types are unchanged.
- No implicit general numeric conversion was added.
- No general-purpose range analysis or improved static bounds proof was added.
- Ownership, OAL, plots, LSP, Python legacy, and `compiler-rs` are untouched.

## 10. Performance impact

Existing `usize` and other 64-bit index paths add no width-conversion
instruction. Narrow integers require at most one `sext` or `zext` per evaluated
index; LLVM can fold or eliminate it where the producer already establishes
the width. Bounds checks, trap blocks, address calculations, allocation
behavior, and runtime data layouts are unchanged. No additional allocation or
runtime dispatch is introduced.

## 11. Suggested commit

```text
feat(compiler-next): admit native integers as scalar indices
```

No commit or push was performed as part of this milestone.
