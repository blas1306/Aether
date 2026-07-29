# Checked Exceptions Architecture Study

> Classification: **Design study — recommendation for decision closure**.
>
> Scope: the checked-versus-unchecked question only.
>
> Inputs:
> [Complete Exception Model RFC](COMPLETE_EXCEPTION_MODEL_RFC.md) and
> [Complete Exception Model Decision Log](COMPLETE_EXCEPTION_MODEL_DECISION_LOG.md).
>
> This document does not modify the working exception proposal, authorize
> implementation, select a backend, or change the Aether 1.0 language profile.

## Decision under study

This study compares two source-language contracts:

- **Checked exceptions:** every function, method, constructor, and callable
  type declares the set of catchable error types that may escape. The compiler
  enforces catch-or-declare and effect compatibility.
- **Unchecked exceptions:** functions do not declare escaping exception sets.
  Any well-typed `Error` may propagate until caught or until it reaches the
  program boundary.

Both designs retain every other working-RFC invariant: only `Error` values are
throwable, panic is distinct and uncatchable, exceptional ARC cleanup is
mandatory, catch matching is typed, and the compiler uses explicit
exception-aware IR, SSA, verification, and optimizer effects. “Unchecked”
means unchecked at source call boundaries; it does not mean untyped,
unverified, or cleanup-free.

The boolean form `throws` without a typed set is not treated as a third final
model. It obtains some call-site explicitness but still adds an exception
effect to function types while losing most type-specific contract value. Its
tradeoffs are discussed where relevant.

## 1. Evaluation criteria

### Language simplicity

How much grammar, type-system machinery, and user-visible rule interaction does
the model add? Simplicity includes the number of concepts a reader needs in
order to understand an ordinary function signature, not just the amount of
syntax typed.

### Explicitness

Can a caller determine from the source contract whether control may leave
exceptionally and which errors may escape? Explicitness also requires that the
contract be accurate across modules rather than merely inferred in one build.

### API evolution

What happens when an implementation begins throwing a new error, stops
throwing an old one, wraps a dependency, or changes its recovery boundary? A
good model should make deliberate breaking changes visible without turning
ordinary implementation evolution into unnecessary source churn.

### Compiler complexity

What permanent work enters parsing, name resolution, type checking, callable
compatibility, interface conformance, module metadata, incremental analysis,
diagnostics, and verification? Implementation effort alone does not decide the
language design, but permanent semantic complexity is a maintainability cost.

### Runtime implications

Does the source choice constrain event representation, calling conventions,
unwinding, cleanup, or FFI? Runtime cost must be separated from opportunities
for static optimization; neither model is entitled to leak one backend
strategy into semantics.

### Tooling

Can the LSP, documentation generator, API browser, formatter, and diagnostics
give useful and stable information? The study distinguishes compiler-enforced
facts from advisory whole-program inference.

### Readability

Does code make its meaningful failure behavior visible at the right level?
Both hidden exceptions and long propagated throws lists can obscure intent.
The relevant measure is signal, not annotation count.

### Long-term maintainability

How does the model scale through interfaces, higher-order functions, modules,
future generics, FFI, and separate compilation? The decision should avoid a
local convenience that requires a second redesign when those features mature.

### Consistency with Aether philosophy

The model should support explicit semantics, correctness over optimization,
end-to-end promotion, ARC ownership, verified compiler boundaries, and no
implementation detail in language semantics. It should also respect the
roadmap's preference for result/status values for expected failures and its
separation of catchable exceptions from panic.

### Decision weighting

For Aether, semantic coherence, composition, and long-term maintainability
weigh more heavily than either annotation convenience or the ease of one
backend. Runtime cleanup correctness is a mandatory baseline under both
models, not a point awarded to one. Optimizer precision is valuable but cannot
by itself justify a source-language contract.

## 2. Checked exceptions

### Model

The working RFC's checked design uses typed throws sets:

```aether
Configuration load(string path)
    throws (ConfigurationError, StorageError) {
    ...
}
```

A call must occur inside a handler that discharges the possible errors or in a
declaration whose own throws set covers them. A missing throws clause denotes
a nonthrowing catchable-exception effect. Panic is still possible and is not
declared.

