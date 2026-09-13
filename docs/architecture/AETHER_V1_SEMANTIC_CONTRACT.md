# Aether v1 semantic contract

Status: **working normative contract for the reconstruction**.

Baseline: `ad9282d`, audited 2026-09-01.  This document distinguishes target
decisions from legacy facts.  It does not silently change the current RC.  The
existing compiler remains governed by
[`AETHER_LANGUAGE_SPEC_V1.md`](../aether/AETHER_LANGUAGE_SPEC_V1.md) until a
target decision is implemented and admitted end to end.

Keywords:

- **DECIDED**: architectural/semantic direction fixed for the reconstruction.
- **PROVISIONAL**: baseline to implement and test, reversible only through an
  explicit decision record.
- **LEGACY FACT**: behavior of the compiler at the audited commit, not an
  automatic target decision.
- **OPEN DECISION**: insufficient evidence to choose safely.  Alternatives and
  their consequences are stated; implementation MUST NOT choose accidentally.

## OOP architecture proposal boundary

[OOP-ARCH-1](OOP_ARCH_1.md) records proposed class/interface semantics, including
ARC aliasing distinct from structural Copy and declared receiver capabilities.
That proposal is not itself admission. The OOP-V1 section below incorporates
the qualified concrete class subset; OOP-V2 adds nominal class-backed interfaces;
OOP-V3 adds the bounded inheritance and dynamic-dispatch contract below;
OOP-POLISH-1 adds explicit immediate-base calls and exact class-call
devirtualization. See the
[design report](OOP_ARCH_1_REPORT.md).

## 1. Values and fundamental types

### 1.1 Primitive set — DECIDED

The target primitive set is:

```text
bool
int8   int16   int32   int64
uint8  uint16  uint32  uint64
isize  usize
float32  float64
char
```

The fixed-width integer names denote exactly their stated widths.  `isize` and
`usize` have the pointer width of the compilation target and are the only
fundamental architecture-sized integers.  `float32` and `float64` denote
IEEE-754 binary32 and binary64 on admitted targets.  `bool` is a logical type,
not an integer.  `char` is a Unicode scalar value, excluding surrogate code
points; its ABI representation is not yet fixed.

`void`/unit/no-result is required in function semantics but whether its source
spelling is `void`, `()`, or a unit type is an **OPEN DECISION**.  It is not a
storable primitive until explicitly specified.

The current compiler instead exposes `int` = checked signed i32, `double` =
binary64, `boolean`, experimental `float` and `complex`, and no fixed-width
integer or `char` family.  That is a **LEGACY FACT** and a compatibility input.

### 1.2 Ergonomic aliases — DECIDED

Aliases are transparent: they introduce a spelling, never a nominal type or a
new layout.  User aliases are a v1 language feature and MUST exist before
self-hosting.

The baseline aliases are:

```text
alias int    = int64;
alias double = float64;
alias float  = float32;
alias byte   = uint8;
```

`byte` has no textual or character semantics.  `boolean` MAY be retained as a
compatibility alias for `bool`; that spelling policy is an **OPEN DECISION**.
Nominal wrappers/newtypes are a separate future facility.

Alias expansion MUST terminate, reject cycles, preserve source alias names for
diagnostics where useful and canonicalize before layout/code generation.

### 1.3 Meaning of `int` — DECIDED

`int` is a transparent alias of `int64`.  It is the same semantic type, has the
same range and layout, and does not create a distinct overload, conversion or
ABI identity.  It has a target-independent width and MUST NOT silently follow
pointer width.  `isize` and `usize` are the only fundamental integers whose
width follows the target's natural pointer width.

The rationale is to keep the common spelling comfortable for counters and
scientific/general-purpose integer work without making source meaning depend
on the compilation target.  Explicit `int8`/`int16`/`int32`/`int64` and their
unsigned counterparts remain available when storage, vector density, binary
formats or interoperation require a precise width.

Consequences:

- ABI and layout canonicalize `int` to signed 64-bit.  An Aether function
  spelled with `int` and one spelled with `int64` have the same signature; the
  alias spelling MAY survive only for diagnostics and source metadata.
- This deliberately breaks the legacy compiler's signed checked-i32 `int`
  ABI, IR constants, range diagnostics and affected goldens.  Existing
  compiled objects are not link-compatible merely because the source spelling
  is unchanged; reconstruction artifacts require a new ABI/version boundary.
- An unconstrained integer literal and a locally inferred binding default to
  `int`, hence `int64`.  Context may instead select any representable explicit
  integer type as specified in section 2.1.
- `int` is not an index-sized synonym.  Target layouts and physical offsets use
  `usize`/`isize` where appropriate.  The eventual source indexing API still
  must define its accepted type and checked conversions; choosing `int64` does
  not silently convert negative values to `usize` or settle that later API.
- C FFI canonicalizes Aether `int` as an exact signed 64-bit value (for
  example, C `int64_t` on a conforming binding), never as C `int` or C `long`.
  `isize`/`usize` require a target-specific pointer-width match.  Public FFI
  schemas SHOULD prefer the explicit canonical spelling `int64` even when
  source APIs use `int`.

### 1.4 Complex numbers — OPEN DECISION

`complex64` (two `float32`) and `complex128` (two `float64`) are required early
design inputs.  The options are primitive types, core compiler-known structs,
or ordinary core-library generics with intrinsic/operator support.

Compiler-known core types are the leading option: they permit predictable
layout, literals and vectorization without treating complex numbers as scalar
machine primitives.  The decision requires C/Fortran ABI experiments,
operator/conversion rules, transcendental semantics and LLVM codegen evidence.

## 2. Literals and numeric conversions

### 2.1 Literal typing — DECIDED

Integer and real literals MUST retain exact source magnitude (and for reals,
source spelling or an exact parsed representation) until contextual typing.
The host language's integer/float behavior MUST NOT define acceptance.

Integer literals are compiler-only abstract/contextual values until the
surrounding expression requires a concrete type.  The same literal may become
`int8`, `uint32`, `int`/`int64`, or another explicit integer type exactly when
its mathematical value is representable in that type.  Contextual literal
conversion is not a runtime numeric conversion and must not wrap, saturate or
truncate.

```aether
int8 a = 42;
uint32 b = 42;
int c = 42;
x = 42;       // conceptually unconstrained: defaults to int/int64
```

Without a constraining context, an integer literal resolves to `int`, hence
`int64`.  Without a constraining context, a floating literal resolves to
`float64`.  This defaulting happens after the exact literal has been parsed;
the compiler does not first coerce through a host integer or host float.

Vertical-13 confirms that an integer literal spelling may be selected directly
as a contextual floating literal when the expected type is `float32` or
`float64`, including inside Array literals. This is compile-time literal
typing, not an implicit conversion from an already typed integer value; the
ordinary integer-to-floating conversion rule in section 2.2 remains explicit.

Range errors are compile-time diagnostics:

- when context chooses a concrete integer type, reject a value below its
  minimum or above its maximum and report the value, target type and range;
- when no context exists, apply the `int64` default and diagnose values outside
  that range;
- preserve the unsigned magnitude and source span through unary sign handling
  so the minimum signed value (for example `-9223372036854775808` for `int64`)
  can be recognized without first constructing an invalid positive value;
- constant evaluation uses mathematical/exact intermediates and diagnoses a
  known unrepresentable result rather than inheriting host overflow.

Literal suffix syntax remains an **OPEN DECISION** and is not needed for
NEXT-VERTICAL-0.  Contextual literals do not imply general implicit narrowing
for non-literal values.  The current decimal-only, immediate `int32`/`double`
behavior remains a legacy oracle and compatibility input, not the target rule.

### 2.2 Implicit conversions — PROVISIONAL

Implicit conversion MUST be value-preserving for every source value.  At
minimum this permits widening within signed or unsigned families and
contextual exact conversion of a literal.  Signed↔unsigned, narrowing and
float→integer conversions MUST be explicit.

Integer-to-floating conversion is not implicit in the scalar baseline because
not all 32/64-bit integer values are exactly representable in binary32/binary64.
Source must request it with the explicit conversion syntax below. Mixed
arithmetic does not create a special exception, and no conversion depends on C
integer promotion rules.

**NEXT-VERTICAL-3 implemented baseline (2026-09-01):** contextual literals may
select any representable scalar numeric type. Already typed values widen only
along `int8 -> int16 -> int32 -> int64`, `uint8 -> uint16 -> uint32 -> uint64`,
and `float32 -> float64`. `isize`/`usize` do not implicitly convert to or from
fixed-width types. Signed/unsigned, integer/floating, narrowing, and bool/numeric
conversions are rejected. HIR makes admitted conversions explicit; MIR and SSA
perform no numeric inference.

**NEXT-VERTICAL-4 explicit-conversion baseline (2026-09-01):** the source form
`TargetType(expression)` denotes a value conversion when the target resolves to
a primitive numeric type or transparent alias. It is not an ordinary call,
constructor, bitcast, reinterpretation or unsafe cast. HIR records the exact
source type, target type and selected conversion category; MIR and SSA preserve
that decision without adding conversions.

All integer-to-integer combinations are explicit and checked. A value converts
only if it is exactly representable in the target; otherwise execution traps
with `ConversionOutOfRange`. A statically known failure is diagnosed instead.
This includes narrowing and signed/unsigned boundaries, and applies to the
distinct `isize`/`usize` types using the target pointer width. There is no
wrapping explicit cast.

Integer-to-float conversion uses the source signedness and may round when the
integer is not exactly representable. Float-to-integer truncates toward zero,
then requires the result to be representable; NaN, either infinity and values
whose truncated result is out of range trap with `ConversionOutOfRange`.
Checks precede backend `fptosi`/`fptoui`, so poison or undefined backend results
are not source behavior. `float32 -> float64` and `float64 -> float32` are both
available explicitly; narrowing follows IEEE rounding and preserves the
finite/infinity/NaN category as the target format permits. Numeric conversion
to or from `bool` is invalid.

### 2.3 Integer overflow — DECIDED baseline

Ordinary signed and unsigned integer arithmetic has checked semantics.  If its
mathematical result is not representable in the operation's concrete result
type, execution traps with `IntegerOverflow` unless the compiler can diagnose
the failure statically.  Overflow is never undefined behavior and never
silently wraps.  `-O0` through `-O3` MUST preserve this meaning; a release or
optimization profile cannot remove a required check without proof that the
operation is in range.

For NEXT-VERTICAL-0 this rule covers the admitted ordinary integer addition,
subtraction, multiplication and signed negation operations.  Integer division
or remainder by zero traps with `DivisionByZero`; the signed minimum divided by
`-1` traps with `DivisionOverflow`.  A constant expression whose failure is
known is rejected at compile time with the same failure category and a source
span.  Otherwise MIR carries an explicit checked operation/trap edge and the
backend materializes the check.

Future explicitly requested `wrapping`, `checked` (value/status result) and
`saturating` operation families are reserved.  Their API or syntax is an
**OPEN DECISION**; their future existence does not weaken ordinary arithmetic.
Shift counts, exponentiation and any unchecked conversion/escape hatch remain
outside this baseline and require separate exact rules before admission.

## 3. Floating point

### 3.1 Representation and optimization baseline — DECIDED

`float32` is IEEE-754 binary32 and `float64` is IEEE-754 binary64 on admitted
targets.  `float` is a transparent alias of `float32`; `double` is a
transparent alias of `float64`.  A floating literal without a constraining
context defaults to `float64` as specified in section 2.1.

Normal optimization levels preserve the language's floating semantics.  `-O3`
(or equivalent) MUST NOT imply fast math.  Relaxed/fast mathematics will be a
separately requested policy, visible in build metadata, and cannot be inferred
from the optimization level.

This fixes formats and defaults, not every operational detail.  Until the open
items below are decided, the optimizer and backend must use conservative
settings: no reassociation, contraction, no-NaN/no-infinity assumptions,
signed-zero disregard or flush-to-zero may be introduced merely because
optimization is enabled.

### 3.2 Floating details — OPEN DECISION

The contract still needs decisions for, and NEXT-VERTICAL-0 does not need to
admit floating operations before they close:

- implicit integer/float conversion and rounding modes beyond the explicit
  conversion baseline in section 2.2;
- NaN comparison/propagation and payload behavior;
- infinity-producing operations and domain/pole behavior;
- subnormal preservation or target-profile restrictions;
- signed-zero observability;
- permitted fused multiply-add contraction in strict mode;
- exact parse/format algorithms and shortest-roundtrip requirements;
- reproducibility across targets versus conformance within a target;
- explicit rounding-mode APIs and whether ambient hardware mode is observable;
- constant evaluator parity with target execution;
- libm accuracy requirements for transcendental functions.

LLVM constrained floating-point intrinsics, ordinary FP instructions and
target attributes must be evaluated against this list.  A global fast-math bit
is insufficiently precise for mixed strict/relaxed code.

**NEXT-VERTICAL-3 operational baseline:** literals are rounded by the bootstrap
compiler to IEEE binary32 or binary64 after contextual type selection. The
backend emits ordinary LLVM floating operations with no fast-math flags and no
contraction request. Comparisons use ordered predicates for `==`, `<`, `<=`,
`>`, and `>=`, so each is false if either operand is NaN. `!=` uses unordered
not-equal and is true if either operand is NaN. This closes comparison truth
values for the scalar subset; NaN payload propagation, ambient rounding modes,
cross-target bit reproducibility and constant-folding parity remain open.

### 3.3 Integer division and remainder — DECIDED baseline

NEXT-VERTICAL-4 implements typed integer quotient: after the ordinary
same-family widening rules, `integer / integer` returns that same integer type.
Signed quotient truncates toward zero; unsigned quotient is ordinary unsigned
division. A zero divisor traps with `DivisionByZero`. Signed `MIN / -1` traps
with the distinct `DivisionOverflow` category before backend division executes.

`%` is remainder corresponding to that quotient, not an always-nonnegative
mathematical modulo. Thus `-5 % 2 == -1`, and for valid division operands
`a = (a / b) * b + (a % b)`. A zero divisor traps. Signed `MIN % -1` is zero
and uses guarded control flow so LLVM's problematic `srem` case never executes.

Floating `/` accepts same/promoted floating operands and follows IEEE behavior,
including infinity or NaN for zero divisors; it does not use integer trap
semantics. Integer-to-float conversion remains explicit, so merely mixing an
integer and float does not make `/` valid. Floating `%` is not admitted.

This deliberately diverges from the legacy compiler, where `int / int`
produced `double`. Compatibility evidence labels the difference as intentional;
legacy code requiring real division must convert an operand explicitly.

## 4. Evaluation, calls and assignment

### 4.1 Evaluation order — DECIDED

Expressions, call arguments and assignment subexpressions evaluate left to
right.  `&&` and `||` short-circuit.  An optimizer may reorder only when it
proves the change unobservable under effects, traps, floating semantics and
aliasing.

### 4.2 Initialization — DECIDED

A value cannot be read before initialization.  Construction of an aggregate
must either initialize every required field or fail without exposing a
partially initialized value.  Definite-initialization analysis is a semantic
phase; zero-filled allocation is not proof of source initialization.

Whether all local declarations require an initializer or types may define a
default value is an **OPEN DECISION**.  Any default MUST be type-owned and
cannot invent a null handle for non-null reference types.

### 4.3 Assignment, copy and move — DECIDED for primitive scalars / PROVISIONAL otherwise

Assignment denotes logical replacement of the destination after the right-hand
side has been evaluated successfully.  Self-assignment must be safe.  A failed
operation MUST NOT leave a destination half-replaced.

The target lifecycle vocabulary is:

```text
initialize(place, value)
copy(place, value)
move(place, value)
assign(place, value)
destroy(place)
```

Primitive `bool`, every signed/unsigned integer type, `float32`, `float64` and
`char` have value semantics.  Their initialization, assignment, argument
passing and return copy the scalar value and introduce no ownership, ARC,
destruction or observably shared alias.  `int`, `float` and `double` inherit
this rule through transparent aliasing.  NEXT-VERTICAL-0 therefore needs no
borrow or lifecycle analysis for its admitted scalar locals.

Value aggregates recursively follow field semantics.  Move transfers
ownership and makes the previous owning place unavailable.  Whether a
source-level move is implicit from last use, explicit, or both is an **OPEN
DECISION** for nontrivial values.  The existing Initial IR lifecycle operations
and verifier are valuable executable evidence, not automatically the final
surface model.

NEXT-VERTICAL-10 closes this rule only for `Buffer<T>`: initialization from an
owning expression, assignment, by-value argument passing and return implicitly
move the buffer handle. The source becomes unavailable immediately and
use-after-move is a static error. Replacing a live Buffer destroys its previous
allocation after the right-hand side succeeds; exact self-assignment is a safe
no-op. Lexical scope exit and every normal return destroy each still-owned
Buffer exactly once. This does not settle the eventual general move syntax or
last-use policy for arbitrary nontrivial values.

