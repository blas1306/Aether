# Rust verifier operational readiness

## Scope and authority

Phase 4.5D hardens deployment boundaries only. It does not change an Initial
IR invariant, diagnostic ordering, request encoding, comparison rule, or
authority decision.

The checked-in default remains
`PYTHON_AUTHORITY_RUST_SHADOW`. Python controls compilation and Rust is
observational. `RUST_AUTHORITY_PYTHON_SHADOW` remains an available, fail-closed
configuration for a future rollout. Phase 4.6 subsequently restricted that
mode to the explicit canary environment described in
`RUST_VERIFIER_CANARY.md`; the production default is unchanged.

## Operational architecture

```text
deployment configuration
        |
        v
versioned platform package
  manifest.json + executable
        |
        v
path/name -> SHA-256 -> --identity
        |
        v
exact version/protocol/schema/features
        |
        v
bounded subprocess client
        |
        v
VerifierAuthorityPipeline
  Python authority / Rust shadow
```

The production resolver is
`discover_packaged_rust_verifier(package_directory)`. It reads exactly
`manifest.json` and the named executable from one explicitly configured
directory. It does not consult `PATH`, an environment variable, the current
working directory, an unversioned install location, or a second package
version.

`scripts/package_rust_verifier.py` creates this layout:

```text
<output>/
  0.0.0/
    <sysconfig platform tag>/
      manifest.json
      aether-ir-verifier[.exe]
```

The manifest locks its own schema, platform tag, executable basename, SHA-256,
and the complete runtime identity. The resolver verifies bytes before starting
the executable and then requires the runtime identity to equal the manifest.
The returned selection contains the canonical absolute path, content hash, and
reported identity. These three values are the stable executable identity to
record in deployment metadata.

The older `discover_rust_verifier_executable()` remains a development helper.
Its order is explicit path, explicitly requested repository/profile, and
explicitly opted-in `PATH`. `PATH` lookup defaults to off and can never outrank
a requested repository artifact.

## Version and capability contract

The executable exposes two metadata-only commands:

```console
aether-ir-verifier --version
aether-ir-verifier --identity
```

`--version` is for operators. `--identity` emits strict, compact JSON with:

- identity schema version `1`;
- executable identity `aether-ir-verifier`;
- package version `0.0.0`;
- supported verifier protocol versions `[1]`;
- supported Initial IR schema versions `[1]`; and
- feature capabilities `["verify"]`.

`SubprocessRustVerifierClient` validates this identity before its first request
and caches it for that client instance. Every field is exact: unknown, missing,
additional, unsorted, duplicated, older, or newer values fail startup. A
protocol version, IR schema version, capability set, executable name, identity
schema, or release-version mismatch raises
`RustVerifierIncompatibleExecutable` naming the incompatible field. Invalid
identity output raises `RustVerifierInvalidExecutable`. There is no capability
downgrade or silent fallback.

The low-level legacy `verify_module_with_rust()` compatibility API retains its
single-request behavior and strict response-version decoding. Production and
authority/shadow construction use `SubprocessRustVerifierClient`, whose startup
validation is enabled by default.

## Supported environments and platform evidence

The operational contract supports the host Rust executable on:

| Platform | Executable | Operational snapshot |
| --- | --- | --- |
| Linux | `aether-ir-verifier` | locally validated |
| Windows | `aether-ir-verifier.exe` | required CI matrix gate |
| macOS | `aether-ir-verifier` | required CI matrix gate |

`.github/workflows/rust-verifier-operational.yml` builds and executes the same
corpus snapshot on all three systems. Its comparison job requires the three
JSON artifacts to be byte-identical. The snapshot contains all 141
schema-v1-transportable migration cases and, for every case, the canonical
request SHA-256, migration classification, and timing-free differential
report. Platform paths, timings, binary hashes, and host metadata are
deliberately absent.

The current Linux snapshot has 65 accepted matches, 73 semantic rejection
matches, three documented diagnostic divergences, zero documented outcome
divergences, and zero unexpected divergences. Repeated local snapshot
generation is byte-identical.

