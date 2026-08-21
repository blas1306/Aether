# RUST-3.6 SSA authority promotion

## Checked-in authority switch

The canonical `SSALoweringAuthorityConfiguration` default changed from
`PYTHON_SSA_ONLY` to `RUST_SSA_AUTHORITY_PYTHON_SHADOW`. Rust lifecycle
normalization, SSA construction, and `verify_owned_ssa` now form the authority
lane. Python's `GeneralSSABuilder` remains present and runs synchronously as the
mandatory shadow on the same verified Initial IR schema-v1 snapshot.

The Rust companion returns qualified SSA schema-v2. Python imports that result
into the existing `SSAModule` API and verifies the imported boundary. The
Python shadow is independently verified. The existing complete canonical
comparison then runs, and only a match allows the imported Rust object to pass
to the optimizer and backend. Regression instrumentation checks object
identity; it does not infer origin from the enum alone.

```text
verified Initial IR snapshot
        |                 |
        v                 v
 Rust lifecycle/SSA   Python GeneralSSABuilder
        |                 |
 Rust Owned verifier  Python SSA verifier
        |                 |
 schema-v2 import     canonical schema-v2
        |                 |
        +---- exact comparison ----+
                       |
                       v
          imported Rust SSAModule
                       |
                 optimizer/backend
```

## Fail-closed policy

Startup, timeout, transport, framing, identity, product/protocol/schema,
lowering, lifecycle, Rust verification, schema import, Python shadow,
Python verification, canonicalization, and mismatch failures abort compilation
and return no SSA. The Python result is never a fallback. A timeout terminates
the affected persistent companion session, and the failed request is not
retried.

Production discovery resolves only
`<python-prefix>/libexec/aether/ssa-shadow/manifest.json` and validates the
manifest, platform, executable name, checksum, permissions, and runtime
identity. There is no PATH, checkout-relative, or Cargo debug fallback. One
process-wide synchronized client retains the qualified persistent transport.

## Rollback

Both rollback modes remain ordinary selections of the same immutable
configuration type:

- `PYTHON_SSA_AUTHORITY_RUST_SHADOW` returns verified Python SSA only after a
  synchronous Rust match.
- `PYTHON_SSA_ONLY` returns verified Python SSA without requiring the
  companion.

Neither rollback requires a schema, policy, lowering, optimizer, backend, or
source semantic change.

## Evidence and CI

The historical RUST-3.5 artifacts remain unchanged and continue to establish
116/116 lifecycle/canonical/verification/import/reserialization/determinism,
adversarial and deep-CFG closure, and the 132/132 zero-failure pre-promotion
soak. They are readiness evidence, not post-promotion platform evidence.

`scripts/qualify_rust_ssa_authority_platform.py` performs the authority
revision in a clean installed wheel, installs the release companion at the
strict canonical location, proves multiple Rust-authoritative requests,
synchronous Python comparison, Rust-object return origin, optimizer/backend
handoff, and both rollback modes. CI runs it natively on Linux x86_64, Windows
x86_64, macOS arm64, and macOS x86_64.

`scripts/check_rust_ssa_authority_promotion.py` is evidence-only. It refuses to
substitute the pre-promotion platform reports for new RUST-3.6 reports. The
focused pipeline, historical 116/116 corpus, 132/132 soak, Linux clean
installation, and representative optimizer/backend probes pass. The full
repository run remains fail closed on newer aggregate collection,
class/interface, constructor ownership, and exceptional-cleanup inputs. Fresh
Windows x86_64, macOS arm64, and macOS x86_64 authority reports are also not
available on this host. Consequently, the checked-in deterministic decision
is:

    RUST_SSA_AUTHORITY_PROMOTION_FAILED

The exact current blockers are recorded in
`rust_ssa_authority_promotion.json`. Once semantic closure is requalified and
CI supplies all four valid native reports, the same checker with
`--require-promoted` can emit only:

    RUST_SSA_AUTHORITY_PROMOTED

No policy, lifecycle rule, schema, canonical comparison, optimizer behavior,
or backend behavior changed in this milestone. Python SSA remains preserved,
and no commit is created by the qualification tools.
