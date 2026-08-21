# RUST-3.4a aggregate shadow differential qualification

Decision: **RUST_AGGREGATE_SSA_DIFFERENTIAL_QUALIFIED**.

The first divergence was the lifecycle-normalized Initial IR boundary. The
verified Initial IR snapshot was identical in both lanes. Before the fix,
Python emitted 87 normalized instructions in `main / entry`, while Rust emitted
86. SSA inherited that difference as 56 versus 55 instructions; the
canonicalizer was not responsible.

The missing instruction was `call __aether_release(%40: Item)` immediately
after `list_set`. `%40` is the owning `Item` temporary produced by
`struct_set`; `list_set` copies it into collection storage, and its last-use
ownership must then be discharged. It has no source location, transferred
storage, or aggregate metadata. `Item` needs destruction recursively because
`Item.label.text` is a string.

The Rust lifecycle dispatcher implemented this transition for `list_push`, but
allowed `array_set`, `list_set`, and `list_insert` to fall through unchanged.
The fix applies the same ownership primitive to the full collection-mutation
family and does not special-case `aggregates.ae`.

The minimized source reproducer is
`tests/aether/rust_migration/fixtures/aggregate_list_set_temporary.aether`; its
exact verified Initial IR snapshot is retained beside it as
`aggregate_list_set_temporary.initial_ir.json`. The regression covers owning
aggregate temporaries consumed by array set, list set, and list insert.

After the fix, lifecycle parity for `aggregates.ae` is 87/87 and canonical SSA
parity is 56/56. The complete soak is 161 programs, 132 accepted, 29 rejected
before SSA, 132 shadow comparisons, zero semantic mismatches, and zero
infrastructure failures. The historical differential remains 116/116. All
`aether-ir` and `aether-verifier` tests pass.

The persistent transport, fail-closed behavior, canonical comparison, schemas,
qualified policies, and SSA algorithms are unchanged. Python remains the
authority under `PYTHON_SSA_ONLY`; Rust SSA does not reach optimization or a
backend. RP3 is unchanged. The prior operational-blocked evidence remains a
separate blocked artifact, and no commit was created.