NEXT-VERTICAL-11 generalizes the same implicit consuming use to every concrete
non-Copy nominal aggregate. Copy and destruction are structural properties of
canonical concrete `TypeId`, not declaration-wide flags: a struct is Copy iff
all substituted fields are Copy and needs destruction iff any substituted
field does; an enum applies those rules across every payload in every variant.
The properties remain independent; symbolic queries explicitly report that
their result is not yet concrete. Whole-value moves invalidate the complete
source root. Moving an owning field out is rejected in V11 because partial-move
states are not represented. Whole-local replacement is admitted: evaluate the
new value first, recursively destroy the old destination, then transfer the
new owner. Exact self-assignment remains a no-op.

### 4.4 Function calls — DECIDED/OPEN

Arity, parameter and return types are statically checked.  Public/exported
function signatures are explicit except for narrowly specified local/private
inference.  Nontrivial return ownership is explicit in semantic IR.

Vertical-11 applies the V10 Buffer rule structurally: any non-Copy aggregate
passed by value consumes its argument, while `ref T`/`ref mut T` parameters
borrow it. Returning a non-Copy aggregate transfers ownership to the caller.
The complete parameter-mode syntax remains an **OPEN DECISION**; a single
implicit “borrow everything” convention is insufficient for FFI, buffers and
returned views.

The bootstrap `int main()` return is the process exit status; successful
applications conventionally return 0. Tests that return observable values such
as 42 use the native process status as a bootstrap computation probe. Those
nonzero fixtures are qualification technique, not idiomatic successful
application examples, and V13 does not change this entry-point contract.

### 4.5 Nominal value structs — NEXT-VERTICAL-5 DECIDED baseline

Vertical-5 admits nominal, module-owned structs whose fields are recursively
value-semantic scalars, transparent aliases, or other finite Vertical-5
structs. Two struct declarations are distinct types even when their names,
fields and target layouts coincide. Transparent aliases preserve the one
underlying `StructId`; they do not create nominal wrappers.

The canonical construction syntax is positional application syntax:

```aether
Point(3.0, 4.0)
Segment(Point(0.0, 0.0), Point(1.0, 1.0))
```

Arguments correspond to fields in declaration order, with exact arity and the
ordinary contextual-literal/widening rules. This form is structural aggregate
construction: it creates no function, invokes no user code and is not a
user-defined constructor. `Point { x: 3.0, y: 4.0 }`, named arguments, methods
and user-defined constructors are not admitted. A future general named-argument
facility may cover both functions and struct construction without changing the
Vertical-5 positional meaning.

The parsed application form is semantically neutral. HIR resolves it to a
concrete `FunctionId`, a scalar conversion, or `StructInit(StructId, fields)`;
no call-like ambiguity reaches MIR. Functions, structs and aliases occupy one
fail-closed top-level namespace in each module. Imported structs remain directly
qualified (`geometry.Point`) for both type use and construction.

Field access and mutation resolve source names once to `FieldId` projections.
Nested assignment denotes replacement of the projected subvalue. Struct
initialization, assignment, parameter passing and return copy the complete
logical value, with no identity, sharing, heap storage, ARC or destruction.

### 4.6 Nominal payload enums and exhaustive matching — NEXT-VERTICAL-6 DECIDED baseline

Vertical-6 admits nominal, module-owned enums with payloadless variants and
positional value payloads. Equal names and payload types do not make two enum
declarations equivalent. Construction is qualified (`Number.Integer(42)`,
`State.Idle`); imported enums remain directly qualified and variants never
enter unqualified scope. Transparent aliases preserve enum identity and may
qualify construction.

`match (value) { Enum.Variant(binding) => { ... } }` is initially a statement.
Every variant occurs exactly once with exact positional binding arity. No
wildcard, guard, OR/range/nested/reference pattern or expression-valued match is
admitted. Bindings are ordinary function-local values copied from payloads.
Enums recursively containing Vertical-0..6 value types copy by value; direct or
mixed struct/enum by-value cycles are rejected as infinite.

The bootstrap discriminant is unsigned 32-bit and declaration ordered from
zero. LLVM uses a deterministic typed tagged envelope without niche
optimization or type-punning. Discriminants, physical layout and aggregate
calling convention remain internal rather than stable source/public ABI.
`Result`, `Option` and similarly named enums receive no language magic.
Direct or mutual by-value recursive layouts are rejected as infinite-size.

## 5. Mutability, ownership and aliasing

### 5.1 Mutability — DECIDED

Binding mutability and pointee/value mutability are distinct.  Read-only access
through one alias does not prove the underlying shared object immutable.
Mutation requires a statically permitted path.  `const`/immutable API spelling
remains open.

### 5.2 Ownership model — PROVISIONAL

The model combines:

- by-value semantics for scalars and suitable aggregates;
- moves for unique owned resources;
- explicit shared ownership, normally ARC, when aliasing requires it;
- non-owning access with a lifetime limited by analysis or an explicit API;
- a future low-level pointer facility behind the escape hatch.

ARC is not inserted for every value.  Cycles, weak references, atomic versus
non-atomic counts and concurrency are **OPEN DECISIONS**.  The compiler MUST
retain ownership/alias facts through optimization rather than reconstructing
them from opaque runtime calls.

### 5.3 Non-owning references — NEXT-VERTICAL-9 DECIDED baseline

Vertical-9 admits explicit, non-null, non-owning references:

```aether
ref T
ref mut T
&place
&mut place
*reference
```

`ref T` grants read capability through that reference. `ref mut T` grants read
and write capability. In this baseline `mut` does **not** mean unique,
exclusive or `noalias`: multiple mutable references and shared/mutable overlap
may designate the same storage. Read-only access through one `ref T` proves
only that writes cannot occur through that capability; another alias may still
mutate the object. No Rust-style exclusivity checker or LLVM `noalias`
attribute follows from these types.

Borrow creation requires an existing addressable Place (a local, nested field,
or dereference projection). Rvalues, calls and aggregate temporaries are not
borrowable and receive no temporary lifetime extension. Dereference is
explicit; `*r` reads the pointee and is assignable only when `r : ref mut T`.
Aggregate field access through a reference is spelled `(*r).field`. Parameters
and call arguments retain explicit reference syntax, and the bootstrap ABI
passes an address rather than a copied pointee.

The V9 lifetime rule is deliberately conservative. References may be function
parameters, temporary call arguments and initialized local bindings. Reference
locals have one initialization and cannot be rebound. References cannot be
returned, stored in struct fields or enum payloads, captured or instantiated as
generic type arguments. A generic parameter may appear underneath `ref` in a
parameter (`ref T`) and is substituted normally. With mandatory local
initializers, lexical name visibility and no reference rebinding or return,
these rules make a dangling local reference inexpressible without general
region inference. Reference values copy only the non-owning view; they never
copy, retain, release, move or otherwise own the pointee.

Backend pointers are an internal representation, not raw-pointer source
semantics. There is no null reference expression, address equality, pointer
arithmetic, integer/reference cast or address exposure. Returning views,
storing views, reallocation invalidation, concurrency/async crossings and a
future unique/restrict capability remain **OPEN DECISIONS**. Vertical-9 itself
introduced no heap allocation, ARC, destruction or move-only value;
Vertical-10 adds the deliberately bounded Buffer case below without changing
reference alias capabilities.

### 5.4 Fixed owning buffers and contiguous views — NEXT-VERTICAL-10 DECIDED baseline

`Buffer<T>` owns one fixed-length contiguous allocation. It is move-only,
needs destruction and has no implicit deep copy, retain/release or shared
ownership. `T` is restricted in this baseline to a concrete `Copy` type that
does not need destruction or contain borrowed/owning substructure. Nested
Buffer or borrowed descriptor elements and symbolic `Buffer<T>` in
generic bodies are rejected until generic capabilities for Buffer elements are
represented explicitly. V11 permits Buffer fields and enum payloads because
their containing aggregate now receives structural move/drop semantics.

Definite ownership state is checked across control flow. An owned local may be
uninitialized, owned, moved or dropped. Continuing branches must agree on the
ownership state, and loop-carried ownership moves are rejected in this
baseline. A Buffer cannot move or be replaced while a local reference or view
derived from it remains live. Cleanup on aborting traps is not required;
exceptional cleanup depends on the future recoverable-error model.

`View<T>` and `ViewMut<T>` are Copy, non-owning pointer-and-length descriptors.
They expose contiguous element storage rather than Buffer container identity.
`View<T>` reads and `ViewMut<T>` additionally writes. They never transfer or
extend owner lifetime. V10 applies the conservative V9 non-escape rules:
single-initialization locals and parameters are allowed, but returns, aggregate
storage and generic arguments are rejected. Buffers never resize, so an element
reference remains stable while its owner remains alive.

### 5.5 Transitive nominal aggregate ownership — NEXT-VERTICAL-11 DECIDED baseline

The compiler owns one memoized type-property query keyed by canonical concrete
`TypeId`. Scalars, references and views are Copy/no-drop; Buffer is
non-Copy/needs-drop. Concrete structs combine every substituted field and
concrete enums combine every substituted payload in every variant. Recursive
queries fail closed. An unresolved generic parameter reports `is_known=false`
and is not guaranteed Copy; parametric bodies may move/pass it through but may
not duplicate it. Concrete monomorphizations re-synthesize ownership using
substituted properties, so
`Holder<int>` and `Maybe<int>` remain Copy while their `Buffer<int>` instances
are move-only and need destruction.

Aggregate construction consumes each non-Copy field/payload argument. A
temporary owner transferred into an aggregate is not independently destroyed.
Moving a whole aggregate invalidates all access through the old root, including
Copy fields. Partial moves are rejected. Borrow provenance follows nested field
and index places to the owning root, which cannot move or be replaced while a
derived local borrow/view is live.

Compiler-generated drop glue recursively destroys struct fields in reverse
declaration order. Enum glue inspects the active discriminant, destroys only
the active variant's drop-requiring payloads, and processes multiple payloads
in reverse declaration order. MIR and SSA retain a general typed owner `Drop`;
the LLVM bootstrap backend expands that semantic operation. LLVM may bit-copy
an aggregate representation during a verified move, but this never grants
source Copy semantics.

Variant-only enum matching (with no payload binding) and Copy payload bindings
remain supported. Binding a non-Copy payload by value is rejected until
match-by-value/ref/ref-mut and partial ownership are designed. Stored
references/views remain forbidden, including transitively. The V10 Buffer
element restriction remains unchanged:
V11 composes ownership outward and does not add element drop glue inside a
Buffer. Traps still abort without unwind cleanup.

### 5.6 Ownership-aware matching and conditional cleanup — NEXT-VERTICAL-12 DECIDED baseline

Enum match ownership is selected explicitly for the whole match. Value mode is
spelled `match (value)`: Copy enums retain value-copy behavior, while a non-Copy
enum is consumed before control enters any arm. Bound payloads have type `T` and
non-Copy payload ownership transfers in declaration order. The source root and
the transient wrapper are not dropped after the whole-root destructure; bound
payload locals own their values and omitted drop-requiring payloads are still
destroyed. This is a dedicated consuming enum operation, not permission for
ordinary field extraction or partial moves.

Shared and writable modes are `match (ref value)` and
`match (ref mut value)`. They require an existing addressable enum Place and
bind every written payload as exactly `ref T` or `ref mut T`, independently of
whether `T` is Copy. The source owner remains valid. A ref-mut binding may
modify the selected active payload, but carries no uniqueness/noalias meaning.
Payload addresses are formed only in the tag-selected arm. Match-created
references obey the conservative V9 non-escape policy and cannot be returned,
stored, rebound into an outer reference local or otherwise outlive the arm.

Whole-root ownership dataflow has `Owned`, `Moved` and `MaybeMoved` states at
continuing program points (plus internal initialization/drop states). Equal
incoming states remain equal; `Owned + Moved` becomes `MaybeMoved`; any merge
with `MaybeMoved` remains `MaybeMoved`. Terminating branches do not contribute
to a later join. Every ordinary use, read, borrow, move, match or replacement
requires `Owned`; `Moved` and `MaybeMoved` are compile-time errors. There is no
runtime-checked ordinary ownership use.

Cleanup treats `Owned` as an unconditional recursive drop, `Moved` as no drop,
and `MaybeMoved` as a conditional recursive drop. Only a root that reaches an
actual conditional cleanup receives a compiler-generated boolean flag. The flag
is initialized and updated explicitly in MIR, becomes ordinary SSA/phi state,
and controls a normal CFG branch around the existing typed `Drop`. Flags are
never source-addressable and never per-field/per-payload. The policy applies to
every concrete `needs_drop(TypeId)`, including owning structs, active-variant
enums and concrete generic aggregates; it does not alter `is_copy` or
`needs_drop` themselves.

Early returns preserve path sensitivity and avoid unnecessary flags. A loop
backedge whose next iteration could observe a changed ownership state remains
rejected; conditional flags do not make repeated use safe. Existing lexical
owner-liveness rejects a conditional move while a derived reference/view is
live. Traps still abort without unwind cleanup. V12 adds no Array, reallocation,
general conditional initialization, destructor trait, ARC, exception handling
or general partial-move state.

### 5.7 Fixed-size Array ownership — NEXT-VERTICAL-13 DECIDED baseline

`Array<T>` is non-Copy and needs destruction. Initialization, whole-value
assignment, by-value arguments and return transfer its unique allocation using
the general V11/V12 ownership machinery; there is no Array-specific move
analysis, implicit deep copy, ARC or Buffer conversion. It may be stored in
struct fields, enum payloads and concrete generic aggregates, whose existing
structural type-property and recursive drop rules apply unchanged.

Because Array never changes length or relocates, references and views derived
from an element stay address-stable. Existing conservative owner-liveness rules
still prevent moving or replacing the owner while such a borrow remains live.
Normal cleanup frees the allocation exactly once. Elements are temporarily
restricted to concrete Copy/no-drop types, so V13 requires no per-element drop
loop. Conditional ownership uses the same root-level `MaybeMoved` flags as any
other owning aggregate.

### 5.8 Dynamic List ownership and storage borrows — NEXT-VERTICAL-14 DECIDED baseline

`List<T>` is non-Copy and needs destruction. Whole-value assignment,
by-value calls, returns, aggregate composition and conditional cleanup use the
general V11/V12 ownership lattice; List introduces no container-specific move
state. Normal drop frees the current allocation exactly once. V14 elements are
Copy/no-drop, so no per-element destruction loop is required.

References and views derived from List element storage additionally retain the
owning List root as storage provenance. While such a borrow is lexically live,
`push` and `reserve` are rejected as potentially invalidating structural
mutations regardless of runtime capacity. Element assignment is not structural.
Passing the List through `ref mut List<T>` to an arbitrary call is
conservatively potentially invalidating; passing `ref List<T>` is not. This
temporary rule awaits an effect system and adds no alias exclusivity or LLVM
`noalias` promise.

### 5.9 Owned collection elements and relocation — NEXT-VERTICAL-16 DECIDED

Array/List element admission is the centralized conjunction: a concrete `T`
is Relocatable, current storage/lifetime analysis proves it storable, and it
contains no forbidden reference or view. Neither non-Copy nor `needs_drop` is a
rejection reason. Buffer retains its V10 element restriction because its only
constructor repeats one fill value and V16 does not add uninitialized Buffer
storage or an owned-element literal.

An Array/List literal evaluates elements in source order and transfers one
semantic owner into each destination slot. A non-Copy local is moved and may
not subsequently be used; a non-Copy temporary has exactly one cleanup
destination. Push applies the same type-property-driven rule. In contrast,
`Array<T>(length, fill)` duplicates its fill value and therefore requires
`T: Copy` even when `Array<T>` itself is otherwise a legal type.

Relocate is a compiler-internal physical transfer distinct from source Move.
Its verified contract is one initialized source object, one uninitialized
destination slot, the same `TypeId`, a Relocatable type, and an uninitialized/
dead source after success. List growth applies this operation in increasing
index order to exactly `[0,length)`. Generated relocation glue cannot trap:
capacity arithmetic and allocation complete first. Descriptor owners transfer
their handles without pointee copies or frees; structs relocate fields in
declaration order and enums relocate the discriminant plus only active payloads.

Array/List drop glue visits initialized elements in reverse index order and
then frees backing storage. List does not inspect `[length,capacity)`. Struct
fields and active enum payloads retain reverse declaration order. Relocated old
List slots receive no Drop before the old backing allocation alone is freed.
Nested Array/List values remain separate owners, never a Matrix
representation.

## 6. Core data abstractions

### 6.0 `Buffer<T>` — NEXT-VERTICAL-10 DECIDED substrate

`Buffer<T>(length, fill)` is the no-uninitialized-memory construction surface.
Length and zero-based index operands are `usize`; every element is initialized
from the Copy fill value. Indexing a Buffer or View is checked. A provable
constant failure is a diagnostic; dynamic failure aborts with
`IndexOutOfBounds`. Length-times-element-size overflow aborts with
`AllocationSizeOverflow`, and allocation failure aborts with
`AllocationFailure`. These traps do not unwind in V10.