Platform-specific observations:

- Windows uses the `.exe` basename and does not rely on POSIX executable mode
  bits. Process exit and timeout classifications remain typed and path-free.
- Linux and macOS require an executable file according to host access checks.
- JSON is strict UTF-8 with an explicit LF, sorted canonical request keys, and
  timing-free reports; native path separators and text-mode newline conversion
  never enter a request or snapshot.
- A platform package is accepted only when its manifest platform tag equals
  the running Python platform tag.

The matrix result is a release prerequisite. Local Linux evidence alone does
not substitute for completed Windows and macOS jobs.

## Startup validation and diagnostics

Startup failures never become semantic verifier outcomes. Their public
diagnostics omit paths and operating-system prose:

| Condition | Stable diagnostic |
| --- | --- |
| missing artifact/manifest | `RustVerifierExecutableNotFound` |
| file not executable | `RustVerifierNotExecutable` |
| invalid executable format or identity | `RustVerifierInvalidExecutable` |
| package bytes corrupted | `RustVerifierExecutableIntegrityError` |
| version/protocol/schema/features mismatch | `RustVerifierIncompatibleExecutable(field)` |
| bounded startup or request timeout | `RustVerifierTimeout` |
| nonzero verifier request exit/crash | `RustVerifierProcessFailure(status)` |
| other spawn refusal | `RustVerifierSpawnFailure(OS exception class)` |

Stdout and stderr remain bounded. A nonzero request exit is never trusted even
when stdout resembles an accepted protocol response. A package hash mismatch
is rejected before the damaged file is executed. Rust panics that reach the
binary boundary remain contained by the existing deterministic `internal`
protocol response.

## Authority activation and rollback

Authority is selected only through one immutable
`VerifierAuthorityConfiguration`. Deployment composition constructs the
existing `VerifierAuthorityPipeline` with one of its two closed modes; no
independent booleans, fallback, pipeline branch, or executable lookup policy is
changed.

Activation rehearsal:

1. Start with `PYTHON_AUTHORITY_RUST_SHADOW`.
2. Verify package identity and platform snapshot evidence.
3. Change the deployment configuration object to
   `RUST_AUTHORITY_PYTHON_SHADOW` in
   `VerifierAuthorityEnvironment.CANARY`.
4. Observe the existing comparison and failure telemetry.
5. To roll back, restore `PYTHON_AUTHORITY_RUST_SHADOW`.

The operational test performs that exact Python -> Rust -> Python sequence
against the real executable. Each engine still executes once in every mode;
only `AuthorityResult` and `ShadowResult` role selection changes. There is no
source mutation, recompilation, migration, retry, fallback, or pipeline
refactoring during the rehearsal.

Rust authority is fail-closed. A Rust timeout, crash, invalid response,
protocol failure, or unavailable executable fails verification; the Python
shadow is never promoted implicitly. Rollback is an explicit configuration
change, not an automatic fallback.

## Soak execution

`scripts/rust_verifier_soak.py` repeatedly runs:

- the complete migration adapter corpus;
- the differential/shadow corpus;
- compiler example smoke tests; and
- the benchmark suite.

Every run uses the explicit content-identified executable and the
Python-authoritative shadow harness. The JSON report records suite runs,
completed pytest tests, verifier observations, suite failures, suite timeouts,
verifier failure kinds, comparison classifications, and a timing-free
fingerprint for each suite/iteration. A successful soak requires zero suite
failures, zero timeouts, zero verifier infrastructure/integration failures,
and identical fingerprints across iterations.

Example:

```console
python scripts/rust_verifier_soak.py \
  --executable compiler-rs/target/release/aether-ir-verifier \
  --iterations 10 \
  --output build/rust-verifier-soak.json
```

## Production release checklist

- [ ] Build with the locked Rust dependency graph and the intended release
      profile.
