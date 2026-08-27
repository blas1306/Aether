# RUST-4.5 — shadow-independent production promotion closure

Decision: `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED`.

Exact revision: `b7362b06ead8da36d3ad3a97351fd5813c258590`. Official GitHub Actions run: [`33110365185`](https://github.com/blas1306/Aether/actions/runs/33110365185), completed with conclusion `success` on 2026-08-27. The preceding recorded decision remains `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_PENDING_CI`; it was not edited by hand.

This is an evidence closure, not a new implementation milestone. No RUST-4.6 was created and no production, verifier, lifecycle, schema, protocol, optimizer, backend, or rollback code was changed.

## Fail-closed closure result

The run-level and job-level conclusions are green, but the official RUST-4.5 differential artifact is not qualified. `rust-4.5-differential-shadow/differential.json` has SHA-256 `672312402262e282e51cbc2f89700468b2bb92d19be8b066e7387f007f86a220` and records:

- decision `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_BLOCKED`;
- `focused_policy_tests.status=FAIL`, return code 1, 36 passed and 6 failed;
- observed `new_default=RUST_SSA_AUTHORITY_PYTHON_SHADOW` because the differential job scoped `AETHER_SSA_AUTHORITY_MODE=rust_ssa_authority_python_shadow` over the whole qualification command;
- local qualification incomplete, with full-suite, cargo-workspace, and clean-install subgates not run inside that artifact.

The official job log confirms that the qualification command printed the blocked decision before the artifact was uploaded. The workflow step still succeeded because it did not require a promoted decision. A green artifact-upload job cannot replace the artifact's own fail-closed decision, and the evidence must not be edited or regenerated locally. Therefore condition 12 (no relevant failure) and the exact RUST-4.5 aggregate qualification condition are not satisfied.

The Node.js deprecation warning is recorded as non-blocking because it did not affect execution. The 12 repository-suite skips are test-level expected skips, not skipped RUST-4.5 jobs; every required job itself concluded `success`.

## Gates that did pass

- Production default: 42/42 focused policy tests and 5020 repository tests passed; 12 tests skipped and one warning. The default job did not define `AETHER_SSA_AUTHORITY_MODE`.
- Differential behavior: 2/2 focused differential tests passed. Python `GeneralSSABuilder`, canonical comparison, mismatch fail-closed behavior, and refinement fail-closed behavior were exercised under the explicit differential override.
- Clean installs: `linux-x86_64`, `windows-x86_64`, `macos-x86_64`, and `macos-arm64` all passed at the exact revision. Every platform recorded repository default `RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED`, zero Python shadow executions in default, and zero default canonical comparisons.
- Historical: 116/116 passed with no failures.
- Semantic mutations: 58/58 unique mutations were rejected by both paths; no production-shadow dependency and no invalid case accepted by both were recorded.
- Adversarial qualification passed. Deep CFG 993, 1000, 5000, and 10000 passed with equal authoritative SSA.
- Differential soak: 64/64 passed without restart; authority soak accepted 140 of 169 programs, rejected 29 before SSA, and recorded zero mismatches or infrastructure failures.
- Rollback: Rust authority plus Python differential shadow, Python authority plus Rust shadow, and Python-only all passed and remain available.
- Stabilization: operational, 155 regression tests, the 5020-test full suite, all four platforms, and all 17 aggregate stabilization gates passed at the qualification revision.
- Historical authority aggregate concluded `RUST_SSA_AUTHORITY_PROMOTED_V2`; stabilization aggregate concluded `RUST_SSA_PRODUCTION_STABILIZED`. Neither supersedes the contradictory RUST-4.5 differential artifact.

All 33 jobs and the official artifact ZIP digests are recorded in the [machine-readable closure record](rust_ssa_shadow_independent_production_promotion_closure.json). Its 24-artifact manifest also records the SHA-256 of every evidence file used by this closure, including the four RUST-4.5 clean-install artifacts, four platform-authority artifacts, differential, promotion fixtures, historical, adversarial, deep-CFG, soak/operational, full-suite, stabilization, and both aggregate artifacts.

## Production architecture retained

The production path remains:

```text
initial IR verification
    -> lifecycle normalization
    -> Rust SSA lowering and Rust-side verification
    -> schema-v2 import
    -> imported SSA verification
    -> same-input/integrity check
    -> independent refinement verification
    -> same-input/integrity check
    -> final generic SSA verification
    -> optimizer/backend
```

The returned SSA object is the exact verified Rust-origin schema-v2 import. Python SSA shadow does not run by default and there is no automatic Python fallback.

The permanent differential mode remains explicit:

```text
AETHER_SSA_AUTHORITY_MODE=rust_ssa_authority_python_shadow
```

It runs Rust SSA, independent refinement, Python `GeneralSSABuilder`, complete canonical comparison, and fail-closed mismatch handling. The CI job `rust-4.5-ci-differential-rust-refinement-python-shadow` remains present and explicitly forces this mode; the default job does not inherit it.

The rollback surface remains unchanged:

- Python authority with Rust shadow;
- Python-only;
- Rust authority with Python differential shadow.

## Trust boundary and history

RUST-4.5 does not formally prove that Rust SSA is universally correct. The official evidence shows that the shadow-independent default and four clean installs work on the qualified matrix, that independent refinement covers the known qualified semantic classes, and that the explicit differential lane still supplies a Python oracle. It does not permit ignoring an internally blocked official RUST-4.5 artifact.

The historical sequence remains explicit: Python shadow was mandatory during migration, followed by an independent verifier, refinement integration, redundancy qualification, shadow-independent qualification, and this production-promotion closure attempt. Historical RUST-3.x and RUST-4.0–4.4 evidence and decisions were not rewritten.

Python SSA remains in the repository for differential CI, qualification, explicit diagnostic/safety use, Python-authority rollback, and Python-only rollback. No commit was created.
