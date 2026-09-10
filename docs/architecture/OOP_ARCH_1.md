# OOP-ARCH-1 — classes and interfaces for Aether

Status: **design recommendation, not language admission**. Audited 2026-09-10.
No class, interface, constructor, inheritance, dispatch, exception or runtime
implementation is part of this milestone. All new syntax below is illustrative.
The proposed defaults are the baseline for subsequent bounded implementation
work; items explicitly deferred remain unavailable until independently qualified.

## 1. Problem and authority

Define identity-oriented objects without changing Aether's existing value
aggregates, assuming neither tracing GC nor Rust ownership semantics. Sharing
must have a documented cost, mutation must be visible in signatures, and every
lowering boundary must retain enough information for independent verification.

The reconstruction authorities are the [charter](AETHER_V1_LANGUAGE_CHARTER.md),
[semantic contract](AETHER_V1_SEMANTIC_CONTRACT.md),
[compiler architecture](AETHER_COMPILER_ARCHITECTURE.md),
[compiler-next README](../../compiler-next/README.md), and
[LANGUAGE-PARITY-1 report](LANGUAGE_PARITY_1_REPORT.md).
Their implemented contracts remain authoritative for compiler-next. This
proposal does not supersede them by admitting new programs.

Implementation evidence inspected:

| Evidence | Relevant authority/finding |
|---|---|
| [types.rs](../../compiler-next/crates/aether-frontend/src/types.rs) | `TypeData`, nominal IDs, `GenericOwner`, `TypeProperties`, `aggregate_properties`, capability queries; no class/interface type |
| [hir.rs](../../compiler-next/crates/aether-frontend/src/hir.rs) | Module resolution, `InstanceKey`, monomorphization, places, `synthesize_ownership`, borrow provenance and cleanup |
| [mir.rs](../../compiler-next/crates/aether-middle/src/mir.rs), [ssa.rs](../../compiler-next/crates/aether-middle/src/ssa.rs) | Typed ownership operations, verified phase boundaries and exact type checks |
| [LLVM backend](../../compiler-next/crates/aether-backend-llvm/src/lib.rs) | Concrete layouts and recursive `emit_drop_glue` |
| [legacy parser](../../src/aether/parser.py), [typechecker](../../src/aether/typechecker.py) | Actual legacy syntax, conformance, visibility and receiver analysis |
| [legacy class model](../../src/aether/class_value.py), [class runtime](../../src/aether/backend/llvm/class_runtime.py), [interface ABI](../../src/aether/interface_abi.py) | Native identity/RC, initialization tracking, erased interface witnesses |
| [class tests](../../tests/aether/test_classes.py), [interface tests](../../tests/aether/test_interfaces.py), [class examples](../../examples/classes/reference_aliasing.ae) | Historical behavior and intentional-difference candidates, not a new qualification run |

The static `TypeArena` is a compiler data structure. Its Rust `Arc` ownership
between phases is unrelated to source class ARC.

## 2. Legacy model: evidence, not authority

Legacy classes share identity: assigning a handle and mutating through the new
alias changes what the original observes. `NativeClassObject` models a strong
count, initialized fields and reverse field destruction. Native helpers insert
non-atomic retain/release and free on the last release. This is stronger evidence
than Python host object behavior alone.

`_class_declaration` accepts **both** `implements I` and `: I`. Its list resolves
interfaces; it does not establish a stateful class base. The inspected class AST
has an `implements` list and no base-class member. Java-style `extends` is a
comparison candidate here, not a demonstrated legacy inheritance feature.

Classes have private default fields/methods, public interface implementations,
implicit member lookup and `this.field` for shadowing. One explicit
`constructor(...)` is allowed; private constructors are rejected, and omission
generates a positional field constructor even for private fields. The legacy
checker infers receiver mutation from bodies and transitively called methods;
`_interface_method_is_mutating` scans known implementations. Thus the observed
interface access classification is not solely its declared signature.

Const class access blocks mutation through that path but does not freeze aliases.
Legacy examples reject class equality and mutating temporary receivers. Interfaces
are nominal, support struct and class implementations, and hide fields. Native
interface machinery includes a two-word carrier, witnesses, erased ownership
adapters, and struct boxing. Existing exception integration with `Error` is
historical evidence only; it does not choose the next exception model.

## 3. Ideas preserved

Preserve class identity and alias-visible state, nominal interface conformance,
encapsulation, explicit public API, `this` disambiguation, static member lookup,
class calls using `C(...)`, and deterministic RC for actual sharing. Preserve
the useful distinction between value structs and classes. Preserve the insight
that interface dispatch and ownership adaptation need explicit compiler facts.
None of this imports legacy IR schemas, name-based type identities, runtime ABI
version numbers or Python semantic passes into compiler-next.

## 4. Ideas intentionally changed or bounded

| Legacy evidence | Reconstruction recommendation | Reason |
|---|---|---|
| `implements` or `:` for interfaces | One `:` list, also resolving an optional class base later | Type kind is already known |
| No demonstrated stateful inheritance in inspected parser | Design one explicitly open base | Deliberate new feature, not claimed parity |
| Mutation inferred from implementation bodies | Read receiver by default; declared `mut` receiver | Stable interface/API contract |
| Interface mutation found by scanning implementers | Each interface requirement declares receiver access | New implementations cannot change old call legality |
| Positional construction exposes private field signature | Explicit `init`; only empty classes get a synthesized empty initializer | Encapsulation and invariant ownership |
| Private constructor rejected | Private initializer supported by design | Factories/control of construction |
| Const access exists in legacy | Preserve read-path principle; defer owned const spelling | Avoid an incomplete qualifier/escape system |
| Struct interface boxing | Class-backed interfaces first | Avoid changing struct copy/box semantics |
| Class equality rejected | Identity `==`/`!=` for compatible handles | Useful, fixed, inexpensive meaning |
| Legacy error-interface machinery | Independent EXCEPTION-ARCH-1 | OOP must not determine which values can be thrown |

## 5. Struct versus class versus interface

| Property | `struct` | `class` | `interface` |
|---|---|---|---|
| Meaning | Nominal value aggregate | Nominal object identity, held by strong handles | Nominal behavior contract; an interface value owns an adapted class handle initially |
| Fields | Inline in value | Inline in heap object; handle stored in variable | None |
| Assignment/call/return | Existing structural Copy or move | Alias lvalue handle; transfer fresh owned result | Same ownership as underlying class handle |
| Identity | No identity independent of value | Stable until destruction | Same underlying object, no wrapper identity |
| Layout | Existing value layout | Handle layout separate from object layout | Conceptual object pointer plus witness |
| Lifecycle | Existing aggregate rules | Release handle; destroy object at last release | Release same object through carrier |

