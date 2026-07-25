# Rust verifier authority canary

## Purpose and boundary

Phase 4.6 validates the Rust Initial IR verifier as the real authority in
controlled CI executions. It does not change the product or repository
default:

```text
default:  Python authority -> Rust shadow -> comparison -> report
canary:   Rust authority   -> Python shadow -> comparison -> report
```

Both flows execute Python and Rust exactly once. Comparison and reporting
finish before the selected authority is resolved. A Rust rejection or
operational failure therefore controls a canary result, while the Python
outcome remains present in the shadow report. There is no fallback from Rust
authority to Python inside one execution.

Rust authority is structurally restricted to
`VerifierAuthorityEnvironment.CANARY`. Constructing
`RUST_AUTHORITY_PYTHON_SHADOW` in the default environment is rejected. The
installed package has no command-line or environment-variable authority
selector, and its immutable default remains
`PYTHON_AUTHORITY_RUST_SHADOW`.

## Explicit configuration and activation

The checked-in configuration is
`tests/canary/rust_verifier_canary.json`. It is outside the installed package
and declares:

- the canary environment and Rust-authority/Python-shadow roles;
- mandatory Python execution, comparison, and reporting;
- the subprocess timeout;
- the four required canary populations.

The loader requires an exact schema, rejects duplicate or unknown fields, and
requires sorted unique suite names. Changing an environment variable cannot
activate it.

Run the complete canary from the repository root after building the verifier:

```bash
cargo build --manifest-path compiler-rs/Cargo.toml \
  --locked --package aether-ir-verifier
python scripts/rust_verifier_canary.py \
  --config tests/canary/rust_verifier_canary.json \
  --executable compiler-rs/target/debug/aether-ir-verifier \
  --output-directory rust-authority-canary-reports
```

Activation requires the configuration path, executable path, output
directory, and each configured population selected by the runner. The pytest
harness similarly requires its config, executable, output, and population
options together. Partial option sets fail before collection, and shadow
validation and canary activation are mutually exclusive.

The runner executes:

- the full transportable migration corpus;
- the critical differential corpus;
- all examples in `examples/ir`;
- the repository benchmark suite.

The GitHub Actions `rust-authority-canary` job invokes this exact runner. The
existing platform and operational jobs remain Python-authoritative. The canary
job is non-blocking and cannot rewrite the default authority configuration.

## Rollback

Rollback means removing the explicit canary selection and constructing the
ordinary default configuration. No verifier implementation, comparison logic,
or compiler call site changes:

```text
VerifierAuthorityConfiguration(PYTHON_AUTHORITY_RUST_SHADOW)
    -> VerifierAuthorityConfiguration(
           RUST_AUTHORITY_PYTHON_SHADOW,
           CANARY,
       )
    -> VerifierAuthorityConfiguration(PYTHON_AUTHORITY_RUST_SHADOW)
```

`test_authority_rollback_rehearsal_uses_configuration_only` executes that
Python -> Rust canary -> Python sequence against the real subprocess verifier
and verifies the authority/shadow roles for every step. Operational rollback
is immediate: stop supplying the test-only canary configuration. The next
ordinary construction uses Python authority and Rust shadow.

## Monitoring and deterministic summaries

Every population writes a stable-key-order, timing-free JSON summary. The
runner also writes `canary-summary.json`, which aggregates:

- Rust-authoritative accepted, rejected, and unavailable module counts;
- total comparisons and counts by closed comparison classification;
- verifier timeouts;
- all Rust infrastructure failures;
- protocol failures returned by the verifier;
- startup/identity/spawn failures;
- integration failures and stable failure kinds;
- suite exit codes and summary completeness.

Request bodies, source text, process identifiers, environment values, host
paths, and timing samples are not recorded. Request hashes and a SHA-256 of
the timing-free semantic snapshots support deterministic comparison without
retaining payloads. Counter keys, suite keys, and request hashes are sorted
before serialization.

Any Rust timeout, protocol failure, startup failure, or other integration
failure is fail-closed inside the canary. Its report is emitted before the
authority error is raised, so the failure remains observable.

## Exit criteria

Before evaluating promotion, the release owner must record the project-policy
window of multiple consecutive canary runs to evaluate. Phase 4.6 deliberately
does not invent a run count. Leaving canary requires all of the following
throughout that predeclared window:

- every required canary population completes successfully on every run;
- semantic mismatch classifications remain zero;
- infrastructure, protocol, startup, integration, and timeout failures remain
  zero;
- no unexpected or skipped comparison classification occurs;
- migration and critical differential corpus expectations remain unchanged;
- Linux, Windows, and macOS platform snapshots remain byte-identical;
- verifier identity, protocol version, IR schema version, and capability
  snapshots remain stable;
- Python shadow execution and report availability are confirmed;
- the rollback rehearsal continues to pass using configuration changes only.

Promotion is a separate phase and decision. Satisfying these criteria does not
change authority automatically and does not authorize removing the Python
verifier or its comparison path.
