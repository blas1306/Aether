# Lifecycle Normalization Policy v1

Policy version: `lifecycle_normalization_policy_version = 1`

The normative contract is
[`lifecycle_normalization_policy_v1.json`](lifecycle_normalization_policy_v1.json).
If it differs from Python or this companion, qualification fails; Python is not
the normative reference.

## Decision and boundary

`LIFECYCLE_NORMALIZATION_POLICY_V1_QUALIFIED`

The interface is `normalize_lifecycle(verified_initial_ir_module, policy_v1) ->
normalized_initial_ir_module | deterministic_error`. Module context supplies
nominal structs. A complete function census supplies operands, remaining uses,
owned temporaries, and names. There is no global mutable input and the input is
not mutated.

The complete inventory is `IRInitDefault`, `IRCopyInit`, `IRMoveInit`,
`IRAssign`, `IRDestroy`, and `IRRelocate`. The JSON freezes exact ordered
sequences for trivial, owned, interface-containing, storage-source, and default
cases; recursive traits; naming; transfer; `transferred_storage`; and errors.

Default initialization synthesizes a typed default and stores it. Copy loads a
storage source and either stores directly, consumes an owned temporary, retains
a borrowed owner, or copies an interface owner. Assignment acquires the
replacement before loading and releasing the old value. Move loads/stores and
then resets a destructible/defaultable source. Relocate loads/stores once;
verified positive `count` does not repeat a typed storage value. Destroy
loads/releases only a type needing destruction.

Traversal is function, block (including unreachable), and instruction order;
each expansion is contiguous. Generated decimal names start after the greatest
numeric name and skip collisions. Generated instructions have no source
location; copied instructions and module/function metadata remain exact. The
verified return-transfer marker is consumed and removed.

Pseudo expansion cannot change CFG or exceptional targets. The production pass
also has a separately specified constructor-invoke ownership repair which may
append exceptional cleanup trampolines and prepend normal struct releases.

## Domain, idempotence, and scope

The operation is intentionally single-pass. Legal input is verified
pre-normalization IR without internal ownership helpers; normalized output is
not generally legal input because the pass also processes ordinary ownership
operations. A module already containing an internal retain/release/interface
copy helper is returned by identity as a production compatibility shortcut.
Helper-free normalized functions are not promised to be fixed points. The
instruction-effect registry is not consulted.

Run `python scripts/check_lifecycle_normalization_policy_v1.py`. This milestone
does not implement Rust normalization or lowering. Python remains SSA lowering
authority; RP3, Initial IR authority, SSA schema-v2, CFG/dominance/phi/renaming,
optimizer, and backend semantics are unchanged.
