# RUST-3.D — Owned SSA verifier qualification

Decision: `RUST_OWNED_SSA_VERIFIER_QUALIFIED`

## Architecture

`aether-verifier::verify_owned_ssa(&OwnedSsaModule)` is the authoritative owned-model
entry point. It adapts the owned model to the existing value-based semantic rule
engine inside `aether-verifier`; the rules themselves are not copied. The eight
schema-v2 collection instructions retain their `bounds_checked` value in the
canonical adapter while their pre-existing operands are checked by the same rules.
No JSON serialization or schema-v1 decoding is used by the semantic API.

The historical `verify_ssa_module_dto` entry point remains available and unchanged.
The dependency direction remains `aether-verifier -> aether-ir`; `aether-ir` does
not depend on the verifier.

## Qualification

- Current verified Python SSA corpus: 116/116 accepted through
  schema-v2 -> `OwnedSsaModule` -> `verify_owned_ssa`.
- Differential schema-v2 output: 116/116 exact matches.
- `bounds_checked`: both `true` and `false` accepted and preserved for ArrayGet,
  ArraySet, ListGet, ListSet, VectorGet, VectorSet, MatrixGet, and MatrixSet.
- Negative owned test: malformed phi incoming set rejected with the historical,
  deterministic function/block diagnostic.
- Existing verifier suite and owned/lowering focused suites pass.

Machine-readable evidence is in `rust_owned_ssa_verifier_qualification.json`.
The orchestration examples support both schema-v2 owned verification and the full
Initial IR -> Rust lowering -> owned verification path.

Production SSA lowering authority remains Python. RP3 is unchanged. This milestone
does not claim `RUST_SSA_LOWERING_IMPLEMENTED`.
