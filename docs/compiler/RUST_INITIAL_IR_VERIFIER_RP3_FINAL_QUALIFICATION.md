# RUST-1.3 — RP3 Final Promotion Qualification

Final decision: **`READY_FOR_RP3_AUTHORITY_SWITCH`**.

Python remains the production Initial IR verifier authority and the migration phase remains RP2. This qualification does not perform RUST-2.

## Current evidence

The canonical rule registry remains 150/150 in Python and 150/150 in Rust, with 0 semantic divergences and 3 accepted diagnostic-only divergences. Instruction and type coverage remain complete.

The final release-companion canary completed 404 comparisons: 316 accepted matches, 85 semantic reject matches, and 3 documented diagnostic divergences. All semantic, unexpected, protocol, startup, timeout, and infrastructure failure counts are zero.

| Gate | Status | Current evidence |
|---|---|---|
| OP1 | PASS | RUST-1.2.2 release index and four checksummed release artifacts |
| OP2 | PASS | platform qualification discovery, missing_companion and path_isolation checks |
| OP3 | PASS | platform metadata, unsupported_protocol and malformed_protocol checks |
| OP4 | PASS | authoritative failures are explicit; no silent semantic fallback |
| OP5 | PASS | RUST-1.2.1 deterministic B1 packaging contract |
| OP6 | PASS | RUST-1.2.2 four-platform executed release-artifact matrix |
| OP7 | PASS | .github/workflows/rust-verifier-operational.yml rust-authority-canary gate |
| OP8 | PASS | single _AUTHORITY_CONFIGURATION default rollback |
| OP9 | PASS | structured report, identity/version and VerifierSemanticDisagreement |
| OP10 | PASS | RUST-1.2.2 clean_install and path_isolation on every platform |

## RUST-2 handoff and rollback

The switch point is `src/aether/ir/shadow_verifier.py::_AUTHORITY_CONFIGURATION`: change `PYTHON_AUTHORITY_RUST_SHADOW` to `RUST_AUTHORITY_PYTHON_SHADOW`, and change the architecture registry from RP2 to RP3. Preserve fatal disagreement handling, the operational failure policy, and the Python verifier. Rollback restores that one default and the RP2 registry state; no semantic rollback is involved.

RUST-2 is limited to authority configuration, the phase registry, migration documentation/tests, and qualification artifacts. It must not change verifier semantics, protocol/schema, packaging, optimization, another compiler subsystem, or delete Python verification.

Python shadow must remain through RP3 soak, release/canary evidence, zero unresolved disagreement, and stable packaging/platform operation. Rust verifier authority does not imply a Python-free compiler distribution.
