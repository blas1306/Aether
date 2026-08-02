# Exception Frozen-Semantics Review Checklist

> Milestone: **0 — Preparation**
>
> Purpose: review checklist for every exception implementation PR.
>
> Authority:
> [`EXCEPTION_ARCHITECTURE_RESOLUTION.md`](../EXCEPTION_ARCHITECTURE_RESOLUTION.md),
> [`COMPLETE_EXCEPTION_MODEL_RFC.md`](../COMPLETE_EXCEPTION_MODEL_RFC.md), and
> [`EXCEPTION_IMPLEMENTATION_PLAN.md`](../EXCEPTION_IMPLEMENTATION_PLAN.md).
>
> This checklist summarizes frozen decisions. It does not define new semantics
> and is not an RFC.

## How to use this checklist

For every implementation PR:

- [ ] Link the PR to the milestone that owns its changes.
- [ ] Mark every applicable item below as satisfied and cite its test evidence.
- [ ] Mark an item not applicable only with a component-specific explanation.
- [ ] Treat any semantic deviation as an implementation defect unless a new RFC
      explicitly changes the architecture.
- [ ] Keep `ERROR_HANDLING` disabled in the stable native capability profile
      until Milestone 12 promotes the complete system atomically.

## Source-language model

- [ ] `Error` is installed as a built-in interface, not as a base class, magic
      string type, or arbitrary-value marker.
- [ ] The `Error.message()` contract remains semantically non-throwing and
      returns `string`: it cannot produce an Aether exception; an unrecoverable
      internal failure panics without a second `Error` or recursive handling.
- [ ] Only non-null values implementing `Error` are throwable.
- [ ] Structs may implement `Error` and retain ordinary struct value semantics.
- [ ] Classes may implement `Error` and retain ordinary class reference identity.
- [ ] Throwing a struct establishes the approved owned snapshot semantics.
- [ ] Throwing a class preserves identity while establishing event ownership.
- [ ] No exception inheritance, exception base-class hierarchy, exception
      downcast rule, or implicit throwable conversion is introduced.
- [ ] Shared behavior is expressed through interfaces; concrete catch matching
      does not use ordinary interface assignability.
- [ ] `throw error;` is a terminating statement only.
- [ ] `throw` is not accepted in expression position and no bottom-type or
      expression-inference semantics are introduced.
- [ ] Bare `throw;` is accepted only in the active catch context defined by the
      architecture.
- [ ] Bare rethrow transfers the existing event without copying or repacking its
      payload and preserves original throw provenance.
- [ ] A rethrow skips sibling catches and resumes matching at the next outer
      handler.
- [ ] A concrete catch matches only exact canonical dynamic nominal identity.
- [ ] `Error` is the explicit catch-all; no other interface is a catch-all.
- [ ] Catch clauses are evaluated in source order.
- [ ] Multiple concrete catches are supported.
- [ ] Duplicate concrete catches are rejected.
- [ ] At most one `Error` catch-all exists and catches following it are rejected
      as unreachable.
- [ ] Try/catch constructs may nest arbitrarily.
- [ ] The innermost active handler matches first.
- [ ] Exceptions thrown by a catch body begin matching at the next outer handler,
      not at sibling catches.
- [ ] Catch bindings have the approved lexical scope and borrowed payload
      lifetime.
- [ ] A catch borrow cannot escape without an ordinary owning copy.
- [ ] `finally` is not accepted as exception syntax in Aether 1.x.
- [ ] Automatic lifecycle cleanup is not described or exposed as `finally`.

## Unchecked source semantics and failure taxonomy

- [ ] Exceptions remain unchecked in source.
- [ ] Source signatures contain no `throws` clause or typed throws set.
- [ ] Interfaces, overrides, constructors, callbacks, higher-order functions, and
      function types gain no exception component.
- [ ] No catch-or-declare rule is introduced.
- [ ] Internal conservative `may_throw` facts remain compiler metadata and do not
      become source-level checked effects.
- [ ] `Result` or status values remain the mechanism for expected failures that
      callers normally inspect.
- [ ] Exceptions represent recoverable but exceptional failures that may be
      handled at a subsystem boundary.
- [ ] Panic remains reserved for safety failures, invariant violations, bounds
      failures, overflow, allocator failure, ARC corruption, and equivalent
      fail-fast conditions.
- [ ] Panic is distinct from throw, uncatchable, and never packaged as an
      exception event.
- [ ] Panic retains the approved no-Aether-unwind/no-exception-cleanup behavior.
- [ ] A failure while processing an exception follows the approved fail-fast
      policy and does not recursively create a catchable exception.

## CFG, lifecycle, and event ownership

