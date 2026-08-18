# RUST-1.2 — RP3 operational readiness

## Decision

`RP3_OPERATIONAL_READINESS_BLOCKED`

Python remains the Initial IR verification authority and the migration phase
remains RP2. The production default is the single private
`_AUTHORITY_CONFIGURATION` in `src/aether/ir/shadow_verifier.py`, whose value
is `PYTHON_AUTHORITY_RUST_SHADOW` in the `DEFAULT` environment. Rust authority
is constructible only as `RUST_AUTHORITY_PYTHON_SHADOW` in the explicit
`CANARY` environment. There is no CLI or environment-variable authority
override and no automatic fallback.

Semantic readiness is complete and is not re-opened here. The historical
evidence is
`docs/compiler/rust_initial_ir_verifier_parity_closure.json`: 150/150 direct
evidence for both implementations, no unresolved semantic gap and no semantic
divergence. RUST-1.2 changes no verifier rule, Initial IR representation,
optimizer, or optimization level.

## Operational gates

| Gate | Status | Result |
| --- | --- | --- |
| OP1 binary availability | `BLOCKED` | No versioned companion artifacts have been published for every claimed platform. |
| OP2 discovery | `PASS` | Production-style discovery uses one explicit package directory and manifest. |
| OP3 version/protocol | `PASS` | Strict `--identity` handshake covers executable/package version, identity schema, protocol, IR schema and capabilities. |
| OP4 startup/failure | `PASS` | Missing, permissions, spawn, crash, nonzero exit, malformed output, limits and timeout are typed and fail closed. |
| OP5 packaging | `BLOCKED` | Packaging tooling exists, but release publication/install dependency is not established. |
| OP6 platforms | `BLOCKED` | Linux, Windows and macOS jobs exist; completed release-package evidence for all three is not checked in. |
| OP7 CI RP3 coverage | `PASS` | Rust-authority/Python-shadow is a required release-profile canary; packaging is a three-OS gate. |
| OP8 rollback | `PASS` | One configuration replacement restores Python authority; a Python→Rust→Python rehearsal exists. |
| OP9 diagnostics | `PASS` | Reports keep roles, comparison, request hash, protocol/schema, timing and bounded failure classification. |
| OP10 clean install | `BLOCKED` | Source-independent companion resolution is tested, but the unreleased combined install contract cannot be qualified. |

There are no `UNKNOWN` gates. OP1, OP5, OP6 and OP10 are promotion blockers.

## Discovery and packaging contract

Canonical RP3 discovery is deterministic:

1. An explicit path may be supplied by a test/development composition.
2. Production composition supplies one explicit, versioned companion package
   directory to `discover_packaged_rust_verifier()`.
3. Otherwise discovery fails.

The development helper may resolve an explicitly requested
`compiler-rs/target/{debug,release}/aether-ir-verifier[.exe]`, or `PATH` only
when `search_path=True`. Neither the current working directory, an environment
variable, the repository, nor `PATH` is consulted implicitly. Thus a checkout
`target/debug` binary cannot leak into packaged discovery.

RUST-1.2 selects **Model B: a separate versioned platform companion
artifact**. `scripts/package_rust_verifier.py` is the sole packaging command
and creates:

```text
<companion-root>/0.0.0/<sysconfig-platform>/
  manifest.json
  aether-ir-verifier[.exe]
```

The Python wheel remains platform-independent. The companion owns native
platform/architecture selection, executable permissions, the Windows `.exe`
name and real-filesystem installation. It is never executed from a compressed
Python resource. The sdist is source/development-oriented and never hides an
install-time Cargo build; production installations must eventually obtain the
published companion artifact explicitly.

The manifest records platform, filename, SHA-256 and runtime identity. SHA-256
detects damaged/mismatched release bytes; cryptographic signing is outside the
current release model. Unix executable mode is checked; Windows relies on its
native executable contract.

## Protocol, process, and failure policy

Compatibility is contractual, not an exact Git SHA: identity schema `1`,
package version `0.0.0`, verifier protocol `1`, Initial IR schema `1`, and the
exact `verify` capability must match. Older, newer, malformed, missing,
duplicated or extra identity fields are incompatible before verification.
Unsupported request protocol/schema is infrastructure failure, never semantic
rejection.

The subprocess remains canonical; PyO3/`aether-python` is not required for
RP3. The default finite timeout is five seconds and can be reduced explicitly
in tests. Request, stdout and stderr are bounded. Exit zero plus one strict
stdout JSON response is the protocol contract: accepted and semantic rejected
both exit zero. Nonzero exit, signal termination, invalid JSON, trailing data,
empty output and startup errors are operational failures. Stderr is bounded
transport metadata only; parsing never depends on its prose.

RP3 policy is fail closed. Rust infrastructure failure never promotes Python.
An unexpected semantic or diagnostic disagreement raises
`VerifierSemanticDisagreement` after the report preserves both observations.
Because Python shadow is required during initial RP3 migration, an unexpected
Python verifier crash also fails compilation and the CI promotion gate. No
external telemetry service is required.

## Platform, CI, installation, and performance findings

The repository claims host packages for Linux, Windows and macOS; architecture
is encoded by `sysconfig.get_platform()`. The workflow builds/runs all three,
compares timing-free platform snapshots, runs a required release-binary RP3
canary, packages a release companion on each OS and tests resolution outside
the checkout. Local evidence must not be represented as Windows/macOS
evidence. Until those release artifacts are published and retained as release
qualification, platform-scoped RP3 is rejected; Aether will not silently use
different authorities by OS.

The clean resolver test changes to a fresh temporary working directory,
removes the development PATH and proves the selected path contains no
`compiler-rs`. This qualifies the resolver and leakage guard, not the still
missing released Python-plus-companion installation contract.

The locked maintainer build is:

```console
cargo build --manifest-path compiler-rs/Cargo.toml --release --locked --package aether-ir-verifier
```

The packaging command is:

```console
python scripts/package_rust_verifier.py --output <artifact-directory>
```

`Cargo.lock` is committed and release builds use `--locked`. This establishes
dependency/input control, not bit-for-bit machine-code reproducibility.
Existing canary/performance evidence shows no pathological verifier overhead;
the subprocess startup remains acceptable for the migration gate. A local
25-invocation sanity sample was about 1.60 ms per release subprocess versus
1.69 ms for debug; the small empty-module Python verification was about 0.007
ms. These host-local numbers are diagnostic, not a cross-platform promotion
gate.

The release executable requalification completed all 404 comparisons: 316
accepted matches, 85 semantic rejection matches, three documented
diagnostic-only divergences, zero semantic mismatches, zero unexpected
results, zero infrastructure failures and zero timeouts. `complete` and
`successful` were both true. This confirms the requested release-profile
canary locally, but does not manufacture Windows or macOS release evidence.

## Promotion and rollback

The eventual RUST-2 switch point is deliberately not enabled by RUST-1.2. Once
OP1/OP5/OP6/OP10 pass, RUST-2 should only make the production default accept
`RUST_AUTHORITY_PYTHON_SHADOW` outside the canary restriction, retain Python as
required shadow, retain fail-closed infrastructure/disagreement policy and
the explicit companion resolver, update ownership evidence, and run full
authority qualification. It must not delete Python or migrate another
component.

Rollback is the inverse single configuration change back to
`PYTHON_AUTHORITY_RUST_SHADOW`; it requires no verifier semantic change,
binary deletion or automatic per-compilation fallback. Rust shadow evidence
can continue after rollback.
