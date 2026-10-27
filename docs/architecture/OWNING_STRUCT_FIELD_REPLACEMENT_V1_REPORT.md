# OWNING-STRUCT-FIELD-REPLACEMENT-V1 — implementation and qualification report

Status: **PARTIAL; functional implementation and broad regression gates pass,
but the complete architecture safety proof is not representable by the current
borrow/SSA metadata**, updated 2026-10-27.

Normative authority:
[OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1](OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md).

This report does not declare this capability or GRAPHICS-SVG-BACKEND-V1
CLOSED.

## Implemented contract

- HIR distinguishes `ReplaceOwned` from Copy assignment and admits only exact
  concrete, storable, Relocatable, non-Copy, drop-needing values at Field-only
  local paths or writable dereferences.
- MIR and SSA preserve one indivisible `ReplaceOwned` operation. Their type and
  place verifiers reject wrong types, shared dereferences, Index paths,
  unsupported bases and unknown-provenance reference parameters that may alias.
- The ownership ledgers consume the materialized RHS once without a projected
  Move or Drop and preserve the root owner state.
- `ReplaceOwned` has no exceptional edge. LLVM captures old, publishes new and
  invokes typed Drop on old, in that order.
- No allocation, boxing, field flag, runtime alias check, Graphics branch,
  partial move-out or `noalias` attribute was introduced.

## Safety audit and localized correction

The closure audit found one verifier defect. Corrupt MIR could replace a
dereference `ReplaceOwned` with an ordinary `Move` whose destination was
`*ref mut T`. The old owner was overwritten without Drop while the RHS was
still recorded as consumed. `verify_mir` now rejects an owning dereference
`Move` destination and requires the verified replacement transaction.

The rejection is deliberately narrow. Typed List/collection transactions also
mutate descriptors reached through references, so rejecting every drop-needing
dereference destination would block valid existing operations. The complete
vertical suite confirms that the narrow rule preserves those operations.

SSA rejects ordinary owning Field-only Stores rooted at promoted local/value
storage. It cannot yet reject every owning Store rooted at a dereference:
legitimate verified collection and File transactions and a forged source
replacement currently converge on the same unlabelled `SsaOp::Store` shape.
Closing that distinction independently requires explicit Store provenance or a
separate internal transaction marker. Inferring the distinction from producer
spelling would only trust MIR again. This remains a safety qualification
blocker.

## Borrow liveness and may-alias audit

`ref mut` remains write capability, not exclusivity; no new `noalias` is
emitted. Known-root live references/views reject through the existing owner
analysis. A replacement through a reference rejects another compatible
reference parameter conservatively in HIR, MIR and SSA, without assuming the
parameters are disjoint.

Call and formatting borrows have explicit Begin/End-style metadata in MIR and
SSA, so those scoped borrows can end before commit and their regions are
verified independently. General local references and views do not have region
end metadata in HIR/MIR/SSA; their existing analysis is lexical. Consequently
the architecture's stronger requirement to reconstruct arbitrary non-lexical
borrow death and may-alias state independently at every IR level cannot be
proved without extending the global borrowing contract. No region inference
was added for this V1. Unknown provenance continues to fail conservatively.

## Qualification matrix

| Area | Result | Evidence / limitation |
|---|---|---|
| Buffer direct, nested and through `ref mut` | PASS | native O0/O2, HIR/MIR/SSA operation identity and balanced lifecycle |
| consecutive `v0 -> v1 -> v2` | PASS | exactly 3 heap allocations and 3 frees at O0/O2 |
| sibling preservation | PASS | aggregate with three independent owners |
| List, Array, Vector and Matrix | PASS | concrete field replacements execute and balance at O0/O2 |
| nested owning aggregate | PASS | replaced aggregate plus untouched owning sibling |
| concrete generic instance | PASS | `Box<Buffer<int>>` after substitution |
| string | PASS | existing `ReplaceString`, publish-before-release, O0/O2 |
| class/interface handles inside structs | BLOCKED | global E0274 forbids transitively storing these reference-like handles in struct fields |
| arbitrary symbolic `T: Storable` | BLOCKED | no positive symbolic Drop capability; no capability was invented |
| RHS throw / later unwind | PASS | old survives pre-commit throw; new is cleaned after later throw |
| early return and general cleanup regressions | PASS | complete workspace and owning-parameter suites |
| allocation/free balance | PASS | exact and balanced heap counters at O0/O2 |
| per-allocation Drop identity/order events | BLOCKED | runtime exposes aggregate counters, not typed per-owner identity events |
| arbitrary borrow end before commit | BLOCKED | no general region-end metadata outside scoped call/format borrows |
| HIR/MIR/SSA conservative parameter may-alias | PASS | independently reconstructed from canonical parameter/reference types |
| MIR owning dereference Store evasion | PASS | corruption reproducer now rejected by the localized verifier rule |
| SSA owning local Field Store evasion | PASS | forged `ReplaceOwned -> Store` rejected |
| SSA owning dereference Store evasion | BLOCKED | indistinguishable from established typed internal dereference transactions |