- [ ] Every potentially throwing operation has explicit, distinguishable normal
      and exceptional CFG successors.
- [ ] No hidden try-region metadata, implicit mid-block transfer, host-language
      signal, global, or TLS “current exception” is control-flow authority.
- [ ] Normal results exist only on normal edges.
- [ ] Exception events exist only on exceptional edges.
- [ ] Ordered catches, nesting, cleanup, rethrow, and outward propagation are
      represented by the explicit CFG.
- [ ] Lifecycle cleanup is planned and expanded before SSA while lexical scope and
      initialization state remain authoritative.
- [ ] Every successfully initialized owner is cleaned exactly once on a catchable
      exceptional exit.
- [ ] Cleanup runs in strict reverse initialization order from the throw point to
      the selected handler boundary or outward propagation boundary.
- [ ] Partial initialization rolls back only the initialized prefix of an
      aggregate, object, array, list, or interface carrier.
- [ ] Normal, return, break, and continue cleanup behavior remains unchanged.
- [ ] The event is formed or acquired before source-value cleanup invalidates the
      thrown value.
- [ ] Exception-event ownership is linear: exactly one hidden owner exists on
      every reachable path.
- [ ] Propagation and rethrow transfer event ownership rather than copy it.
- [ ] Matching and catch bindings borrow the payload.
- [ ] Successful handling destroys the event exactly once.
- [ ] Unhandled root termination destroys the event exactly once after reporting.
- [ ] SSA joins select one incoming owner and never duplicate or drop it.
- [ ] Optimizers preserve event ownership, cleanup presence and order, throw
      timing, handler selection, and panic ordering.

## Opaque representation, backend, and runtime

- [ ] The event representation remains opaque and private to compiler/runtime
      implementation.
- [ ] Payload layout, boxing, descriptor fields, helper symbols, propagation
      state, and machine ABI are not exposed as source semantics.
- [ ] Canonical nominal descriptor identity is collision-safe across modules and
      linked artifacts.
- [ ] Pointer equality is used for exact matching only if unique descriptor
      identity is guaranteed.
- [ ] The runtime performs event creation, matching support, borrowing, transfer,
      destruction, root reporting, and termination under the selected private ABI.
- [ ] The runtime does not scan the stack or arbitrary memory for Aether owners.
- [ ] Compiler-generated, verifier-approved cleanup invokes typed lifecycle
      primitives.
- [ ] LLVM/backend lowering consumes already verified CFG, cleanup, dominance,
      identity, and ownership facts; it does not repair invalid IR.
- [ ] Backend strategy choices do not alter source behavior, cleanup, diagnostics,
      panic separation, or FFI containment.
- [ ] Unhandled exception output and exit status follow the frozen observable
      diagnostic contract.

## FFI and ABI containment

- [ ] An Aether exception never crosses an unaware raw C frame in either
      direction.
- [ ] Raw C imports are nonthrowing in the Aether exception model.
- [ ] Expected C failures use their declared status/result/out-parameter
      conventions.
- [ ] An Aether wrapper may throw only after the raw C call has returned.
- [ ] Throwing Aether exports are either rejected or contained by a wrapper that
      converts the event to explicit error transport.
- [ ] C callbacks into Aether are nonthrowing or contain every event before
      returning to C.
- [ ] C++/Objective-C/SEH/other foreign exceptions are caught by a foreign adapter
      and translated outside the raw C boundary.
- [ ] Ownership and destruction of any boundary error handle are explicit.
- [ ] The private runtime ABI is not presented as a stable public FFI ABI.
- [ ] Panic is not converted into a recoverable FFI result.

## Parity, tooling, capability, and release

- [ ] Python and Rust IR schemas/importers/verifiers change atomically or through a
      version gate that fails closed.
- [ ] Python and Rust verifiers agree on shared valid and invalid fixtures.
- [ ] Reference AST, Initial IR interpreter, SSA/optimized paths, and native
      execution agree on results, catch choice, cleanup trace, panic/throw, and
      exit status.
- [ ] Formatter, language service, LSP, CLI, VS Code, IntelliJ, Qt/UI editor, and
      web editor implement the same frozen syntax and diagnostics.
- [ ] Tooling never suggests checked-exception declarations.
- [ ] Every enabled optimizer has an explicit exception-safety disposition and
      post-pass verification evidence.
- [ ] Exceptions remain rejected by the stable native capability profile until
      lexer-through-runtime, FFI, tooling, parity, and release evidence are
      complete.
- [ ] Promotion is atomic in Milestone 12; there is no parser-only,
      interpreter-only, or backend-only stable promotion.
- [ ] Documentation distinguishes experimental legacy behavior from the approved
      architecture throughout migration.
