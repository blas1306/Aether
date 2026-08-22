# RUST-3.6-V2 Rust SSA authority promotion

Decision: `RUST_SSA_AUTHORITY_PROMOTION_V2_FAILED`

The production authority boundary is implemented and the canonical
`SSALoweringAuthorityConfiguration` default has changed from
`PYTHON_SSA_AUTHORITY_RUST_SHADOW` to
`RUST_SSA_AUTHORITY_PYTHON_SHADOW`. The decision remains failed, rather than
claiming promotion, because fresh post-switch native evidence is available
only for Linux x86_64 in this worktree. Windows x86_64, macOS arm64, and macOS
x86_64 remain mandatory and blocked pending their native CI runners.

The local evidence revision is
`5ced223b0eaf77ef3e77e9b595f355a6ec18da42-worktree-rust-3.6-v2`; no commit was
created. The qualified base revision supplied to this milestone is
`5ced223b0eaf77ef3e77e9b595f355a6ec18da42`.

## Authority and failure behavior

For the default production path, `SSAPipeline` consumes one verified Initial IR
snapshot, runs Rust lifecycle/SSA lowering and schema-v2 import, verifies the
import, runs and verifies Python `GeneralSSABuilder` synchronously from that
same snapshot, performs the qualified canonical comparison, and returns the
Rust-imported object only after equality. The optimizer and LLVM backend
therefore receive `rust_schema_v2_import`, not the Python shadow object.

Identity-based regression tests capture both Python and schema-v2-imported
objects and assert that the returned object is the latter and is not the
former. Python shadow failure, Rust failure, malformed output, imported
verification failure, canonicalization failure, or mismatch raises and
returns no SSA. There is no fallback or automatic authority substitution.

`GeneralSSABuilder` is unchanged and remains the mandatory shadow and
differential oracle. Both configuration-only rollback modes remain:

- `PYTHON_SSA_AUTHORITY_RUST_SHADOW`
- `PYTHON_SSA_ONLY`

## Post-switch results

| Gate | Result |
| --- | --- |
| V2-L01 owning temporaries consumed by borrowed operations | PASS |
| V2-L02 nullable owning return/cast transfer | PASS |
| V2-L03 nullable constructor argument from storage | PASS |
| V2-L04 interface lifecycle defaultability / move_init | PASS |
| V2-L05 direct struct-constructor receiver release | PASS |
| Historical corpus and all eight semantic checks | 116/116 PASS |
| Expanded soak | 140/140, zero semantic or infrastructure failures |
| Adversarial | 21/21 positive and 7/7 negative PASS |
| Deep CFG | 993, 1000, and 5000 PASS |
| Full suite under Rust default | 4839 passed, 4 skipped, 0 failed |
| Failure classification | 0 semantic, 0 infrastructure, 0 environmental, 0 unclassified |
| Historical failure subset | 18/18 PASS under Rust authority |
| Native exception compatible run | 54/54 PASS |
| Persistent long session | 1000 requests / 1 process |
| Concurrency | 128 requests / 1 process |
| Linux x86_64 clean install | PASS |
| Windows x86_64 clean install | BLOCKED: fresh runner evidence absent |
| macOS arm64 clean install | BLOCKED: fresh runner evidence absent |
| macOS x86_64 clean install | BLOCKED: fresh runner evidence absent |

The full-suite denominator increased from the supplied 4837 baseline to 4839
because this change adds two deterministic RUST-3.6-V2 checker regression
tests. No existing test was removed to obtain the result.

The Linux clean-install run used a freshly built wheel outside the checkout,
packaged companion discovery, no checkout `PYTHONPATH`, and no PATH/debug
companion fallback. It made 34 lowering requests with one persistent process.
Sixteen Rust-origin modules reached optimizer/backend. Eight representative
native executions—scalar, numerical, collections, aggregate,
class/interface, exception, constructor ownership, and function-value indirect
call—matched the Python-authority baseline observably.

Fresh performance measurement is observational only. Across four workloads,
Rust-authority/Python-shadow took 11.181 times the Python-only median in this
run. There is no performance threshold and no optimization was attempted.

## CI and aggregation

The promotion workflow now runs the full suite in default
`RUST_SSA_AUTHORITY_PYTHON_SHADOW` mode, retains explicit
`PYTHON_SSA_AUTHORITY_RUST_SHADOW` and `PYTHON_SSA_ONLY` rollback jobs, and
collects exact-revision evidence from all four official native platforms.
`scripts/check_rust_ssa_authority_promotion_v2.py` is evidence-only and emits
`RUST_SSA_AUTHORITY_PROMOTED_V2` only when every gate, including all four fresh
platform reports, passes. It refuses to reuse pre-promotion platform evidence.

## Scope preservation

Initial IR schema-v1, SSA schema-v2, lifecycle policy v1, lowering policy v1,
source-location policy, bounds-checked provenance policy, canonical comparison,
optimizer semantics, and backend semantics are unchanged. Historical RUST-3.5,
failed RUST-3.6, RUST-3.6a, RUST-3.6b, and RUST-3.5b artifacts are unchanged.
No schema-v3, policy version, fallback, or commit was created.

Machine-readable local aggregation is in
`docs/compiler/rust_ssa_authority_promotion_v2.json`.
