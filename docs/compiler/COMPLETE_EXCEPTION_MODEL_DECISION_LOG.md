# Complete Exception Model — Architecture Decision Log

> Classification: **Design approval checklist**.
>
> Companion to
> [Complete Exception Model RFC](COMPLETE_EXCEPTION_MODEL_RFC.md).
>
> This document records decisions only. The RFC remains the source of rationale
> and detailed semantics. Nothing here authorizes implementation or changes the
> Aether 1.0 profile.

## Status definitions

- **Accepted** — already fixed by Aether's normative philosophy, lifecycle
  contract, or strategic roadmap. Acceptance does not mean implemented.
- **Pending Decision** — must be explicitly accepted or rejected before
  exception implementation begins.
- **Deferred to Future RFC** — intentionally excluded from Phase 7.1 and
  requires a separate future design process.

## 1. Language model

### L1. Built-in `Error` interface

- **Decision:** Whether only non-null values implementing a built-in `Error`
  interface may be thrown.
- **Current recommendation:** Adopt `Error` as the root throwable interface,
  with a nonthrowing `string message()` contract.
- **Why it matters:** It defines the throwable type boundary without adding
  class inheritance or allowing arbitrary scalar throws.
- **Consequences:** Requires a new built-in type, interface conformance,
  existential ownership, and runtime nominal identity.
- **Dependencies:** Error payload rules, catch matching, diagnostics, runtime
  descriptors, and exception effects.
- **Final status:** **Pending Decision**

### L2. Struct and class errors

- **Decision:** Whether both structs and classes may implement `Error`.
- **Current recommendation:** Permit both; structs retain value semantics and
  classes retain reference identity.
- **Why it matters:** Domain errors should not be forced into one allocation or
  identity model.
- **Consequences:** Throwing a struct establishes an owned snapshot; throwing a
  class preserves identity and acquires an owned reference.
- **Dependencies:** L1, lifecycle registry coverage, interface boxes, and
  opaque event storage.
- **Final status:** **Pending Decision**

### L3. No exception inheritance

- **Decision:** Whether Phase 7.1 introduces a class hierarchy for exceptions.
- **Current recommendation:** Do not introduce inheritance; use interface
  conformance and exact nominal matching.
- **Why it matters:** Class inheritance, downcasts, and override chains are
  outside the 1.x object model.
- **Consequences:** Concrete catches are disjoint; shared behavior comes from
  `Error`, not a base-class chain.
- **Dependencies:** L1 and L6.
- **Final status:** **Accepted**

### L4. Statement-only `throw`

- **Decision:** Whether `throw` is a statement or also an expression.
- **Current recommendation:** Support terminating `throw error;` statements
  only in 1.x.
- **Why it matters:** Expression throw would require bottom-type, inference,
  precedence, and partial-expression rules.
- **Consequences:** Throw cannot appear inside an initializer or conditional
  expression; expression throw can be designed later without changing this
  statement form.
- **Dependencies:** Parser grammar, return analysis, and checked effects.
- **Final status:** **Pending Decision**

### L5. Bare rethrow

- **Decision:** Whether `throw;` inside a catch propagates the active event.
- **Current recommendation:** Allow it only lexically inside a catch and
  preserve the original payload, dynamic type, and throw provenance.
- **Why it matters:** Rethrow must not accidentally copy or replace the active
  exception.
- **Consequences:** Catch bodies need an active-event context and rethrow skips
  sibling catches.
- **Dependencies:** Event ownership, catch CFG, effects, and verifier rules.
- **Final status:** **Pending Decision**

### L6. Exact catch matching

- **Decision:** How typed catches select an error.
- **Current recommendation:** Match an exact canonical concrete type; use
  `Error` as the only catch-all. Do not match other interfaces or implicit
  conversions.
- **Why it matters:** It determines runtime type identity and avoids introducing
  inheritance or general downcasts.
