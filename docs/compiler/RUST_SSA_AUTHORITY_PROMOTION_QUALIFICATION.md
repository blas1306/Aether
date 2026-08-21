# RUST-3.5 final Rust SSA authority-promotion qualification

Decision: `READY_FOR_RUST_SSA_AUTHORITY_SWITCH`

This decision qualifies a later authority-switch milestone. It does not perform
that switch. Python remains the production SSA authority, the production
default remains `PYTHON_SSA_ONLY`, and Rust SSA cannot reach the optimizer or
backend. The reserved Rust-authority selection rejects deterministically until
the later milestone explicitly activates its coordinator.

## Final gate table

| Gate | Requirement | Result | Evidence |
|---|---|---|---|
| G01 | All semantic contracts qualified | PASS | lowering policy v1, source-location policy v1, aggregate closure |
| G02 | All lifecycle policies qualified | PASS | policy v1 and Rust differential 116/116 |
| G03 | Schema-v2 qualified | PASS | lossless strict SSA wire qualification |
| G04 | Rust Owned SSA model qualified | PASS | 116/116 |
| G05 | Rust Owned SSA verifier qualified | PASS | 116/116 |
| G06 | Historical corpus | PASS | lifecycle, canonical SSA, verification/import, exact reserialization, and determinism 116/116 |
| G07 | Adversarial corpus | PASS | positive and deterministic-negative inventory |
| G08 | Deep CFG regressions | PASS | Python and Rust; Rust 5,000-block `PASS_AND_VERIFY` |
| G09 | Expanded soak | PASS | 132/132 compared, zero semantic mismatches, zero infrastructure failures |
| G10 | Persistent transport | PASS | 1,000 sequential requests/one process; 128 concurrent requests/one process |
| G11 | Clean install | PASS | native clean release artifact on all official runners |
| G12 | Four official platforms | PASS | Linux x86_64, Windows x86_64, macOS arm64, macOS x86_64 |
| G13 | Rollback configuration | PASS | both Python authority selections are available without schema, policy, or lowering edits |
| G14 | Independent Python authority | PASS | `PYTHON_SSA_ONLY` lowers and verifies without a companion |
| G15 | Fail-closed Rust shadow | PASS | malformed/infrastructure/mismatch results return no SSA |
| G16 | Rust SSA excluded from consumers | PASS | reserved Rust-authority mode is disabled; both live modes return Python SSA |
| G17 | Companion compatibility | PASS | product 0.1.0, protocol 1, Initial IR schema 1, SSA schema 2 |
| G18 | Determinism | PASS | 116/116 repeated results and persistent representative observations |
| G19 | No semantic blocker | PASS | all semantic gates pass; aggregate divergence is closed |
| G20 | No operational blocker | PASS | qualified native aggregate contains no blockers |

## Semantic qualification

The frozen lowering and lifecycle policies remain unchanged. Historical
lifecycle parity, canonical SSA parity, Rust Owned SSA verification/schema-v2
import, exact Python schema-v2 reserialization, and deterministic Rust output
are each 116/116. Schema-v2 losslessness, source-location lowering,
adversarial coverage, Python/Rust deep-CFG regressions, and aggregate ownership
shadow closure all pass. There is no unresolved semantic blocker.

## Operational qualification

The expanded soak discovered 161 programs; 132 reached SSA and all 132 were
compared. It recorded zero semantic mismatches and zero infrastructure
failures. One persistent process served 1,000 sequential requests. One
synchronized process served 128 concurrent client requests. Packaged companion
discovery, identity, checksum, clean installation, representative comparisons,
and clean shutdown passed on every official native runner.

The older checkout-local `RUST_SSA_SHADOW_OPERATIONALLY_BLOCKED` artifact is
preserved unchanged. The separately imported native-runner aggregate is stored
as `rust_ssa_shadow_operational_qualified.json`, including the aggregate hash,
the four report hashes, and the four companion hashes.

| Platform | Rust target | Result |
|---|---|---|
| Linux x86_64 | `x86_64-unknown-linux-gnu` | PASS |
| Windows x86_64 | `x86_64-pc-windows-msvc` | PASS |
| macOS arm64 | `aarch64-apple-darwin` | PASS |
| macOS x86_64 | `x86_64-apple-darwin` | PASS |

