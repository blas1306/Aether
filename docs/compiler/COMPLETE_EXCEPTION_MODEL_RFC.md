# RFC: Complete Exception Model

> Classification: **Design/RFC — proposed**.
>
> Historical status: **superseded in part** by
> [Exception Architecture Resolution](EXCEPTION_ARCHITECTURE_RESOLUTION.md).
> In particular, the RFC's checked `throws` design is historical; accepted
> exceptions are unchecked. The accepted `Error.message()` non-throwing rule
> remains authoritative as clarified by that resolution.
>
> Roadmap phase: **Phase 7.1 architecture**.
>
> Date: 29 July 2026.
>
> This document does not change the Aether 1.0 language contract or native
> capability profile 23. Exceptions remain excluded until a later normative
> specification revision, capability promotion, implementation, and parity
> gate adopt this proposal end to end.

## 1. Purpose and constraints

This RFC defines a complete, implementation-neutral exception model before any
backend strategy is selected. It covers source semantics, ownership, Initial
IR, lifecycle expansion, SSA, optimizers, LLVM lowering, runtime support, FFI,
diagnostics, and testing.

The proposal is constrained by the current
[Aether 1.0 Language Specification](../aether/AETHER_LANGUAGE_SPEC_V1.md), the
[Aether Strategic Roadmap](AETHER_STRATEGIC_ROADMAP.md), and the existing
[Value Lifecycle Design](VALUE_LIFECYCLE_DESIGN.md):

- Aether 1.0 currently reserves `try`, `catch`, `throw`, and `Exception`, but
  exceptions are not in the stable profile.
- The existing AST-only exception behavior is experimental evidence, not a
  language contract.
- Catchable exceptions are planned for 1.x only after normal and exceptional
  cleanup are complete.
- Panic remains a fail-fast, uncatchable safety failure.
- Source semantics must not select LLVM EH, an OS unwinding ABI, status
  returns, `setjmp`, or any other propagation mechanism.
- Strong, non-atomic ARC remains the 1.x ownership model.
- Lifecycle is explicit before SSA, and ownership is not reconstructed from
  LLVM behavior.
- Expected failures, especially numerical convergence, parsing, and ordinary
  IO outcomes, should continue to use result/status values. Exceptions are for
  exceptional but recoverable failures.

This is an architecture proposal, not an implementation plan disguised as
source semantics. Layouts, helper names, calling conventions, and exception
transport are deliberately not source-visible.

## 2. Alternatives considered and recommendation

Several coherent exception models are possible. They should be compared before
selecting one.

### 2.1 Throwable domain

#### Alternative A: one built-in `Exception` class

Only a built-in reference class can be thrown. It owns a message and possibly
an error code.

Advantages:

- simple and uniform catch representation;
- preserves the shape of the current AST experiment; and
- requires no dynamic type matching beyond a catch-all.

Disadvantages:

- every domain error must be encoded into one weakly structured object;
- typed catches and user-defined payloads are unavailable without later class
  inheritance or ad hoc tags;
- it makes reference identity mandatory for what may naturally be a small
  value error; and
- multiple catches have no useful 1.x meaning.

#### Alternative B: a root class and exception inheritance

All throwable classes derive from a built-in root.

Advantages:

- familiar typed-catch model;
- natural reference identity; and
- mature native EH implementations map easily to it.

Disadvantages:

- class inheritance, override chains, subtype conversion, and downcasts are
  intentionally outside Aether 1.x;
- it would distort the object roadmap merely to obtain exception matching;
- value errors require allocation; and
- source semantics would become coupled to an object-model expansion.

#### Alternative C: arbitrary throwable values

Any non-void Aether value may be thrown and catches match its type.

Advantages:

- maximally general; and
- no new root abstraction is required.

Disadvantages:

- scalar throws such as `throw 3` have no stable diagnostic contract;
- catchability becomes accidental for every type;
- error-oriented API documentation and effect checking become weak; and
- runtime type descriptors and formatting would be required for the entire
  type system.

#### Alternative D: values conforming to a built-in `Error` interface

Classes and structs may implement a built-in error contract. The propagation
mechanism owns an existential error package while preserving the payload's
ordinary semantics.

Advantages:

- uses Aether's existing interface and lifecycle model instead of adding
  inheritance;
- supports structured domain errors;
- preserves value semantics for structs and identity semantics for classes;
- gives the typechecker a precise throwable boundary; and
- allows exact typed catches plus a root catch.

Disadvantages:

- requires runtime nominal type identity at catch sites;
- throwing a struct needs owned boxing or an equivalent opaque package; and
- `Error` existential ownership must be specified carefully.

**Recommendation:** Alternative D. A built-in `Error` interface is the
throwable boundary. Exceptions are not a special class hierarchy.

### 2.2 Checked versus unchecked propagation

#### Unchecked exceptions

Every call is potentially throwing unless analysis proves otherwise. This
keeps source signatures short, but makes call effects implicit, forces
optimizers and FFI to be conservative, and permits public APIs to acquire new
exception behavior silently.

#### Boolean checked effect

A function declares only that it may throw, without listing types. This makes
control effects explicit but gives callers and catches little precision.

#### Typed checked effect

A function declares the error types that may escape. The effect participates
in callable and interface method compatibility.

This adds signature surface, but it provides the strongest separate-compilation
contract, makes nonthrowing calls provable without whole-program analysis, and
fits Aether's preference for explicit semantics.

**Recommendation:** typed checked effects. A function with no `throws` clause
is nonthrowing in the catchable-exception sense. Panic remains possible and is
not part of a `throws` set.

### 2.3 Catch matching

Reasonable models include inheritance matching, arbitrary interface matching,
pattern matching over payloads, and exact nominal matching plus a root catch.

**Recommendation:** exact dynamic nominal type matching for concrete error
types, plus `Error` as the catch-all. This is expressive without introducing
general downcasts, inheritance, guards, or pattern matching. Other interfaces
implemented by an error do not participate in catch matching.

### 2.4 `throw` expression versus statement

A bottom-typed `throw` expression is useful inside conditional expressions and
initializers, but it requires bottom-type rules, precedence, inference, and
expression-level partial-initialization semantics.

**Recommendation:** `throw` is a terminating statement in 1.x. Expression
`throw` can be added later without changing statement semantics if Aether
eventually gains a deliberate bottom/never type.

### 2.5 Cleanup syntax

`finally`, `defer`, scope guards, and automatic lifecycle cleanup solve
different problems.

**Recommendation:** automatic ARC/lifecycle cleanup is mandatory; `finally`
is not included in 1.x. A future general resource-management RFC may consider
`defer` or scope guards independently.

### 2.6 Backend transport

Native EH tables, status returns, explicit dual-continuation CFG, and
`setjmp`-style transport can all implement the proposed semantics. Section 11
compares them. This RFC deliberately does **not** choose one.

## 3. Proposed source language

### 3.1 What an exception is

An **error value** is an ordinary non-null Aether value whose concrete type
implements the built-in `Error` interface.

An **exception** is the transient control-flow event created when an error
value is thrown. The event contains:

- ownership of the thrown error payload;
- the payload's canonical dynamic nominal type;
- the original throw source location when debug provenance is available; and
- propagation state required by the selected backend.

The event is not a source-level class, cannot be constructed directly, and has
no source-visible layout or identity.

Conceptually, the root contract is:

```aether
interface Error {
    string message();
}
```

`Error.message()` is semantically non-throwing: it must never produce an Aether
exception. This is a language-defined contract, independent of the historical
checked-`throws` proposal in this RFC. If its implementation encounters an
unrecoverable internal failure, the existing panic contract takes over
immediately; no second `Error` is constructed and exception handling is not
invoked recursively. A future effect/purity system may further constrain
diagnostic methods, but purity is not required by this RFC.

The base library should provide a final convenience class conceptually
equivalent to:

```aether
class Exception implements Error {
    // The concrete field representation is not specified here.
    constructor(string message) { ... }
    string message() { ... }
}
```