- **Consequences:** Duplicate concrete catches and catches after `Error` are
  invalid.
- **Dependencies:** L1, descriptor identity, module nominal identity, and
  effect subtraction.
- **Final status:** **Pending Decision**

### L7. Multiple catches

- **Decision:** Whether one try may have multiple source-ordered catch clauses.
- **Current recommendation:** Allow multiple exact catches followed by at most
  one root catch.
- **Why it matters:** Structured error recovery otherwise collapses into manual
  tags inside a single handler.
- **Consequences:** The parser, typechecker, CFG, and diagnostics must preserve
  ordering and reject unreachable clauses.
- **Dependencies:** L6 and exception effects.
- **Final status:** **Pending Decision**

### L8. Nested try/catch

- **Decision:** Whether handlers nest lexically and dynamically.
- **Current recommendation:** The innermost active try matches first; errors
  from a catch begin at the next outer handler.
- **Why it matters:** It fixes propagation boundaries and prevents sibling
  catches from handling failures raised by a catch body.
- **Consequences:** Cleanup and handler context must remain correct through
  arbitrary nesting.
- **Dependencies:** Exceptional CFG, cleanup ladders, and rethrow.
- **Final status:** **Pending Decision**

### L9. Panic versus throw

- **Decision:** Whether safety panics participate in language exception
  handling.
- **Current recommendation:** Keep panic fail-fast, uncatchable, and
  non-unwinding; only `throw` creates a catchable event.
- **Why it matters:** Bounds, overflow, ARC corruption, and invariant failures
  must not become recoverable accidentally.
- **Consequences:** Panic has no checked effect or handler edge and wins if it
  occurs during exception processing.
- **Dependencies:** Runtime termination, optimizer effects, and diagnostics.
- **Final status:** **Accepted**

### L10. No `finally` in 1.x

- **Decision:** Whether arbitrary cleanup code runs through `finally`.
- **Current recommendation:** Exclude `finally` from 1.x; automatic lifecycle
  cleanup remains mandatory.
- **Why it matters:** `finally` introduces separate rules for competing return,
  break, continue, throw, and panic transfers and prejudges general resource
  management.
- **Consequences:** A future resource-scope proposal must compare `finally`,
  `defer`, scope guards, and owned resources independently.
- **Dependencies:** Future resource and destructor design.
- **Final status:** **Deferred to Future RFC**

## 2. Exception effects: checked exceptions

- **Decision:** Whether catchable exceptions are part of function signatures as
  checked typed effects.
- **Current recommendation:** The working RFC recommends explicit typed throws
  sets, but this recommendation is not accepted.
- **Why it matters:** This choice changes the language's function type system
  and public API compatibility, not merely compiler analysis.
- **Consequences:** Checked effects make nonthrowing calls explicit and prevent
  public APIs from silently acquiring new escaping errors. They also add
  annotation burden, effect-subtraction rules, module visibility constraints,
  and migration costs. Unchecked exceptions keep signatures smaller but force
  conservative call assumptions and make exception behavior less explicit.
- **Dependencies:** The consequences must be evaluated across:
  - **Interfaces:** implementations may need effect-subset rules relative to
    interface methods.
  - **Function types:** throws sets become part of callable compatibility and
    serialization.
  - **Higher-order functions:** callable parameters must express which effects
    they permit, propagate, or handle.
  - **Future generics:** generic algorithms may eventually need effect
    parameters, constraints, inference, or deliberate effect erasure.
  - **FFI:** exported throwing signatures need wrappers; imported C functions
    have explicit nonthrowing Aether exception effects.
- **Final status:** **Pending Decision**

Advantages include separate-compilation precision, optimizer certainty,
auditable public failure contracts, and explicit propagation. Disadvantages
include larger signatures, callable variance/subset rules, interface and
higher-order complexity, possible generic effect polymorphism, and significant
source compatibility consequences. This decision must be made before grammar,
IR signatures, callable identity, or FFI wrappers are designed.