### Advantages

1. **Failure is part of the static API.** A signature identifies both the
   normal result and the exceptional results that the implementation commits
   to exposing.
2. **Catch-or-declare prevents accidental omission.** A new throwing call
   cannot be added to a nonthrowing function without either handling it or
   changing the surrounding contract.
3. **Separate compilation remains precise.** Importers need only the public
   signature, not the callee body, to know its exception effect.
4. **Interfaces can bound implementations.** An implementation cannot
   surprise callers with an error outside the interface requirement.
5. **Tooling obtains authoritative facts.** API views, completion, call
   hierarchy, and diagnostics can show exact declared propagation rather than
   best-effort inference.
6. **FFI eligibility is visible.** A declaration with an empty effect is a
   statically obvious candidate for a raw nonthrowing boundary.
7. **Optimization summaries are available.** The compiler knows from a
   signature when no catchable exceptional edge is possible, although runtime
   panics and other effects remain.
8. **API changes are deliberate.** Adding an escaping error is a source
   contract change rather than a silent behavioral expansion.

### Disadvantages

1. **Throws sets spread through abstraction layers.** A low-level dependency
   change can force signatures to change through every forwarding layer even
   when those layers do not conceptually expose the dependency.
2. **Exact sets are fragile.** Libraries tend either to translate errors at
   every boundary or widen to root `Error`, at which point much of the promised
   precision is lost.
3. **The function type system grows permanently.** Compatibility needs
   subset/subtyping rules, canonical set identity, module visibility rules,
   and serialization.
4. **Higher-order composition needs effect polymorphism.** A function that
   merely invokes a callback must express “throws exactly what the callback
   throws,” not a fixed local set. A broad `Error` loses precision; a
   `rethrows`-like special case or generic error parameter adds another
   language mechanism.
5. **Diagnostics can cascade.** One new throw can produce errors across many
   callers, interface implementations, callable assignments, and module
   boundaries before the user reaches the true design decision.
6. **Implementation details can leak into public contracts.** A change from
   one storage provider to another can expose a new nominal error even when the
   public operation has not conceptually changed.
7. **Constructors and initialization become effect-heavy.** Every factory,
   collection initialization, and higher-level constructor that delegates to a
   throwing constructor must participate.
8. **Future general effects are pre-committed.** Aether would add a
   throws-specific effect system before deciding whether IO, allocation,
   mutation, async cancellation, or other effects should share a unified
   model.

### Examples

Handling a checked error:

```aether
try {
    Configuration config = load("app.conf");
    use(config);
} catch (ConfigurationError error) {
    report(error);
} catch (StorageError error) {
    report(error);
}
```

Propagating it:

```aether
Application prepare()
    throws (ConfigurationError, StorageError) {
    Configuration config = load("app.conf");
    return Application(config);
}
```

An abstraction must either preserve, translate, or widen the dependency's set:

```aether
interface Loader {
    Configuration load(string path)
        throws (ConfigurationError, StorageError);
}
```

### Interaction with language features

#### Interfaces

Throws sets become part of interface requirements. The sound compatibility
rule is effect covariance/subsetting: an implementation may throw fewer
declared errors, never more. A class implementing two compatible interface
requirements needs an effect acceptable to both. An interface that hides a
provider must translate provider errors or expose them, making error
abstraction a mandatory API design task.

#### Function types

Throwingness and the error set become part of structural callable identity. A
nonthrowing function can safely substitute for a throwing one; a function
throwing a subset can substitute for one allowing a superset. Equality,
overload resolution, mangling/schema identity, imports, and indirect-call
verification must all agree on this rule.

#### Constructors

A constructor must declare errors from field initialization and constructor
logic. Callers cannot create the type without handling or propagating the
effect. This is precise, but it makes representation changes potentially
source-visible unless constructors translate errors into stable public types.

#### Methods

Methods follow the same rules as functions, with additional interface
compatibility. A method changed from nonthrowing to throwing is a source
contract change. Overrides are not currently relevant because Aether rejects
class inheritance.