This retains a simple message-bearing error without making all exceptions
instances of that class.

The current experiment's `Exception("text")` construction therefore has a
direct migration path. Its `e.message` field experiment becomes the ordinary
interface call `e.message()`. The compiler should diagnose the old field form
with that replacement when the exception profile is promoted. The experimental
string-throw shorthand does not receive an implicit conversion.

### 3.2 Are exceptions classes?

No. A class may be an error payload by implementing `Error`, but structs may
also implement it. The root `Error` type is a built-in interface, not a base
class. No class inheritance is introduced.

Catch matching performs a restricted runtime type test defined only for error
dispatch. It does not add a general downcast or reflection operation to Aether.

### 3.3 Value and reference semantics

Throwing does not change the ordinary semantics of the payload type:

- A struct error is a value. Throwing it establishes an owned logical copy in
  the exception event. Fields are copied with their registered lifecycle
  operations.
- A class error is a reference. Throwing it preserves object identity and
  acquires an owned reference to the same object.
- Throwing an `Error` interface value preserves its dynamic carrier and
  witness identity while acquiring ownership according to the interface
  lifecycle.
- Nullable errors cannot be thrown without an explicit operation that
  produces a non-null `Error`; `throw value` rejects `Error?`.

For an lvalue source, the exception event acquires its ownership before stack
cleanup begins. The source local therefore remains valid until normal
exceptional cleanup destroys that local. For a consumable temporary, the
compiler may move ownership directly into the event. These strategies are
observationally equivalent and do not create a source-visible move operation.

The catch binder is an immutable, catch-scoped borrowed view of the payload
owned by the active exception event. Copying it into an ordinary owning slot
uses the payload type's ordinary copy rule. The event remains alive until the
catch completes, rethrows, or transfers propagation outward.

### 3.4 Function exception effects

A throwing signature lists the concrete error types that may escape:

```aether
FileReadResult load() throws (ConfigurationError, StorageError) {
    ...
}
```

The proposed grammar is:

```text
throws_clause := "throws" "(" error_type ("," error_type)* ")"
```

The clause follows the parameter list and precedes a function body,
expression-function marker, or interface method terminator. It applies equally
to functions, methods, constructors, interface requirements, and callable
types.

The normative lexical revision that promotes this RFC must reserve `Error` and
`throws` consistently with other built-in type names and control words. This
RFC does not alter the current profile merely by using those spellings.

Rules:

- Every listed type must be `Error` or a concrete type implementing `Error`.
- The list is a set: duplicates are invalid and source order has no semantic
  meaning.
- `Error` subsumes every concrete error; listing it with another type is
  redundant and rejected.
- A function without a `throws` clause has an empty exception effect.
- A concrete throw of `E` is allowed when the enclosing effect contains `E`
  or `Error`.
- A call is allowed when every escaping callee error is handled by an
  enclosing `try` or covered by the caller's declared effect.
- For a direct or indirect callable conversion, parameter and result types
  retain their existing exact rules. The source callable's throws set must be
  a subset of the destination callable's allowed set.
- A method implementing an interface method may throw a subset of the
  interface method's declared set, never a superset.
- Effect identity uses canonical nominal type identity across modules, not an
  import alias or short spelling.
- A public declaration cannot expose a private error type in its throws set.

Effect subtraction by catches is conservative:

- `catch (E e)` handles the exact declared effect `E`.
- `catch (Error e)` handles every remaining error.
- If an operation declares `throws (Error)`, a concrete catch cannot prove
  that all other dynamic error types are handled; the residual effect remains
  `Error`.
- Errors thrown by catch bodies are unioned into the surrounding effect.

Safety panics are absent from these sets. A `throws ()` spelling is unnecessary
and invalid; omission already means nonthrowing.

### 3.5 Throw and rethrow

The forms are:

```aether
throw errorExpression;
throw;
```

`throw expression;`:

1. evaluates the expression exactly once, left to right with all containing
   expression evaluation rules;
2. requires its static type to be `Error` or a concrete `Error` implementer;
3. establishes owned payload storage for the exception event;
4. terminates the current normal control-flow path; and
5. begins propagation to the innermost matching active `try`, or to the caller
   when no local handler matches.

Throwing a `string`, scalar, nullable, collection, callable, Vector, Matrix, or
non-error nominal value is a type error. In particular, the current
experimental `throw "message";` form is not promoted. Its explicit stable
replacement is `throw Exception("message");`.

Bare `throw;` is a rethrow:

- it is valid only lexically inside a catch body;
- it propagates the same exception event without copying the payload;
- it preserves the original dynamic type and original throw provenance;
- it is covered by the statically caught error domain (`E` for an exact catch,
  `Error` for a root catch); and
- it bypasses all later catches belonging to the same `try`.

`throw e;` inside a catch is a new throw, not a rethrow. It creates a new event
and a new throw origin after first acquiring ownership from `e`.

### 3.6 Try and catches

The forms are:

```aether
try {
    work();
} catch (ParseError error) {
    recoverParse(error);
} catch (StorageError error) {
    recoverStorage(error);
} catch (Error error) {
    report(error);
}
```

For compatibility with the existing experimental grammar:

```aether
catch (error) { ... }
```

is accepted as exact sugar for `catch (Error error)`. It is a catch-all and
must be last.

At least one catch is required. There is no `try` without `catch` in 1.x.
Each catch creates a lexical scope. Its binder cannot shadow another visible
binding and cannot escape as a borrow; an owning copy may escape through the
ordinary assignment or return rules.

### 3.7 Matching and ordering

When an exception reaches a `try`, catches are tested in source order:

- A concrete catch matches only the exact canonical dynamic type.
- `catch (Error e)` and untyped `catch (e)` match every error.
- No implicit conversion, other implemented interface, field value, message,
  or class relationship participates.
- The first match executes; no later catch is considered.
- If no catch matches, the same event propagates outward.

The typechecker rejects:

- duplicate concrete catch types;
- any catch after a root catch;
- more than one root catch; and
- a catch whose type cannot overlap the statically possible effect of the try
  body.

Concrete catch types are disjoint under this model, so their relative order is
normally documentary. Source order remains normative to permit future
compatible match categories without changing the fundamental dispatch rule.

### 3.8 Nested try/catch

Handlers are dynamically nested and lexically scoped:

- The innermost active `try` gets the first opportunity to match.
- An unmatched exception propagates to the next enclosing active `try`.
- An exception thrown by a catch body is not offered to sibling catches of the
  same `try`; it starts at the next enclosing handler.
- A nested `try` inside a catch creates a new inner handler normally.
- Rethrow skips the remaining siblings and resumes at the outer handler.

A catch begins only after cleanup of scopes exited between the throw site and
that catch. Scopes outside the `try` remain alive and are visible to the catch.
Mutations completed before the throw remain observable.

### 3.9 Return completeness and unreachable flow

`throw` and rethrow do not complete normally. They satisfy the terminating arm
of return-path analysis in the same sense as `return`.

A `try` statement can complete normally through:

- normal completion of its body; or
- normal completion of any reachable matching catch.

For a non-void function, every such normal continuation must eventually
return. An unmatched propagating path is covered by the function's throws
effect rather than a return value.

### 3.10 Interaction with `return`, `break`, and `continue`

`return`, `break`, and `continue` are normal abrupt control transfers, not
exceptions:

- they never select a catch;
- they clean every lexical scope they leave in the ordinary reverse order;
- a `return` in a try or catch returns from the function;
- a `break` or `continue` in a try or catch targets the innermost enclosing
  loop under the existing rules; and
- no transfer may jump into a try or catch body.

When returning from a catch, catch locals are cleaned first, then the active
exception event is destroyed, then outer function scopes are cleaned as
required by the return path. On rethrow, catch locals are cleaned but ownership
of the active event is transferred outward rather than destroyed.

### 3.11 Unhandled exceptions and `main`

The source entry-point rule is extended only by permitting a throws clause:

```aether
int main() throws (ApplicationError) {
    ...
}
```