Do not redesign structs, add struct methods, or change positional aggregate
construction in this milestone. A later struct containing a class handle stays
a value: the handle is its field, not an inline object payload. Under section 33
that struct is non-Copy and moves as a whole. Enums retain their current active
payload and move/drop rules. No automatic deep copy is introduced.

## 6. Class identity

Recommend non-null owning handles to independently allocated objects:

```aether
// Proposed syntax, not accepted by compiler-next.
class Counter {
    int value;
    public init(int value) { this.value = value; }
    public mut int increment() { value = value + 1; return value; }
    public int get() { return value; }
}

int main() {
    Counter a = Counter(0);
    Counter b = a;
    b.increment();
    return a.get(); // 1: a and b own handles to the same object
}
```

Inline class values would duplicate struct semantics and complicate identity
across moves. Unique heap handles give identity but make the requested ordinary
aliasing example consuming or require an explicit sharing operation. Shared
handles fit identity-centric objects and GUI/model/service-style graphs, with
the RC and cycle limitations below. Allocation is implied by choosing `class`;
ordinary structs and scientific owners do not acquire ARC.

## 7. Ownership alternatives

| Model | Ergonomics and lifetime | Cost and destruction | Cycles, threads and FFI |
|---|---|---|---|
| Compiler-managed strong RC | Natural alias assignment and owning returns | Retain on alias, release at cleanup, synchronous last-release destruction | Strong cycles leak; atomic counts alone do not protect fields; opaque owned/borrowed FFI handles needed |
| Intrusive ARC header | RC model above; compiler controls header | Usually one object allocation, header traffic and descriptor load | Private layout unsuitable for pretending object is a C struct; weak support may need side metadata |
| Non-intrusive ARC control block | Can manage foreign payload without modifying it | Extra control storage/indirection, possibly another allocation; coallocation possible | Useful foreign/deleter boundary; same cycle and data-race issues |
| Unique owner plus explicit shared handle | Clear exclusive lifetime; alias requires explicit promotion/clone | Moves need no retain; sharing pays only when selected | Unique trees cannot form owning cycles; shared graphs still can; transfer to FFI is explicit |
| Regions/lifetime ownership | Cheap access in bounded computations; awkward unrelated escaping aliases | Arena allocation and bulk reclamation; destructor schedule needs a contract | Intra-region cycles reclaim with region; cross-region references need proof; threads/FFI must respect region |
| Manual destruction | Direct control but substantial obligations on every alias | Explicit allocation/free; dangling aliases and double destruction require unsafe rules | No automatic cycle handling; threading and FFI obligations fall on programmer |
| Hybrid values/unique owners/shared classes | Existing value and container code keeps its ownership | RC only for class identity; more compiler ownership categories | Future explicit weak/region/foreign facilities can coexist without changing class meaning |

Compiler-managed RC and intrusive/non-intrusive layout are separate axes, not
competing language semantics. Tracing cycle collection would add a different
runtime and destruction contract. It is not part of the recommendation.
Swift's [ARC documentation](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/automaticreferencecounting/)
provides a concrete reference for strong-cycle limitations and weak alternatives;
its source ownership rules are not adopted wholesale.

## 8. Recommended initial ownership

Use compiler-managed **non-atomic intrusive ARC for class handles**, alongside
existing value semantics and unique resource owners. The initial execution
profile is single-threaded; class handles may not cross thread/foreign callback
boundaries without a separately admitted transfer contract. Do not infer thread
safety from a future switch to atomic RC. Shared mutable fields would still need
synchronization or isolation rules.

Every owning handle accounts for one strong ownership obligation. Allocation
creates one; aliasing creates another; transfer changes its location; cleanup
discharges it. Counts are checked for overflow/underflow and invalid resurrection
in the bootstrap runtime. Allocation failure/count overflow terminate using an
explicit aborting runtime failure, not an invented catchable exception. Exact
diagnostic identifiers are a future implementation choice.

This choice makes `class` a visible sharing decision. It is not a universal ARC
rule for Aether, and it accepts bounded bookkeeping to satisfy ordinary alias
ergonomics. Section 33 makes the necessary extension beyond today's binary
Copy-versus-move analysis explicit.

## 9. Assignment and aliasing

`C b = a` from an owning class lvalue with writable object access retains the
object; `a` remains valid. Assignment to an existing handle evaluates the RHS
first, acquires its ownership, publishes the new handle, then releases the old
handle. This ordering handles `a = a` and aliased field replacement safely and
gives future destructor reentrancy a fully initialized destination. Exact
self-assignment may be an effect-free no-op.

Fresh constructor/call results transfer their owned token into the destination
without a second retain. By-value class parameters own a token: passing an
lvalue aliases; passing a fresh result transfers. Return of an lvalue aliases
before local cleanup; return of a fresh owner transfers. A proven transfer of
a dying local may remove a balanced retain/release without changing observable
destruction order. No new source `move` operator is specified here.

Rebinding `b` later does not rebind `a`. Changes to the shared object's fields
are visible through both. Alias creation from a read-only path is restricted
by section 23; copying a handle must not launder write permission.

## 10. Inheritance syntax alternatives

| Candidate | Evaluation |
|---|---|
| `class Dog extends Animal implements Runnable, Serializable` | Readable kind labels, but repeats type declarations and grows the grammar |
| `class Dog : Animal, Runnable, Serializable` | One relation list; resolver knows each nominal kind and diagnoses cardinality |
| `class Dog(Animal) : Runnable, Serializable` | Risks conflating the type relation with constructor parameters/invocation |
| Separate conformance/implementation blocks | Useful future retroactive-conformance design, but adds coherence/visibility questions unnecessary here |

`extends` and `implements` convey redundant kind information once names resolve.
Neither keyword proves override correctness or initialization order. Requiring
one merely for familiarity does not satisfy the boilerplate principle.

## 11. Recommended relation syntax

Use `class Dog : Animal, Runnable, Serializable` and
`interface ReadWrite : Readable, Writable`. Resolve transparent aliases before
classifying each entry. The list is semantically unordered: at most one class
entry, the rest interfaces; recommend base-first formatting without making
order carry type information. Reject duplicate canonical entries, unknown or
inaccessible names, scalar/struct/enum entries, and invalid generic arity.

No implicit root `Object` class. Relation syntax does not invoke a constructor;
base initialization has its own explicit argument-bearing syntax in section 21.
No compatibility synonym `implements` or `extends` is recommended for the new
compiler's initial admission.

## 12. Class inheritance cardinality

Recommend **at most one stateful base class and any number of interfaces**.
No inheritance at all is sufficient for the first two verticals and encourages
composition, but forbidding it permanently would exclude useful shared state
and behavior specialization. Multiple stateful bases introduce diamonds,
subobject identity, ambiguous field paths, pointer adjustment and destructor
ordering without a demonstrated Aether need. Reject that model.

