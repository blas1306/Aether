# Refinement verifier production integration — RUST-4.2

Decision: `RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION_QUALIFIED`.

Baseline: `7a864686ec2698467f092a42efbe7982aede2018`.

## Production ordering

1. Initial IR integrity verification (IRBackend before SSA coordination)
2. single lifecycle normalization and normalized-input snapshot
3. Rust SSA lowering and companion-owned SSA verification (companion retains idempotent normalization defense)
4. schema-v2 import
5. existing imported SSA verification
6. same-input integrity checkpoint
7. independent refinement verification
8. same-input integrity checkpoint
9. mandatory synchronous Python shadow over the same normalized object
10. final same-input integrity checkpoint
11. canonical comparison
12. final generic SSAPipeline verification

The integration point is `aether.ssa.shadow._lower_dual_lane`: only the Rust-authoritative branch invokes refinement, after strict schema-v2 import and existing SSA verification, and before the Python shadow. Any exception becomes stable `refinement_verifier_failure` / `refinement_verification` and aborts immediately.

## Same input and failure injection

Lifecycle normalization is performed once by Python coordination. Its schema-v1 snapshot is serialized once for Rust, while refinement and Python shadow reuse the same normalized object. Source and normalized snapshots are checked before refinement, before Python, and after both lanes. The Rust companion retains its idempotent normalization as an internal defense.

| Mutation | First failure | Python would detect |
|---|---|---|
| missing_phi | refinement_verifier_failure | yes |
| extra_phi | refinement_verifier_failure | yes |
| wrong_phi_incoming_value | refinement_verifier_failure | yes |
| wrong_return | refinement_verifier_failure | yes |
| missing_preserved_instruction | refinement_verifier_failure | yes |
| duplicated_preserved_instruction | refinement_verifier_failure | yes |
| retained_unreachable_block | refinement_verifier_failure | yes |
| wrong_branch_target | refinement_verifier_failure | yes |
| wrong_call_target | refinement_verifier_failure | yes |
| wrong_call_argument | refinement_verifier_failure | yes |
| incorrect_promoted_value | refinement_verifier_failure | yes |

All injected corruptions failed before Python could authorize them. The eight RUST-4.0 shadow-only classes are covered. Python itself was not weakened and would also detect every injected semantic difference.

## Positive and operational qualification

Historical: 116/116. Ordinary/adversarial/randomized cases: 39; false positives: 0. Deep CFG 993/1000/5000/10000: PASS. Operational soak, persistent session, concurrency, repetition, A→B/B→A/A→A and valid→invalid→valid: PASS. State leakage: 0.

## Performance

No threshold is imposed. Times are seconds on the local Linux x86_64 qualification host; each row alternates the pre-integration diagnostic dual lane and integrated dual lane in the same persistent characterized companion.

| Workload | Before median (min–max) | After median (min–max) | Refinement median | Share |
|---|---:|---:|---:|---:|
| ordinary | 0.002488 (0.001773–0.003899) | 0.002456 (0.001902–0.002894) | 0.000254 | 10.34% |
| deep_100 | 0.011194 (0.010422–0.011892) | 0.012329 (0.011351–0.012985) | 0.000833 | 6.76% |
| deep_1000 | 0.125196 (0.102961–0.130773) | 0.110615 (0.109989–0.111378) | 0.008460 | 7.65% |
| deep_5000 | 0.591720 (0.557355–0.604038) | 0.639697 (0.631624–0.645146) | 0.045668 | 7.14% |
| deep_10000 | 1.265457 (1.248895–1.285013) | 1.381359 (1.380931–1.386779) | 0.093267 | 6.75% |

Memory was not measured because it was optional when practical. No optimization was attempted.

## Compatibility, rollback, platforms, and evidence

The ordinary SSA response, schema-v2 serialization, companion protocol v1, and `SSAShadowReport` fields are unchanged. Rust remains authority in `RUST_SSA_AUTHORITY_PYTHON_SHADOW`; Python shadow remains mandatory, synchronous, independent, comparison-based, and fail-closed. Python-authority/Rust-shadow and Python-only rollback paths do not invoke refinement and remain unchanged.

Local qualification is Linux x86_64 only. CI runs the RUST-4.2 gate in the existing Linux x86_64, Windows x86_64, macOS x86_64, and macOS arm64 matrix; no non-local result is claimed here. Historical RUST-3.x/RUST-4.0/RUST-4.1 artifacts were not rewritten.

## Gates

- RUST-4.2 checker: PASS.
- RUST-4.0 mutation and RUST-4.1 verifier contracts: PASS.
- Production failure injection, historical 116/116, adversarial, randomized, deep, soak, persistent session, concurrency, rollback, authority/shadow and fail-closed contracts: PASS.
- Full Python suite: 4,976 passed, 4 skipped, 6 plotting warnings.
- `cargo test --workspace --locked`: PASS.
- `cargo fmt --all --check`: PASS.
- `git diff --check`: PASS.

No commit was created.

Final decision: `RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION_QUALIFIED`.
