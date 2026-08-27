# RUST-4.5 — shadow-independent production promotion

Decision: `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_PENDING_CI`.

Baseline revision: `c524d9be54d2e23f865f45583b59ce88ba7233ef`. The old default was `RUST_SSA_AUTHORITY_PYTHON_SHADOW`; the new default is `RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED`.

## Production ordering

initial_ir_verification → lifecycle_normalization → rust_ssa_lowering_and_verification → schema_v2_import → imported_ssa_verification → same_input_integrity_before_refinement → independent_refinement_verification → same_input_integrity_after_refinement → final_generic_verification → accept

The returned object is the Rust-origin schema-v2 import that passed imported SSA verification, independent refinement verification, same-input integrity, and final generic verification. There is no automatic Python fallback.

## Structural execution proof

The production trace and direct monkeypatch hooks prove `GeneralSSABuilder` was not instantiated, Python dominance/phi placement/renaming did not run, no Python comparison DTO was constructed, and canonical Rust/Python comparison did not run. The same trace proves imported SSA verification, independent refinement, and final generic verification did run. This is direct instrumentation, not a timing inference.

The opposite differential proof is also executable: `RUST_SSA_AUTHORITY_PYTHON_SHADOW` invokes `GeneralSSABuilder`, constructs and compares complete canonical schema-v2 results, and rejects both Python shadow failure and genuine mismatch.

## Modes and rollback

The default omits Python SSA. `RUST_SSA_AUTHORITY_PYTHON_SHADOW` remains the fail-closed differential/diagnostic and emergency safety mode. `PYTHON_SSA_AUTHORITY_RUST_SHADOW` and `PYTHON_SSA_ONLY` remain configuration-only rollbacks.

Set `AETHER_SSA_AUTHORITY_MODE=rust_ssa_authority_python_shadow` to synchronously re-enable the differential Python shadow without a code patch. Invalid values are configuration errors.

## Qualification

Historical A/B: 116/116. Semantic mutations: 58/58 rejected by both; production-shadow dependencies: 0; invalid accepted by both: 0.

Adversarial: `PASS` (13 established and 32 generated cases). Deep CFG: [993, 1000, 5000, 10000]. Operational soak: `PASS` (64/64, the established RUST-4.4 soak equivalent). Concurrency: `PASS`.

Focused policy tests: `PASS`. Full suite: `PASS`. Cargo workspace: `PASS`. Clean install: `PASS`.

Full-suite environment: LSAN_OPTIONS=detect_leaks=0; established functional suite configuration, not leak-safety evidence.

A/B timing is observational with no threshold: ordinary old/new `0.024416s` / `0.019147s`, speedup `1.28x`; removed Python shadow `0.005407s`, removed canonical comparison `0.001286s`, refinement share `11.01%`. Deep timing rows for 100/1000/5000/10000 are in the JSON artifact.

Only actually supplied exact-revision platform artifacts are counted. Missing official platform evidence keeps the decision pending or blocked; it is never invented.

Platform status: linux-x86_64=PASS; Windows x86_64, macOS x86_64, and macOS arm64 remain pending the explicit CI matrix.

Compatibility remains protocol-v1 and schema-v2 with unchanged response shape. Clean native qualification: `PASS`. Optimizer/backend handoff retains the exact verified Rust-origin object and does not reconstruct it from canonical form.

Historical RUST-3.x evidence files are preserved. The active RUST-3.7 checker now narrowly recognizes that its differential default was superseded while still requiring the old mode to remain selectable. RUST-4.4 tooling and evidence are unchanged. Both RUST-4.4A properties remain fail-closed: refinement catches semantic corruption in every Rust-authority route, and canonical mismatch still rejects the explicit differential route.

Python SSA remains in the repository for differential CI, qualification, explicit safety mode, and rollback authority. This evidence is not a formal proof of Rust correctness. No commit was created.

## Historical closure attempt

The first formal closure attempt, using GitHub Actions run `33110365185`, remains historically blocked. Its differential job inherited the explicit authority override while probing the production default, so its internally blocked artifact cannot be used for promotion. RUST-4.5A isolates the qualification environments; a new run on one exact revision is required before any new closure.

## CI follow-up: run 33104958944

The four cross-platform clean-install jobs and the mandatory differential job passed. The production-default full-suite job's two failures were setup defects: it did not build the release `aether-ir-verifier`, and its no-build-isolation wheel test lacked `setuptools.build_meta` because the job did not explicitly provision current setuptools and wheel packages. The job now provisions `setuptools>=77` and `wheel>=0.45` and builds the locked release verifier before running the unfiltered suite.

The permanent promotion-fixture qualification now exercises all four authority modes. Every `RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED` row must return `rust_schema_v2_import`, complete every shadow-independent stage exactly once, execute Rust-side, independent-refinement, and final generic verification, and prove that the Python SSA builder, Python lowering, and canonical Rust/Python comparison did not execute. Local follow-up qualification passed all eight fixtures; the complete production-default repository suite passed with 5028 passed, 4 skipped, and no failures. The promotion decision remains pending until a clean exact-revision workflow rerun records these repaired gates.
