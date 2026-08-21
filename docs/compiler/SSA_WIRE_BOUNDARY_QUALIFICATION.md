# RUST-3.A1 explicit SSA wire schema-v2 qualification

## Decision

`SSA_WIRE_SCHEMA_V2_QUALIFIED`

New Python SSA serialization emits schema-v2. The invariant
`Python SSA -> schema-v2 DTO -> Python SSA` passes for all 116 programs that
reach verified Python SSA in the existing RUST-3.A corpus (116/116). The 28
frontend or Initial IR failures among 144 discovered inputs remain separately
recorded and are not part of the denominator.

## Exact v1 to v2 delta

Schema-v2 adds one required boolean field, `bounds_checked`, to exactly these
eight existing instruction shapes: `array_get`, `array_set`, `list_get`,
`list_set`, `matrix_get`, `matrix_set`, `vector_get`, and `vector_set`. The
other 69 instruction shapes are unchanged. The complete 77-dataclass field
audit found no other existing SSA semantic field that needs a v2 wire addition,
and no convenience or prospective fields were added.

## Compatibility policy

Schema-v1 remains frozen. Decoding dispatches on the envelope version before
instruction decoding. Unaffected v1 instructions retain their compatibility
path. A v1 payload containing one of the eight affected kinds is rejected
because it did not serialize `bounds_checked`; the decoder does not manufacture
a value. A v2 affected instruction must contain a JSON boolean
`bounds_checked`. Missing, malformed, unknown, or cross-version fields are
rejected, and unsupported versions fail deterministically.

Rust provides explicit v1/v2 wire-envelope dispatch and strict schema-v2 DTOs
for all eight changed shapes. This is DTO readiness only: no owned Rust SSA
model or Rust SSA lowering was implemented.

The deterministic evidence is
[`ssa_wire_boundary_qualification.json`](ssa_wire_boundary_qualification.json).
It inventories all fields of all 77 SSA instruction dataclasses and records the
exact corpus result. Regenerate or verify it with:

```bash
python scripts/audit_ssa_wire_boundary.py
python scripts/audit_ssa_wire_boundary.py --check
```

Initial IR protocol/schema-v1, Initial IR Rust authority at RP3, SSA
construction, optimizers, verifiers, LLVM/backend, lifecycle, and ownership
semantics are unchanged.
