# Rust SSA deep-CFG stack qualification — RUST-SSA-ROBUST-1

Decision: `RUST_SSA_DEEP_CFG_QUALIFIED`

## Root cause and isolation

The overflow was in `FunctionLowerer::rename_block`, reached through
`lower_verified_ir_to_ssa_v1 -> lower_normalized_ir_to_ssa_v1 -> lower_function
-> FunctionLowerer::rename_block -> dominator child -> rename_block`. A linear
5000-block CFG has a 5000-node dominator tree, so the recursive call depth was
proportional to CFG depth. The last successful lowering phase was phi placement;
the process aborted during SSA renaming, before `OwnedSsaModule` construction,
Owned SSA verification, or schema-v2 serialization.

Reachability, dominator fixed point, immediate-dominator/tree construction,
dominance frontiers, liveness, definite initialization, and phi placement are
already iterative. Owned SSA construction, verification, and serialization use
collection iteration for CFG structure. Recursive aggregate/type processing is
proportional to type nesting, not CFG depth, and was not exercised recursively
by this input. No second CFG-depth recursive traversal was found on this path.

The historical environment passed 1000 blocks and overflowed at 5000. The
first observed failing size is therefore 5000 (the unstable threshold is bounded
above 1000 and at or below 5000); it is recorded for diagnosis, not used as a
portable threshold requirement.

## Fix

Production renaming now uses a `Vec` of explicit `Enter` and `Exit` frames.
Children are pushed in reverse so visitation remains in the original order.
The exit frame removes value bindings and pops slot stacks in the same reverse
order as recursive return. This preserves block order, successor order, phi
incoming order, naming/collision behavior, and all instruction fields.

Time complexity is unchanged. Auxiliary traversal storage changes from `O(D)`
call-stack frames to `O(D)` heap frames, where `D` is dominator-tree depth.
Existing dominator sets remain `O(V^2)` space and dominate large debug-build
runtime; consequently 10000 blocks was not added to the normal suite.

## Results

- Focused lowering tests: 3/3 pass.
- Permanent ordinary-stack lowering plus `verify_owned_ssa`: 5000/5000 blocks,
  pass in 38.21 s in the debug test environment.
- Deep differential sizes 100, 993, 1000, and 5000: pass. The 5000 case has
  lifecycle parity, Python/Rust canonical SSA parity, both verifiers passing,
  schema-v2 import, exact reserialization, three-run Rust determinism, and input
  immutability. First Rust lower-and-verify run: 37.40 s.
- Non-linear adversarial families include nested diamonds and deep loop bodies;
  the fresh positive inventory passed 21/21.
- Shallow/moderate exact behavior is covered by the existing deterministic phi,
  lifecycle, exceptional, unreachable, loop, collision, codec, and historical
  corpus gates. No output difference was observed.
- Historical differential: lifecycle 116/116, canonical SSA 116/116, Rust
  verification/import 116/116, exact reserialization 116/116, determinism
  116/116.
- Fresh adversarial positive suite: 21/21, plus the separate permanent
  5000-block differential gate. Historical blocked RUST-3.2 artifacts were not
  modified.

No custom stack size, `RUST_MIN_STACK`, larger-stack thread, retry, reduced CFG,
or linear special case is used. Python, lowering/lifecycle policies, schemas,
canonical comparison, production authority (Python), and RP3 are unchanged.
No commit was created.

