# Rust SSA post-3.8a performance characterization — RUST-3.8b

Decision: `RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED`

## Result

Exact revision `cccf3c507c08fb319a407fcbf5070d62b6cda630` was measured
after RUST-3.8a. No optimization was implemented. From verified Initial IR, the
eight-workload representative suite produced:

| Mode | Median | Min | Max | Samples |
|---|---:|---:|---:|---:|
| `PYTHON_SSA_ONLY` | 177.020 ms | 156.618 ms | 193.624 ms | 7 |
| diagnostic Rust-only | 311.029 ms | 287.758 ms | 344.576 ms | 7 |
| `RUST_SSA_AUTHORITY_PYTHON_SHADOW` | 503.742 ms | 491.678 ms | 532.266 ms | 7 |

The dual/Python ratio is **2.846x** and Rust-only/Python is **1.757x**. Rust-only
therefore remains slower than Python-only. `rust_ssa_lowering` is the largest
Rust-intrinsic phase and the largest individual phase overall.

These are observational, machine-local results, never semantic thresholds. Raw
samples, digests, environment, workload shapes and bounded statistics are in
`rust_ssa_post_3_8a_performance_characterization.json`.

## Current residual model

The phase ranking uses each phase's representative-suite median divided by the
dual-lane median. Independently selected phase medians need not add to the wall
median. Categories instead add every measured dual-lane sample and therefore
sum to exactly 100%.

| Rank | Surviving phase | Median | Dual median | Category |
|---:|---|---:|---:|---|
| 1 | Rust SSA lowering | 86.282 ms | 17.128% | intrinsic Rust work |
| 2 | schema-v2 import | 61.154 ms | 12.140% | transport/import |
| 3 | Python lifecycle normalization | 42.792 ms | 8.495% | Python shadow work |
| 4 | Python verification of imported Rust SSA | 41.895 ms | 8.317% | safety/verification |
| 5 | Python builder verification | 39.094 ms | 7.761% | safety/verification |
| 6 | Python SSA lowering | 36.845 ms | 7.314% | Python shadow work |
| 7 | Python result DTO serialization | 30.373 ms | 6.029% | comparison |
| 8 | Rust canonicalization | 21.421 ms | 4.252% | comparison |
| 9 | Python canonicalization | 19.650 ms | 3.901% | comparison |
| 10 | Initial IR integrity check | 17.129 ms | 3.400% | safety/verification |

The remaining measured phases, in order, are canonical comparison (15.980 ms),
request/response transport and serialization (15.914 ms), Rust lifecycle
normalization (15.610 ms), Initial IR snapshot preparation (13.613 ms), Rust
Owned SSA verification (11.775 ms), Rust transport serialization, response JSON
decode, Rust input parsing, schema-v2 materialization, orchestration residual and
steady-state process startup. The JSON evidence reports median, min, max, sample
count, percentage and category for every phase.

| Category | Current dual-lane share |
|---|---:|
| transport/import | **24.154%** |
| safety/verification | **21.702%** |
| intrinsic Rust work | **20.498%** |
| comparison | **17.452%** |
| Python shadow work | **16.078%** |
| orchestration | **0.115%** |

Thus the requested overhead split is 20.498% intrinsic Rust, 16.078% duplicated
Python shadow lifecycle/lowering, 21.702% safety verification, 24.154%
transport/import and 17.452% canonical comparison/DTO work. The final 0.115% is
orchestration. Verification is separated from the shadow's intrinsic
lifecycle/lowering so the categories are mutually exclusive.

## RUST-3.8a removed work and RUST-3.7b comparison

The following historical phases are explicitly **removed/not executed**:

| Phase | RUST-3.7b share | Current share | RUST-3.8a effect |
|---|---:|---:|---|
| Python shadow input reconstruction | 8.751% | 0% | original verified Initial IR is reused |
| duplicate Python shadow verification | 5.706% | 0% | builder's unchanged verified result is trusted |
| Rust-result DTO reserialization | 4.598% | 0% | received schema-v2 DTO is reused |

