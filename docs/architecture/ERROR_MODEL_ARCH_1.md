# ERROR-MODEL-ARCH-1 — recoverable failure semantics

Status: **PROPOSED NORMATIVE CANDIDATE — NOT YET ADMITTED**.

This is a design, not a language admission or an implementation specification
approved for execution. MUST, MUST NOT and SHOULD below describe the candidate
contract **if admitted**. No example introduces accepted syntax today. Exact
spelling, implementation gates and internal ABI remain provisional.

Baseline: `compiler-next` at repository `ef91bfc`, reviewed 2026-09-09, through
MATH-ARCH-1/V33. The [analysis report](ERROR_MODEL_ARCH_1_REPORT.md) records
alternatives, evidence, open decisions and the recommended first vertical.
The existing [language charter](AETHER_V1_LANGUAGE_CHARTER.md) and
[semantic contract](AETHER_V1_SEMANTIC_CONTRACT.md), especially sections 4, 5
and 8.3, remain authoritative for admitted behavior. Their historical references
to legacy native exceptions do not mean `compiler-next` has recoverable calls.

## 1. Decision proposed

A function has an ordinary successful result T and either **no recoverable
failure channel** or **one statically declared error type E**. The latter is
conceptually `(A...) -> T errors E`. Execution returns exactly one of success T
or failure E; it never creates a usable T and E simultaneously.

The error type is an ordinary nominal enum or struct, or a generic parameter
instantiated with such a type. No exception base class, runtime type registry,
mandatory heap box, dynamic error interface or universal `AnyError` is required.
Payload fields use ordinary Aether types and ownership. Generic error enums and
structs preserve their canonical nominal identity and concrete payloads.

Calls MUST discharge the failure channel explicitly by local handling or
declared propagation. Recoverable return and cleanup MUST use ordinary control
flow, not platform exception unwinding. The internal result can be represented
as a discriminated sum without making `Result<T,E>` the mandatory source return
type. A no-failure function keeps an ordinary return and ordinary calling path.

This is a bounded typed return contract, not a general effect system. It says
nothing about purity, termination, IO effects or the absence of traps.

## 2. Trap and recoverable failure are separate

| Situation | Candidate rule |
|---|---|
| Checked integer overflow, division by zero, signed division overflow, invalid numeric conversion | Existing operations retain their current compile-time diagnostic or abortive runtime trap |
| Invalid indexing, empty trapping List operation | Existing `IndexOutOfBounds`/`ListEmpty` behavior remains |
| Incompatible dimensions in native mathematical operators | Existing `ShapeMismatch` behavior and guard ordering remain |
| Allocation size overflow or allocation failure | Existing allocation traps remain in V1 |
| Broken compiler/runtime invariant, invalid internal representation | Unrecoverable invariant failure; never an ordinary E |
| Malformed external text, missing file, denied permission, network failure | Expected failures in APIs that explicitly declare an appropriate E |
| Singular matrix, not positive definite, lack of convergence | Ordinary library errors when the algorithm contract promises their reporting |
| Invalid dimensions supplied to a future checked library API | May be a declared `DimensionMismatch`; that API checks before executing a trapping native operation |

Classification belongs to the **operation's contract**, not merely the numeric
condition's name. A parsing range failure can produce `ParseError.Overflow`
while an unchecked-by-the-program arithmetic expression still traps. Recoverable
failure MUST NOT silently invoke a trap because a caller omitted handling.

Handlers MUST NOT catch traps. A `try_*` arithmetic, indexing or allocation API
would need an independently admitted contract and a path that detects failure
before executing the trapping operation. It cannot wrap `llvm.trap` and resume.
No signal interception, `longjmp` recovery or trap-to-error conversion is added.

## 3. Function contract and identity

Use the following semantic notation; these are not admitted source types:

```text
FunctionContract(arguments, success_type, NoFailure)
FunctionContract(arguments, success_type, Error(error_type))
```

`NoFailure` is compiler metadata, not a new source `Never`, unit or optional
type. Absence and nullability are outside this milestone.

The contract MUST be part of signature checking, imported declaration metadata,
generic substitution and future function type identity. Thus `(A)->T` and
`(A)->T errors E` are different callable types. A `Function<(A),T>` notation, if
eventually admitted, can denote only the no-failure form unless richer contract
metadata is explicitly represented. It cannot erase E.

