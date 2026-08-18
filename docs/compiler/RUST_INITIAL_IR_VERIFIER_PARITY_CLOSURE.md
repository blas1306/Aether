# RUST-1.1 — Initial IR verifier parity closure

## Decision

`RUST_VERIFIER_SEMANTIC_PARITY_COMPLETE`

Python remains the production authority and the migration phase remains RP2.
This milestone closes semantic evidence only; it does not authorize RP3.

## Frozen RUST-1 gaps

RUST-1 reported the following exact 26 IDs. Every rule was already enforced by
a shared Rust verifier phase, but RUST-1's literal-ID scan could not prove the
mapping. The primary blocker for every entry was `RULE_MAPPING_ERROR`; no wire
field or semantic implementation was missing.

| IDs | Semantics | Python location | Rust phase / focused evidence |
| --- | --- | --- | --- |
| IRV-012–IRV-015 | enum, nominal struct, recursive composite and admitted leaf types | `_is_valid_type` | `TypeVerifier::require_valid_type`; `type_verifier.rs` |
| IRV-023 | exhaustive supported-instruction dispatch | `_transfer_instruction` | exhaustive `IRInstruction` match; `type_verifier.rs` |
| IRV-031 | canonical storage-name/type resolution | `_require_slot_exists` | SSA/lifecycle resolution; `lifecycle_verifier.rs` |
| IRV-035–IRV-036 | predecessor intersection and lifecycle merge state | `_State.intersect`, `_verify_reachable_values` | dominance/lifecycle joins; focused data-flow tests |
| IRV-054 | builtin operands defined/type-identical before builtin checks | `_verify_call` | SSA then builtin pass; `builtin_verifier.rs` |
| IRV-131–IRV-135 | handler entry shape, event type, identity and catch metadata/order | exception structure phase | exception type/CFG phases; `exception_verifier.rs` |
| IRV-137–IRV-148 | exception types/edges, reachability, effects, provenance and linearity | exception structure/ownership phases | exception type/CFG/ownership phases; `exception_verifier.rs` |

The deterministic JSON contains one row per ID with semantic description,
implementation locations, test coverage, wire dependency, blocker,
cardinality, and final state.

## Gates

- Production registry: 150; Python evidence: 150; Rust direct evidence: 150.
- Unresolved rules: 0; semantic divergences: 0.
- Canary: 65 both-accept, 72 both-semantic-reject and three acceptable
  diagnostic-only divergences.
- All 84 instructions and 19 types have non-lossy verifier representation;
  unsupported verification-relevant counts are zero.
- No runtime or wire behavior changed; no pathological regression was added.

Regenerate or check the artifact with `python
scripts/check_rust_verifier_parity.py` and its `--check` mode.

## Remaining RP3 operational blockers

`REMAINING_RP3_OPERATIONAL_BLOCKERS`

- packaged verifier/platform availability qualification;
- an RP3 production-authority CI gate.

These belong to RUST-1.2. Rust is not production authority until a separate
promotion milestone changes the central authority configuration.