This remains the same process entry for return and parameter purposes. An
explicit `main` without a throws clause must handle all checked exceptions.
Executable top-level statements normalized into a synthetic `main` must also
handle all exceptions; the compiler does not infer a hidden public throws
contract for them.

When an exception escapes `main`:

1. every live Aether frame has already completed exceptional cleanup;
2. the root runtime retains the exception event long enough to diagnose it;
3. it invokes `Error.message()` exactly once after frame cleanup;
4. it writes
   `Aether unhandled exception: <canonical-type>: <message>\n` to stderr;
5. it destroys the event; and
6. the process exits with code 1.

The returned `int` value of `main` is absent on that path. The canonical type
uses source-level module/package identity, not a mangled symbol or host class
name. Embedded bytes in the message are emitted according to the ordinary
valid-UTF-8 string contract.

Unhandled exception output is distinct from panic output even though both
currently use exit code 1. AST, IR, and native execution must agree on bytes,
stream, and status.

### 3.12 Panic versus throw

| Property | `throw` | Panic |
| --- | --- | --- |
| Purpose | exceptional but recoverable program failure | unrecoverable safety/invariant failure |
| Payload | typed `Error` value | stable panic message |
| Static effect | declared in `throws` | not in `throws` |
| Catchable | yes | no |
| Aether frame cleanup | yes | no |
| Propagation | to matching catch/caller/root | immediate fail-fast termination |
| Output | only if unhandled | `Aether panic: <message>` on stdout |
| Exit | 1 if unhandled at root | 1 |

Bounds failures, checked integer failures, allocation/length overflow, ARC
counter corruption, invalid descriptors, and other registered safety checks
remain panics. They are never converted into `Exception`.

If a panic occurs while an exception is being packaged, propagated, matched,
cleaned, diagnosed, or destroyed, panic wins immediately. No catch runs and no
further Aether cleanup is promised. Lifecycle destructors must not throw a
catchable exception; an attempted second exception during cleanup is an
internal invariant failure and terminates as panic.

### 3.13 Why `finally` is not in 1.x

`finally` is deliberately excluded:

- ARC already guarantees memory and ownership cleanup on both normal and
  exceptional paths.
- A `finally` block is arbitrary user code, not lifecycle cleanup. It requires
  rules for a return, break, continue, panic, or second throw overriding a
  pending transfer.
- It complicates checked-effect subtraction, CFG duplication, inlining, and
  exact cleanup ordering before the basic model has parity.
- It encourages using exceptions for ordinary resource protocols even though
  Aether has not designed file handles, locks, transactions, or user
  destructors.
- The strategic roadmap explicitly does not imply `finally`.

This is not an implementation-simplicity argument. It avoids prematurely
choosing a general resource-scope construct through exception syntax. A future
RFC can compare `finally`, `defer`, RAII-like owned resources, and explicit
scope guards against real library requirements.

## 4. Ownership and lifecycle

### 4.1 Core invariant

Every owning lifetime that begins successfully is ended exactly once on every
normal or exceptional path. Panic is the sole fail-fast path that does not
promise stack cleanup.

The lowerer maintains an ordered cleanup stack. Each successful initialization
registers one cleanup action. Leaving scopes executes registered actions in
strict reverse successful-initialization order, not merely reverse textual
declaration order. This distinction covers temporaries and partial
initialization.

Before cleanup starts for `throw expression`, the exception event must own its
payload. Cleanup can therefore destroy the source local without invalidating
the event.

### 4.2 Scope boundary

For an exception caught in the current function:

- clean scopes strictly inside the protected try region between the throw site
  and the handler;
- retain scopes enclosing the try, including their owning locals;
- enter the matching catch with the active event owned by hidden catch
  storage; and
- clean the event after normal catch completion.

For propagation to a caller, clean all owning locals in the callee, but not its
borrowed parameters. The caller's exceptional continuation then repeats the
same rule.

### 4.3 Locals and temporaries

- Fully initialized owning locals are destroyed in reverse registration order.
- Borrowed parameters, borrowed loop elements, and borrowed catch binders are
  not destroyed.
- Owned temporaries are registered as soon as they become live and are cleaned
  in reverse completion order unless moved into another owner.
- A moved or already destroyed slot receives no second cleanup.
- A local declared outside the try remains live for its catch. Any assignment
  committed before the throw remains visible.
- A declaration whose initializer throws never becomes a live local; only its
  completed subobjects and temporaries are rolled back.

### 4.4 Partially initialized values

Partial state must be explicit enough that every exceptional edge knows the
initialized subset:

- Struct fields initialize in declaration order and roll back the completed
  prefix in reverse order.
- Class fields initialize in declaration order; a failed constructor destroys
  the initialized fields in reverse order and frees the unpublished object.
- Array/List construction records the number of live elements. A failed
  element initialization destroys the live prefix in reverse index order,
  then releases the buffer and container.
- Collection copying and slicing follow the same live-prefix rule.
- A nullable payload is destroyed only when its present tag has been
  committed.
- Interface construction publishes no interface value until its carrier/box
  and witness state are complete.

No cleanup path may inspect uninitialized bytes as an Aether value. Static
prefixes should use specialized cleanup edges. Truly dynamic prefixes, such as
collection loops, use an explicit live-count value owned by the operation.

### 4.5 Type-specific destruction

The lifecycle registry remains authoritative:

- Scalars, payload-free enums, and capture-free function references need no
  destruction.
- A string cleanup releases its ARC handle.
- A struct destroys fields in reverse declaration order.
- An Array/List local releases the shared container handle. On last release,
  the container destroys live elements in reverse index order, then frees its
  buffer and object.
- A class local releases its object. On last release, fields are destroyed in
  reverse declaration order, then the object is freed.
- An interface backed by a class releases the carrier. An interface backed by
  a struct destroys the owned box and its payload recursively.
- Nullable cleanup delegates to the present payload only.
- Vector/Matrix cleanup follows their canonical future lifecycle descriptor;
  exceptions do not create a separate ownership model for them.

Destruction order is an internal lifecycle correctness contract. User
destructors remain absent in 1.x, so it is not a new source-level hook for
observable arbitrary code.

### 4.6 Catch event ownership

The hidden active event is a linear owner:

- catch dispatch borrows it;
- a typed catch projection borrows its payload;
- normal catch completion destroys it after catch locals;
- rethrow or unmatched propagation moves it to the outer continuation;
- explicit `throw e` creates a separately owned event before the old event is
  destroyed; and
- no phi, optimizer, or runtime helper may duplicate the event owner
  implicitly.

### 4.7 Early exits

Cleanup applies uniformly:

```text
scope end      clean exited scope, continue normally
return         acquire/move return owner, clean exited scopes, return
break          clean scopes down to loop exit, branch
continue       clean scopes down to loop latch/header, branch
throw          acquire exception owner, clean to handler/caller, propagate
rethrow        clean catch locals, move active event outward
panic          no Aether stack cleanup
```

Return values and newly thrown error values must be acquired before cleaning a
source slot on which they depend.

## 5. Control-flow model

### 5.1 Exceptional edges are real CFG edges

The CFG must distinguish:

- **normal edges**, including branch, jump, return preparation, break, and
  continue; and
- **exceptional edges**, taken only by `throw`, rethrow, or a call with a
  nonempty throws effect.

Panic is not an exceptional edge to a handler. A panic call is a no-return
process-termination edge ending in unreachable control flow.

Every potentially throwing call ends its basic block and has one normal
successor and one exceptional successor. This prevents an implicit exception
from jumping out of the middle of a block and makes dominance, liveness,
cleanup, and optimization explicit.

### 5.2 Try/catch CFG

Conceptually:

```text
                     normal
entry -> try.body ---------------> after.try
             |
             | throw/invoke failure
             v
      exceptional cleanup
             |
             v
       catch dispatch
        /     |      \
       /      |       \ unmatched
   catch.E1 catch.E2    outer cleanup/propagate
       \      /
        \    / normal
       after.try
```

Dispatch is a source-ordered chain of exact type tests followed by a root test
or unmatched propagation. A catch body's exceptional successor targets the
next outer handler, never its sibling dispatch.