`FunctionId` continues to identify a declaration. Error contracts do not introduce
overloading by return/error type. Changing a declaration's error contract is an
API compatibility change even if its name and argument types are unchanged.

Future function values MUST preserve the complete contract. A no-failure
function MAY be explicitly adapted to a may-fail callable with the same
parameters and T: the adapter always produces success. This need not be a
bitwise-compatible function pointer; it can require a thunk. Implicit coercion
is deferred. A may-fail callable MUST NOT substitute for a no-failure callable
without a wrapper that handles every error, including an intentional trap policy.

Different E types are invariant for the initial design. There is no automatic
error subtyping, enum containment conversion or inferred union widening.
Transparent aliases retain canonical equality. No additional parameter/result
variance system is proposed. Actual function values and closures remain future
work: the current `TypeData` has no function variant.

All may-fail declarations, including private functions, MUST explicitly declare
E initially. Body inference MUST NOT silently enlarge a signature. A declaration
may retain E even if its current body always succeeds; optimization does not
change its externally checked contract. `main` remains the existing no-channel
`int main()` and must resolve errors into ordinary control flow/exit status.

## 4. Proposed surface direction

Prefer type-first function signatures, the word `errors`, a failure return
`fail`, explicit two-arm `handle`, and prefix `try` for later propagation sugar.
All syntax here is **provisional and currently unsupported**.

```aether
enum ParseError {
    InvalidDigit(int),
    Overflow,
    UnexpectedEnd
}

int parse_digit(int code) errors ParseError {
    if (code < 48) {
        fail ParseError.InvalidDigit(code);
    }
    if (code > 57) {
        fail ParseError.InvalidDigit(code);
    }
    return code - 48;
}

int forward(int code) errors ParseError {
    return try parse_digit(code);
}

int recover(int code) {
    handle (parse_digit(code)) {
        success(value) { return value; }
        failure(error) {
            match (error) {
                ParseError.InvalidDigit(bad) => { return 0; }
                ParseError.Overflow => { return 0; }
                ParseError.UnexpectedEnd => { return 0; }
            }
        }
    }
}
```

`success` and `failure` are conceptual handler arms, not source enum variants
or a public wrapper. Both arms are required, unique, and bind exactly T and E
respectively. Names need not be reserved globally; grammar admission is later.
The failure arm receives the entire ordinary error value and can use today's
enum matching rules to inspect it. A struct error can be inspected as a struct.

The primary handler form is a statement whose arms use ordinary statements and
returns. A later expression form can use `yield` as an expression result:

```aether
int value = handle (parse_digit(code)) {
    success(v) { yield v; }
    failure(e) { yield 0; }
};
```

This is a **new handler expression proposal**, not a claim that existing `match`
returns values. Each continuing arm must yield the same result type under
ordinary typing rules; terminating arms do not contribute to the merge. The
fallback expression executes only on failure. `yield` here has no generator or
async meaning. Its spelling and whether this convenience merits a separate
form remain open. The first implementation recommendation uses only statement
handling, not expression handlers or `try`.

## 5. Call-site obligations and scope

| Intent | Required semantic action |
|---|---|
| Handle locally | Execute a handler with success T and failure E arms |
| Propagate unchanged | `try call(...)`, permitted only when the enclosing function declares that same canonical E |
| Map error | In the failure arm construct the enclosing function's declared F and `fail` with it |
| Deliberately ignore | Use an explicit handler whose failure arm finishes normally and drops any owned error; no usable T is invented |
| Turn error into trap | In the failure arm invoke an explicitly admitted abort/trap operation; exact primitive and diagnostic kind remain open |
| Supply fallback | Produce a T only in the failure arm, after receipt of E |
| Examine payload | Bind E and use ordinary exhaustive value/ref/ref-mut enum matching or struct access |

A bare unresolved may-fail call is a static error, including as an expression
statement, discarded initializer, argument, or return operand. Discarding a
successful value does not discharge E. After resolution, ordinary unused-value
and drop rules apply; explicit deliberate ignoring is allowed, not accidental
implicit success. Recoverable calls returning a future unit-like T still need
handling; this document does not admit a unit type.

