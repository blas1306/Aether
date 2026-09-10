# ERROR-MODEL-ARCH-1 — design analysis and report

Status: **DESIGN ONLY — NOT YET ADMITTED**. The companion
[normative candidate](ERROR_MODEL_ARCH_1.md) is a proposal, not a change to
accepted programs. All new error syntax, library signatures and IR operations
below are conceptual. Exact spelling remains provisional until implementation
admission. Reviewed against `compiler-next` at `ef91bfc` on 2026-09-09.

## 1. Problem statement

Aether needs a general contract for expected failures in file IO, parsing,
networking, serialization, lookup, user APIs and numerical algorithms. Aborting
checked operations cannot express a caller choosing recovery, fallback or
propagation. Conversely, making every runtime trap catchable would change
existing cleanup and numeric contracts.

The recommendation is a statically typed second return channel, one nominal E
per may-fail signature, explicit handling/propagation and ordinary CFG cleanup.
The successful source result remains T. A private sum representation is a
lowering choice. No implementation or admission is claimed.

The following repository evidence anchors this report. Symbol names identify
reviewed code; they are current facts, not names of implemented error support.

| Evidence | Finding relevant to this design |
|---|---|
| [compiler-next README](../../compiler-next/README.md), pipeline, grammar, ownership and bootstrap ABI sections | Isolated native pipeline, direct calls, concrete instances, ownership-aware enum matching, declaration-only modules; no function values or public ABI |
| [Language charter](AETHER_V1_LANGUAGE_CHARTER.md), identity, commitments and governance | Native general-purpose language, local inference, scientific ergonomics, inspectable costs; support requires admission and qualification |
| [Semantic contract](AETHER_V1_SEMANTIC_CONTRACT.md), §§4, 5, 8.2–8.3 and 9 | Left-to-right evaluation, replacement after successful RHS, move/drop/borrow rules, abortive traps; recoverable error choice remains open |
| [Compiler architecture](AETHER_COMPILER_ARCHITECTURE.md), §§5–7 and V11/V12/V16 confirmations | HIR→MIR→SSA→LLVM, verified boundaries, explicit ownership/cleanup, active enum payload destruction and initialized collection prefixes |
| [HIR](../../compiler-next/crates/aether-frontend/src/hir.rs): `FunctionSignature`, `FunctionInstanceInfo`, `HirCallTarget`, `HirStmtKind`, `HirBlock`, `HirDrop` | Signatures have one `return_type`; calls resolve to declarations/instances; returns and lexical exits carry cleanup lists |
| [Types](../../compiler-next/crates/aether-frontend/src/types.rs): `TypeData`, `TypeProperties`, `TypeArena` | Nominal enum/struct instances, canonical generics, structural Copy/drop/storage properties; no function type variant |
| [HIR](../../compiler-next/crates/aether-frontend/src/hir.rs): `instantiate`, `synthesize_ownership`, `MatchMode`, `merge_owner_state` | E must later enter substitution and parametric checking; existing ownership synthesis is partly in HIR, before MIR |
| [MIR](../../compiler-next/crates/aether-middle/src/mir.rs): `Rvalue::Call`, `Terminator`, `TrapKind`, `MirDropFlag`, `emit_hir_drop` | Calls are assigned rvalues; terminators have Return/Trap but no recoverable call/return; conditional cleanup becomes ordinary branches |
| [SSA](../../compiler-next/crates/aether-middle/src/ssa.rs): `SsaOp::Call`, `SsaInstruction`, `SsaTerminator`, `Phi` | One ordinary instruction result; explicit CFG, phis, memory locals and preserved drop flags |
| [LLVM backend](../../compiler-next/crates/aether-backend-llvm/src/lib.rs): call emission, `emit_drop_glue`, `emit_collection_drop`, trap emission | Direct aggregate/scalar calls, recursive active-payload drop, `llvm.trap` plus unreachable; no general recoverable unwind path |
| [Driver](../../compiler-next/crates/aether-driver/src/lib.rs): `Session` module discovery | Static transitive source imports and logical module identities; no runtime handler registration/module initialization |
| [MATH-ARCH-1 report](MATH_ARCH_1_REPORT.md), §§29–32 and 42 | Advanced decompositions are future STD work; function result/error and library boundaries precede advanced algorithms |

The semantic contract's §8.3 also mentions the **legacy** compiler's native
exceptions and typed parsing/file results. Those are historical context, not
evidence that the reconstruction already supports this proposal. Similarly,
Rust `Result` used inside the compiler is a host implementation detail.

## 2. Current trap model

`TrapKind` currently enumerates `IntegerOverflow`, `ShapeMismatch`,
`DivisionByZero`, `ConversionOutOfRange`, `DivisionOverflow`,
`AllocationSizeOverflow`, `AllocationFailure`, `IndexOutOfBounds` and `ListEmpty`.
Some checked operations carry trap metadata; explicit CFG guards lead to trap
terminators. LLVM emits `llvm.trap` and unreachable, sometimes through shared
trap blocks. Compile-time-known invalid operations can instead be diagnosed.

Traps terminate execution and do not unwind owning frames. Current mathematical
kernels can trap after some output initialization without rollback/cleanup.
Normal returns and lexical scope exits have deterministic cleanup, but there
is no recoverable success/error call boundary or arbitrary partial-initialization
cleanup facility. The proposed channel must not reinterpret an existing trap
terminator as a recoverable successor.

## 3. Recoverable-vs-trap distinction

Expected failure is an outcome promised by an API: bad text, missing file,
permission failure, failed connection, singular system or no convergence.
It must have a statically visible E. A trap denotes violation of the current
operation's checked contract or an unrecoverable runtime/invariant failure.

The same external condition can have different contracts at different layers.
A checked library `solve` may return `DimensionMismatch`; a native matrix
multiplication retains `ShapeMismatch`. A parser can detect range exhaustion
and return `ParseError.Overflow` without performing overflowing arithmetic.
This is prevalidation/dedicated checked computation, not catching the trap.