## Future authority configuration

The configuration type is
`src/aether/ssa/shadow.py:SSALoweringAuthorityConfiguration`; pipeline
selection occurs in `src/aether/pipeline.py:SSAPipeline.build`.

| Mode | Authoritative result returned | Shadow behavior | Current state |
|---|---|---|---|
| `PYTHON_SSA_ONLY` | verified Python SSA | none | available; production default |
| `PYTHON_SSA_AUTHORITY_RUST_SHADOW` | verified Python SSA after comparison | synchronous verified Rust comparison | available |
| `RUST_SSA_AUTHORITY_PYTHON_SHADOW` | schema-v2 Rust result imported into Python's `SSAModule`, after Rust Owned SSA verification, Python boundary verification, and successful canonical comparison | synchronous verified Python lowering; discarded only after a match | reserved and disabled |

The future Rust-authority coordinator must snapshot the verified Initial IR
once, run both lanes from that exact snapshot, verify both results, canonicalize
the complete schema-v2 semantics, and compare them. Only after a match may it
return the imported Rust result. Python shadow output is never substituted for
the Rust result in that mode.

## Fail-closed behavior

Rust startup failure, timeout, malformed response, Rust or boundary
verification failure, canonicalization failure, Python-shadow failure, and
semantic mismatch each abort compilation and return no SSA. A timeout also
terminates the companion. A semantic mismatch emits the existing bounded,
deterministic diagnostic evidence. There is no silent fallback to Python.

This matches the verifier-promotion philosophy: an authority lane that cannot
prove its result does not produce a consumable result.

## Rollback

After the later promotion, ordinary rollback selects
`PYTHON_SSA_AUTHORITY_RUST_SHADOW`, retaining Rust observation while returning
Python SSA. Independent rollback selects `PYTHON_SSA_ONLY`, requiring no
companion. Both are configuration selections in the final architecture; no
code, policy, schema, lowering, optimizer, or backend edit is required.

## CI gates before and after promotion

Before promotion, all 20 RUST-3.5 gates must pass again on the exact promotion
revision. The four native clean-install reports, 132-program zero-mismatch
soak, fail-closed regressions, rollback regressions, packaging identity, and
compatibility checks are mandatory.

The promotion change may activate only
`RUST_SSA_AUTHORITY_PYTHON_SHADOW`. CI must prove the returned object originated
from verified Rust schema-v2 output and that every mismatch/failure path
returns no SSA. It must not remove either Python rollback lane.

After promotion, Rust-authority/Python-shadow is mandatory on all four
platforms. Python-only and Python-authority/Rust-shadow remain required rollback
lanes. Scheduled soak, long-session, concurrency, clean-install, packaged
discovery, protocol/schema/product compatibility, determinism, and fail-closed
tests remain release gates; any mismatch or infrastructure failure blocks the
release.

## Performance observation

Seven rounds each of scalar arithmetic, nested CFG, and aggregate collection
workloads were measured through one persistent process. The representative
median totals were 5.680 ms for Python-only and 48.752 ms for
Python-authority/Rust-shadow, an observed 8.582x ratio on this host. These are
observations, not absolute gates.

Rust-authority/Python-shadow is expected to have approximately the same 8.582x
over-Python-only cost on these workloads because it runs the same two
lowerings, verifiers, canonicalization, and comparison synchronously; reversing
which matched object is returned does not remove a lane. No speedup is required.

## Evidence and scope

The deterministic final artifact is
`rust_ssa_authority_promotion_qualification.json`; its generator is
`scripts/qualify_rust_ssa_authority_promotion.py`. It records hashes of every
input qualification artifact and `--check` reproduces the exact final bytes.
The raw observational timing record is
`rust_ssa_authority_promotion_performance.json`.

No policy, schema, lowering semantics, optimizer, backend, or canonical
comparison was changed. No prior blocked or qualified artifact was modified.
Python remains authority, no Rust SSA reaches a consumer, and no commit was
created.
