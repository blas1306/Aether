# RUST-2.P1 — Post-RP3 performance audit

## Decision

The remaining full-suite wall time is not shown to be an RP3 verifier
regression. On this checkout, the ordinary pytest suite does not construct a
dual-verifier pipeline: `IRBackend` receives `shadow_verifier=None` and calls
the Python `IRVerifier` directly. Rust authority plus mandatory Python shadow
is injected only by the explicit canary harness.

The dominant measured cost is the pre-existing O2 audit/regeneration group:
69 tests took 770.57 s, or 67.75% of the 1,137.36 s full-suite wall time. Twelve
individual O2 audit phases exceeded 10 s; the two slowest took 130.93 s and
127.23 s. No optimization is made in this milestone.

## Method and environment

Measurements were taken on 2026-08-20 with CPython 3.14.7, Linux
7.1.8-1-cachyos x86_64, an AMD Ryzen 5 7535HS, and 12 logical CPUs. Commands
used `PYTHONPATH=.:src PYTHONDONTWRITEBYTECODE=1`; without that environment,
collection was contaminated by missing checkout-root imports and a stale
external-path bytecode cache. Timings are observations for this machine, not
CI thresholds.

Pytest configuration contains only `testpaths = tests`; there are no timing,
parallelism, or session-fixture policies in `pytest.ini`.

## Suite result and decomposition

Collection found 4,699 tests in 208 `test_*.py` files. The complete ordinary
suite finished in 1,137.36 s (18:57): 4,671 passed, 24 failed, and 4 skipped.
All 24 failures are in sanitizer-backed native exception tests and emit
`LeakSanitizer does not work under ptrace`. The exact last-failed set reran in
4.01 s (24 failed, 1,431 deselected) and reproduced the same managed-host
incompatibility. They are environment-specific failures here; they are not
verifier mismatches and do not explain the long wall time.

Measured profile:

| Component | Wall time | Share / classification |
| --- | ---: | --- |
| O2 audit/regeneration modules | 770.57 s | 67.75%; pre-existing test-harness work |
| All other ordinary-suite work | 366.79 s | 32.25%; frontend, IR/SSA, native, numerical, packaging and harness remainder |
| RP3 canary, four pytest suites | 7.25 s | separate controlled run; 404 comparisons |
| Estimated verifier work within 404 requests | 0.247 s | Python + serialization + persistent Rust transport/verification |

The O2 group alone proves that the suite is dominated by a small integration
cluster rather than a broad verifier constant factor. Setup phases are also
material: two generated baselines consumed 96.72 s and 64.81 s in setup.
Native execution is visible (for example one numerical native dogfood case
took 2.23 s), while sanitizer tests fail quickly on this host rather than
dominating the measured runtime. Packaging, frontend, Initial IR, SSA and LLVM
costs remain in the 366.79 s remainder; this audit does not invent a more
precise split where the full terminal duration report was obscured by the 24
verbose sanitizer failures.

## Slowest observed tests

The following is the measured top 20 across the fully measured O2 group and
the targeted numerical/native group. The first 13 exceed 1 s, the first 12
exceed 5 s and 10 s.

| # | Seconds | Phase | Test |
| ---: | ---: | --- | --- |
| 1 | 130.93 | call | `test_o2_measurement.py::test_checked_in_static_baseline_is_exactly_regenerated` |
| 2 | 127.23 | call | `test_o2_aggregate_copy_elision_readiness.py::test_report_regeneration_is_byte_deterministic` |
| 3 | 96.72 | setup | `test_o2_post_immediate_borrow_optimization_audit.py::test_current_post_o297_baseline` |
| 4 | 64.81 | setup | `test_o2_post_arrayget_hot_ownership_audit.py::test_current_post_o297_production_census` |
| 5 | 63.87 | call | `test_o2_aggregate_lifetime_analysis.py::test_real_hot_workload_reconciles_every_site_deterministically` |
| 6 | 63.49 | call | `test_o2_arc_structural_eligibility_audit.py::test_json_is_stable_and_audit_is_read_only` |
| 7 | 62.78 | call | `test_o2_aggregate_copy_elision_readiness.py::test_o211_reconciles_exact_four_real_sites_as_no_explicit_copy_edges` |
| 8 | 32.87 | call | `test_o2_scalar_replacement_readiness.py::test_o210_freezes_and_classifies_the_exact_o298_candidates` |
| 9 | 32.23 | setup | `test_o2_hot_arc_opportunity_audit.py::test_hot_arc_census_loop_depth_balance_and_closed_taxonomies` |
| 10 | 31.91 | call | `test_o2_arc_structural_eligibility_audit.py::test_cfg_dominance_paths_joins_and_phis_are_reported` |
| 11 | 31.87 | call | `test_o2_arc_structural_eligibility_audit.py::test_exact_pairs_and_structural_blockers` |
| 12 | 30.89 | call | `test_o2_immediate_array_string_borrow_audit.py::test_exact_three_sites_are_borrowed_and_stable_region_remains_owned` |
| 13 | 2.23 | call | `test_numeric_backend_parity.py::test_numeric_dogfood_examples_execute_natively[probandoNR3.ae]` |
| 14 | 0.21 | call | `test_numerical_methods_example.py::test_numerical_methods_dogfood_program_matches_native_backend` |
| 15 | 0.19 | call | `test_o2_measurement.py::test_candidate_fingerprints_and_overlap_are_stable` |
| 16 | 0.11 | call | `test_numerical_methods_example.py::test_numerical_methods_dogfood_program_validates_all_cases` |
| 17 | 0.09 | call | `test_o2_measurement.py::test_static_measurement_required_censuses_and_unsupported_reporting` |
| 18 | 0.08 | call | `test_numeric_backend_parity.py::test_mixed_numeric_operations_match_all_backends_in_both_orders` |
| 19 | 0.08 | call | `test_numeric_backend_parity.py::test_contextual_int_to_double_promotion_matches_all_backends` |
| 20 | 0.07 | call | `test_numeric_backend_parity.py::test_numeric_dogfood_examples_execute_natively[FormulaNumerosPrimos.ae]` |