Buffer/View physical lowering is an internal `{ data pointer, length }`
descriptor. Element size and alignment come from canonical target layout.
Allocation/free happen through a compiler runtime boundary, not through a
source raw-pointer or allocator API. The bootstrap implementation uses the
platform allocator and counts normal-path allocation/free balance in generated
Buffer programs as qualification instrumentation.

This is lower-level storage for future `Array`, `List`, `Vector` and `Matrix`
work, not the final Array abstraction. V10 adds no capacity, resize,
append/insert/remove, slicing syntax, raw pointers, allocator selection, ARC or
general-purpose ownership.

### 6.1 `Array<T>` — NEXT-VERTICAL-13 DECIDED baseline

`Array<T>` is the ordinary fixed-size computational collection. It owns exactly
`length` initialized contiguous elements; length never changes after
construction and allocated element count equals logical length. It has no
capacity concept, growth, `push`, `pop`, `reserve`, `resize` or reallocation.
It is semantically and canonically distinct from `Buffer<T>`, which remains the
lower-level explicit storage primitive. No implicit conversion exists between
them, although the bootstrap backend shares allocation and descriptor
machinery.

The canonical literal syntax is `{...}`, including `{}` for length zero. The
parser records a neutral collection literal, and semantic analysis requires an
expected `Array<T>` before producing resolved `ArrayInit` HIR. This preserves
the syntax now shared with List without making braces an Array-only AST node. Fill
construction `Array<T>(length, fill)` independently creates a runtime-sized
fixed Array. Every literal element and fill value is checked with ordinary
contextual literal/coercion rules. V13 temporarily requires `T` to be concrete,
Copy and no-drop without borrowed or owning substructure; symbolic `Array<T>`
remains rejected in V15 because public Copy/Relocatable constraints do not
express the full internal admission predicate.

Index operands have semantic type `usize`, indexing is checked and zero-based,
and a dynamic failure is `IndexOutOfBounds`. `length(array_place)` is the
provisional bootstrap query surface and resolves to semantic `ArrayLength` HIR,
MIR and SSA rather than a stringly method call. Desired property syntax such as
`array.length` awaits a coherent property/method system. Slices/views are
separate non-owning `View<T>`/`ViewMut<T>` values.

### 6.2 `List<T>` — NEXT-VERTICAL-14 DECIDED baseline

`List<T>` is the growable computational collection. It is canonically distinct
from `Array<T>` and `Buffer<T>`, has no implicit conversion to either, uses
zero-based indexing and shares the neutral `{...}` collection literal syntax
with Array. Expected-type resolution produces `ListInit` without parser-level
List syntax. `{}` has length and capacity zero with no allocation; a nonempty
literal allocates once, initializes in source order, and begins with length and
capacity equal to the element count.

The bootstrap descriptor is `{data pointer, length, capacity}` and maintains
`0 <= length <= capacity`. Only `[0, length)` contains initialized objects.
`[length, capacity)` is reserved raw storage and is never accessible through
source indexing or views. Bounds checks compare with length, and a whole-List
view spans exactly the initialized prefix.

`length(list)` and `capacity(list)` resolve to `ListLength` and `ListCapacity`.
`push(list, value)` and `reserve(list, requested)` resolve to `ListPush` and
`ListReserve`; both carry explicit structural-mutation classification through
HIR, MIR and SSA. Push uses checked arithmetic, ensures capacity, initializes
`data[length]`, then publishes the new length. Reserve leaves length unchanged
and guarantees at least the requested capacity. Exact growth factors and spare
capacity values are implementation details.

Growth is semantically allocate-copy-free-update rather than libc `realloc`:
allocate checked `capacity * sizeof(T)` storage, copy exactly `[0, length)`,
free the replaced allocation, then update pointer and capacity. V14 admits only
concrete Copy/no-drop elements without borrowed or owning substructure;
symbolic `List<T>` remains rejected in V15 because reallocation still copies
elements and has no element drop glue.

Array remains fixed-size and has no capacity, growth, push or reserve. List is
not the storage model for matrices. `pop` is intended for List but deliberately
deferred until its empty-result/error semantics are designed. Resize, insert,
erase, non-Copy elements and a general method/property
surface are also outside V14.

### 6.3 `Vector` — V21 foundation; Matrix V23 and MatrixView V24 below

`Matrix<T>` has contiguous dense storage by default with dimensions and
ownership represented explicitly in semantic IR. V23 owners have no stored
strides; V24 borrowed MatrixView values carry explicit strides. It is not
`Array<Array<T>>`, `List<List<T>>` or nested Vector literals. A future sparse
matrix is a different type/family.

`Vector<T, Orientation>` carries Row/Column orientation in its mathematical
semantics and type because orientation changes multiplication validity and
result type. V21 resolves Row/Column as intrinsic compile-time orientation
arguments in canonical TypeData; it does not introduce general value generics.

Vector literal syntax is `[a, b, c]`. Matrix literal syntax is one
two-dimensional construct whose semicolons separate rows:

```aether
[
    a, b;
    c, d
]
```

Both mathematical types use one-based source indexing; Matrix access is
`A[i, j]`. Their bracket AST/HIR forms remain structurally distinct from the
neutral `{...}` collection literal. V21 implements the Vector foundation below;
Matrix syntax and mathematical operations remain deferred.

Static dimensions are also open.  Dynamic dimensions must work; optional
compile-time dimensions may enable specialization without making ordinary
matrix types unwieldy.

Natural operations—shape queries, element access, addition/subtraction,
multiplication and transpose—belong to the core type/operator model.
Factorizations, solvers, eigensystems and decompositions belong to libraries.
The exact multidimensional indexing grammar representation below the source
form remains an implementation decision; it must not turn Matrix into nested
collections.

All core scientific operations MUST remain recognizable before lowering to
loops/runtime calls so the compiler can later select fusion, buffer reuse,
SIMD or BLAS.

#### V21 fixed-dimensional Vector contract — DECIDED

`Vector<T,Row>` and `Vector<T,Column>` MUST be distinct canonical TypeIds.
Repeated element/orientation resolution MUST reuse the same TypeId. Orientation
is not a runtime field or an incidental HIR annotation. No implicit orientation
conversion or Array/Vector conversion is admitted.

`[...]` MUST produce a distinct mathematical AST node and resolve only with
expected Vector context. Both orientations share this literal shape. Each
operand uses normal contextual element typing/coercion; literals transfer
non-Copy operands exactly once. `[]` is valid for both orientations, owns a
null/zero descriptor and has dimension zero with no heap allocation.

Element admission requires T: Storable, including symbolic T. It MUST NOT
require Copy, Relocatable or Numeric merely for fixed storage. Vector owns
contiguous fixed-dimensional initialized storage. It has no capacity, resize,
push/reserve/pop/remove/swap_remove contract. Its bootstrap descriptor contains
only pointer and dimension. Dimension is fixed for each constructed value;
ordinary whole-owner reassignment may install a different constructed value.

`dimension(vector_place)` MUST resolve to VectorDimension and return usize
without consuming the owner. Every index operand is usize. Vector indexing is
valid exactly when `1 <= i <= dimension`; known-invalid direct constants are
rejected, otherwise failure traps with IndexOutOfBounds. Lowering MUST prove or
check the lower and upper bounds before computing i-1 or issuing an inbounds
GEP. The IndexSemantics carried by each Place projection MUST match its canonical
container type, independently verified in HIR/MIR/SSA. Nested storage MUST use
each descriptor's own semantics, never its outer owner's index base/extent.

Copy reads and writes, shared element references and mutable element references
are admitted. Ordinary non-Copy reads by value and partial owning replacement
remain unsupported and MUST fail closed. Borrowing an owning element and
mutating its Copy subobjects remains legal. No hidden clone/drop operation may
approximate partial replacement.

Vector is non-Copy and needs_drop. Ordinary root ownership handles moves,
consuming parameters, returns, structs, enums, generics and conditional cleanup.
Drop MUST visit initialized elements in reverse logical index order n..1 and
then free the backing allocation exactly once. No Vector-specific ownership
state or runtime orientation is introduced. Live element references retain owner
liveness requirements; fixed Vector storage does not structurally invalidate
addresses. Nested mutable Lists retain their independent invalidation rules.

Public raw View/ViewMut conversion from Vector MUST be rejected because it
would discard orientation and one-based semantics. V25 below defines VectorView as a
separate mathematical abstraction. `[a,b; c,d]` remains reserved for a future
structurally 2D Matrix literal, never parsed as nested VectorLiteral. No vector
arithmetic, dot, outer, norm, transpose, Matrix, methods, traits or numerical
capability system is admitted in V21.

#### V22 explicit consuming Vector transpose — DECIDED

`transpose(v)` MUST map Vector<T,Row> to Vector<T,Column> and Vector<T,Column>
to Vector<T,Row>. The result MUST be derived from the operand's canonical type,
preserving the exact element TypeId without expected-orientation guessing.
Direct assignment between orientations MUST remain invalid. The source syntax
is an ordinary application with one owning Vector operand and no explicit type
arguments. Array, List, Buffer, scalar and reference operands MUST be rejected
with a structured Vector-transpose diagnostic.

The operation MUST consume the Vector owner regardless of whether T is Copy.
The result MUST own the identical backing allocation and preserve its pointer
and dimension bit-for-bit. This is a strong O(1) contract with exactly zero
allocations, frees, element copies, relocations, reconstruction or drops during
transpose. Empty null/zero descriptors MUST remain unchanged. Components MUST
retain their order and values. Transpose MUST NOT reverse or conjugate elements,
apply numeric transformations or call element functions. Conjugate transpose
is a separate future operation.

T: Storable is sufficient, checked parametrically before monomorphization.
Neither Copy, Relocatable nor Numeric is an additional requirement. In particular,
Vector<Buffer<int>,Row> transfers only the outer descriptor; no Buffer element
or pointee is touched. The final owner performs ordinary reverse-index element
destruction and one backing free. The moved source MUST NOT destroy storage.

Existing move, live-borrow, conditional ownership and cleanup rules apply;
shared and mutable element borrows block consumption while live. No special
borrow escape or partial-field move exception is admitted. Return, consuming
call, aggregate construction and cross-module signatures retain exact types.
The statement `consume(transpose(v));` admits a declared function with a
guaranteed Copy result that is discarded. An owning call result requires an
explicit binding; V22 adds no void type or implicit owning-result destruction.
Successful results support ordinary one-based indexing, Copy writes and borrows.
Double transpose restores the original orientation with the same descriptor.

HIR VectorTranspose and MIR/SSA VectorTransposeMove MUST preserve source and
result TypeIds, prove equal element types/opposite orientations and consume one
owner to produce one owner. Canonical Vector types define compatible descriptor
layout; no runtime orientation metadata is permitted. Independent verifiers
MUST reject corrupt type/orientation metadata and duplicated transpose owners.
LLVM MUST transfer the same aggregate bits without backing operations or runtime
orientation branches. Transpose MUST NOT become a scalar cast or arbitrary
reinterpret operation. Qualification MUST check per-operation pointer/dimension
identity and zero allocation/free/relocation deltas.

Borrowed transpose, VectorView, Matrix transpose, methods, apostrophe syntax,
arithmetic, conjugation and numeric capabilities are outside V22.

### 6.4 Bounds — DECIDED

Safe indexing and slicing check bounds and trap or return the language's
specified error form.  Optimization may remove a check only with a proof.
Unchecked indexing requires an explicit low-level operation/region. Index base
is type-dependent, never a configurable global switch. `Buffer`, `View`,
`ViewMut`, `Array` and `List` are zero-based. Vector is one-based; future
Matrix and mathematical views will also be one-based.

### 6.5 Initialized storage extraction — NEXT-VERTICAL-18 DECIDED

`pop(list_place)` returns T for a writable `List<T>` place, including explicit
`pop(*reference)` through `ref mut List<T>`. Shared/read-only access cannot pop.
List's existing Storable + Relocatable requirements suffice parametrically;
no Copy requirement or runtime capability dispatch is added.

The operation MUST check `length > 0` before computing `length-1` or accessing
storage. Empty pop MUST take structured `ListEmpty` without storage mutation.
Traps abort without unwind. This contract does not introduce Option/try_pop or
prevent a future independent library optional form.

On success, Take transfers the one initialized tail T to an ordinary result and
ends the old slot's initialized lifetime. The source slot becomes Uninitialized,
including for Copy T. The length becomes exactly `old_length-1`; pointer and
capacity MUST remain unchanged. Extraction performs no heap allocation, free,
reallocation, shrinking or movement of surviving elements. Transfer after the
check is non-trapping for admitted types. The result follows ordinary ownership
semantics in locals, returns, consuming arguments and aggregate construction.

The invariant is that exactly `[0,length)` contains live initialized elements.
Reserved slots and the taken tail are raw storage. Take is distinct from a
source Move (which marks a source root Moved) and Relocate (which transfers
between storage locations). List drop visits only the new prefix. Push can
initialize the old tail again; it must not drop the already-taken value.
No per-slot runtime bitmap or extra tail drop flag is permitted.

The compiler MUST distinguish ordinary checked logical indexing from internal
typed storage-slot addressing. MIR and SSA retain and verify the nonempty edge,
Take transition and prefix commit. Corrupted state, repeated extraction, a
missing/wrong boundary commit or Drop of a taken slot must be rejected. The V18
implementation admits a bounded contiguous checked transaction, without a
general memory or partial-initialization analysis.

Element assignment is element mutation; pop is stable structural/range mutation;
push/reserve remain potentially relocating mutations. A live direct constant
reference to an earlier element is permitted when current length facts prove it
excludes the removed tail. Definite tail, unknown-index and unknown-length
borrows fail closed. Whole-list View/ViewMut covers the old initialized prefix
and therefore blocks pop until its lexical lifetime ends. No ranged view or
arithmetic theorem prover is implied. Nested borrow provenance remains
conservative; a surviving inner allocation alone is not a sufficient proof.
Borrowed call arguments stay live while subsequent arguments are evaluated;
arbitrary calls with writable access to List-containing types conservatively
invalidate storage/length knowledge. Calls restricted to scalar/Copy elements
do not constitute structural List mutations.

Array keeps fixed, fully initialized storage. V18 adds no Array take, general
field partial move, remove/insert/swap_remove/drain/pop_front, methods, Option,
Buffer expansion, named lifetimes, Vector or Matrix.

### 6.6 Indexed owning extraction — NEXT-VERTICAL-19 DECIDED

`T removed = swap_remove(list_place, index);` removes one element without
preserving List order. The target MUST be a writable List Place; explicit
`swap_remove(*list, i)` supports `ref mut List<T>`. The index follows ordinary
List rules: usize, zero-based, no implicit signed conversion. The result is T,
including owning non-Copy T, and may be returned or consumed directly.

The operation MUST evaluate the requested index once and check it against a
fresh descriptor length N. Failure (`index >= N`, including N = 0) takes the
normal structured `IndexOutOfBounds` trap before Take, relocation, tail
subtraction or length mutation. No Option or boolean failure result is added.

After the check, `tail = N-1` is safe. Take transfers slot[index] to the ordinary
result and changes that slot from Initialized to Uninitialized. If index equals
tail, no Relocate occurs. Otherwise exactly one element Relocate transfers the
initialized tail to the uninitialized removed slot: the hole becomes Initialized
and the old tail becomes Uninitialized, without source Drop or duplication.
Only after these transitions complete may length commit to tail. Take,
Relocate and commit are non-trapping for admitted elements.

The final initialized prefix MUST be exactly `[0,N-1)`, with no interior hole.
For `[10,20,30,40]`, removing index 1 returns 20 and leaves `[10,40,30]`.
Copy elements obey the same slot liveness transitions. Owning descriptors move
without deep copying their pointees; aggregates use recursive relocation glue.
Intended time complexity is O(1), modulo element relocation glue cost.

Pointer and capacity MUST remain unchanged. The operation performs zero heap
allocations and frees, including element ownership. All later queries, indexing,
push, moves, returns and drop observe the new descriptor length. Drop destroys
survivors in reverse FINAL index order; the relocated tail is destroyed at its
replacement index, and the extracted result has its ordinary separate owner.
Push may reuse the raw old tail without allocating when capacity suffices.

The effect is `StableStructuralMutation` at the List backing level. Its logical
invalidation shape is `{index, tail}`, reduced to one slot in the tail case.
Live shared/mutable borrows that may cover either slot block extraction. Direct
constant references provably outside that set survive; unknown borrow/removal
indices or length facts fail closed where distinctness cannot be proved.
Whole-list View/ViewMut covers the old sequence and blocks extraction until
scope exit. Writable descriptor aliases retain underlying root identity.
Nested provenance remains conservative, without runtime pointer comparisons.

