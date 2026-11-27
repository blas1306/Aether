# Aether — POSTFIX-UPDATE-V1 report

Status: **CLOSED — global workspace qualification exception documented.**

Date: 2026-11-27

Base: `24b5247347e83608a17d33033789ebb1469934db`

## Syntax and typing

`place++;` and `place--;` are statement-only forms. They never produce a value.
The parser rejects prefix spelling, initializers, returns, arguments and other
expression contexts, including ambiguous adjacency such as `i+++j`.

Only `int8`, `int16`, `int32`, `int64`, `uint8`, `uint16`, `uint32`, `uint64`,
`isize`, `usize` and their transparent aliases are admitted. The synthesized
unit is resolved contextually as the canonical destination type. Bool, floats,
char, string, reference values and nonnumeric values are rejected.

## Reuse of compound assignment

The lexer reserves `++` and `--` by maximal munch without changing `+`, `-`,
`+=`, `-=`, unary signs, comments or whitespace. AST `CompoundAssign` records an
explicit `PostfixUpdate` origin and a contextual unit; this is structured syntax,
not textual substitution.

HIR retains `PostfixIncrement` or `PostfixDecrement` long enough to verify:

- increment maps only to `AddIntegerChecked`;
- decrement maps only to `SubtractIntegerChecked`;
- the RHS is exactly integer unit `1` of the destination type;
- the destination is a writable built-in integer scalar.

HIR then normalizes to the already qualified compound transaction. MIR and SSA
receive the existing identified `CompoundLoad`/`CompoundCommit` pair, including
the same Place/ClassScalarField alternative, access and bounds checks, lifetime
and provenance protection, invalidation scan, CFG proof and unique commit. No
new MIR, SSA, LLVM opcode, ownership rule, ARC path or rollback mechanism exists.

## Destinations and evaluation order

The admitted surface is the scalar integer subset of compound assignment:
locals; struct fields; accessible mutable class and inherited fields;
`this.field`; Array/List/Buffer, Vector/Matrix and mutable-view indices; `ref mut`;
and nested projections. Const storage, shared references, read-only views,
temporaries and inaccessible or immutable fields remain rejected.

Base, receiver and indices are evaluated once and stabilized before the old
value is loaded. The contextual unit has no source effect. Checked arithmetic
runs after the load and a single commit occurs only on normal completion.
Bounds failure, overflow or underflow publishes no partial update.

`++` preserves `IntegerOverflow` through `AddIntegerChecked`; `--` preserves it
through `SubtractIntegerChecked`. LLVM uses the existing signed/unsigned
`with.overflow` intrinsics and ordinary stores, without wrapping flags or
undefined-overflow assumptions.

## Verification and coverage

The focal `postfix_update_v1.rs` suite covers both operators through AST, HIR,
MIR, SSA and LLVM; all ten integer types and a transparent alias; local, struct,
class, inherited field, collection, mathematical collection, mutable view and
mutable-reference destinations; single evaluation; statement-only rejection;
noninteger and read-only rejection; checked overflow/underflow; parity with
`+= 1`/`-= 1`; and native O0/O2 execution. HIR corruption coverage changes an
explicit compound source into postfix metadata and verifies fail-closed behavior.

Qualification focal: **PASS**.

- focal postfix suite: 9 passed;
- compound-assignment regression: 16 passed;
- dedicated HIR corruption: 1 passed;
- dedicated MIR/SSA compound corruption: 6 passed;
- selected indexing, slices/views, ownership, OOP, reference and exception
  regressions: 45 passed;
- `cargo check --workspace`: passed;
- `cargo fmt --all --check`: passed;
- `cargo clippy --workspace --all-targets -j 1`: passed with only pre-existing warnings;
- differential harness: **PASS**;
- official differential: **PASS — 96 checked, 0 failures**;
- `git diff --check`: passed.

Workspace global: **NOT PASS / BLOCKED**. The workspace-wide command was run
twice with explicit time limits. The first 240-second run timed out while still
making progress through the large linear algebra corpus. The longer run reached
the registry suite after all observed tests passed; four registry tests
completed and the known
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` case then made no
further progress. The process was stopped and is not recorded as PASS. That test
was reproduced again in isolation with a fresh `TMPDIR` and a 30-second timeout
(`exit 124`) with no completion. It was neither changed, skipped nor disabled.

Registry hang: **pre-existing with baseline evidence**. The earlier clean export
of `5e1360694c65` reproduced the same hang for more than 60 seconds. The registry
test blob is identical at that revision and at the POSTFIX base
`24b5247347e83608a17d33033789ebb1469934db`, and neither the intervening history
nor the POSTFIX working diff changes `compiler-next/crates/aether-registry` or
`linearAlgebra`. The prior baseline reproduction therefore remains applicable,
and the clean current reproduction supplies a second non-regression check. No
new failure is attributable to POSTFIX-UPDATE-V1.

## Exclusions

This milestone adds no prefix update, postfix expression value, bitwise or power
operator, additional compound assignment, reference replacement, wrapping
arithmetic or widened write surface.

## Files changed

- `compiler-next/crates/aether-frontend/src/{lexer,parser,ast,lib,hir}.rs`
- `compiler-next/crates/aether-middle/src/mir.rs`
- `compiler-next/crates/aether-driver/tests/postfix_update_v1.rs`
- `compiler-next/tests/programs/postfix_update_v1.ae`
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`
- `docs/architecture/POSTFIX_UPDATE_V1_REPORT.md`

Suggested commit: `feat(compiler-next): add checked statement-only postfix updates`