## Corruption matrix

| Corruption | Result |
|---|---|
| HIR operation changed to ordinary Assign | PASS |
| HIR/MIR/SSA TypeId or result type | PASS |
| MIR/SSA RHS type/materialization | PASS |
| mutable dereference changed to shared | PASS |
| Field-only replacement changed to Index at source/type-place verification | PASS |
| owning local Field replacement changed to SSA Store | PASS |
| owning dereference replacement changed to MIR Move/Store | PASS |
| exceptional edge added to MIR/SSA ReplaceOwned | PASS |
| generic projected Move/Drop and ownership double-consume rules | PASS in the global ownership verifier suites |
| dedicated FieldId, root drop-flag and duplicate-consume mutations for this operation | NOT COMPLETE |
| explicit arbitrary borrow-region/alias metadata mutation | BLOCKED: that metadata does not exist generally |
| backend old-Drop omitted/duplicated or moved before publish | NOT COMPLETE; static LLVM order is checked, but there is no independently verified backend event IR |

## Reproducible gate evidence

- `cargo test -p aether-driver --test owning_struct_field_replacement_v1`:
  **10/10 PASS**.
- `cargo test -p aether-driver --test vertical`: **220/220 PASS**.
- A temporary venv with `numpy==2.4.2` was placed first on `PATH`;
  `cargo test --workspace`: **PASS**, including all SVD/NumPy oracles and
  workspace doc tests.
- `cargo fmt --check`: **PASS**.
- `cargo clippy --workspace --all-targets -- -D warnings`: **FAIL,
  preexisting**. The first failure remains
  `aether-package/src/environment.rs:555` (`clippy::assert_is_empty`), followed
  by existing frontend `assert_is_empty` and `needless_borrows_for_generic_args`
  warnings. They were not edited to obtain a green result.
- repository-wide `git diff --check`: **FAIL, preexisting user file only** at
  `examples/minimos_cuadrados/MinimosCuadrados.ae:51`. Files changed for this
  capability are whitespace-clean; the user file was preserved.
- unchanged `reproducers/graphics_svg_owning_buffer_growth.ae`: check, build and
  native execution all **PASS** with status 0.

## Files changed by this qualification closure

- `compiler-next/crates/aether-middle/src/mir.rs`: reject the corrupt ordinary
  owning dereference Move/Store representation.
- `compiler-next/crates/aether-driver/tests/owning_struct_field_replacement_v1.rs`:
  lifecycle/type matrix, exact counters and MIR/SSA corruption coverage.
- this report.

The earlier functional implementation also remains in frontend, MIR, SSA,
LLVM and the two global architecture/semantic documents listed by the previous
report. No Graphics, SVG, Plots, production dependency, user example, commit or
remote state was changed by this closure.

## Remaining before CLOSED

Closure requires all of the following, without weakening existing guarantees:

1. represent and independently verify general borrow/view liveness and
   may-alias regions in HIR, MIR and SSA, or revise the normative architecture
   through a separate borrowing decision;
2. distinguish legitimate internal SSA dereference Stores from forbidden
   source owning replacement Stores;
3. resolve the global class/interface-handle-in-struct conflict or explicitly
   revise the required type matrix;
4. add typed/per-identity lifecycle events and the remaining drop-flag,
   duplicate-consume, FieldId and backend publish/drop corruptions;
5. make the repository-wide Clippy and whitespace gates green without changing
   unrelated user work merely for this milestone.

Because safety guarantees 1 and 2 remain unproved, the correct status is
**PARTIAL**, not CLOSED.