MIR and SSA MUST independently verify the bounded Take/optional-Relocate/commit
transaction, actual bounds and tail branch edges, fresh operands, exact typed
slot identities and unique extracted ownership. Length continues to represent
the runtime initialized prefix; no per-slot bitmap, general partial initialization
or rollback mechanism is introduced. Existing pop retains its V18 transaction.

Generic bodies require the existing `T: Storable + Relocatable` guarantees
before monomorphization; there are no runtime capabilities. Order-preserving
removal is specified separately in 6.7. V19 itself adds no remove, insert,
range erasure, drain, methods, try_swap_remove/Option, Array extraction, Buffer
changes, lifetimes, traits, Vector or Matrix.


### 6.7 Order-preserving List remove — NEXT-VERTICAL-20

`T removed = remove(list_place, index);` requires a writable List<T> Place and
an ordinary zero-based usize index. Dereferencing `ref mut List<T>` is explicit.
The removed element transfers exactly once to the expression result, including
owning/non-Copy T; the existing Storable + Relocatable requirements suffice,
checked parametrically before monomorphization. There are no runtime capability
dictionaries, boolean/Option results or new extraction primitives.

The index is evaluated exactly once. A fresh List length N MUST be read and
`index < N` checked before tail subtraction, Take, relocation or commit. Failure
is the structured IndexOutOfBounds trap and leaves the List unchanged, including
for N=0. On success tail=N-1, Take(index) ends the slot's initialization and
produces the ordinary result. Take remains non-trapping.

The remaining sequence preserves order: `{10,20,30,40}` with index 1 returns
20 and leaves `{10,30,40}`. In contrast, swap_remove leaves `{10,40,30}`.
Intended remove complexity is O(N-index), modulo relocation-glue cost, with
exactly N-index-1 element relocations. Swap_remove retains intended O(1).

The compiler MUST represent and verify this overlapping storage protocol:

```text
hole = index                    // after Take(index)
while hole < tail:
    next = hole + 1             // proven <= tail; cannot overflow
    Relocate slot[next] -> slot[hole]
    hole = next
require hole == tail
commit length = tail
```

At each header, `[0,hole)` is Initialized with final values, hole is
Uninitialized, and `(hole,N)` is Initialized old suffix. Each forward Relocate
requires initialized source and raw destination, leaves the destination
Initialized and source Uninitialized, and relocates each suffix element once.
Backward, duplicated and skipped transfers are invalid even for Copy T. There
is no Copy/deep-copy requirement, source Drop, runtime bitmap or rollback.
Take(tail) immediately satisfies the exit invariant: tail and singleton cases
execute no relocation body. At commit `[0,tail)` MUST be initialized and old
tail MUST be Uninitialized. No effect, trap or side exit may observe the hole.

MIR and SSA MUST independently verify this invariant inductively on their
actual CFG: initial hole, roots, fresh index/length, exact successor, forward
transfer, initialization transitions, loop bound, backedge and only exit to
commit. It is insufficient to count instructions. Only expected hole/control
phis may occur; extracted owners and owning elements must not be phi-duplicated.
The implementation resolves projected descriptor addresses before the transaction
so no checked outer indexing runs inside it. Typed compiler-derived relocation
glue is non-trapping. Memmove is not semantic ownership authority.

Pointer and capacity MUST remain unchanged. Remove itself performs no allocation
or free, including element ownership allocations. Only length changes, after
all transfers finish. Subsequent length/capacity, indexing, push/pop/swap_remove/
remove, drop and owner move/return MUST observe fresh descriptor state through
aliases and projections. Reserved remove+push reuses capacity, transferring the
removed owner through its result into the new tail exactly once.

The backing effect is StableStructuralMutation. SuffixFrom(index) invalidates
all old element slots in `[index,N)`: the removed object disappears, later
objects change address, and the old tail disappears. A live direct ref/ref mut
with provable borrowed_index < removal_index survives. Otherwise affected,
dynamic or unknown index relations are rejected conservatively. Whole View and
ViewMut cover the old sequence and block removal until scope exit. Writable
aliases identify the same root; there are no noalias assumptions or generalized
layered-provenance proofs. Ambiguous nested provenance may be over-rejected.

Drop traverses only `[0,new_length)` in reverse FINAL index order. Relocated
owners drop once at their new location, the old tail is never dropped, and the
removed result follows normal lexical cleanup independently. For Buffer payloads
`{10,20,30,40}` removing 1, the List drops 40,30,10; a later-declared result
normally drops 20 first. Counters are test instrumentation, not public API.

This vertical adds only remove. It adds no insert, range erase, drain,
try_remove/Option, methods, lifetimes, traits, Array removal, Buffer extension,
Vector, Matrix, optimizer pass or MemorySSA.

## 7. Text

### 7.1 `byte`, `char` and `string` — DECIDED

- `byte` is transparent `uint8` and carries no encoding.
- `char` is one Unicode scalar value, not one UTF-8 byte and not a UTF-16 code
  unit.
- `string` is immutable, non-null, valid UTF-8 text with explicit byte length.

String equality compares Unicode scalar sequences; because valid UTF-8 has a
unique byte encoding, byte comparison is sufficient.  No implicit Unicode
normalization or locale collation occurs.

### 7.2 String indexing/slicing — OPEN DECISION

Raw integer indexing into `string` is not admitted until its unit and complexity
are unambiguous.  Options are no direct indexing (iterators/views only), scalar
indexing with non-constant cost, or distinct byte/scalar/grapheme APIs.  Byte
access must return `byte`/byte slices and make the encoding boundary explicit.

Slicing must define boundary validity, ownership and whether it returns an
owned string or borrowed `str`-like view.  Grapheme operations belong in a
Unicode library, not the primitive runtime contract.

### 7.3 String representation and ABI — PROVISIONAL

Immutable shared UTF-8 storage with an empty singleton and ARC is a useful
baseline proven by the current runtime.  Short-string optimization, rope
representation and public header layout are not commitments.  Runtime/FFI uses
opaque handles or explicit `{pointer, byte_length}` borrowed views with written
ownership; C NUL termination is never inferred.

## 8. Nullability and errors

### 8.1 Nullability — OPEN DECISION

The current compiler implements tagged `T?`, does not use null pointers as
values and has no flow-sensitive narrowing.  The target must decide among
`Option<T>` as a generic tagged union, postfix `T?` sugar, or both.  Niche
optimization may be an ABI-internal representation only when semantics and FFI
remain explicit.

No ordinary owning/reference/string value is implicitly nullable.  The
decision depends on tagged unions, pattern matching and error handling and
must precede public ABI stabilization.

### 8.2 Scalar traps — DECIDED

NEXT-VERTICAL-0 models non-recoverable scalar failures explicitly in Flow MIR.
A trap is a typed/structured terminator or checked-operation failure edge with
a source span, not an arbitrary backend string or a host-language exception.
The admitted scalar failure kinds are:

```text
IntegerOverflow
DivisionByZero
ConversionOutOfRange
DivisionOverflow
```

The first covers checked addition/subtraction/multiplication/negation. The
second covers integer division and remainder with a zero divisor. The third
covers runtime-failing explicit conversions, and the fourth distinguishes
signed `MIN / -1` from ordinary arithmetic overflow.
Verified MIR and verified SSA must make every possible trap explicit enough
for control-flow, effect and optimization checks; optimizers preserve its
observable ordering unless they prove the failure impossible.

The bootstrap backend/runtime may initially lower a trap to an abort or target
trap plus an appropriate diagnostic and non-success exit.  Exact rendering,
exit code and runtime symbol ABI remain implementation contracts to qualify,
not a recoverable language error facility.  Because this slice owns no
nontrivial resources, it requires neither unwinding nor cleanup edges.

### 8.3 Recoverable errors, panic and exceptions — OPEN DECISION

The repository has a qualified native exception model plus typed result structs
for parsing/files, while native safety panics currently terminate without
unwinding.  The reconstruction must choose and distinguish:

- recoverable expected errors (`Result<T,E>` or equivalent);
- language exceptions, if retained;
- unrecoverable panic/contract failure;
- foreign/runtime errors across the C ABI.

The choice controls MIR exceptional edges, cleanup, ABI, code size and
self-hosting ergonomics.  Raw Rust/C++ exceptions MUST NOT cross FFI.  The
structured scalar traps in section 8.2 are intentionally separate from this
future recoverable model and do not decide whether exceptions, `Result` or
unwinding eventually exist.

## 9. Modules and initialization

### 9.1 Modules — PROVISIONAL

Each source module has a stable logical identity independent of absolute paths.
Name resolution, visibility and import cycles are checked before codegen.
Wildcard import is not required.  Imports do not execute through a separate
interpreter.

The package/root discovery mechanism and project manifest are **OPEN
DECISIONS**.  The existing file-to-module mapping and `ModuleId`/`SymbolId`
work are reusable evidence.

### 9.2 Initialization order — OPEN DECISION

The current native profile rejects imported mutable global storage and module
initializers while the AST interpreter supports more.  The target needs rules
for constants, globals, lazy/eager initialization, cycles, failure and exactly-
once execution.  No module initialization feature is supported until it has a
single native ordering and lifecycle model.

## 10. Generics

### 10.1 Model — DECIDED

Generics are parametric and constraint-based.  Generic declarations are
represented before typechecking is complete; constraints are explicit
semantic predicates/capabilities, not substitution failure.  Generic arguments
may be inferred only when the solution is unique and diagnostics can explain
the constraint path.

Native code normally uses monomorphization/specialization.  The compiler MUST
also define canonical substitution identities, deterministic mangling,
cross-module instantiation ownership, recursion limits and cache keys.

### 10.2 Remaining generic decisions — OPEN DECISION

- constraint/trait/protocol surface syntax and coherence;
- separate compilation versus whole-program instantiation;
- code-size controls and optional shared generic implementations;
- variance and subtyping interactions;
- const/type-level parameters for orientation and dimensions;
- overload rules and specialization;
- public ABI of generic functions/types;
- diagnostics and cycle/recursion limits.

No architecture layer may erase generic identity before constraint checking
and monomorphization decisions.

### 10.3 Canonical compiler type identity — IMPLEMENTED INFRASTRUCTURE

The reconstruction represents every resolved semantic type from HIR onward by
a session-local canonical `TypeId`. Equal semantic types in one compilation
have the same ID. The ID is an implementation identity only: it is not source
semantics, ABI, serialized metadata or a cross-session stable key.

Transparent aliases resolve to the underlying ID and never create nominal type
identity. Nominal structs and enums remain distinct because their canonical
type data refers to distinct declaration IDs, independent of layout equality.
Architecture-sized integers retain categories distinct from fixed-width
integers; target layout resolves their width and does not canonicalize `isize`
to `int64` or `usize` to `uint64`.

Target layout is queried from canonical semantic type plus target properties.
The current single-target compilation session may cache the result by type ID;
no cache or ID is persistent across sessions. Future generic parameters and
applications extend canonical type data and substitution contexts rather than
reintroducing copied source-type representations in HIR/MIR/SSA.

### 10.4 Parametric generics baseline — NEXT-VERTICAL-8 IMPLEMENTED

Functions, structs and enums may declare unconstrained type parameters after
their declaration name. Binder identity is `GenericParamId { owner, index }`;
equal spellings owned by different declarations are unrelated. A binder has an
interned `TypeData::GenericParam` type. Generic nominal applications use the
kind-safe `StructInstance(StructId, TypeArgsId)` and
`EnumInstance(EnumId, TypeArgsId)` forms. Their recursively interned argument
lists make equal applications share a `TypeId` while preserving nominal
declaration identity.

Generic bodies are resolved and typechecked once under their declared
parameters. An unconstrained parameter supports ownership-moving binding,
storage, passing and returning, but supplies no implicit duplication,
arithmetic, comparison, conversion or
unknown-field capability. Declared fields of a generic struct and variants of a
generic enum remain statically known. This is parametric checking, not
instantiation-dependent template validation.

Calls support explicit type arguments. Limited local inference unifies direct
parameter patterns against call arguments, including exact nested nominal
applications; no return-context, global or constraint inference is performed.
An explicit `Substitution` recursively maps declaration-owned parameters to
canonical `TypeId`s. Concrete function calls are canonicalized as
`(FunctionId, type arguments) -> InstanceId`. A deterministic worklist
substitutes already checked generic HIR, discovers transitive calls and emits
only concrete MIR/SSA. Ordinary recursion reuses an existing instance;
structurally growing recursion is rejected, with depth and instance-count
limits as a safety fallback.

Concrete generic aggregates receive cached target layout by applied `TypeId`.
Unresolved generic declarations have no codegen layout. LLVM named types and
function instances are emitted only for concrete applications, and callable
symbols derive from logical declaration names and structural arguments rather
than raw session IDs. Cross-module use retains the existing direct-import
qualification rule. Transparent aliases may name a concrete generic type;
generic alias declarations are not admitted.

This baseline deliberately added no constraints, traits, interfaces or
specialization. Generic public ABI and separate-compilation ownership remain
open.

### 10.5 Compiler-derived generic capabilities — NEXT-VERTICAL-15 IMPLEMENTED

V15 adds the inline forms `T: Copy`, `T: Relocatable` and
`T: Copy + Relocatable`. These are a closed set of compiler-derived semantic
capabilities, not traits/interfaces/typeclasses: source code cannot implement,
derive or assert them, and there are no methods, associated types, behavioral
operator predicates, specialization, dictionaries, vtables or dynamic
dispatch.

`Copy` means implicit duplication leaves both values valid. `Relocatable`
means physical movement preserves value and ownership when the old location
ceases to be live under the move rules. They are not synonyms. The central
implication lattice is `Copy => Relocatable`. Scalars, references and views
provide both. Buffer, Array and List are non-Copy but Relocatable under their
descriptor/owned-allocation representation. Structs derive each capability
iff every substituted field provides it; enums do so iff every substituted
payload provides it.

Resolved guarantees belong to `GenericParamInfo` keyed by exact
`GenericParamId`. They are not encoded into `TypeId` and do not turn a symbolic
parameter's concrete `TypeProperties` into fabricated facts. A separate
cycle-protected symbolic query evaluates parameters and applied structs/enums
recursively. Generic bodies and forwarding calls are checked parametrically.
Explicit and inferred applications validate constraints before creating a
function `InstanceId`; inference failure and post-inference constraint failure
remain distinct diagnostics.

Constraints erase before MIR and introduce no LLVM/runtime artifact. Borrow,
provenance and escape restrictions remain independent. Symbolic Buffer, Array
and List elements remain rejected because their current admission also needs
concreteness, no-drop and absence of borrowed/owning substructure; V15 does not
expose those internal facts or generalize non-Copy collection elements.

### 10.6 Symbolic storage interaction — NEXT-VERTICAL-16 DECIDED

V16 operationalizes concrete Relocatable collection elements but does not
equate capability satisfaction with lifetime legality. `T: Relocatable` is
sufficient to derive Relocatable for `Holder<T>`, but not to prove that an
unknown `T` lacks a stored reference or view: those borrowed descriptors also
provide Relocatable. No public negative `NoBorrow` constraint is introduced.
Consequently symbolic Array/List element applications remain rejected with a
storage-proof diagnostic, while concrete substituted generic aggregates are
admitted when the central collection predicate succeeds.

### 10.7 Positive persistent storage — NEXT-VERTICAL-17 IMPLEMENTED

This section supersedes V16's concrete-only Array/List admission and symbolic
storage rejection. `Storable` means that a value may reside persistently as an
owning subobject/element without an unrepresentable lifetime dependency under
the **current** ownership model. It is compiler-derived only. It is not Copy,
Relocatable, no-drop, Sized, lifetime erasure, or a user assertion.

The closed capability set is `Copy`, `Relocatable`, `Storable`; inline grammar
accepts any conjunction (`T: Storable`, `T: Copy + Storable`,
`T: Storable + Relocatable`). The only non-reflexive implication remains
`Copy => Relocatable`. There is no negative constraint, where clause, user impl,
trait dispatch or new grammar family.

| Type | Copy | Relocatable | Storable | needs_drop |
|---|:---:|:---:|:---:|:---:|
| admitted scalar | yes | yes | yes | no |
| `Buffer<int>`, `Array<int>`, `List<int>` | no | yes | yes | yes |
| `ref int`, `ref mut int`, `View<int>`, `ViewMut<int>` | yes | yes | no | no |

A struct is Storable iff every substituted field is Storable. An enum is
Storable iff every payload of every variant is Storable. One forbidden borrowed
payload invalidates that property for the whole enum, even if currently inactive.
Owning descriptors recursively derive Storable from their element. Nested owning
Array/List and owning aggregates require no special whitelist.

Concrete `TypeProperties` has independent `is_known`, `is_copy`,
`is_relocatable`, `is_storable`, `needs_drop`. Symbolic guarantees belong to exact
declaration-owned generic parameters and are derived through applied aggregates;
they never become concrete facts on an unresolved GenericParam. A generic
`T: Storable` remains potentially non-Copy, non-Relocatable and drop-requiring.
`Holder<T>` and `Maybe<T>` derive only the properties guaranteed by all members.