An inheritance graph must be acyclic and bases explicitly extensible. Derived
objects have one identity and one strong count, never a separately owned base
object. Fields cannot hide inherited fields; visible inherited method name
collisions must be resolved as valid overrides or rejected. General member
overloading and explicit hiding are deferred.

## 13. Minimal interface contract

An interface declares public instance method requirements, each with explicit
parameter/result types and a declared receiver capability. No instance state,
fields, constructors, destructors, properties, associated types, constants,
static members, generic methods or default bodies in the first interface
vertical. An interface itself cannot be constructed.

```aether
interface CounterAccess {
    int get();
    mut int increment();
}
// A class would explicitly declare : CounterAccess and supply public methods.
```

Omit `public` and `abstract` on requirements because the declaration already
determines both facts. Reject contradictory modifiers. Associated types and
generic interface methods require a later object-safety/erasure design; ordinary
generic interfaces are considered separately in section 34.

## 14. Nominal conformance

`class C : I1, I2` explicitly commits to both contracts. Merely matching methods
does not grant conformance or an implicit conversion. Structural matching is
convenient for adapters, but can accidentally create a relationship as an API
evolves and obscures where its compatibility commitment is made.

Validate public method availability and exact canonical parameter/result types,
parameter ownership modes and receiver capability. Initially require exact
receiver matching too: a read implementation for a mutating requirement is
safe in principle but capability subtyping is deferred. No covariant returns,
parameter variance, structural fallback or implicit boxing. An inherited public
implementation can satisfy a newly declared interface if its complete contract
matches. Inheriting a base class also inherits its nominal conformances.

One implementation may satisfy identical requirements from several declared
interfaces; a same-name incompatible requirement is a diagnostic. Explicit
per-interface method bodies and overload resolution are later work.

## 15. Interface inheritance

Recommend multiple interface inheritance as a statically checked acyclic graph.
It combines requirements without state. Deduplicate diamonds by originating
interface/member identity, not by table position or spelling. Independently
declared identical contracts can share one implementing method but retain their
own requirement identities. Conflicting same-name contracts are rejected.

`ChildInterface` can upcast to its declared parent while retaining object
identity and access capability. First interface implementation need only admit
flat interfaces; inherited witness adaptation is a subsequent bounded step.
No unrelated interface-to-interface conversion without a static relation.

## 16. Default interface implementations

Defer. Default bodies can remove repeated forwarding but introduce conflict
resolution, versioning, inherited receiver effects and dispatch questions.
Initial requirements have no code, so the class supplies every implementation.
Reusable free functions are available without inventing an inheritance priority
rule. The first implementation must reject default bodies early.

## 17. Dispatch defaults and language comparison

| Reference design | Tradeoff for Aether |
|---|---|
| C++: virtual dispatch is explicitly introduced; overrides continue it | Predictable opt-in, but silent overriding without mandatory `override` is undesirable |
| C#: ordinary methods non-virtual; `virtual` and `override` express extension | Good local dispatch visibility; extensible class defaults are a separate decision |
| Java: ordinary accessible instance methods participate in overriding unless restricted | Convenient polymorphism, but extension and indirect-call expectations become pervasive |
| Kotlin: classes/members final by default, `open` opts in | Extension is an intentional API commitment; extra spelling occurs where semantics change |

