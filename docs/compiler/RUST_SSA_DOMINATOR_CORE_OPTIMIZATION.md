# Rust SSA dominator core optimization — RUST-3.9b

Baseline revision: `173383a4cab02a4239e2716574716176e1e3d337`.

## Pre-implementation audit and dependency map

The Rust lowering pipeline is:

```text
normalized Initial IR schema-v1
  -> named successor CFG (all terminator edges, including exceptional edges)
  -> entry-rooted reachable set
  -> iterative full dominator sets
  -> immediate dominators
  -> dominator tree
  -> dominance frontiers
  -> liveness and definite-initialization data flow
  -> pruned Cytron phi placement
  -> iterative dominator-tree renaming
  -> deterministic schema-v2 block assembly
```

Before RUST-3.9b, `compute_dominators` allocated one `BTreeSet<String>` for
every reachable block. Every non-entry set was initially a copy of the entire
reachable set. It then visited reachable blocks in source order until a full
pass made no changes, intersecting every reachable predecessor set. This stores
up to V² dominance relationships and adds tree/string allocation and comparison
cost to the quadratic structural bound.

Immediate dominators were the strict dominator with the largest full-set
cardinality, with source block index as a deterministic tie breaker. Tree
children were appended while visiting functions in source block order.
Dominance frontiers used only predecessor lists and `idom`: at every merge they
walked each predecessor's `idom` chain to the merge's immediate dominator.
Liveness, definite initialization, phi placement, and renaming use no full
dominator-set query. Unreachable blocks have no dominator or frontier entry and
are omitted from produced SSA; unreachable predecessors are excluded when the
reachable predecessor graph is built.

The complete caller audit therefore found no production consumer that requires
full dominator sets. They are retained only in the test reference path for
differential qualification.

## Algorithm selection

| Candidate | Memory | Engineering and semantic tradeoff |
|---|---:|---|
| Iterative full sets (reference) | O(V²) | Simple and deterministic, but it is the measured pathology. |
| Cooper-Harvey-Kennedy `idom` iteration | O(V+E) | Small implementation, deterministic reverse-postorder convergence, supports irreducible CFGs, and directly produces the only relation production needs. |
| Lengauer-Tarjan | O(V+E) | Strong theoretical bound but substantially more machinery and qualification risk for the observed CFG sizes. |
| Per-node path/search alternatives | O(V+E) storage, potentially high work | No maintainability or performance advantage over CHK for this use. |

RUST-3.9b selects Cooper-Harvey-Kennedy. Reachability and reverse postorder use
iterative stacks, successor order is the frozen terminator order, convergence
visits reverse postorder deterministically, and `intersect` walks already-known
`idom` chains. Production stores one optional parent and adjacency vectors per
block, rather than a set per block. The reference set solver is compiled only
for Rust tests and is not selectable through a compiler option.

## Frozen semantics

The change is internal to entry-rooted dominance. Initial IR schema-v1, SSA
schema-v2, edge discovery, unreachable policy, frontier semantics, pruned phi
placement, naming, collision suffixes, renaming, metadata, ownership/lifecycle,
verification, Rust authority, mandatory synchronous Python shadow, canonical
comparison, and fail-closed behavior remain unchanged.

## Qualification and measurements

Machine-readable qualification results, deterministic randomized seeds,
adversarial-family coverage, performance measurements, and remaining
bottlenecks are recorded in
`rust_ssa_dominator_core_optimization.json`. The permanent checker is
`scripts/check_rust_ssa_dominator_core_optimization.py`.

The differential suite passed 16 named adversarial families and 400 generated
CFGs from five fixed seeds. Every small/medium graph compared reachability, the
full dominance relation, `idom`, ordered children, and every frontier against
the old solver. Focused SSA tests cover merge and loop-carried phis, exact
predecessor/value labels, liveness pruning, unreachable definitions, and repeat
determinism. The existing 21-case adversarial lowering suite, 116/116 historical
corpus, and 155 production-regression tests all retain exact Python/Rust parity.
A 10,000-block dual-lane lowering also matched and returned all 10,000 blocks.
The full Python suite passed 4,886 tests with 4 platform/optional skips, using
the repository's `LSAN_OPTIONS=detect_leaks=0` convention for runners under
`ptrace`. The locked Rust workspace suite also passed.

On the same Linux x86_64 release build, the Rust SSA-lowering median changed
from 0.237081 s to 0.015435 s at 1,000 blocks and from 7.002413 s to 0.098208 s
at 5,000 blocks. Thus the 5x input increase changed from 29.54x growth to 6.36x,
with a 71.3x speedup at 5,000 blocks. The isolated optimized analysis measured
0.069 ms at 1,000, 0.326 ms at 5,000, 0.626 ms at 10,000, and 1.581 ms at
25,000 blocks (seven-round medians after two warmups).

The old chain representation stores V(V+1)/2 dominance relationships: 500,500
at 1,000 blocks, 12,502,500 at 5,000, and 50,005,000 at 10,000. Production now
keeps linear graph vectors and one temporary parent per reachable block. Larger
reference runs were deliberately avoided because allocating the full sets is
the pathology under removal.

The mandatory Python shadow remains the leading deep-CFG bottleneck: a 10,000
block parity run took 52.06 s overall while Rust SSA lowering itself took
0.226 s. Optimizing Python dominance, weakening the shadow, and rewriting the
verifier remain outside this milestone.

## Rollback and closure

There is one production algorithm and no user-facing or hidden production
switch. The old solver exists only inside the Rust test module, so it is absent
from the production hot path but remains available as the qualification oracle.
The older stabilization tree-hash guard now excludes only the two authorized
implementation files (`lowering.rs` and `dominance.rs`); its
file-specific schema-v2 and lifecycle-policy hashes and the tree hash for every
other Rust IR source remain frozen to the baseline.
Official Windows x86_64 and macOS arm64/x86_64 execution remains owned by the
normal CI matrix; the implementation has no platform-specific path.

Decision: `RUST_SSA_DOMINATOR_CORE_OPTIMIZED`.
