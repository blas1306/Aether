# RUST-IR-3 authority-promotion implementation

Status: `RUST_INITIAL_IR_AUTHORITY_PROMOTION_PENDING_CI`

This document records Phase A only. It is not a closure record and does not
claim `RUST_INITIAL_IR_AUTHORITY_PROMOTED`.

## Prerequisite

The public GitHub API was queried on 2026-09-01 rather than relying on local
documentation. It reported:

- workflow: `.github/workflows/rust-ir-pre-lifecycle-shadow-qualification.yml`;
- workflow ID: `347123867`;
- successful run: `33465504645`;
- exact qualified revision: `bd156a52757721fba552231fa88ac7083b715b6d`;
- event: `workflow_dispatch`;
- conclusion: `success`;
- 21 mandatory jobs, all `success`;
- 21 unexpired artifacts with official IDs, names, and GitHub SHA-256 digests;
- failed runs `33462871203` and `33464649897` remain failed/blocked.

The anonymous GitHub archive endpoint returned HTTP 401, so this local Phase A
session could not download and replay the aggregate ZIP. The dedicated RUST-IR-3
prerequisite job uses `${{ github.token }}` to download all 21 official ZIPs,
compare every GitHub digest, rerun the RUST-IR-2 checker, and fail closed before
any promotion qualification can succeed.

## Authority boundary reconstructed

Before this change, the productive call sites were:

```text
IRLowerer
  -> Python IRVerifier AND Rust verify_module (PRE-lifecycle)
  -> Python LifecycleExpander
  -> Rust-owned SSA/refinement authority and remaining pipeline
```

Python and Rust could both block Initial IR admission. The post-optimization
Python `IRVerifier` was also a productive check. No productive Rust
`verify_module` call existed after lifecycle expansion.

After this change:

```text
IRLowerer
  -> Rust verify_module (exclusive PRE-lifecycle product authority)
  -> Python LifecycleExpander (unchanged product lifecycle authority)
  -> remaining pipeline
```

Python `IRVerifier` remains available through the explicit differential
pipeline, tests, qualification, and diagnostic APIs. Rust rejection is final;
there is no fallback or rescue path. Default post-lifecycle optimization no
longer consults Python `IRVerifier`; explicit custom/debug coordinators retain
their oracle behavior.

## Invariant audit

Source audit found 144 Python invariant IDs and all 150 Rust invariant IDs.
There are no Python-only semantic invariant IDs. Rust additionally enforces
`IRV-012`, `IRV-013`, `IRV-014`, `IRV-015`, `IRV-022`, and `IRV-035` as
legitimate structural/data-flow checks. The generated authority-contract
artifact contains a 22-row matrix covering:

- module/function, struct, parameter, block, and value uniqueness;
- signatures, calls, indirect calls, returns, CFG, entry, terminators, and dominance;
- scalar, aggregate, operand/result, collection, matrix, and vector typing;
- exceptions, invoke/throw/rethrow/propagate, `may_throw`, and exceptional CFG;
- lifecycle pseudo-ops, storage state, branch initialization, move/copy/destroy,
  use-after-move, transferred storage, and constructor receiver ownership;
- borrows, scopes, escape, collection ownership, classes, interfaces, builtins,
  method results, metadata, and source locations.

The three known differences remain diagnostic-only:

- undefined slot: Python `IRV-031`, Rust `IRV-032`;
- returned storage after move: Python `IRV-050`, Rust `IRV-026`;
- inconsistent branch initialization: Python `IRV-036`, Rust `IRV-028`.

The two representation-domain exclusions remain separate from verifier parity:
lifecycle destinations not representable as `IRStorageDTO`, and Python integers
outside schema-v1 i32. Neither is treated as a product verifier divergence.

## Directed qualification results

Local execution used the native `aether-ir-verifier` binary and materialized
fixtures from their source tests:

| Campaign | Cases | Python/Rust acceptance divergences |
|---|---:|---:|
| Directed false-negative search | 150 | 0 |
| Directed Rust-stricter search | 130 | 0 |
| Positive post-switch differential | 130 | 0 |
| Mutation post-switch differential | 150 | 0 |
| Critical PRE-lifecycle IRV-041 boundary | 2 | 0 |

Each directed campaign includes 75 or 65 historical seeds plus a reproducible
four-block unreachable-CFG composition for every seed. Divergence records carry
case identity, source test, request SHA-256, both decisions/diagnostics, and the
full serialized fixture. No `Python REJECT / Rust ACCEPT` or `Rust REJECT /
Python ACCEPT` case was found.

The deep/stress artifact repeats the 130 valid cases with exact CFG sizes. The
performance artifact records Python-oracle baseline cost, serialization, Rust
invocation, cold import, before/after stage totals, and makes no universal
speedup claim. No pathological timeout was observed locally.

## Product provenance and recovery

The installed product verifier probe passed and observed:

- `product_authority = rust`;
- `python_ir_verifier_role = oracle_only`;
- Rust executed and accepted PRE-lifecycle IR;
- zero Python `IRVerifier` product calls;
- canonical request SHA-256 matched an independent recomputation;
- Python `LifecycleExpander` ran after Rust acceptance;
- representative invalid IR was rejected as `IRV-018` without Python rescue;
- lifecycle and SSA construction did not run after that rejection;
- the next valid request succeeded;
- the Python oracle ran separately and did not affect the product decision;
- a representative full Rust-SSA compile succeeded with Python lifecycle and
  existing Rust refinement authority intact.

## Workflow and checker

`.github/workflows/rust-ir-authority-promotion.yml` is a new
`workflow_dispatch` workflow. It has 25 distinct mandatory jobs: prerequisite,
authority audit, both directed searches, regression/mutation/IRV-041,
provenance/no-rescue/lifecycle, packaged/source/recovery/transport/deep/
performance, four platforms, four CPython versions, and aggregate fail-closed.

The aggregate downloads every producer artifact twice: extracted evidence via
`actions/download-artifact` and the official ZIP via the GitHub API. It records
artifact ID, name, source job, run, revision, kind, role, status, GitHub digest,
ZIP SHA-256, and evidence SHA-256. The checker rejects missing/wrong identities,
Python product authority, Rust absence, either acceptance divergence, fallback,
lifecycle movement, wrong phase, missing environment/matrix coverage, or any
aggregate inconsistency. Adversarial tests cover each major fail-closed branch.

## Validation

Local results:

- new authority and checker tests: 47 passed;
- historical Initial IR/shadow/SSA coordination tests: 129 passed;
- full suite: 5,274 passed, 4 skipped, 26 failed;
- 24 failures are the pre-existing LeakSanitizer-under-ptrace environment
  limitation (`LeakSanitizer does not work under ptrace`), unrelated to this change;
- the remaining two corpus-capture failures were fixed by teaching the migration
  harness to observe the new product Rust admission boundary; both focused
  integration tests then passed.

No schema-v1/schema-v2, protocol-v1, transport, PyO3, SSA construction,
`verify_owned_ssa`, SSA refinement verifier, optimizer implementation, LLVM
backend, runtime, Python `SSAVerifier`, or Python `SSARefinementVerifier` contract
was changed. Python `LifecycleExpander` remains the productive lifecycle
authority.

Official platform/Python matrices, packaged/source installations, official
aggregate, independent recomposition, and closure artifacts remain pending the
authorized push and a successful official run. No closure files exist in Phase A.