Status:
**Pending Decision**

## 3. Ownership

### O1. Cleanup guarantee

- **Decision:** Whether all successfully initialized owning values are cleaned
  exactly once on catchable exceptional exits.
- **Current recommendation:** Require the same deterministic ARC lifecycle
  guarantee as normal scope exit, return, break, and continue.
- **Why it matters:** Exceptions are unsafe without complete frame cleanup.
- **Consequences:** Every throwing point needs an exact cleanup path; panic
  remains the only path without Aether stack cleanup.
- **Dependencies:** Existing lifecycle registry and explicit exceptional CFG.
- **Final status:** **Accepted**

### O2. Linear exception-event ownership

- **Decision:** How ownership of the in-flight event is represented.
- **Current recommendation:** Exactly one hidden owner is transferred through
  propagation; catches borrow the payload; normal handling destroys it; rethrow
  moves it outward.
- **Why it matters:** Duplication or loss creates leaks, double destruction, or
  invalid catch borrows.
- **Consequences:** IR, SSA, runtime helpers, and optimizers must preserve event
  linearity.
- **Dependencies:** O1, exception-event representation, SSA edge values, and
  runtime API.
- **Final status:** **Pending Decision**

### O3. Partial-initialization rollback

- **Decision:** Whether exceptions roll back only the successfully initialized
  prefix of an aggregate/object.
- **Current recommendation:** Require reverse-order rollback for struct/class
  fields and Array/List elements, without reading uninitialized storage.
- **Why it matters:** Constructors, collection creation, copy, and slicing can
  fail after acquiring partial ownership.
- **Consequences:** Initialization state or live-prefix counts must survive
  until cleanup is generated and verified.
- **Dependencies:** Lifecycle metadata and per-type destruction plans.
- **Final status:** **Accepted**

## 4. Initial IR

### IR1. Explicit exceptional CFG

- **Decision:** Whether exceptional flow is explicit before SSA.
- **Current recommendation:** Represent normal and exceptional successors as
  real, distinguishable CFG edges; do not retain implicit try regions as
  control-flow authority.
- **Why it matters:** Cleanup, dominance, ownership, and verification require
  complete predecessor information.
- **Consequences:** Potentially throwing operations terminate blocks and cleanup
  paths are explicit.
- **Dependencies:** Exception-effect decision and IR schema revision.
- **Final status:** **Accepted**
- **Resolution:** Initial IR uses real, distinguishable normal and exceptional
  edges. Potentially throwing operations terminate their blocks, and all CFG
  consumers traverse normal then exceptional successors deterministically.
- **Record:** `adr/ADR-EXCEPTION-INITIAL-IR.md`

### IR2. `invoke`

- **Decision:** Whether a throwing call uses a two-successor semantic operation.
- **Current recommendation:** Use an implementation-neutral `invoke` with one
  normal and one exceptional successor; ordinary `call` remains nonthrowing.
- **Why it matters:** A hidden mid-block transfer would make CFG analyses
  unsound.
- **Consequences:** All direct, indirect, method, interface, constructor, and
  imported calls must carry accurate exception effects.
- **Dependencies:** IR1, checked-effects decision, and callable signatures.
- **Final status:** **Accepted**
- **Resolution:** Direct, indirect, and interface potentially throwing calls use
  two-successor `invoke` terminators. Ordinary `call` is the nonthrowing form;
  `may_throw` remains conservative internal metadata distinct from panic/trap.
- **Record:** `adr/ADR-EXCEPTION-INITIAL-IR.md`

### IR3. Exception events

- **Decision:** Whether Initial IR carries an opaque owned event distinct from
  the source error payload.
- **Current recommendation:** Use explicit pack, match, borrow, transfer, and
  destroy semantics without fixing a machine layout.
- **Why it matters:** Source value/reference semantics must remain independent
  of backend transport.