### 5.3 Throw CFG

An explicit throw:

1. evaluates and owns the error payload on normal expression edges;
2. creates the internal exception event;
3. enters a cleanup ladder for the exact current cleanup stack;
4. reaches the nearest handler dispatch; or
5. ends in the function's exceptional exit when no local handler is active.

If evaluation of the throw expression itself calls a throwing function, that
callee exception propagates normally; the outer `throw` never creates its new
event.

### 5.4 Cleanup ladders

A cleanup ladder is ordinary explicit CFG. Each block performs one or more
nonthrowing lifecycle operations and transfers the same event owner to the next
block.

Sites may share a ladder only when all of these match:

- exact ordered cleanup actions;
- initialization/move state;
- active handler continuation; and
- exception event ownership state.

Otherwise the lowerer specializes or clones the ladder. It must not introduce
boolean "maybe initialized" cleanup unless partial state is genuinely dynamic.

### 5.5 Normal abrupt control flow

Return, break, and continue use normal cleanup ladders and never enter catch
dispatch. A merge after a try may have normal predecessors from:

- normal completion of the try body; and
- normal completion of each catch.

An unmatched or rethrown exception does not reach that merge.

## 6. Initial IR

### 6.1 Design alternatives

The Initial IR could represent exceptions as:

1. structured `try` regions with implicit edges;
2. explicit CFG with exceptional successors;
3. status/sum values followed by ordinary branches; or
4. backend-shaped landing pads.

Structured regions preserve syntax but hide real predecessors from lifecycle
and SSA. Status values prematurely select one lowering family. Backend landing
pads leak LLVM/platform semantics.

**Recommendation:** explicit, typed, implementation-neutral CFG before SSA.
Source-region metadata may remain for diagnostics, but it is not the source of
control-flow truth.

### 6.2 Required operations

Names below are conceptual and do not prescribe Python class names or serialized
opcode spellings.

#### `exception_pack`

```text
%event: exception_event = exception_pack %error: E
```

- `E` must implement `Error` or be `Error`.
- Produces one owned, linear exception event.
- Acquires or consumes payload ownership according to explicit lifecycle
  operands.
- May panic on allocation or internal invariant failure, but does not throw a
  catchable exception.
- Records source provenance without making it semantically observable except
  through defined diagnostics.

#### `invoke`

```text
invoke @f(args)
    normal normal.block [result %value]
    exceptional error.block [event %event]
```

- Terminates the block.
- The callee must have a nonempty checked throws effect.
- Exactly one successor executes.
- A return value exists only on the normal edge.
- An owned event exists only on the exceptional edge.
- Direct, indirect, method, interface, constructor, imported, builtin, and
  runtime calls use the same semantic form when their signature may throw.

Ordinary `call` remains valid only for a statically empty catchable-exception
effect.

#### `throw`

```text
throw %event to exceptional.target
```

- Terminates the block.
- Moves the event owner to the exceptional successor.
- Has no normal successor.

#### `rethrow` / `propagate`

```text
propagate %event
```

- Terminates the function through its exceptional exit, or transfers to an
  enclosing cleanup continuation.
- Preserves the existing event and original throw provenance.
- Does not repackage the payload.

The same semantic terminator may serve unmatched propagation and rethrow if
source provenance metadata distinguishes diagnostics where needed.

#### `exception_type_is`

```text
%matches: boolean = exception_type_is %event, E
```

- Performs an exact canonical dynamic-type comparison.
- For root `Error`, the result is always true for a valid event.
- Is nonthrowing and does not transfer ownership.
- Is the only new dynamic type test exposed to IR; it has no direct
  source-level generalization.

#### `exception_borrow`

```text
%error: borrowed E = exception_borrow %event, E
```

- Is valid only on a path where matching `E` has been established, or for
  root `Error`.
- Produces a catch-scoped borrow, never another owner.
- Cannot outlive, destroy, move, or be independently propagated without an
  explicit copy/pack operation.

#### `exception_destroy`

```text
exception_destroy %event
```

- Consumes the event on normal catch completion.
- Recursively destroys its owned payload exactly once.
- Is nonthrowing; invariant failure panics.

#### Exceptional phi/block parameter

An Initial IR handler with multiple exceptional predecessors needs an explicit
way to receive exactly one event owner. This may be represented as an
edge-argument/block-parameter primitive or as a dedicated exceptional phi.
It is semantic IR infrastructure, not a runtime ABI choice.

### 6.3 Function metadata

Each IR function and callable signature carries a canonical throws set. The
metadata is:

- part of call verification and separate compilation;
- independent of whether the backend widens the machine return type;
- included in module identity/schema versioning where internal IR is
  serialized; and
- not inferred from the presence of backend landing pads.

### 6.4 Effects

The shared instruction effect model must distinguish at least:

```text
may_throw       catchable exceptional successor
may_panic       fail-fast, uncatchable termination
reads_memory
writes_memory
allocates
has_side_effects
```

The current `may_trap` concept should not ambiguously cover both panic and
throw. An instruction with `may_throw` is never represented as a removable
ordinary instruction with a hidden edge.

## 7. Lifecycle expansion

### 7.1 Phase ordering

The approved lifecycle architecture remains:

```text
typed AST
  -> Initial IR with lexical scopes, ownership, explicit exceptional edges,
     and generic lifecycle operations
  -> Initial IR verification
  -> lifecycle expansion
  -> expanded IR verification
  -> SSA construction and verification
```

AST-to-IR lowering is the primary source of scope and initialization truth. A
dataflow pass may verify or canonicalize cleanup ladders, but post-SSA liveness
must not become the sole source of ownership semantics.

### 7.2 Inserting cleanup

For every exceptional edge, lowering computes the difference between:

- the ordered cleanup stack at the throw/invoke site; and
- the cleanup stack owned by the selected handler boundary.

It inserts generic `destroy` operations for exactly that suffix, in reverse
order, before dispatch or propagation. The event owner is threaded through the
ladder without copying.

Calls inside:

- a try body target that try's cleanup/dispatch chain;
- a catch body target the next outer chain;
- an unprotected function target the function exceptional exit chain; and
- a partial initializer target an operation-specific rollback followed by the
  surrounding chain.

### 7.3 Expanding generic lifecycle

`LifecycleExpander` continues to lower generic operations from the canonical
registry:

- trivial cleanup to no operation;
- string/class/Array/List/interface cleanup to effectful release operations;
- structs and nullable values to recursive typed cleanup;
- partial aggregates to reverse-prefix cleanup;
- event destruction to payload lifecycle plus envelope release; and
- event transfer to a move with no retain/release pair.

Expansion must preserve normal and exceptional successor identity and source
provenance. It cannot merge cleanup ladders based only on textual equality if
ownership state differs.

### 7.4 Cleanup failures

Normal cleanup is nonthrowing. ARC overflow during an ownership acquisition is
a panic under the current lifecycle contract. Underflow, double destruction,
invalid descriptors, or an exception thrown by a forbidden destructor are
panics/internal failures.

Consequently, cleanup ladders have no catchable exceptional successors of
their own. This prevents recursive "exception while unwinding" semantics in
1.x.

## 8. SSA

### 8.1 Exceptional predecessors

Exceptional edges are first-class CFG edges for:

- predecessor/successor construction;
- reachability;
- dominators and dominance frontiers;
- phi placement;
- liveness;
- loop analysis; and
- verifier exact-predecessor checks.

Analyses must never derive the graph from normal `branch`/`jump` terminators
alone after exception support is enabled.

### 8.2 Edge-defined values

`invoke` has mutually exclusive edge results:

- its ordinary result is available only on the normal edge; and
- its exception event is available only on the exceptional edge.

There are three reasonable SSA representations:

1. special edge-defined values with edge-dominance rules;
2. block arguments supplied by each terminator edge; or
3. a unique trampoline block per edge that materializes the result.