`handle (f(args))` resolves the outcome of **that call**. It is not a dynamically
installed catch region. Nested may-fail argument expressions must each explicitly
resolve their own channel. For example `handle (f(try g()))` propagates a failure
of g to the enclosing function and never invokes f; the handler sees only f's
outcome. Prefer staged locals when this scope would be hard to read.

`try` targets the enclosing function, never an implicit surrounding handler.
`fail e` also exits the enclosing function through E after required cleanup.
Calls in handler arms obey the same explicit rules, and an error from a handler
is not caught by that same handler. There is no retry or resumable failure.

## 6. Propagation and multiple sources

The typing invariant is:

```text
f : (A...) -> T errors E
enclosing g declares errors E
--------------------------------
try f(args) : T on success; return failure E from g otherwise
```

Without exact E compatibility, explicit mapping is required. No implicit
constructor, conversion trait, string conversion or runtime cast is selected.
Mapping is ordinary code and may itself fail only with explicit resolution.

```aether
enum LoadError {
    Parse(ParseError),
    IO(IOError)             // IOError denotes a future nominal library type.
}

int load_digit(int code) errors LoadError {
    handle (parse_digit(code)) {
        success(v) { return v; }
        failure(e) { fail LoadError.Parse(e); }
    }
}
```

For a function calling both `read` and `parse`, V1 should use one explicitly
named aggregate error enum such as `LoadError`, mapping each source into its
corresponding payload. Multiple entries in an `errors` clause, anonymous unions,
automatic flattening/deduplication and `AnyError` are not proposed for V1.
`Outer.Inner(e)` preserves its nominal nesting rather than being normalized
into a structural union. Library authors can deliberately discard detail when
mapping, but the compiler MUST NOT do so implicitly.

Adding an error variant affects exhaustive clients; replacing E or widening
an aggregate contract requires an explicit library compatibility decision.

## 7. Generic forwarding and modules

Explicit E type parameters are sufficient initially. A generic `errors E`
declaration carries the same E through checking and substitution. E must be a
legal outgoing error type at instantiation; this is a signature well-formedness
condition, not a new user capability or exception hierarchy. Payload storage and
ownership requirements still apply independently.

Parametric bodies MUST validate before instantiation, even if unused. They may
move E but cannot assume E is Copy, inspect an unknown variant or allocate an
implicit box. If E occurs only in the error annotation, and current local
argument matching cannot infer it, the call supplies E explicitly. Do not add
whole-program inference or infer E from whichever handler happens to exist.

Monomorphization MUST substitute E alongside parameters and T, recompute concrete
payload properties, and reject residual symbolic contracts before concrete MIR.
The existing `(FunctionId, concrete type arguments)` instance identity can still
derive the contract; a second independent E cache key is unnecessary when E is
already in those arguments. Future signature fingerprints must include the
contract to invalidate stale callers. Bootstrap mangling changes, if needed,
must remain deterministic and cannot be confused with public ABI stability.

Higher-order `map` or `with_resource` can eventually quantify a callback's
ordinary type parameter E and preserve its callable contract. This requires
function values first; it does not require effect rows, effect inference,
polymorphic handler scopes or runtime dictionaries. Handling no-failure callbacks
can use a separate helper or explicit adapter until a later admission settles it.

Module-qualified errors retain their declaring module's nominal identity.
Identically named/layout-compatible enums in different modules are different E.
Import resolution must make E available in signatures before checking calls;
no runtime module initialization or error registration is introduced. Existing
declaration-only modules, import cycles and lack of visibility/package machinery
are unchanged. Future export visibility must not expose an inaccessible E.

## 8. Ownership at evaluation and call boundaries

Recoverable failure does not roll back moves, mutations or external effects.
The following transitions MUST be explicit and independently verifiable:

| Stage | Ownership and initialization rule |
|---|---|
| Evaluate arguments | Evaluate left to right, snapshot Copy values at their evaluation point, protect borrows while later arguments evaluate |
| Evaluate a non-Copy argument | Move its root into a staged argument temporary immediately; the source is unavailable from this point |
| Later argument exits recoverably before invocation | Do not call the outer callee; destroy already staged owned arguments/temporaries in reverse construction order; do not restore moved roots; later arguments are not evaluated |
| Invoke callee | Transfer staged by-value owners into parameters once; Copy parameters copy; references borrow |
| Callee succeeds | Move T to the outgoing success slot, remove its local cleanup obligation, destroy remaining live locals/parameters, then return success |
| Callee fails | Move E to the outgoing failure slot, remove its local cleanup obligation, destroy remaining live locals/parameters and unfinished private construction, then return failure |
| Caller receives success | Only T is initialized; move it into its binding or consumer; E has no value and must not be read/dropped |
| Caller receives failure | Only E is initialized; move it into its binding or outgoing propagation slot; T has no value and must not be read/dropped |
| Handler finishes | Drop any still-owned error, success value, bindings and temporaries leaving scope exactly once |

If a later argument handles its own failure and supplies a fallback value,
argument evaluation instead completes normally: earlier staged arguments remain
live, subsequent arguments execute, and the outer call can proceed. Cleanup of
the staged arguments applies only when control abandons the pending invocation.

If a callee consumed an argument, the caller cannot use it on failure. To return
ownership on failure, the API must explicitly include that resource in E (or
choose borrowing); there is no automatic resource return. An unchanged Copy
argument remains available. Borrowed owners remain owned by the caller, but
writes through `ref mut` and earlier IO side effects can persist on failure.
The language guarantees valid ownership, not transactional contents.

Call-scoped borrows end on both outcomes subject to existing lexical provenance
rules. Pre-existing lexical borrows keep their normal duration. References or
views cannot escape through E any more than through T: initial error types must
be sized outgoing value types without stored/returned borrows, transitively.
Failure adds no lifetime system, exclusivity or LLVM `noalias` promise.

An assignment `destination = try make()` commits replacement only after a
successful RHS. On failure the assignment itself has not destroyed/replaced
the prior destination. This does not undo changes/moves performed by argument
evaluation; the existing borrow/move checker must reject incompatible uses.
If propagation exits the destination's scope, its still-owned old value receives
normal scope cleanup. Local handling can continue with that old value when its
ownership state permits it.

## 9. Partial initialization and outgoing payload construction

The inactive channel is uninitialized storage, not a dummy/default T or E.
No successful payload may escape until all its required fields are initialized.
If evaluation of a later constructor argument fails, already constructed owning
arguments remain staged temporaries and are destroyed in reverse order. This
strategy does not require general source partial-field moves.

If a later implementation constructs directly into aggregate/result storage,
it MUST track the initialized field set or a provable construction prefix and
destroy only initialized owning subobjects on failure. It must not call a
whole-value destructor on an incomplete aggregate. Collection storage similarly
requires a valid initialized prefix and one release of owned backing storage;
reserved/uninitialized slots are never values. Existing bounded native kernels
do not automatically gain recoverable edges or general partial-initialization
support from this proposal.

The same rules apply while building E. A nested recoverable failure during error
construction must itself be explicitly resolved; a failed partially built E is
not the outgoing error. Its completed subobjects are cleaned before leaving.
Once an outgoing T or E is committed, it is protected from callee cleanup and
transferred exactly once. A trap during construction remains abortive.

## 10. Deterministic cleanup and ownership merges

Cleanup is normal generated code before ordinary returns and on explicit scope
exit edges. It does not search a stack of runtime handlers. A callee cleans its
frame before returning E; a propagating caller then cleans its own frame.

On an exited scope, destroy still-live expression temporaries in reverse
construction order, then lexical locals in reverse declaration order. Nested
scopes exit from inner to outer; parameters participate in the function scope.
Existing aggregate glue destroys fields/active enum payloads in reverse
declaration order and collection elements in reverse initialized-index order.
Moved values contribute no drop. Handling locally leaves enclosing locals alive;
propagation exits every remaining function scope. Handler bindings have their
own scope and receive ordinary cleanup.

`Owned + Moved` joins remain `MaybeMoved`, with sparse conditional drop flags
only where cleanup needs them; they do not permit runtime-checked ordinary use.
Terminating failure/propagation arms do not contribute to continuing joins.
If both handler arms continue after different moves, the continuing state must
merge conservatively. Existing loop restrictions remain until separately
qualified; a new failure edge cannot silently legalize an ambiguous backedge.