For an apples-to-apples category view, the RUST-3.7b raw samples were
reclassified with the current mutually exclusive mapping:

| Category | RUST-3.7b | Post-3.8a | Interpretation |
|---|---:|---:|---|
| intrinsic Rust work | 14.893% | 20.498% | larger share after redundant costs disappeared |
| Python shadow work | 23.733% | 16.078% | input reconstruction was removed |
| safety/verification | 22.472% | 21.702% | one duplicate verifier was removed; mandatory boundaries survive |
| transport/import | 18.407% | 24.154% | now the largest residual category |
| comparison | 20.063% | 17.452% | Rust DTO reserialization was removed |
| orchestration | 0.433% | 0.115% | negligible residual |

These are normalized percentages from independent campaigns. They explain the
composition change but do not make raw cross-machine medians causal. The full
phase-by-phase old/current table is machine-readable in the JSON evidence.

## Workload manifest

The RUST-3.7b stratification was retained: two warmups and seven rotated
measured rounds per workload, with canonical output digests checked across all
three modes.

Reproduce the complete campaign with:

```text
.venv/bin/python scripts/characterize_rust_ssa_post_3_8a.py \
  --revision cccf3c507c08fb319a407fcbf5070d62b6cda630 \
  --executable compiler-rs/target/release/aether-ssa-shadow \
  --warmup 2 --rounds 7 --deep-cfg-rounds 3 \
  --deep-cfg-sizes 1000,5000
```

| Class | Versioned program | Python | Rust-only | Dual |
|---|---|---:|---:|---:|
| tiny/scalar | `benchmarks/arithmetic.ae` | 1.679 ms | 3.407 ms | 4.847 ms |
| numeric iterative | `benchmarks/nested_loops.ae` | 1.319 ms | 2.465 ms | 3.775 ms |
| collection-heavy | `benchmarks/list_for_sum.ae` | 1.864 ms | 3.955 ms | 6.470 ms |
| struct-heavy | `examples/structs/custom_constructor_and_equality.ae` | 1.376 ms | 3.134 ms | 5.111 ms |
| class/interface-heavy | `examples/classes/implements_interface.ae` | 1.097 ms | 2.057 ms | 3.587 ms |
| indirect call | `corpus/exceptions/positive/indirect_call.ae` | 1.875 ms | 3.055 ms | 5.660 ms |
| exception/lifecycle | `corpus/exceptions/positive/cleanup_during_unwinding.ae` | 2.876 ms | 5.152 ms | 8.777 ms |
| realistic medium | `examples/expense_tracker/Main.ae` | 165.040 ms | 287.670 ms | 465.230 ms |

The realistic program dominates the aggregate; the per-class results therefore
remain part of the evidence rather than treating the aggregate as universal.

## Deep-CFG characterization

Deep CFG used the qualified linear generator, two warmups and three measurements
per mode and size:

| Blocks | Python-only median | Rust-only median | Dual median | Rust lowering median |
|---:|---:|---:|---:|---:|
| 1000 | 0.371 s | 0.400 s | 0.680 s | 0.237 s |
| 5000 | 9.728 s | 10.543 s | 17.371 s | 7.002 s |

For a 5x block increase, Python-only grew **26.25x**, Rust-only **26.35x**, dual
**25.54x**, and Rust SSA lowering **29.54x**. This strongly justifies a separate
dominator/SSA algorithm milestone for large and deep CFGs. It is not a formal
complexity proof; it is empirical behavior consistent with the known explicit
dominator-set implementation documented as `O(V^2)` space.

## Startup and steady state

The release companion started once and served 165 requests. Startup was
1.182 ms; the first tiny diagnostic request was 4.280 ms, so startup was 27.63%
of that cold request. The steady tiny diagnostic median was 3.407 ms over seven
samples, with zero further starts. Startup is material for one tiny cold request
but only about 0.235% of the 503.742 ms representative dual-lane suite and is
amortized across the persistent session. No startup optimization was made.