- **Consequences:** The IR needs an internal event type and ownership checks.
- **Dependencies:** L1, O2, runtime event contract, and descriptor identity.
- **Final status:** **Accepted**
- **Resolution:** Initial IR carries a linearly owned opaque
  `exception_event`, with explicit pack, exact/root match, payload borrow,
  transfer, rethrow, propagation, and destroy operations. No machine layout or
  runtime ABI is selected.
- **Record:** `adr/ADR-EXCEPTION-INITIAL-IR.md`

## 5. SSA

### S1. Exceptional predecessors and edge values

- **Decision:** How SSA receives normal results and exception events from an
  invoke edge.
- **Current recommendation:** Exceptional edges are real predecessors; choose
  block arguments, edge-defined values, or verified trampolines before
  implementation.
- **Why it matters:** Normal results exist only on normal edges and events only
  on exceptional edges.
- **Consequences:** Dominance, frontiers, phis, critical-edge splitting, and
  reachability must use the full CFG.
- **Dependencies:** IR1, IR2, and the pending SSA representation selection.
- **Final status:** **Pending Decision**

### S2. SSA event ownership

- **Decision:** How event ownership crosses SSA joins.
- **Current recommendation:** A handler join receives exactly one owner from
  each executable exceptional predecessor; phis transfer rather than copy it.
- **Why it matters:** Ordinary SSA value substitution cannot be allowed to
  duplicate a linear owner.
- **Consequences:** Catch borrows cannot outlive event destruction, and event
  phis need ownership-aware simplification.
- **Dependencies:** O2 and S1.
- **Final status:** **Pending Decision**

### S3. Verifier authority

- **Decision:** Whether exceptional structure and ownership are mandatory SSA
  verifier invariants.
- **Current recommendation:** Verify exact predecessor sets, edge availability,
  full-CFG dominance, call/effect agreement, cleanup ordering, and single event
  consumption.
- **Why it matters:** LLVM lowering must not repair invalid compiler IR.
- **Consequences:** Python/Rust verifier schemas and negative corpora must be
  updated before exception promotion.
- **Dependencies:** Final S1 representation and internal IR schema.
- **Final status:** **Accepted**

## 6. Optimizers

### OPT1. Global exception-aware optimizer contract

- **Decision:** Whether exception timing, handler selection, cleanup, and event
  ownership are observable optimizer constraints.
- **Current recommendation:** No transformation may delete, duplicate, reorder,
  or redirect a possible throw or its cleanup without proof of semantic and
  ownership equivalence.
- **Why it matters:** Normal-result equivalence alone is insufficient when a
  transformation changes which error, panic, side effect, or handler occurs.
- **Consequences:** All pass families need accurate throw/panic/effect summaries
  and post-pass verification; unknown operations remain conservative.
- **Dependencies:** Explicit CFG, ownership model, and verifier coverage.
- **Final status:** **Accepted**

## 7. Backend lowering

- **Decision:** Which mechanism transports a verified exception through native
  frames.
- **Current recommendation:** None. Candidate families are LLVM
  `invoke`/landing pads or funclets, status-value returns, explicit
  dual-continuation CFG, exception out-parameters, and `setjmp`/`longjmp`-style
  transport.
- **Why it matters:** The choice affects portability, normal-path cost, calling
  convention, indirect calls, debugging, sanitizer behavior, and FFI
  containment.
- **Consequences:** Competing prototypes must preserve identical source
  semantics, cleanup, ownership, diagnostics, and panic separation. Different
  targets may eventually use different mechanisms.
- **Dependencies:** Frozen semantic IR/SSA contract, first and second target
  matrix, runtime contract, and measured prototype evidence.
- **Final status:** **Pending Decision**

No candidate is preferred by this decision log.

Status:
**Pending Decision**

## 8. Runtime

### R1. Opaque event

- **Decision:** Whether runtime exception transport is an opaque internal
  object/event rather than a source class or exposed header.
