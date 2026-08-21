# Rust SSA lowering adversarial qualification rerun — RUST-3.2

Decision: `RUST_SSA_LOWERING_ADVERSARIAL_BLOCKED`

The fresh qualification stopped at the permanent 5000-block deep-CFG gate.
The generated Initial IR was verified before lowering. Python lifecycle
normalization, Python SSA lowering, and Python SSA verification succeeded, but
the Rust lower-and-verify executable aborted with exit status `-6`, emitted no
schema-v2 JSON, and reported:

```text
thread 'main' has overflowed its stack
fatal runtime error: stack overflow
```

This is a real cross-lane robustness difference. No lowering implementation was
changed and no remaining gates were run after confirmation of the failure.

## Results before fail-fast

- Fully completed positive adversarial cases: **22/22**.
- Failing positive case: **1** (`scale_linear_5000`).
- Negative adversarial cases: **not run after divergence**.
- Largest CFG exercised: **5000 blocks**.
- Permanent 993- and 1000-block cases: **pass**.
- Lifecycle canonical parity: **23/23**.
- Canonical SSA parity: **22/22 completed comparisons**; unavailable for the
  5000-block case because Rust emitted no SSA.
- Python SSA lowering and verification: **23/23**.
- Rust Owned SSA verification: **22/23**; process aborted before verification
  completed for the 5000-block case.
- Schema-v2 import and exact Python reserialization: **22/22 emitted Rust
  results**; unavailable for the failing case.
- Deterministic repeated Rust lowering: **22/22 completed cases**. The isolated
  5000-block reproduction deterministically aborts in the Rust lane; it is not
  counted as successful lowering determinism.
- Input immutability: **23/23**.
- Historical 116-program corpus: **not run after divergence**.

## Preserved evidence

The exact failing input is generated deterministically by
`linear("linear5000_rerun", 5000)` in the existing RUST-3.2 harness. Its
canonical pretty-printed schema-v1 JSON SHA-256 is
`a7cf52f66c7eddc145643d0dc49ca8c5b3f16762cafd38d183581dbb7316dd53`.
The machine-readable rerun record contains the command, exit status, output
sizes, stderr, completed-gate counts, and hashes proving the historical blocked
artifacts were not changed.

Python remains the production lowering authority. RP3 is unchanged. No
lowering algorithm, policy, schema, canonical comparison, or production
authority was modified. No commit was created.