Array element admission requires Storable only. Fixed storage is initialized
once per slot; source value transfer during initialization is not relocation of
an existing initialized Array element. There is no Array growth or post-
construction element relocation. Future address-sensitive types will require an
initialization/ABI design before admission; this vertical adds no such type.
List element admission requires both Storable and Relocatable, as its growth
physically transfers initialized elements to new storage. These predicates apply
parametrically before instantiation, not only after concrete substitution.

`Array<T> a = {x}` is legal under `T: Storable`; the List equivalent and push
need `T: Storable + Relocatable`. Without Copy, a source root is consumed and
unavailable afterward. A Copy guarantee permits reuse. Array fill additionally
requires Copy, independently of storage legality. No capability removes drop
obligations; concrete instantiation supplies the existing recursive drop and
relocation glue, with no runtime capability representation.

Explicit, inferred and forwarded function applications, plus constrained struct/
enum applications, validate capabilities before `InstanceId` allocation.
Diagnostics identify parameter, required capability and actual type. Storage,
relocation and fill duplication failures are distinct. Existing V9 generic
borrow/escape restrictions still apply after capability checking; Storable never
permits reference/view fields, payloads, elements or borrowed returns.

Buffer's semantic storage property and initialization API are distinct. Its
current only initializer repeats a fill and its current drop frees the backing
allocation without element recursion, so the V10 concrete Copy/no-drop source
admission remains an explicit implementation restriction. Broadening Buffer
would require separate type admission, Copy-only fill validation, recursive
cleanup and an initializer that creates every owning element once. V17 does not
implement that extension or claim that storage semantically implies Copy.

No pop/remove, generalized slot extraction, named lifetimes, stored borrowed
lifetime parameters, self-references, pinning, user capability implementations,
behavioral traits, Vector or Matrix are introduced. Zero-based collection and
future one-based mathematical indexing remain separate.

### 10.8 Behavioral scalar constraints — NEXT-VERTICAL-29 IMPLEMENTED

V29 extends the closed source vocabulary with Add, Sub and Mul. Structural
Copy/Relocatable/Storable remain compiler-derived representation guarantees;
behavioral capabilities prove executable homogeneous scalar contracts:

| Guarantee | Bootstrap signature | Concrete integer operation | Concrete float operation |
|---|---|---|---|
| Add | T + T -> T | AddIntegerChecked | AddFloat |
| Sub | T - T -> T | SubtractIntegerChecked | SubtractFloat |
| Mul | T * T -> T | MultiplyIntegerChecked | MultiplyFloat |

Every built-in signed/unsigned integer, isize/usize, float32/float64 and their
transparent aliases satisfies all three separately. bool, references, views,
structs, enums, Buffer, Array, List, Vector and Matrix do not satisfy these
scalar capabilities. Fields supporting Add do not confer Add on a struct.
Constraints on struct/enum arguments do not confer behavior on that nominal
instance. No user implementation or structural behavioral derivation exists.

The existing inline syntax accepts `T:Add`, `T:Add+Mul` and
`T:Copy+Storable+Add` in functions, structs and enums. Guarantees belong to the
exact GenericParamId and remain distinct from concrete classification and
TypeProperties. No cross-family implication is admitted; Copy => Relocatable
remains the only non-reflexive implication. Add does not prove Sub or Mul.

A symbolic T may use only its guaranteed operators with operands/result of the
same canonical T. Generic literals are not identities or arbitrary T values.
Ordinary ownership applies: without Copy, separate operands are consumed, and
reusing one operand requires an independent Copy proof. Missing guarantees are
errors during parametric checking, even for functions never instantiated.
Forwarding, including inferred calls and cross-module calls, must prove all
callee constraints. Concrete arguments failing a constraint are rejected before
InstanceId creation/caching, with the missing capability in the diagnostic.

HIR CapabilityBinary retains a single authoritative Add/Sub/Mul tag, both
operands and the enclosing result T. Independent verification checks equal
operand/result types, symbolic guarantees or concrete built-in satisfaction,
and agreement between generic declaration metadata and the type arena. A
concrete HIR tree after monomorphization MUST contain only reified scalar ops.
Checked integer overflow/underflow raises IntegerOverflow without wrapping;
floats use IEEE fadd/fsub/fmul without fast-math, preserving signed zeros,
infinities and NaNs. MIR/SSA keep their existing scalar semantics and reject
unresolved symbolic types before codegen.

Capabilities have no runtime representation, dictionaries, witness/vtables,
hidden arguments or indirect operator calls. Ordered sets use structural
Copy, Relocatable, Storable then behavioral Add, Sub, Mul order. Constraints do
not enter TypeId identity or instance mangling/ABI: declaration plus concrete
type arguments remains authoritative. HIR dumps display both guarantee families.

V27/V28 concrete container arithmetic is unchanged. Generic container arithmetic,
user operator implementations, traits/interfaces, associated types, Rhs/Output
parameters, heterogeneous operators, Numeric, Zero/One, dot/outer/matmul and
dynamic dispatch remain outside V29.

## 11. Layout, ABI and FFI

### 11.1 Layout — DECIDED/OPEN

Source semantics distinguish logical value, semantic type and physical layout.
Only fixed-width scalars have an immediately fixed bit width.  Aggregate
layout, alignment, padding and calling convention are target-specific unless a
type explicitly requests an interoperable representation.

For the NEXT-VERTICAL-5 bootstrap representation, source declaration order is
both positional-construction order and physical field order; changing it is a
source API change. Size, alignment and padding are computed from the admitted
target descriptor, and the resulting layout/calling convention is explicitly
not public ABI. Reorder permission for a future optimized/default
representation, stable representation annotations and enum/tagged-union layout
remain **OPEN DECISIONS**. Layout facts
must be calculated from a target descriptor, never duplicated as magic offsets
across backend/runtime code.

### 11.2 C FFI — DECIDED direction

C ABI is the primary native interoperation boundary.  FFI declarations must
state calling convention, fixed-width types, mutability, pointer provenance,
buffer length/stride/layout, ownership transfer, allocator/free function,
callback lifetime, error convention and thread requirements.

A canonical schema SHOULD generate C headers, Rust declarations and Aether
bindings.  Opaque handles are preferred for managed objects.  No Rust layout,
C++ STL/template type, Python object, internal string/collection header or
unversioned LLVM struct is public ABI.

FFI syntax, stable representation annotations, callbacks and dynamic linking
are **OPEN DECISIONS**.  BLAS/LAPACK interoperation is an early qualification
case, not a reason to bake one provider into the language.

## 12. Low-level control

An explicit escape hatch is **DECIDED** as an architectural requirement; its
name and syntax are open.  It will eventually cover raw pointers, unchecked
indexing, manual memory, aliasing-sensitive operations, SIMD intrinsics, custom
allocators, FFI and OS interfaces.

The contract must specify which checks are waived, required invariants,
optimizer assumptions, cleanup responsibilities and whether unsafety is
lexically scoped or operation-local.  It MUST NOT disable unrelated checks or
floating-point guarantees globally.

## 13. Decision dependencies and closure order

The highest-impact remaining open decisions should close in this order:

1. numeric conversions beyond contextual literals;
2. recoverable error model and exceptional cleanup;
3. ownership parameter modes, moves and non-owning views;
4. non-lexical/general slice and view lifetime semantics beyond V14 List roots;
5. string indexing/view semantics;
6. generic constraints plus orientation/static-dimension policy;
7. module initialization;
8. runtime handle schema, target layout and C FFI surface;
9. full floating-point/relaxed-math policy and low-level syntax.

Each closure requires source examples, rejected examples, semantic tests,
targeted native codegen evidence, diagnostic expectations and a compatibility
statement against the existing compiler.


## NEXT-VERTICAL-23 — normative Matrix foundation

This section supersedes the earlier reservation of bracket semicolons for
future Matrix syntax. `Matrix<T>` requires exactly one Storable element type;
rows and columns belong to the value, with no static shape or source layout
parameter. Matrix is distinct from Array, List and both Vector orientations.
It is non-Copy, owns fixed stable contiguous storage and participates in normal
move, parameter/return, aggregate and conditional cleanup semantics.

`[...]` preserves mathematical rows until contextual resolution. A comma
separates entries, a semicolon separates nonempty rows, and every Matrix row
must have the same width. Empty brackets mean 0x0 under Matrix context and
zero dimension under Vector context. A single row may initialize either type
according to context; multiple rows cannot initialize Vector. The only trailing
separator accepted is one comma immediately before the closing bracket. No
trailing row semicolon or comma before a row separator is accepted.

Elements use ordinary contextual typing and coercion. Each operand is evaluated
and captured in source row-major order. Non-Copy operands transfer once, with
no implicit Clone or intermediate nested container. Matrix<T> works with
symbolic T:Storable and with structurally Storable nested owning types.

`rows(matrix_place)` and `columns(matrix_place)` return usize. `A[i,j]` takes
two usize operands; a single index or three indices is invalid. Checks proceed
row >= 1, row <= rows, column >= 1, column <= columns. Any failure is
IndexOutOfBounds. Only after all guards may the implementation subtract one,
calculate the physical offset and form an address. Copy element reads and
replacement, shared references and mutable references all obey these checks.
Non-Copy partial extraction and unsafe slot replacement remain rejected.

The bootstrap descriptor is {ptr,rows,columns}, without capacity or strides.
Checked shape multiplication and checked allocation size establish an immutable
representable element count. For valid axes, row0*columns+col0 is less than that
count, proving representable unsigned offset arithmetic. Cleanup destroys
initialized elements in reverse row-major order, then frees the allocation
exactly once; an empty Matrix allocates nothing. Normal traps do not unwind.

Row-major is an implementation choice, not mathematical type identity.
View/ViewMut cannot expose Matrix. Matrix transpose is explicitly unavailable;
swapping descriptor dimensions would incorrectly reinterpret rectangular data.
A future MatrixView or transpose must specify lifetime, strides and layout.
No arithmetic, BLAS, tensor model, Numeric capability or source layout system
is introduced. See [NEXT_VERTICAL_23_REPORT.md](NEXT_VERTICAL_23_REPORT.md).


## NEXT-VERTICAL-24 — normative borrowed MatrixView contract

`MatrixView<T>` and `MatrixViewMut<T>` MUST retain distinct mathematical type
identity from Matrix, View/ViewMut, Array, List and Vector. Their canonical
representation is `MatrixView { element, mutable }`; runtime shape and strides
MUST NOT enter TypeId. Both are Copy, Relocatable, non-Storable and no-drop,
independently of T. Writable descriptors MAY alias; they imply no exclusivity,
no runtime reference count and no LLVM noalias.

`matrix_view(x)` and `transpose_view(x)` produce shared MatrixView<T>.
`matrix_view_mut(x)` and `transpose_view_mut(x)` produce MatrixViewMut<T> only
from a writable Place. Sources MUST be Matrix<T> or either matrix-view type;
a shared view cannot produce a writable view. References require explicit `*`.
The operations MUST borrow the existing owner and MUST NOT consume it.

Descriptors contain `{ptr,rows,columns,row_stride,column_stride}` with strides
measured in elements. From an R by C contiguous row-major owner, normal metadata
MUST be `(R,C,C,1)` and transposed metadata `(C,R,1,C)`. From a view, normal
creation preserves metadata and transpose swaps rows/columns AND row/column
strides. Two transposes restore the descriptor. Empty Matrix has null backing
and canonical 0x0 shape, normal strides `(0,1)` and transposed strides `(1,0)`.
These stride values are internal, not a source inspection API.

All four creation operations MUST have zero allocation, free and relocation
deltas and MUST preserve the source backing pointer. They MUST NOT load/store
or drop backing elements. Reading/copying an existing descriptor is permitted.
There is no source raw-pointer/stride constructor and no arbitrary descriptor
assembly operation in HIR/MIR/SSA. Each boundary MUST independently validate
the closed descriptor recipe against source kind, transpose flag and result
capability. A shape swap without the corresponding stride swap is invalid IR.
The source Place is the borrow relation; ordinary descriptor copies preserve
its def-use ancestry, never introduce an independent owner.

`rows(x)`/`columns(x)` MUST accept all three matrix types, return usize and
preserve the source kind through IR. `v[i,j]` MUST carry OneBased2D with exactly
two usize operands. Checks MUST establish `1<=i<=rows` and `1<=j<=columns` before
subtraction, stride multiplication, addition or address calculation. The offset
is exactly `(i-1)*row_stride+(j-1)*column_stride`. No raw zero-based access or
contiguity assumption is permitted for matrix views.

Safety follows inductively from the checked owner's shape/byte allocation:
normal offsets are at most R*C-1; a transpose only exchanges coordinate/stride
pairs and hence preserves that offset set; copying preserves it as well.
Every reachable descriptor therefore has representable in-allocation offsets.
Empty descriptors cannot pass bounds. LLVM uses plain unsigned arithmetic
without overflow flags and a non-inbounds GEP after the guards.

Copy elements MAY be read by value and written through mutable views. Shared
views MUST reject writes and mutable element borrows, including nested paths.
Non-Copy elements MUST be borrowed instead of partially extracted; replacing
an owning slot remains unsupported. No implicit Clone/drop is introduced.

Provenance MUST resolve to the existing owner root through copies, transposes,
projected fields, indexed owning containers and explicit references. A live
view or derived alias prevents owner movement/replacement; lexical scope end
releases this restriction. Nested List invalidation stays conservative, with
no stored lifetimes or runtime ownership tags. Borrowed parameters support
local shared/mutable helpers, including cross-module calls. Passing mutable
matrix views whose elements contain List (also through references to the
descriptor) across a call MUST fail closed until
nested alias effects are representable; shared views and writable views of
scalar/Buffer elements remain permitted. Returning/storing
views, rebinding borrowed locals, and using a view as a bare generic type
argument remain forbidden by the current borrowed-value rules. Element-generic
MatrixView<T> helper signatures remain permitted.

Matrix ownership, its three-word row-major descriptor and reverse cleanup MUST
remain unchanged. `transpose(Matrix)` MUST stay invalid; Vector transpose MUST
retain its consuming O(1) transfer. V24 adds no slicing/ranges, row/column views,
VectorView, arithmetic, BLAS, numeric traits, methods, raw pointers or user lifetimes.


## NEXT-VERTICAL-25 — normative oriented VectorView contract

`VectorView<T,Row>`, `VectorView<T,Column>`, `VectorViewMut<T,Row>` and
`VectorViewMut<T,Column>` MUST have canonical mathematical identity distinct
from Vector, MatrixView and raw View. Canonical representation is
`VectorView { element, orientation, mutable }`. All three components enter
TypeId, substitution and structural mangling. No runtime orientation exists.
Both views MUST be Copy and Relocatable, non-Storable and no-drop, independently
of T's Copy property. Mutable capability MUST NOT imply uniqueness or noalias.

The target-derived bootstrap descriptor is `{ptr,dimension,stride}`, with
usize metadata and stride measured in elements. No owner/provenance field,
refcount, capacity or runtime orientation is permitted. `vector_view(x)` and
`vector_view_mut(x)` accept a matching oriented Vector or vector-view Place;
`transpose_view(x)` and `transpose_view_mut(x)` additionally flip Row/Column.
Sources behind references require explicit dereference. Temporary borrowing
and user-defined raw pointer/stride constructors MUST remain rejected.

Owner-derived views MUST preserve pointer/dimension and set stride to 1,
including canonical empty `{null,0,1}`. Existing-view creation and borrowed
transpose MUST preserve pointer/dimension/stride exactly. Double transpose MUST
restore the original type and metadata. Each operation MUST have zero allocation,
free and relocation deltas and MUST NOT read/write/transform elements. Source
owners remain borrowed and live. V22 `transpose(Vector)` remains consuming.

`dimension` accepts owners and both view capabilities and returns logical usize
dimension. Indexing requires exactly one usize operand. Both guards
`index >= 1` and `index <= dimension` MUST precede subtraction, multiplication
and addressing. Addressing MUST use `(index-1)*stride`, including non-unit
strides, without assuming contiguous view storage. Empty indexing traps before
offset calculation. Copy reads are allowed through either capability. Writes
and `&mut` require a writable path and mutable view capability. Non-Copy slot
extraction/replacement remains rejected; owning elements may be borrowed.

Descriptor validity is inductive: checked Vector allocation supplies valid
contiguous offsets; owner creation sets stride 1; view copies and transpose
preserve the valid offset set. Closed compiler-only recipes MUST independently
verify dimension/stride selectors, source/result orientation, element identity,
write capability and source Place. Raw View substitution and arbitrary recipe
corruption MUST fail HIR/MIR/SSA verification. No arbitrary source stride
creation or Matrix row/column projection is admitted by V25.

