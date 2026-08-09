# O2 loop, range, and shape analysis foundation

O2.2 consumes these immutable results in `ProvenBoundsCheckEliminator`; see
`O2_BOUNDS_CHECK_ELIMINATION.md`. It does not weaken or extend the analysis.

Status: implemented as read-only SSA analyses. No pass pipeline or observable
program behaviour is changed, and no check or instruction is removed.

## Repository audit and reuse

The implementation reuses `SSACFGBuilder`, its complete normal/exceptional
successor model, `predecessors`, `reachable_blocks`, `reverse_postorder`, and
the existing `DominatorAnalysis`. Instruction effects remain authoritative for
unknown calls and mutation. Phi nodes are the existing `SSAPhi` representation.

The readiness audit called reusable reachability "partial"; the repository at
implementation time already has public SSA `reachable_blocks` and
`reverse_postorder` helpers. That repository state is authoritative. The other
reported gaps—loops, integer ranges, and persistent collection shape facts—did
not previously have reusable implementations.

## Analyses and safety model

`LoopAnalysis` merges all dominance backedges with a common header into one
natural loop, builds the loop forest, records exits and canonical preheaders,
and recognizes constant-step integer phis. Cyclic SCCs without a dominating
natural header are reported separately as irreducible; unreachable cycles are
ignored.

`RangeAnalysis` is a forward must-analysis. It handles integer constants,
constant-offset add/subtract, phis, canonical IV lower/upper bounds, and simple
comparison facts refined on normal branch edges. Joins retain only common
symbolic predicates and conservatively join numeric intervals. Checked i32
arithmetic loses a bound whenever shifting it would leave the Aether integer
domain; multiplication, division, modulo, and unsupported cases are unknown.
Exceptional invoke edges never receive branch-only refinement.

`ShapeAnalysis` records length provenance for Array/List and static or stable
Vector/Matrix shapes. Structural List operations invalidate their List fact.
The original transfer invalidates every List length at a writing call. O2.4 now
provides an opt-in alias/mod-ref preservation API for unrelated mutations and
summarized nonmodifying calls; it is not wired into production shape transfer
or BCE. Array length and value-shape
facts remain stable under the operations currently represented by SSA. Slices
receive a distinct result provenance, without asserting an unproved numeric
length.

## Complexity and convergence

Natural-loop collection performs dominance once, a reverse predecessor walk
per distinct header, and one Tarjan SCC traversal: `O(D + H(V+E) + V+E)`, where
`D` is the existing dominance cost and `H` the number of natural headers.
Range and shape analyses use reverse-postorder fixed points capped linearly in
the CFG size. Their lattices only lose precision at joins/invalidation; loop
IVs are widened immediately to one-sided bounds, preventing accidental
iteration-count-dependent finite ranges. All capped or unsupported cases fail
closed to unknown facts.

See `O2_ALIAS_MODREF_ANALYSIS.md` for the O2.4 semantic model and summaries.
