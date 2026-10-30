# OWNING-STRUCT-FIELD-REPLACEMENT-V1 — final qualification report

Status: **CLOSED**, updated 2026-10-30.

Normative authorities:

- [OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1](OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md);
- [OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1-AMENDMENT-1](OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1_AMENDMENT_1.md);
- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md).

The CLOSED
[SSA-STORE-PROVENANCE-V1](SSA_STORE_PROVENANCE_V1_REPORT.md) result is a
regression baseline, not duplicated qualification work. This report closes
only `OWNING-STRUCT-FIELD-REPLACEMENT-V1`.

## Result

All normative guarantees of the amended V1 profile are verified. The final
qualification found no new admitted safety bypass and required no production
compiler or runtime correction. It added missing tests for lexical and explicit
borrow endings, reborrow/view propagation, control flow, corruption at each IR
layer, and lifecycle by logical allocation identity.

The implementation remains deliberately conservative. Ordinary local
references/views live to lexical scope end. Only call/format regions with a
verified `End` and already-delimited iteration regions can end earlier. No
general NLL inference, new reference feature, storage surface, public hook,
runtime ABI change or `noalias` promise was introduced.

Class/interface handles in structs remain negative E0274 cases. A symbolic
`T: Storable` still cannot authorize `ReplaceOwned`; the exact concrete
`TypeId` must independently be Storable, Relocatable, non-Copy and drop-needing.

## Final qualification matrix

| Area | Result | Reproducible evidence |
|---|---|---|
| Buffer direct, nested, `ref mut Buffer`, `ref mut Struct` | PASS | dedicated native O0/O2 cases retain `ReplaceOwned` through HIR/MIR/SSA |
| Array, List, Vector and Matrix | PASS | concrete type matrix at O0/O2; element/view alias negatives |
| nested aggregate, concrete generic instance | PASS | aggregate replacement, concrete `Box<Buffer<int>>` and typed lifecycle |
| consecutive `v0 -> v1 -> v2` | PASS | identity ledger observes publish(v1), Drop(v0), publish(v2), Drop(v1), final Drop(v2) |
| owning siblings | PASS | two sibling identities remain readable and each receives one final Drop |
| RHS borrow closed before commit | PASS | verified `EndBorrow` precedes `ReplaceOwned` in MIR and SSA |
| lexical last-use before scope end | PASS | rejected; last use does not synthesize NLL |
| reborrow/reference and view copies | PASS | same-root reference copy and MatrixView copy reject replacement |
| branches, joins and later use | PASS | live predecessor borrow rejects at join; post-replacement use and invalid End metadata reject |
| element/backing/view alias | PASS | Buffer, Array, List, Vector, Matrix and nested aggregate negatives |
| independently rooted local owner | PASS | distinct-owner element reference remains admitted in O0/O2 |
| unknown parameter alias | PASS | HIR/MIR/SSA independently reconstruct `may_borrow_storage_of` |
| class/interface struct fields | PASS (negative) | E0274 remains authoritative |
| symbolic `T: Storable` | PASS (negative) | rejected without concrete Drop/Relocatable proof |
| RHS throw and later throw | PASS | old survives pre-commit throw; RHS temporary and committed new clean once |
| early return and normal/exceptional cleanup | PASS | focused ownership/exception suites and workspace |
| string regression | PASS | existing `ReplaceString` remains publish-before-release at O0/O2 |

## Borrow and alias evidence

The dedicated qualification now demonstrates that:

- a borrow synthesized only for a call in the RHS closes with `EndBorrow`
  before the replacement commit;
- a local reference whose last source use already occurred remains live until
  lexical scope end and blocks replacement;
- copying a reference or a view preserves its owner/storage provenance;
- branches do not erase a live region at a join, and a later dereference cannot
  make an otherwise invalid replacement legal;
- aliases to collection elements/backing and mathematical views reject through
  the shared topology query;
- an element reference proven to originate from a different local owner does
  not block replacement;
- replacement through a parameter remains conservative when another parameter
  may reach the owner or backing storage.

MIR and SSA call-region corruption changes `argument_index` on `End` metadata
and removes the End by replacing it with an ordinary use. Both layers reject
independently. Existing borrow qualification additionally covers CFG region
disagreement, dominance, escaping uses and temporary cleanup.

No concrete route was found that executes `ReplaceOwned`, destroys old backing
and subsequently uses a reference/view derived from that backing.

## Corruption matrix