The slowest modules by observed cumulative duration are
`test_o2_aggregate_copy_elision_readiness.py` (at least 190.01 s),
`test_o2_measurement.py` (at least 131.19 s),
`test_o2_arc_structural_eligibility_audit.py` (at least 127.27 s),
`test_o2_post_immediate_borrow_optimization_audit.py` (at least 96.72 s),
and `test_o2_post_arrayget_hot_ownership_audit.py` (at least 64.81 s).

## Verifier audit

The qualified current debug companion completed the four canary populations:
50/50, 6 passed with one expected skip, 10/10, and 5/5. It produced 404
comparisons: 316 accepted matches, 85 semantic rejection matches and three
documented diagnostic divergences. Semantic mismatches and infrastructure
failures were zero.

Each canary population is intentionally a separate pytest process. The harness
constructs one `PersistentSubprocessRustVerifierClient` at session setup and
closes it at session finish. Therefore the run used four worker startups, 404
Rust requests, 404 Python-shadow invocations, and 101 requests per worker on
average. Within a population the worker is not scoped per backend or per test;
there is no evidence of accidental one-request client lifetime. Running the
four populations in one process might save three startups, but the RUST-2.P
50-request benchmark and this lifecycle inspection show that it cannot explain
minutes of suite time.

A controlled migration-corpus benchmark measured:

| Operation | Requests | Total | Mean/request |
| --- | ---: | ---: | ---: |
| Python verifier only | 1,420 | 0.139375 s | 98.151 us |
| Canonical serialization | 1,400 | 0.085564 s | 61.117 us |
| Persistent Rust transport + verification | 1,400 | 0.634310 s | 453.078 us |

The Rust row used one worker startup. Adding the three per-request means gives
an intentionally conservative dual-verification estimate of 612.346 us, or
0.247 s for 404 requests. Authority ordering A (Rust authority/Python shadow)
and rollback ordering B (Python authority/Rust shadow) execute the same two
engines in `VerifierAuthorityPipeline.verify`; authority selection occurs only
after both outcomes are compared. Thus accepted-path compute cost is invariant
to A/B ordering. Isolated Python and Rust measurements above estimate each
side without exposing a production configuration selector.

A stale release binary present in the checkout supported `--identity` but not
the new persistent framing and correctly failed closed. Repeating with the
current debug binary passed. This is an environment/artifact freshness issue,
not a semantic disagreement; it also demonstrates that fail-closed behavior
was not weakened.

## Attribution and opportunities

Ranked findings:

1. **Pre-existing test cost:** O2 audit regeneration is dominant (770.57 s).
   Several tests appear to rematerialize overlapping repository-wide evidence.
2. **Test-harness setup cost:** two O2 module fixtures account for at least
   161.53 s in setup alone.
3. **Native compilation/execution:** present and measurable, but not dominant
   in the targeted numerical group (largest observed case 2.23 s).
4. **Sanitizers/environment:** 24 deterministic host incompatibilities, quick
   on rerun; important for reliability, not the wall-time cause here.
5. **RP3 verifier + mandatory shadow:** about 0.247 s per 404 representative
   requests in isolation; negligible beside the measured O2 group.
6. **Persistent lifecycle:** correct at pytest-session scope. Four starts are
   intentional because the canary driver isolates four populations.

The historical pre-RP3 runtime below eight minutes remains a useful signal but
is not causal evidence. No reproducible pre-RP3 checkout measurement is
available here, and current O2 audit tests alone exceed that historical number.
Consequently the remaining difference cannot be attributed to RP3.

Recommended next milestone: profile and consolidate O2 audit materialization.
First map which generators share identical immutable inputs, then consider
session-scoped fixtures or a single generated evidence bundle with explicit
input hashes and mutation isolation. Do not add an IR-verification cache or
change verifier lifetime/authority based on this audit: the measured verifier
cost is not dominant. Separately, ensure release-companion builds are refreshed
before canary execution and run sanitizer qualification on a host where LSan
is not under ptrace.

Machine-readable evidence is in
`docs/compiler/rust_initial_ir_rp3_performance_audit.json`.
