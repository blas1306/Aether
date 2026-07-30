# ADR: Private Exception Runtime Event ABI

Status: Proposed

## Context

The compiler and native runtime need a narrow private contract for creating,
identifying, borrowing, transferring, destroying, propagating, reporting, and
terminating opaque exception events. The contract must support the selected
backend strategy while keeping payload layout, helper names, propagation state,
and machine representation outside source semantics and outside any public FFI
commitment.

This ADR does not define a public C ABI and does not select new language
semantics.

Authority:

- `docs/compiler/EXCEPTION_ARCHITECTURE_RESOLUTION.md`
- `docs/compiler/COMPLETE_EXCEPTION_MODEL_RFC.md`, especially §§12–13
- `docs/compiler/EXCEPTION_IMPLEMENTATION_PLAN.md`, Milestone 8
- `docs/compiler/AETHER_NATIVE_ABI.md`
- `docs/compiler/exceptions/EXCEPTION_FROZEN_SEMANTICS_CHECKLIST.md`

## Frozen constraints

- An event owns one non-null struct or class payload implementing `Error`.
- Struct payloads preserve value/snapshot semantics; class payloads preserve
  reference identity.
- The event is opaque and internal.
- Exactly one event owner moves through propagation.
- Matching borrows; handling/root termination destroy exactly once; rethrow
  transfers without repacking or changing provenance.
- Exact catch matching uses collision-safe canonical nominal identity across
  modules.
- `Error` catch-all behavior is compiler-directed; the runtime does not invent
  source matching policy.
- The runtime never scans the stack for Aether owners.
- Compiler-generated cleanup invokes typed lifecycle operations.
- Panic entry/reporting is separate and never packages a catchable event.
- Allocation/reporting/internal failures follow the fail-fast policy and cannot
  recursively throw.
- No Aether exception crosses raw C.
- The contract is versioned and private; a stable public exception ABI is out of
  scope.

## Decision: Pending

The approved ADR must specify the private operation set, ownership pre/postconditions,
event/payload storage choice, canonical descriptor contract, version negotiation or
schema identity, root termination sequence, failure policy, and relationship to the
selected backend lowering.

## Candidate options

The architecture leaves several internal representation axes open. Only options
explicitly identified by the approved documents are listed.

### Payload storage

- Store eligible small struct payloads inline in the opaque event.
- Box payloads in event-owned storage.
- Move payloads into an existing interface box where that preserves value/reference
  semantics and ownership.
- Reuse a carrier reference for class errors.

These choices may be combined by payload category; no choice is selected here.

### Canonical descriptor identity

- Pointer equality when linking/module loading guarantees one canonical descriptor
  instance.
- Another collision-safe canonical nominal identity when unique pointer identity
  is not guaranteed.

Hash-only equality is not a candidate.

### Propagation-state organization

- Event-private backend-specific propagation state for native EH.
- Explicit event handle transfer through status-value or out-parameter lowering.
- Compiler-owned explicit continuation state for a continuation backend.

The backend ADR selects the applicable transport family. The runtime ADR must keep
the logical pack/match/borrow/transfer/destroy/root contract identical.

## Evaluation criteria

1. Exact ownership preconditions/postconditions for pack, borrow, transfer,
   destroy, rethrow, propagation, and root handling.
2. Correct struct snapshot and class identity behavior.
3. Canonical cross-module descriptor identity without collision ambiguity.
4. Compatibility with the selected backend and plausible alternate targets.
5. No runtime stack scanning or duplicated lifecycle policy.
6. Event allocation cost, small-payload behavior, alignment, and code size.
7. ARC/lifecycle integration for nested managed payloads and interface boxes.
8. Safe deterministic handling of allocation, descriptor, message dispatch, and
   diagnostic formatting failures.
9. Preservation of original throw provenance without exposing it as public layout.
10. Separate panic entry points and termination paths.
11. Internal versioning, symbol namespace, linker behavior, and module loading.
12. Debug ownership counters, event IDs, and fault-injection hooks without changing
    production semantics.
13. FFI containment and future wrapper viability without making the private ABI
    public.
14. Sanitizer, stress, reentrancy, and supported threading/task behavior.

## Consequences

Pending the decision:

- M8 runtime implementation is not approved.
- M7 backend work may prototype only against an explicitly provisional contract.
- M9 cannot finalize adapter ownership.

After approval:

- Compiler lowering and runtime implementation share one versioned private
  contract and ABI test suite.
- Event layout/helper names remain free to evolve through the private versioning
  policy and are not language guarantees.
- All event consumers must obey linear ownership; convenience helpers cannot
  absorb compiler cleanup policy.
- A later public FFI ABI requires separate design and approval.

## Validation requirements

- Unit tests for pack, descriptor lookup, exact/root match support, borrow,
  transfer, destroy, rethrow, propagation, and root termination.
- Struct and class payload tests, including nested managed ownership.
- Cross-module/link-unit descriptor identity tests and collision-safety tests.
- Leak, double-destroy, use-after-destroy, and catch-borrow lifetime tests.
- Fault injection at event allocation, descriptor access, `message()`, diagnostic
  formatting, and root reporting.
- Deep propagation, nested/repeated catch-rethrow, high-volume stress, and
  reentrant paths.
- Supported sanitizer and platform termination-output tests.
- Tests proving panic is never an event and that panic during exception processing
  follows fail-fast behavior.
- Backend-facing ABI/version mismatch tests that fail closed.
- FFI containment tests proving raw C frames never observe event propagation.

## Decision deadline / owning milestone

**Deadline:** before the private exception runtime implementation is merged and
before Milestone 7 backend lowering is finalized against it.

**Owning milestone:** **Milestone 8 — Runtime**.
