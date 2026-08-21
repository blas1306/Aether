# RUST-3.5b Rust SSA authority requalification

Decision: `RUST_SSA_AUTHORITY_REQUALIFICATION_BLOCKED`

The local semantic and operational requalification is complete and has no
semantic blocker. The final V2 authority-switch decision is blocked because
fresh exact-revision evidence has not been executed on Windows x86_64, macOS
arm64, or macOS x86_64. Workflow configuration is not counted as platform
evidence.

The repository default remains
`PYTHON_SSA_AUTHORITY_RUST_SHADOW`. Rust authority was selected explicitly only
inside qualification probes. This milestone does not switch the default.

## Expanded gate table

| Gate | Qualification | Result |
| --- | --- | --- |
| V2-G01 | All semantic contracts | PASS |
| V2-G02 | All lifecycle policies | PASS |
| V2-G03 | Schema-v2 | PASS |
| V2-G04 | Rust Owned SSA model | PASS |
| V2-G05 | Rust Owned SSA verifier | PASS |
| V2-G06 | Historical corpus 116/116 | PASS |
| V2-G07 | Adversarial 21/21 positive and 7/7 negative | PASS |
| V2-G08 | Python/Rust deep CFG 993, 1000, 5000 | PASS |
| V2-G09 | Expanded soak, zero mismatches | PASS |
| V2-G10 | Persistent transport, long session, concurrency | PASS |
| V2-G11 | Clean install in both dual-lane modes on all platforms | BLOCKED |
| V2-G12 | All four official platforms | BLOCKED |
| V2-G13 | Configuration-only rollback | PASS |
| V2-G14 | Independent Python authority | PASS |
| V2-G15 | Fail-closed comparison and infrastructure | PASS |
| V2-G16 | Rust origin and optimizer/backend handoff on all platforms | BLOCKED |
| V2-G17 | Packaged companion discovery on all platforms | BLOCKED |
| V2-G18 | Deterministic output | PASS |
| V2-G19 | No semantic blocker | PASS |
| V2-G20 | No operational blocker | BLOCKED |
| V2-L01 | Owning temporary: length, is_empty, interface receiver | PASS |
| V2-L02 | Nullable owning return/cast transfer | PASS |
| V2-L03 | Nullable constructor argument from storage | PASS |
| V2-L04 | Interface defaultability / move_init | PASS |
| V2-L05 | Direct struct-constructor receiver release | PASS |

The immutable RUST-3.5 baseline remains 20/20 PASS. The V2 aggregate currently
has 20/25 PASS; its five blocked rows are all consequences of the three missing
native platform reports.

## Permanent root-cause gates

| Previous cause | Mandatory fixtures | Promotion gate |
| --- | --- | --- |
| RC1 owning borrowed-consumer temporary | `aggregate_owned_projection.ae`, `owning_call_result.ae`, `owning_is_empty_result.ae`, `interface_call_temporary.ae` | V2-L01 |
| RC2 nullable owning return | `nullable_owned_return.ae` | V2-L02 |
| RC3 nullable constructor argument | `class_get_owned_result.ae` | V2-L03 |
| RC4 interface move/defaultability | `interface_lifecycle_default.ae` | V2-L04 |
| RC5 constructor receiver release | `boxed_constructor_receiver.ae` | V2-L05 |

All seven RUST-3.6a minimizers remain unchanged and mandatory. RUST-3.5b adds
one explicit `List.is_empty` owning-temporary fixture, so the mandatory
promotion inventory is eight fixtures. Every fixture passed lifecycle parity,
canonical SSA parity, Rust and Python verification, schema-v2 import, exact
reserialization, determinism, metadata preservation, optimizer verification,
and the three-mode returned-origin matrix.

## Results

- Historical corpus: 116/116 across all eight established checks.
- Expanded soak: 169 discovered, 140 accepted/compared, 29 rejected before
  SSA, zero semantic mismatches and zero infrastructure failures. The previous
  expected denominator was 139; it increased by one only because the explicit
  `List.is_empty` promotion fixture is now permanent.
- Persistent transport: 1000 requests / 1 process.
- Concurrency: 128 requests / 1 process.
- Adversarial: 21/21 positive and 7/7 negative.
- Deep CFG: 993, 1000, and 5000 PASS for Python and Rust, including Rust Owned
  SSA verification and exact schema-v2 reserialization.
- Cargo workspace: PASS.
- Full safe-default suite: 4828 passed, 4 skipped, 0 failed. The denominator is
  four higher than the prior 4824 because RUST-3.5b adds four qualification
  contract tests.
- Original real promotion subset: 18/18 under explicit
  `RUST_SSA_AUTHORITY_PYTHON_SHADOW`.
- Native exceptions: the uncontrolled run reproduced the exact 24
  LeakSanitizer/ptrace aborts; `LSAN_OPTIONS=detect_leaks=0` produced 54/54.
  These are environmental and not SSA/compiler failures.
- Linux x86_64 clean install: PASS. The packaged companion was discovered
  outside the checkout; all eight fixtures reached optimizer/backend with
  Rust-origin SSA only after a successful Python-shadow comparison; both
  rollback modes passed.
- Windows x86_64, macOS arm64, macOS x86_64: BLOCKED pending executed native
  evidence for the exact revision.
- Rollback: PASS by configuration only, to
  `PYTHON_SSA_AUTHORITY_RUST_SHADOW` or `PYTHON_SSA_ONLY`.

Performance was measured without a speed requirement. Across four
representative workloads, the observed Rust-authority/Python-shadow median was
10.996 times the Python-only median in this concurrent local run. This is an
observation, not an optimization target or gate.

## V1 blind spot and V2 prevention

V1 used the 116-program corpus and broad soak as aggregate coverage. Neither
inventory explicitly required every lifecycle root-cause shape, and there was
no machine-readable root-cause -> fixture -> promotion-gate mapping. A green
full suite or workflow definition could therefore coexist with missing
promotion-specific paths.

V2 makes the eight-source manifest an independent gate, executes every source
under all three modes, checks the returned SSA origin, and requires the same
revision in every evidence record. The evidence-only aggregator refuses to
infer native success from workflow existence and cannot return READY while any
official platform report is absent or stale.

## Files created

- `tests/fixtures/rust_ssa_promotion_failure/qualification_manifest.json` and
  `owning_is_empty_result.ae`;
- `scripts/qualify_rust_ssa_authority_promotion_fixtures.py`;
- `scripts/qualify_rust_ssa_authority_deep_cfg.py`;
- `scripts/qualify_rust_ssa_authority_full_suite.py`;
- `scripts/qualify_rust_ssa_authority_requalification_operational.py`;
- `scripts/check_rust_ssa_authority_requalification.py`;
- `tests/aether/test_rust_ssa_authority_requalification.py`;
- `docs/compiler/rust_ssa_authority_requalification_evidence/`;
- this report and `rust_ssa_authority_requalification.json`.

Machine-readable results are in
[`rust_ssa_authority_requalification.json`](rust_ssa_authority_requalification.json).
The historical READY, failed promotion, failure classification, and lifecycle
closure artifacts were not modified. No lowering, lifecycle policy, schema,
canonicalizer, optimizer, or backend semantics were changed. No commit was
created.
