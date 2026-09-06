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

### 6.3 `Vector` and `Matrix` — DECIDED surface direction / future implementation

`Matrix<T>` has contiguous dense storage by default with dimensions, strides,
layout and ownership represented explicitly in semantic IR. It is not
`Array<Array<T>>`, `List<List<T>>` or nested Vector literals. A future sparse
matrix is a different type/family.

`Vector<T, Orientation>` carries Row/Column orientation in its mathematical
semantics and type because orientation changes multiplication validity and
result type. The exact type-level argument mechanics still await generic
constraint work.

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
neutral `{...}` collection literal. No Vector or Matrix syntax is implemented
by V14.

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

### 6.4 Bounds — DECIDED

Safe indexing and slicing check bounds and trap or return the language's
specified error form.  Optimization may remove a check only with a proof.
Unchecked indexing requires an explicit low-level operation/region. Index base
is type-dependent, never a configurable global switch. `Buffer`, `View`,
`ViewMut`, `Array` and `List` are zero-based. Future mathematical
`Vector`, `Matrix` and their mathematical views are one-based.

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