#### Callbacks

Callback types need throws sets. A callback-accepting API must decide whether
it handles callback errors, propagates them, or accepts only nonthrowing
callbacks. This is useful precision but makes callback signatures less
interchangeable.

#### Higher-order functions

Transparent propagation requires an effect parameter or a `rethrows`-like
rule:

```text
R apply(R(P) throws E callback, P value) throws E
```

Without such a mechanism, higher-order utilities must use root `Error`,
enumerate a closed set, or reject throwing callbacks. Each option either loses
precision or limits composition.

#### Future generics

Generic code needs to quantify over normal types and possibly error effects.
An error parameter must support constraints, inference, substitution,
specialization/erasure, associated error types, and diagnostics. This may be a
valid future effect system, but checked exceptions force Aether to reserve that
design space now.

#### Modules

Throws sets use canonical nominal identity. Public functions cannot expose
private error types. Re-exporting or wrapping declarations must preserve
visibility and set compatibility. A new exported error is a source API change
even if the machine ABI is unchanged.

#### FFI

Checked effects help reject a raw C export that may throw. Wrappers still need
an explicit foreign error transport and must catch root `Error`, because a C
ABI cannot encode an open Aether throws set implicitly. Imported C functions
remain nonthrowing in the Aether exception sense and report failures through
their declared C result contract.

### Long-term implications

Checked exceptions make exception behavior a first-class static effect and
therefore establish useful discipline early. They also create a permanent
exception-specific dimension in every callable abstraction. Once libraries
publish typed sets, simplifying to unchecked exceptions later leaves
annotations, compatibility rules, and API expectations to migrate. Conversely,
the compiler can always widen a precise set to `Error`, but that escape hatch
reduces the value that justified exact checked sets.

## 3. Unchecked exceptions

### Model

The unchecked design removes source throws clauses:

```aether
Configuration load(string path) {
    ...
    throw ConfigurationError(...);
}
```

The thrown expression is still statically required to implement `Error`.
Typed catches, bare rethrow, ARC cleanup, explicit exceptional CFG, and
unhandled-root behavior remain unchanged. A caller may handle an error, but
the compiler does not require catch-or-declare.

### Advantages

1. **Function signatures retain one purpose.** They describe parameters,
   results, ownership conventions, and callable identity without a second
   nominal result channel.
2. **Abstraction boundaries can change internally.** Replacing a provider or
   adding a new exceptional failure does not force mechanical signature changes
   through forwarding layers.
3. **Interfaces remain focused on behavior.** Implementations can evolve their
   exceptional failures without violating type conformance.
4. **Higher-order functions compose naturally.** A callback can propagate an
   error without `rethrows`, effect variables, or root-set widening.
5. **Future generics remain uncommitted.** Aether can design a general effect
   system later from evidence instead of embedding one exception-specific
   effect first.
6. **Modules expose fewer private implementation types.** Provider-specific
   errors need not appear in every public wrapper's signature.
7. **Source evolution is less brittle.** Adding or translating an exception
   does not invalidate callable assignments or interface implementations.
8. **The runtime architecture remains fully explicit.** Source uncheckedness
   does not remove compiler-owned `may_throw` effects, cleanup, or verification.

### Disadvantages

1. **The call contract is incomplete at the signature.** A reader cannot know
   from a function declaration whether it may throw or which errors may escape.
2. **Missed recovery is not a compile-time error.** A caller can unintentionally
   allow a recoverable error to reach `main`.
3. **API documentation carries more responsibility.** Public libraries need
   accurate exception documentation and compatibility policy without compiler
   enforcement.
4. **Tooling facts are advisory.** Whole-program analysis can show likely
   thrown types, but indirect calls, separate modules, FFI, and future dynamic
   linkage require conservative “may throw” answers.
5. **Unknown calls are conservative internally.** The optimizer and backend
   need verified internal summaries or must assume an exceptional edge.
6. **FFI safety cannot rely on ordinary signatures.** Raw exports and callbacks
   require explicit boundary wrappers or a separate nonthrowing boundary
   declaration.
