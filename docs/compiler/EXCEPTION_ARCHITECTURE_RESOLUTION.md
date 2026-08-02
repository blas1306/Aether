# Exception Architecture Resolution

> Classification: **Architecture closure and implementation authorization**.
>
> Phase: **7.1 — Complete Exception Model**.
>
> This is not an RFC. It records the final resolution of the
> [Complete Exception Model RFC](COMPLETE_EXCEPTION_MODEL_RFC.md), its
> [Decision Log](COMPLETE_EXCEPTION_MODEL_DECISION_LOG.md), and the
> [Checked Exceptions Architecture Study](CHECKED_EXCEPTIONS_ARCHITECTURE_STUDY.md).
> Where the earlier working documents leave checked exceptions pending or
> recommend checked effects, this resolution records the final choice:
> exceptions are unchecked.

## 1. Purpose

All language and architecture work for Phase 7.1 is complete. The exception
model, ownership rules, compiler-pipeline obligations, runtime boundaries, and
FFI containment policy are approved and frozen by this resolution.

Remaining work is implementation engineering: choosing internal
representations, lowering the approved semantics, verifying every stage, and
proving parity. Implementation work may now begin, but it may not reopen or
silently reinterpret the language design.

## 2. Final accepted architectural decisions

- ✓ **`Error` is a built-in interface.** This provides one typed throwable
  boundary without requiring arbitrary values or a class hierarchy.
- ✓ **`Error.message()` is semantically non-throwing.** It never produces an
  Aether exception. An unrecoverable internal failure follows the existing
  fail-fast panic contract without constructing a second `Error` or recursively
  entering exception handling.
- ✓ **Structs and classes may implement `Error`.** This preserves ordinary
  struct value semantics and class reference identity for domain-appropriate
  error types.
- ✓ **There is no exception inheritance.** Interfaces and exact nominal types
  fit Aether's object model without introducing inheritance or downcasts.
- ✓ **`throw` is statement-only.** A terminating statement avoids committing
  1.x to bottom-type and expression-inference semantics.
- ✓ **Bare rethrow is supported.** `throw;` propagates the active event without
  copying its payload or replacing its original throw provenance.
- ✓ **Catch matching is exact.** Concrete catches match canonical dynamic
  nominal identity, while `Error` is the explicit catch-all.
- ✓ **Multiple catches are supported.** Source-ordered handlers provide typed
  recovery without manual error tags.
- ✓ **Try/catch may be nested.** The innermost active handler matches first,
  giving propagation and cleanup deterministic lexical boundaries.
- ✓ **Panic is distinct from throw.** A panic is fail-fast and uncatchable,
  whereas a throw creates a recoverable exceptional control transfer.
- ✓ **There is no `finally` in 1.x.** Automatic lifecycle cleanup is approved,
  while arbitrary resource-scope code requires a separate future RFC.
- ✓ **Exceptional control flow is explicit in the CFG.** Real exceptional
  edges are required so cleanup, dominance, verification, and optimization
  operate on the complete graph.
- ✓ **Lifecycle cleanup is explicit before SSA.** Lexical ownership and partial
  initialization are resolved while their source-level scope information is
  still authoritative.
- ✓ **Exception-event ownership is linear.** Exactly one owner moves through
  propagation, catches borrow the payload, and handling destroys it once.
- ✓ **The exception event is opaque.** Payload storage and propagation layout
  remain private so source semantics do not select a backend or ABI.
- ✓ **The runtime never scans the stack for owners.** Compiler-verified cleanup
  invokes typed lifecycle operations under the existing ARC model.
- ✓ **Exceptions never cross raw C.** Exports, imports, and callbacks use
  explicit containment and error transport so foreign frames never observe an
  Aether unwind.
- ✓ **Expected failures use Result/Status values.** Routine outcomes that
  callers normally inspect remain explicit ordinary values.
- ✓ **Panic is reserved for safety and invariant failures.** Bounds, overflow,
  ARC corruption, and equivalent failures cannot be recovered through catch.
- ✓ **Recoverable exceptional failures use exceptions.** Non-routine failures
  that may be handled at a subsystem boundary use typed `Error` events.
- ✓ **Exceptions are unchecked.** Throws sets do not participate in source
  signatures, interfaces, or function types, avoiding a second exhaustive
  error channel and an exception-only effect system.

Unchecked source semantics do not weaken compiler correctness: every
potentially throwing operation remains explicit and conservative in internal
effects, CFG, ownership analysis, verification, optimization, and lowering.
The unchecked rule does not apply to the language-defined `Error.message()`
contract; a throwing implementation is a semantic error.

## 3. Remaining implementation decisions

The following choices remain open because they do not define language
semantics:

- **SSA edge representation:** block arguments, edge-defined values, verified
  trampolines, or another representation that preserves exceptional
  predecessors and linear event ownership.
- **Backend lowering strategy:** LLVM EH, explicit status/out-parameter
  lowering, dual continuations, or another verified strategy.
- **Runtime ABI:** the private compiler/runtime operations, versioning, and
  representation used for event creation, matching, transfer, destruction,
  propagation, and root termination.

Different implementations and target-specific strategies are permitted. Every
choice must preserve identical approved source behavior, ARC cleanup,
diagnostics, panic separation, and FFI containment.

## 4. Implementation constraints

No implementation, optimization, runtime extraction, target port, or FFI
adapter may change any of the following without a new RFC:

- source semantics;
- value, reference, or exception-event ownership;
- cleanup eligibility or ordering;
- panic meaning, catchability, or termination behavior;
- containment at raw C boundaries; or
- observable exception and panic diagnostics.

Implementation convenience, backend limitations, performance results, and
foreign ABI conventions are not authority to alter these contracts. A
deviation is an implementation defect until a new RFC explicitly changes the
architecture.

## 5. Approval

Architecture status: **APPROVED**

Language semantics: **FROZEN**

Implementation: **AUTHORIZED**

Future language changes require a new RFC.