Compiler bugs, corrupt internal tags and broken ownership invariants must never
be laundered into an ordinary domain error. Resource exhaustion remains an
abortive allocation contract in the current V1 direction, even when the enclosing
function declares an unrelated recoverable error. NoFailure means no recoverable
outcome, not no traps, no effects or guaranteed termination.

## 4. Design requirements

The design must preserve explicit API contracts, exact payload types, bounded
local inference, non-Copy transfer, deterministic destruction and predictable
native costs. Callers must not silently ignore a declared channel. Existing
non-failing functions must retain ordinary result types and calls.

It must compose through modules and monomorphization, support nominal domain
errors without a runtime hierarchy, and permit later C adapters. The compiler
must represent ownership and both outcomes before LLVM. No GC, dynamic type
lookup, automatic allocation or global effect inference is required.

The comparisons below are architectural assessments for **Aether**, not claims
that the referenced languages cannot optimize or express alternatives. These
tables apply all requested criteria to eight models; sections 5–10 explain the
important tradeoffs. “Sum surface” means a direct T surface over a compiler-known
discriminated return; by itself that representation does not settle checking.

| Model | Source ergonomics / readability | Static guarantees / ignored failures | Composability / propagation |
|---|---|---|---|
| Explicit `Result<T,E>` | Visible value model; wrapping and destructuring can dominate ordinary code | Exact exclusive variants; ignoring needs a must-use rule | Excellent stored/combinable outcomes; concise only with matching or sugar |
| Tuple/status | Familiar procedural checks; repeated boilerplate | Product permits inconsistent value/error states unless extra rules; status easily ignored | Explicit repeated forwarding and dummy/default result conventions |
| Unchecked exceptions | Short success path; invisible failure exits at calls | Signatures do not bound recoverable failures | Easy broad propagation; dependencies and handler reach are difficult to audit |
| Java-style checked exceptions | Declared failures; call sites can still have nonlocal exits | Checked family is constrained, but a literal Java model also has unchecked families | Declaration growth and hierarchy-based catches complicate generic forwarding |
| Typed second channel | Ordinary T plus explicit error annotation and call disposition | Exact E, exclusive outcome, unresolved call is an error | Concise explicit propagation; nominal mapping for mixed domains |
| Sum surface | Can look like direct returns and handlers | Depends on source contract, not tag representation; no automatic must-handle guarantee | Works well with typed channel; stored outcomes need an explicit value bridge |
| CPS/error continuation | Explicit continuations but nested source is noisy | Can type continuations; single-shot/non-escape rules also needed | Flexible local composition; propagation is continuation plumbing |
| Hybrid typed channel + explicit outcome values | Ordinary code stays direct; values available when useful | Must specify bridge and prohibit silent channel erasure | Good for storing/batching outcomes; more surface concepts to teach |

| Model | Runtime representation | Happy-path cost | Failure-path cost | Code size |
|---|---|---|---|---|
| Result | Discriminated value, target-specific layout | Tag/extraction/branch or optimized equivalent | E construction, moves and ordinary cleanup | Monomorphized wrappers/combinators and cleanup branches |
| Tuple/status | Product or status plus output storage | Status check; possibly extra result/error storage | Manual branch, payload/status translation, cleanup | Repeated checks and adapters |
| Unchecked exceptions | Often runtime exception object and native EH tables; strategy is not dictated by syntax | Table-based EH can avoid per-call tag checks; ABI/optimization costs still possible | Runtime handler search, transfers and cleanup; possibly allocation | EH tables, landing pads and runtime support |
| Checked exceptions | Static declaration discipline can sit on the same unwind runtime | Same as selected runtime, not made cheaper by checking | Same runtime cost plus chosen error object representation | Runtime EH plus typed catch/translation code |
| Typed second channel | Static T-or-E returned outcome | Discriminator/branch and layout-dependent traffic | E transfer and explicit frame cleanup per propagated call | Extra CFG, drops and specialized instances |
| Sum surface | Envelope, overlap, status/out-pointer or target aggregate return | Depends on chosen ABI; surface spelling costs nothing itself | Same payload/cleanup work as represented semantics | Lowering and specialization dependent |
| CPS | Extra success/error continuations or specialized branch targets | Extra arguments, possible indirect call unless specialized | Invoke error continuation and explicit cleanup | Continuation specialization/cloning can grow code |
| Hybrid | Channel internally, explicit sum when materialized | Bridge/tag may optimize away, not guaranteed | Same drops plus any explicit conversion | Additional adapters and library combinators |

| Model | Generics | Ownership | Cleanup | FFI | Optimization |
|---|---|---|---|---|---|
| Result | Ordinary T/E monomorphization | Active payload owns; natural whole-value moves | Ordinary scope/early-return drops | Explicit C adapter | Familiar sum simplification/inlining |
| Tuple/status | Typed product generics possible; C status alone loses detail | Both fields appear live unless conditional rules added | Must cover every check/return | Natural C statuses; translate lifetimes | Easy branches but weaker validity facts |
| Unchecked exceptions | Static payload types possible; broad catches often erase precision | Payload transfer must be specified separately | Native unwind needs a complete destruction contract | Contain at foreign boundary | Nonlocal exits constrain motion; EH-aware optimizer required |
| Checked exceptions | E forwarding possible, hierarchy/sets may complicate it | Checking alone says nothing about owning payloads | Still requires a chosen unwind or CFG strategy | Declared list is not a C ABI | Checking can narrow failures; runtime strategy dominates |
| Typed second channel | Explicit E substituted with T | Consumed arguments stay consumed on either outcome | Explicit MIR exits and drops | Static status/out-slot adapters | Branch, tag, payload and dead-edge simplification |
| Sum surface | Concrete layout for each T/E | Tag selects the sole live payload | Needs semantic ownership evidence before layout | Private sum is not automatically C-compatible | ABI lowering can choose registers or memory |
| CPS | Typed E and continuation parameters | Captures, escape and exactly-once calls add proof burden | Must precede continuation transfer; cannot skip owners | Callback adapters possible but costly/awkward for ordinary C calls | Specialization can reduce to CFG; tail calls not guaranteed |
| Hybrid | Same E plus optional generic outcome type | Explicit bridges move exactly one active payload | Ordinary cleanup on both sides of bridge | Useful wrapper layer, still explicit ABI | Elide bridge with proof; retain stored outcomes when observable |