7. **Behavior can expand compatibly in the type system but incompatibly in
   practice.** A new escaping error may surprise callers even though they still
   compile.
8. **Broad catches may hide evolution.** A root catch can continue compiling
   while silently handling a newly introduced error in an inappropriate way.

### Examples

The handling code is unchanged:

```aether
try {
    Configuration config = load("app.conf");
    use(config);
} catch (ConfigurationError error) {
    recover(error);
} catch (Error error) {
    report(error);
}
```

Transparent propagation needs no declaration:

```aether
Application prepare() {
    Configuration config = load("app.conf");
    return Application(config);
}
```

The absence of syntax does not claim that `prepare` is nonthrowing. It means
exception behavior is not part of its source type.

### Interaction with language features

#### Interfaces

Interface methods carry no exception effect, so implementation conformance is
unaffected by error evolution. The interface documentation should define
stable conceptual errors where callers are expected to recover. Implementations
may translate provider errors to maintain that behavioral contract, but the
typechecker does not force translation.

#### Function types

Throwing and nonthrowing functions have the same source function type when
parameters and result match. Indirect calls are conservatively potentially
throwing in internal compiler analysis. No effect subset relation enters
callable assignment.

#### Constructors

Constructors may throw without changing the nominal type's callable signature.
This keeps representation evolution private but makes constructor failure
discoverable only from documentation, diagnostics at runtime, or tool
analysis.

#### Methods

Methods behave like functions. Adding a possible exception does not break
interface conformance or callable identity. Public API policy, not the type
system, determines whether it is a compatible behavioral change.

#### Callbacks

Any callback may throw. A callback consumer that cannot tolerate propagation
must establish a root catch around invocation. This is easy to compose but
requires explicit boundary discipline because the function type does not prove
nonthrowing behavior.

#### Higher-order functions

No exception effect variable or `rethrows` rule is needed. Errors propagate
through the higher-order function like errors through any other call. The cost
is that the type system cannot distinguish a callback consumer that is
guaranteed not to throw.

#### Future generics

Generic parameters and constraints need no exception dimension. A future
general effect system could add an explicit nonthrowing or throwing constraint,
but doing so would be a new language decision and probably a major-version
feature. The unchecked model does not pretend that current inference is a
stable effect contract.

#### Modules

Module signatures do not serialize throws sets or reject private escaping error
types. Tools may publish documented exception behavior and inferred summaries,
but import correctness does not depend on those summaries.

#### FFI

FFI containment must be structural: raw C exports are generated only through a
boundary form that catches all Aether exceptions and converts them to explicit
foreign error transport, or they are statically proven nonthrowing by a
separate boundary rule. No exception may cross raw C merely because analysis
failed to notice it. Imported C failures remain values/statuses until an
Aether wrapper explicitly throws.

### Long-term implications

Unchecked exceptions keep exceptional propagation out of the source function
type system. That reduces coupling and makes higher-order/generic growth
simpler, but it permanently accepts that some control effects are not visible
in ordinary signatures. Strong documentation, LSP inference, top-level
diagnostics, tests, and FFI wrappers become necessary governance rather than
optional polish.

## 4. Comparison

