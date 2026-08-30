# RUST-REFINE-2 — owned SSA refinement verifier shadow qualification

RUST-REFINE-2 is a qualification-only milestone. It does not promote Rust to
exclusive authority and does not retire Python's `SSARefinementVerifier`.
Production acceptance remains fail-closed:

```text
Rust owned-SSA refinement verifier
AND
Python SSARefinementVerifier
```

The functional baseline is commit
`b5835a5cc3c947333e6576791149767713dd0689` on `main`, with subject
`Implement Rust shadow SSA refinement verifier`. The remote `main` revision
observed before qualification infrastructure changes was that same SHA.

The dedicated manual workflow is
`.github/workflows/rust-refine-shadow-qualification.yml`. Its aggregate checker
accepts only official artifacts downloaded from the same GitHub Actions run,
validates run/revision identity plus the GitHub and downloaded ZIP digests, and
requires every dedicated, platform, and Python-version gate to succeed.

The only permitted final decisions are:

```text
RUST_REFINEMENT_SHADOW_QUALIFIED
RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED
```

Local tests validate the infrastructure but are not qualification evidence.
`RUST_REFINEMENT_SHADOW_QUALIFIED` may be recorded only from a successful
official `workflow_dispatch` run whose downloaded artifacts pass
`scripts/check_rust_refine_2_shadow_qualification.py`.
