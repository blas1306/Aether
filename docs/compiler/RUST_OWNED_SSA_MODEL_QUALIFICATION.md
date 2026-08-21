# RUST-3.C Rust owned SSA model qualification

Decision: `RUST_OWNED_SSA_MODEL_QUALIFIED`

The `aether-ir` crate now has a schema-independent `OwnedSsaModule` boundary.
`from_schema_v2` explicitly imports types, declarations, parameters, ordinary
instructions, identities, phi associations, and control structure into owned
Rust data. `to_schema_v2` emits the versioned DTO; the owned module itself has
no schema-version field and does not derive `Serialize` or `Deserialize`.

## Identity and ordering

`FunctionId`, `BlockId`, and `SsaValueId` are distinct newtypes. Their retained
strings are lossless relative to schema-v2 while preventing accidental identity
interchange in later CFG/dominance work. Function, block, instruction, operand,
phi-incoming, field, witness-slot, and type-component order remains in `Vec`;
validation lookup uses `BTreeSet`, so hash iteration cannot affect output.

Phi is first-class: each `PhiIncoming` contains a `BlockId` predecessor and its
associated owned `IRValue`. Incoming order is retained and no new ordering is
imposed. Normal and exceptional targets remain distinct for all three invoke
families. Throw, rethrow, and propagate retain their optional continuation and
exceptional arguments.

## Semantic coverage

The existing exhaustive owned `IRInstruction` and `IRType` hierarchies provide
the ordinary SSA vocabulary: scalar/composite/function/nominal types, constants,
calls and function references, ownership/lifecycle operations, aggregates,
class/interface witness and erased-box metadata, collections, vector/matrix
operations, exception payload operations, source locations, shapes, and
`transferred_storage`. SSA-only phi and exceptional control are represented by
the owned SSA layer. Schema-v2's eight collection access variants remain
distinct and retain the required `bounds_checked` boolean without inference.

The machine inventory covers all 77 Python SSA instruction dataclasses. No
schema-v1 or schema-v2 shape was changed.

## Validation and results

Serde DTO decoding rejects missing/unknown fields, invalid tags, malformed
types, invalid booleans, and unsupported versions. Owned import separately
rejects empty/duplicate block identities, absent entry blocks, dangling phi
predecessors, and dangling exceptional continuations with stable path-qualified
errors. Full semantic SSA verification remains a separate concern.

The deterministic checker `scripts/qualify_rust_owned_ssa.py` ran the frozen
RUST-3 corpus through:

`Python SSA -> schema-v2 -> Rust owned SSA -> schema-v2 -> Python SSA`

Result: **116/116 passed**, with exact DTO comparison (no alpha normalization)
and Python owned-SSA equality. Rust adversarial tests cover minimal structure,
multi-predecessor phi, all eight bounds-sensitive kinds with both boolean
values, unknown versions, dangling continuations, and ten repeated byte
serializations. Existing DTO tests additionally cover direct/indirect/interface
calls and invokes, ownership, metadata, types, locations, and malformed input.

No Initial IR-to-SSA lowering, phi placement, liveness, dominance, renaming, or
optimization algorithm was added. Python lowering remains production authority;
RP3 and all authority assignments are unchanged.
