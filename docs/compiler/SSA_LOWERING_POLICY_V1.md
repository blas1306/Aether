# Initial IR → SSA lowering policy v1

Status: `SSA_LOWERING_POLICY_V1_QUALIFIED`  
Policy version: `lowering_policy_version = 1`

The normative machine-readable artifact is
[`ssa_lowering_policy_v1.json`](ssa_lowering_policy_v1.json). This document is
its human guide. The policy versions SSA construction, not Initial IR schema,
SSA schema, verifier protocol, or product releases.

## Semantic boundary and purity

The interface is `lower(verified_initial_ir, lowering_policy_v1) ->
verified_ssa | deterministic_error`. Production callers provide Initial IR
already verified by the Rust-authoritative RP3 path. `GeneralSSABuilder` expands
lifecycle under `lifecycle_normalization_policy_version = 1`, builds
CFG/dominators/frontiers, places phis, renames, then always
runs `SSAVerifier`. It does not mutate the input and has no mutable global
policy. The JSON classifies every influence as input, policy, derived local
state, or global constant; there are no accepted hidden dependencies.

## CFG, dominance, and unreachable code

Block and edge order comes from Initial IR. Jump has one normal edge, branch
has true then false normal edges, and return has none. All three invoke forms
have normal then exceptional edges. Throw, rethrow, and propagate have one
exceptional edge only when their optional target is present. An empty block has
no successor.

Dominance is rooted at the first block. Reachable dominators are computed by
fixed-point predecessor intersection. Unreachable blocks dominate only
themselves, have no immediate dominator or frontier, and are omitted from SSA
output. Immediate-dominator ties use later input block index; dominator-tree
children are nevertheless traversed in input block order. Frontiers include
reachable joins and walk each reachable predecessor to the join's immediate
dominator.

## Phi placement and renaming

Only normalized `IRStore` defines promotable storage; only `IRLoad` reads it.
Placement uses iterated dominance frontiers and retains a candidate when the
slot is live-in or definitely initialized on entry. Liveness is the usual
backward fixed point over loads-before-store and store kills. Definite
initialization is a forward must analysis using predecessor intersection.

Phi type is the unique declared load/store slot type. Phis are sorted by slot
name. Incoming values remain predecessor-labelled and are appended as blocks
are visited by entry-rooted dominator-tree DFS, with children in input block
order. Each slot has a stack: phis and stores push, loads read the top, and
block-local pushes are popped in reverse on exit.

Parameters populate the ordinary SSA value namespace, not slot stacks.
Ordinary results keep their Initial IR name and duplicate definitions fail.
A phi prefers the first matching load result in its block, otherwise
`<block>.<slot>.phi`; collision suffixes are `.1`, `.2`, ... using the least
free positive number. SSA blocks retain reachable Initial IR order.

## Lifecycle, effects, exceptions, and metadata

The six pseudo-instructions `IRInitDefault`, `IRCopyInit`, `IRMoveInit`,
`IRAssign`, `IRDestroy`, and `IRRelocate` are expanded before CFG construction
under the standalone normative
[`lifecycle_normalization_policy_v1.json`](lifecycle_normalization_policy_v1.json).
That artifact, rather than Python behavior, freezes exact type-directed order,
ownership, naming, metadata, domain, CFG/exception repair, and errors. Direct
renaming never accepts these six kinds.

The canonical semantic effect owner is `aether.instruction_effects` together
with instruction-class `effects` attributes in `aether.ir.model`. Lowering's
storage interpretation is deliberately narrower and lives in
`PhiPlacement`/`SSARenamer`.

Cleanup and exception regions are ordinary CFG blocks. Invoke values use their
normal and exceptional continuations; throw/rethrow/propagate follow the table
above. Exception merges use the same predecessor-labelled phi rule, including
unreachable-region exclusion.

All source fields representable by the corresponding SSA instruction and
schema-v2 are copied exactly. This includes retained source locations,
aggregate shape, nominal structs, erased/class/interface metadata, function
references and indirect callees, ownership calls, `transferred_storage`, and
exception metadata. The serialization reference is SSA schema-v2.

Initial IR schema-v1 has no `bounds_checked` field. Each Initial IR Array,
List, Vector, and Matrix get/set instruction therefore synthesizes
`bounds_checked=true` in the corresponding SSA instruction. This rule covers
all eight get/set kinds and is synthesis, not preservation; an SSA constructor
default is not policy authority. `bounds_checked=false` is an SSA-level state
that may be supplied by schema-v2 or hand-built SSA, or produced later by a
qualified SSA optimization.

## Determinism and checking

Semantic equivalence does not waive concrete determinism. Function, parameter,
instruction, struct, and reachable block order are input order; phi and tree
orders and generated names follow the rules above. Sets are internal fixed-point
containers only: no output ordering is derived from their iteration order.

Run `python scripts/check_ssa_lowering_policy_v1.py`. The checker validates the
version, lifecycle inventory, schema reference, CFG inventory, pipeline order,
and naming anchors. Tests add behavioral probes for CFG/exception edges,
unreachable dominance, phi pruning/order, collision naming, repeated lowering,
lifecycle normalization, metadata/schema-v2 round trips, and unknown policy
rejection. This milestone adds no Rust lowering and changes no SSA semantics.