**Recommendation:** adopt block arguments or semantically equivalent
edge-defined values, with ordinary phis at multi-predecessor joins. Do not use a
hidden "current exception" global/TLS value in SSA, and do not force every call
into a status sum solely to fit the current model.

The concrete choice between block arguments and edge-defined values is an
internal SSA representation decision required before implementation.

### 8.3 Phi handling

- Phi predecessor sets include both normal and exceptional predecessors.
- A handler event phi has exactly one owned event incoming per exceptional
  predecessor and produces exactly one owner.
- Outer mutable variables observed by a catch need phis over the versions
  reaching each exceptional predecessor.
- Values local to a try and destroyed before handler entry do not flow into
  the handler.
- An invoke result may be incoming only from its normal edge.
- An invoke event may be incoming only from its exceptional edge.
- A catch binder borrow cannot be carried through a phi beyond the catch event
  lifetime. An owning copy must be made first.
- Owned phis transfer ownership from each selected edge; they do not synthesize
  retain operations.
- Phi simplification must retain the same ownership and edge-availability
  facts.

Critical edges may be split to place edge-specific cleanup, ownership
transfers, or phi copies. Splitting preserves the edge kind and provenance.

### 8.4 Dominance

Block dominance is computed over the full CFG. Adding an exceptional edge may
invalidate dominance that held in the normal-only graph.

Instruction rules:

- An instruction before an invoke dominates both successor paths in the
  ordinary block sense.
- The invoke normal result edge-dominates only the normal successor.
- The invoke event edge-dominates only the exceptional successor.
- Neither edge result is available in the invoking block before the
  terminator.
- A handler reached from several sites is not dominated by any one throw site.
- Catch dispatch definitions must dominate every matching catch use.

Post-dominance, control dependence, loop membership, and LICM must likewise use
the full graph or an explicitly documented graph projection. A normal-only
projection is never valid for transformations that can affect exceptions.

### 8.5 SSA verifier requirements

The SSA verifier must require:

- every block has exactly one valid terminator, including invoke, throw, and
  propagate;
- successor edge kinds and edge payloads agree with the terminator;
- predecessor sets include exceptional edges exactly once;
- phis have the exact real predecessor set;
- edge-defined values are used only where their edge availability dominates;
- invoke signatures, result types, and declared throws sets match;
- nonthrowing calls use ordinary call and throwing calls use invoke;
- exception events have the internal event type and contain valid `Error`
  payloads;
- exact type tests and borrows use canonical error types;
- a typed borrow is dominated by a successful match;
- each event owner is consumed exactly once on every reachable path by destroy,
  rethrow, or propagate;
- no catch borrow outlives its event;
- lifecycle-expanded releases remain ordered before exceptional transfer;
- unreachable exception blocks follow the same explicit unreachable-block
  policy as other blocks; and
- no optimizer-created path bypasses required cleanup or enters a handler
  illegally.

Verifier failure after accepted source remains an ICE, not a source diagnostic.

## 9. Optimizer contract

Exceptions add observable control flow, cleanup, dynamic dispatch, and
termination. Every pass needs an explicit policy.

### 9.1 Global legality rules

Unless proven equivalent, an optimization must not:

- delete or duplicate a potentially throwing operation;
- change which handler is active at an operation;
- change the relative order of throws, panics, IO, mutation, allocation, or
  lifecycle effects;
- move an operation across a cleanup boundary;
- turn panic into throw or throw into panic;
- change the dynamic type or ownership of an error payload;
- change whether a catch executes;
- change the original throw versus rethrow provenance used by diagnostics; or
- remove an exceptional edge without proving it infeasible.

Effect summaries are conservative by default. Unknown and FFI calls are
effectful and potentially throwing only when their declared Aether boundary
permits Aether exceptions; raw C calls themselves cannot produce an Aether
exception.

### 9.2 Dead-code elimination

Exception-aware changes are required.

- A call/instruction with `may_throw` is live even when its normal result is
  unused.
- Throws, propagates, type dispatch, event destruction, and cleanup are
  control/lifecycle effects.
- An unused catch may be removed only when all matching exceptional edges are
  proven infeasible and event ownership remains valid.
- Code after a guaranteed throw is unreachable and may be removed.
- A throwing call may become removable only after proof that it cannot throw
  and has no other observable effect.

### 9.3 Sparse conditional constant propagation

Exception-aware changes are required.

- SCCP tracks executable normal and exceptional edges independently.
- A known explicit throw marks only its exceptional edge executable.
- A proven nonthrowing invoke may make its exceptional edge unreachable.
- Exact exception type tests may fold when the packed dynamic type is known.
- Cleanup blocks on executable exceptional paths remain executable even if
  their scalar results are unused.
- CFG cleanup must repair exceptional phis and linear event ownership.

### 9.4 Constant folding and constant propagation

Exception-aware changes are required.

- Pure, nonthrowing values propagate normally when full-CFG dominance holds.
- Folding must not evaluate or suppress a throw at compile time as though it
  were a language constant.
- A constant result cannot be propagated from an invoke's normal edge onto its
  exceptional edge.
- Folding a catch type test is legal only with canonical dynamic-type proof.
- Propagation cannot reorder evaluation so that an earlier panic, throw, or
  side effect disappears.

Local and global constant propagation share these rules. SCCP additionally
owns edge executability.

### 9.5 Copy propagation

Exception-aware ownership and dominance changes are required.

- Replacements must dominate the use in the full CFG.
- Edge-defined normal results and events cannot cross to the opposite edge.
- An owner cannot be replaced with a borrowed alias.
- A catch borrow cannot be extended past event destruction.
- Event tokens are linear and cannot be duplicated by replacing multiple
  copies with one apparent source.
- Copy propagation cannot erase a lifecycle acquisition required before an
  exceptional cleanup.

Pure scalar copy propagation otherwise remains legal.

### 9.6 ARC optimization

Major exception-aware changes are required.

- Retain/release pairing must account for every normal and exceptional path.
- A retain cannot move after a call that might throw when exceptional cleanup
  needs the acquired owner.
- A release cannot move before the last use on either edge.
- Removing a pair on the normal path is illegal if the exceptional path still
  requires one side.
- Event payload ownership, interface boxes, class identity, collection
  handles, and partial aggregates participate in ownership dataflow.
- A phi transfers one selected ownership; it does not justify eliminating
  edge acquisitions without proof.
- Cleanup releases cannot be sunk after propagation.

ARC optimization should require an ownership verifier after each rewrite.
Adjacency alone is never sufficient evidence.

### 9.7 Inlining

Exception-aware changes are required.

Inlining must:

- map the callee's normal return to the caller continuation;
- map every callee exceptional exit to the caller's active handler/cleanup
  chain;
- splice callee cleanup before caller cleanup;
- preserve declared effect compatibility;
- rename event owners and exceptional phis;
- preserve original source provenance for throws and rethrows;
- respect recursion and code-size budgets; and
- rerun IR/SSA and ownership verification.

It is illegal to route an inlined callee exception around a caller catch or to
merge cleanup scopes solely because they are textually adjacent.

### 9.8 Loop-invariant code motion

Major exception-aware restrictions are required.

A potentially throwing operation cannot be hoisted out of a loop unless proof
shows:

- it executes on every original path on which the hoisted form executes;
- the same handler is active;
- the same exception/panic/side-effect ordering is preserved;
- its memory and ownership inputs are invariant; and
- moving it does not change the number of throws, allocations, retains, or
  releases.

Likewise it cannot be sunk if doing so delays or suppresses an exception.
Pure, nonthrowing arithmetic may move under the existing checked-integer and
IEEE rules.

### 9.9 Global value numbering

Exception-aware restrictions are required.

- Potentially throwing operations are not common subexpressions merely because
  operands match; eliminating the second execution can remove a throw or
  change its source location.
- Loads require memory/alias facts across exceptional edges.
- Event packing, matching borrows, ARC, allocation, and cleanup are not
  value-numbered as pure operations.
- Pure nonthrowing expressions may be numbered when full-CFG dominance and
  floating-point rules permit.

### 9.10 Bounds-check elimination

