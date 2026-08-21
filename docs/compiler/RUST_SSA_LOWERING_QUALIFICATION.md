# Rust SSA lowering qualification

Decision: `RUST_SSA_LOWERING_BLOCKED`

This RUST-3.1d attempt completes the policy-v1 direct-constructor exceptional
ownership repair in `aether-ir`. An owning direct `*.__ctor` invoke now receives
one unique exceptional trampoline containing, in order, `catch_entry`,
`__aether_release(receiver)`, and `propagate` to the original handler. Owning
struct receivers are also released at the start of the normal continuation;
owning class receivers are not. Indirect and interface invokes are intentionally
unchanged because the normative policy provides no constructor identity for
those forms. Existing invoke metadata and source location are preserved.

Construction and qualification remain separate. `aether-ir` provides
`normalize_lifecycle_v1`, `lower_normalized_ir_to_ssa_v1`, and
`lower_verified_ir_to_ssa_v1`; it does not depend on `aether-verifier`.

Complete qualification cannot be claimed. The Rust construction API emits
`OwnedSsaModule` and schema-v2 (`SSAModuleV2DTO`), while the authoritative wire
verifier in `aether-verifier` accepts only the frozen schema-v1 `SSAModuleDTO`.
The other authoritative SSA verifier accepts the older owned `IRModule`, not
`OwnedSsaModule`. There is therefore no authoritative verification entry point
for the exact Rust lowering result. Converting schema-v2 to schema-v1 would be
lossy for `bounds_checked`, and duplicating verifier semantics in `aether-ir`
would violate crate layering. No such conversion or duplicate verifier was
introduced.

Consequently the required differential gates were not run to a qualifying
conclusion: lifecycle parity 0/116 established, Rust construction 0/116
established, authoritative Rust verification 0/116 established, and semantic
SSA parity 0/116 established. There are no classified semantic mismatches; the
qualification lane is blocked before comparison. Phase timings are therefore
not reportable for a complete lane.

The focused `aether-ir` lifecycle tests pass, including deterministic temporary
and cleanup naming, nested owning fields, an exceptional target with existing
instructions, simultaneous normal/exceptional successors, source-location
preservation, ordered cleanup, and input immutability. The complete existing
`aether-ir` suite also passes.

Initial IR schema-v1, SSA schema-v2, `lowering_policy_v1`, and
`lifecycle_normalization_policy_v1` are unchanged. Python remains production SSA
lowering authority. RP3, optimizer/backend semantics, and all historical V1,
V2, and V3 blocked artifacts are unchanged. No commit was created.
