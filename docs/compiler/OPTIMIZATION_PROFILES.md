# Optimization profiles

Aether has one compilation-wide optimization setting. The default for direct
execution, `run`, `build`, every `--emit-*` inspection command, and `bench` is
**O0**. `--opt` remains available as a deprecated compatibility alias for
`-O1`; it is not a second optimization switch.

| Profile | Aether middle-end | clang backend |
| --- | --- | --- |
| O0 | No optional IR or SSA passes | `-O0` |
| O1 | The proven conservative IR and SSA pass sets below | `-O1` |
| O2 | O1 plus proven bounds-check elimination and cleanup | `-O2` |

O2's only additional Aether optimization family is the proof-gated bounds-check
eliminator described in `O2_BOUNDS_CHECK_ELIMINATION.md`. It does not imply a
broad aggressive middle-end or general shape-check elimination.
Exact generated machine code is not a language guarantee.

Correctness-required work is independent of these optional pass lists: parsing,
type checking, entry-point normalization, lifecycle expansion where required,
SSA construction, capability validation, and IR/SSA verification remain active.

The canonical registry is `aether.optimization.PROFILES`. O1 executes the
following Aether passes in this exact order, iterating to a fixed point:

1. Initial IR: `ConstantFolder`, `LocalConstantPropagator`, `ConstantFolder`,
   `AlgebraicSimplifier`, `DeadCodeEliminator`, `DeadStoreEliminator`,
   `DeadCodeEliminator`.
2. SSA: `SSAConstantFolder`, `SSAGlobalConstantPropagator`,
   `SSAAlgebraicSimplifier`, `SCCPPass`, `TrivialPhiEliminator`,
   `DeadPhiEliminator`, `SSADeadCodeEliminator`.

O2 executes that same IR pipeline and appends
`ProvenBoundsCheckEliminator`, `SSADeadCodeEliminator` to the O1 SSA order.

`--emit-ir` prints verified Initial IR after the selected IR passes;
`--emit-ssa` prints verified SSA after both selected middle-end stages; and
`--emit-llvm` emits LLVM from that same selected pipeline. `--show-passes`
traces the Initial IR pass registry for the selected profile.
