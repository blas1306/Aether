# Rust SSA lowering implementation v3

Decision: `RUST_SSA_LOWERING_BLOCKED`

This attempt adds a native Rust lifecycle-normalization boundary, deterministic
typed phase errors, all-six pseudo dispatch, recursive default synthesis,
stored-source loads, ARC/interface-copy expansion, move/reset, relocation,
destruction, transferred-storage marker discharge, deterministic temporary
allocation, post-normalization validation, input immutability tests, and the
composed `lower_verified_ir_to_ssa_v1` entry point.

Qualification is blocked. The required 116/116 differential has not been
established, constructor invoke cleanup/continuation repair is not yet present,
and the composed entry point cannot claim verified SSA while it resides in
`aether-ir`: the authoritative SSA verifier is in the downstream
`aether-verifier` crate, which already depends on `aether-ir`. Adding it as a
dependency would create a cycle. The composition/verification boundary must be
qualified in a downstream crate or split into a dependency-neutral verifier.

The two historical blocked artifacts remain unchanged. Production lowering
authority, RP3, both policies, both schemas, Python lowering, optimizers, and
backends were not changed.
