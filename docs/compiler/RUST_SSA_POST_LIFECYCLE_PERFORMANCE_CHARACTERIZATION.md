# Post-lifecycle SSA performance characterization — RUST-3.14

Decision: `RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZED`

Baseline revision: `7500d66a0d830542d2436b22356e0c34698f076f`.

## Outcome

This milestone only adds opt-in diagnostics and observational evidence. Rust authority, the mandatory synchronous independent Python shadow, fail-closed behavior, schemas, protocol, canonicalization/comparison, verifiers, lifecycle/ownership semantics, CHK Rust, Python bit-mask dominance, optimizer/backend, rollback modes, and production policy are unchanged.

Ordinary corpus totals: Python-only **4.323758s**, diagnostic Rust-only **7.706167s**, and dual-lane **13.111598s**. Dual/Python is **3.03×** and Rust/Python **1.78×**.

## Additive ordinary accounting

| Category | Dual-lane share |
|---|---:|
| `TRANSPORT_REPRESENTATION` | 32.43% |
| `SAFETY_VERIFICATION` | 23.63% |
| `RUST_INTRINSIC` | 18.78% |
| `PYTHON_SHADOW` | 17.01% |
| `CANONICAL_COMPARISON` | 8.05% |
| `ORCHESTRATION_RESIDUAL` | 0.11% |

The accounting reconciles to 100.000000000% with residual explicit. The exclusive interpretive split is implementation-optimizable 24.60%, deliberate policy/safety 56.62%, inherent Rust SSA 18.78%, and unknown 0.00%. Optimizable means measured candidate work, not guaranteed removable time.

## Top 10 additive phases

| Rank | Phase | Share |
|---:|---|---:|
| 1 | `rust_ssa_lowering` | 15.74% |
| 2 | `rust_schema_v2_import` | 14.83% |
| 3 | `imported_rust_python_verification` | 8.85% |
| 4 | `python_result_dto_serialization` | 8.26% |
| 5 | `python_builder_verification` | 8.20% |
| 6 | `python_ssa_lowering` | 8.07% |
| 7 | `input_snapshot_integrity_check` | 4.24% |
| 8 | `canonical_comparison` | 3.52% |
| 9 | `initial_ir_snapshot_preparation` | 3.47% |
| 10 | `rust_lifecycle_normalization` | 3.03% |

## Lifecycle after RUST-3.13

Lifecycle normalization is 8.94% of ordinary dual-lane time. Its diagnostic decomposition is:

| Phase | Lifecycle share | Dual share |
|---|---:|---:|
| `lifecycle_operand_discovery` | 26.77% | 2.39% |
| `lifecycle_rewrite` | 23.48% | 2.10% |
| `lifecycle_operand_census` | 11.77% | 1.05% |
| `lifecycle_remaining_use_accounting` | 11.07% | 0.99% |
| `lifecycle_residual` | 8.66% | 0.77% |
| `lifecycle_owned_value_census` | 7.72% | 0.69% |
| `lifecycle_name_census` | 5.66% | 0.51% |
| `lifecycle_reconstruction` | 2.78% | 0.25% |
| `lifecycle_return_transfer_folding` | 1.12% | 0.10% |

Operand discovery is timed at its existing single reflection walk; operand census consumes the cached tuple. Rewrite and remaining-use subtraction are separated. No measurement rescan was added.

## Ordinary versus deep CFG

| Blocks | Python-only | Rust-only | Dual | Largest category |
|---:|---:|---:|---:|---|
| 100 | 0.223606s | 0.227957s | 0.474193s | `TRANSPORT_REPRESENTATION` (34.11%) |
| 1000 | 2.252654s | 2.451215s | 4.988209s | `TRANSPORT_REPRESENTATION` (31.64%) |
| 5000 | 9.816768s | 10.522892s | 20.504594s | `SAFETY_VERIFICATION` (30.00%) |
| 10000 | 19.979146s | 20.384549s | 42.590765s | `SAFETY_VERIFICATION` (30.39%) |

Ordinary and deep CFG now differ: representation/transport leads ordinary, while safety/verification leads at 5,000 and 10,000 blocks. Lifecycle stays near 11–14% in deep CFG, above its 8.94% ordinary share, but it is no longer the leading phase in either regime.

## Direct answers

1. The largest individual ordinary phase is `rust_ssa_lowering` (15.74%); `rust_schema_v2_import` follows at 14.83%.
2. The largest additive category is `TRANSPORT_REPRESENTATION` (32.43%).
3. The six-category table above gives the requested exclusive dual-lane split; residual is 0.11%.
4. Reasonably optimizable implementation work is 24.60% under the documented conservative attribution.
5. Lifecycle normalization is 8.94% of ordinary dual-lane time after RUST-3.13.
6. Operand discovery leads lifecycle (26.77%), then ordered rewrite (23.48%); every requested separable component is reported above.
7. Name census is not material: 0.51% of dual-lane time.
8. Rewrite does not dominate lifecycle; operand discovery is larger, and rewrite itself is only 2.10% of dual time.
9. Remaining-use accounting is not material at 0.99% of dual time.
10. Python builder verification (8.20%) is slightly cheaper than all lifecycle normalization (8.94%); it is not a lifecycle-specific verifier and cannot be treated as interchangeable work.
11. Python renaming is larger than lifecycle rewrite (3.30% vs 2.10%) but is an algorithmic-core, high-qualification candidate, not automatically a better target.
12. Schema-v2 import is much larger (14.83%) but is a required independent safety boundary, so its upside carries substantially higher semantic and qualification risk.
13. Transport/representation is again the strongest ordinary implementation/architecture investigation: 17.60% excluding separately-ranked schema import.
14. Deep CFG differs from ordinary as described above; safety/verification reaches 30.39% at 10,000 blocks.
15. The exclusive deliberate policy/safety cost is 56.62% of ordinary dual-lane time; shadow-policy evolution alone exposes 33.26% but is outside optimization policy.

