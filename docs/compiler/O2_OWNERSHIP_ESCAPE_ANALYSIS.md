# O2.8 Ownership and escape analysis

O2.8 is analysis infrastructure only. It does not remove ARC operations,
promote allocations, alter SSA/LLVM, or change optimization profiles.

## Current model

Scalars have no ownership. Structs, internal aggregates, Vector, and Matrix
retain value semantics; recursively discovering owned fields is deliberately
deferred. Classes, strings, Array, List, nullable reference-like values, and
interfaces are reference-like. Parameters use the current borrowed callee
view. Fresh class/Array/List allocations, allocating copies/slices, interface
construction, and reference-like call results are owned. Borrowed collection
gets and `exception_payload` are borrows, never independent owners.

`exception_pack` creates a linearly owned event. Throw, rethrow, and propagation
consume/transfer it; `exception_destroy` consumes it. Constructor,
`MethodResult`, class identity, and struct-copy behavior remain defined by the
existing lifecycle lowering; this analysis observes them without changing
IRV-150 behavior.

Field and collection stores escape the stored reference. Interface construction
escapes a class carrier into the interface owner; a struct-backed result is a
fresh box identity. Unknown direct/native, indirect, and witness calls may
retain or store arguments. Known non-writing builtins borrow. No public
ownership annotations or closed-world assumptions are added.

## Domains and dataflow

Ownership is `OWNED`, `BORROWED`, `CONSUMED`, or `UNKNOWN`. Escape is a separate
bit set: return, field, collection, call, interface, global/module, exception,
may-escape, and unknown; zero is no-escape. Provenance reuses O2.4 roots and is
not an ownership count.

The per-function fixed point records states entering/leaving every block.
Predecessor states agree or join to unknown. The complete CFG includes invoke
normal/exceptional edges, cleanup, catch, rethrow, propagation, and uncaught
exits. Escape facts record normal, exceptional, or both paths. Direct summaries
monotonically union retained, consumed, stored, returned, and escaping
parameters plus fresh returns and exceptional escape. This converges for direct
and mutual recursion. Indirect/interface calls remain may-escape.

Queries are `ownership_state`, `provenance`, `escape_modes`, `is_fresh`,
`may_escape`, and `candidate_arc_pairs`. Debug output and unknown reasons are
deterministic. Verification fails closed on inconsistent ownership or omitted
exception paths.

## ARC candidates and post-dominance

Post-dominators use all normal and exceptional successors plus a synthetic
common exit. Diagnostic pairing requires the same exact SSA identity and a
post-dominating release. Escape, exceptional exits, or uncertain joins block a
local proof. Pair classes are locally provable, needs escape information, needs
path-sensitive ownership, blocked by exception/alias, and not redundant. No
pair is transformed.

## Complexity and limitations

For `B` blocks, `V` values, and `I` instructions, ownership state uses `O(BV)`
space and the conservative fixed point is bounded by `O(BV(B+I))`. Escape
propagation is linear in uses times small provenance sets. Summary convergence
is bounded by parameter/flag bits. Iterative post-dominance is `O(B(B+E))`;
pair scanning is linear apart from the small pending-retain list.

The first precision is block/edge-sensitive, not fully path-sensitive. It does
not recursively walk heap graphs, infer indirect targets/contracts, or fully
expand nested aggregate and constructor/MethodResult fields. Those cases fail
closed. O2.7 remains the field-cell authority: storing into `obj.a` escapes the
value specifically while mutation of `obj.b` remains distinct.

Focused local/return, field/collection, unknown-call, exceptional ARC,
post-dominance, and mutual-recursion probes pass together with O2.7 (13 tests).
Historical O2.6.2 traffic remains 2 retains, 16 releases, and 0 proven pairs;
that audit is not rewritten. A production corpus counter is not yet wired.

Decision: **IMPROVE_OWNERSHIP_ANALYSIS_FIRST**. An eventual smallest safe pass
is same-identity local pair removal with no escape/consume and complete
dominance, post-dominance, and exceptional-path proof. Nested aggregates,
constructors/MethodResult, and corpus metrics need improvement first. Stack
promotion and box elimination gain prerequisite queries but are not ready;
memory-read LICM and inlining remain unchanged.
