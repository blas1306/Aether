# RUST-3.7a — Rust SSA Production Stabilization

Decision: `RUST_SSA_PRODUCTION_STABILIZATION_BLOCKED`

Qualification base: `aa0d6bf1d3316b0c425671bac768259d003f25d5`

The local Linux qualification is clear, but this checkout does not contain
fresh executed evidence for Windows x86_64, macOS arm64, or macOS x86_64.  The
decision is therefore blocked rather than inferred from the workflow or from
older promotion evidence.  CI now runs and uploads those three missing results
and can produce `RUST_SSA_PRODUCTION_STABILIZED` only when all exact-revision
gates pass.

## Frozen production contract

The repository default remains
`RUST_SSA_AUTHORITY_PYTHON_SHADOW`.  Rust-produced schema-v2 SSA is returned to
the optimizer only after the synchronous Python `GeneralSSABuilder` lane,
verification, and canonical comparison succeed.  Mismatch, malformed response,
timeout, companion failure, verifier failure, and either-lane failure remain
fail closed.  The producer performs no automatic retry.

`PYTHON_SSA_AUTHORITY_RUST_SHADOW` and `PYTHON_SSA_ONLY` remain the two
configuration-only rollback modes.  No `RUST_SSA_ONLY` mode was introduced.

The aggregate checker pins byte hashes for the readiness, failed-promotion,
lifecycle-closure, V2-readiness, and V2-promotion artifacts.  It separately
pins Initial IR schema-v1, SSA schema-v2, lowering-policy-v1, and lifecycle-
normalization-policy-v1 implementation/artifact files.  All are unchanged from
the promoted revision.

## Broadened corpus

The prior inventory covered 169 `.ae` files under `examples`, `benchmarks`,
`corpus`, and `tests`.  RUST-3.7a also audits `scrap`, including the currently
active numerical experiments, for a deterministic total of 176 discovered
programs.

| Result before SSA | Count |
|---|---:|
| Discovered | 176 |
| Accepted through verified Initial IR | 141 |
| Rejected before SSA | 35 |
| Compared in each successful round | 141 |

Every discovered path, source hash, category, acceptance state, and rejection
stage/reason is recorded in `operational.json`.  Known negative fixtures remain
outside the positive denominator; they are visible as pre-SSA rejections, not
silently discarded.  Accepted coverage includes benchmarks, numerical methods,
exceptions, collections, structs, classes, interfaces, function values,
recursion, allocation-heavy and string-heavy sources, expense tracker modules,
and realistic multi-function modules.

## Repeated and process-state stabilization

All successful requests used the same verified Initial IR snapshot for both
lanes and required Rust lowering/lifecycle success, Rust Owned SSA verification,
schema-v2 import and verification, synchronous Python SSA construction and
verification, canonical equality, and Rust-origin return.

| Gate | Result |
|---|---|
| Repeated differential soak | 3 rounds, 423/423 requests, 1 process, PASS |
| Long-lived mixed stream | 5000/5000 requests, 1 process, PASS |
| Concurrent callers | 256/256 requests, 16 callers, 1 serialized process, PASS |
| Semantic mismatches | 0 |
| Infrastructure/unclassified failures | 0 / 0 |
| Deterministic-output mismatches | 0 |
| Crashes/timeouts/poisoned-client failures | 0 / 0 |

Linux RSS was sampled without invasive tooling.  It rose from 7,225,344 bytes
after the first request to 37,302,272 bytes after request 5000, with only
782,336 bytes of growth over the second half of the session.  The gate records
this as stable after warm-up, with no continuing unexplained trend.

## Permanent regression families

The dedicated regression selection passed 155 tests.  Its explicit family
gates are source-location preservation, `bounds_checked` provenance, aggregate
ownership, class/interface ownership, constructor exceptional cleanup, nullable
ownership/casts, collection temporary ownership, and indirect calls/function
values.  V2-L01 through V2-L05 also passed independently, as did Python/Rust
deep CFG at 993, 1000, and 5000 blocks.

The first run exposed one evidence-harness defect: pytest's JUnit report can
identify a test only through dotted `classname`, while the collector expected a
`file` attribute.  This caused 155 passing tests to be reported as uncollected.
The minimized permanent regression is in
`test_rust_ssa_production_stabilization.py`; the collector now supports both
forms.  No Rust/Python SSA defect was discovered.

## Optimizer, backend, native execution, and platforms

The clean-installed Linux x86_64 product passed scalar, numerical, collection,
string, aggregate, class/interface, exception, constructor-ownership, and
function-value/indirect-call workloads.  It recorded 17 optimizer handoffs, 17
LLVM backend handoffs, 9 native comparisons against the Python-authority
baseline, all 17 three-mode matrices, one process startup, zero semantic
mismatches, and zero infrastructure failures.

| Platform | Fresh clean-install result |
|---|---|
| Linux x86_64 | PASS |
| Windows x86_64 | BLOCKED — CI evidence not present locally |
| macOS arm64 | BLOCKED — CI evidence not present locally |
| macOS x86_64 | BLOCKED — CI evidence not present locally |

Rollback is demonstrated on Linux but remains aggregate-blocked until the same
three-mode clean-install probe passes on all four official platforms.

## Full suite and incidental observations

The complete local suite under the production default passed 4853 tests with 4
skips and zero semantic, infrastructure, environmental, or unclassified
failures.  The ptrace-compatible native exception subset passed 54/54.

Observed wall time was 11.39 seconds for the repeated soak, 137.44 seconds for
the 5000-request session, and 6.16 seconds for concurrency.  These are recorded
only as observations.  There is no timing gate and no transport, SSA, optimizer,
or backend optimization in this milestone; any performance work is deferred to
RUST-3.7b.

## Reproduction and evidence

Operational evidence:

```text
python scripts/qualify_rust_ssa_production_stabilization.py \
  --revision <revision> --build --output qualification/operational.json
```

Permanent regression evidence:

```text
python scripts/qualify_rust_ssa_production_regressions.py \
  --revision <revision> \
  --executable compiler-rs/target/debug/aether-ssa-shadow \
  --output qualification/regressions.json
```

Exact-revision aggregation:

```text
python scripts/check_rust_ssa_production_stabilization.py \
  --revision <revision> --evidence-dir qualification \
  --output qualification/rust_ssa_production_stabilization.json \
  --require-stabilized
```

The checked-in aggregate is
`docs/compiler/rust_ssa_production_stabilization.json`; raw local evidence is
under `docs/compiler/rust_ssa_production_stabilization_evidence`.  CI uploads
the corpus/session result, regression result, full-suite result, each platform
result, and final aggregate separately.

No commit was created.