- [ ] Create one package per supported platform with
      `scripts/package_rust_verifier.py`.
- [ ] Archive the manifest, canonical executable path, SHA-256, `--version`,
      and `--identity` output in release evidence.
- [ ] Resolve the package through `discover_packaged_rust_verifier`; do not use
      `PATH` in production.
- [ ] Confirm package version, identity schema, protocol version, IR schema
      version, and exact capability set.
- [ ] Complete packaging and startup tests, including corrupt-artifact
      injection.
- [ ] Complete byte-identical Linux, Windows, and macOS platform snapshots.
- [ ] Complete migration, differential, examples, benchmark, shadow,
      authority-pipeline, and soak gates with no unexpected divergence,
      infrastructure failure, or timeout.
- [ ] Confirm the deployed authority configuration before activation.
- [ ] Rehearse Python -> Rust -> Python role changes using configuration only.
- [ ] Retain the known-good Python-authority configuration and previous Rust
      package for immediate explicit rollback.
- [ ] During the Phase 4.6 canary, change only the authority configuration to
      `RUST_AUTHORITY_PYTHON_SHADOW` in the explicit canary environment.
- [ ] After a future switch, monitor comparison classifications, invariant
      distributions, request hashes, startup compatibility, process failures,
      timeouts, latency percentiles, and package SHA-256.
- [ ] Roll back on any unexpected outcome divergence, incompatible identity,
      sustained timeout/process failure, or unreviewed diagnostic shift.

## Phase 4.5D validation commands

```console
pytest -q tests/aether/test_rust_verifier_adapter_integration.py
pytest -q tests/aether/test_shadow_verifier_integration.py
pytest -q tests/aether/test_shadow_validation_harness.py
pytest -q tests/aether/test_shadow_verifier.py
pytest -q tests/aether/test_rust_verifier_operational.py
python scripts/rust_verifier_platform_snapshot.py --executable <path> --output <path>
python scripts/rust_verifier_soak.py --executable <path> --iterations 3 --output <path>

cd compiler-rs
cargo fmt --all --check
cargo check --workspace
cargo test --workspace
cargo clippy --workspace --all-targets --all-features -- -D warnings
cd ..
git diff --check
```

## Phase execution evidence

Local Phase 4.5D evidence was collected on Linux x86_64:

- release-profile packaging produced and re-resolved
  `0.0.0/linux-x86_64/manifest.json` plus `aether-ir-verifier`; the resolved
  identity reported version `0.0.0`, protocol `[1]`, IR schema `[1]`, and
  capabilities `["verify"]`;
- the 141-case platform snapshot was generated twice with identical SHA-256
  `26e92a30fa9fbd0fc6be2ac306be59312d1a56f30d062be99f38f6d69d565e54`;
- the two-iteration soak completed 10 operational runs and 136 pytest test
  executions, with 328 injected-shadow observations and 282 complete-corpus
  snapshot observations;
- soak comparisons were 458 accepted matches, 146 semantic rejection matches,
  and six documented diagnostic divergences across the two repetitions;
- soak failures, verifier failure kinds, and timeouts were all zero, and all
  five timing-free fingerprints were identical between repetitions;
- focused packaging/startup/shadow/authority/migration tests passed 120/120,
  followed by a 23/23 operational/differential rerun after the soak;
- repository-wide shadow validation completed all 4,239 collected tests:
  4,234 passed, one skipped, and the same four pre-existing V1 example-manifest
  failures recorded by the prior baseline;
- that full shadow run produced 1,675 observations: 1,674 accepted matches and
  one semantic rejection match, with zero verifier failure kinds and no
  privacy marker hits; and
- `cargo fmt --all --check`, `cargo check --workspace`,
  `cargo test --workspace`, Clippy with warnings denied, Python compilation,
  and `git diff --check` passed.

Windows and macOS execution cannot be produced by a Linux-only local host. The
three-platform workflow and byte-identity comparison are implemented, but both
non-Linux jobs must complete before a production release may check the
supported-platform item above.
