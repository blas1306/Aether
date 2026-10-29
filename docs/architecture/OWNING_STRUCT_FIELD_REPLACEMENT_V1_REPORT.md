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

## Element/reference provenance audit

The reproducer `reproducers/.owning_replace_element_alias_probe.ae` exposed a
type-topology hole at a function boundary. The caller retained the same
concrete root for `&mut owner` and `&owner[0]`: `derived_owner`/
`owner_of_place` resolve both arguments to `owner`, and call-argument analysis
keeps element/view storage provenance. The callee, however, necessarily sees
two parameter proxy roots. Its conservative `ReplaceOwned` check only compared
another reference pointee with the replaced owner type, or asked whether that
pointee itself contained an owner. Consequently `ref int` was considered
unrelated to `ref mut Buffer<int>` even though `int` is the Buffer backing
element. HIR admitted the body; MIR and SSA repeated the same incomplete
type-only predicate and admitted their `ReplaceOwned` operations.

`TypeArena::may_borrow_storage_of` now supplies one shared, name-independent
may-overlap topology query. It follows concrete aggregate members, substituted
generic members, nullable payloads, and the element types of Buffer, Array,
List, Vector and Matrix owners. A reference pointee or borrowed-view element
reachable through that topology may denote storage invalidated by replacement.
Unknown or malformed aggregate topology fails closed.

HIR ownership synthesis and the structural HIR verifier reject a replacement
through a parameter when another parameter may borrow that storage. MIR and
SSA independently reconstruct the same fact from their own canonical parameter
tables and types. Concrete local provenance remains more precise: replacement
is accepted when a surviving element reference is rooted in a different local
owner. This does not make `ref mut` exclusive and emits no `noalias` promise.

This conservative boundary rule cannot admit a callee that replaces through
`ref mut Owner` while retaining a second potentially derived parameter merely
because every currently visible caller passes distinct roots: separate
compilation and indirect calls erase that call-site proof. Admitting that shape
later requires a broader reference-system decision—an explicit disjointness
precondition in the function type, or verified interprocedural specialization
and effect summaries. Neither was introduced by this localized correction.

The audit covers direct element references and `View`, `VectorView` and
`MatrixView` descriptors. Equivalent dynamic-storage families are Buffer,
Array, List, Vector and Matrix; nested owning aggregates are covered by the
recursive topology query. String exposes no mutable element-reference/view
surface under this contract, and class/interface fields remain blocked by the
existing global storage rule.

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

`SSA-STORE-PROVENANCE-V1` closes the remaining Store distinction. Every
`SsaOp::Store` now carries a closed `Copy`, `Initialize`, `RootTransfer` or
typed descriptor-commit provenance. SSA independently reconstructs slot state,
ValueId definition/use, root capture/publish/Drop and the exact ListPush,
ListReserve or MatrixAdd source/destination contract. A dereference Store is
therefore admitted only for Copy or a verified descriptor commit; a forged
source replacement cannot authorize itself by changing the label. File results
use ordinary initialization rules without a package/name exception. See
`SSA_STORE_PROVENANCE_V1_REPORT.md`.

## Borrow liveness and may-alias audit

`ref mut` remains write capability, not exclusivity; no new `noalias` is
emitted. Known-root live references/views reject through the existing owner
analysis. A replacement through a reference rejects another parameter whose
reference/view type can reach the replaced owner or its backing element
conservatively in HIR, MIR and SSA, without assuming the parameters are
disjoint.

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
| Buffer element alias reproducer | PASS | rejected with semantic `E0292`; unsafe native program was not executed |
| Array/List/Vector/Matrix element and view aliases | PASS | negative semantic cases for direct references plus View/VectorView/MatrixView |
| independent element-reference provenance | PASS | positive case retains a reference rooted in a distinct local owner |
| MIR owning dereference Store evasion | PASS | corruption reproducer now rejected by the localized verifier rule |
| SSA owning local Field Store evasion | PASS | forged `ReplaceOwned -> Store` rejected |
| SSA owning dereference Store evasion | PASS | closed Store provenance plus independently reconstructed slot/producer protocol |

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

- `cargo run -q -p aether-cli -- check
  ../reproducers/.owning_replace_element_alias_probe.ae`: **FAIL as required**,
  exit 1 with semantic `E0292` at the replacement; the program was not built or
  run.
- `cargo test -p aether-driver --test owning_struct_field_replacement_v1`:
  **12/12 PASS**, including the reproducer shape, all dynamic owner/view
  families, a distinct-owner positive case, and independent MIR/SSA metadata
  corruptions.
- `cargo test -p aether-driver --test ssa_store_provenance_v1`: **5/5 PASS**,
  including all six concrete provenance forms, corruption gates and native
  O0/O2 execution.
- Focused ownership/collection tests (`owning_param_early_return_v1`,
  `linear_algebra_ownership_ergonomics_v1`, `class_buffer_fields_v1`, and
  `matrix_add_v1`): **21/21 PASS**, including their O0/O2 native gates.
- `cargo test -p aether-frontend -p aether-middle`: **104/104 PASS** plus
  doc tests.
- `cargo test -p aether-driver --test vertical`: **220/220 PASS**.
- Previous closure baseline: a temporary venv with `numpy==2.4.2` first on
  `PATH` produced a passing `cargo test --workspace`. The current localized
  delta instead reran the frontend/middle, focused ownership/collection, and
  complete vertical gates listed above.
- `cargo fmt --check`: **PASS**.
- Targeted `cargo clippy -p aether-frontend -p aether-middle -p aether-driver
  --all-targets -- -D warnings`: **FAIL, preexisting** on the existing frontend
  `assert_is_empty` and `needless_borrows_for_generic_args` warnings. They were
  not edited to obtain a green result, and no new warning from this delta was
  reported before those failures.
- repository-wide `git diff --check`: **PASS**.
- unchanged `reproducers/graphics_svg_owning_buffer_growth.ae`: check, build and
  native execution all **PASS** with status 0.

## Files changed by this qualification closure

- `compiler-next/crates/aether-frontend/src/types.rs`: conservative owner
  backing/reference-view topology query.
- `compiler-next/crates/aether-frontend/src/hir.rs`: apply the query in
  ownership synthesis and structural HIR verification.
- `compiler-next/crates/aether-middle/src/mir.rs`: reject the corrupt ordinary
  owning dereference Move/Store representation and independently reject
  element/view parameter overlap.
- `compiler-next/crates/aether-middle/src/ssa.rs`: independently reject the
  same parameter overlap from SSA metadata; now also carries and independently
  verifies closed Store provenance and memory-slot state.
- `compiler-next/crates/aether-driver/tests/owning_struct_field_replacement_v1.rs`:
  lifecycle/type matrix, exact counters, element/view positives and negatives,
  and MIR/SSA corruption coverage.
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
2. resolve the global class/interface-handle-in-struct conflict or explicitly
   revise the required type matrix;
3. add typed/per-identity lifecycle events and the remaining drop-flag,
   duplicate-consume, FieldId and backend publish/drop corruptions;
4. make the repository-wide Clippy and whitespace gates green without changing
   unrelated user work merely for this milestone.

Because safety guarantees 1 and 2 remain unproved, the correct status is
**PARTIAL**, not CLOSED.