Bounds failures remain panic, not exceptions, but exception awareness is still
required.

- A check may be removed only when range/shape proof makes failure impossible.
- A check cannot be hoisted or delayed across a possible throw, mutation, IO,
  or other panic if that changes which failure is observed first.
- Catch blocks can never catch a removed or retained bounds panic.
- Array/List length facts must account for aliases and exceptional exits from
  mutations.
- Loop versioning must preserve cleanup and handler state on every version.

### 9.11 Other optimizer families

- **Dead-store elimination:** must preserve stores visible to a catch and
  stores that establish ownership needed by exceptional cleanup.
- **Algebraic simplification:** may simplify only under existing checked
  integer/IEEE rules and cannot erase evaluation of a throwing operand.
- **Phi cleanup:** must preserve edge kinds, edge availability, and ownership
  transfer.
- **Interprocedural propagation:** may narrow throws summaries only with a
  closed-world proof that does not alter the declared public contract.
- **Escape/scalar-replacement analysis:** must reconstruct partial-object
  cleanup on exceptional exits and preserve class identity.
- **Devirtualization:** may specialize `Error.message()` or interface calls
  only with exact dynamic-type proof and an equivalent exceptional/panic
  effect.

## 10. Backend-independent lowering contract

Before LLVM lowering, the compiler must have already established:

- explicit normal and exceptional CFG;
- exact cleanup on each edge;
- verified event ownership;
- canonical dynamic error identity;
- checked throws metadata; and
- panic/throw separation.

LLVM lowering is not allowed to discover missing cleanup, infer source catch
scope from landing-pad nesting, or define the source matching rules. A backend
may coalesce, encode, or outline this verified graph, but must preserve it.

## 11. LLVM lowering strategies

### 11.1 LLVM `invoke` plus landing pads/funclets

The backend maps semantic invokes to LLVM `invoke`, uses a personality
function, materializes landing pads or Windows funclets, runs cleanups, matches
types through runtime descriptors, and resumes propagation when unmatched.

Advantages:

- efficient normal path on table-based EH targets;
- LLVM understands exceptional control flow;
- natural integration with native stack unwinding and debugging;
- no mandatory source-call return widening; and
- mature optimization support when attributes are correct.

Disadvantages:

- Itanium/DWARF EH and Windows SEH use materially different LLVM forms;
- personality, LSDA/typeinfo, cleanup-pad, and foreign-exception rules become a
  substantial runtime/target surface;
- textual LLVM generation becomes more complex and version-sensitive;
- incorrect `nounwind` or cleanup construction can miscompile ownership; and
- raw C/C++ boundary behavior needs strict containment.

This strategy must not make C++ class hierarchies or platform typeinfo the
source definition of Aether matching.

### 11.2 Status-value lowering

Every throwing function returns an outcome containing either its normal result
or an owned exception event. Callers branch explicitly and run cleanup.
Concrete machine forms could use a tagged aggregate, an out parameter plus
status, or target-specific register conventions.

Advantages:

- portable to targets without native unwinding;
- explicit CFG closely matches verification and is easy to fault-inject;
- no dependency on a platform personality ABI;
- naturally prevents exceptions crossing a raw C boundary; and
- works with LLVM ordinary branches and sanitizers.

Disadvantages:

- changes internal call signatures, including indirect calls and recursion;
- increases branches, code size, and normal-path register pressure;
- complicates non-void aggregate returns and tail calls;
- requires careful optimization to avoid pervasive outcome materialization;
  and
- an accidental status ABI must not become a public source or C ABI.

### 11.3 Explicit dual-continuation/CPS lowering

A throwing function receives or targets separate normal and exceptional
continuations. This may be encoded with internal functions, block addresses
where supported, or a compiler-owned continuation convention.

Advantages:

- exceptional control is explicit;
- cleanup composition is direct; and
- it can avoid materialized sum values.

Disadvantages:

- significantly changes calling convention and debug stack shape;
- continuation representation is target-sensitive;
- indirect calls and separate compilation are difficult; and
- LLVM optimizers may not recover ordinary call/return structure.

### 11.4 Exception out-parameter plus explicit CFG

A function retains an ordinary or out-parameter normal result and writes an
owned exception handle to a caller-provided slot, returning a small status.

Advantages:

- explicit and portable;
- event ownership is visible;
- can reduce aggregate return complexity; and
- offers a straightforward future C-wrapper mapping.

Disadvantages:

- adds aliasing and initialization obligations for the out slot;
- still widens every throwing call contract;
- requires exact rules for empty/stale slots; and
- may inhibit LLVM optimization without strong attributes.

This is a status-lowering family, but it has distinct ownership and ABI
tradeoffs worth evaluating separately.

### 11.5 `setjmp`/`longjmp`-style transport

The runtime registers handlers and performs a nonlocal jump on throw. Cleanup
must be explicit before the jump or driven by compiler-generated cleanup
records.

Advantages:

- avoids platform C++ exception interoperability;
- can work on platforms with C runtime support; and
- does not require every ordinary source return value to become a tagged sum.

Disadvantages:

- local-value validity and optimizer rules around `setjmp` are subtle;
- ARC cleanup is not automatic;
- reentrancy, signals, sanitizers, and debugging are difficult;
- Windows and freestanding targets differ; and
- it is easy for implementation behavior to leak into FFI.

It should be considered only with a verified cleanup protocol and compelling
target evidence.

### 11.6 Comparison and decision policy

| Criterion | LLVM EH | Status value | Dual continuation | Exception out slot | `setjmp` family |
| --- | --- | --- | --- | --- | --- |
| Normal-path cost | usually low | branch/signature cost | convention-dependent | branch/signature cost | setup-dependent |
| Portability | target EH work | high | medium | high | medium |
| Explicit cleanup | mapped to pads | yes | yes | yes | mandatory/manual |
| Indirect calls | native signature | widened outcome | difficult | widened signature | runtime context |
| FFI containment | requires wrappers | natural | requires wrappers | natural | strict guard needed |
| LLVM complexity | high | moderate | high | moderate | high |
| Debug/unwind tooling | strongest potential | ordinary frames | altered frames | ordinary frames | weakest/variable |

No strategy is selected by this RFC. Before implementation, prototypes must
lower the same verified SSA corpus through at least LLVM EH and one explicit
status/out-slot strategy, then compare:

- correctness and sanitizer results;
- Linux x86_64 and the next planned target;
- code size and normal/throw path cost;
- indirect calls, interfaces, constructors, and aggregate returns;
- debug stack quality;
- optimization stability at clang `-O0`, `-O1`, and `-O2`; and
- FFI containment.

The selected backend may vary by target as long as observable source semantics
and the internal verified exception contract remain identical.

## 12. Runtime architecture

### 12.1 Opaque exception event

The runtime needs an opaque event capable of:

- owning an `Error` payload;
- reporting canonical dynamic nominal identity;
- borrowing the payload for exact/root catches;
- invoking the `Error.message()` contract;
- destroying or transferring the payload;
- preserving original throw provenance for debug diagnostics; and
- carrying backend-specific propagation state.

Its header, inline/boxed payload policy, reference count, type descriptor,
helper symbols, and machine layout are private and versioned internal runtime
details.

Small struct errors may be stored inline, boxed, or moved into an existing
interface box. Class errors may reuse a carrier reference. These choices must
not change value versus identity semantics, allocation observability promised
by the language, or catch behavior.

### 12.2 Runtime type descriptors

Typed catches require a canonical descriptor identity across modules. A
descriptor must provide, directly or through registered operations:

- canonical nominal ID;
- lifecycle operations for the payload;
- `Error` witness behavior;
- safe exact-match identity; and
- diagnostic source name.

Pointer equality may be used only when module loading/linking guarantees one
canonical descriptor instance. Otherwise matching must use another collision-
safe canonical identity. Hash-only equality is insufficient.

### 12.3 Propagation

Logical propagation is:

1. caller transfers an owned event to its exceptional continuation;
2. compiler-generated cleanup releases the frame's live owners;
3. the next handler performs source-ordered matching;
4. unmatched or rethrown events continue without payload copies; and
5. the root handles an event escaping `main`.

Whether the machine stack unwinds, returns statuses, or follows explicit
continuations is not observable.

### 12.4 Cleanup support

The runtime supplies only typed lifecycle primitives required by the verified
cleanup graph. It must not scan arbitrary stack memory to guess Aether owners.
Native EH may use cleanup pads; status lowering may use ordinary blocks. Both
call the same logical lifecycle operations.

Debug builds should expose counters/fault injection for:

- event creation/destruction;
- payload copy/move/destroy;
- ARC retain/release;
- partial aggregate rollback; and
- unmatched propagation depth.

These diagnostics are not a stable ABI.

### 12.5 Termination

The root runtime owns the final event while obtaining its canonical type and
message, emits the specified stderr diagnostic, destroys the event, and exits
1. If message dispatch panics, the ordinary panic contract takes over
immediately; the runtime must not attempt recursive exception formatting.

### 12.6 Interaction with panic

Panic and exception entry points must be distinct. No runtime helper may catch
panic as `Error`, synthesize an `Error` from a panic, or unwind Aether frames
for panic under this RFC.

Allocation failure while creating an exception event is a panic/platform
allocation failure according to the allocator contract, not another
catchable exception. ARC corruption during propagation is likewise panic.

## 13. FFI expectations

This RFC does not define a public ABI. It defines containment requirements for
the future C FFI.

### 13.1 C calls Aether

A raw C frame cannot participate in Aether exception propagation.

A future exported Aether function must therefore be one of:

- statically nonthrowing; or
- exposed through a generated/declared boundary wrapper that catches every
  Aether exception and converts it to an explicit C-facing error transport.

That transport may eventually be a status plus opaque owned error handle, a
caller-provided error slot, or another versioned C ABI form. It must document
who owns and destroys the handle. The ABI is not selected here.

An Aether exception must never unwind through an unaware C caller. If a runtime
guard detects such an escape, it is a boundary contract violation and must
terminate deterministically rather than continue with undefined behavior.

### 13.2 Aether calls C

A raw `extern "C"` function is nonthrowing in the Aether exception model. C
failures arrive through its declared return/status/out-parameter contract.
Signals, `longjmp` not coordinated with Aether, and process termination are not
Aether exceptions.

The Aether wrapper around a C API may inspect its status and explicitly throw
an Aether `Error`; that throw begins on the Aether side of the boundary after
C has returned.

### 13.3 C callbacks into Aether

A callback invoked by C follows the same rule as an export: it must be
nonthrowing or use a wrapper that captures the event before returning to C.
Callback storage and any captured opaque error handle follow explicit ARC
ownership.

### 13.4 C++ and other foreign exceptions

C++/Objective-C/SEH/host-language exceptions must not cross the minimal C ABI
in either direction. External adapters catch foreign exceptions in their own
language and translate them to explicit statuses before Aether code resumes.
Aether wrappers may then create an Aether error.

Panic also does not cross as a recoverable FFI value; it terminates according
to the panic contract.

## 14. Diagnostics

### 14.1 Parser

Parser diagnostics should cover:

- missing error expression after `throw`;
- tokens after bare rethrow;
- bare rethrow syntax outside a statement position;
- missing try or catch blocks;
- missing catch parentheses, type, binder, or braces;
- a typed catch with malformed type syntax;
- catch clauses separated from their try;
- `finally` with a direct "not part of Aether 1.x" diagnostic;
- malformed or empty `throws` clauses; and
- misplaced `throws` clauses on declarations/callable types.

Parser recovery should synchronize at the next catch, closing brace, or
statement boundary without inventing semantic catch scopes.

### 14.2 Name and type checking

Static diagnostics should cover:

- thrown value does not implement `Error`;
- nullable or void thrown value;
- bare rethrow outside a catch;
- duplicate, root-before-later, non-error, inaccessible, or impossible catch;
- catch binder shadowing or escape;
- missing or excessive function throws effects;
- invalid/private types in public throws sets;
- callable throws incompatibility;
- interface implementation widening the declared effect;
- unhandled checked effect in a nonthrowing function or synthetic main;
- an entry-point throws clause with invalid types;
- catch/try return completeness;
- error type identity ambiguity across imports; and
- failure of an `Error` implementation to supply the exact nonthrowing
  `string message()` method.

Diagnostics should name the throwing call/statement, the escaping canonical
error types, and the nearest candidate handler or declaration that needs an
effect update. Host exceptions must never appear.

### 14.3 Capability gate

Until every required backend and parity gate is complete, any source exception
construct or throwing signature remains rejected before Initial IR lowering by
the existing error-handling capability category. Frontend recognition does not
promote the feature.

Promotion must be atomic for the declared exception profile. There must be no
silent AST-only execution or native subset that accepts throw but omits
cleanup, typed catches, callable effects, or ownership cases.

### 14.4 Initial IR verifier

IR diagnostics are internal invariant failures and should identify:

- invalid throws metadata;
- ordinary call used for a throwing signature or invoke used incorrectly;
- malformed normal/exceptional successors;
- nonterminal throw/propagate/invoke;
- missing event edge values;
- invalid pack/match/borrow/destroy types;
- borrow without dominating match;
- event owner duplication, leak, or double consume;
- cleanup state mismatch at an exceptional join;
- destruction of uninitialized/moved storage; and
- propagation bypassing a required cleanup or handler boundary.

The verifier should retain stable internal invariant IDs when the exception
schema is implemented.

### 14.5 SSA verifier

SSA diagnostics should cover all requirements in section 8.5, with explicit
wording for edge availability versus ordinary block dominance. Dumps should
label edge kind, event arguments, throws set, and cleanup provenance so failures
can be reduced.

### 14.6 LLVM lowering

LLVM lowering must fail as an ICE, before invoking or after being rejected by
clang as appropriate, for:

- unsupported target exception strategy;
- an unlowered semantic exception operation;
- missing personality/runtime helper when native EH is selected;
- inconsistent status/out-slot signature when explicit lowering is selected;
- illegal foreign-boundary propagation;
- missing cleanup pad/block;
- descriptor/type-match inconsistency; or
- LLVM verification failure.

User source must not receive a misleading type or runtime error for compiler-
generated invalid LLVM.

### 14.7 Runtime diagnostics

Unhandled exception output, panic output, stream selection, and exit status are
part of parity tests. Debug builds may append stack/source information only
under an explicitly selected debug diagnostic mode; release output remains the
stable single line specified in section 3.11.

## 15. Testing strategy

Exception promotion requires a feature matrix, not a handful of syntax tests.

### 15.1 Positive language tests

Cover:

- built-in `Exception` and user struct/class errors;
- exact and root catches;
- untyped catch-all sugar;
- multiple catches and source ordering;
- nested try/catch;
- propagation across direct, indirect, imported, method, interface, recursive,
  and mutually recursive calls;
- constructor throws;
- rethrow versus `throw e`;
- catch normal completion and continuation;
- return, break, and continue in try/catch;
- outer-variable mutation visible in catches;
- throws-set subset compatibility for callable and interface methods;
- explicit throwing `main`; and
- UTF-8 error messages and canonical cross-module type names.

### 15.2 Negative tests

Cover every parser/type diagnostic, including:

- string/scalar/non-error/nullable throws;
- missing effect declarations;
- impossible and duplicate catches;
- catch after root;
- rethrow outside catch;
- catch binder escape as a borrow;
- throws-set callable mismatch;
- interface implementation widening;
- private error leakage;
- malformed syntax;
- unsupported `finally`; and
- current-profile capability rejection until promotion.

### 15.3 Ownership and lifecycle tests

Use deterministic debug counters and failure injection to prove:

- exactly one event and payload destruction;
- class identity survives throw/catch;
- struct payload snapshot semantics;
- string, Array, List, class, nullable, nested struct, and interface-box ARC;
- reverse local/field/element cleanup order;
- catch binder copies versus borrows;
- return/break/continue cleanup inside try and catch;
- rethrow transfers rather than copies;
- explicit new throw in a catch destroys the old event;
- partially initialized struct/class/Array/List rollback at every element or
  field boundary;