Creation, copies (including explicit loads through descriptor references),
transpose and derived element references MUST retain the same underlying root
provenance. A relevant live alias MUST block owner move, drop or replacement.
The existing lexical scope, borrowed-local single initialization and no-escape
rules apply: views cannot return, be stored in structs/enums/Array/List/Matrix/
Vector, or serve as bare generic type arguments. Helpers may use symbolic T
inside oriented view parameters; Copy access needs T:Copy, and symbolic owner
sources need T:Storable. Orientation itself is not a generic type parameter.

Struct/projected/indexed owners and explicit ref/ref-mut owner sources retain
the containing root. List structural mutation remains conservatively blocked
when it could invalidate derived aliases. The common mathematical-view effect
query MUST reject calls with mutable views whose elements contain List,
including references to writable descriptors, until nested alias effects can
be represented. Loading a mathematical view through a reference MUST preserve
its backing provenance rather than create an independent root.

Lifetime authority remains frontend lexical analysis. MIR/SSA retain source
Place and descriptor use chains and independently enforce the type/recipe/
capability contracts; V25 adds no global IR lifetime analysis. LLVM emits only
descriptor extraction/insertion for transforms, three-word view values, and
checked strided GEP. MatrixView keeps its separate five-word 2D semantics.
No slicing/ranges, arithmetic, conjugation, apostrophe syntax, methods, traits,
named lifetimes, Matrix row/column extraction or raw pointers are introduced.


## NEXT-VERTICAL-26 — normative Matrix axis projection contract

`row(source,i)` MUST return VectorView<T,Row>; `column(source,j)` MUST return
VectorView<T,Column>. Mutable variants MUST return the corresponding
VectorViewMut with identical T and orientation. Canonical V25 TypeData MUST be
reused. No raw View, owning Vector, RowView or ColumnView type is introduced.
Each operation takes exactly two arguments and no explicit type arguments.
The source MUST be an existing Matrix/MatrixView/MatrixViewMut Place and the
fixed index MUST be usize. References require explicit dereference.

Shared projections MAY borrow any of the three source kinds. Mutable
projections MUST require writable Matrix or MatrixViewMut capability through
the current typed path. A shared MatrixView, shared reference to an owner, or
shared reference to a mutable matrix-view descriptor MUST NOT recover writable
capability from its backing owner. Mutable descriptors MAY alias; they do not
imply uniqueness or noalias.

All recipes operate on the logical matrix-like descriptor `(ptr,R,C,RS,CS)`:

| Axis | Fixed bound | Base offset after bounds | Dimension | Stride | Orientation |
|---|---|---|---|---|---|
| Row | 1 <= i <= R | (i-1)*RS | C | CS | Row |
| Column | 1 <= j <= C | (j-1)*CS | R | RS | Column |

Owners materialize RS=C and CS=1; views MUST supply actual descriptor fields.
Source orientation/layout MUST NOT change the result's mathematical
orientation. For `[1,2,3;4,5,6]` transposed to shape 3x2 and strides (1,3),
row 2 MUST be Row `[2,5]` with dimension 2 and stride 3; column 2 MUST be Column
`[4,5,6]` with dimension 3 and stride 1. Mutable projections use the same
mapping for write-back.

The lower and upper fixed-axis checks MUST precede index subtraction, stride
multiplication and base GEP. Failure is structured IndexOutOfBounds. The second
axis MUST NOT be checked at projection creation; ordinary V25 one-based
indexing checks the resulting dimension and uses its stride. A 0x0 Matrix
has no valid row/column and MUST trap or produce a constant bounds diagnostic.
No empty view may be fabricated for a nonexistent axis.

Address validity is inductive from V24. A valid fixed row i0 and result k0
address `i0*RS+k0*CS`, exactly source coordinate (i,k); a column addresses
`k0*RS+j0*CS`, exactly (k,j). Thus all offsets remain representable and within
the allocation established by the source descriptor invariant. LLVM uses plain
internal arithmetic without poison overflow flags and non-inbounds GEP.
No arbitrary pointer/stride constructor or unchecked source recipe is allowed.

Each successful projection MUST have alloc/free/relocation deltas (0,0,0)
and MUST NOT load/store/copy/drop backing elements merely to create the view.
Only descriptor extraction, bounds, base address calculation and construction
of the existing three-word VectorView descriptor are permitted. Copying the
source descriptor or resolving its Place is permitted.

The source Place and fixed index are evaluated in source order. Projected
source addresses MUST be resolved before the fixed index can mutate index
locals. The source root/storage borrow MUST remain protected while evaluating
the fixed index, including calls that could consume the owner or invalidate
its containing List. The resulting borrow MUST retain the underlying root
through MatrixView transpose, projection, VectorView copy/load/transpose and
derived references. No local MatrixView descriptor becomes a replacement
lifetime root. Live aliases block owning root movement/replacement; lexical
scope end releases the restriction. Containing struct/Array/List roots and
explicit dereference paths follow existing conservative provenance rules.

Owning elements such as Buffer<T> MAY be borrowed without extraction; mutable
projections MAY update Copy subelements through existing rules. Partial owning
slot replacement remains invalid. Shared results prohibit writes. `dimension`
and VectorView indexing MUST reuse V25 unchanged. Parametric helpers taking
MatrixView<T>/MatrixViewMut<T> MAY project locally, with inferred/explicit T
and cross-module monomorphization; element reads/writes need T:Copy and owning
Matrix<T> types need T:Storable. The centralized mutable mathematical-view
call-effect query MUST apply unchanged for List-containing elements.

HIR/MIR/SSA MUST retain explicit MatrixAxisVectorView metadata: source Place,
fixed index, axis, capability, closed descriptor selectors and canonical result
type. MIR/SSA additionally carry IndexOutOfBounds. Each verifier independently
checks source rank, element, orientation, capability, usize index and exact
fixed-extent/base-stride/dimension/stride selectors. SSA dependency and dominance
walkers MUST visit the source and fixed operand. Lifetime authority remains
frontend lexical analysis; no general IR lifetime inference is introduced.

Current no-escape/non-Storable/borrowed-rebind restrictions remain. Applying
borrowed transpose to a projection requires a local binding; no temporary
lifetime extension exists. Owning Matrix transpose remains rejected. This
vertical adds no slicing, ranges, submatrix constructors, owning row copies,
arithmetic, BLAS, traits, methods, raw pointers or stored lifetimes.

## NEXT-VERTICAL-27 — built-in elementwise addition/subtraction

Source operators `+` and `-` resolve by operand family, retaining ordinary
additive precedence. Scalar arithmetic remains unchanged. Vector-like means
Vector<T,O>, VectorView<T,O> or VectorViewMut<T,O>; matrix-like means Matrix<T>,
MatrixView<T> or MatrixViewMut<T>. A pair MUST belong to the same family, have
the exact same canonical element TypeId, and for vectors the same O. There is
no element coercion, broadcasting or vector/matrix mixing.

`supports_builtin_add_sub(TypeId)` admits only concrete built-in integers and
floats: int8/16/32/64, uint8/16/32/64, isize/usize, float32/float64. Aliases resolve
to these identities. bool, structs, enums, collections, mathematical owners,
references and symbolic generic elements have no arithmetic through storage
capabilities. This query creates no public trait, method or operator protocol.

Operands are evaluated left-to-right, capturing readable descriptors. A live
left descriptor protects its underlying owner/storage against invalidation
while the right operand evaluates. Existing owners MUST NOT move. Writable
views are read-only for this operation; exact/partial aliasing is allowed and
no noalias promise is introduced. Explicit expression-created owner temporaries
stay alive through the operation and use ordinary cleanup afterward.

Before element access or result allocation, Vector compares dimensions;
Matrix compares rows then columns, never just their product. Known mismatch
may diagnose E0345; otherwise the structured ShapeMismatch trap aborts.
Only compatible shapes reach checked AllocationSizeOverflow/AllocationFailure.
Compatible empty Vectors and 0x0 Matrices yield empty null owners without
allocation. Nonempty results have one backing; Vector is contiguous and Matrix
is contiguous row-major, preserving the logical shape and orientation.

Logical addressing uses `i*stride` for vectors, and
`r*row_stride + c*column_stride` for matrices with zero-based internal counters.
Owners materialize unit/vector or row-major/matrix strides; views retain their
explicit strides. Descriptor validity, loop bounds and checked allocation
establish representable in-backing offsets; no per-element public index guard
is needed. Source indexing remains one-based and unchanged.

Each scalar element uses exactly the checked integer or IEEE float Add/Sub
operation already admitted for that type. No wrapping, nsw/nuw, fast-math or
reassociation is permitted. Overflow during partial initialization aborts;
there is no unwinding, rollback or result-slot exception cleanup. Elements are
trivial/no-drop. A successful result initializes every logical slot once before
ownership escapes: N operations/stores in O(N), or R*C in O(R*C).

HIR records family-specific operations and ordered shape contracts. MIR/SSA
preserve an executable structured region: ShapeGuard(s), Allocate, unit-step
For loop(s), two StridedLoads, ScalarBinary, InitializeNext and YieldOwner.
Only the validated complete-prefix yield escapes the region. Each verification
boundary checks the full ordered region tree, operand/result types, exact
strides, scalar/trap contract and initialization induction, independently of
prior verification. LLVM translates these instructions into branches, loop
phis and loads/stores, without an arithmetic runtime helper or dispatcher.
No MemorySSA or global lifetime extension is introduced.


## NEXT-VERTICAL-28 — scalar multiplication of mathematical owners/views

`*` with exactly one mathematical input resolves before scalar coercion or
implicit owner Move. The other operand MUST have the same canonical TypeId
as the element. Supported concrete types are int8/16/32/64, uint8/16/32/64,
isize/usize, float32/float64 and their canonical aliases. The internal
`supports_builtin_multiply(TypeId)` establishes this closed admission; storage
and Copy constraints do not prove multiplication for symbolic T. bool,
user-defined elements, collections, nested mathematical elements and references
are rejected. Pairwise mathematical `*` MUST NOT resolve to scalar scaling,
Hadamard, dot, outer or matmul.

Both source orders preserve left-to-right execution. HIR retains left/right
expressions and ScalarSide rather than swapping operands. Only syntactic numeric
literals or directly negated numeric literals use the existing element context.
For a left literal the checker may discover the right type first, since the
literal has no effects; HIR/MIR still retain source order. This never coerces
an already typed variable or arbitrary scalar expression to another type.

The mathematical input is Vector<T,O>, VectorView<T,O>, VectorViewMut<T,O>,
Matrix<T>, MatrixView<T> or MatrixViewMut<T>. Its descriptor is captured for
read-only use; an existing owner MUST NOT move. A captured left input protects
its storage while the right scalar evaluates. Effects of a left scalar are
visible when the right descriptor is selected; normal ownership checks reject
use after consumption. Existing alias rules allow noninvalidating element
writes during scalar evaluation; subsequent kernel loads observe those effects.
This does not permit the kernel itself to write its mathematical input.
Both operands, including an effectful scalar for an
empty input, MUST evaluate before the result region starts. Expression-created
owner temporaries live through the kernel and receive normal cleanup afterward.

Result is Vector<T,O> or Matrix<T>, with logical extents from the single input.
No compatibility ShapeGuard/ShapeMismatch is allowed in the kernel. Empty
inputs yield canonical null owners and bypass allocation/iteration. Nonempty
results check sizes, allocate one backing and only then read elements. Existing
AllocationSizeOverflow/AllocationFailure traps apply. No adaptation allocates
or converts the input backing. Shared aliases are allowed; no noalias promise.

For each zero-based logical coordinate, Vector loads ptr[i*stride]; Matrix
loads ptr[r*row_stride+c*column_stride]. Owners materialize their contiguous
strides. Results write i or r*C+c. Projection and transposed-view expressions
are admitted wherever existing Place/temporary-borrow rules permit; there is
no new temporary lifetime extension. N or R*C multiplications and stores cost
O(N) or O(R*C). Empty inputs execute no element operations/stores.

Elements use MultiplyIntegerChecked with IntegerOverflow or MultiplyFloat
with IEEE fmul. No wrapping, UB overflow flags, fast-math or reassociation.
Overflow after prior initialized slots aborts without unwind or rollback.

HIR records VectorScalarMultiply/MatrixScalarMultiply, ScalarSide, element and
owning result type (including orientation). MIR/SSA preserve the source-ordered
scalar and descriptor as the two operands of ElementwiseBinary and the kernel's
scalar_side. Its closed region is Allocate, nested unit For loops, one
InvariantScalar selection, one StridedLoad, exact Multiply ScalarBinary,
InitializeNext, YieldOwner. InvariantScalar references the captured Copy input;
it has no per-iteration memory read. Scalar operand order follows source side.
The single descriptor defines Allocate extents, loop bounds and output shape.

Both MIR and SSA independently verify their operand/result TypeIds against the
complete canonical instruction tree. They reject wrong sides, scalar/element
mismatch, mathematical owners substituted for readable descriptors, wrong rank
or orientation, any shape dependency, incorrect strides, non-Multiply operations
and missing/duplicate initialization. Unit loops enumerate each result slot
once, so the complete initialization prefix reaches N/R*C before YieldOwner;
no runtime bitmap is required. LLVM translates this same verified region.
No MemorySSA, public behavior capability or whole-program lifetime pass is added.


## NEXT-VERTICAL-30 — generic mathematical kernel guarantees

This section extends the concrete-only V27/V28 admission to exact GenericParam
T under V29's homogeneous behavioral contracts. It does not alter scalar V29
ownership rules or introduce implications between capabilities.

| Kernel | Independent element guarantees |
|---|---|
| Vector/Matrix + | Storable + Copy + Add |
| Vector/Matrix - | Storable + Copy + Sub |
| scalar * Vector/Matrix, Vector/Matrix * scalar | Storable + Copy + Mul |

All readable owners, shared views and mutable views of the same mathematical
family are admissible. Generic Vector orientation MUST remain concrete Row or
Column. Scalar, input elements and owning result element MUST have the exact
same canonical T. Every body MUST establish each guarantee before any concrete
instance is requested, even if no call exists. Missing Copy or behavior MUST
identify the independent missing requirement; missing Storable is diagnosed by
storage legality or the kernel obligation. Calls and forwarding retain V29
constraint validation before InstanceId allocation/cache insertion.

Copy applies to elements and the repeated scalar, never the owning descriptor.
An existing owning input MUST be borrowed, preserving owner usability and all
lexical borrow protections. Reading an element MUST NOT consume its slot. No
implicit clone or per-iteration scalar Move is allowed. Borrowed descriptor
non-Storable properties do not negate an element's independent Storable proof.

HIR retains a declarative MathElementOp, not per-element CapabilityBinary
expressions. Behavioral metadata is legal only for exact symbolic T with all
three guarantees. Pairwise nodes retain source operator evidence and require
exact Add/Sub matching; scaling nodes require Mul. The verifier independently
checks result, family, orientation, source read-only contract and capabilities.
Substitution uses the central V29 concrete_behavior_op mapping to checked
Add/Subtract/MultiplyIntegerChecked or Add/Subtract/MultiplyFloat. Concrete HIR
MUST reject any remaining Behavioral tag, even when the element is now numeric.
MIR/SSA use only the existing concrete ElementwiseKernel and independently
verify its complete schedule. No behavioral operation is representable there.

Vector dimensions, or Matrix rows then columns, MUST match before allocation.
Scaling MUST have one shape source and no compatibility guard. Logical source
strides govern every read, including projected columns and transposed views.
Each nonempty result allocates one backing and initializes each contiguous slot
once. Empty results bypass allocation and iteration; source-order scalar
expression evaluation still occurs. Checked integer traps, IEEE operations
without fast-math, abortive overflow after partial initialization, and storage
failure traps remain unchanged. No runtime capability machinery is emitted.


## NEXT-VERTICAL-31 — algebraic Zero and native Vector multiplication

Vector orientation is algebraic shape and remains part of canonical TypeId:
Row(n) means 1×n and Column(n) means n×1. This includes Row(0)=1×0 and
Column(0)=0×1. Dimension and physical stride remain value metadata.

Native `*` additionally admits exactly these readable Vector products:

| Operands | Result | Independent generic element guarantees |
|---|---|---|
| Row(n) × Column(n) | exact T scalar | Copy + Add + Mul + Zero |
| Column(n) × Row(m) | owning Matrix<T>, shape n×m | Storable + Copy + Mul |

Each side independently accepts Vector, VectorView or VectorViewMut with the
specified orientation. Mutable views are only read. Elements and result have
exactly the same canonical T; no promotion or widened accumulator is introduced.
Owners in signatures independently need Storable for type formation; the inner
product of views itself MUST NOT require Storable. Every generic body and each
forwarding call MUST prove all requirements before instantiation, even unused
bodies. Unsatisfied arguments fail before InstanceId/cache insertion.

