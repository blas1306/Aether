# O2.2 proven bounds and shape-check elimination

O2 adds the explicit SSA pass `ProvenBoundsCheckEliminator` after the complete
O1 SSA pipeline and before a final `SSADeadCodeEliminator`. O0 and O1 are
unchanged. The canonical order is defined by `SSA_O2_PASSES` in
`aether.optimization`.

## Safety and representation

Array, Vector, and Matrix get/set instructions carry a `bounds_checked` bit.
Lowering creates checked instructions. O2 changes that bit only after the
existing `ProofCoverageAudit` classifies the exact check at the exact SSA block
and instruction position as `PROVEN_SAFE`; `UNKNOWN` and `PROVEN_UNSAFE` retain
the runtime helper. Operands are already-computed SSA values, and the access
instruction itself remains, so evaluation, ownership, and side-effect order do
not change.

Array indices require `0 <= index < length`. Vector indices require
`1 <= index < length + 1`. Matrix row and column obligations use the same
one-based rule and are proved independently. Because the runtime currently
combines both Matrix checks in one helper, it is removed only when both proofs
succeed; there is no partial elimination. The unchecked LLVM lowering only
computes the already-proved element offset and performs the original load or
store.

## Conservative boundaries

The pass consumes O2.1's point-sensitive range and shape results and therefore
inherits checked-overflow conservatism and mutation/call/exception-edge
invalidation. It invents no purity, alias, or mod/ref facts. List checks remain
checked in this milestone even if an isolated immutable case is auditable as
safe (zero baseline List transformations). Array/List slicing remains checked:
although the audit can prove some half-open slices, their runtime check is
inside an allocating helper and is not independently removable without a new
representation. No general runtime shape-check instruction is SSA-visible in
the audited corpus, so shape transformations are zero; fixed Vector and Matrix
dimensions are used for bounds proofs, but orientation and operation
compatibility checks are not removed.

## Statistics and verification

The pass reports deterministic internal counts for examined/removed checks,
bounds/shape removals, preserved UNKNOWN/PROVEN_UNSAFE checks, and Array, List,
Vector, Matrix, and slicing removals. The standard optimizer verifies SSA after
the pass and after cleanup, including exceptional CFG and lifecycle rules.
The proof-coverage baseline remains the O2.1.5 analysis baseline and is not
rewritten; transformation coverage is tested separately.

## O2.6 pass order

The O2 SSA suffix is proven BCE, conservative scalar LICM, then DCE. BCE runs
first so removed checks may expose safe scalar work; initial LICM still refuses
all collection loads and does not alter BCE's proof contract.