Cleanup glue MUST have no recoverable failure channel. A future resource API
whose `close`/`flush` can report failure needs an explicit may-fail operation;
its non-failing destructor is separately specified and cannot silently replace
the primary error. User destructors and suppression chains are not admitted
here. If cleanup traps, execution aborts and remaining cleanup is not guaranteed.

## 11. Compiler representation candidate

HIR should retain declared E, explicit failure return, handler scopes and each
call's disposition, along with existing identities, types and source spans.
Ownership synthesis currently resides partly in HIR; it must learn the new exits
and staged temporaries before MIR lowering. Adding a backend branch alone is
insufficient.

Prefer a MIR **`CallRecoverable` terminator** over an ordinary rvalue with a
magical throwing flag. Conceptual form:

```text
CallRecoverable(instance, evaluated_args,
                success_place: T, success_block,
                failure_place: E, failure_block)

success_block:  // T initialized, E uninitialized
    ... consume T ...
failure_block:  // E initialized, T uninitialized
    ... handle E or cleanup then ReturnFailure(E) ...
```

Both destination places are compiler-created, initially uninitialized, distinct
from live arguments, and never exposed as two simultaneous source values.
The existing `Return` denotes success; a proposed `ReturnFailure` carries E.
Ordinary no-failure `Rvalue::Call` and `Return` remain. Alternative node names
such as `InvokeRecoverable` do not imply LLVM `invoke`.

Minimum verifier obligations include exact callee/argument/T/E contracts, two
valid successors, initialization only on the corresponding edge, ownership
transfer of arguments on both outcomes, correct cleanup for all exited scopes,
no inactive payload access and no failure return in a no-channel function.
MIR must retain enough evidence for SSA to validate the outcomes independently.

An internal `CallOutcome<T,E>` rvalue followed by a switch is semantically viable,
but exposing it as an ordinary aggregate too early would obscure the
edge-dependent initialization contract. Prefer the terminator for flow MIR and
choose its concrete sum/ABI representation later.

SSA must model success/error CFG and successor-specific payload definitions.
Because today's SSA has single-result instructions and ordinary phis, a future
edge-defined result representation or verified outcome plus successor-local
projection is required. Payload projections must be dominated by the correct
tag branch. Inactive payloads cannot be read merely to satisfy a phi.

At a handler expression join, only continuing arms supply the yielded T; a
propagating arm supplies no phi input. Ownership merges and conditional drop
flags must agree with MIR. Addressable payloads remain memory locals where
needed. Cleanup blocks can be shared only when live ownership states and drop
ordering agree. LLVM ultimately emits ordinary calls, branches and returns:
there is no language need for an EH personality, landing pad or unwind table.

## 12. Bootstrap ABI and cost contract

No public ABI is finalized. Start evaluation with a private discriminated-return
envelope, such as `{tag, T-storage, E-storage}`, because the backend already has
typed enum envelopes. Exactly one payload is live; physical storage for both
does not imply construction/destruction of both. This envelope is not claimed
to be an overlapping union or optimal layout. No zero-initialization of a dead
owner is a semantic requirement, and inactive bits must not cause LLVM poison
to flow into active control or payload values.

| Case | Candidate implementation and tradeoff |
|---|---|
| Small scalar T and small E | Aggregate return may fit registers; tag/branch and register pressure remain target-dependent |
| Large T | Caller result storage plus status (`sret`-style) avoids repeated large transfers; caller commits T only after success |
| Large E, small T | Hidden error out-pointer plus status/success return can preserve a compact normal result, at the cost of caller storage/addressing |
| Large T and E | Separate out-slots or aligned overlapping payload storage; union layout needs explicit alignment, active-member and initialization proofs |
| Zero-sized payload | No payload bytes need transfer, but outcome identity remains when both success and failure are possible; a payloadless enum still has its own tag |
| Monomorphized generics | Concrete T/E layouts selected per instance, without runtime dictionaries; specialization can enlarge code |
| No failure channel | Existing ordinary return; no universal status word or error slot |