## 5. Result<T,E> analysis

An explicit sum value is a strong design: success/error exclusivity is encoded in
the type, payloads retain precision, and users can store outcomes, match them or
pass them to generic helpers. Rust's standard result documentation describes
`Ok`/`Err`, propagation via `?`, and an unused-result warning rather than an
unconditional language rejection. Those are useful references, not Aether's
required policy. [Rust result documentation](https://doc.rust-lang.org/core/result/).

For Aether, a mandatory wrapper in every may-fail signature and intermediate
binding would make failure handling conspicuous but could burden ordinary
scientific/API code. Propagation sugar reduces that burden; therefore Result is
not rejected as intrinsically unergonomic. The actual choice is where to put the
contract: in an ordinary stored value, or in the callable signature and resolved
call syntax. Prefer the latter for routine operations, with strict must-resolve
checking. Keep ordinary user-defined outcome enums available when outcomes are
the data being stored or returned. An internal Result-like sum is fully compatible
with this choice; no built-in Result or Option is admitted here.

## 6. Tuple/status analysis

A product `(T, E)` does not encode mutual exclusivity. It needs a success sentinel
for E, a validity rule for T, or a status plus out-storage convention. Requiring
a dummy T is particularly bad for non-null owned resources: zero bytes are not
a valid default owner. Adding dependent initialization rules effectively moves
the model toward the proposed discriminated outcome.

Go demonstrates concise multiple returns and a conventional `error` interface;
its documentation also illustrates partial progress accompanying an error.
Aether can learn from that partial-progress API design without adopting dynamic
error interfaces or a universal tuple convention.
[Effective Go](https://go.dev/doc/effective_go#errors).

Status returns remain useful at C boundaries and in deliberately low-level APIs.
For a general-purpose source default, repeated checks and easy accidental
discard outweigh their simple ABI. If progress and failure are simultaneously
meaningful, store progress explicitly in a domain structure/error payload rather
than inventing a usable T on a failed channel.

## 7. Unchecked-exception analysis

Unchecked exceptions provide terse happy paths but do not require callees to
advertise their recoverable outcomes. Broad catches can acquire responsibility
for failures introduced by unrelated dependency changes. This conflicts with
explicit APIs and the wish to avoid uncontrolled invisible exits.

Unchecked semantics do not logically require heap objects or unwinding, but a
C++-style runtime is a concrete implementation reference. The Itanium C++ EH ABI
describes exception storage, handler search, personality functions and cleanup
during unwinding. Such infrastructure is substantially beyond current Aether
direct calls. [Itanium C++ exception ABI](https://itanium-cxx-abi.github.io/cxx-abi/abi-eh.html).

Table-based native EH can favor the normal path by moving much machinery to
metadata and rare failure paths. It should not be dismissed as universally slow.
Nevertheless, the invisible source contract is the primary objection; dynamic
search and a new unwind lifecycle system add engineering and cost uncertainty.
Reject unchecked exceptions as V1's expected-failure mechanism.

## 8. Checked-exception analysis

Java's checked exception discipline constrains escaping checked classes through
declarations/handlers, while its unchecked classes are exempt. It uses a nominal
Throwable hierarchy; these are separate design choices from the fact of static
checking. [Java language specification, chapter 11](https://docs.oracle.com/javase/specs/jls/se22/html/jls-11.html).

The useful principle is declaration checking, not copying a dynamic hierarchy,
GC representation or transitive checked exception list. Multiple checked types
can force callers to widen lists whenever dependencies change, while broad base
classes lose precise payload contracts. Generic forwarding becomes harder if
it needs a variable set of exception subclasses rather than one E.

Aether should take static visibility and reject the hierarchy/list model as its
initial rule. A signature spelled `throws E` could still lower to ordinary tagged
returns; syntax alone does not choose the runtime. Ownership and cleanup would
still need the explicit rules in sections 18–20.

## 9. Typed second-channel analysis

One E is attached to a function contract beside T. The function either returns
T or E, and a call site explicitly resolves which continuation is possible.
This keeps successful source expressions at T without requiring a runtime
exception base type. E may be an enum with payloads, a struct, or a generic
parameter resolving to a legal nominal error type.

The key gain over unchecked exceptions is a statically bounded escape contract;
the gain over mandatory Result is the ordinary successful result surface. The
cost is compiler work: call typing, ownership synthesis, new exit handling and
verified edge-defined payloads. A simple enum library alone cannot enforce all
these call-site rules. One explicit E plus nominal mapping avoids effect rows
and hidden widening. This is the recommended semantic model.

## 10. Hybrid/lowering analysis

Surface contract, flow representation and ABI are separate decisions:

```text
T f(...) errors E       // candidate callable contract
        ↓
success/error edges    // ownership and cleanup verified in MIR/SSA
        ↓
tagged envelope or status/out-slots   // private ABI selection
```

A sum-return ABI hidden behind this surface is preferred initially. An envelope
matches existing backend aggregate handling, although current enum envelopes
physically contain the variant payload structures instead of necessarily
overlapping them. Reusing that machinery is not a claim of optimal union size.

A hybrid can later explicitly materialize an outcome into an ordinary enum for
batching, storage or a callback boundary. Today a proposed two-arm handler could
manually construct such an enum. Automatic bridges, builtin combinators and a
public wrapper protocol should wait; implicit bridge selection would obscure
whether a call is being handled or merely stored.

CPS is a viable lower-level equivalent when success/error continuations become
static block targets. As a source default it adds callback signatures, captures,
escape/single-shot rules and possible indirect calls. Tail-call optimization is
not guaranteed with pending cleanup. General CPS transformation has no necessary
benefit over explicit branches for the first vertical. `setjmp`/`longjmp` is not
a substitute: jumping across frames would bypass ownership cleanup unless an
additional lifecycle runtime were designed. Reject both as the initial runtime.

## 11. Recommended semantic model

Adopt, subject to future admission, `(A...) -> T errors E` with one ordinary
nominal E, exclusive outcomes, explicit local handling or exact-type propagation,
normal control-flow cleanup, and a private static discriminated representation.
No declaration means NoFailure, not inferred `AnyError`. Calls cannot implicitly
erase E, invent T, discard the error, or convert it to a trap.

Errors are values whose roles are specified by the call contract. There is no
mandatory message, backtrace, allocator or base-class field. Owned payloads and
module-qualified nominal identity remain exact. A semantic error channel is
not a stored optional value; nullability and Option remain wholly separate.

## 12. Recommended provisional surface syntax

Three concrete directions illustrate the same core semantics. All are
**unsupported candidate syntax**. Each group is independent and reuses these
ordinary nominal error declarations:

```aether
enum ParseError { InvalidDigit(int), Overflow, UnexpectedEnd }
enum InputError { Parse(ParseError) }
```

**A — words, prefix propagation and two-arm handlers (recommended).**

```aether
// Parse.
int parse_digit(int code) errors ParseError {
    if (code < 48) { fail ParseError.InvalidDigit(code); }
    if (code > 57) { fail ParseError.InvalidDigit(code); }
    return code - 48;
}
// Propagate.
int forward(int code) errors ParseError { return try parse_digit(code); }
// Handle.
int handled(int code) {
    handle (parse_digit(code)) {
        success(v) { return v; }
        failure(e) { return 0; }
    }
}
// Map error.
int mapped(int code) errors InputError {
    handle (parse_digit(code)) {
        success(v) { return v; }
        failure(e) { fail InputError.Parse(e); }
    }
}
// Lazy fallback expression; a later convenience, not the first vertical.
int n = handle (parse_digit(code)) {
    success(v) { yield v; }
    failure(e) { yield 0; }
};
```

This preserves Aether's type-first declarations, braces and qualified enum
construction. `errors` describes an outcome rather than implying runtime
unwinding. Prefix `try` is visible without punctuation and ordinary scientific
expressions need only mark actual may-fail calls. Two-arm handling is verbose
but makes the initial ownership branches straightforward. Expression `yield`
would add grammar beyond today's statement-only enum match and is deferred.

**B — throws declaration, postfix propagation and expression catch.**

```aether
// Parse.
int parse_digit(int code) throws ParseError {
    if (code < 48) { throw ParseError.InvalidDigit(code); }
    if (code > 57) { throw ParseError.InvalidDigit(code); }
    return code - 48;
}
// Propagate.
int forward(int code) throws ParseError { return parse_digit(code)?; }
// Handle.
int handled(int code) {
    return parse_digit(code) catch (e) { yield 0; };
}
// Map error.
int mapped(int code) throws InputError {
    return parse_digit(code) catch (e) { throw InputError.Parse(e); };
}
// Lazy fallback.
int n = parse_digit(code) catch (e) { yield 0; };
```

Here `catch` binds only the immediately protected call, not a dynamic stack
region. Success passes T through; its arm is implicit. `throw` means typed
failure return and never requires C++ unwinding. This is compact and familiar,
but postfix punctuation is easy to overlook in dense numeric expressions, and
`?` risks confusion with the separate unresolved nullability surface. Familiar
exception words could also give users the wrong trap/catch expectations.

**C — explicit propagation regions and typed recovery blocks.**

```aether
// Parse.
int parse_digit(int code) errors ParseError {
    if (code < 48) { fail ParseError.InvalidDigit(code); }
    if (code > 57) { fail ParseError.InvalidDigit(code); }
    return code - 48;
}
// Propagate: a region explicitly resolves otherwise bare ParseError calls.
int forward(int code) errors ParseError {
    propagate ParseError { return parse_digit(code); }
}
// Handle.
int handled(int code) {
    attempt ParseError { return parse_digit(code); }
    recover (e) { return 0; }
}
// Map error.
int mapped(int code) errors InputError {
    attempt ParseError { return parse_digit(code); }
    recover (e) { fail InputError.Parse(e); }
}
// Lazy fallback, expressed by the failure-only return above.
int fallback(int code) {
    attempt ParseError { return parse_digit(code); }
    recover (e) { return 7; }
}
```

These lexical regions could route unmarked calls with exact E to a declared
destination; a different E still requires resolution. Recovery bodies are
outside their own protected region. The design reduces repeated markers in
long pipelines but makes individual failure exits less visible and introduces
handler scope/region typing. Function-wide automatic propagation would amplify
that problem. Reject this region direction for the initial V1 model.

Choose A's semantic direction. It is explicit enough for systems code, uses
words rather than a growing punctuation vocabulary and does not pretend to be
native exceptions. Parser precedence, contextual keyword handling, expression
handler spelling and any eventual shorthand require separate admission.

## 13. Function-type implications

The callable identity must contain argument types/modes, T and NoFailure or E.
Current declarations and instances have `return_type` only; `TypeData` does not
yet represent function values. Future `Function<(A),T>` cannot silently denote
both contracts. A richer function type must preserve E across storage, callbacks,
imports and calls, even when a concrete body currently has no failing branch.

A no-failure function can safely adapt to the corresponding may-fail contract
by returning success, but an adapter thunk may be needed. Recommend explicit
adaptation initially, not function-pointer reinterpretation. Reverse substitution
is invalid without a handling wrapper. E remains invariant except canonical
alias equality; no enum-subset or hierarchy subtyping is required. Declaration
identity remains `FunctionId`, not a new overload family selected by E.

## 14. Call-site handling

Every may-fail call requires one resolution: two-arm local handling, unchanged
propagation under an exact E contract, or explicit mapping followed by failure
return. Fallback is local handling that constructs T lazily. Payload inspection
uses existing enum matching; no dynamic cast is needed.

Deliberate discard is a handler with a normal failure-arm exit that destroys E.
It need not fabricate a T if no value is requested. Deliberate abort is an
explicit failure-arm trap operation; its future spelling/diagnostic kind is open.
Bare call statements and ignored bindings cannot silently discharge the channel.
Once the outcome is resolved, ordinary cleanup applies to unused bindings.

Handlers bind the specific call's outcome. A nested argument call needs its own
resolution; `try` exits the enclosing function. Errors raised in an arm are not
recaught by that arm. This scope rule avoids hidden dynamically installed handlers
and must be visible in future diagnostics.

## 15. Propagation

`try f()` yields T or returns E from the enclosing function after cleanup. The
enclosing function must explicitly declare that canonical E. The same rule
applies to manual `failure(e) { fail e; }`; propagation sugar adds no semantics.
No implicit error conversion protocol or catch-all error type is proposed.

Every private and public may-fail function declares E initially, preventing
dependency changes from silently altering callers' contracts. Diagnostics should
identify the failing call, callee E, enclosing contract and the need to handle
or map. `int main()` remains non-failing in this sense and handles errors into an
ordinary exit code or an explicit abort policy. Recursive propagation uses the
same static contract, with normal cleanup in each returning frame.

## 16. Multiple error types

Consider `read` producing IOError and `parse` producing ParseError. Alternatives
are a multi-type declaration, a compiler-generated anonymous union, a named
aggregate enum or explicit conversion to a single existing E.

Prefer `enum LoadError { IO(IOError), Parse(ParseError) }` and explicit wrapping
in each failure arm. It preserves origin and payloads, has stable nominal names,
and reuses monomorphization and exhaustive matching. It can require boilerplate
and adding variants affects clients; those are visible API costs. Anonymous
union normalization raises flattening, ordering, equality and ABI questions;
multi-type lists invite effect-set machinery. Neither is needed for V1.
No automatic nested-sum flattening, hidden widening or `AnyError` is allowed.

## 17. Generic error forwarding

A generic `errors E` needs ordinary type substitution, not a runtime error
interface. The body may move an unknown E exactly once but cannot inspect it or
duplicate it without the applicable guarantee. Each instantiation must establish
that E is a sized legal outgoing nominal error type; no stored/returned borrows
or layout cycles become permitted through an error annotation.

Generic errors such as `DecodeError<Context>` retain concrete payload types.
Explicit E parameters suffice initially. If E is not inferable by existing
parameter/argument matching, supply it explicitly; do not infer an API from its
callers' handlers. Instance selection substitutes E together with T and parameters
and re-synthesizes ownership as the current monomorphizer already does for bodies.

Future `map`, parsing combinators and `with_resource` can accept a callback with
`FunctionContract(A,T,Error(E))` and forward E. This notation is metasyntax, not an
existing Aether type. Function values/closures must be admitted first. Generic
E is sufficient for the initial capability; effect rows, inferred failure sets,
effect polymorphism and higher-rank handlers are deferred. Supporting both
NoFailure and Error(E) callbacks can begin with separate helpers/adapters.

## 18. Ownership on success

Arguments evaluate left to right. Copy values must be frozen at their evaluation
point; borrowing an earlier argument protects its owner while later arguments
evaluate. Non-Copy arguments move into staged temporaries at evaluation and
transfer into callee parameters at invocation. There is no implicit copy of an
owning handle's backing allocation.

The callee constructs T completely, moves it into the outgoing success slot,
and cleans remaining owned locals/parameters before returning. The caller owns
only T and moves it into its binding or consumer. There is no E to initialize,
read or destroy. A successful payload that is explicitly ignored still receives
ordinary drop. Replacing a destination destroys the old value only after RHS
success and after all relevant ownership/provenance checks.

## 19. Ownership on failure

Failure is not a transaction. By-value arguments remain consumed even when the
callee returns E. Borrowed arguments remain owned by the caller, but permitted
mutations and external IO effects persist. An API promising ownership return
must put the resource in E; an API promising rollback must implement rollback.

If a later argument expression exits recoverably before the outer call starts,
that callee has acquired no parameters. Earlier staged argument owners are cleaned by the
caller in reverse construction order; their original roots remain moved. Later
arguments do not execute. If the call began, the callee cleans still-owned
parameters and locals before E crosses the boundary. A failure handled inside
the argument with a fallback does not abandon the pending invocation: staged
arguments remain live and evaluation continues normally.

E moves once from its constructor/local into the outgoing failure slot and then
to the caller's handler or propagation slot. Transferred E is excluded from
callee cleanup. Unconsumed handler E is destroyed on normal handler exit; mapping
may move it into a containing enum. Only the selected enum payload is live. No
T exists on failure and no generic zero/default owner is manufactured.

Partially constructed T or E cannot be dropped as a complete aggregate. Staging
constructor arguments permits cleanup of completed temporaries without general
partial-field state. Future in-place construction must track initialized fields
or prefixes and release only their owners plus any owned storage. A recoverable
failure while constructing E needs its own explicit handler/propagation and
cleans the abandoned construction. A trap still aborts.

Returning borrowed data through E remains prohibited by existing non-escape
rules. Handler-local ref/ref-mut payload bindings cannot escape their arm.
Assignment failure itself leaves the previous destination intact, although
earlier evaluated expressions may already have moved or mutated other state.
If propagation exits its scope, the old destination is then cleaned normally.

## 20. Cleanup strategy

Use explicit MIR scope-exit and failure edges, with HIR ownership synthesis
extended to enumerate the new exits and expression temporaries. Current
`HirBlock.exit_drops`, return drop lists and `HirDrop` already establish the
pattern, and `emit_hir_drop` lowers conditional flags to ordinary branches.
These are reusable mechanisms, not proof that arbitrary new failure paths
already receive correct cleanup.

Destroy expression temporaries in reverse construction order, lexical locals
in reverse declaration order, and exited scopes from inner to outer. Parameters
belong to the function scope. Existing aggregate drop order and collection
reverse initialized-prefix destruction remain. Local recovery does not destroy
still-live enclosing locals. Propagation cleans every scope being exited.

Merge Owned/Moved as MaybeMoved at continuing joins, retaining sparse drop flags
for cleanup and rejecting ordinary use of MaybeMoved roots. Terminating arms
do not join the continuation. Loop restrictions remain conservative. Shared
cleanup blocks are valid only for equivalent live-owner sets and ordering.

Cleanup itself must not report a recoverable E. A future explicit `close`/`flush`
can fail as an ordinary API, while its resource destructor needs a separate
non-failing policy. Otherwise failure during failure cleanup would demand
suppression/replacement semantics and a larger model. A trap during cleanup
aborts with no promise to finish the remaining drops.

Native unwinding could also provide deterministic destruction, but would require
platform EH integration, stack search and cleanup metadata. Branch-based cleanup
matches the current verifiable CFG and avoids that new runtime dependency.
LLVM's EH documentation describes personalities and distinct unwind constructs;
the candidate does not need those constructs for recoverable returns.
[LLVM exception handling](https://llvm.org/docs/ExceptionHandling.html).

## 21. MIR implications

Existing calls are `Rvalue::Call { callee: InstanceId, args }` assignments.
Existing terminators are Goto, Branch, Switch, Return and Trap. Prefer a proposed
`CallRecoverable` terminator with callee/arguments, T/E destination places and
success/failure successors, plus `ReturnFailure(E)`. Retain ordinary calls for
NoFailure. `InvokeRecoverable` is a possible name, but not LLVM `invoke`.

Both output places begin uninitialized; only the selected edge initializes one.
MIR verification must prove contract equality, valid destinations/successors,
argument transfer on either outcome, no inactive output use, valid outgoing
payload and cleanup on every exit. The success destination cannot be an existing
user owner destroyed before the call succeeds. Use temporaries and a later
replacement commit.

A `CallOutcome` rvalue plus tag switch is an alternative that resembles current
enum lowering. Prefer the terminator because it exposes initialization and
control together; a general product-shaped rvalue risks making both outputs
appear available. Backend-oriented sum layout can be selected after this proof.
The first implementation must extend independent verifier boundaries rather
than accept a marker checked only by LLVM emission.

## 22. SSA implications

Success/error successors become ordinary CFG blocks, but edge-defined payloads
need deliberate representation. Today's single-result `SsaInstruction` cannot
simply define two unrestricted values. Either introduce verified successor-local
definitions, or define a typed outcome and allow payload projection only in the
corresponding dominated block. No projection from inactive storage may feed a
phi or an eager `select`.

Handler-expression phis merge same-typed yielded values from continuing arms
only. Terminating propagation has no incoming value. Error payloads and drop
flags follow the same dominance/type checks as other values; address-taken
payloads can stay in memory locals. Ownership merges must preserve the MIR
proof, including conditional cleanup. No MemorySSA or runtime personality is
required merely to encode the two outcomes. Optimizations may remove an edge
only with proof and must preserve side effects and drop ordering.

## 23. LLVM/ABI candidates

| ABI candidate | Advantages | Costs and obligations |
|---|---|---|
| `{tag, T-storage, E-storage}` returned aggregate | Closest to existing typed enum envelope; simple to inspect | Physical size may include both payloads and padding; pressure/spills can affect success; only active payload may be consumed |
| Tag plus aligned overlapping T/E storage | Size near maximum payload rather than sum | New layout, alignment, initialization and projection proof; not automatically today's enum ABI |
| Caller result storage plus status (`sret`-style) | Suitable for large T; can construct directly into destination | Hidden pointer, target ABI details, delayed ownership commit, partial construction cleanup |
| Small success/status return plus hidden E out-pointer | Keeps large E off ordinary return registers | Caller stack/storage may still cost on success; E slot has conditional initialization |
| Multiple logical return components | May use efficient target register assignment | Must lower through actual target ABI/aggregate/out-parameters; no universal register guarantee |

For small scalar T/E, trial the envelope. For large success or error values,
compare aggregate traffic against out-slots; do not freeze one rule without
native measurements. Zero-sized payloads need no payload bytes, but outcome
discrimination remains if both alternatives are possible. A payloadless source
error enum can still carry its enum discriminant; it is not necessarily a ZST.

Generic T/E become concrete per instance, so layout has no runtime dictionary.
NoFailure keeps today's ABI. Dead payload bits cannot be interpreted as an owner
or let LLVM poison influence an active tag/value. Out-slots require exact
alignment, lifetime and aliasing contracts. Successful status commits one
initialized owner; failure status commits the other. Destruction is never
inferred from zero filling or physical presence of both storage regions.

The current bootstrap target/ABI is not a public Aether ABI or `extern C`.
Signature metadata must preserve E across modules; future cache fingerprints
must include it. Existing instance keys already contain explicit generic E
arguments when present. Mangling/export stability is a separate future decision,
not settled by matching LLVM aggregate syntax.

## 24. Cost model

The meaningful zero-cost aspiration is **no mandatory allocation, runtime type
lookup, dynamic dispatch or stack walk simply because a function may fail**.
Ordinary error fields, diagnostic wrappers and user algorithms may allocate.
No universal error container or status field is added to NoFailure functions.

Success can require a branch/tag, extra live registers, stack space and payload
traffic. Failure requires E construction, moves and deterministic drops, repeated
through propagating frames. Cleanup work is proportional to actual live
resources and their destruction work. Monomorphization and duplicated cleanup
can enlarge code. A large rare E can hurt success-path frame size unless the ABI
and optimizer avoid it; “rare failure” does not imply free storage.

Inlining, dead-edge elimination and scalar replacement can erase layers, but
these are opportunities rather than guaranteed instruction counts. Future
qualification should inspect O0 and optimized LLVM/native code, allocation/drop
counts, frame/layout sizes and branching for representative T/E sizes. No
benchmark or performance claim is made by this documentation milestone.

## 25. Interaction with enums

Error enums reuse nominal identity, positional payloads, qualified construction,
generic instances and exhaustive matching. Current `match` is a statement with
one arm per variant; it has no wildcard, guard, nested pattern or expression
result. The candidate handler's success/failure arms do not extend ordinary enum
matching implicitly. Pattern payload inspection can stay a nested statement.

Value matching consumes a non-Copy error root, transfers bound payloads once
and destroys omitted owning payloads. Shared/ref-mut matching preserves the root
and obeys current lexical non-escape restrictions. Ref-mut is write capability,
not uniqueness. Error structs are also suitable when the contract has one shape
of data rather than multiple variants. No special exception hierarchy is needed.

## 26. Interaction with traps

Recoverable E can be intentionally converted to a trap by an explicit handler
policy. The primitive spelling and trap diagnostic category require later
admission; do not manufacture an IntegerOverflow to represent an unrelated API
error. Before the explicit abort point, ordinary completed callees have already
cleaned up; the abort point itself does not unwind still-active caller scopes.

Trap-to-recoverable conversion is disallowed. Bounds, arithmetic and shape traps
remain uncatchable. Later `checked_add`, `try_index` or shape-validating APIs
could expose separate recoverable paths by testing the condition first, without
changing the existing operators. A try-like marker only resolves declared E;
it does not make all failures of a call recoverable.

## 27. Allocation failure policy

Keep AllocationFailure and AllocationSizeOverflow as traps for current V1
operations, including allocations performed by a may-fail function. Making every
allocation affect E would force pervasive widening and change existing APIs.

A later low-level `try_allocate`/`try_reserve` may declare a nominal allocation
error, if allocator access, size checking, partial initialization and ownership
preservation are independently specified. Constructing/reporting its error must
not require a second allocation to succeed. No allocator behavior changes here.

## 28. LinearAlgebra examples

The following is future API metasyntax, not an algorithm or STD admission:

```text
enum FactorError {
    Singular(usize), NotPositiveDefinite(usize),
    NoConvergence(usize), DimensionMismatch(usize, usize)
}
lu(MatrixView<double> A) -> LUFactors errors FactorError
solve(MatrixView<double> A, VectorView<double,Column> b)
    -> Vector<double,Column> errors FactorError
cholesky(MatrixView<double> A) -> CholeskyFactors errors FactorError
```

Each algorithm can instead choose a narrower error enum. Singular/iteration
payloads preserve a pivot or iteration count without dynamic typing. Inputs
borrow normally; partially built factors require ordinary owned-temporary cleanup.
A destructive in-place variant must document what modifications survive failure.
Dimension validation must precede trapping native operations where the library
promises recoverable mismatch. Nothing makes `lu` or `Singular` compiler intrinsics.

Exact decomposition types, numerical tolerance, precision policies, algorithm
selection and whether partial factors are returned remain future library design,
as required by [MATH-ARCH-1](MATH_ARCH_1_REPORT.md#30-future-linearalgebra-std-boundary).

## 29. IO/parsing examples

Future metasyntax exercises the same model; File, Text, methods and these APIs
are not currently admitted:

```text
File.open(path) -> File errors IOError
read(ref mut File file) -> Text errors IOError
parse(ref Text text) -> Config errors ParseError
enum LoadError { IO(IOError), Parse(ParseError) }
load_config(path) -> Config errors LoadError
```

`load_config` handles each IO failure into `LoadError.IO` and parsing failure
into `LoadError.Parse`. File ownership is acquired only after open succeeds.
On read failure the still-owned file is cleaned before load_config returns E;
on parse failure both the text and file are cleaned unless explicitly moved
into the outgoing payload. Success transfers Config and cleans the remaining
locals. Mapping does not stringify or erase the source error.

File cursor movement, partial writes and network effects are not rolled back.
If partial progress matters, declare it in the error payload or a separate
domain result. A future `with_resource` must separately decide what to report
when both the body and an explicit close fail; automatic destructor failure is
not introduced to resolve that library policy. Serialization and lookup use the
same nominal errors without special compiler support.

## 30. FFI implications

C status codes map to a nominal E in an explicit wrapper. Errno-like state must
be captured immediately after the documented failure indicator, before cleanup
or another foreign call can overwrite it. A nullable pointer can be a foreign
failure sentinel mapped to E; it does not require source Option/nullability.
Foreign APIs where null means a legitimate empty outcome need an API-specific
adapter contract, not a universal null-is-error rule.

Ownership of partial outputs, foreign buffers and handles follows the foreign
contract on both statuses. Wrappers must release or transfer those resources
explicitly. C++/Rust unwinding must be contained on the foreign side rather than
cross Aether frames. Aether export wrappers can use a fixed-width status and
explicit C-compatible output/error storage plus release functions. Generic
instances and nominal source aggregates do not acquire a stable C layout by
virtue of having E. No FFI implementation/public ABI is included.

## 31. Diagnostics/debugging

A returned error value has no automatic exception trace. Compiler spans and
debug locations identify failure creation and handling code, but do not store
runtime call history in every E. Capturing a trace later cannot recover frames
that already returned through propagation.

Optional diagnostics can use a static origin ID, caller-provided fixed-capacity
trace/context storage or an explicitly allocated higher-level error wrapper.
Bounded storage needs a visible truncation policy; owned wrappers need a visible
allocation policy. Context must be captured at origin or explicitly appended
along the propagation path. No hidden TLS stack, runtime type lookup, mandatory
formatting or mandatory allocation is part of the base model.

## 32. Future async implications

A task completion can eventually contain the same exclusive T/E outcome, with
E preserved in its static completion contract. Ordinary branches can become
state-machine transitions. This creates no obvious representation blocker.
Cancellation, suspended-owner cleanup, resource affinity and cross-thread value
transfer remain separate questions. No async syntax, scheduler or cancellation
effect is proposed or implied by the word `yield` in candidate handler syntax.

## 33. Rejected alternatives

Reject unchecked recoverable exceptions, dynamic exception base classes,
catchable current traps, universal integer statuses, implicit `AnyError`,
automatically widened error sets and mandatory public Result wrapping as the
default V1 direction. Each either hides contracts, weakens payload guarantees,
changes existing behavior or adds unnecessary surface/runtime machinery.

Also reject native EH and general CPS as the initial lowering, mandatory
backtraces, default-constructed inactive owners, implicit restoration of consumed
arguments and recoverably failing destructors. These are not necessary for the
core outcome contract. Result-like internal sums, deliberate data results and
C status adapters remain useful rather than prohibited. Absence/Option is left
untouched; it is not rejected or designed by this milestone.

## 34. Unresolved questions

| Open decision | Candidate default / admission needed |
|---|---|
| Exact grammar, contextual words and precedence | Prefer errors/fail/handle and later prefix try; parser admission required |
| Expression handlers and lazy fallback shorthand | Statement handlers first; do not implicitly turn current match into an expression |
| Abort conversion spelling and diagnostic payload | Explicit operation only; no reuse of unrelated trap categories |
| First-class function types and no-failure adaptation | Preserve full contract; explicit adapter/thunk first; no pointer reinterpretation |
| General partial initialization and fallible nested expressions | Stage temporaries; admit each control form only with lifecycle evidence |
| Final SSA edge-result encoding | Verify successor-local projections or edge definitions; backend cannot be first authority |
| Optimized internal T/E layout and out-slot convention | Begin with private envelope; measure size/alignment/traffic before specializing |
| Public export ABI, packages and visibility | Separate milestone; E is part of source contract, not a public layout guarantee |
| Optional diagnostic/context facilities | Explicit cost and capture point; no automatic trace allocation |
| Library API evolution and aggregate error variants | Explicit nominal mappings; no automatic compatibility promise for added variants |
| Higher-order E inference and non-failing callbacks | Explicit ordinary generics/adapters suffice initially; function values first |
| Future recoverable allocation/checked safety APIs | Independently specify detection, cleanup and ownership; existing traps unchanged |

These open items refine implementation/admission. They do not leave the main
choice ambiguous: one typed channel, exact declared propagation, explicit CFG
cleanup and uncatchable traps are the concrete recommendation.

## 35. Smallest implementation vertical recommendation

Recommend **ERROR-VERTICAL-1 — concrete direct recoverable return and statement
handling**, as a future, separately authorized implementation admission.

Scope: one concrete nominal E per function; scalar successful T; ordinary direct
calls; explicit `fail`; explicit success/failure statement arms. Permit concrete
owned fields in E and concrete by-value owning parameters so the vertical
actually validates lifecycle. Use existing payload enums/structs and Buffer or
Array owners rather than introducing File, strings or new resources. A direct
cross-module call checks signature identity without adding module features.

Lower to a proposed MIR recoverable call terminator and failure return, verified
SSA outcome edges, ordinary LLVM branches and a private tagged envelope on the
existing bootstrap target. Manually forwarding with a handler and `fail e` is
within scope; propagation sugar is not. Entry remains `int main()`.

Future qualification gates, **not tests added by this architecture milestone**:

1. A concrete scalar parse-like function succeeds and fails with an exact enum
   payload; a non-failing caller handles both and continues/returns correctly.
2. A may-fail function owns a by-value resource parameter and a local resource;
   success and failure release each untransferred owner once. The caller cannot
   reuse the consumed parameter on either outcome.
3. An owning E transfers through a failure return and a manual forwarding caller
   into a handler, then is consumed/matched or dropped once. Inactive success
   storage receives no drop. An enclosing caller owner survives local handling
   and is dropped only at its real scope exit.
4. Branches with a move in only one continuing arm preserve MaybeMoved and sparse
   cleanup flags; ordinary use is rejected. Terminating arms do not pollute a
   continuing join. Existing unsupported loop ownership remains rejected.
5. Wrong E, failure in a NoFailure function, unresolved calls, mismatched imported
   contracts, use-after-move, escaped error borrows and invalid handler arms fail
   before LLVM. Explicit ignore via a failure arm remains valid.
6. Independent MIR/SSA corruption checks reject swapped successor types, inactive
   payload reads, duplicate ownership/drop, missing cleanup and invalid failure
   returns. Native/debug execution and LLVM inspection verify both outcomes,
   zero channel-mandated allocations and no EH personality/landingpad.
7. Existing native/ownership/module and abortive trap regressions stay unchanged.
   Inspect both unoptimized and optimized paths; report qualification evidence
   before declaring the vertical supported.

Exclude `try`, handler expressions, arbitrary nested fallible argument syntax,
generic E forwarding, function values, automatic error mapping, multiple declared
types, FFI, STD, recoverable allocation and ABI optimization. Therefore cleanup
of an earlier staged argument when a later argument recoverably exits is a
**required next gate before admitting nested fallible expressions**, not a test
that depends on syntax excluded from this smallest vertical. Likewise large
owning T and in-place partial-result construction need later qualification.
Do not silently admit those forms through an existing expression production.

This is small enough to isolate contract/CFG/ownership correctness while testing
a real owning E. A payloadless scalar-only demo would fail to validate the
critical transfer/destruction semantics. A first vertical that includes callback
polymorphism, IO, multiple error sets or propagation sugar would obscure them.

## 36. Risks

The largest correctness risk is extending MIR while leaving HIR ownership
synthesis unaware of new exits and temporaries. Another is reading or dropping
an inactive/partially initialized payload after translating the outcome to an
ordinary LLVM aggregate. Both require independently checked phase contracts.

Large E can increase happy-path frame/register cost. Explicit mapping can become
verbose across library layers; that should motivate measured, narrow sugar
after core qualification, not automatic error widening. Users may assume `try`
catches traps or restores consumed values; diagnostics/examples must show the
actual contract. Function values, resource-close policy and public ABI are real
future work and must not be advertised as already solved.

This milestone changes only the two architecture documents. No parser, HIR,
MIR, SSA, LLVM, runtime, tests, language charter admission or semantic contract
behavior is modified. Validation is document structure, reference integrity,
internal consistency and repository change scope; compiler tests are not run
because no compiler change or executable candidate syntax is introduced.

## 37. Compatibility with Aether philosophy

The proposed model keeps static nominal payloads and explicit callable contracts,
ordinary successful T expressions, bounded local inference and deterministic
ownership. It compiles through normal native control flow with inspectable costs,
without GC, mandatory dynamic dispatch or allocations inherent in being may-fail.
Scientific algorithms and IO share the same general mechanism. Ordinary
non-failing functions stay simple, while lower-level adapters retain explicit
representation control.

It neither copies Result as a mandatory user model nor rejects its useful sum
representation. It does not inherit invisible unchecked exceptions or make
traps recoverable. The remaining implementation work follows the reconstruction's
admission rules rather than modifying them through a design document.

**Concrete next recommendation: admit and implement only ERROR-VERTICAL-1 as
bounded in section 35, proving concrete direct T/E returns, statement handling
and owning-error cleanup before adding propagation sugar, generic forwarding,
multiple error types, FFI or STD use. Do not implement it in ERROR-MODEL-ARCH-1.**
