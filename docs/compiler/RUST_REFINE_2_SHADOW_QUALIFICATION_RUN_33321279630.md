# RUST-REFINE-2 follow-up run 33321279630

GitHub Actions run `33321279630`, attempt 1, executed revision
`a18ed9acd7c928f991f3278cb4ecdaf39d0e7b64` from `main`. Its immutable
conclusion is `FAILED` and its decision is:

```text
RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED
```

This was a new `workflow_dispatch`, not a rerun of `33319278847`. The contract
job and every job other than `source-development-install` and the fail-closed
aggregate completed successfully. In particular, the contract artifact was
produced after installing the declared runtime requirements.

The source job installed the declared runtime requirements and `dev` dependency
group, the local native core, and the editable language package. It built the
debug `aether-ssa-shadow` companion and release `aether-ir-verifier`. The full
suite then executed:

```text
python -m pytest -q tests | tee qualification/rust-refine-2/full-pytest.log
exit code: 1
```

The result was `2 failed, 5179 passed, 12 skipped, 1 warning in 291.20s`.
Both remaining failures were the two RUST-REFINE-1 mutation qualification
tests already seen in run `33319278847`. With the companion now present, they
advanced to `_rust_outcome()` and attempted to execute:

```text
compiler-rs/target/debug/examples/verify_owned_ssa_refinement
```

`subprocess.run` reached `Popen`/`os.posix_spawn`, which raised
`FileNotFoundError: [Errno 2]` because the job had not built the example. This
was an additional repository-test build prerequisite masked in the first run
by the earlier missing-companion failure. It is a qualification harness defect,
not an acceptance divergence or a Rust refinement defect.

The source product probe was skipped, so `source.json` was absent. The aggregate
correctly emitted `RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED` and exited 1.
No evidence from this run may fill a gap in a later qualification.

The remediation adds `--example verify_owned_ssa_refinement` to the existing
source-job debug Cargo build. It does not change Rust source or verifier
behavior, exclude tests, weaken the aggregate, retire Python authority, or
promote Rust authority.