These comparisons use the [C++ virtual-function draft](https://eel.is/c%2B%2Bdraft/class.virtual),
[C# class specification](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/language-specification/classes),
[Java class specification](https://docs.oracle.com/javase/specs/jls/se21/html/jls-8.html),
and [Kotlin inheritance documentation](https://kotlinlang.org/docs/inheritance.html).

Recommend non-virtual, non-overridable methods by default, with `open` explicitly
introducing a virtual slot. Interface calls dispatch through their witness even
when the concrete implementation is non-virtual. Class openness and method
openness are independent. An open class need not have any virtual methods.

## 18. Override rules

Require `override` when replacing an inherited open class method. It asserts an
intended relationship not already known from the new declaration: the compiler
must reject a missing base target, a final target, or any signature/capability
mismatch. It prevents a newly added base API from silently changing a derived
method into an override. Omitting it on a matching inherited slot is an error.

`override` preserves the existing virtual slot and its openness; no repeated
`open` is needed. Future `final override` may close it. Visibility cannot narrow.
A same-name incompatible inherited method is rejected in the initial model
rather than introducing overload/hiding rules.

Implementing an interface requirement alone does **not** require `override`:
the explicit conformance and exact signature already establish that obligation,
and there is no inherited class body to replace. It does require `override` if
the same method also replaces a base class slot.

## 19. Open, final and sealed

Classes are final by default. `open class Animal` permits derivation, while
`public open int sound()` permits overriding that method. A newly declared
derived class is final unless it too says `open`. Private methods cannot be
open. Declaring a fresh open method in a final class is rejected as ineffective.

First vertical: final concrete classes and direct methods only, with no modifier
family implementation. Admit `open` and `override` together with inheritance in
a later vertical. Defer explicit `final` and `sealed`; the latter needs a defined
closed-world boundary for permitted subclasses and exhaustive analysis. Enums
already serve closed value alternatives. Abstract classes are also deferred.

## 20. Visibility

| Position/modifier | Recommended meaning |
|---|---|
| Class field or ordinary method, omitted | Private to its declaring class, across instances of that class |
| Initializer, omitted | Private, following member defaults |
| New top-level class/interface, omitted | Internal to the current module |
| `public` | Accessible through existing imports, subject to containing type visibility |
| `private` member | Declaring class only; not automatically subclasses |
| `internal` member/type | Same module, not an inferred package/project boundary |
| `protected` (later) | Declaring class and subclasses; no unrelated same-module privilege |
| Interface requirement | Public contract member implicitly |

Initial admission needs private/default members, `public`, and implicit internal
top-level types. Explicit `internal` spelling can wait; `protected` waits for
inheritance. The proposed protected rule allows subclass access through `this`
or a receiver statically typed as that subclass/its descendants, not arbitrary
base objects. Top-level `protected` is invalid; top-level `private` need not be
admitted as a redundant synonym for internal.

Defaults are fixed lexical rules, never inferred from use sites or bodies.
Omitting visibility is useful for implementation details; public exposure must
be deliberate. Public signatures, public bases and public conformances cannot
expose less-visible types. Access checks use declaration ownership and imports,
independently of physical field offsets. Existing struct fields and existing
module/free-function visibility are not retroactively changed by this proposal.

## 21. Constructors

| Spelling | Assessment |
|---|---|
| `constructor(int x)` | Clear role; verbose but viable legacy spelling |
| `Counter(int x)` in class body | Repeats enclosing type name and complicates rename/parser distinction |
| `init(int x)` | Short role marker without repeated name; recommended |

Construction expression remains `Counter(0)`; HIR distinguishes type application
from a free call using declarations. An initializer has no result type and cannot
return a value. `init` is a dedicated member role, not an overloadable ordinary
method. Prefer a contextual spelling instead of globally reserving a common
free-function name; exact token treatment is an implementation decision.

Initially allow one explicit initializer, no overloads, named/default arguments
or field initializer expressions. Every field must be definitely initialized
on every normal completion path; no default zero/null memory counts as proof.
Reads before initialization fail. Branches must establish the same complete
initialized state; reassignment after initialization follows normal replacement.
Loops alone cannot establish required initialization unless proven to execute.

If no initializer exists, synthesize a zero-argument initializer **only for an
empty class**, with the containing type's effective visibility. Do not synthesize
a field-wise initializer for nonempty classes. Explicit private/public `init`
controls construction; named free factories can later hide construction without
requiring static members or constructor overloads.

Future inheritance direction:

```aether
open class Animal {
    int age;
    public init(int age) { this.age = age; }
}
class Dog : Animal {
    int tag;
    public init(int age, int tag) : base(age) { this.tag = tag; }
}
```

The base initializer completes before derived fields/body can be used. Its
arguments evaluate left to right and cannot access the uninitialized receiver.
Omission is permitted only if an accessible zero-argument base initializer
exists. There is one allocation for the complete object; base initialization
does not allocate a second object. Constructor delegation/overloading waits.
Construction failure and exception unwinding wait for EXCEPTION-ARCH-1; aborting
traps retain the current no-unwind behavior.

## 22. `this` and initialization escape

`this` is an implicit non-owning receiver capability, not a rebindable owning
local. Member names can be unqualified. Local/parameter names take precedence;
`this.value = value` resolves shadowing without naming conventions.

During the entire initializer, `this` cannot escape, be retained, be returned,
be passed to another function, stored into another object, or be used for a
method call. This conservative first rule includes direct helper calls on
`this`, even after some fields are initialized. Free helpers operating on
already evaluated scalar values remain possible. Relaxation would need explicit
initialization/effect proof; no virtual dispatch on partially built objects.

After construction, a method may lend its receiver during a nested call. A
mutating receiver can create an owning alias (and pay a retain); a read receiver
cannot export a writable alias. Returning/storing borrowed `this` remains
forbidden under the existing non-escape model. No implicit lifetime extension.

## 23. Receiver capabilities and mutability

Recommend implicit receiver syntax with **read access by default and a declared
`mut` method modifier**. `mut int increment()` borrows writable object access;
`int get()` borrows read access. The modifier is part of the checked signature,
including interfaces and overrides; it is not inferred from the body. Body
checking verifies that every receiver-derived write uses writable access.

Java/C# style implicit mutable receivers minimize spelling but cannot express a
read receiver contract alone. Rust's [method receiver forms](https://doc.rust-lang.org/stable/book/ch05-03-method-syntax.html)
distinguish read, mutable and consuming access explicitly. C++ const member
qualification offers another declared read path; see its
[class rules](https://eel.is/c%2B%2Bdraft/class). Aether can preserve the useful
capability distinction without repeating the known enclosing receiver type or
adopting Rust exclusivity.

**Existing Aether `ref mut` is not exclusive and never implies `noalias`.**
Read-only access prevents writes through that path, not mutation through other
aliases. Read methods are not pure, globally immutable or safe to memoize:
separate writable arguments/aliases may still mutate the same object.

| Access path | Handle slot | Object access |
|---|---|---|
| Ordinary owned local `C c` | Rebindable | Read/write shared access |
| `ref C r = &c` | Borrowed read access; cannot replace `c` | `(*r)` can read fields/call read methods |
| `ref mut C r = &mut c` | Borrowed read/write; may replace `c` under provenance rules | `(*r)` can also write fields/call `mut` methods |
| Read method `this` | No replaceable handle slot | Read capability on this object |
| Mutating method `this` | No replaceable handle slot | Read/write capability on this object |
| Future owned `const C` | Recommended non-rebinding access path | Read path, not a frozen object; syntax/admission deferred |

Explicit reference calls stay explicit: `(*r).get()`, not general auto-deref.
Dot-call receiver lending is one class-specific rule, not implicit borrowing
for ordinary free-function parameters. Borrowing a handle slot itself performs
no retain and obeys current lexical non-escape/replacement constraints.

A read path must not become writable by `C x = *r`, returning `this`, passing
it to a by-value `C` parameter, or copying a class-valued field into a writable
handle. Reject these operations initially. Read capability propagates through
receiver-derived field projections and interface/base adaptations. An eventual
owning read-only handle needs a real type/access model; local `const` bookkeeping
alone would be insufficient. It is not introduced here. Read paths may copy
ordinary scalar/Copy value fields: those copies do not share object state.

Calls evaluate and stabilize the receiver before arguments, left to right.
The object must stay alive even if an argument/nested call rebinds the original
handle. A compiler-managed temporary strong keepalive supplies this proof when
an existing owner cannot be proven stable; see costs in section 33. Receiver
borrowing neither consumes the caller's handle nor promises object uniqueness.
Initially require an addressable writable receiver for `mut` calls; read calls
on temporaries are allowed and keep the temporary alive through the call.
Consuming receiver methods are deferred: consuming one alias could not promise
destruction or exclusive ownership of the shared object.

## 24. Field access and admissible storage

`object.field` addresses the field of the shared identity. Scalar reads copy;
scalar writes require writable access and are alias-visible. Future class-field
reads through writable access retain the referenced identity, never copy its
payload. Owning value fields cannot be moved out by an ordinary read; no holes
or partially moved objects are admitted. Replacement acquires the new owner
before releasing the old field.

| Field category | Architectural direction | First class vertical |
|---|---|---|
| Admitted scalar | Inline, ordinary value rules | Yes |
| Finite concrete Copy struct/enum | Inline, preserve layout and value reads | Yes |
| Drop-requiring struct/enum | Inline recursive move/drop | Defer |
| Class/interface handle | Strong owned edge; cycles possible | Defer |
| `Buffer<int>` | Existing unique owner inside object | Private initialization and destruction only, to exercise nested cleanup |
| Other Buffer/Array/List | Subject to existing positive element admission and drop support | Defer |
| Vector/Matrix | Existing owning descriptor, shape/layout unchanged | Defer |
| `ref`, mutable refs, any view, transitively borrowed aggregate | Not Storable under current lifetimes | Reject |

The narrow Buffer allowance does not admit borrowed/indexed storage access
through a class. Such operations need alias-aware invalidation: `a` and `b`
may reach the same List field even though their local roots differ. Merely
reusing today's root-local borrow analysis would be unsound. Initially reject
source references/views into all class fields, including scalars, and do not
let an interior address escape an operation. Stable object address alone cannot
make a replaced field's old backing live. Future storage methods must prove
borrow stability across every alias/reentrant call or impose a checked access
discipline; ordinary `ref mut` is not that proof.

Storable is a necessary storage condition, not automatic feature admission.
Buffer's current Copy/no-drop element gate remains unchanged. Containers of
class handles, and structs/enums containing them, need dedicated admission later.

## 25. Lifecycle and destruction

Evaluate construction arguments first, allocate the complete object, establish
its header/count and initialize its fields. Publish a normal owning handle only
after successful complete initialization. Lexical exits and normal returns
release still-owned local handles in the existing reverse cleanup order.
Temporaries release at their defined full-expression/cleanup boundary.
Replacing a live handle releases its old ownership. Last release synchronously
destroys the dynamic object's fields and frees its allocation. A surviving
alias keeps it alive beyond any particular variable's scope.

Eventually support a deterministic user destruction hook, provisionally
`deinit { ... }`, with no parameters/result/visibility/virtual declaration.
It is not a callable `delete`, a GC finalizer, or an interface requirement.
First vertical has compiler-generated field cleanup only.

Future inheritance destruction order: most-derived user hook, its fields in
reverse declaration order, then the base hook and base fields recursively,
followed by one allocation free. Hooks may inspect their still-live fields but
cannot resurrect/publish `this`, dispatch virtually on it, or throw. An escaping
failure terminates; recoverable destructor semantics are not designed here.
The dynamic descriptor chooses destruction even through a base/interface handle;
users never need to spell a virtual destructor for memory safety.

HIR owns semantic acquisition/transfer/release obligations. MIR materializes
them on paths, SSA preserves explicit effects, and runtime executes them. There
must be one insertion authority, not independently guessed cleanup in LLVM.
Do not move final releases earlier across observable work as a last-use
optimization. Aborting scalar traps still do not promise cleanup; future unwind
paths must be designed separately.

## 26. Cycles

Strong ARC does not reclaim cycles, including a self-edge or cycles through
interfaces/containers. Last external release of a cycle need not run any
destructor. This is an accepted model limitation, not deterministic reclamation
of every unreachable object. The first vertical cannot create owned graph edges
because class/interface fields and captures are excluded.

Before admitting general object graphs, document acyclic ownership patterns and
decide a weak-edge/checked-upgrade API or another explicit cycle-breaking model.
Weak references are a future possibility, not permission to add null or optional
handles here. Non-owning stored back-pointers cannot bypass the current lifetime
restrictions. No tracing collector, automatic cycle detection or manual safe
`delete` is assumed. Cycles are not solved by atomic RC or custom allocators.

## 27. Conceptual physical representation

```text
owned C handle ----------> object allocation
                          [ strong count | descriptor pointer ]
                          [ base payload, if any             ]
                          [ derived fields                  ]

descriptor (immutable, per concrete dynamic class)
  size/alignment, dynamic destruction glue
  optional virtual slots and interface witness references
```

Recommend a one-word class handle and intrusive header as a bootstrap choice.
Descriptor placement, header order, widths, alignment, initialization bookkeeping
and whether vtables are embedded or referenced are private target layout choices.
No public ABI, stable addresses exposed to source, runtime numeric `TypeId`,
reflection API or universal `Object` is fixed. Identity means one live object,
not a publicly observable integer address. Initialization facts belong in IR;
a per-field runtime bitmap is not automatically required by the legacy layout.

## 28. Base-class values and conversions

`Animal a = Dog(...)` transfers the new handle to the same complete object;
upcasting an existing owning Dog lvalue creates another strong ownership token.
No slicing, field copy, allocation or independent base refcount. The bootstrap
can keep a common object-start pointer; field lowering uses the static declaring
class and known layout. Base payload layout never changes the semantic identity.

Permit only statically proven upcasts along declared accessible bases. An
explicit reference to a **handle slot** is invariant: `ref mut Dog` must not
convert to `ref mut Animal`, which would allow storing a non-Dog into a Dog slot.
Do not conflate safe value upcasts with reference-to-slot covariance. Receiver
adaptations are a separate typed operation and cannot increase write access.

## 29. Interface values

`Drawable d = circle` initially produces a conceptual pair
`{object pointer, immutable witness pointer}` owning **one** strong token on
the original class object. The witness belongs to the exact dynamic class and
target interface; it is metadata, not a second owner. Copying an owning carrier
aliases/retains once; dropping it releases once. No wrapper allocation, copied
object or struct boxing in this slice.

Class-to-interface conversion is allowed only by nominal conformance and
preserves capability. If the static source is a base class, adaptation must use
the object's dynamic descriptor to select the correct witness for overridden
implementations, rather than freezing the base implementation. Interface-parent
upcasts adapt witness metadata without changing object identity. A conversion
of a borrowed receiver need not retain unless a keepalive is required; an owned
result does acquire/transfer its token explicitly.

A boxed wrapper is useful for future value-type conformers but would require a
separate copy/identity/erasure decision. One thin erased pointer alone would
move all interface selection into runtime lookup on calls. Prefer the fat carrier
for explicit adaptation and bounded per-call dispatch. Do not freeze its ABI.

## 30. Virtual class dispatch

A base-typed receiver calling an open slot invokes the most-derived override.
A known-class receiver calling a non-virtual method uses a direct target. Even
`Animal a` requires virtual dispatch for an open method unless the compiler can
prove the dynamic type. A `Dog` static type alone is insufficient if Dog is open.

Conceptually load the object's class descriptor/vtable, select the verified
slot, and call its exact receiver/argument ABI. `base.method(...)`, when later
admitted, explicitly selects the base implementation directly. No arbitrary
runtime name lookup. Devirtualization requires an exact dynamic target/final
slot proof and must preserve receiver capability, lifetime and effects.

## 31. Interface dispatch

An interface call resolves a requirement identity statically, selects its slot
from the carrier's witness, and calls the class implementation through a typed
adapter if needed. The slot signature includes read/mutating receiver access,
parameter modes and result ownership. A direct concrete-class call to a
non-virtual implementing method remains direct.

When inheritance is added, witnesses for a derived dynamic class must reflect
its overrides even if conformance was declared by the base. A witness thunk may
forward through a virtual slot; a proven exact implementation can be direct.
No per-call search by method name or scanning all known implementers for receiver
effects. Interface dispatch does not make every implementing class method open.

## 32. Equality and future type tests

Recommend `==` and `!=` as **object identity comparison** for handles of the
same canonical class/interface type or when one operand has a statically valid
upcast to the other's type. Compare object identity, not fields, witness pointer
or metadata address. No allocation/retain is necessary for comparison beyond
operand evaluation/keepalive. Unrelated types without such conversion require
an explicit common declared type or are rejected. Struct/enum equality rules
remain unchanged; no user equality overloads or automatic value comparison.

Descriptors and nominal relation metadata leave room for future `is`/`as`/cast
operations. None is admitted now, and no failing-cast representation, RTTI API,
reflection or exception is selected. Dispatch metadata is not a blanket RTTI
feature admission.

## 33. Copy, move and performance contract

Today's `Copy` guarantees implicit duplication and derives through aggregate
fields; all current concrete Copy values are no-drop. The implementation often
uses `!guarantees_copy` to select ownership tracking. Simply setting classes
Copy would therefore be both an unexamined cost decision and an invalid
implementation shortcut.

Three viable directions are: broaden Copy to include nontrivial RC duplication
and audit all copy/drop/fill lowering; make ordinary class assignment move and
require an explicit share operation; or distinguish class aliasing from
structural Copy. **Recommend the third for the initial class model.**

| Property/operation | Proposed class/interface handle rule |
|---|---|
| `Copy` capability | False; cannot satisfy `T:Copy`, Copy-based fill or bitwise duplication |
| `Relocatable` | True for the handle; transfer bytes/token, invalidate old slot, no retain |
| `Storable` | True for admitted owned handles; never a waiver for inadmissible object field lifetimes |
| `needs_drop` | True; release one strong obligation |
| Ordinary known class/interface lvalue use | Built-in `Alias` operation, checked access and explicit retain semantics |
| Fresh owner use | Transfer its existing obligation |
| Struct/enum containing such a handle, later | Non-Copy value aggregate; whole-value move/drop, no implicit recursive alias-copy |

This deliberately adds a third source-use category; it is not derivable from
today's Copy boolean. It is a documented exception to a binary copy/move rule,
chosen to retain both ordinary class aliasing and existing structural Copy
expectations. `Alias` is compiler vocabulary, not a new user trait or mandatory
source keyword. The semantic-contract admission for the first class vertical
must record it explicitly.

An unknown `T` still cannot be duplicated without a declared guarantee.
Monomorphization must not retroactively accept an invalid generic body because
T happens to become a class. A generic forwarding body can transfer its incoming
owned token; a concrete caller supplying a known class lvalue creates that token
by aliasing. Class-aware generic sharing constraints, and generic code that
needs to duplicate a handle, wait for a separate capability decision. Initial
class admission may reject class-containing generic applications until these
paths and ownership re-synthesis are qualified; it must not silently broaden Copy.

Expected unoptimized cost, excluding evaluation of arbitrary argument/body code:

| Operation | Cost/ownership |
|---|---|
| Construction | One object allocation plus field-owned allocations, header initialization, field stores and initializer work |
| Lvalue assignment to new handle | One retain and handle store; O(1), no field copy |
| Replacing a handle | Retain/acquire RHS, publish replacement, release old; old release may cascade |
| By-value lvalue parameter | Retain at argument ownership acquisition, callee cleanup release unless transferred onward |
| Explicit `ref`/`ref mut` parameter | Borrow slot, no RC for reference formation; call receiver stabilization may separately require it |
| Return | Transfer fresh token; otherwise retain before cleanup; balanced local retain/release may be eliminated with proof |
| Direct method | Direct call plus receiver keepalive; no vtable lookup |
| Virtual method | Receiver keepalive, descriptor/slot loads, indirect call |
| Interface adaptation/call | Metadata selection/pair construction; owned adaptation retains unless transferring; call loads witness slot and calls indirectly |
| Release/destruction | Constant count decrement if non-final; last release runs recursive field cleanup and frees allocation, potentially large cascades |
| Equality | Identity comparison after ordinary operand evaluation |

The conservative receiver protocol pins the evaluated object with one temporary
retain before arguments and releases after the call; a fresh temporary can
supply its existing owner. Eliminate the pair only if another ownership token
is proven to keep that **object**, not merely the original slot, alive across
argument evaluation and the body. A borrowed receiver still owns no token of
its own; the caller's keepalive is explicit IR cleanup.

For the Counter example: two owning locals give count 2; a conservative method
keepalive raises it to 3 during the call and returns to 2; releasing b gives 1;
releasing a destroys the object. Trivial-copy optimizations, load commoning and
ARC elimination must not treat shared mutable fields as immutable. Inspection
dumps should expose Alias, transfer, keepalive, retain/release and dispatch kind.
Do not promise zero cost or count elision at a chosen optimization level.

## 34. Generic classes and interfaces

`class Box<T>` fits declaration-owned `GenericParamId`, canonical applications
and the existing monomorphization worklist. Add kind-safe class/interface generic
owners and instances, rather than encoding them as structs or strings. Each
concrete class instantiation has its own field layout, descriptor, drop glue and
virtual table when needed. Recursive handle fields have finite representation;
inline recursive value layout remains invalid. Recursive generic expansion
still needs the current instance/depth termination controls.

Class fields containing T require positive storage guarantees and concrete
initialization/drop support. Constraints are checked even for unused generic
bodies; canonical substitutions resolve before MIR/SSA. Distinct applications
are invariant initially: `Box<Dog>` is not `Box<Animal>`.

`interface Comparable<T>` can later have an exact witness per concrete interface
application and implementing class application. Declared conformance may forward
T only with proved requirements. Generic interface values use specialized
contracts, not an untyped runtime dictionary for arbitrary T. Do not conflate
interfaces with the closed `Copy/Relocatable/Storable/Add/...` capability system.
User interface constraints, object safety, variance and generic methods require
separate admission. Neither generic classes nor generic interfaces belongs in
the first two verticals.

## 35. Static members

Defer static fields and methods. Free functions already express behavior without
a receiver; static fields would require module/global initialization order,
ownership and threading decisions absent from the current entry model. No
singleton initialization, global executable code or static constructors follow
from classes. Later namespace-qualified static functions are compatible with
the type model but unnecessary to validate identity.

## 36. Properties

Explicit getters/setters are sufficient initially. C#-style properties can avoid
repetitive accessors, but a field-looking expression may then invoke code,
dispatch, allocate or fail. That is material semantics, not merely saved typing.
No accessor syntax or property lowering is reserved/admitted now. A later
proposal must distinguish stored fields from computed access, declare receiver
effects and specify evaluation count/order for compound assignment.

## 37. Methods and free functions

Methods organize behavior that naturally belongs to an identity/type and can
enforce its private invariants. Free functions remain the ordinary home for
algorithms, mathematical kernels, cross-type operations and module organization.
There is no universal object wrapper, extension-method mechanism or requirement
to rewrite existing native mathematical operators/functions as methods.

## 38. Modules and nominal identity

Assign `ClassId`/`InterfaceId` from declarations owned by existing modules;
canonical TypeIds refer to those identities. Equal spelling/layout in different
modules remains distinct. Imports resolve bases/interfaces statically using
the current direct-import rule. Transparent aliases preserve the underlying
declaration and do not create a conformance or a new object kind.

Use logical module/declaration identities and concrete arguments for stable
mangling, never raw session IDs or absolute paths. Public API validation checks
visibility of every referenced type and relationship. No new package system,
runtime class loading or retroactive external conformance is introduced.

## 39. Exceptions connection

Keep **EXCEPTION-ARCH-1 independent**. A conventional Exception base class would
provide shared state and subtype catches but require inheritance; an Exception
interface would constrain behavior without prescribing state; arbitrary nominal
structs/enums could instead preserve value-oriented errors. No universal base
is needed for the object model, and nothing here requires exceptions to be classes.

If classes can eventually be thrown, exception storage must own/transfer a
strong token until handling/propagation ends, preserving identity across catches.
Throwing an existing alias must not leave a borrowed payload after scope cleanup.
Struct/enum throws would need their own move/drop or erased carrier rules.
Unchecked exceptions and a C#/C++-like experience are future direction, not a
choice of throw eligibility, catch matching, unwinding ABI or failure types now.
Constructor partial cleanup and destructor failure must join that later design;
the current aborting trap policy is unchanged.

## 40. Nullability boundary

Every admitted class/interface handle refers to a live initialized object.
Uninitialized construction storage and moved-from internal slots are compiler
states, never source values. An empty class still needs identity/allocation.
No null expression, implicit zero handle, Option type, nullable `?`, failed weak
upgrade result or nullable cast is added. Future nullability has an independent
architecture milestone and cannot be smuggled in through RC implementation.

## 41. Low-level compatibility

Explicit lexical references remain non-owning capability paths. Future raw
pointers need visible unsafe boundaries and cannot silently create ARC owners.
Foreign integration should use opaque handles with explicit borrow/retain/
release or ownership-transfer functions; C struct layout is not implied.
Callbacks that keep a pointer beyond a call need ownership, not a borrowed slot.

Custom allocators can be recorded in a descriptor/control block with a matching
deallocator. Non-intrusive foreign payload adapters remain possible. Stack-only
identity objects or region classes would need an explicit representation/lifetime
mode and cannot implicitly escape as ordinary shared handles; proving a heap
allocation removable is a separate optimization with the same observable
identity/lifecycle. Pinning, address exposure and thread transfer remain deferred.
The private bootstrap layout must not become a permanent barrier to these modes.

## 42. HIR implications

Proposed vocabulary, not Rust declarations to implement now:

| HIR fact | Responsibility |
|---|---|
| Class/interface declarations | Kind-safe IDs, module ownership, visibility, generics, base/conformance graphs |
| Method/initializer identity | Complete signature, receiver capability, constructor role, override target |
| Field access | Exact declaring class/FieldId, access path, initialization/ownership category |
| Constructor application | Selected initializer and concrete class, before allocation lowering |
| Method call | Direct target or explicit virtual/interface requirement identity; receiver evaluated once |
| Class upcast/interface adapt | Proven relation, source/target capabilities, ownership mode |
| Handle use | Alias versus transfer versus borrow, independently of structural Copy |

Extend the static arena honestly with new nominal kinds. HIR resolves all member
names and effects from declarations, checks receiver bodies, and records cleanup
obligations. Preserve current ownership synthesis as the semantic authority but
extend its categories; do not derive shared aliasing from `is_copy` alone.
Parametric checking and concrete substitution remain separate stages.

## 43. MIR implications

MIR makes the receiver/arguments/order and initialization state explicit in
CFG and places. Conceptual operations include ObjectAlloc, FieldInit,
PublishInitializedObject, HandleAlias/Retain, HandleTransfer, Release,
BorrowObject, DirectMethodCall, VirtualCall and InterfaceCall. Names are not
an opcode commitment; existing typed operations should be reused when their
contracts truly match.

Class object projections are distinct from handle-slot projections. Cleanup
tracks owning tokens/conditional initialization rather than pointer SSA uses.
Keepalive spans argument evaluation and nested calls. Owned return transfer
precedes local releases. Allocation/retain/release and dispatch effects must
remain visible before LLVM. Keep partial initialization representable without
admitting exceptions; abort paths may terminate without cleanup under today's
contract. No virtual call or general alias can use an unpublished object.

## 44. SSA implications

Preserve exact class/interface TypeIds, relation metadata, ownership effects,
initialization publication and call signatures through SSA construction.
Block parameters/phis of owned handles transfer one obligation per executed
incoming edge; joining pointers neither duplicates nor discards ownership.
Carrier merges require the exact interface type and a witness valid for each
incoming object's dynamic class. Do not merge capabilities by erasing mutability.

ARC and calls remain ordered effects, not pure pointer arithmetic. Verify
dominance and all incoming paths independently. Reentrant calls may mutate
shared fields even through a read receiver if another writable alias exists.
Optimization needs proofs for devirtualization, lifetime shortening, alias
analysis and retain/release pairing, then re-verification. No backend inference
from mangled method names or LLVM pointer equality replaces semantic identities.

## 45. LLVM and runtime implications

LLVM lowers only verified concrete SSA: private object layouts, descriptor/drop
glue, initialization stores, checked RC operations and typed indirect calls.
The runtime supplies allocation/free and the selected RC failure behavior behind
a versioned internal boundary. Non-atomic counts match the admitted single-thread
profile; no `noalias` follows from either receiver `mut` or source `ref mut`.

Exact type metadata needed for dispatch/drop can exist without public RTTI.
Emit interface witness adapters for concrete class/interface pairs and preserve
capability/ownership ABI contracts despite erased machine pointer receivers.
The backend must not synthesize an omitted retain, constructor initialization
or destructor ordering rule based on target convenience. No legacy runtime
import, tracing hooks or public ABI freeze is required.

## 46. Fail-closed verifier obligations

HIR, MIR and SSA each validate the facts needed at their boundary, using immutable
declaration/type context, never trusting a previous pass's boolean success flag.

| Obligation | Required independent rejection/proof |
|---|---|
| Exact identity | Valid class/interface IDs, canonical arguments and declaring field/method ownership; same layout is insufficient |
| Relation graph | At most one open class base, only valid interfaces, no cycles/duplicate canonical edges; imports/access satisfied |
| Override/conformance | Exact parameter/result/ownership/receiver contract, legal visibility and target openness |
| Dispatch | Slot belongs to selected class/interface requirement; witness matches dynamic object; target calling convention exact |
| Initialization | Allocation precedes field initialization; no read before init, no normal publication with missing fields, no `this` escape |
| Receiver | Live initialized object, correct static relation, sufficient capability, keepalive covering argument and call effects |
| Handle ownership | Alias creates an obligation; transfer consumes exactly one; borrow creates none; each normal path releases/transfers every owned token |
| Replacement | RHS acquired before old release, new value published consistently, self-alias safe |
| Destruction | Dynamic destruction glue, each initialized field once in order, one free, no post-final-release use or resurrection |
| Interface adaptation | Nominal relation, correct witness/carrier pair, no payload copy, preserved access, exactly one token per owning carrier |
| CFG/SSA | Dominance, exact joins, conditional cleanup and ownership modes agree on each executed edge |
| Storage/borrows | Positive storage legality and no forbidden stored/interior borrow; future alias-invalidating mutation requires explicit proof |
| Unsupported slice | Early rejection of deferred generics, inheritance, modifiers, interior refs, defaults, exceptions and nullable syntax |

Static verification balances ownership operations compositionally; it does not
solve arbitrary runtime graph reachability or prove a numerical refcount for
every heap object. Runtime checks cover counter validity; neither mechanism
detects all strong cycles. Future malformed-IR tests must independently corrupt
identities, slots, witnesses, capabilities, initialization, joins and cleanup.

## 47. First implementation vertical: concrete class identity

Recommend **OOP-V1 — concrete class identity and lifecycle** (planning label).
One non-generic final class kind; fields limited as in section 24; one explicit
initializer; private/public members; direct read/mutating methods; implicit
`this`; non-null allocation; Alias/transfer/release; identity equality; existing
module identity. Use scalar-returning methods so this slice does not accidentally
depend on resolving the separate void/unit question.

Include the narrow private Buffer<int> field to show the last alias recursively
destroys a real existing owner, not just an empty object allocation. Do not
expose interior borrows, collection operations through class fields, class graph
fields, generic classes or class-containing generic applications in this slice.
No inheritance/interfaces, virtual tables, user destructor hooks, exception
unwinding, nullable types, statics or properties.

Required future qualification (not tests added/run by this milestone):

- Native Counter aliasing observes 1; independent objects compare unequal,
  aliases equal; rebinding one alias leaves the other object's state intact.
- Lvalue parameter/return aliasing, fresh-result transfer, self-assignment,
  branch cleanup and early normal return balance object and nested Buffer counts.
- Receiver survives an argument/nested call that rebinds the original owner;
  conservative keepalive appears in dumps and is balanced.
- Private access, read-to-write escalation, read method mutation, constructor
  escape/read-before-init/missing field and interior ref formation fail early.
- Malformed HIR/MIR/SSA ownership and identity operations fail independently;
  admitted value structs/enums/generics/refs/mathematical owners retain behavior.
- LLVM/native allocation/free evidence validates identity and nested destruction;
  report baseline and optimized costs without assuming ARC elision.

This is enough to validate shared ownership, mutation and lifecycle before
dispatch. A parser-only class declaration is not a successful vertical.

## 48. Second implementation vertical: flat nominal interfaces

Recommend **OOP-V2 — non-generic class-backed interfaces**, before inheritance.
It depends only on concrete classes and exercises the central erased owning
carrier, capability contract and indirect dispatch without base construction,
override graphs or layout complications.

Admit flat method-only interfaces, explicit `: I1, I2`, exact public signatures,
class-to-interface adaptation, interface alias/parameter/return cleanup and
read/mutating witness calls. Reuse the class ownership model; no boxing, default
bodies, interface inheritance or generic interfaces yet. Qualification must
show the concrete alias observes interface mutation, witness calls select the
right implementation, unrelated nominal matches fail, read access cannot gain
write access, and final release through an interface destroys the same object
and nested Buffer exactly once. Corrupted witness/slot/signature/ownership pairs
must fail verification; adaptation must allocate no wrapper.

Then schedule a separate inheritance vertical: one open base, `open`/`override`,
base initialization, no slicing, dynamic drop, overridden interface witness
selection, and eventually interface-parent adaptation. Stateful inheritance is
not a prerequisite for proving the proposed interface representation.

## 49. Open decisions and admission gates

The recommended identity, non-atomic ARC, Alias-not-Copy distinction, declared
receiver capability, final defaults, nominal conformance and two verticals are
decisions proposed by this milestone. They must not be silently replaced during
implementation. Remaining boundaries:

| Open item | Gate / reason |
|---|---|
| Exact contextual tokens and no-result type | Close before accepting affected syntax; examples here use scalar method results |
| Owned read-only/const handles and sharing constraints | Close before read-path owner escape or generic handle duplication; first slice rejects these |
| Interior class storage access and alias invalidation | Close before projecting refs/views or manipulating shared container fields |
| Class/handle fields, containers of handles and weak edges | Qualify storage/drop and document graph cycles before graph admission |
| User destruction hook and partial unwind cleanup | Separate lifecycle/EXCEPTION-ARCH-1 work; first slice generated cleanup and abort only |
| Generic classes/interfaces, variance and interface constraints | Separate parametric/object-safety and monomorphization admission |
| Protected/final/sealed/abstract, overloads and default bodies | Later bounded inheritance/API design |
| Atomic sharing and cross-thread transfer | No thread crossing until synchronization/isolation contract exists |
| Weak upgrade, nullability, casts/RTTI and throw eligibility | Independent decisions; none is needed for OOP-V1/V2 |
| Layout, allocator hooks and public FFI ABI | Bootstrap private representation only; version before external promise |

Do not use these deferrals to omit the first vertical's Alias classification,
read-path checks, receiver keepalive or nested cleanup: those are required to
make even a scalar Counter with shared identity sound and reviewable.

## 50. Fit with Aether philosophy

The model keeps value structs and scientific storage efficient, uses class
declarations to opt into shared identity, and pays ARC only for that sharing.
It removes repeated relation-kind/type-name spelling while retaining `mut`,
`override`, `open` and visibility where they communicate real API or cost facts.
Static nominal identity, local inference, monomorphization and native verification
remain the compiler foundation. Free functions remain useful. No GC, nullable
side feature or mandatory exception hierarchy is required.

The principal accepted tradeoffs are ARC traffic, possible destruction cascades,
strong-cycle leaks and a third handle-use category separate from structural Copy.
They are explicit architectural choices with bounded validation work, not claims
of free reference semantics. See the [milestone report](OOP_ARCH_1_REPORT.md) for
the deliverable/coverage record and verification scope.
