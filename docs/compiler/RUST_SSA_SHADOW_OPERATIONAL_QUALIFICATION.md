# RUST-3.4 Rust SSA shadow operational qualification

Decision: **RUST_SSA_SHADOW_OPERATIONALLY_BLOCKED** pending imported native-runner evidence.

The former aggregate semantic blocker is closed. The reproducible Linux soak
now compares every program reaching SSA: 161 discovered, 132 compared, zero
semantic mismatches and zero infrastructure failures. The final decision is
deliberately evidence-only; configuring a CI matrix does not qualify a
platform. The aggregate becomes qualified only after canonical reports from
all four official runners have executed and passed.

| Gate | Local/current result | Final evidence source |
|---|---|---|
| SO1 persistent transport | PASS | Linux complete soak |
| SO2 same-input guarantee | PASS | differential harness |
| SO3 semantic differential | PASS | 132/132 comparisons |
| SO4 fail-closed semantic mismatch | PASS | regression suite |
| SO5 fail-closed infrastructure | PASS | regression suite |
| SO6 clean installation | PENDING | each native platform report |
| SO7 packaged companion discovery | PASS | manifest/checksum contract |
| SO8 long-session isolation | PASS | 1,000 requests, one process |
| SO9 concurrency safety | PASS | 128 serialized requests, one process |
| SO10 cross-platform execution | PENDING | four imported native reports |
| SO11 rollback | PASS | `PYTHON_SSA_ONLY`, no companion |
| SO12 CI qualification | PASS | strict matrix plus aggregate job |

## Companion contract

The SSA product reuses the native companion architecture established by
`aether-ir-verifier`; it does not introduce a second packaging system. Its
product is `aether-ssa-shadow`, versioned from the Cargo workspace, with
executable `aether-ssa-shadow[.exe]`, protocol 1, Initial IR schema 1 input,
SSA schema 2 output, and capability `lower_verified_ssa_shadow`.

Each deterministic platform archive contains the binary, `manifest.json`, and
license. A SHA-256 sidecar and `ssa-shadow-companions.json` index identify the
archive. Runtime discovery accepts only an explicit extracted companion
directory, validates the exact manifest, platform, checksum, executable name,
and startup identity, and never consults PATH, a checkout, or Cargo artifacts.
The canonical machine-readable contract is
`rust_ssa_shadow_companion_packaging.json`.

## Executed local evidence

- Aggregate lifecycle/canonical mismatch: closed.
- Expanded soak: 161 discovered; 132 reached SSA and were all compared; 0
  semantic mismatches; 0 infrastructure failures.
- Long session: 1,000 sequential requests through one persistent process;
  deterministic responses and stable observed Linux RSS.
- Concurrency: 128 client requests serialized through one process with no
  crossed framing.
- Rollback: `PYTHON_SSA_ONLY` remains the default and requires no companion.

The workflow builds the release binary and Python wheel, installs the wheel in
a temporary environment outside the checkout, extracts the native companion,
isolates PATH, starts one persistent process, executes multiple representative
comparisons, verifies clean shutdown, and uploads the report, archive, and
checksum. Linux additionally runs the full semantic soak. The aggregate CLI
rejects missing, duplicate, wrong-platform, unchecked, or checksum-invalid
evidence before emitting `RUST_SSA_SHADOW_OPERATIONALLY_QUALIFIED`.

Python remains the SSA authority. Rust SSA is comparison-only and never
reaches the optimizer or backend.
