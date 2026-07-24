# Initial IR verifier authority infrastructure

## Phase 4.5B scope

Phase 4.5B makes authority a centralized internal policy without changing the
active policy. Python remains authoritative, Rust remains observational, and
the existing direct Python path remains available when no dual-verifier
pipeline is explicitly configured. This phase performs no subprocess rollout,
executable discovery, CLI or environment-variable selection, fallback, PyO3
integration, or verifier semantic change.

The internal feature flag is the single `_AUTHORITY_CONFIGURATION` assignment
in `aether.ir.shadow_verifier`. It contains one
`VerifierAuthorityConfiguration`, whose closed mode enum permits exactly:

| Mode | Authority | Shadow |
| --- | --- | --- |
| `PYTHON_AUTHORITY_RUST_SHADOW` | Python | Rust |
| `RUST_AUTHORITY_PYTHON_SHADOW` | Rust | Python |

There are no independent authority/shadow booleans and no representation for
both-authoritative, both-shadow, Python-only, Rust-only, or disabled-shadow
policy. The repository default is `PYTHON_AUTHORITY_RUST_SHADOW`.
`VerifierAuthorityPipeline` reads the configuration once when it is
constructed. Focused tests may pass the other immutable configuration
directly; ordinary compiler and harness construction uses the internal
default.

## Execution flow

An explicitly configured dual-verifier pipeline owns the complete policy:

```text
VerifierAuthorityConfiguration
                |
                v
      VerifierAuthorityPipeline
          /              \
         v                v
 Python execution    Rust execution
         \                /
          v              v
        ComparisonResult
                |
                v
 ShadowVerificationReport
                |
                v
   resolve AuthorityResult only
```

Each semantic verification runs exactly once. Comparison remains ordered by
implementation—Python key versus Rust key—so existing hash-scoped divergence
rules and corpus results do not depend on which side is authoritative. Role
selection then produces:

- `AuthorityResult(implementation, outcome)`;
- `ShadowResult(implementation, outcome)`; and
- `ComparisonResult`, independent of authority.

The immutable report exposes all three. Its compatibility `authoritative` and
`shadow` properties retain the existing role-based views. Under the default
configuration, the timing-free semantic snapshot is byte-for-byte structurally
identical to the Phase 4.3 report: no authority field was inserted into the
persisted snapshot, and request hashing is unchanged.

`IRBackend` stores the explicitly injected pipeline as
`verification_pipeline`. The former `shadow_verifier` constructor and
attribute spelling remains as a compatibility boundary for the validation
harness; verification itself delegates to the authority pipeline. When no
pipeline is injected, `IRBackend` retains the pre-rollout direct Python
verification path, so Phase 4.5B does not discover or start a Rust executable
during ordinary compilation.

## Fail-closed authority and no fallback

Only the selected `AuthorityResult` controls the compiler result. The shadow
result is never resolved as a substitute:

- authoritative semantic acceptance returns the module;
- authoritative semantic rejection fails verification;
- authoritative infrastructure or protocol failure fails verification;
- authoritative request construction, subprocess, malformed-response,
  process-exit, or timeout failure fails verification; and
- a report-sink failure cannot replace an authoritative rejection or
  operational failure.

Rust-authoritative semantic rejection is represented by
`AuthoritativeVerifierRejected`. Rust-authoritative operational failure is
represented by `AuthoritativeVerifierUnavailable`. `IRBackend` translates both
through its existing IR verification error boundary. It never retries with the
Python shadow. Python-authoritative behavior continues to re-raise the original
`IRVerificationError` object with its traceback, exactly as before.

No fallback is intentional. Falling back after an authority failure would make
authority depend on machine health, timeout timing, protocol compatibility, or
the type of rejection. That would produce nondeterministic compiler semantics
and conceal rollout defects.

## Why shadow always executes

For every configured dual-verifier semantic operation, both Python and Rust
execute before authority is resolved. This remains true when:

- Python accepts and Rust rejects;
- Python rejects and Rust accepts;
- both reject with different diagnostics; or
- Rust produces a trusted infrastructure result.

Consequently, switching authority does not remove comparison, reporting,
request hashes, shadow observations, or divergence detection. Shadow execution
is evidence only. It cannot accept a module rejected by the authority, reject a
module accepted by the authority, or rescue an unavailable authority.

Unexpected implementation bugs outside the modeled verifier outcomes continue
to propagate rather than being relabeled as semantic or transport results.

## Backward compatibility

With the default Python-authoritative configuration:

- the original Python module identity or `IRVerificationError` remains the
  compiler result;
- Rust failures remain observational;
- canonical protocol-v1 bytes and SHA-256 request hashes are unchanged;
- comparison classifications and divergence registry matching are unchanged;
- semantic report snapshots are unchanged; and
- no manifest, diagnostic, exit-code, IR, SSA, LLVM, or native behavior is
  selected by the new configuration.

The full migration corpus and shadow regression remain the compatibility
oracles. Rust-authority tests use controlled clients and do not alter the
repository-wide feature flag.

## Future rollout

A later, separately approved rollout may provide the production Rust client
and change only `_AUTHORITY_CONFIGURATION` to
`RUST_AUTHORITY_PYTHON_SHADOW`. Before that change, the authority proposal must
retain the full migration corpus, fail-closed integration tests, packaging and
version matching, supported-platform evidence, the reviewed IRV-024 policy,
and an operational rollback plan.

Changing authority must not add fallback. Rollback is an explicit deployment
or source-policy change back to Python authority, never a per-compilation
retry.
