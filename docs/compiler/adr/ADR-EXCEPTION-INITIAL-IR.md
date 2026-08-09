# ADR: Initial IR Exception Representation

Status: Accepted

## Context

Milestone 3 requires Initial IR to represent the frozen exception semantics
without choosing an SSA encoding, LLVM lowering, native transport, or runtime
layout. Before this decision, exception control flow existed only in the typed
frontend and reference interpreter.

Authority:

- `docs/compiler/EXCEPTION_ARCHITECTURE_RESOLUTION.md`
- `docs/compiler/EXCEPTION_IMPLEMENTATION_PLAN.md`, Milestone 3
- `docs/compiler/exceptions/EXCEPTION_FROZEN_SEMANTICS_CHECKLIST.md`

## Decision

### Event representation and ownership

Initial IR uses the opaque, non-source `exception_event` type. `exception_pack`
moves or copies a validated non-null `Error` payload into a new owned event while
retaining its canonical dynamic nominal descriptor and source provenance. The IR
does not define the event's machine layout.

Event ownership is linear. `exception_borrow` exposes the payload only as a
borrow. `exception_destroy` consumes a handled event. `throw`, `rethrow`, and
`propagate` consume the owner by transferring it to another handler or out of the
function. A rethrow reuses the active caught event; it never repacks the payload
or changes provenance.

### Exceptional CFG

A potentially throwing call is an `invoke` terminator with two explicit,
ordered successors:

1. the normal successor, on which only the ordinary result is available;
2. the exceptional successor, on which only the owned event is available.

Direct, indirect, and interface dispatch have distinct invoke variants. Normal
and exceptional successors are different blocks, and exceptional edges carry
the target handler's event value explicitly. `throw`, `rethrow`, and `propagate`
are exceptional terminators, not conditional branches. CFG traversal retains
normal-before-exceptional ordering for deterministic output and diagnostics.

### Handler entry and matching

`catch_entry` is the first instruction in a handler dispatch block. It defines
the handler event and records a unique handler identifier plus the ordered
canonical catch descriptors. Dispatch uses `exception_match` in source order.
Concrete descriptors match exact dynamic nominal identity; `Error` is the final
explicit catch-all. `exception_borrow` binds the selected payload in the catch
scope. An unmatched event propagates to the lexically enclosing handler or root.

### Function and call effects

`IRFunction.may_throw` is conservative internal metadata and does not alter
source function types. `InstructionEffects.may_throw` is distinct from
`may_trap`: panic/trap remains uncatchable. A call to a known throwing function
must use `invoke`. The semantic exception-effect summary is the sole authority
for `may_throw`: lowering consumes its function and interface-slot facts and
does not re-infer them. Interface witness slots carry the same fact; a throwing
slot uses `invoke_interface`, while a nonthrowing slot uses `interface_call`.
Ordinary `call` denotes a nonthrowing edge shape. `Error.message` is the frozen
nonthrowing slot.

No optimization is authorized to infer nonthrowing behavior from this metadata
in Milestone 3.

### Cleanup and interpretation

AST lowering materializes lexical storage cleanup before every exceptional
transfer. Catch payloads remain borrows, and handled events are destroyed once.
The Initial IR interpreter executes explicit handler lookup, exact matching,
propagation, rethrow, and root termination. Panic continues to use the existing
uncatchable `IRExecutionError` path and is never converted into an event.

Implementation clarification: when a potentially throwing invocation exits a
catch and propagates a newly produced event, lowering inserts an explicit
exceptional cleanup block. That block receives the new event, performs the
terminal destruction required for every caught event whose scope is being
exited, and only then propagates the new event. Caught events belonging to an
enclosing catch scope that remains active across a nested handler are retained.
The same rule applies when an unmatched nested handler propagates a new event
out of an active catch. This is the explicit cleanup required by the original
linear-ownership decision; it introduces neither implicit consumption nor a new
event representation.

### Verification

The verifier rejects, at minimum:

- missing, identical, or unresolved invoke successors;
- exceptional edges that do not supply the target handler event;
- handler entries outside first position, duplicate handler identifiers,
  duplicate catches, or catches after `Error`;
- handlers reached by normal edges or by no exceptional edge;
- event operands with a non-event type;
- wrong-edge result or event uses;
- an ordinary call to a known `may_throw` function;
- exception-bearing functions without `may_throw`;
- rethrow of an event not introduced by a catch; and
- local use after event consumption.

Python owns the complete Milestone 3 semantic verifier. The Rust mirror imports
the same type and instruction variants, treats exceptional transfers as CFG
terminators, and retains exhaustive/fail-closed schema matches. SSA-specific
dominance and ownership rules remain reserved for Milestone 5.

### Serialization

Python DTO/JSON and Rust serde use identical discriminated tags for the opaque
type, invoke family, event operations, and transfers. `may_throw` is encoded only
when true and defaults to false, preserving old non-exception documents.

The existing schema-v1 envelope remains the current envelope because the change
is additive: old documents retain identical shapes, while older readers reject
unknown exception tags or the `may_throw` field rather than ignoring them. Any
future change that reinterprets an existing tag or makes an existing optional
field mandatory requires a schema-version increment.

## Consequences

- Initial IR is the first complete backend representation of exception
  semantics.
- Printers, operand traversal, CFG analysis, optimizers, the interpreter, and
  Python/Rust interchange must preserve exceptional constructs.
- Exception-bearing Initial IR passes only to the accepted exception-aware SSA
  and native lowering defined by their own ADRs.
- Profile 24 promotes native `ERROR_HANDLING` after completion of the
  implementation plan's capability-promotion milestone.

## Out of scope

This ADR does not select SSA edge values, LLVM EH or status lowering, landing
pads, unwinder integration, runtime event layout/ABI, FFI propagation, or native
execution.
