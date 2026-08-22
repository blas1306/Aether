# Rust SSA redundant-work optimization — RUST-3.8a

Decision: `RUST_SSA_REDUNDANT_WORK_OPTIMIZED`

## Outcome

RUST-3.8a removes three measured computations from the Rust-authoritative,
Python-shadowed coordinator without changing either lowering algorithm or any
correctness boundary. Production remains
`RUST_SSA_AUTHORITY_PYTHON_SHADOW`: Rust schema-v2 SSA is returned only after
the mandatory synchronous `GeneralSSABuilder` shadow matches, and every failure
still aborts compilation.

On the same Linux x86_64 worktree, release companion and eight-workload suite,
the dual-lane median fell from **686.994 ms** to **504.872 ms** (a **26.51%**
reduction). Its measured ranges did not overlap: the after maximum was
521.919 ms and the before minimum was 646.751 ms. The Python-only and diagnostic
Rust-only controls became slower during the after run, so control drift cannot
account for the dual-lane improvement.

## Implemented reuse

1. The Python shadow consumes the original verified `IRModule`. The schema-v1
   snapshot is created immediately beforehand from that object and Rust still
   receives its exact serialized bytes. `GeneralSSABuilder` now documents its
   non-mutating input contract, regressions compare the old reconstructed path
   with direct reuse, and the existing post-lowering DTO equality check remains
   fail-closed.
2. The coordinator no longer invokes `SSAVerifier` a second time on the exact
   `SSAModule` that `GeneralSSABuilder` has just verified. There is no mutation
   or transformation between those points. The Rust Owned verifier, the Python
   verifier over imported Rust SSA and the builder's Python oracle verifier all
   remain mandatory.
3. Canonical comparison reuses the received Rust schema-v2 DTO after it has
   passed strict import and independent Python verification. Previously the
   imported object was serialized back into the same DTO shape solely for the
   comparison. `canonical_ssa` deep-copies its input, so transport state is not
   mutated and reuse ends with each compilation.

The removed phase medians were:

| Phase | Before | After |
|---|---:|---:|
| Python shadow input reconstruction | 61.283 ms | eliminated |
| duplicate Python shadow verification | 39.727 ms | eliminated |
| Rust result DTO reserialization | 32.487 ms | eliminated |

## Audit inventory

The full machine-readable inventory is in
`rust_ssa_redundant_work_optimization.json`. The retained correctness boundaries
are Initial IR DTO creation and transport serialization, Rust response decode,
schema-v2 import, Rust Owned verification, Python verification of imported Rust
SSA, GeneralSSABuilder verification, Python result DTO materialization, both
canonicalizations, structural difference reporting, and the Initial IR
integrity reserialization.

The canonicalizer's JSON clone was rejected because changing normalization of
its public `Mapping` input could change semantics. The generic `SSAPipeline`
post-build verifier was also left untouched because it covers multiple builders
and authority modes outside the measured coordinator. Dominators were not
changed. No global or cross-compilation cache was introduced.

## Performance methodology

Both before and after used two warmups and seven measured rounds per workload,
rotating mode order, with the same release companion and the existing RUST-3.7b
eight-workload manifest. Raw temporary outputs were
`/tmp/rust_ssa_3_8a_before.json` and `/tmp/rust_ssa_3_8a_after.json`. Reproduce a
measurement with:

```text
.venv/bin/python scripts/measure_rust_ssa_authority_performance.py \
  --executable compiler-rs/target/release/aether-ssa-shadow \
  --warmup 2 --rounds 7 --deep-cfg-rounds 3 --deep-cfg-sizes 2 \
  --output <output.json>
```

| Mode | Before median | After median | Before ratio | After ratio |
|---|---:|---:|---:|---:|
| Python-only | 159.863 ms | 178.214 ms | 1.000x | 1.000x |
| diagnostic Rust-only | 295.574 ms | 314.324 ms | 1.849x | 1.764x |
| Rust authority + Python shadow | 686.994 ms | 504.872 ms | 4.297x | 2.833x |

The checked-in RUST-3.7b reference remains 162.546 ms, 304.283 ms and
702.864 ms respectively (4.324x and 1.872x). Absolute values are observational,
not semantic gates.

## Correctness and platform status

Focused optimization and Rust SSA tests pass. Historical qualification passes
116/116. Stabilization accounts for all 169 eligible programs (140 accepted,
29 rejected before SSA), with 420/420 repeated comparisons, 5,000/5,000
persistent requests and 256/256 concurrent requests. V2-L01..L05 pass, as do
the 993/1000/5000 deep-CFG gates. The first full-suite invocation reached 4,864
passes and failed only because this evidence file had not yet been materialized;
the final recheck passed with 4,865 passed, 4 skipped and 0 failed.

Linux x86_64 implementation, measurements and semantic gates were executed
locally. Official Windows x86_64, macOS arm64 and macOS x86_64 CI remain pending;
there are no platform-specific paths in this change.

After optimization, the leading phases are Rust SSA lowering (86.637 ms),
schema-v2 import (62.663 ms), Python lifecycle normalization (43.075 ms), Python
verification of imported Rust SSA (42.091 ms) and Python builder verification
(39.365 ms). A next low-risk investigation should profile schema-v2 import
allocation and compilation-local canonical representation reuse. Dominator work
belongs to a separate milestone.

No commit was created.
