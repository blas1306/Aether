# Rust Initial IR to SSA lowering — RUST-3.1b

Decision: `RUST_SSA_LOWERING_BLOCKED`

The lifecycle-normalization blocker recorded by the original RUST-3.1 artifact
was closed by RUST-3.B1.  RUST-3.1b nevertheless cannot implement a complete
normative lowering because `lowering_policy_v1` leaves the schema-v2
`bounds_checked` value under-specified.

The policy requires every schema-v2 field, including `bounds_checked`, to be
copied exactly.  Initial IR schema-v1 has no `bounds_checked` field on
`array_get`, `array_set`, `list_get`, `list_set`, `vector_get`, `vector_set`,
`matrix_get`, or `matrix_set`.  Python `GeneralSSABuilder` constructs the
corresponding SSA classes without passing the field, thereby obtaining the SSA
model default `true`.  Copying is therefore impossible and reproducing Python's
implicit default would make the reference implementation, rather than the
frozen policy, normative.

Contract closure must state how each of the eight Initial IR instructions maps
to schema-v2 `bounds_checked` (for example, a normative constant `true`, or a
new Initial IR field and its preservation rule).  Until then, two conforming
Rust implementations can emit different schema-v2 documents and the concrete
determinism/parity gate is not well-defined.

No Rust lowering code or production authority was changed.  The historical
`RUST_SSA_LOWERING_BLOCKED` artifact remains unchanged.

