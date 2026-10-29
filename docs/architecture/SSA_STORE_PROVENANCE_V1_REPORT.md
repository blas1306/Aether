# SSA-STORE-PROVENANCE-V1 — implementation and qualification report

Status: **CLOSED**, implemented and qualified 2026-10-28.

Normative authority:
[SSA_STORE_PROVENANCE_ARCH_1](SSA_STORE_PROVENANCE_ARCH_1.md).

This milestone closes only the SSA Store-provenance blocker. It does not
declare `OWNING-STRUCT-FIELD-REPLACEMENT-V1` CLOSED.

## Implemented representation

`SsaOp::Store` now retains one closed `StoreProvenance` value:

- `Copy`;
- `Initialize`;
- `RootTransfer`;
- `DescriptorCommit(ListPush | ListReserve | MatrixAdd)`.

There is no `Other`, `Trusted` or `Unknown` variant. The metadata survives SSA
construction, verification, the OOP optimization/re-verification boundary and
the deterministic dump. LLVM consumes only `VerifiedSsa` and erases the tag;
the ABI and emitted physical store are unchanged.

`ReplaceOwned` and `ReplaceString` remain distinct operations. No language API,
reference rule, collection/File algorithm, `noalias` attribute or public
capability was added.

## Producer inventory and lowering

The only mechanical Store producer remains the `memory_destination` path in
`rename_block`. It covers address-taken locals, indexed storage, dereferences
and class storage. Lowering classifies from the MIR operation, destination and
concrete type, never from function/package names or spans.

The real root protocol was audited before verification was implemented. For
an address-taken owning root it is:

```text
old = Move(root)
new = Move(rhs)
Store(root, new, RootTransfer)
Drop(old)
```

RHS evaluation and its unwind precede capture. Existing programs also contain
bookkeeping between these conceptual steps, so the classifier keys on the
old-owner capture and the SSA verifier proves the later Drop instead of
requiring lowering to label a preselected adjacent four-instruction spelling.

Typed descriptor commits retain the existing producer followed immediately by
the physical publication Store. Ordinary SSA-local List/Matrix updates still
redefine the SSA local directly and create no Store.

File has no exception. A `readText` result stored into an address-taken fresh
local is an ordinary `Initialize`; File identity is irrelevant.

## Independent SSA verification

The verifier does not accept provenance as evidence. It reconstructs:

- exact place/value type, writability and reference capability;
- materialized ValueId definition, dominance and complete use count;
- memory-root state from parameters, Moves, Stores, Drops, CFG joins and
  instruction unwind edges;
- old-owner capture, new-owner publication and unique post-publication Drop for
  `RootTransfer`;
- exact typed producer, kind, structural source/destination identity, direct
  commit region and single result use for descriptor commits;
- existing const, borrow, alias, relocation, initialization, mutation,
  invalidation and trap contracts.

The memory ledger uses a may-state union at CFG joins. `Initialize` requires
only `Uninitialized`; descriptor commit requires `Initialized`; capture moves
an initialized root to uninitialized and `RootTransfer` republishes it. A mixed
or corrupted state fails closed.

For dereferences, the effective closed rule is: Copy Store or an exact typed
descriptor commit. `Initialize` and `RootTransfer` require a root
`MemoryLocal`. Consequently an owning Store cannot impersonate
`ReplaceOwned` merely by changing its tag.

## Qualification

The dedicated suite
`compiler-next/crates/aether-driver/tests/ssa_store_provenance_v1.rs` covers:

- all six concrete provenance forms;
- address-taken initialization and root reassignment;
- ListPush, ListReserve and MatrixAdd through mutable references;
- native O0/O2 execution;
- wrong provenance and wrong descriptor kind;
- forged `ReplaceOwned -> Store`;
- wrong ValueId, producer source and destination relation;
- a producer/commit region split by another operation;
- duplicate descriptor publication/result consumption;
- missing and reordered old-owner Drop.

The existing ReplaceOwned corruption test now supplies explicit invalid Store
provenance and remains independently rejected by `verify_ssa`.

## Gate evidence

- dedicated `ssa_store_provenance_v1`: **5/5 PASS**, including native O0/O2;
- dedicated `owning_struct_field_replacement_v1`: **12/12 PASS**;
- frontend and middle unit/doc tests: **104/104 PASS**;
- focused Matrix, File, string, ownership and collection regressions:
  **PASS**;
- complete vertical suite: **220/220 PASS**;
- complete `cargo test --workspace`: **PASS**;
- `cargo fmt --check`: **PASS**;
- targeted Clippy with `-D warnings`: **FAIL, preexisting** in frontend
  `assert_is_empty` and `needless_borrows_for_generic_args`; no milestone file
  was diagnosed before compilation stopped;
- repository `git diff --check`: **PASS**.

## Files changed for this milestone

- `compiler-next/crates/aether-middle/src/ssa.rs`: closed representation,
  lowering classification, memory ledger and structural verification;
- `compiler-next/crates/aether-middle/src/lib.rs`: internal compiler exports;
- `compiler-next/crates/aether-middle/src/ssa/classes.rs`: exhaustive Store
  consumer updated without semantic change;
- `compiler-next/crates/aether-backend-llvm/src/lib.rs`: erase verified
  provenance while retaining existing lowering;
- `compiler-next/crates/aether-driver/tests/ssa_store_provenance_v1.rs`:
  dedicated positive/negative/corruption and O0/O2 qualification;
- `compiler-next/crates/aether-driver/tests/owning_struct_field_replacement_v1.rs`:
  explicit invalid provenance in the existing bypass corruption;
- this report and its architecture authority.

No Graphics, SVG, Plots, collection/File implementation, mathematical example,
commit or remote state was changed for this milestone. Unrelated user changes
present in the worktree were preserved.

## Remaining ReplaceOwned blockers

The former “SSA owning dereference Store evasion” blocker is resolved. The
parent capability remains **PARTIAL** because independent issues remain:

1. general non-lexical borrow/view liveness metadata is still absent outside
   the closed call/format/iteration regions;
2. the global class/interface-handle-in-struct conflict remains unresolved;
3. typed per-identity lifecycle events and some FieldId/drop-flag/backend
   corruption gates remain incomplete;
4. repository-wide Clippy remains red on the preexisting frontend warnings.

Therefore `SSA-STORE-PROVENANCE-V1` is CLOSED, while
`OWNING-STRUCT-FIELD-REPLACEMENT-V1` is not.
