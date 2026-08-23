# Post-Python-shadow SSA performance characterization — RUST-3.12

Decision: `RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZED`

Qualification revision: `ec4cfea41b5ae49b0038b63d39cadaf0715d6494`.

## Outcome

This is an observational recharacterization after RUST-3.11. Rust authority, the mandatory synchronous independent Python shadow, fail-closed comparison, schemas, verifiers, lifecycle, phi placement, renaming, CHK Rust, Python full-set bit-mask dominance, optimizer/backend, and rollback modes are unchanged. No productive optimization was implemented.

Across the representative ordinary corpus, Python-only is 0.638172s, diagnostic Rust-only is 1.114612s, and dual-lane is 1.811015s median per complete suite. Dual/Python is 2.84× and Rust/Python is 1.75×.

## Ordinary additive cost model

| Category | Share of dual lane |
|---|---:|
| `TRANSPORT_REPRESENTATION` | 25.64% |
| `SAFETY_VERIFICATION` | 20.68% |
| `PYTHON_SHADOW` | 20.16% |
| `RUST_INTRINSIC` | 17.49% |
| `COMPARISON` | 15.85% |
| `ORCHESTRATION_RESIDUAL` | 0.18% |

Deliberate shadow/safety/comparison policy accounts for approximately 72.07% of ordinary dual-lane wall time (including strict schema-v2 import). Inherent Rust SSA production accounts for 17.49%, and remaining transport/orchestration implementation cost for approximately 10.43%. This partition does not imply that a safety boundary may be removed.

Every raw sample records measured phase sum, explicit residual, and total. The additive categories reconcile to 100.000000000% and retain residual as `ORCHESTRATION_RESIDUAL`.

The top individual ordinary phases are:

| Phase | Share of dual lane |
|---|---:|
| `rust_schema_v2_import` | 15.38% |
| `rust_ssa_lowering` | 14.88% |
| `python_lifecycle_normalization` | 13.32% |
| `imported_rust_python_verification` | 7.90% |
| `python_result_dto_serialization` | 7.13% |

## Deep CFG

| Blocks | Python-only | Rust-only | Dual-lane | Dual/Python | Rust/Python | Largest category | Dominant Python phases |
|---:|---:|---:|---:|---:|---:|---|---|
| 100 | 0.030479s | 0.035234s | 0.063169s | 2.07× | 1.16× | PYTHON_SHADOW (39.87%) | liveness, lifecycle_normalization, builder_verification |
| 1000 | 0.311267s | 0.355420s | 0.726800s | 2.33× | 1.14× | SAFETY_VERIFICATION (31.48%) | lifecycle_normalization, builder_verification, renaming |
| 5000 | 1.871612s | 1.568431s | 3.798326s | 2.03× | 0.84× | SAFETY_VERIFICATION (29.20%) | lifecycle_normalization, builder_verification, renaming |
| 10000 | 3.994437s | 3.680867s | 8.224154s | 2.06× | 0.92× | SAFETY_VERIFICATION (34.48%) | builder_verification, lifecycle_normalization, definite_initialization |

All three routes were measured at 100, 1,000, 5,000, and 10,000 blocks with raw repeated samples. RUST-3.11 removed dominance as the deep Python bottleneck; lifecycle normalization and verification now lead, while renaming or definite initialization follows depending on size. At 10,000 blocks the deliberate policy/safety partition is 82.67%, inherent Rust SSA is 9.80%, and remaining implementation/transport residual is 7.53%.

RSS is recorded from fresh processes. Parent and companion peaks are reported separately; their sum is explicitly labelled conservative because independent process peaks need not be simultaneous.

| Blocks | Python parent RSS | Dual parent RSS | Companion RSS | Conservative dual family sum |
|---:|---:|---:|---:|---:|
| 100 | 192184 KiB | 192184 KiB | 74724 KiB | 266908 KiB |
| 1000 | 192184 KiB | 192184 KiB | 77880 KiB | 270064 KiB |
| 5000 | 192184 KiB | 192184 KiB | 92856 KiB | 285040 KiB |
| 10000 | 192184 KiB | 192184 KiB | 159468 KiB | 351652 KiB |

## Startup and persistence

One companion process served 345 requests with 1 startup. Startup was 0.020581s, first request 0.033308s, and warm small Rust-only median 0.009749s. Startup, first request, and warm small-request samples are separate, so startup is not charged as per-request steady-state work.

## Historical interpretation

RUST-3.10 remains useful for phase definitions but its pre-bit-mask deep-CFG bottleneck is obsolete. RUST-3.11 established 4.07×/18.19× Python-shadow and 2.70×/9.98× dual-lane speedups at 1,000/5,000 blocks and a 14.69× 5,000-block RSS reduction. Cross-revision absolute timing is treated as machine-sensitive; only compatible fixtures, route definitions, and within-campaign ratios support conclusions. The Rust-only diagnostic also improved in RUST-3.11 without a Rust lowering change because imported-Rust SSA verification runs the independent Python dominance implementation; that indirect effect is not attributed to CHK.

## Candidate ranking and recommendation

| Rank | Candidate | Classification | Ordinary | Deep 10,000 |
|---:|---|---|---:|---:|
| 1 | dual-lane architecture/policy | `SHADOW_POLICY` | 56.69% | 74.39% |
| 2 | remaining Python shadow lowering | `ALGORITHMIC_CORE` | 6.83% | 17.85% |
| 3 | schema-v2 import | `SAFETY_BOUNDARY` | 15.38% | 8.28% |
| 4 | remaining Rust SSA lowering | `NOT_CURRENT_BOTTLENECK` | 14.88% | 7.90% |
| 5 | imported Rust SSA verification | `SAFETY_BOUNDARY` | 7.90% | 13.67% |
| 6 | Python lifecycle normalization | `LOW_RISK_IMPLEMENTATION` | 13.32% | 8.35% |
| 7 | Python lifecycle verification | `SAFETY_BOUNDARY` | 6.37% | 12.41% |
| 8 | DTO/serialization/transport | `LOW_RISK_ARCHITECTURAL` | 10.26% | 7.46% |
| 9 | Python renaming | `ALGORITHMIC_CORE` | 2.69% | 3.43% |
| 10 | canonical comparison | `SAFETY_BOUNDARY` | 2.96% | 1.69% |

Recommended next milestone: audit and qualify Python lifecycle normalization as a semantics-preserving implementation target. Mandatory verification, canonical comparison, and the independent shadow architecture remain safety/policy boundaries even where their measured cost is large. The answer is regime-dependent: ordinary work retains material representation/transport cost, while deep CFG is led by Python lifecycle, verification, and renaming after dominance ceased to dominate.

## Method and qualification

The representative eight-workload RUST-3.10/3.11 corpus is unchanged. Routes rotate each round after warmups. The JSON contains every raw profile, min/median/max/sample count/total wall, phase/category reconciliation, growth ratios, RSS, environment, startup/session counts, invariant declarations, candidate evidence, and gate results. The permanent checker validates structure and consistency only; it has no machine-speed threshold.

Production behavior did not change.