Multiple logical results still need a target-supported calling convention or
aggregate/out-pointer lowering; LLVM does not promise arbitrary native return
registers. The ABI must specify storage lifetime, alignment, non-aliasing of
out-slots where required, status validity and ownership transfer symmetrically
for caller/callee. Future tail forwarding must respect cleanup and slot aliasing.

Cost transparency means no heap allocation merely for being may-fail, no runtime
type lookup, and no required dynamic dispatch or stack walk. User-chosen E fields
and diagnostics can allocate. Success can cost a tag, branch, extra registers,
stack space or aggregate traffic. Failure costs payload construction/moves,
branches and drops proportional to live resources and propagation depth.
Inlining and proof can remove redundant layers but are not semantic guarantees.
This is not a promise of literally zero instructions or faster code than native
unwinding on every workload.

## 13. Library, FFI and diagnostic boundaries

IO, parsing, serialization, lookup, networking and LinearAlgebra share this
mechanism. `lu`, `solve` and `cholesky` may declare ordinary domain enums without
compiler-recognized algorithm names. A dimension-validating `solve` does not
make the core `*` operator's shape trap catchable. Detailed algorithms, resource
types, strings, methods and STD APIs remain separate admissions.

Partial progress belongs in an explicit success structure or error payload,
according to the API. For example a write failure may carry bytes committed;
failure does not imply no bytes were written. An API that always returns both
progress and status may also choose an ordinary data product instead of the
language's mutually exclusive channel.

Foreign wrappers translate C status codes, immediately captured errno-like
state or nullable-pointer conventions into a declared nominal E. A nullable
foreign failure sentinel need not become a source nullable type. The wrapper
must distinguish sentinel failure from API-specific legitimate empty results
and release foreign resources according to the foreign contract.

Future exported Aether functions need explicit C-compatible status/out-parameter
adapters with ownership and destruction routines for transferred resources.
Neither the private envelope nor raw Aether aggregate layout is automatically
`extern C`. Raw Rust/C++ unwinding cannot cross the boundary; foreign exceptions
must be contained and translated on the foreign side. No FFI is implemented.

A returned E is a value, not an automatically captured exception stack trace.
Source spans remain compiler diagnostic/debug metadata. Optional static location
IDs, caller-provided bounded trace storage or a deliberate higher-level owned
diagnostic wrapper can add context. Capturing a backtrace after propagation
cannot reconstruct frames already returned; capture must occur at origin or
context must be explicitly appended along the path. These features need their
own cost and truncation contracts; none adds allocation to every error.

Async is not designed here. A future task completion can carry the same
success/error sum and preserve E. Cancellation, suspended-frame cleanup and
cross-thread transfer requirements remain independent decisions. Ordinary
outcome storage creates no obvious representation blocker, but is not proof
that the future concurrency semantics are solved.

## 14. Admission boundary and first vertical

Recommend **ERROR-VERTICAL-1: concrete direct recoverable return and statement
handling**. One concrete nominal E per function; existing direct calls; scalar T
and concrete nominal/owning E; explicit `fail` and two-arm `handle`; no `try`,
handler expressions, generic E forwarding, multiple-source mapping sugar,
function values, FFI or STD. Use the private tagged-envelope ABI on the current
bootstrap target and explicit MIR/SSA failure edges.

Qualification must exercise both outcomes, a non-Copy by-value parameter cleaned
on failure, an owning error transferred and dropped exactly once, handler-local
cleanup, an outer owner surviving local recovery, inactive-payload rejection,
wrong/ignored error contracts, and unchanged abortive traps. Include a cross-module direct
call to prove imported contract identity; no module feature is added. Unsupported
partial construction or control-flow forms must fail closed. Staged-argument
cleanup when a later argument exits recoverably is a required subsequent gate
before admitting nested fallible expressions; their syntax is excluded from this
first vertical, so they are not an executable first-vertical qualification case.

This validates real ownership, not only a scalar success/error tag. Propagation
can first be written manually as a failure-arm `fail e`; concise propagation and
larger return/generic cases follow after the core qualification. The report's
section 35 defines the reviewable gate in more detail. **Do not implement this
vertical as part of ERROR-MODEL-ARCH-1.**
