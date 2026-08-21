# SSA source-location lowering policy v1

Status: `SSA_SOURCE_LOCATION_LOWERING_POLICY_V1_QUALIFIED`

The normative artifact is
[`ssa_source_location_lowering_policy_v1.json`](ssa_source_location_lowering_policy_v1.json).
It inventories every concrete Initial IR instruction and records all six audit
questions through four exhaustive groups.

## Normative rule

A direct Initial IR instruction copies `source_location` exactly when the
corresponding SSA model and schema-v2 can represent it. `None` remains `None`.
Lowering never fabricates a location and constructor defaults are not policy.

The ten preserving mappings are binary operation, direct call/invoke,
array/list copy, array/list get, array/list slice, and exception packing. All
other direct mappings lack the field on both models. Loads and stores are
elided during SSA renaming.

## Synthetic instructions

Phi instructions have no location because a merge has no unique source
instruction. Lifecycle-normalization output has no location under the existing
v1 lifecycle policy. CFG-generated instructions do not inherit neighboring
locations. Constructor cleanup/trampoline `catch_entry`, `release`, and
`propagate` instructions are likewise unlocated. These are explicit absence
rules, not implicit constructor behavior.

## Six divergences

Initial lowering assigned locations to `array_copy`, `array_get`,
`array_slice`, `list_copy`, `list_get`, and `list_slice`; lifecycle
normalization copied those ordinary instructions unchanged. Rust's DTO-based
renaming retained the fields. Python's `SSARenamer` omitted the final
constructor argument, producing `None`. The normative preservation rule makes
Python incomplete, so only Python lowering changes.

Run `python scripts/check_ssa_source_location_lowering_policy_v1.py` to verify
the exhaustive inventory, model/schema support, implementation anchors, and
canonical JSON deterministically.