## Candidate audit

| Candidate | Classification | Reason |
|---|---|---|
| Rust SSA lowering | `ALGORITHMIC_CORE` | semantic Cytron/dominator-dependent lowering core |
| Rust lifecycle normalization | `ALGORITHMIC_CORE` | implements ownership and lifecycle semantics |
| Rust Owned SSA verification | `SAFETY_BOUNDARY` | mandatory native verifier |
| request/response transport + serialization | `LOW_RISK_ARCHITECTURAL` | allocation/framing can be improved while preserving the wire contract |
| schema-v2 import | `SAFETY_BOUNDARY` | strictly validates and constructs the authoritative object |
| Python verification of imported Rust SSA | `SAFETY_BOUNDARY` | preserves cross-language verification diversity |
| Python shadow lifecycle/lowering/verification | `SHADOW_POLICY` | mandatory synchronous oracle policy |
| canonicalization/comparison | `SAFETY_BOUNDARY` | fail-closed semantic parity boundary |
| integrity check | `SAFETY_BOUNDARY` | detects mutation after direct Initial IR reuse |
| dominator implementation | `ALGORITHMIC_CORE` | replacement changes the SSA algorithm and needs dedicated qualification |

Schema-v2 import remains a major cost: **12.10%** of additive dual-lane time and
the second-largest individual median. Canonicalization plus structural comparison
is **11.47%**; it is worth retaining as a secondary representation-allocation
target, but not the next dedicated milestone because it is a fail-closed safety
boundary and no surviving redundancy has been proven.

The best expected benefit/risk target is a **transport/serialization allocation
and representation-efficiency milestone**. Transport/import is the largest
category, and the transport/serialization subset accounts for 12.05% while
being architectural rather than algorithmic. It must preserve schema-v1,
schema-v2, protocol-v1, strict import validation, authority, synchronous shadow
and fail-closed comparison. Dominator replacement should follow as a separate,
higher-risk algorithmic milestone because deep-CFG evidence clearly warrants it.

## Observational isolation and qualification

Instrumentation remains opt-in. Production does not request or consume timing
metadata. Rust-only is a diagnostic function, is absent from
`SSALoweringAuthorityMode`, and cannot be selected by `SSAPipeline`. Rust SSA
remains authoritative, `GeneralSSABuilder` remains synchronous and mandatory,
and comparison remains fail closed. Schemas, protocol, lifecycle/lowering and
verifier/canonicalizer semantics, optimizer/backend, policies and rollback modes
are unchanged.

Environment: Linux 7.1.8 x86_64, 12 logical CPUs, Python 3.14.7, rustc 1.97.1,
Cargo 1.97.1, release companion. Timings begin at verified Initial IR and exclude
frontend, optimizer and backend.

Qualification covers performance contracts and accounting, PV2-G15 exact-
revision acceptance, RUST-3.8a regression/source contracts, authority/shadow and
production-stabilization tests, the 116-program historical corpus, release Rust
workspace tests, and `git diff --check`. Timing values remain non-gating.

Executed results:

- Post-3.8a checker: 12/12 evidence contracts passed.
- Performance, PV2-G15, RUST-3.8a and focused authority tests: 26 passed.
- Shadow, authority promotion, stabilization and requalification tests: 29 passed.
- Frozen historical corpus: 116/116 accepted.
- `cargo test --workspace --locked`: passed, including the permanent 5000-block
  stack-safe lowering/verifier regression.
- Python syntax compilation and `git diff --check`: passed.

## Limitations

- Wall-clock measurements depend on machine and load.
- The manifest is representative, not a model of every Aether program.
- Final Rust response serialization and IPC cannot yet be separated.
- Deep-CFG timing supports prioritization but does not prove asymptotic complexity.
- Raw RUST-3.7b and post-3.8a medians are not treated as causal comparisons.

No commit was created.
