# INTEGER-SLICE-BOUNDS-V1 — Qualification Report

**Date:** 2026-11-27
**Status:** CLOSED
**Authority:** `compiler-next`

## 1. Preflight and scope

The milestone started from `main` at `9ce07c8611e106b845adad24ca708d38ddc695d1`,
one commit ahead of `origin/main` at
`18b94662093c4d47764a476caf2e53f915a221a7`. The existing personal changes and
untracked files under `examples/ProbandoNR`, `scrap/`, and `docs/reports` were
preserved. Before this consolidation, no reset, clean, stash, commit, or push
was performed.

Only `compiler-next` is implementation authority. The existing selector IR,
slice result types, descriptors, traps, and ownership model were sufficient;
no new IR variant or public range type was added.

## 2. Implemented contract

Both endpoints of an inclusive `Closed { first, last }` selector and scalar
selectors inside a mixed subscript now admit all native integer types:

- signed: `int8`, `int16`, `int32`, `int64`, `isize`;
- unsigned: `uint8`, `uint16`, `uint32`, `uint64`, `usize`.

`int` remains a transparent alias of `int64`. Endpoints may use different
integer types and retain their original `TypeId` through HIR, MIR, and SSA.
This contextual admission introduces no general signed/unsigned conversion.
Float, bool, char, string, and every other non-integer selector remain rejected.

The extension applies to existing Array/List slice copies, Vector/Matrix views,
their supported subviews, reads, assignments, and mixed Matrix forms such as
`A[i,:]`, `A[:,j]`, and `A[i,a:b]`. Buffer and linear View slicing remains
prohibited.

## 3. Heterogeneous comparison and traps

LLVM normalizes each closed endpoint into an internal `i65` mathematical
domain. Signed operands are sign-extended and unsigned operands are
zero-extended. This domain represents the complete interval
`[-2^63, 2^64-1]`, so a negative signed endpoint compares below every unsigned
endpoint and `uint64::MAX` is never reinterpreted as negative or truncated into
range.

Validation order is:

1. compare `first <= last` in the mathematical domain;
2. on failure, take `SliceOrderError`;
3. validate the existing zero- or one-based logical bounds;
4. on failure, take `SliceBoundsError`;
5. only then narrow validated non-negative operands to the descriptor width and
   calculate base adjustment, length, stride, offset, and address.

Mixed scalar selectors use the scalar-index normalization from
`INTEGER-INDEXING-V1` and retain `IndexOutOfBounds`. Tests cover `1:-1`,
`-2:-1`, `3:2`, `3:3`, negative mixed scalars, and `uint64::MAX` at O0 and O2.

## 4. Frontend and verifier changes

`type_subscript` no longer contextually coerces slice operands to `usize`. It
types each operand independently and admits it only when the canonical type is
a native integer. The existing constant value propagated by the frontend is
used for static order checking, including heterogeneous explicitly cast
constants such as `int8(3):uint16(2)`.

The independent HIR, MIR, and SSA verifiers now require an integer `TypeId`
rather than exact `usize` for every closed endpoint and mixed scalar selector.
Dedicated corruption tests replace operands with bool values and confirm that
all three verification layers fail closed.

## 5. Preserved semantics

- Base and selector expressions are evaluated exactly once: base first,
  selectors left-to-right, and `first` before `last`.
- Slice assignment still evaluates the RHS after selectors, validates the
  complete transaction, snapshots the RHS, and only then stores.
- Closed slices remain inclusive and never validly empty; equal endpoints have
  length one. Full slices preserve empty extents and shapes `0x0`, `mx0`, and
  `0xn`.
- Array/List remain independent O(k) copies requiring `T: Copy`.
- Vector/Matrix slices remain O(1) views with rank, orientation, strides,
  provenance, borrow, and no-escape rules unchanged.
- Exact assignment shape/orientation, overlap semantics, and all existing trap
  classes remain unchanged.
- Open ranges, reverse, step, sentinels, and indexing from the end remain out of
  scope.

## 6. Tests

The new `integer_slice_bounds_v1` integration suite covers all ten native
integer types and `int`, heterogeneous signed/unsigned pairs, reads and
assignments, Array, Vector, Matrix, views, mixed selectors, exactly-once source
order, equal endpoints, negatives, maximum `uint64`, static and dynamic
inverted order, upper/lower bounds, non-integer rejection, verifier corruption,
and O0/O2 equivalence.

The historical `INTEGER-INDEXING-V1` negative cases that existed solely to
reject `int` slice operands were removed. All remaining non-integer, ownership,
shape, syntax, and unsupported-family rejections remain covered. Existing
SLICE-SELECTORS-V1, SLICE-READ-V1, and SLICE-ASSIGNMENT-V1 suites pass without
semantic weakening and continue to cover empty shapes, snapshot, overlap,
strided views, and assignment ordering.

## 7. Normative changes

`AETHER_V1_SEMANTIC_CONTRACT.md` now defines INTEGER-SLICE-BOUNDS-V1 beside the
scalar indexing amendment, including integer admission, heterogeneous order,
trap priority, evaluation order, and preserved exclusions.

`DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md` received a narrow amendment superseding
its historical exact-`usize` operand restriction and clarifying that a negative
signed expression is admitted but is neither an index-from-end feature nor a
valid in-bounds endpoint.

## 8. Qualification

| Check | Result |
| --- | --- |
| INTEGER-SLICE-BOUNDS-V1 focused integration suite | PASS, 5/5 |
| Existing integer-indexing and slice suites | PASS |
| HIR/MIR/SSA corruption coverage | PASS |
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | PASS |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS with pre-existing warnings |
| differential harness self-tests | PASS |
| official differential qualification | PASS, 96/96 |
| `git diff --check` | PASS |

Clippy continues to report the existing large-enum, identical-match-arm,
long-function, single-match, pass-by-reference, and raw-string warnings. The
existing ASan target-triple warnings and the differential script's ignored NUL
byte warning also remain. No new warning or qualification failure is
attributable to this milestone.

## 9. Files modified

- `compiler-next/crates/aether-frontend/src/hir.rs`
- `compiler-next/crates/aether-middle/src/mir.rs`
- `compiler-next/crates/aether-middle/src/ssa.rs`
- `compiler-next/crates/aether-backend-llvm/src/lib.rs`
- `compiler-next/crates/aether-driver/tests/integer_indexing_v1.rs`
- `compiler-next/crates/aether-driver/tests/integer_slice_bounds_v1.rs`
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`
- `docs/architecture/DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md`
- `docs/architecture/INTEGER_SLICE_BOUNDS_V1_REPORT.md`
