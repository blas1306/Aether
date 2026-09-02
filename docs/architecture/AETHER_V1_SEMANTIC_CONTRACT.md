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

### 4.4 Function calls — DECIDED/OPEN

Arity, parameter and return types are statically checked.  Public/exported
function signatures are explicit except for narrowly specified local/private
inference.  Nontrivial return ownership is explicit in semantic IR.

The concrete parameter modes (owned, borrowed read-only, borrowed mutable,
shared) and their source syntax are an **OPEN DECISION**.  A single implicit
“borrow everything” convention is insufficient for FFI, buffers and returned
views.

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

### 5.3 References and lifetimes — OPEN DECISION

The language needs at least non-owning read access and mutable access for
zero-copy slices, matrix views and FFI.  Candidate enforcement ranges from
lexically scoped borrows to explicit view types with conservative escape
checks.  A full Rust-style borrow checker is not assumed.

The decision must cover return of views, storage in aggregates, async/thread
boundaries, mutation during iteration, reallocation invalidation and
diagnostics.  The current borrowed `for-in` element rule is evidence that a
narrow non-escaping model works and is a reusable starting point.

## 6. Core data abstractions

### 6.1 `Array<T>` — PROVISIONAL

`Array<T>` is a contiguous, fixed-length, owning sequence with zero-based
indexing.  It is generic over representable `T`.  Whether assignment moves,
copies the buffer or shares an object is an **OPEN DECISION**; the current
compiler shares a mutable ARC handle, which is convenient but weakens value
reasoning and parallel alias analysis.

The design MUST support explicit alignment, allocator choice and FFI-safe data
access without exposing the runtime header.  Slices/views are separate
non-owning values, not secretly allocated arrays.

### 6.2 `List<T>` — PROVISIONAL

`List<T>` is a growable sequence built above a buffer abstraction.  Growth,
capacity and reallocation are observable through cost and view invalidation,
not through an unstable ABI header.  It is a general collection and is not the
storage model for matrices.

### 6.3 `Vector` and `Matrix` — PROVISIONAL/OPEN

`Matrix<T>` has contiguous dense storage by default with dimensions, strides,
layout and ownership represented explicitly in semantic IR.  It is not
`Array<Array<T>>`.  A future sparse matrix is a different type/family.

`Vector<T, Row>` and `Vector<T, Column>` are provisionally distinct static
types because orientation changes multiplication validity and result type.  A
type-level orientation parameter avoids two unrelated nominal implementations.
However, this remains an **OPEN DECISION** until inference and generic
diagnostics are prototyped; orientation on every vector can burden non-linear-
algebra APIs.  A possible resolution is an unoriented one-dimensional
`Vector<T>` plus oriented row/column views used by linear algebra.

Static dimensions are also open.  Dynamic dimensions must work; optional
compile-time dimensions may enable specialization without making ordinary
matrix types unwieldy.

Natural operations—shape queries, element access, addition/subtraction,
multiplication and transpose—belong to the core type/operator model.
Factorizations, solvers, eigensystems and decompositions belong to libraries.
The spelling `A[i, j]` is the preferred multidimensional model, but indexing
grammar and whether indexes are a tuple are an **OPEN DECISION**.

All core scientific operations MUST remain recognizable before lowering to
loops/runtime calls so the compiler can later select fusion, buffer reuse,
SIMD or BLAS.

### 6.4 Bounds — DECIDED

Safe indexing and slicing check bounds and trap or return the language's
specified error form.  Optimization may remove a check only with a proof.
Unchecked indexing requires an explicit low-level operation/region.  Index
base is zero for general collections.  Whether mathematical Vector/Matrix
retain the current one-based source indexes is an **OPEN DECISION**; mixed
index bases impose teaching, generic-code and FFI costs and require strong
evidence to retain.

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
4. Array assignment/value model and slice/view lifetime;
5. string indexing/view semantics;
6. generic constraints plus orientation/static-dimension policy;
7. module initialization;
8. runtime handle schema, target layout and C FFI surface;
9. full floating-point/relaxed-math policy and low-level syntax.

Each closure requires source examples, rejected examples, semantic tests,
targeted native codegen evidence, diagnostic expectations and a compatibility
statement against the existing compiler.