- **Current recommendation:** Keep payload storage, boxing, propagation state,
  and helper names private.
- **Why it matters:** Source semantics must survive backend and target changes.
- **Consequences:** Runtime operations expose behavior and ownership, not
  layout.
- **Dependencies:** IR3, O2, and selected backend.
- **Final status:** **Pending Decision**

### R2. Descriptor identity

- **Decision:** How exact catch matching identifies a nominal error across
  modules.
- **Current recommendation:** Use collision-safe canonical nominal identity;
  pointer equality is valid only if one descriptor instance is guaranteed.
- **Why it matters:** Hash collisions, import aliases, or duplicate descriptors
  must not select the wrong catch.
- **Consequences:** Module/linking and runtime descriptors need one canonical
  identity contract.
- **Dependencies:** L6, module identity, and runtime extraction/versioning.
- **Final status:** **Pending Decision**

### R3. Runtime cleanup responsibility

- **Decision:** Whether the runtime discovers stack owners dynamically.
- **Current recommendation:** It does not; compiler-verified cleanup invokes
  typed lifecycle primitives, while the runtime owns event transfer,
  destruction, and root termination.
- **Why it matters:** Stack scanning would duplicate and weaken the compiler's
  ARC ownership model.
- **Consequences:** Both native EH and explicit-status backends must execute the
  same logical cleanup graph.
- **Dependencies:** O1, lifecycle expansion, and backend lowering.
- **Final status:** **Accepted**

### R4. Runtime contract and ABI

- **Decision:** What private runtime operations and versioned boundary support
  pack, match, borrow, transfer, destroy, and root handling.
- **Current recommendation:** Freeze a narrow internal contract before
  implementation; do not define a public exception ABI in Phase 7.1.
- **Why it matters:** Compiler and runtime must agree without exposing current
  headers or LLVM calling conventions as language semantics.
- **Consequences:** An internal version/schema is required; a stable public ABI
  remains separate work.
- **Dependencies:** R1, R2, O2, backend selection, and allocator failure policy.
- **Final status:** **Pending Decision**

## 9. FFI

### F1. Boundary containment

- **Decision:** Whether an Aether exception may cross an unaware raw C frame.
- **Current recommendation:** Never. C-callable Aether code is nonthrowing or
  uses a wrapper that captures every event and converts it to explicit error
  transport. Raw C calls cannot directly throw an Aether exception.
- **Why it matters:** Cross-language unwinding without a shared ABI is undefined
  and would couple Aether to foreign exception systems.
- **Consequences:** Exports, callbacks, and foreign adapters need declared
  wrappers and explicit ownership; C++ or host exceptions are translated
  outside the raw C boundary.
- **Dependencies:** Checked-effects decision, runtime contract, and a future
  public C ABI RFC.
- **Final status:** **Pending Decision**

## 10. Promotion criteria

### P1. Atomic end-to-end promotion

- **Decision:** Whether exceptions can enter the stable profile incrementally
  with missing pipeline stages.
- **Current recommendation:** Promote only after syntax/type semantics,
  ownership, Initial IR, both verifier paths, SSA, enabled optimizers, one
  native backend, runtime termination, diagnostics, tooling, and AST/native
  parity are complete.
- **Why it matters:** Frontend-only or normal-path-only support would violate
  Aether's capability and correctness model.
- **Consequences:** The capability gate continues to reject exceptions until
  the declared profile is complete; no silent AST fallback or partial native
  subset is permitted.
- **Dependencies:** Resolution of every pending decision above, sanitizer and
  target tests, normative specification changes, and release-profile updates.
- **Final status:** **Accepted**

## 11. Final checklist

Architecture frozen

- [ ] Exception model accepted
- [ ] Checked exceptions decision
- [ ] Runtime ownership model
- [ ] SSA representation
- [ ] Backend lowering strategy
- [ ] Runtime ABI
- [ ] FFI policy
- [ ] Ready for implementation