`Zero` is an algebraic value capability, separate from structural
Copy/Relocatable/Storable and binary behavioral Add/Sub/Mul. Built-in signed and
unsigned integers, including isize/usize, provide exact typed 0; float32 and
float64 provide canonical positive zero. Transparent aliases share satisfaction.
Bool, nominal aggregates, containers, references and views do not satisfy Zero.
There is no structural derivation and no implication to or from Add, Copy or
Storable; Copy => Relocatable remains the only nonreflexive implication. Source
constraints use existing syntax, e.g. `T:Copy+Add+Mul+Zero`. There is no public
`zero()` function in this vertical; algebraic identity is explicit generic HIR
metadata, concretized to an ordinary typed scalar constant before MIR.

Row×Column checks exact dimension equality. Known mismatch is E0345; dynamic
mismatch traps ShapeMismatch before any element load, multiplication or addition.
After the guard, initialize one accumulator from Zero<T>. Iterate increasing
logical indices 0..n, load both values using their independent strides, multiply,
then add the product to the accumulator. There are exactly n multiplications and
n additions, including the first addition to positive zero. Empty reduction
returns canonical Zero<T>, with no loads or operations. No allocation, freeing
or relocation belongs to the reduction itself.

Integer product and accumulation use separate checked operations and trap
IntegerOverflow without widening or wrapping. Float32/float64 use separate fmul
then fadd in logical order, with no fast-math, reassociation, tree reduction, FMA
contraction or conjugation. Signed zero, infinity and NaN follow those exact IEEE
operations. Traps retain the existing abortive, non-unwinding semantics.

Column×Row has no compatibility guard. Result rows come from the left dimension,
columns from the right dimension, including 0×m, n×0 and 0×0. The normal owning
Matrix descriptor preserves both axes independently. Checked result-size
calculation precedes one backing allocation for a nonempty result; a zero-size
result uses null storage and allocates nothing. Nested increasing row/column
loops load each source with its own stride and initialize each contiguous
row-major result slot once from their product. Exactly n*m multiplications and
stores, no additions or Zero requirement. Bootstrap row-major layout is not
public mathematical identity. Matrix +/−/scaling preserve zero axes too. Literal
`Matrix<T> []` continues to mean only 0×0; no literal syntax is extended.

Operands evaluate in source order and both are captured before the kernel.
Existing borrow/provenance rules protect the left backing while evaluating the
right expression; successful products leave existing input owners usable.
Aliasing is permitted, with no noalias assertion. Expression-created owners get
normal cleanup after the kernel. Existing consuming `transpose(Vector)` is
unchanged; use `transpose_view` for a nonconsuming orientation change.

Row×Row and Column×Column remain errors, with no implicit transpose or Hadamard
interpretation. Matrix×Vector, Vector×Matrix, Matrix×Matrix remain deferred;
existing scalar multiplication and +/− are unchanged. There is no dot(Vector,
Vector), outer() or matmul() intrinsic. `dot` is reserved as a possible future
sequence operation for Array/List, which is not implemented here. One, user
implementations, heterogeneous output, generic orientation, slicing, lifetime
extensions, BLAS and SIMD remain outside scope. Advanced decompositions remain
future STD LinearAlgebra concerns.

## NEXT-VERTICAL-32 — native Matrix×Column and Row×Matrix

V32 extends the V31 algebraic contract with exactly two mathematical pairings:

| Inputs | Result | Shape equality | Result extent | Contraction extent |
|---|---|---|---|---|
| Matrix<T>(m,n) × Column<T>(n) | owning Vector<T,Column>(m) | A.columns = x.dimension | A.rows | A.columns |
| Row<T>(m) × Matrix<T>(m,n) | owning Vector<T,Row>(n) | r.dimension = A.rows | A.columns | A.rows |

Readable Matrix/MatrixView/MatrixViewMut and oriented
Vector/VectorView/VectorViewMut MUST work in any combination. Both elements MUST
have identical canonical T, with no promotion or widening. Result orientation
is type identity, independent of layout, strides and runtime dimensions. The
owning Vector uses the existing `{ptr,dimension}` descriptor; orientation adds
no runtime field. The complete native mathematical multiplication table is now
scalar×Vector, Vector×scalar, scalar×Matrix, Matrix×scalar, Row×Column->T,
Column×Row->Matrix, Matrix×Column->Column and Row×Matrix->Row.

Generic T MUST independently satisfy Storable, Copy, Add, Mul and Zero. Storable
permits owning result storage, Copy permits repeated by-value reads without
moving source slots, Mul forms each T*T term, Add updates each T accumulator,
and Zero seeds it. V32 adds no capability implications. Unused generic bodies
and cross-module forwarding MUST be validated parametrically. Symbolic HIR
retains Behavioral(Mul), Behavioral(Add), Algebraic(Zero), exact families,
orientation, shape equality and distinct result/contraction selectors.
Monomorphization MUST concretize operations and typed positive zero before MIR;
capability metadata MUST NOT enter MIR/SSA/LLVM.

Known contraction mismatches MUST raise structured compile-time errors. Dynamic
ShapeMismatch MUST dominate allocation, loads, multiplication and accumulation,
even when the result extent is zero. After compatibility, a zero result extent
MUST return the canonical null/zero Vector without backing allocation, scalar
operations or stores. A positive result extent MUST check backing byte size,
allocate exactly once, and preserve AllocationSizeOverflow/AllocationFailure.

For each result coordinate, initialize acc=Zero<T>, visit the contraction index
in increasing logical order, compute product=lhs*rhs, then acc=acc+product, then
store the final accumulator once. Matrix×Column computes each row's reduction;
Row×Matrix computes each column's reduction. Integer Mul/Add MUST be checked at
T's original width and trap IntegerOverflow independently. Floating zero MUST
be +0.0; multiplication and addition MUST remain separate strict operations,
with no reassociation, FMA, fast-math, BLAS or changed iteration order.

Result and contraction extents MUST NOT be conflated:

| Case | Result | Allocation | Mul/Add | Stores |
|---|---|---:|---:|---:|
| Matrix(m,0)×Column(0), m>0 | Column(m), all Zero | 1 | 0 | m |
| Matrix(0,n)×Column(n) | Column(0) | 0 | 0 | 0 |
| Row(0)×Matrix(0,n), n>0 | Row(n), all Zero | 1 | 0 | n |
| Row(m)×Matrix(m,0) | Row(0) | 0 | 0 | 0 |

For general m,n, both products perform m*n multiplications and m*n additions;
Matrix×Column stores m outputs and Row×Matrix stores n. Empty contraction MUST
run zero inner iterations and store the untouched Zero for every output. Every
result slot MUST be initialized exactly once before its owner can escape.

Logical Matrix addressing MUST use i*RS+j*CS (zero-based internal coordinates),
with independent descriptor strides. Owner RS=columns, CS=1; MatrixView uses
explicit strides. Vector addressing MUST use its descriptor stride. No source
flattening, materialized transpose, or repeated row()/column() construction is
permitted. Transpose_view of a zero-axis Matrix MUST preserve swapped axes and
obey the same rules, including Matrix(3,0)->View(0,3) and
Matrix(0,4)->View(4,0).

Operands MUST evaluate left to right. The left root MUST remain protected while
evaluating the right; effects that consume, replace or invalidate it are errors.
Inputs are borrowed, remain usable after success, and may alias. The result is
fresh owning storage; no hidden source backing copies or lifetime changes.

MIR MUST represent a closed map of reductions: exact shape guard, separate
extent selections, result-only empty bypass/allocation, outer result loop,
Zero initialization, inner contraction loop, strided reads, Mul then Add,
one InitializeNext per output, then YieldOwner. MIR and SSA MUST independently
resolve operand/result types and validate the full schedule, including strides,
loop bounds, traps, accumulator chain, initialization, no input moves/writes,
and no late shape guard. SSA preserves the closed region without MemorySSA.
LLVM translates the verified schedule; it MUST NOT be its first authority.

At the V32 boundary Matrix×Matrix was deferred; V33 admits it below.
Matrix×Row, Column×Matrix, Row×Row and Column×Column remain rejected, including
dimension one. V31 products, scalar scaling, +/− and
transpose/projections retain their contracts. No dot(Vector), Array/List dot,
Hadamard, matmul function, user impl, One, heterogeneous types, widening,
BLAS/SIMD/reassociation or lifetime extensions are introduced. Advanced
decompositions remain future LinearAlgebra STD responsibilities.


## NEXT-VERTICAL-33 — native Matrix×Matrix

For A:Matrix<T>(m,k), B:Matrix<T>(k,n), native `A * B` MUST return a fresh
owning Matrix<T>(m,n). Each operand independently accepts Matrix, MatrixView or
MatrixViewMut (nine readable pairings); mutable inputs MUST NOT be written.
Both elements MUST have identical canonical TypeId T. No promotion, structural
arithmetic derivation, heterogeneous output or accumulator widening is allowed.
Storable, Copy, Add, Mul and Zero MUST each be established independently for
symbolic T, including unused generic bodies and local/cross-module forwarding.

The complete table is scalar×Vector/Vector×scalar -> Vector,
scalar×Matrix/Matrix×scalar -> Matrix, Row×Column -> T, Column×Row -> Matrix,
Matrix×Column -> Column, Row×Matrix -> Row, and Matrix×Matrix -> Matrix.
Native type identity MUST determine the result family: 1×k Matrix times k×1
Matrix returns a 1×1 Matrix, never T. Row×Row, Column×Column, Matrix×Row and
Column×Matrix remain invalid even with dimension one.

A.columns MUST equal B.rows. A known mismatch MUST produce a structured static
diagnostic; a dynamic mismatch MUST trap ShapeMismatch. Guard ordering MUST be
shape guard -> empty output bypass -> checked allocation -> source element
loads -> Mul/Add, including 0×3 times 4×0. The following three extents MUST
remain explicit and independently reconstructed by HIR/MIR/SSA verification:

| Extent | Exact source | Purpose |
|---|---|---|
| output_rows | A.rows | outer loop, shape, emptiness, size |
| output_columns | B.columns | middle loop, shape, emptiness, size |
| contraction_extent | A.columns, checked equal to B.rows | inner loop only |

For m=0 or n=0, result MUST be {null,m,n}, without allocator, stores, loads or
Mul/Add. For m,n>0 and k=0, result MUST instead allocate once and store exactly
m*n typed Zero values, with zero source loads, zero Mul and zero Add. Empty
contraction MUST NOT bypass the output loops. Result size MUST check m*n and
then bytes using existing Matrix allocation semantics; it MUST NOT include k.
AllocationSizeOverflow and AllocationFailure MUST precede source element reads.

Logical schedule (internal zero-based indices):

```text
for i in 0..m:
    for j in 0..n:
        acc = Zero<T>
        for l in 0..k:
            product = A[i,l] * B[l,j]
            acc = acc + product
        C[i,j] = acc
```

Rows, columns and contraction MUST increase in that nesting order. The first
addition to Zero MUST remain. Each integer product is MultiplyIntegerChecked;
each accumulation is AddIntegerChecked, with distinct IntegerOverflow paths and
no widening/wrapping. Float32/float64 MUST use canonical +0 and separate strict
fmul then fadd; no FMA, reassociation, fast-math or pairwise reduction is allowed.
Symbolic HIR uses Behavioral(Mul), Behavioral(Add), Algebraic Zero. Existing
monomorphization MUST reify exact integer zero / positive floating zero and
concrete scalar operators; no symbolic metadata may reach concrete MIR/SSA.

Source addresses MUST be i*lhs.RS+l*lhs.CS and l*rhs.RS+j*rhs.CS independently.
Owners use RS=columns, CS=1; views retain explicit strides. Either or both
transposed inputs MUST work without source flattening, temporary Vector,
row()/column() expansion, transpose materialization or noalias assumptions.
Result stores MUST initialize i*n+j exactly once, and YieldOwner MUST occur
after complete initialization. There is no bitmap or partially escaped owner.

Operands MUST evaluate left to right; lhs descriptor/root stays protected
against rhs consumption, replacement or invalidation. Inputs may alias and
remain usable after success. Temporary owners live through the product and
receive normal cleanup. No lifetime rules change.

MIR and SSA MUST each resolve their own operand and result types and revalidate
the complete closed 2D map-of-reductions schedule: guard, all selectors, bypass,
allocation extents/traps, nesting/bounds/order, per-cell Zero, both stride
coordinates, Mul before Add, single accumulator, one ordered InitializeNext,
and final owner yield. Corruption MUST fail closed. No source move/drop/write
instruction is admitted in this region. SSA needs no MemorySSA. LLVM MUST
translate the already verified schedule and preserve exact empty shape fields.

Exact successful costs are m*k*n Mul, m*k*n Add, 2*m*k*n source loads, m*n
stores, one allocation iff m,n>0, and zero free/relocation delta in the product.
Normal final cleanup balances allocations. Counts are measured at runtime
separately from compilation snapshots. V0..V32 contracts remain unchanged.

No new Vector product, Array/List dot, Hadamard, matmul function, One, user impl,
BLAS, SIMD, reassociation or FMA is introduced. Advanced decompositions remain
future STD LinearAlgebra work. See [NEXT_VERTICAL_33_REPORT.md](NEXT_VERTICAL_33_REPORT.md).


## LANGUAGE-PARITY-1 — main fallthrough and source comments

**ADMITTED** in compiler-next. The entry module MUST select exactly one function
with signature `int main()`, zero parameters and no generic parameters. Return
type checking uses canonical int64 identity: existing `int64` and transparent
user aliases remain valid, as required by sections 1.2–1.3. bool, double/int32,
parameterized and generic entry functions MUST be rejected with E0201. `void`
and undeclared return types remain unsupported through existing type/parser
diagnostics. Missing and conflicting entry declarations retain existing errors;
empty/comment-only input retains the parser's E0101 rejection.

Normal fallthrough in the resolved entry function MUST mean `return 0;`.
Conditional explicit returns preserve their values; only the continuing path
returns zero. An already definitely returning body receives no additional return.
Ordinary non-void functions, including imported functions named `main`, MUST
still fail with E0207 when the existing return analysis finds possible normal
fallthrough. The analysis remains structural and conservative for loops; this
milestone adds no general control-flow theorem proving. Modules remain
containing declarations only: no script mode, synthesized main, top-level
execution or global executable initialization is admitted.

The implicit return MUST be explicit in HIR before ownership analysis. It uses
an ordinary typed int64 zero, normal return cleanup, a compiler-generated
provenance marker and the actual closing-brace span. The marker provides no
verification or lowering exemption. MIR and SSA use their ordinary Return
terminators. LLVM retains the platform wrapper that calls the Aether int64
entry and truncates its result to i32; the platform exposes its usual process
status. Explicit `return 0;` and `return 7;` remain valid, yielding native status
0 and 7 on the admitted Linux x86-64 target. No runtime helper is introduced.

`//` MUST ignore all content through the line ending or EOF without requiring a
trailing newline. `/* ... */` MUST ignore content through the first `*/`,
including source-looking code, quotes and `//`. Block comments do not nest:
`/* outer /* inner */ tail */` leaves `tail */` for ordinary tokenization.
Unterminated block comments MUST produce E0002, Phase::Lex, Syntax, with message
`unterminated block comment` and the opening two-byte delimiter span.

Whitespace and comments share one lexer trivia authority. Skipping MUST operate
on the original source: no preprocessed buffer may shift offsets. Spans remain
half-open UTF-8 byte ranges with SourceId. SourceFile derives one-based lines
from LF and columns from Unicode scalar counts in the original line; CRLF is
preserved. Existing CR whitespace handling is unchanged. Comments may appear
where whitespace is legal, including generic binders, type arguments and math
syntax, but MUST NOT join source token fragments: `< /*...*/ =` is not `<=`.
Exact `//` and `/*` start comments; other `/` and `*` remain operators. A division
slash directly followed by a comment opener needs separating whitespace to
avoid forming `//`. Comments produce no parser-visible or semantic IR nodes.
Strings remain unadmitted; this milestone adds no string syntax. Future string
scanning must consume a complete literal before trivia is consulted again.

Qualification, exact position assertions, deterministic dumps and semantic
comparisons are recorded in [LANGUAGE_PARITY_1_REPORT.md](LANGUAGE_PARITY_1_REPORT.md).


## OOP-V1 — concrete class identity and lifecycle

Status: **ADMITTED** in `compiler-next`, native Linux x86-64, single-threaded,
abortive traps with no unwind. [Qualification and limitations](OOP_V1_REPORT.md).

`class C { ... }` declares a module-owned nominal concrete class. It is effectively
final: no inheritance syntax exists. Top-level visibility is internal by default;
`public class` exports the type. Members default to private and may use `public`
or `private`. Fields admit supported primitive scalars, transparent aliases,
finite concrete Copy/no-drop structs/enums with available layout, and private
`Buffer<int>`. Owning class edges, class-containing aggregates/containers,
refs/views, generic class applications and other owning fields are rejected.
Transparent aliases preserve ClassId. Public class APIs cannot expose internal
class types.

