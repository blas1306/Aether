# RUST-4.5A — differential qualification environment isolation

RUST-4.5A changes qualification infrastructure only. It does not change Rust
SSA lowering, Python `GeneralSSABuilder`, refinement or generic verifier
semantics, authority semantics, rollback, schema, protocol, optimizer, or
backend behavior.

## Root cause and six focused failures

GitHub Actions run `33110365185` set
`AETHER_SSA_AUTHORITY_MODE=rust_ssa_authority_python_shadow` at the whole-job
scope of `rust-4.5-ci-differential-rust-refinement-python-shadow`. The
qualification script copied that environment into its focused-test subprocess
and also constructed `SSALoweringAuthorityConfiguration()` in the contaminated
parent process to infer `new_default`.

The exact local reproduction was `36 passed, 6 failed`. Every failure was a
production-default contract executed under the explicit differential mode:

| Node ID | Expected policy | Observed policy | Cause |
|---|---|---|---|
| `test_default_returns_the_exact_imported_verified_object` | refinement-verified Rust default and exact shadow-independent import | Rust authority plus Python differential shadow | inherited override; the differential importer ran instead of the default path |
| `test_new_default_fails_closed_without_python_fallback[response0]` | default transport failure wrapped by the shadow-independent fail-closed path | differential `SSAShadowFailure` | inherited override |
| `test_new_default_fails_closed_without_python_fallback[response1]` | default malformed response rejected by the shadow-independent path | differential lane attempted its response contract | inherited override |
| `test_new_default_fails_closed_without_python_fallback[response2]` | default Rust rejection wrapped by the shadow-independent path | differential `SSAShadowFailure` | inherited override |
| `test_new_default_fails_closed_without_python_fallback[response3]` | default schema import failure wrapped by the shadow-independent path | differential malformed-response failure | inherited override |
| `test_new_default_refinement_failure_is_mandatory_and_closed` | default independent refinement rejection | differential pipeline did not call the patched shadow-independent verifier | inherited override |

No failure reproduced when the default probe removed the override. The focused
differential tests passed under the explicit override. Therefore these six
failures do not reveal a production SSA regression.

## Isolated observations

The qualification harness now constructs environments explicitly:

- `production_default_observation` removes `AETHER_SSA_AUTHORITY_MODE` from a
  copy of the caller environment. It must observe Rust authority, mandatory
  refinement, no Python builder, and no canonical comparison.
- `differential_mode_observation` sets the variable to
  `rust_ssa_authority_python_shadow`. It must observe Rust authority, mandatory
  refinement, Python builder execution, canonical comparison, and fail-closed
  semantic mismatch and refinement failure.

The default is resolved from an explicitly empty authority environment; it is
never inferred from the qualification process environment. The workflow now
scopes the override only to the focused differential step, while the harness
sets or removes it for each subprocess probe.

The differential artifact uses the specific decision
`RUST_SSA_DIFFERENTIAL_SHADOW_QUALIFIED` (or
`RUST_SSA_DIFFERENTIAL_SHADOW_BLOCKED`). This decision qualifies the
differential lane only and does not promote production globally.

## Fail-closed CI

After generating `qualification/rust45/differential.json`, the workflow runs
`scripts/check_rust_ssa_differential_qualification.py`. A blocked, malformed,
or internally inconsistent artifact makes that step and therefore the job
fail. Artifact upload retains `if: always()` so diagnostic evidence remains
available after failure.

The formal closure for run `33110365185` remains blocked and immutable. A new
promotion closure must consume artifacts from a new run on one exact revision;
the historical artifact is not reused or rewritten.