| Layer / mutation | Result |
|---|---|
| HIR `ReplaceOwned -> Assign`, TypeId, FieldId/projection | PASS: rejected |
| HIR writability, initialization, property and alias contract | PASS: rejected by dedicated and structural cases |
| MIR TypeId/RHS, FieldId/projection, shared dereference, Index | PASS: rejected |
| MIR root drop-flag transition adjacent to replacement | PASS: rejected as unpaired transition |
| MIR RHS obligation omitted/another RHS consumed twice | PASS: ownership ledger rejects |
| MIR duplicate replacement consumption, unwind added | PASS: rejected |
| MIR `ReplaceOwned -> Move` on owning dereference | PASS: rejected |
| SSA TypeId/place/value, FieldId/projection | PASS: rejected |
| SSA RHS obligation omitted/another RHS consumed twice | PASS: ownership ledger rejects |
| SSA duplicate consumption, borrow/End mismatch or End removed | PASS: rejected |
| SSA unwind added, `ReplaceOwned -> Store` | PASS: rejected; Store provenance baseline retained |
| backend old Drop omitted | PASS: identity ledger detects in O0 and O2 |
| backend old Drop duplicated | PASS: identity ledger detects in O0 and O2 |
| backend old Drop moved before publish | PASS: identity ledger detects in O0 and O2 |

The SSA Store Provenance corruption suite remains separately green and was not
copied into this suite.

## Lifecycle by identity

`owning_struct_field_replacement_v1` injects a ledger only into the generated
LLVM string used by the test executable. It does not alter compiler output,
runtime source, ABI or public API. The ledger assigns a logical identity to
each `aether_alloc`, retains allocations during the short probe so host pointer
reuse cannot conflate identities, and records publication and Drop stage.

For the consecutive replacement fixture it verifies distinct v0/v1/v2
obligations, publish-before-Drop at each commit, exactly one final Drop of v2,
and preservation plus one final Drop for two siblings. For the exception
fixture one static replacement is invoked with a throwing RHS and then
successfully: there is no first publication/Drop of old, the initialized RHS
temporary is cleaned once, and the later commit and cleanup retain exact
identity. The event contract is identical at O0 and O2.

The same harness runs against LLVM mutations that omit, duplicate or move the
first old Drop before its store. Every mutation is detected at both optimization
levels. Static LLVM inspection independently retains store-before-drop.

## Gates

Commands ran from `compiler-next` on the final tree unless stated otherwise.

| Gate | Result | Evidence |
|---|---|---|
| `cargo test -p aether-driver --test owning_struct_field_replacement_v1` | PASS | 16/16; native O0/O2, identity ledger and backend mutations |
| `cargo test -p aether-driver --test ssa_store_provenance_v1` | PASS | 5/5 baseline regressions |
| ownership, collections and exceptions focused command | PASS | 50/50 across early return, ownership ergonomics, class Buffer, Matrix add and exception v1-v4 |
| `cargo test -p aether-frontend -p aether-middle` | PASS | 75 frontend + 29 middle; doc tests PASS |
| `cargo test -p aether-driver --test vertical` | PASS | 220/220 |
| `cargo test --workspace` | PASS | final-tree rerun exited 0; includes the real linear-algebra registry consumer in O0/O2 |
| `cargo fmt --check` | PASS | final Rust tree formatted |
| global targeted Clippy with `-D warnings` | FAIL (PREEXISTING) | frontend `assert_is_empty`/`needless_borrows_for_generic_args`, then middle `match_same_arms`, `too_many_lines`, `single_match_else` and `manual_let_else`; sites are outside this delta |
| Clippy on modified Rust scope | PASS | driver qualification test passes `--no-deps -D warnings`; frontend all-targets passes after allowing only the two enumerated preexisting frontend lints |
| repository `git diff --check` | PASS | no whitespace errors, including preserved unrelated user changes |

The focused regression command included
`owning_struct_field_replacement_v1`, `ssa_store_provenance_v1`,
`owning_param_early_return_v1`, `linear_algebra_ownership_ergonomics_v1`,
`class_buffer_fields_v1`, `matrix_add_v1` and `exception_v1` through
`exception_v4`.

The global Clippy result is not relabeled PASS. Its diagnostics are in
unchanged frontend/middle code and reproduce the previously recorded tooling
debt. The equivalent gate over both modified Rust scopes passes, so under
Amendment §7 this preexisting tooling failure is not a regression and does not
block the semantic milestone.

## Files changed by final qualification

- `compiler-next/crates/aether-driver/tests/owning_struct_field_replacement_v1.rs`:
  borrow/alias, corruption and per-identity lifecycle qualification;
- `compiler-next/crates/aether-frontend/src/hir.rs`: HIR FieldId corruption test;
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`: amended CLOSED status
  and definitive lexical/explicit-region profile;
- this report.

The amendment and its review report were pre-existing untracked inputs and
remain preserved. No Graphics, SVG, Plots, personal example, production
dependency, production compiler/runtime code, commit or remote state was
changed by this closure.

## Final state

`OWNING-STRUCT-FIELD-REPLACEMENT-V1` is **CLOSED** because the amended type,
borrow/alias, ownership, exception, corruption, backend ordering and O0/O2
guarantees all have reproducible evidence, and no essential gate is blocked.
The absence of general NLL and the E0274 class/interface storage prohibition
are explicit V1 boundaries rather than unverified guarantees.
