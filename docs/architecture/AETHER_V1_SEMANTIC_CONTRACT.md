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

The candidate primitive set is:

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

The baseline compatibility aliases are:

```text
alias double = float64;
alias float  = float32;
alias byte   = uint8;
```

`byte` has no textual or character semantics.  `boolean` MAY be retained as a
compatibility alias for `bool`; that spelling policy is an **OPEN DECISION**.
Nominal wrappers/newtypes are a separate future facility.

Alias expansion MUST terminate, reject cycles, preserve source alias names for
diagnostics where useful and canonicalize before layout/code generation.

### 1.3 Meaning of `int` — OPEN DECISION

`int` MUST have one target-independent width.  It MUST NOT silently follow
pointer width.  The live choices are:

| Choice | Advantages | Costs |
|---|---|---|
| `int32` | Current Aether compatibility; compact arrays; common hardware scalar; existing overflow corpus and ABI | More overflow surprises in general/scientific counters; frequent conversion to `usize`; legacy name remains narrower than many users expect |
| `int64` | Larger ergonomic default; safer literals/counters; common scientific integer width | Breaks current code/ABI/goldens; doubles many integer buffers; may add conversions and reduce some SIMD density |
| no `int` | Maximum precision clarity | Harms the “comfortable by default” charter and makes literals/APIs noisy |

Recommendation pending measurement: compare `int32` and `int64` on the
versioned corpus for source breakage, memory, diagnostics, LLVM quality and
index conversions.  `isize`/`usize` remove the only valid reason for a
target-varying `int`.  The first vertical compiler milestone SHOULD use an
internal explicitly named integer type, not freeze the source alias.

### 1.4 Complex numbers — OPEN DECISION

`complex64` (two `float32`) and `complex128` (two `float64`) are required early
design inputs.  The options are primitive types, core compiler-known structs,
or ordinary core-library generics with intrinsic/operator support.

Compiler-known core types are the leading option: they permit predictable
layout, literals and vectorization without treating complex numbers as scalar
machine primitives.  The decision requires C/Fortran ABI experiments,
operator/conversion rules, transcendental semantics and LLVM codegen evidence.

## 2. Literals and numeric conversions

### 2.1 Literal typing — OPEN DECISION

Integer and real literals MUST retain exact source magnitude (and for reals,
source spelling or an exact parsed representation) until contextual typing.
The host language's integer/float behavior MUST NOT define acceptance.

Candidates:

- default immediately to `int`/`float64` with range diagnostics;
- use compiler-only unbounded literal types resolved by context;
- require suffixes when the default cannot represent the value.

The second option best supports fixed-width types and clear diagnostics, but
must be bounded so overload/generic inference stays deterministic.  Suffix
syntax remains open.  The current decimal-only, `int32`/`double` behavior is a
legacy oracle, not the target decision.

### 2.2 Implicit conversions — PROVISIONAL

Implicit conversion MUST be value-preserving for every source value.  At
minimum this permits widening within signed or unsigned families and
contextual exact conversion of a literal.  Signed↔unsigned, narrowing and
float→integer conversions MUST be explicit.

Whether an integer type implicitly converts to a floating type is an
**OPEN DECISION** because not all 32/64-bit integer values are exactly
representable in binary32/binary64.  Choices are:

- permit conventional rank-based widening and document precision loss;
- permit only when compile-time value is exactly representable;
- require explicit conversion for non-literals.

Mixed arithmetic and generic numeric constraints cannot be frozen before this
choice.  No conversion may depend on C integer promotion rules.

### 2.3 Integer overflow — OPEN DECISION

The current language traps on signed i32 add/sub/mul/neg/div/rem/power.  The
recommended baseline is checked arithmetic in safe code, independent of
optimization level, with explicit wrapping, saturating and unchecked
operations when requested.  Before closing the decision, measure loop/kernel
impact and specify:

- signed and unsigned add/sub/mul/negation;
- division by zero and signed minimum divided by `-1`;
- shifts and shift counts;
- exponentiation;
- conversions and literal overflow;
- constant-evaluation equivalence with runtime.

Release mode MUST NOT silently change checked operations to wrapping.

## 3. Floating point

### 3.1 Strict baseline — DECIDED

On an admitted target, `float32` and `float64` use IEEE-754 binary32/binary64
values and operations.  Normal optimization levels preserve the language's
strict floating semantics.  `-O3` (or equivalent) MUST NOT imply fast math.
A separately requested relaxed-math policy may weaken named guarantees and
MUST be visible in build metadata.

Strict mode preserves:

- NaN unordered behavior and propagation permitted by the specified operation;
- positive and negative infinities;
- signed zero where IEEE distinguishes it;
- subnormals unless the target profile explicitly rejects the target or a
  relaxed mode requests flush behavior;
- round-to-nearest, ties-to-even for ordinary operations unless an explicit
  rounding facility says otherwise.

The optimizer MUST NOT assume `x == x`, reassociate, contract operations,
discard signed zero, ignore NaN/infinity, or introduce flush-to-zero without a
semantic permission attached to that operation/function/module.

### 3.2 Floating details — OPEN DECISION

The contract still needs decisions for:

- permitted fused multiply-add contraction in strict mode;
- exact parse/format algorithms and shortest-roundtrip requirements;
- reproducibility across targets versus conformance within a target;
- signaling NaNs and payload preservation;
- explicit rounding-mode APIs and whether ambient hardware mode is observable;
- float→integer results for NaN, infinity and out-of-range values;
- constant evaluator parity with target execution;
- libm accuracy requirements for transcendental functions.

LLVM constrained floating-point intrinsics, ordinary FP instructions and
target attributes must be evaluated against this list.  A global fast-math bit
is insufficiently precise for mixed strict/relaxed code.

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

### 4.3 Assignment, copy and move — PROVISIONAL

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

Trivial scalars copy by value.  Value aggregates recursively follow field
semantics.  Move transfers ownership and makes the previous owning place
unavailable.  Whether a source-level move is implicit from last use, explicit,
or both is an **OPEN DECISION**.  The existing Initial IR lifecycle operations
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

### 8.2 Errors, panic and exceptions — OPEN DECISION

The repository has a qualified native exception model plus typed result structs
for parsing/files, while native safety panics currently terminate without
unwinding.  The reconstruction must choose and distinguish:

- recoverable expected errors (`Result<T,E>` or equivalent);
- language exceptions, if retained;
- unrecoverable panic/contract failure;
- foreign/runtime errors across the C ABI.

The choice controls MIR exceptional edges, cleanup, ABI, code size and
self-hosting ergonomics.  Raw Rust/C++ exceptions MUST NOT cross FFI.  Until
closed, the new core must model exceptional control-flow explicitly rather than
assuming abort or unwind.

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

## 11. Layout, ABI and FFI

### 11.1 Layout — DECIDED/OPEN

Source semantics distinguish logical value, semantic type and physical layout.
Only fixed-width scalars have an immediately fixed bit width.  Aggregate
layout, alignment, padding and calling convention are target-specific unless a
type explicitly requests an interoperable representation.

Default struct field order, reorder permission, stable representation
annotations and enum/tagged-union layout are **OPEN DECISIONS**.  Layout facts
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

The highest-impact open decisions should close in this order:

1. `int`, literal typing, conversions and overflow;
2. error model and exceptional cleanup;
3. ownership parameter modes, moves and non-owning views;
4. Array assignment/value model and slice/view lifetime;
5. string indexing/view semantics;
6. generic constraints plus orientation/static-dimension policy;
7. module initialization;
8. runtime handle schema, target layout and C FFI surface;
9. relaxed floating-point modes and low-level syntax.

Each closure requires source examples, rejected examples, semantic tests,
targeted native codegen evidence, diagnostic expectations and a compatibility
statement against the existing compiler.
