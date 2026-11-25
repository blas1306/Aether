# Aether — OWNING-COLLECTION-FIELDS-V1 — Implementation and qualification report

Status: **CLOSED**, implemented and qualified 2026-11-23.

Normative authority:
[OWNING_COLLECTION_FIELDS_ARCH_1](OWNING_COLLECTION_FIELDS_ARCH_1.md).

This milestone closes F1 only. `INDEX-DEREFERENCE-DIAGNOSTIC-V1` (F2) remains
independent and was not changed.

## 1. Confirmed root cause

HIR and MIR already retained the exact writable `Place`, structural mutation,
element type, relocation contract and final aggregate cleanup. The first
invalid representation was raw SSA:

- a direct SSA List root was redefined by `ListPush`/`ListReserve` without the
  ownership ledger consuming the preceding root definition;
- a promoted owning field used `mutator -> InsertField`, but `InsertField`
  consumed only its old aggregate and not the inserted owning descriptor;
- an address-taken aggregate used `mutator -> Store DescriptorCommit`, whose
  producer/source/use provenance was already reconstructed correctly, but the
  generic Store type check rejected an owning `MemoryLocal + Field*` before
  that proof could authorize the commit.

The backend was not causal and required no change.

## 2. SSA implementation

`compiler-next/crates/aether-middle/src/ssa.rs` now has one closed
`descriptor_mutation` query covering exactly `ListPush`, `ListReserve` and
`MatrixAdd`.

The ownership ledger now models the three normative continuations:

1. **Direct SSA root.** A mutator whose source is exactly an unprojected
   `SsaPlaceBase::Value` consumes that preceding owner definition. Its result
   becomes the new root definition. Memory roots and projected aggregate roots
   are deliberately not consumed by this rule.
2. **Promoted field.** `InsertField` consumes both the old aggregate and its
   owning inserted value. A new verifier requires the inserted value to be the
   immediately preceding result of a closed typed descriptor mutator; the
   producer source must equal `aggregate + exact FieldId path`, remain in the
   same block, have no unwind edge, and have exactly one use.
3. **Materialized field.** The generic projected-owning Store prohibition now
   defers only for a `DescriptorCommit` assertion. The independent Store
   provenance verifier still proves exact producer kind, structural
   source/destination identity, adjacency, no unwind and a single result use.
   A tag alone grants no permission.

`Store DescriptorCommit` continues to consume only the transient producer
result while leaving the memory slot initialized. No Drop of the preceding
descriptor was introduced.

## 3. Preserved invariants

- ordinary partial moves of owning fields/elements remain rejected;
- ordinary owning field replacement still requires `ReplaceOwned` or the
  existing specialized string operation;
- arbitrary owning `InsertField` and projected owning Store remain invalid;
- `ref mut` still supplies write capability without exclusivity or `noalias`;
- List growth still invalidates relevant borrows and uses the existing typed
  relocation protocol;
- traps retain their abortive behavior;
- normal/unwind aggregate cleanup retains one final recursive Drop;
- no Clone, implicit Alias/retain, ABI, layout, STD, OAL or public API change
  was made.

LLVM lowering was inspected and left unchanged: it computes the updated
descriptor, reinserts or stores it, and reaches the ordinary final aggregate
Drop. The implementation does not lower descriptor continuity through
`ReplaceOwned`.

## 4. Reproducers and positive qualification

The dedicated suite
`compiler-next/crates/aether-driver/tests/owning_collection_fields_v1.rs`
builds raw SSA with `build_ssa` before `verify_ssa` and fixes all required
shapes:

- `List<Item{string}>` as a direct local root;
- promoted `Result.items: List<Item{string}>`;
- direct `reserve(List<string>, capacity)`;
- an address-taken aggregate followed by direct field mutation;
- mutation through `ref mut Result`, retained as a positive regression;
- promoted `MatrixAdd -> InsertField` on a struct field;
- nested fields, Copy and owning List elements, repeated push with growth,
  reserve-before-push, aggregate return, early return and sibling owners;
- throw before a commit and throw after a commit;
- native O0/O2 execution with balanced heap and string lifecycle counters;
- an AddressSanitizer run for representative repeated growth.

The focal consumer fixture
`compiler-next/tests/programs/owning_collection_fields_expense_load.ae`
returns one `LoadResult` containing both `List<Expense>` and `LoadState`, then
mutates the returned list without splitting status into another local.

## 5. Corruption qualification

Independent raw-SSA mutations demonstrate rejection of:

- a second consumption of the direct root source;
- an owning inserted value without a typed descriptor producer;
- duplicate aggregate/source consumption;
- a wrong producer operation;
- a wrong FieldId/projection;
- producer/InsertField separation by an intermediate operation;
- a descriptor producer result with multiple uses;
- a forged DescriptorCommit kind;
- a mismatched Store destination;
- duplicate descriptor publication;
- omitted and duplicated final aggregate Drop.

The existing `ssa_store_provenance_v1` corruption matrix additionally retains
coverage for a forged DescriptorCommit label on a non-mutator producer,
source/destination mismatch, wrong ValueId, wrong kind, intermediate operation
and duplicate Store. Existing owning replacement tests continue to reject
Store-based bypasses.

## 6. Native lifecycle and IR evidence

O0 and O2 runs check program results plus equality of heap allocations/frees
and string allocations/frees. ASan reports no invalid access or double-free in
the representative growth program (LeakSanitizer is disabled under the
sandbox; explicit allocation balance remains enabled).

HIR and MIR retain typed `ListPush`/`ListReserve` places. SSA dumps demonstrate
all three physical forms: direct root redefinition, promoted
`ListPush -> InsertField`, and materialized
`ListPush -> Store DescriptorCommit`. LLVM contains the existing typed List
helpers, no owning-slot replacement marker for these commits, and no Clone
operation.

## 7. Consumers

The following consumers pass `aether check` in O0 and O2:

- `examples/assessment/expense-tracker`;
- `examples/expense_tracker/main.ae` (the historical multi-file entrypoint,
  not a manifest package root);
- `examples/assessment/data-processor`.

The official examples were not rewritten.

## 8. Gate evidence

Executed from `compiler-next`:

- dedicated `owning_collection_fields_v1`: **6/6 PASS**, including O0/O2,
  corruption, lifecycle and ASan;
- `ssa_store_provenance_v1`: **5/5 PASS**;
- `owning_struct_field_replacement_v1`: **16/16 PASS**;
- focused borrow, exceptions V1-V4, MatrixAdd and linear-algebra ownership
  suites: **PASS**;
- List Vertical-14: **7/7 PASS**;
- owning collections Vertical-16: **2/2 PASS**;
- `cargo check --workspace`: **PASS**;
- `cargo test --workspace -j 1`: **PASS** (all unit, integration and doc tests);
- `cargo fmt --all --check`: **PASS**;
- `cargo clippy --workspace --all-targets -j 1`: **PASS with existing
  warnings** in unrelated frontend/middle code and the pre-existing Store
  provenance test;
- `git diff --check`: **PASS**.

## 9. Files changed

- `compiler-next/crates/aether-middle/src/ssa.rs`;
- `compiler-next/crates/aether-driver/tests/owning_collection_fields_v1.rs`;
- `compiler-next/tests/programs/owning_collection_fields_expense_load.ae`;
- this report.

No compiler frontend, MIR representation, LLVM backend, runtime, Core, STD,
OAL, public API, official example, commit or remote state was changed.

## 10. Closure

Direct-root, promoted-field and materialized-field ownership continuity all
pass positive, negative and lifecycle qualification. Therefore
**OWNING-COLLECTION-FIELDS-V1 is CLOSED**.
