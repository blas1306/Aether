# RUST-4.5 — shadow-independent production promotion closure (second attempt)

Decision: `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED`.

Exact revision: `6274cd2024fd012d297533d7783f7c4547feb26f`. Official GitHub Actions run: [`33121500789`](https://github.com/blas1306/Aether/actions/runs/33121500789), completed with conclusion `success` on 2026-08-27.

This is a second, separate closure record. The first closure at revision `b7362b06ead8da36d3ad3a97351fd5813c258590`, run `33110365185`, remains immutable with decision `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED`. Its block reason remains differential qualification environment contamination / false-green qualification gate. None of its artifacts or hashes are reused here.

## Basis for promotion

All required jobs in run `33121500789` concluded `success`, all evidence selected for this closure identifies the exact revision, and all 24 relevant GitHub artifacts expose a `sha256` digest. The downloaded official artifact files were hashed independently; the GitHub artifact digests and 28 evidence-file SHA-256 values are recorded in the [machine-readable second closure](rust_ssa_shadow_independent_production_promotion_closure_6274cd20.json).

The historical closure JSON, report, checker, and tests remain byte-preserved. Their hashes are recorded separately under `historical_closure_preservation`; they are not promotion evidence for this attempt.

The preserved decision history is: RUST-3.x → mandatory Python shadow → RUST-4.1 independent refinement → RUST-4.2 production refinement → RUST-4.3 redundancy qualification → RUST-4.4 shadow-independent qualification → RUST-4.5 production promotion → first closure BLOCKED → RUST-4.5A environment isolation → second official qualification → final closure. No earlier decision is reinterpreted or rewritten by this record.

## RUST-4.5A and differential qualification

The official `rust-4.5-differential-shadow/differential.json` has SHA-256 `703e94b71075d7d82344495014508b696510f5b4f0c855ec7f3496da59190eca` and decision `RUST_SSA_DIFFERENTIAL_SHADOW_QUALIFIED`.

Its production-default observation explicitly removes `AETHER_SSA_AUTHORITY_MODE`, observes Rust authority in `RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED`, requires refinement, and records no Python `GeneralSSABuilder` execution and no canonical Rust/Python comparison. The focused default probe passed 43 tests.

Its differential observation explicitly sets `AETHER_SSA_AUTHORITY_MODE=rust_ssa_authority_python_shadow`, observes Rust authority in `RUST_SSA_AUTHORITY_PYTHON_SHADOW`, and records all of the following:

- Python `GeneralSSABuilder` executed;
- complete canonical comparison executed;
- semantic mismatch rejected fail-closed;
- refinement failure rejected fail-closed;
- focused differential probe passed;
- rollback modes remained available.

The artifact checker recomputed PASS for identity, semantic campaign, production-default observation, differential observation, rollback, completion, and decision. The official CI step `Differential qualification decision gate` then concluded `success` before artifact upload. Promotion therefore relies on the artifact and its fail-closed checker, not merely the green job conclusion.

## Shadow-independent production default

The job `rust-4.5-production-default-no-python-shadow` did not define `AETHER_SSA_AUTHORITY_MODE`. Its focused policy suite passed 43/43, and its full repository run reported `5031 passed, 12 skipped, 1 warning`. The closure records the production architecture as:

1. initial IR verification;
2. lifecycle normalization;
3. Rust SSA lowering;
4. Rust-side verification;
5. schema-v2 import;
6. imported SSA verification;
7. same-input and integrity controls;
8. independent refinement verification;
9. final generic verification;
10. optimizer/backend.

Python SSA shadow execution and canonical Rust/Python comparison are absent from this default. Independent refinement is mandatory and failures remain closed.

## Exact-revision matrix and campaigns

The four clean-install artifacts explicitly report PASS on `linux-x86_64`, `windows-x86_64`, `macos-x86_64`, and `macos-arm64`. Each reports `RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED`, Rust-origin schema-v2 output, zero Python shadow executions in the default, and zero canonical comparisons in the default. Separate authority and production-stabilization artifacts exist and pass for the same four named platforms; no platform result is inferred.

The official campaign evidence records:

- historical corpus: 116/116;
- semantic mutations: 58/58 rejected by both implementations, with zero production-shadow dependencies and zero invalid programs accepted by both;
- deep CFG: 993, 1000, 5000, and 10000 blocks accepted by production and qualification with equal authoritative SSA;
- differential soak: 64/64, authority soak decision `RUST_SSA_AUTHORITY_SOAK_PASS`, zero semantic mismatches, and 128 serialized concurrent requests;
- `production-stabilization-operational`, `production-stabilization-regressions`, `production-stabilization-full-suite`, and `full-suite-rust-default`: PASS;
- rollback jobs `python-authority-rust-shadow` and `python-only`: PASS;
- explicit Rust authority plus Python differential shadow: PASS.

The aggregate artifacts decide `RUST_SSA_PRODUCTION_STABILIZED` and `RUST_SSA_AUTHORITY_PROMOTED_V2` on the exact revision. Their embedded four-platform results are all PASS.

## Decision boundary

Every fail-closed eligibility gate recomputes true, so this second record declares `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED` for revision `6274cd2024fd012d297533d7783f7c4547feb26f` and the qualified matrix.

This closure does not formally prove that Rust SSA is universally correct. Python SSA remains in the repository for explicit differential CI, diagnosis, and rollback authority; the promoted default remains independently refinement-verified and fail-closed.
