# ADR: Exception SSA Edge and Value Representation

Status: Proposed

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

## Decision: Pending

The decision must identify the canonical exceptional edge/value form, its
definition and dominance rules, its join representation, and the required
Python/Rust verifier invariants before Milestone 5 implementation begins.

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
values, but it deliberately leaves the concrete selection pending. This template
does not prefer a candidate.

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

Pending the decision:

- Milestone 3 may define implementation-neutral exceptional Initial IR, but it
  must not commit SSA consumers to an undocumented edge encoding.
- Milestone 5 SSA implementation and exception-bearing SSA optimizer enablement
  are blocked.
- Python/Rust SSA schemas and verifier rules cannot be finalized.

After approval:

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

## Decision deadline / owning milestone

**Deadline:** before exception-bearing SSA implementation begins.

**Owning milestone:** **Milestone 5 — SSA**.