## Historical comparison

RUST-3.13's same-process interleaved measurement remains the causal lifecycle comparison: 0.191002s → 0.095622s (2.00×), with the optimized lifecycle at 6.04% of that campaign's dual lane.

RUST-3.12 ranked schema-v2 import first, Rust SSA lowering second, and Python lifecycle third; RUST-3.14 ranks Rust SSA lowering first, schema import second, and no lifecycle subphase in the top ten. RUST-3.12's largest category and the current one are both transport/representation, but its shares and absolute times are machine- and observer-sensitive. The current 8.94% lifecycle share must not be interpreted as a regression from RUST-3.13's 6.04% because RUST-3.14 adds fine per-instruction clocks and uses a different campaign boundary.

## Memory

| Workload | Route | Parent peak | Companion peak | Conservative family sum |
|---|---|---:|---:|---:|
| ordinary corpus | `diagnostic_rust_only` | 94884 KiB | 79720 KiB | 174604 KiB |
| ordinary corpus | `python_only` | 79804 KiB | 0 KiB | 79804 KiB |
| ordinary corpus | `rust_authority_mandatory_python_shadow` | 98208 KiB | 79440 KiB | 177648 KiB |
| 5000 blocks | `diagnostic_rust_only` | 192960 KiB | 94424 KiB | 287384 KiB |
| 5000 blocks | `python_only` | 192960 KiB | 0 KiB | 192960 KiB |
| 5000 blocks | `rust_authority_mandatory_python_shadow` | 192960 KiB | 94124 KiB | 287084 KiB |
| 10000 blocks | `diagnostic_rust_only` | 192960 KiB | 159868 KiB | 352828 KiB |
| 10000 blocks | `python_only` | 192960 KiB | 0 KiB | 192960 KiB |
| 10000 blocks | `rust_authority_mandatory_python_shadow` | 192960 KiB | 159784 KiB | 352744 KiB |

Fresh processes were used. The family sum is conservative because parent and child peaks need not be simultaneous.

## Safety boundaries

| Boundary | Classification | Share |
|---|---|---:|
| Initial IR integrity | `REQUIRED_INDEPENDENT` | 4.24% |
| Rust Owned SSA verification | `REQUIRED_INDEPENDENT` | 2.34% |
| schema-v2 import | `REQUIRED_INDEPENDENT` | 14.83% |
| verification of imported Rust SSA | `REQUIRED_INDEPENDENT` | 8.85% |
| Python builder verification | `REQUIRED_INDEPENDENT` | 8.20% |
| canonical comparison | `REQUIRED_INDEPENDENT` | 3.52% |

## Candidate ranking

| Rank | Candidate | Class | Ordinary | Deep 10k | Upside | Risk |
|---:|---|---|---:|---:|---|---|
| 1 | shadow-policy evolution | `SHADOW_POLICY` | 33.26% | 42.42% | very high | very high |
| 2 | transport/representation | `LOW_RISK_ARCHITECTURAL` | 17.60% | 15.43% | medium | medium |
| 3 | remaining Rust SSA work | `NOT_CURRENT_BOTTLENECK` | 15.74% | 8.36% | bounded | medium |
| 4 | schema-v2 import | `SAFETY_BOUNDARY` | 14.83% | 12.11% | medium | high |
| 5 | Python builder verification | `SAFETY_BOUNDARY` | 8.20% | 11.02% | low without policy change | high |
| 6 | imported Rust SSA verification | `SAFETY_BOUNDARY` | 8.85% | 10.93% | low without weakening checks | high |
| 7 | Python renaming | `ALGORITHMIC_CORE` | 3.30% | 5.38% | medium | high |
| 8 | canonical comparison | `SAFETY_BOUNDARY` | 3.52% | 2.42% | low without semantic change | high |
| 9 | lifecycle rewrite | `LOW_RISK_IMPLEMENTATION` | 2.10% | 2.11% | medium | low |
| 10 | remaining-use accounting | `LOW_RISK_IMPLEMENTATION` | 0.99% | 1.06% | bounded | medium |
| 11 | lifecycle name census | `LOW_RISK_IMPLEMENTATION` | 0.51% | 0.55% | bounded | low |

## Strategic conclusion

Measured implementation candidates account for 24.60% of ordinary dual-lane wall time, enough for one architecture-level investigation but not a broad new series of micro-optimizations. The three lifecycle micro-candidates together are only 3.60%; the material implementation surface is transport/representation. Most remaining cost is inherent Rust SSA or deliberate shadow/safety/comparison policy.

Recommendation: **RUST-3.15_TRANSPORT_REPRESENTATION_REAUDIT_BEFORE_ANY_OPTIMIZATION**.

The cost of changing mandatory-shadow policy is reported only as a possible separate trust/promotion milestone; no such policy change is made or recommended as an optimization here.

## Method and session

The unchanged eight-workload corpus uses 15 measured rounds; deep CFG uses 7. Each follows warmups and rotating route order. All raw profiles are retained. One release companion served 345 requests in 1 process start. Startup was 0.024738s; first request 0.088785s; the steady small-request Rust-only median was 0.096623s.

Full Python suite: 4904 passed, 24 failed, 4 skipped. All failures are confined to `tests/aether/test_native_exceptions.py` and abort in LeakSanitizer before program assertions because the execution environment is under `ptrace`; this is recorded as `ENVIRONMENT_BLOCKED_LSAN_PTRACE`, not PASS.

Production behavior and ordinary response shape did not change.
