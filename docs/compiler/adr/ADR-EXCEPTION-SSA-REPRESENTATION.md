# ADR: Exception SSA Edge and Value Representation

Status: Accepted

## Context

Aether Initial IR will represent every potentially throwing operation with
explicit normal and exceptional CFG successors. The ordinary result is available
only on the normal edge and the owned opaque exception event is available only on
the exceptional edge. SSA construction must represent those mutually exclusive
edge values while including exceptional predecessors in reachability, dominance,
frontiers, phi placement, verification, optimization, and printing.

This ADR is an implementation decision. It cannot change source syntax, matching,
unchecked semantics, cleanup, event ownership, panic behavior, diagnostics, or
FFI containment.

Authority:

- `docs/compiler/EXCEPTION_ARCHITECTURE_RESOLUTION.md`
- `docs/compiler/COMPLETE_EXCEPTION_MODEL_RFC.md`, especially §8
- `docs/compiler/EXCEPTION_IMPLEMENTATION_PLAN.md`, Milestones 3–6
- `docs/compiler/exceptions/EXCEPTION_FROZEN_SEMANTICS_CHECKLIST.md`

## Frozen constraints

- Normal and exceptional successors are real, distinguishable CFG edges.
- An invoke normal result exists only on its normal edge.
- An invoke event exists only on its exceptional edge.
- All CFG analyses use the complete graph.
- Lifecycle cleanup is explicit before SSA.
- Exactly one owner of a live event moves through every executable path.
- Handler joins select one incoming event owner; they do not copy it.
- Catch payload access is a borrow dominated by a successful match and bounded by
  the event lifetime.
- Critical-edge transformations preserve edge kind, provenance, cleanup order, and
  ownership.
- No hidden global or TLS “current exception” may represent SSA event flow.
- Panic remains separate and has no catch-handler edge.
- Python and Rust verification must enforce the same selected representation.

## Decision

Aether SSA uses **special edge-defined invoke values with explicit successor
arguments** (Option A, using the existing phi convention at ordinary joins).
This is semantically equivalent to block arguments without introducing a
second general SSA mechanism.

Each direct, indirect, or interface invoke is a terminator with two ordered
successors:

1. the normal edge, carrying exactly the non-void call result when one exists;
2. the exceptional edge, carrying exactly one opaque `exception_event`.

The invoke result is defined only on its normal edge. The invoke event is
defined only on its exceptional edge. An edge-defined value dominates the
corresponding successor entry and uses reached exclusively through that edge;
it does not dominate the invoke block, the other successor, or unrelated
blocks.

An exceptional successor contains one `catch_entry` as its first non-`phi`
instruction. Any ordinary predecessor-labelled phis required by the existing
SSA convention remain at the start of the block. `catch_entry` selects and
moves the single event supplied by each exceptional predecessor into the
handler's owned event value. It is the handler-entry parameter form for this
representation and does not copy the event. Handler blocks accept only
exceptional predecessors, and every exceptional edge supplies exactly one
event. Ordinary mutable values visible to the handler and values joining later
control flow continue to use predecessor-labelled `phi` nodes. Event phis,
when required at an ordinary join, move one live owner from each predecessor
and may not duplicate or merge additional owners.

`exception_pack` defines a new owned opaque event. `exception_match` observes
the exact dynamic nominal type, and `exception_payload` creates only a borrowed
language `Error` value bounded by the owning event's lifetime.
`exception_destroy`, `throw`, `rethrow`, and `propagate` are explicit terminal
ownership actions. `rethrow` consumes the active event introduced by the
current catch; it does not pack a replacement. A transfer to another handler
carries its event as the sole exceptional successor argument. A root transfer
has no successor arguments.

CFG APIs retain an edge kind (`normal` or `exceptional`) and ordered arguments.
Reachability, predecessor discovery, reverse postorder, dominance, dominance
frontiers, loop discovery, edge rewriting, and block removal operate on the
complete graph. Rewriting an edge preserves its kind and arguments.

The verifier treats both edge definitions as SSA definitions with
edge-qualified availability. It also performs path-sensitive event ownership
dataflow. Every executable path must have exactly one terminal disposition for
each live owner; incompatible joins, missing consumption, double consumption,
ordinary event use, use or borrow after consumption, invalid rethrow, and
handler/edge-shape mismatches fail closed. Calls to known `may_throw` functions
must be invokes, invokes of known non-throwing functions are invalid, and a
function containing exception SSA must retain `may_throw`.

