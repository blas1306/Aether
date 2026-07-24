# IR verifier migration corpus

This directory is the Phase 0 seed corpus for differential verification of
Aether IR modules. It is an index over existing Python tests, not a second set
of semantic fixtures. The referenced tests remain the owners of their source
programs and hand-built `IRModule` objects.

`manifest.yaml` schema version 2 has two top-level corpus lists:

- `valid_modules` identifies modules accepted by the Python `IRVerifier`;
- `invalid_modules` identifies modules rejected by it and records the expected
  invariant from `docs/compiler/IR_VERIFIER_INVARIANTS.md`.

The `covers` values name the rules that a case deliberately exercises. They do
not claim every prerequisite traversed while verifying the module. For an
invalid entry, `expected_invariant` is the Python first failure after
normalization and is also present in `covers`. The Rust expectation is the same
unless the entry explicitly supplies `expected_rust_invariant` and a typed
`diagnostic_divergence`.

The three explicit compatibility expectations are:

| Case | Python | Rust | Classification | Meaning |
| --- | --- | --- | --- | --- |
| `return-storage-after-move` | IRV-050 | IRV-026 | `first_failure_ordering` | Both rules apply and both implementations reject; only the valid first failure differs. |
| `undefined-slot` | IRV-031 | IRV-032 | `representation_import_model` | Rust imports the load slot into its normalized storage model and reports uninitialized storage. This is the previously documented intentional IRV-031 representation difference. |
| `inconsistent-branch-initialization` | IRV-036 | IRV-028 | `lifecycle_dataflow_semantics` | Rust preserves possible merge states and permits a later total transfer to repair them, while Python rejects the divergence immediately. This is the previously documented IRV-036 improvement. |

These cases are not one collective class of fail-fast ordering differences and
must not be silently ignored.

Phase 4.5C resolved the former outcome expectation for
`non-void-path-without-return`. Python now applies the same entry-reachable graph
semantics as Rust, so the case remains in the corpus as accepted history and is
classified `MATCH_ACCEPTED`; its old
`intentional_irv_024_graph_analysis` manifest exception was removed.

The current run over the 141 schema-v1-transportable cases reports 65 accepted
by both, 73 exact first-invariant matches, three documented diagnostic
divergences, zero documented outcome divergences, and zero unexpected
divergences.

Phase 4.5A adds the 13-case critical differential subset documented in
[`CRITICAL_DIFFERENTIAL_CORPUS.md`](CRITICAL_DIFFERENTIAL_CORPUS.md). Those
entries are grouped by semantic family in the manifest and continue to use
pytest-owned module materializers instead of duplicating canonical DTO JSON.

## Reference contract

Each `test` value is a repository-relative pytest node without a parameter
suffix. `parameter_case`, when present, selects a collected parameter case by
its one-based order. `verifier_invocation` selects the one-based call to
`IRVerifier.verify()` made while that selected test runs. It is omitted when
the test makes exactly one relevant call.

The invocation ordinal is important for existing tests that first verify a
valid lowered module and then verify one or more deliberately corrupted copies.
It also allows a single lifecycle test to expose several modules without moving
its builders or duplicating their instructions here.

This manifest records the current Python test as both module materializer and
behavioral oracle. It does not make pytest execution itself part of the future
interchange format.

`fixtures/ir_module_v1_golden.json` is the separate, small canonical schema-v1
wire fixture. It locks JSON formatting and complete root DTO reconstruction; it
is not a semantic-verifier corpus case and is therefore not listed in
`manifest.yaml`.

## Future differential consumer

Once the versioned ModuleDTO adapter exists, the differential harness will:

1. collect the referenced pytest case and intercept the selected verifier
   invocation;
2. serialize that invocation's `IRModule` once through the shared ModuleDTO
   adapter;
3. run the Python verifier and Rust verifier independently on equivalent owned
   input;
4. compare acceptance/rejection before inspecting diagnostics;
5. for two rejections, compare stable invariant IDs against the Python and Rust
   expectations without using diagnostic messages as semantic identity;
6. classify each comparison as an outcome mismatch, exact diagnostic match,
   documented diagnostic divergence, or unexpected diagnostic divergence;
7. report a mismatch with the manifest `id`, schema version, and the smallest
   available serialized reproduction.

A diagnostic divergence is documented only when the observed ordered pair
exactly equals `expected_invariant` and `expected_rust_invariant`. A different
pair is unexpected even for a case that has a documented divergence. When both
implementations accept, outcome parity is recorded and no rejection diagnostic
is compared. An outcome mismatch remains visible in the outcome report even
when `expected_rust_outcome` and `outcome_divergence` make it a known
compatibility expectation.

The capture step is transitional. When a stable checked-in DTO snapshot is
useful, an entry may gain a snapshot reference while retaining `test` as its
provenance and semantic owner. Snapshot creation must not copy Aether source or
hand-built IR into this directory.

## Scope

The seed set draws from the direct IR verifier suite, lifecycle and borrow
checks, and focused enum, integer, builtin, callable, collection, and linear
algebra tests. Tests for `SSAVerifier` and SSA dominance are intentionally not
part of this IR-verifier corpus. Broad pipeline/native parity tests remain
valuable integration oracles, but are not indexed unless they expose a focused
IR verifier invocation.

The current verifier test inventory has three layers:

- `test_ir_verifier.py` owns the primary valid and invalid hand-built modules;
- `test_ir_lifecycle.py` and `test_const_collection_borrowed_for.py` own the
  lifecycle and borrowed-value rules;
- focused tests for collection copy/slicing, enums, i32 constants, logical not,
  lists, string builtins, struct layouts, typed callables, and vector/matrix
  operations supply the remaining entries in this initial manifest.

Other tests that currently invoke `IRVerifier`—array safety/slicing, control-flow
characterization/regressions, equality, `for` lowering, list bounds, and string
concatenation—are broader integration coverage. They are candidates for later
manifest expansion, but adding them now would repeat already indexed verifier
rules rather than add a focused invariant case. `test_ssa_verifier.py`,
`test_ssa_dominance_verifier.py`, and other SSA tests belong to the later SSA
migration corpus.

Adding a case should normally mean adding a manifest reference to an existing
test. Add a new semantic test only when no current test can express the missing
invariant. Keep IDs unique, keep parameter/invocation ordinals explicit when
needed, and update an entry if its owning test is refactored.