| Dimension | Checked typed exceptions | Unchecked exceptions |
| --- | --- | --- |
| Usability | Catch-or-declare prevents omission but creates propagation and translation work | Calls stay concise; recovery is optional and can be missed |
| Language simplicity | Adds throws grammar, set algebra, effect subtyping, and visibility rules | Adds no exception dimension to signatures |
| Explicitness | Authoritative escaping-error contract at every declaration | Throw/catch semantics are explicit, but call effects are not |
| Readability | High signal when sets stay small and conceptual; noise when sets mirror dependencies | Clean signatures; readers must consult docs or tooling for failures |
| Compiler implementation | Requires effect checking across every callable form and module | Requires conservative internal effects but no source effect type system |
| Diagnostics | Can pinpoint unhandled effects and incompatible declarations; cascades are possible | Cannot require handling; can offer advisory flow and documentation warnings |
| Optimization | Declared empty sets provide modular nonthrowing facts | Needs internal summaries/proofs; unknown calls remain conservative |
| Runtime implications | No required transport choice; may permit specialized nonthrowing conventions | No required transport choice; uniform/conservative conventions may be easier |
| Binary compatibility | Changing nonthrowing to throwing may change internal/public call convention; changing error set may change metadata | Function type is stable, though implementation behavior and wrappers can change |
| Source compatibility | Adding an escaping error is intentionally breaking | Adding an escaping error compiles but can be behaviorally breaking |
| API stability | Compiler enforces declared sets; dependency types can leak and cause churn | Stable function types; exception contracts depend on documentation and policy |
| Interfaces | Effect subset rules protect callers but constrain implementations | No effect compatibility; implementations can surprise callers |
| Higher-order code | Needs effect parameters, widening, or `rethrows` | Propagates naturally but cannot prove nonthrowing callbacks |
| Future generics | Likely needs generic effects or associated error types | No immediate coupling; a later effect system is harder to add compatibly |
| FFI | Signature helps classify exports, but wrappers are still mandatory | Boundary forms/wrappers are the sole authority |
| Maintenance cost | More compiler/type-system cost and API-set curation; less undocumented propagation | Less type-system cost; more documentation, testing, and boundary discipline |

### Usability and readability

Checked exceptions optimize for callers who must make a recovery decision at
each propagation boundary. Unchecked exceptions optimize for callers that
usually allow exceptional failure to rise to a subsystem boundary. Because
Aether already directs expected, frequently handled failures into
result/status values, its remaining exceptions should be relatively sparse.
That lowers the benefit of mandatory catch-or-declare and raises the relative
visibility of annotation propagation.

### Diagnostics and optimization

Checked declarations offer stronger call-site diagnostics and modular
optimization facts. They do not remove the need for explicit exceptional CFG,
ARC cleanup, or verification. Unchecked exceptions lose source-authoritative
sets, but the compiler still must distinguish `may_throw` from `may_panic`,
derive conservative summaries, and verify every edge. Advisory thrown-type
analysis can improve tooling without becoming a compatibility contract.

### Binary, source, and API compatibility

Typed throws sets make source incompatibility deliberate: adding an error
forces callers to respond. That protects strict API contracts but can expose
implementation churn. Unchecked exceptions keep function and interface types
stable, but a newly escaping error remains a behavioral compatibility concern.
Neither model eliminates the need for semantic versioning guidance.

The selected backend may make nonthrowing-to-throwing changes machine-ABI
relevant. Aether must not let that fact decide source semantics; a public ABI
would need stable wrappers under either model.

## 5. Experience from other languages

These examples are architectural evidence, not a popularity vote.

### Java