Implementation clarification: SSA preserves the Initial IR interface-slot
`may_throw` fact unchanged. `interface_call` requires a nonthrowing slot and
`invoke_interface` requires a throwing slot; SSA analysis and optimization do
not recompute the effect from witnesses, method names, or CFG shape.

The schema-v1 SSA JSON envelope is distinguished by
`"representation": "aether_ssa"`. It serializes invoke kind, ordered normal and
exceptional targets and arguments, handler entry, ownership operations,
`may_throw`, and predecessor-labelled phi inputs directly. Python and Rust use
the same strict tagged instruction shapes and reject Initial IR lifecycle or
exceptional-control forms at the SSA boundary.

The Initial IR-to-SSA renamer creates these edge definitions and arguments
directly. The compatibility pattern builder rejects exception-bearing input
and directs it to the general builder.

This decision was accepted after direct, indirect, and interface invoke
lowering; nested handler execution; ownership-negative cases; CFG analysis;
serialization round trips; and post-optimization verification passed.

## Candidate options

Only candidates already identified by the approved architecture are in scope.

### Option A: Special edge-defined values

The invoke terminator defines a normal result and an exceptional event on their
respective outgoing edges. SSA applies explicit edge-dominance and
edge-availability rules; ordinary phis select values at multi-predecessor joins.

### Option B: Block arguments supplied by terminator edges

Successor blocks declare arguments and each terminator edge supplies the
edge-specific values. Handler joins receive one owned event argument from each
exceptional predecessor.

### Option C: Unique trampoline block per edge

Each invoke edge targets a unique block that materializes its edge-specific value
before ordinary SSA control continues. Multi-predecessor joins use ordinary phis
after the trampoline.

The RFC recommends block arguments or semantically equivalent edge-defined
values. The accepted representation selects Option A. Option B would require
changing the project's general SSA convention to block arguments. Option C
would add blocks solely to materialize values and make cleanup and
critical-edge provenance more complex. Neither provides a correctness
advantage over the selected edge-qualified definitions and explicit successor
arguments.

## Evaluation criteria

The deciding evidence must compare the candidates on:

1. Correct representation of mutually exclusive invoke results/events.
2. A simple, exact definition of edge availability and dominance.
3. Linear event ownership at handler joins, rethrow, cleanup, and root
   propagation.
4. Correct phi/block-argument placement for mutable values visible to catches.
5. Critical exceptional edge splitting without cleanup or provenance changes.
6. Behavior for multi-invoke handlers, loops, unreachable handlers, and cleanup
   ladders.
7. Compatibility with the general SSA builder and a fail-closed disposition for
   every alternate builder.
8. Operand traversal, printing, cloning/equality, and optimizer transformation
   complexity.
9. Python verifier clarity and negative-test coverage.
10. Rust schema/importer/verifier parity and wire-schema cost.
11. Post-pass verification and ownership-aware phi simplification.
12. Measured implementation complexity and maintainability; source behavior and
    correctness are non-negotiable.

## Consequences

- The selected representation becomes an internal compiler contract, not source
  syntax or a public ABI.
- Every SSA builder, printer, verifier, optimizer, fixture, and Rust mirror must
  implement it or reject exception-bearing input explicitly.
- Alternate backends may lower it differently while preserving the verified
  semantics.

## Validation requirements

- Golden SSA for direct/indirect/interface/constructor invokes.
- Diamonds, loops, nested handlers, multi-invoke handlers, cleanup ladders,
  critical edges, unreachable handlers, and root propagation.
- Positive and negative edge-availability/dominance cases.
- Event join tests proving exactly one incoming owner and exactly one eventual
  consumption.
- Catch-borrow lifetime and match-dominance tests.
- Builder parity or explicit fail-closed tests for unsupported builders.
- Printer and operand-registry completeness tests.
- Python/Rust valid-invalid fixture parity, shadow, canary, and schema round trips.
- Verification before and after every enabled SSA optimizer.

## Decision validation / owning milestone

**Validated:** by the exception-bearing SSA implementation and its Milestone 4
test suite before accepting this ADR.

**Owning milestone:** **Milestone 4 — SSA representation and lowering**.