- aliases remain valid after one local unwinds;
- no cleanup for borrowed parameters;
- no leak/double free/use-after-free at exceptional phis; and
- panic during exception machinery follows fail-fast behavior.

Run native ownership tests under ASan/LSan/UBSan or target-equivalent tooling.
ARC counter overflow/corruption tests use controlled debug hooks rather than
unbounded execution.

### 15.4 CFG, IR, and verifier tests

Construct valid and invalid graphs for:

- invoke normal and exceptional edges;
- multiple exceptional predecessors;
- nested cleanup ladders;
- handler dispatch and unmatched propagation;
- partial initialization;
- edge-defined values;
- critical-edge splitting;
- full-CFG dominance;
- exact phi predecessor sets;
- event linearity; and
- unreachable exceptional blocks.

Both Python and Rust Initial IR verifier paths must receive schema fixtures and
negative corpora before Rust authority can claim exception parity.

### 15.5 AST/IR/native parity tests

For every admitted program, compare:

- stdout bytes;
- stderr bytes;
- process exit status;
- returned value where applicable;
- panic versus unhandled-exception classification;
- final controlled file bytes/effects; and
- debug-disabled diagnostic text.

Run at Aether O0/O1/O2 and clang `-O0`/`-O1`/`-O2` combinations used by CI.
The AST interpreter may use a host control signal internally, but it must
implement Aether ownership, checked effects, matching, and diagnostics rather
than leaking Python exception semantics.

### 15.6 Optimizer tests

Every optimizer family in section 9 needs:

- a positive case where a legal transformation still fires;
- a negative case where an exception edge forbids it;
- a cleanup/ARC case;
- a panic-order case;
- an exact before/after CFG assertion; and
- differential execution before and after the pass.

Randomized pass pipelines should include exception-heavy CFGs. Miscompilation
reducers must preserve catch type declarations and exceptional edges when
minimizing failures.

### 15.7 Native strategy tests

For each candidate lowering prototype:

- LLVM verifier and clang acceptance;
- deep cross-function propagation;
- direct/indirect/interface calls;
- scalar, struct, class, interface, nullable, and collection-adjacent values;
- recursion and tail positions;
- debug stack traces;
- sanitizer runs;
- allocation failure during event construction;
- process root termination;
- no unwinding across libc/raw C; and
- code-size/performance baselines.

Future Linux ARM64, macOS, and Windows ports require target-specific exception
strategy and cleanup tests rather than assuming Linux Itanium behavior.

### 15.8 Stress, fuzz, and property tests

Include:

- thousands of nested lexical scopes and handlers within compiler limits;
- deep recursion with propagation;
- large catch fan-in and many invoke predecessors;
- loops that throw on first, middle, and final iterations;
- randomized well-typed AST generation with effect checking;
- randomized valid/invalid exceptional CFG generation;
- lifecycle state-machine property tests;
- fault injection at every allocation and partial-init point;
- module graphs with aliases and same short error names;
- repeated catch/rethrow cycles; and
- long UTF-8 messages and diagnostic fallback paths.

Resource limits must produce controlled compiler/runtime diagnostics, never a
host traceback.

### 15.9 FFI tests when FFI exists

Before any public FFI promotion, test:

- nonthrowing Aether exports;
- throwing exports through wrappers;
- opaque error-handle ownership;
- C status translation to Aether throw;
- callbacks that throw;
- foreign C++ exception containment in adapter code;
- panic behavior at boundaries; and
- sanitizer verification that no unwind crosses raw C.

## 16. Promotion and rollout gates

Exceptions become part of a stable 1.x profile only when:

1. this RFC or its successor is ratified and normative spec text is written;
2. grammar, formatter, LSP, and diagnostics agree;
3. checked effects cover all call forms and modules;
4. Initial IR and its authoritative verifier model exceptional edges;
5. lifecycle cleanup is verified for every admitted native type;
6. SSA construction, dominance, phis, and verification use the full CFG;
7. every enabled optimizer passes exception-aware tests;
8. one LLVM strategy passes the native and sanitizer matrix;
9. runtime root handling and panic separation are complete;
10. AST/native parity is green;
11. the capability gate promotes the whole declared profile atomically; and
12. documentation and negative fixtures remove the old experimental contract.

An implementation that supports only message throws, only one catch, only AST
execution, or only normal-path ARC is not partial completion eligible for the
stable profile.

## 17. Open design questions

The source proposal above is complete enough for review. The following
architecture choices remain explicit rather than being smuggled in through an
implementation.

### 17.1 Required before implementation

1. **Ratification of the source model.** Confirm the `Error` interface,
   nonthrowing `message()`, checked typed throws sets, exact/root matching,
   statement-only throw, and no `finally`. If any is rejected, the dependent
   IR and callable design must be revised before coding.
2. **SSA edge-value representation.** Choose block arguments, explicit
   edge-defined values, or unique trampolines. The choice must satisfy the
   verifier and linear event ownership rules in section 8.
3. **Canonical nominal descriptor identity.** Specify collision-safe identity
   and cross-module deduplication for typed catch matching.
4. **Internal IR schema revision.** Version throws sets, edge kinds, event
   operands, borrow state, and new terminators for both Python and Rust
   verifier paths.
5. **Backend strategy for the first supported target.** Complete the
   prototype comparison in section 11.6 and select a verified LLVM lowering
   for Linux x86_64. This is an implementation choice, not a language choice.
6. **Runtime event ownership API.** Specify the private pack/borrow/match/
   transfer/destroy contract and allocator-failure path without fixing a
   public ABI.
7. **Effect integration details.** Finalize grammar placement and canonical
   serialization for function, constructor, method, interface, imported, and
   callable throws sets.
8. **Promotion slice.** Decide which concrete standard-library operations, if
   any, first use exceptions. The language model must still be implemented for
   all admitted `Error` structs/classes; result/status APIs are not
   automatically converted.
9. **Prototype target matrix.** Name the second target used to ensure the first
   lowering does not bake Linux/Itanium assumptions into semantic IR.

### 17.2 Can be postponed

1. Stable public stack-trace contents and programmatic stack inspection.
2. Error causes/chaining, suppressed errors, notes, and source attachments.
3. Catch guards, payload patterns, union catches, and general type tests.
4. `finally`, `defer`, user destructors, and general resource scope guards.
5. Throw expressions and a bottom/never type.
6. Class inheritance and exception hierarchies.
7. Resumable exceptions, restart systems, cancellation, and async interaction.
8. Cross-thread propagation and concurrency-safe event ownership.
9. Public C ABI representation and ownership of foreign error handles.
10. Per-target use of different lowering strategies after semantic parity is
    proven.
11. Inline versus boxed small error payload optimization.
12. Exception-specific performance promises or zero-cost terminology.
13. Stable debug provenance for rethrow beyond preserving the original throw
    internally.
14. Library policy for converting existing status/result APIs; such changes
    require separate API RFCs and should generally preserve expected failures
    as values.

## 18. Recommended decision summary

The proposed Aether 1.x exception model is:

- a checked, terminating control-flow effect;
- restricted to non-null values implementing built-in `Error`;
- compatible with both struct value semantics and class identity semantics;
- matched by exact dynamic nominal type or root `Error`, in source order;
- expressed with statement `throw`, bare rethrow, nested try, and multiple
  catches;
- cleaned deterministically through explicit pre-SSA exceptional CFG under
  the existing ARC lifecycle registry;
- represented in SSA with real exceptional predecessors and linear event
  ownership;
- treated as observable by every optimizer;
- lowered by a backend strategy selected later from verified alternatives;
- contained at all raw C boundaries; and
- strictly separate from fail-fast panic.

This model adds recoverable exceptional control flow without adding class
inheritance, general reflection, user destructors, `finally`, panic recovery,
or a platform unwinding ABI to Aether's language semantics.
