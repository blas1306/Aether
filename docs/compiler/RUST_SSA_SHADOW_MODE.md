# RUST-3.3 Python-authority / Rust-shadow SSA lowering

Decision: **RUST_SSA_SHADOW_MODE_READY**.

`PYTHON_SSA_ONLY` is the production default and explicit rollback switch.
`PYTHON_SSA_AUTHORITY_RUST_SHADOW` first snapshots the already verified Initial
IR once, runs `GeneralSSABuilder` as the authority, sends that exact snapshot to
the persistent `aether-ssa-shadow` companion, verifies/imports schema-v2 Rust
SSA, canonicalizes both complete DTOs, and compares them. Only the Python object
is returned; Rust SSA is never passed to optimization or a backend.

Development and CI use fail-closed semantics. Semantic mismatch, startup or
transport failure, timeout, malformed response, Rust/Python SSA verifier
failure, and canonicalization failure raise `SSAShadowFailure`. Reports are
deterministic and bounded, with phase, first difference, canonical fragments,
function/block coordinates where available, and timing. Detailed artifacts are
kept by qualification jobs rather than dumped at runtime.

The transport is a synchronized persistent process using four-byte big-endian
length frames, a versioned startup identity, a 64 MiB response bound, and an
explicit timeout. Client counters expose process startups and requests; tests
assert multiple lowering requests do not imply multiple startups.

Qualification retains the already completed 116/116 historical parity,
adversarial corpus, and Python/Rust deep-CFG results. The shadow gate adds the
coordinator/authority/same-input/failure tests without replacing Python-only
tests. Timing is observational and has no fragile absolute gate.

The local 116-program persistent-transport run measured 0.381 s in Python
lowering, 1.835 s in the Rust lane, and 0.174 s in canonical comparison. It
issued 116 requests with one process startup. These measurements are evidence,
not pass/fail thresholds, and vary by host.