The Java language divides checked exceptions from `RuntimeException` and
`Error`. Its compiler requires checked errors from methods and constructors to
be caught or declared, treats throws clauses as contracts, and restricts
overriding methods from widening them. The stated goal is to reduce unhandled
recoverable exceptions, while ubiquitous programming/runtime failures are
unchecked to avoid pointless declaration clutter.
([Java Language Specification, chapter 11](https://docs.oracle.com/en/java/javase/26/docs/specs/jls/jls-11.html))

Lesson for Aether: checked sets provide real API enforcement, but a practical
language immediately needs a principled checked/unchecked partition and
override/interface rules. Aether's separate panic channel supplies part of
that partition, while its result/status policy already handles many failures
Java assigns to checked exceptions.

### Kotlin

Kotlin makes exceptions unchecked: callers may catch them but need not declare
or handle them. Its `@Throws` annotation exists primarily to communicate with
foreign Java/Swift/Objective-C boundaries, and official documentation notes
that unchecked semantics create interoperability complications.
([Kotlin exception documentation](https://kotlinlang.org/docs/exceptions.html))

Lesson for Aether: unchecked propagation simplifies its own function type
system, but foreign callers still require explicit metadata and containment.
FFI cannot be left to conventions merely because the core language is
unchecked.

### C#

C# uses typed runtime exceptions without source throws sets. .NET design
guidance asks public APIs to document contractual exceptions and avoid changing
them between versions even though the compiler does not enforce that policy.
It also distinguishes ordinary exceptions from fail-fast conditions.
([C# exception handling](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/exceptions/exception-handling),
[.NET exception-throwing guidelines](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/exception-throwing))

Lesson for Aether: unchecked does not mean exceptions are absent from API
governance. It transfers enforcement from type compatibility to documentation,
review, and versioning policy.

### C++

C++ originally had typed dynamic exception specifications, deprecated them,
and removed them in C++17 after poor experience. The surviving `noexcept`
contract expresses the more valuable negative guarantee that no exception
escapes, while RAII supplies deterministic cleanup.
([C++ proposal P0003R5](https://isocpp.org/files/papers/p0003r5.html))

Lesson for Aether: enumerating dynamic exception types in signatures can be
more brittle than specifying a nonthrowing boundary. Cleanup correctness is
orthogonal to checked sets; Aether's ARC/lifecycle graph must work under either
model. C++'s exact history is not directly transferable because Aether has no
destructors or inheritance-based exception ABI, but the contract-evolution
warning is relevant.

### Swift

Swift makes throwingness part of a function type, requires `try` at throwing
calls, supports untyped `throws(any Error)`, and now supports concrete typed
throws. Its higher-order design needs `rethrows` and can alternatively use a
generic error parameter to preserve the callback's error type.
([Swift function types](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/types/),
[Swift rethrowing declarations](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/declarations/))

Lesson for Aether: checked throwingness can be coherent and type-safe, but
higher-order composition inevitably creates effect variance, rethrowing, and
generic-error design. Those are core type-system features, not parser details.

### Rust (`Result`)

Rust represents recoverable failure as `Result<T, E>`. The `?` operator
propagates an error only from a function whose return type can carry it;
generic `E` and conversion rules are ordinary value/type composition. Panic is
separate.
([Rust Book: recoverable errors with `Result`](https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html))

Lesson for Aether: explicit failure contracts compose most transparently when
they are normal return types. Aether already follows this path for expected
parsing, file, and numerical outcomes. Rust does not demonstrate that checked
nonlocal exceptions are necessary; it demonstrates the value of reserving
static exhaustiveness for value-based failures.

### Zig (error unions)

Zig uses error sets and error-union return types, with subset-to-superset
coercion and explicit propagation. Its documentation notes that inferred error
sets make functions generic and complicate function pointers, cross-target
consistency, and recursion.
([Zig language reference: errors](https://ziglang.org/documentation/master/#Errors))

Lesson for Aether: precise error sets are powerful, but inference and callable
composition have deep type-system consequences even when errors are returned
as values rather than unwound. Aether should not assume typed exception sets
will remain a local annotation feature.

### Go

Go exposes ordinary failures as returned `error` interface values and expects
callers to inspect them. Panic/recover is a separate nonlocal mechanism, and
the standard-library convention is to contain panic inside package boundaries
when it is used for internal control.
([Go error handling](https://go.dev/blog/error-handling-and-go),
[Go panic and recover](https://go.dev/blog/defer-panic-and-recover))

Lesson for Aether: values make expected error flow explicit but can be verbose;
nonlocal failure still needs a boundary policy. Aether's result/status types
already cover the former, while its panic deliberately remains less
recoverable than Go's.

### Python

Python exceptions are unchecked and dynamically propagated. A handler catches
matching runtime types from direct or indirect calls, and unhandled exceptions
reach the runtime boundary. The model is flexible, but function declarations
provide no compiler-enforced failure contract.
([Python tutorial: errors and exceptions](https://docs.python.org/3/tutorial/errors.html))

Lesson for Aether: dynamic flexibility is not an architectural target for a
statically typed compiler. The useful evidence is narrower: typed catch
matching and well-defined propagation do not inherently require checked
function signatures. Aether must retain stronger static payload typing,
ownership, verification, and capability gating than Python.

## 6. Interaction with the existing Aether roadmap

### Explicit semantics

Checked exceptions make the call effect explicit. Unchecked exceptions still
have explicit throw, catch, matching, cleanup, and termination semantics, but
do not expose the effect in every signature. Aether's phrase “explicit
semantics” should mean behavior is defined and verified; it does not
automatically require every possible control effect to be a source type.

### Capability system

The capability system decides whether a backend supports an admitted source
feature end to end. It is not a source-level effect system. Under either model,
the capability gate must reject exceptions until the entire pipeline is ready.
Checked exceptions would add a new source contract; they should not be adopted
merely because capability metadata could record them.

### ARC and lifecycle

The choice is neutral. Both require ownership of the event before cleanup,
reverse destruction of live owners, exact partial-initialization rollback, and
no cleanup for panic. Checked declarations may improve static call summaries,
but they do not make one retain/release rule more correct.

### Explicit contracts

Aether already has a strong contract mechanism for expected failures:
result/status values in ordinary return types. Checked exceptions create a
second contract channel with different propagation and composition rules.
Unchecked exceptions keep the distinction:

- expected recoverable outcome: explicit result/status value;
- exceptional recoverable disruption: typed but unchecked exception;
- safety/invariant failure: uncatchable panic.

This partition is coherent only if libraries resist moving expected failures
into exceptions for convenience.

### Verifier

Both models require the same structural and ownership authority over
exceptional edges. Checked mode additionally verifies declared set coverage
and call compatibility. Unchecked mode still verifies that only `Error` values
are packed, every event owner is consumed once, all cleanup is present, and no
optimizer invents or loses an edge.

### Future effect system

Checked exceptions would be Aether's first source effect and would establish
variance, subtyping, inference, and generic composition precedents before a
general effect system is approved. That can be a useful foundation if Aether
is committed to effects; it can also become a special-case legacy if future IO,
allocation, async, cancellation, or mutation effects need a different model.

Unchecked exceptions preserve design freedom. Adding checked effects later
would be source-incompatible, so this is not cost-free postponement; it is a
decision that exception effects should not enter 1.x function types.

### FFI

Neither model may permit an Aether event to cross raw C. Checked sets make
potential throwing visible, but a wrapper must still catch root `Error` and
transport an opaque result. Unchecked mode requires the FFI declaration/wrapper
itself to be the authority. The small C ABI should use explicit status/error
transport regardless of the source model.

### Runtime extraction

Opaque event operations, descriptor identity, cleanup, and root termination
are the same. Checked sets may be serialized as compiler metadata but must not
select object layout or unwinding ABI. Unchecked mode may use internal
nonthrowing summaries, which likewise are compiler/runtime metadata rather
than language semantics.

## 7. Migration impact

### If Aether adopts checked exceptions

#### What becomes easier later

- Adding authoritative exception documentation, LSP views, and catch-or-declare
  diagnostics.
- Proving nonthrowing calls across separately compiled modules.
- Rejecting throwing direct exports at an FFI boundary.
- Building a future effect system that deliberately extends the established
  throws-effect variance model.
- Treating new escaping errors as clearly versioned source API changes.

#### What becomes harder later

- Simplifying function and interface types after libraries publish throws
  sets.
- Introducing higher-order functions without `rethrows` or generic effects.
- Designing generics without error-effect parameters or broad `Error`
  erasure.
- Hiding dependency-specific errors behind stable abstraction boundaries.
- Evolving constructors and methods without signature cascades.
- Relaxing to unchecked semantics without preserving obsolete annotations,
  compatibility rules, and user expectations.

### If Aether adopts unchecked exceptions

#### What becomes easier later

- Keeping interfaces and structural function types compact and stable.
- Adding callbacks, higher-order functions, and generics without immediate
  effect polymorphism.
- Changing internal providers and exception translation boundaries.
- Supporting different backend transports without source effect ABI
  assumptions.
- Maintaining one statically exhaustive mechanism—result/status values—for
  expected failure.

#### What becomes harder later

- Adding mandatory catch-or-declare in a compatible 1.x revision; existing
  functions and callers would lack declarations.
- Recovering complete public exception sets from documentation and
  whole-program inference.
- Proving nonthrowing behavior from imported source signatures alone.
- Giving FFI direct exports a nonthrowing guarantee without a distinct boundary
  form or analysis proof.
- Preventing undocumented new escaping errors through the compiler rather than
  API policy.

The migration asymmetry is real: unchecked-to-checked is more disruptive than
checked-to-unchecked at the syntax level. That favors checked exceptions only
if Aether wants exception effects as a permanent part of its function type
system. It is not, by itself, a reason to add them speculatively.

## 8. Recommendation

Aether should use **unchecked exceptions**.

The deciding reason is not familiarity, annotation dislike, compiler effort,
or ecosystem fashion. It is the architectural boundary Aether has already
chosen for failure:

1. Expected, routine, domain-level failure belongs in explicit result/status
   values.
2. Panic covers unrecoverable safety and invariant failure.
3. Exceptions therefore cover the narrower middle: exceptional disruption
   that a subsystem boundary may recover from.

Typed checked throws sets would create a second statically exhaustive error
channel alongside result/status values. That channel would enter interface
conformance, structural function types, constructor signatures, module
visibility, callback compatibility, and future generic effect polymorphism.
Its largest benefits apply to failures callers are expected to enumerate and
handle routinely—the same failures the roadmap says should remain values.

Unchecked exceptions preserve the useful parts of the working RFC: a typed
`Error` boundary, exact catches, explicit propagation CFG, deterministic ARC
cleanup, verifier authority, panic separation, and FFI containment. None of
those correctness guarantees requires source catch-or-declare. The compiler
must still model `may_throw` internally and conservatively; source
uncheckedness is not permission for an implicit compiler pipeline.

This choice has costs. A function signature will not be a complete exception
inventory, and adding a new escaping exception can surprise callers without a
compile error. Aether should address that directly:

- public APIs document conceptual exceptions as behavioral contracts;
- the LSP and documentation tooling may show inferred and documented throws
  information, clearly marked non-normative;
- compatibility guidance treats changes to documented exceptions as API
  changes even though function types remain compatible;
- broad/root catches receive diagnostics where they mask likely mistakes;
- raw C exports and callbacks use mandatory containment wrappers rather than
  trusting absence of a throws clause; and
- standard-library design continues to use result/status values whenever a
  caller is normally expected to branch on failure.

A boolean checked `throws` effect is not recommended as a compromise. It would
still complicate function types, interfaces, callbacks, and higher-order
composition while providing no exact error contract. If Aether later adopts a
general effect system, nonthrowing/throwing constraints should be designed
together with its other effects rather than frozen now as an exception-only
special case.

The working RFC's typed checked-effect recommendation should therefore be
rejected when the decision log is formally updated. This study does not perform
that update.

## 9. Open questions

These questions affect the unchecked model's quality but do not reopen the
checked-versus-unchecked decision:

1. Should public declarations support a non-semantic documentation annotation
   listing conceptual exceptions, or should documentation remain prose?
2. Which exception-flow facts should the LSP infer, and how will it distinguish
   authoritative source contracts from best-effort analysis?
3. What compatibility policy applies when a public API adds, removes,
   translates, or broadens a documented exception?
4. Should the compiler warn when an exception can escape explicit `main`, or
   should only the runtime unhandled-exception contract apply?
5. Which diagnostics should apply to root catches, empty catches, immediate
   rethrows, and catches with no currently inferred matching throw?
6. What source construct identifies an FFI-safe wrapper, and can a direct
   export ever rely on proof of nonthrowing behavior?
7. Should internal/compiler-generated declarations carry authoritative
   nonthrowing summaries that are absent from source function types?
8. How are inferred throw summaries versioned in module/compiler metadata
   without becoming a source or binary compatibility promise?
9. Must `Error.message()` remain statically nonthrowing even though other
   methods have no source throws effect?
10. How should standard-library review enforce the boundary between expected
    result/status failures and exceptional throws?
11. If a future general effect system is proposed, is exception propagation an
    effect it may optionally model in a new major version, or is unchecked
    propagation permanently outside source effect typing?
12. Which tests ensure unchecked source semantics do not cause the optimizer,
    FFI, or runtime to treat unknown calls as nonthrowing?

Recommended:
Unchecked Exceptions