Each source class value denotes a live, fully initialized, non-null object.
Its structural properties are Copy=false, Relocatable=true, needs_drop=true,
and Storable=true only in admitted positions. This does not widen `T:Copy` or
container admission. Struct, enum and mathematical value semantics are unchanged.

One explicit `init(parameters) { ... }` is permitted, with no source result type
or return value. Nonempty classes require it; empty classes may synthesize a
zero-argument init. Construction `C(args)` evaluates arguments, allocates one
complete object with one initial strong obligation, invokes the resolved init,
and publishes only after all required fields are initialized. Storage bytes do
not count as initialization. Reads before initialization and incomplete normal
paths are errors. Copy-field replacement is allowed. Owning-field state must
agree at joins; loops cannot establish previously uninitialized fields. Traps
abort the process and may bypass cleanup of unpublished objects.

`this` is a compiler-known borrowed identity, never an owning source value.
It cannot be returned, rebound, aliased into a handle, stored, passed as an
ordinary argument or used to create escaping references. During init it may
initialize fields and read initialized Copy fields; it cannot invoke methods.
Within methods, unshadowed field names and `this.field` resolve to the same
FieldId, with locals/parameters taking precedence over implicit field names.

Methods use `public int get()` or `public mut int increment()`. Read is the
default and forbids receiver-derived writes and mut calls. Declared mut grants
write capability, not uniqueness, exclusivity, purity or noalias. Other owning
aliases can mutate the same object. All methods dispatch directly to resolved
function identities. A receiver is evaluated once, before arguments. An explicit
strong keepalive covers argument evaluation and the call; it is released after
the result is obtained. A fresh receiver transfers its existing token instead
of retaining. Read calls on temporary objects are admitted; mut calls require
an addressable writable receiver. Field reads/writes on local handles obey
visibility; temporary field access, owning-field extraction and all interior
references/views are rejected.

An owning class lvalue used by value performs **Alias**: evaluate once and retain
once while preserving the source obligation. This applies to local bindings,
by-value concrete parameters and lvalue returns. Fresh owned results perform
**Transfer**, consuming their existing obligation without an extra retain.
A borrowed receiver is a separate compiler-only use category. Assignment acquires
the RHS, installs the new owner and then releases the old owner. Exact
self-assignment is a no-op. Owning Buffer field replacement similarly evaluates
the RHS, installs the new owner and destroys the previous field without leaving
a source-visible hole. Returning an lvalue acquires the result before local
cleanup; parameters and locals each release their own remaining obligation in
reverse scope cleanup order on every normal path.

`==` and `!=` compare identity for two values of the same ClassId. No field
comparison, ordering, hashing or cross-class conversion is admitted.

The last strong release executes the verified reverse owning-field drop recipe,
including exactly one destruction of each initialized Buffer field, then frees
the object exactly once. No user destructor exists. Strong counter zero on
retain/release or maximum count on retain traps instead of wrapping. ARC is
non-atomic; no weak reference, tracing GC, cycle collector, descriptor/vtable,
RTTI API or public object ABI is added. The current private layout is one pointer
per handle, an eight-byte strong-count header and target-aligned field payload.
Semantic Alias/Transfer, publication and keepalive exist before backend lowering;
correctness does not depend on optimization eliminating balanced ARC operations.

HIR, MIR and SSA independently validate identities, signatures, access,
receiver capabilities, initialization, publication and ownership cleanup.
MIR/SSA preserve ordered object effects and verify normal-path token balance;
SSA joins transfer one incoming obligation, never duplicate it. Programs with
no reachable class use emit no ARC runtime, including unused class declarations.


## OOP-V2 — flat nominal class-backed interfaces

Status: **ADMITTED** in `compiler-next`, native Linux x86-64, under OOP-V1's
single-thread, non-null, non-atomic ARC and abortive-trap restrictions.
[Qualification and limitations](OOP_V2_REPORT.md).

`interface I { int read(); mut int change(int x); }` declares a module-nominal
InterfaceId. Requirements are implicitly public; redundant `public` is accepted,
while `private` and unsupported modifiers are rejected. Top-level interfaces
are internal unless `public interface` is specified. Empty interfaces are
allowed. Transparent aliases preserve the underlying identity. Identical names
and requirement shapes in different modules do not create type equivalence.

`class C : I1, I2` establishes explicit conformance. Each canonical target must
be an interface, and must occur once, including through aliases. A class target
produces an inheritance-not-yet-admitted diagnostic. A matching method without
the declared relation provides no conversion authority. Every requirement needs
one public method of the exact concrete class with matching name, parameter
count, canonical parameter types (including reference ownership/access modes),
result type and read/mut receiver mode. No variance, overload selection or
receiver weakening is applied. A method may satisfy identical requirements in
multiple interfaces. Conflicting same-name contracts are rejected. Public class
conformance and public class/interface APIs cannot expose internal object types.

A value of I owns a strong obligation on the original concrete class object.
It is non-Copy, Relocatable and needs_drop, and is storable only in admitted
positions: locals, concrete by-value parameters and concrete returns. A class
lvalue adapted to I retains once and preserves the original class obligation.
A fresh class result transfers its obligation into I with no conversion retain.
Interface lvalue use aliases once; fresh interface results transfer. Assignment
publishes the acquired replacement before releasing the previous owner; exact
self-assignment is a no-op. Returns acquire/transfer their result before local
cleanup. These rules do not expand generic or aggregate storage admission.

The private carrier contains the original object pointer and an immutable static
witness pointer for the exact (ClassId, InterfaceId) association. No wrapper,
field copy, boxing or per-value witness allocation exists. Requirement identity
is semantic authority; declaration-order numeric slots are privately verified
layout. Each witness includes the exact concrete class release function and
one verified implementation per requirement. Witness metadata owns no strong
reference and is never retained or released.

An interface call resolves InterfaceId, RequirementId, exact signature and
receiver capability before MIR. A strong receiver keepalive is acquired before
argument evaluation and released after the indirect call. It preserves both
carrier components independently of rebinding the source local. Read calls
admit local or fresh receivers; mut calls require a writable local carrier and
do not imply exclusivity, uniqueness or noalias. Shared mutation is visible to
class and interface aliases. Known-class calls continue to dispatch directly.

Dropping an interface owner or its keepalive releases exactly one obligation
on its object. The witness's concrete release function performs the OOP-V1
final destruction protocol when the count reaches zero, dropping nested owning
fields once and freeing the object once. HIR, MIR and SSA independently validate
nominal metadata, signatures, witness association, exact slots, carrier types,
keepalive capabilities and ownership accounting. SSA owners remain whole typed
values; each executed phi edge transfers one obligation. Arbitrary object/witness
pair construction and witness release are not semantic operations.

Interface `==`/`!=`, null, interface-to-interface conversions across distinct
InterfaceIds, fields in classes/structs/enums, container/generic storage,
carrier refs/views and interior references are rejected. Scalar references and
supported values may appear in exact method parameters under their existing
contracts; borrowed method results remain forbidden. No interface inheritance,
fields, init/deinit, generic methods, default bodies, statics, properties,
associated types, generic interfaces, struct conformance, class inheritance,
`implements`, `extends`, `open`, `override`, RTTI surface, exceptions or threading
change is admitted. The carrier and witness layout are not public ABI.

## OOP-V3 — single class inheritance and virtual dispatch

Status: **ADMITTED** in `compiler-next` for the native Linux x86-64 bootstrap.
[Qualification, counters and accepted debt](OOP_V3_REPORT.md).

`open class Base` permits derivation. An ordinary class is final. The existing
colon relation list accepts at most one canonical class base plus any number of
interfaces; relation order has no semantic meaning. Bases must be accessible
and open, the class graph must be acyclic, and a public derived class cannot
expose an internal base. `extends` and `implements` remain invalid.

Methods remain non-virtual by default even inside open classes. A `public open`
method in an open class introduces a `VirtualSlotId` tied to its originating
declaration. A derived same-name declaration is legal only as an exact
`override`: its parameters, result, read/mut receiver capability and public
visibility match, its target is inherited and open, and it reuses the original
slot. Overrides remain overridable whenever the derived class is itself open.
Private/open methods, open initializers and open methods in final classes fail.
There are no overload, hiding, covariance, contravariance or `final override`
rules in this admission.

A complete derived allocation contains the private two-word header, base fields
as a fixed prefix, then derived fields. The header holds one non-atomic strong
count and one immutable descriptor pointer. Every base/derived/interface view
points to that same allocation and count. Each concrete descriptor supplies the
most-derived destruction function, effective virtual targets and effective
interface witnesses. These layouts and numeric slot positions are private
bootstrap ABI and expose no RTTI.

Construction evaluates construction arguments left-to-right, allocates the
complete most-derived object, installs count and descriptor, evaluates base
arguments left-to-right, invokes the immediate base initializer on the same
unpublished object, initializes derived fields/body, and publishes once. Base
initialization recursively follows the same rule. Omitting `: base(...)` is
legal only for an accessible zero-argument immediate-base initializer, for
which the compiler inserts the call. No base allocation, handle or publication
is created. `this` keeps OOP-V1's no-escape/no-call rules; inherited state is
unavailable until base completion.

Inherited fields preserve their declaring `ClassId`/`FieldId` and target offset.
Private base members remain inaccessible to derived bodies. Derived fields and
methods cannot hide inherited names. Public inherited methods are callable.
Calls to non-open methods select the static inherited declaration directly.
Calls to an open slot load the dynamic descriptor and most-derived effective
implementation, including when the static receiver is the derived class.
Receiver capability and keepalive rules are unchanged.

An implicit derived-to-base conversion is a verified `ClassUpcast` with its
exact nominal path. A fresh owner transfers its existing token; a derived
lvalue aliases and retains one token. Transitive upcasts are supported. There
is no slicing, allocation, payload copy or downcast. Equality accepts related
base/derived static types and compares the shared object pointer.

Derived classes inherit all nominal interface conformances from their base;
redeclaring an inherited conformance is rejected. A per-concrete-class witness
maps each requirement to the effective derived implementation. Class-to-interface
adaptation loads that witness from the dynamic descriptor even when its source
has a base static type. Interface dispatch therefore observes overrides, and
the final interface release uses descriptor-based dynamic destruction.

On the last release, the descriptor-selected concrete destructor drops the
most-derived owning fields in reverse declaration order, then each base's fields
in the same recursive order, then frees the complete allocation once. The
static handle type never chooses partial destruction. HIR, MIR and SSA each
rebuild and validate base graphs, overrides, slots, construction state, upcast
paths, effective conformances and owner balance. MIR materializes one
`ObjectAlloc`, same-object `BaseInit`, one `PublishObject`; SSA keeps static class
types separate from exact/unknown dynamic provenance.

Multiple stateful inheritance, abstract/sealed/protected/final modifiers,
class-valued graph fields, generic inheritance, downcasts/type
tests, source RTTI, nullability, user destructors and exceptions remain outside
this admission. Unknown base parameters and mixed derived phis remain indirect.

## OOP-POLISH-1 — immediate-base calls and exact class dispatch

Status: **ADMITTED** in `compiler-next` under all OOP-V1/V2/V3 ownership,
capability, visibility, initialization and dynamic-destruction restrictions.
[Qualification and limitations](OOP_POLISH_1_REPORT.md).

`base.method(arguments)` is available only inside a non-initializer method of a
class with an immediate base. It resolves the named method as seen on that
immediate base and invokes that exact implementation directly, even when the
method belongs to a virtual slot. Multilevel inheritance therefore selects the
immediate base's effective override, not the root implementation and not the
most-derived override. Private base methods are inaccessible. A mut base method
requires a mut current receiver; read calls preserve read capability.

`base` is a contextual call designator, not an expression value. It cannot be
bound, assigned, returned, passed, stored, borrowed or converted. A base call
uses the current borrowed `this` and creates no class handle, upcast, Alias,
Transfer, retain or independent cleanup. The caller's existing receiver
keepalive spans the complete current method, including left-to-right base-call
argument evaluation and the direct nested invocation.

HIR `BaseMethodCall` records the current ClassId, immediate base ClassId,
optional originating VirtualSlotId, exact declaration target, borrowed receiver
and arguments. MIR substitutes the exact InstanceId without changing that
identity and adds no receiver owner cleanup. SSA preserves the same ordered
effect. Every phase independently verifies immediate-base relation, effective
target, slot, signature, result, receiver capability, visibility and argument
ownership. LLVM calls the verified symbol directly and performs no descriptor
or virtual-slot load for this operation.

O2 extends OOP-OPT-1's existing Bottom/Exact/Unknown provenance fixed point to
class `VirtualCall`. Only `Exact(ClassId)` authorizes a physical direct target,
selected by that exact class and the preserved VirtualSlotId. Same-class phi
joins remain Exact; different-class joins, parameters and opaque results are
Unknown and remain indirect. No implementer count, subclass enumeration for
dispatch choice or closed-world assumption is used. The logical VirtualCall,
receiver capability, arguments, result ownership and keepalive remain unchanged,
and the complete transformed SSA is re-verified. Dynamic release and
descriptor-selected destruction are unchanged.

## GENERAL-V1 — immutable UTF-8 string spine

Status: **ADMITTED** in `compiler-next` under the exact surface and exclusions
in [GENERAL-V1](GENERAL_V1_STRING_REPORT.md), implementing the representation
decision in [GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md).

`string` is a canonical fundamental, immutable, non-null, valid-UTF-8 owning
value. It is not a class. Its structural facts are `Copy=false`,
`Relocatable=true`, `Storable=true`, `needs_drop=true`. Direct locals,
assignment, by-value parameters and returns use explicit Alias, Transfer and
Drop decisions. Dynamic backing uses non-atomic strong ARC; static literals,
including the non-null empty singleton, preserve logical ownership while their
physical retain/release is a no-op.

The admitted content operations are only `string + string`, content `==`/`!=`,
`byteLength(string) -> usize`, and length-aware `print(string)` /
`println(string)`. U+0000 is ordinary content and byte length is authoritative;
no operation uses C-string termination. Two non-empty concat operands create a
fresh exact-size heap owner; empty fast paths Alias the other operand. Size
overflow, allocation failure and invalid ARC state trap.

String fields and payloads, string collection elements, generics involving
string, references, indexing, slicing, views, iteration, Bytes, formatting,
parsing, hashing, COW, SSO, normalization, graphemes, public FFI and threads are
not admitted. These exclusions are semantic gates despite the truthful
Storable/Relocatable properties and require independent future qualification.

## GENERAL-V2 — string structural composition

Status: **ADMITTED** in `compiler-next` for struct fields, enum payloads,
`Array<string>` and `List<string>`, under the lifecycle and exclusions in
[GENERAL-V2](GENERAL_V2_STRING_COMPOSITION_REPORT.md). This supersedes only the
corresponding GENERAL-V1 storage gates; string representation and text semantics
do not change.

A type containing `string` composes the ordinary structural properties:
`Copy=false`, `Relocatable=true`, `Storable=true` and `needs_drop=true`.
Whole-value use transfers ownership and invalidates the source. It never
synthesizes field-wise Alias, deep copy or a general Clone/Alias capability.
Thus `T: Copy` rejects both string and any aggregate or collection containing
it, and an owning read through a field or index remains invalid.

Recursive Drop visits every initialized owning field, active enum payload or
live collection element exactly once. Normal exits, early returns and exception
unwind use the same cleanup plans. Array/List relocation transfers initialized
storage without string retain/release; remove/pop transfer the extracted owner.

Replacement of a complete drop-needing value first stages the old owner, then
publishes the fully materialized new value, and finally drops the old owner.
Replacement of an exact stored string slot has the same verified
publish-before-release order. This does not admit arbitrary partial replacement
of non-Copy values.

Class/interface graph ownership, string references, `StringView`, textual
indexing/slicing/iteration, Text APIs, interpolation/formatting, Bytes, hashing,
COW/SSO and threads remain outside this admission. `Buffer<string>`,
`Vector<string>` and `Matrix<string>` are likewise not admitted by GENERAL-V2.

## TEXT-V1 — exact scalar-indexed Text

Status: **ADMITTED** in `compiler-next` for the canonical explicit `Text` module
and exact surface recorded in [TEXT-V1](TEXT_V1_REPORT.md). Public positions are
nominal `Text.ScalarOffset` values counting Unicode scalars; byte positions stay
private. `FindResult` distinguishes `Found(ScalarOffset)` from `NotFound`.

Count, contains, prefix/suffix and find operations borrow inputs and allocate or
Alias nothing. Substring and bootstrap ASCII trim return owned strings with the
specified empty/full identity fast paths and fresh proper fragments. Split
returns a fresh `List<string>`, preserves empty elements and rejects an empty
separator before allocation. Bounds/range violations remain fail-fast traps.

Only private byte-at and validated UTF-8 range-copy representation primitives
are admitted. Regex, views, syntactic slicing/indexing, public iteration/Bytes,
formatting, normalization/graphemes, case/locale operations, parsing, hashing
and public builders remain outside the contract.
