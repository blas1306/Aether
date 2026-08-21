# RUST-3.6b Rust lifecycle promotion defect closure

Decision: `RUST_SSA_PROMOTION_LIFECYCLE_DEFECTS_CLOSED`

RUST-3.6b corrects the five classified lifecycle-normalization primitives in
Rust. All 18 semantic promotion failures now pass with explicit Rust SSA
authority, and every minimized reproducer is exactly equivalent at Boundary B
before SSA construction. No policy gap was found.

The repository default remains `PYTHON_SSA_AUTHORITY_RUST_SHADOW`. The
`RUST_SSA_AUTHORITY_PYTHON_SHADOW` mode remains explicit and fail-closed; this
milestone does not perform another authority promotion.

## Root-cause closure

| Cause | Before | After | Rust semantic correction |
| --- | ---: | ---: | --- |
| Owning expression temporary | 10 | 0 | Collection `length`/`is_empty` consumers and borrowed interface receivers now discharge an owning temporary through the common consumed-owner primitive. |
| Nullable owning return | 1 | 0 | A cast to nullable owning type transfers a fresh owner; a borrowed source is retained, and an interface-containing source uses the qualified carrier copy. Return then transfers the existing owner without another retain. |
| Nullable constructor argument | 1 | 0 | The nullable cast now creates the required temporary copy lifetime, allowing generic call-argument disposition to release it after the constructor call. |
| Interface lifecycle default | 2 | 0 | `move_init` resets a moved source only when the type both needs destruction and supports a default. Interfaces remain carrier-owning and deliberately non-defaultable. |
| Struct constructor receiver | 4 | 0 | A direct owning struct constructor call now releases its borrowed pre-construction receiver on normal completion. Existing invoke cleanup topology is unchanged. |

The implementation is confined to Rust lifecycle normalization. CFG,
dominance, liveness, definite initialization, phi placement, renaming,
canonicalization, optimizer, backend, Python lowering, policies, and schemas
were not changed.

## Boundary and mode results

All seven RUST-3.6a source minimizers pass:

- verified Initial IR: 7/7;
- lifecycle-normalized Initial IR, exact Boundary B equality: 7/7;
- Rust Owned SSA and verifier: 7/7;
- schema-v2 import and Python verification: 7/7;
- canonical SSA equality: 7/7;
- optimizer verification: 7/7 in all three modes.

`PYTHON_SSA_ONLY` and `PYTHON_SSA_AUTHORITY_RUST_SHADOW` return
`python_general_ssa_builder`; `RUST_SSA_AUTHORITY_PYTHON_SHADOW` returns
`rust_schema_v2_import`. Both dual-lane modes report `match` for every
reproducer.

A permanent parameterized regression now checks exact Boundary B output and
the three-mode matrix for these fixtures. The fixture directory is also under
the expanded shadow/authority soak inventory, closing the six early-failure
coverage gaps.

## Qualification

- Previously failing semantic tests under explicit Rust authority: 18/18.
- Historical lifecycle and canonical SSA parity: 116/116.
- Rust Owned SSA verification, schema-v2 import, exact reserialization, and
  determinism: 116/116.
- Expanded soak: 168 discovered, 139 accepted/compared, 29 rejected before
  SSA, zero semantic mismatches, zero infrastructure failures; 1000-request
  persistent session and 128 concurrent serialized requests pass.
- Adversarial qualification: 21 positive and 7 negative cases, PASS.
- Deep CFG: 5000-block Rust lowering and Owned SSA verification, PASS.
- Cargo workspace: PASS.
- Lifecycle policy v1 and source-location lowering policy v1 checks: PASS.

The full pytest suite under the explicit Rust-authority qualification override
first produced 4799 passes, 4 skips, the exact 24 known LeakSanitizer/ptrace
aborts, and one harness-only test whose purpose is to assert the repository's
Python-authority default. That contract test passes in its required default
mode. With the qualified ptrace-compatible procedure
`LSAN_OPTIONS=detect_leaks=0` and that contract test kept in its normative
default mode, the complete result is **4824 passed, 4 skipped, 0 failed**. The
entire native exception module is 54/54 passing under the same procedure.
There are zero non-environmental promotion failures.

Machine-readable evidence is in
[`rust_ssa_promotion_lifecycle_defect_closure.json`](rust_ssa_promotion_lifecycle_defect_closure.json).

No sanitizer behavior was changed globally, no historical RUST evidence was
rewritten, no cross-platform promotion was attempted, and no commit was
created.
