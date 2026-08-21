# Rust SSA lowering adversarial qualification — RUST-3.2

Decision: `RUST_SSA_LOWERING_ADVERSARIAL_BLOCKED`

Qualification stopped at the first demonstrated correctness difference, as the
milestone requires. A verified, generated linear Initial IR function with 1000
blocks lowers and verifies successfully in Rust, but Python's production
`GeneralSSABuilder` raises `RecursionError: maximum recursion depth exceeded`
during SSA renaming. The same family succeeds at 100 blocks. Manual bisection
under the normal interpreter recursion limit reduced the reproducer to 993
blocks; its complete Initial IR and Rust schema-v2 result are retained in the
machine-readable report. No lowering implementation was changed.

## Results before fail-fast

- Positive cases attempted: **19**; complete parity cases: **18**.
- Negative cases recorded separately: **7**, deterministically rejected.
- Maximum CFG exercised: **1000 blocks** (smallest observed reproducer: 993).
- Lifecycle differential: **19/19 equivalent**.
- Canonical SSA differential: **18/19 equivalent**; Python produced no SSA for
  the failing case.
- Python SSA verifier: **18/19** (construction failed before verification once).
- Rust Owned SSA verifier: **19/19**.
- Schema-v2 Python import and exact reserialization: **19/19**.
- Repeated concrete Rust determinism and input immutability: **19/19**.
- Existing real-program differential: not rerun after the divergence because
  RUST-3.2 explicitly requires qualification to stop. The previously qualified
  116/116 evidence remains the applicable result and was not weakened.

The completed generated inventory covers straight-line SSA, required and
pruned diamond phis, simultaneous phis, nested diamonds, loop-carried phis,
deep loop paths, unreachable isolated/chain/cycle CFG, naming pressure,
definite initialization/liveness, and 10/100/1000-block linear scale families.
Later exceptional, constructor, ownership, call, collection, and metadata
families were intentionally not executed after fail-fast; this blocked report
does not claim their adversarial qualification.

Policy/schema checkers executed successfully:
`SSA_LOWERING_POLICY_V1_QUALIFIED`,
`LIFECYCLE_NORMALIZATION_POLICY_V1_QUALIFIED`, SSA wire-boundary audit,
`SSA_SOURCE_LOCATION_CODEC_QUALIFIED`, and
`SSA_SOURCE_LOCATION_LOWERING_POLICY_V1_QUALIFIED`.

Observable totals for the attempted cases were approximately 218 ms in Python
SSA construction (including the failure) and 1.57 s in the first Rust
lower-and-verify executions. These are diagnostics only, not performance gates.

Artifacts are this report,
`rust_ssa_lowering_adversarial_qualification.json`, and the reproducible harness
`scripts/qualify_rust_ssa_lowering_adversarial.py`. Python remains production
SSA-lowering authority. RP3 is unchanged. No authority promotion, fallback,
schema/policy change, optimizer/backend change, or commit was made.
