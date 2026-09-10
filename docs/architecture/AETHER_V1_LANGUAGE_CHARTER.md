# Aether v1 language charter

Status: **normative for the compiler reconstruction**.  It defines direction
and admission policy, not the feature set of the currently released RC.

Baseline: repository `ad9282d`, audited 2026-09-01.  Until a semantic decision
in this reconstruction is implemented and qualified, the current
[`AETHER_LANGUAGE_SPEC_V1.md`](../aether/AETHER_LANGUAGE_SPEC_V1.md) remains the
authority for the existing compiler.

## Identity

Aether is a general-purpose, statically typed, ahead-of-time compiled language
with first-class ergonomics for mathematics, numerical methods, simulation and
other compute-intensive work.  Scientific use is a design centre, not a
restriction to a numerical DSL.

The canonical product compiles to native artifacts.  Its design target is to
avoid unnecessary language/runtime overhead and to make C/C++-class native
performance attainable for equivalent algorithms.  Aether does not promise to
outperform well-written C or C++.

## Governing principle

> Simple things should be simple; difficult things should remain possible
> without hiding their costs.

Equivalently: **comfortable by default, explicit when necessary**.

The language MUST offer one progressive path:

1. ergonomic source with safe, predictable defaults;
2. explicit types, precision and algorithmic choices;
3. inspectable control of layout, allocation, ownership and execution;
4. a clearly marked low-level escape hatch for the cases that require it.

These levels remain Aether.  Serious control MUST NOT require rewriting the
program in C, and convenience MUST NOT conceal costs so thoroughly that they
can only be understood through an unrelated implementation layer.

## Commitments

Aether v1 is designed around these commitments:

- one statically defined meaning per accepted program;
- local, bounded type inference with readable public APIs;
- native AOT compilation as the product execution model;
- predictable evaluation, numeric and lifecycle semantics;
- explicit separation of correctness from optimization policy;
- inspectable allocation, copy, move, sharing, bounds and layout decisions;
- contiguous, layout-aware scientific core abstractions without reducing the
  language to those abstractions;
- reasonable development compilation time as a separate requirement from
  generated-code performance;
- a stable C ABI boundary for runtime and native interoperability;
- an eventual self-hosted implementation where it creates engineering value,
  without weakening the bootstrap compiler or forcing all low-level code into
  Aether.

LLVM is the primary backend strategy, not part of source-language semantics.
Rust is the bootstrap and canonical compiler-core implementation language.  A
small runtime may use Rust and C behind a generated C ABI.  Neither Rust's type
system nor C's historical type names become Aether semantics by default.

## Native compilation authority

`aether run p.ae` MUST execute an artifact produced by the same native
compilation pipeline as `aether build p.ae`:

```text
run   = compile native artifact + execute it
build = compile native artifact + retain it
```

An AST evaluator, constant evaluator or reference interpreter MAY exist for
testing and tooling.  It MUST NOT be an alternative product authority or admit
a language feature ahead of the native route.

### Meaning of supported

A language feature is **SUPPORTED** only when all of the following hold for a
declared target/profile:

1. its syntax and semantic contract are documented;
2. name and type analysis accept valid cases and reject invalid cases;
3. every required lowering and verification invariant is implemented;
4. it reaches object/native emission and linking;
5. its runtime/ABI dependencies exist on the declared target;
6. positive, negative and end-to-end native tests pass;
7. observable behavior is covered by differential or equivalent semantic
   evidence where a reference exists;
8. diagnostics fail before an unsupported downstream stage is entered.

Parser, AST, typechecker or interpreter acceptance alone is never support.
Partially implemented work MUST be explicitly gated as experimental and MUST
fail closed on the product path.  There is no silent fallback.

This is the **native-first language admission policy**.  It governs new
features, bug fixes that expand acceptance, target ports and library features
that require compiler knowledge.

## Static typing and inference

Type inference is primarily local: local bindings, expression results and
generic arguments when constraints have a unique, explainable solution.
Exported/public signatures SHOULD be explicit.  Global or interprocedural
inference MUST justify its effect on compilation time, diagnostics, tooling and
API legibility before admission.

Generics are part of the v1 architecture.  They are parametric, constrained by
explicit semantic capabilities and normally specialized/monomorphized for
native code.  Template text substitution, SFINAE-style accidental constraints
and unbounded compile-time execution are not the model.

NEXT-VERTICAL-15 admits the minimal compiler-derived capabilities `Copy` and
`Relocatable`, with `Copy => Relocatable`. They describe duplication and
ownership-preserving physical movement respectively; they are not a general
trait, interface or operator system and users cannot implement or assert them.
Constraints are checked on the parametric body and every explicit, inferred or
forwarded application, then erased before native lowering.

## Mathematical and scientific ergonomics

Fixed-width scalar types, explicit precision and serious floating-point
semantics are foundational.  `Array<T>`, oriented `Vector` and `Matrix<T>` are
core abstractions rather than primitive scalar types.  Matrix is not defined as
`Array<Array<T>>`; implementations MUST be able to preserve contiguous storage,
shape, strides, layout, alignment, aliasing and view information long enough
for optimization and native interoperation.

Natural structural operations belong with the type/operator model.  Specialized
factorizations, solvers and decompositions belong in libraries.  This boundary
is chosen by semantic generality and optimization needs, not by what happens to
be easiest in the bootstrap interpreter.

Optimization levels MUST NOT silently weaken floating-point semantics.  Strict
optimization and relaxed/fast mathematics are separate policies.  The
middle-end MUST preserve high-level facts needed for fusion, buffer reuse,
allocation elimination, SIMD and BLAS selection until the relevant decision is
made.

### Closed primitive scalar baseline

For the reconstruction, `int` is the transparent, target-independent alias of
`int64`; only `isize`/`usize` follow pointer width.  Integer literals are exact
contextual compiler values and default to `int` when unconstrained.  Ordinary
signed and unsigned overflow traps rather than wrapping or becoming undefined,
independently of optimization level.  Explicit wrapping, checked-result and
saturating families may be designed later.

`float32` and `float64` use IEEE-754 binary32 and binary64 representations;
`float = float32`, `double = float64`, and an unconstrained floating literal
defaults to `float64`.  Full conversion, rounding, NaN, infinity, subnormal,
signed-zero, FMA and cross-target reproducibility rules remain in the semantic
decision ledger.  No normal optimization profile implies fast math.

Primitive booleans, integers, floating values and `char` have value semantics:
copying or assigning them has no ARC, ownership transfer or observable aliasing.
The first vertical compiler represents scalar overflow and division-by-zero as
structured non-recoverable MIR traps; this intentionally does not choose the
future recoverable error or exception model.

NEXT-VERTICAL-5 extends that foundation with nominal value structs. Their
canonical construction is positional application syntax (`Point(x, y)`), with
arguments mapped in field declaration order. They copy by value, contain no
implicit identity or heap ownership, and use resolved nominal/field identities
below HIR. Named-field initializer syntax is not part of this milestone; a
future named-argument design should apply coherently to functions and aggregate
construction.

NEXT-VERTICAL-6 adds nominal value enums with positional payloads and exhaustive
statement matching. Variants have resolved semantic identities, are constructed
through an explicit enum qualifier, and copy by value. Matching covers every
variant exactly once and binds payloads by copy. Declaration-order bootstrap
tags and a typed internal layout do not stabilize public discriminants or ABI,
and this milestone adds no wildcard patterns, ownership, allocation or special
error-propagation semantics.

NEXT-VERTICAL-10 adds a deliberately narrow ownership substrate before the
final collection abstractions: `Buffer<T>` owns fixed-length contiguous
storage, transfers ownership by move, and is destroyed exactly once on normal
paths. `View<T>` and `ViewMut<T>` are non-owning pointer-and-length access
capabilities with checked zero-based indexing. This milestone does not define
`Array<T>`, resizing, shared ownership or general moves. Buffer elements are
temporarily restricted to concrete Copy/no-drop types, and storing ownership or
views inside user aggregates is rejected until transitive lifecycle semantics
are implemented rather than approximated. Borrowed reference/view descriptors
are likewise excluded from Buffer elements so allocation ownership cannot
silently extend their lifetime.

NEXT-VERTICAL-11 makes that ownership structural for nominal aggregates.
Concrete structs and enums inherit Copy and destruction requirements from
their substituted fields/payloads, so ordinary user types may own Buffer
without hidden copies or compiler-specific container wrappers. Whole-value
moves, by-value calls and returns transfer ownership; compiler-generated drop
glue recursively destroys structs in reverse field order and only the active
enum variant. Partial moves and non-Copy payload bindings in matches remain
explicitly deferred. Stored references/views and Buffer elements requiring
drop remain forbidden; this milestone composes ownership outward rather than
weakening lifetime or element-destruction rules.

NEXT-VERTICAL-12 makes enum-pattern ownership explicit. A value match consumes
a non-Copy enum as one whole root and transfers bound payload ownership exactly
once; `match (ref value)` and `match (ref mut value)` instead bind arm-scoped
shared or writable references to the selected active payload. Writable remains
a capability, not an exclusivity or LLVM `noalias` promise. This special enum
destructure does not admit arbitrary struct/field partial moves.

The same vertical admits the minimal `MaybeMoved` state at control-flow joins.
It is never usable by ordinary source operations: it exists only so normal-path
cleanup can choose between one recursive drop and no drop. Compiler-generated
root-level flags are emitted only for roots that actually need such conditional
cleanup; uniform ownership and early-return paths stay flag-free. Loop-carried
ownership ambiguity remains rejected, and aborting traps still do not unwind.

NEXT-VERTICAL-13 adds `Array<T>` as the normal fixed-size computational
collection. It owns one exact contiguous allocation, is non-Copy/needs-drop,
uses checked zero-based indexing, and is constructed either by the neutral
collection literal `{...}` (including empty `{}`) or by `Array<T>(length,
fill)`. Its length never changes and it has no capacity, growth, push/pop,
reserve, resize or reallocation behavior. `Buffer<T>` remains a distinct
lower-level storage primitive even where physical allocation machinery is
shared. Elements are temporarily limited to concrete Copy/no-drop types;
Array itself may compose inside owning structs, enums and concrete generics.

NEXT-VERTICAL-14 adds the distinct dynamic `List<T>` collection. It shares the
neutral `{...}` literal syntax and checked zero-based indexing with Array, but
tracks logical length separately from storage capacity and supports explicit
`push` and `reserve` structural mutations. Its bootstrap descriptor owns
contiguous storage and initializes only `[0, length)`; reserved capacity is not
source-visible. Growth allocates, copies the initialized prefix, frees replaced
storage and preserves data. Exact capacity growth is implementation policy.

List is non-Copy/needs-drop through the existing structural ownership system.
V14 retains the concrete Copy/no-drop element restriction. References and
views into List storage prevent potentially invalidating structural mutations,
including calls through `ref mut List<T>`, independent of runtime spare
capacity. Element assignment is not structural. Array remains fixed and gains
no dynamic operations. V15 adds public Copy/Relocatable constraints but keeps
the stricter concrete collection-element gate internal. `pop`, resize,
non-Copy elements and general method syntax remain deferred.

NEXT-VERTICAL-16 replaces that temporary gate for `Array<T>` and `List<T>`.
Concrete elements must be Relocatable and storable without embedded references
or views; Copy and destruction requirements are independent and no longer
exclude owning elements. Literals and push consume non-Copy values, List growth
relocates the initialized prefix into fresh uninitialized storage without
duplicating ownership, and generated collection drop glue destroys elements in
reverse index order before freeing storage. Fill construction still requires
Copy. Buffer keeps its narrower V10 element policy. Symbolic collection
elements remain conservative when stored-borrow freedom cannot be proven from
the public capability vocabulary.

The collection/mathematics distinction is intentional. `List<T>` is the
dynamic zero-based computational collection sharing `{...}` literal syntax.
`Vector<T, Orientation>` (V21) and future `Matrix<T>` are mathematical types using
bracket literals and one-based indexing. A Matrix literal is one structurally
two-dimensional construct with semicolon-separated rows; Matrix is not
semantically a nested Array, List or Vector.

## Safety and control

Safe and ergonomic behavior is the default.  Value semantics, moves, shared
ownership, non-owning access and raw access are distinct concepts.  ARC is a
tool for actual sharing, not a universal default.  Aether is not required to
copy Rust's borrow checker.

A future explicit low-level region or operation class MAY permit raw pointers,
unchecked indexing, manual allocation, intrinsics, custom allocators and FFI.
Such operations MUST be locally visible, have specified optimizer/aliasing
consequences and never make ordinary safe code implicitly unsafe.

NEXT-VERTICAL-17 formalizes persistent owning-storage legality as the positive,
compiler-derived `Storable` capability. It is independent of duplication,
relocation and destruction: `Copy => Relocatable` remains the only cross-
capability implication. References/views are not Storable under the current
lifetime model. Structs and enums derive it from all stored fields/payloads;
owning containers derive it from their elements and may still require drop.
Array elements require Storable, while List elements additionally require
Relocatable for growth. These same positive requirements admit symbolic generic
collections before monomorphization. Fill separately requires Copy. Source code
cannot implement capabilities, and no runtime capability machinery is introduced.
This does not admit stored borrows, named lifetimes, borrowed returns, self-
references, pinning or extraction operations. Buffer's retained Copy/no-drop
source gate is a current constructor/drop implementation limit, not a general
semantic law of storage.

NEXT-VERTICAL-18 admits whole-element owning extraction with `pop(list)`.
It checks nonemptiness before access and traps with structured ListEmpty on
failure. Success transfers the final value exactly once, makes its old storage
slot uninitialized and decrements length without changing capacity or backing
allocation. Copy and owning non-Copy elements follow the same prefix rule.
Take, source Move and storage Relocate retain distinct compiler semantics;
length alone represents the runtime initialized prefix, without a slot bitmap.
Pop is a storage-stable range mutation. Provably surviving direct prefix
references remain valid; references/views that may cover the removed tail are
rejected. Whole-list views cover the old prefix, and nested provenance remains
conservative. A future optional library API remains independent; this milestone
adds no Option magic, remove/insert, methods, stored lifetimes or Array extraction.

NEXT-VERTICAL-19 adds `swap_remove(list, index)` for indexed owning extraction.
It uses zero-based usize indexing and traps with IndexOutOfBounds before any
mutation when out of range. The old tail replaces the removed slot, unless the
removed slot is itself the tail. Order is not preserved; intended complexity is
O(1), modulo element relocation glue cost. Take plus optional Relocate completes
before length changes, leaving a fully initialized final prefix. Backing pointer
and capacity are stable, and the operation allocates/frees nothing. Borrows to
`{index, tail}` and whole-list views block it; provably unaffected direct element
references survive. Existing generic storage guarantees suffice. V20 extends extraction with
order preservation below; no methods or lifetime system is added.


NEXT-VERTICAL-20 adds `remove(list, index)`, preserving order at intended
O(N-i) time, modulo element relocation glue. It performs exactly N-i-1 forward
slot relocations after Take(index); tail/singleton cases perform none. The
hole moves from index to old tail before length is committed. Bounds failure
uses IndexOutOfBounds before any storage mutation. Pointer/capacity remain
stable and the operation allocates/frees nothing, including owning elements.
Its StableStructuralMutation invalidates old suffix [index,N). Provably earlier
direct references survive; affected/unknown references and whole views block
it. MIR and SSA independently prove the forward hole loop and final initialized
prefix. List's existing Storable + Relocatable requirement suffices. Insert,
drain, range erase, methods, Option, lifetimes and Array removal are not added.

## Performance and predictability

Execution performance and compilation performance are independent product
requirements.  Development profiles prioritize short feedback and future
incrementality.  Production profiles enable progressively more expensive
middle-end and LLVM work.  Correctness checks, lifecycle rules and strict
floating-point meaning are not optional optimizations.

Costs that materially affect performance—allocation, retain/release, copies,
implicit numeric conversions, bounds checks, dynamic dispatch and temporary
buffers—MUST have a documented model and SHOULD be inspectable through compiler
tooling.

## Self-hosting

Self-hosting is a long-term product goal, not an early architecture constraint.
Rust Stage0 MUST remain capable of building a clean checkout.  Aether code may
progress from high-level libraries and tools toward compiler components only
after the required language subset, bootstrap path and differential gates are
stable.

The final system MAY retain Rust and C where they provide a clearer, safer or
more portable implementation.  “Self-hosted” does not require 100% Aether and
zero Rust/C.

## Compatibility and evolution

The existing compiler is an executable specification, corpus and differential
oracle during reconstruction; it is not automatically the v1 design.  Existing
semantics are classified as retained, deliberately changed or still open.
Changes MUST be explicit, tested and accompanied by a compatibility/migration
decision.  They MUST NOT arise accidentally from a new host language, backend
or target.

Source compatibility, semantic compatibility, ABI compatibility, diagnostic
compatibility and artifact compatibility are separate domains.  No domain is
promised unless its versioned contract says so.

## Non-goals

Aether v1 does not attempt to:

- be faster than C++ by declaration;
- reproduce C/C++ historical integer naming or template metaprogramming;
- provide Python-style unrestricted dynamism;
- become a numerical-only DSL;
- hide every allocation, ownership or precision choice;
- require users to understand low-level machinery for simple programs;
- force premature self-hosting;
- standardize LLVM IR or internal compiler representations as public APIs;
- expand a scientific package ecosystem before language and core abstractions
  are stable;
- treat implementation progress in Python or Rust as evidence of language
  support.

## Governance rule

Every proposal that changes accepted programs, observable behavior, layout,
ownership, FFI or optimization legality MUST update the semantic contract, name
its open decisions, identify its end-to-end native path and define its
qualification evidence before being called supported.


## NEXT-VERTICAL-21 mathematical foundation

The isolated compiler admits `Vector<T, Row>` and `Vector<T, Column>` with
contextual `[...]` mathematical literals, including zero-dimensional `[]`.
Orientation is part of canonical type identity. Vectors own fixed contiguous
storage, require Storable elements, and use checked one-based usize indices.
`dimension(v)` is a semantic intrinsic. Array/List retain `{...}` and zero-based
indices. No implicit orientation or Array conversion, raw Vector-to-View
conversion, capacity or dynamic mutation is admitted. Moves, drop and element
references compose with existing ownership; non-Copy partial extraction and
replacement remain rejected. Matrix's `[a,b; c,d]` and `A[i,j]` are reserved for a
future structurally 2D type. Mathematical arithmetic and numeric capabilities
are separate milestones. See [the V21 report](NEXT_VERTICAL_21_REPORT.md).


## NEXT-VERTICAL-22 consuming transpose

`transpose(v)` explicitly consumes an owning Vector and flips Row/Column in
its canonical type. It preserves the exact element type, backing pointer,
dimension, component order and values. This is an O(1) descriptor transfer with
zero allocation, free, element copy, relocation or drop. The source is moved;
live element borrows prevent consumption. No implicit orientation assignment is
added. T: Storable suffices, including owning elements; no numeric capability
is required. Transpose never conjugates. Borrowed VectorView transpose and
Matrix transpose require separate contracts. See [the V22 report](NEXT_VERTICAL_22_REPORT.md).


## NEXT-VERTICAL-23 — Matrix foundation implemented

Matrix<T> is now a first-class mathematical type with runtime value shape,
Storable elements, fixed contiguous ownership, `rows` / `columns` and checked
one-based `A[i,j]` access. Mathematical brackets form a contextual family:
Vector admits a single row; Matrix admits rectangular semicolon-separated rows,
a one-row literal, a one-column literal and empty 0x0. Shape never enters TypeId.
Array/List remain zero-based brace collections. Row-major physical storage is a
bootstrap choice; mathematical identity is independent of layout and of any
nested containers. Matrix arithmetic, transpose, MatrixView/strides, slicing,
static shapes and numeric traits remain separate future work. V22 Vector
transpose keeps its consuming O(1) contract and rejects Matrix.

See [NEXT_VERTICAL_23_REPORT.md](NEXT_VERTICAL_23_REPORT.md).

## NEXT-VERTICAL-24 — borrowed matrix views implemented

MatrixView<T> and MatrixViewMut<T> preserve mathematical 2D shape and one-based
indexing with explicit element strides. They are Copy/Relocatable, non-Storable
borrowed descriptors with no backing ownership or drop. Mutable views confer
write capability without exclusivity. `matrix_view`/`matrix_view_mut` derive
normal views; `transpose_view`/`transpose_view_mut` swap shape and strides in
O(1), preserving the pointer and performing no element/storage operation.
They accept Matrix owners and existing matrix-view Places, including projected
owners and explicit references. Copies and transposes retain lexical owner
provenance; live aliases prevent owner move/replacement. Stored/returned borrows
remain forbidden. Matrix's owner descriptor/layout is unchanged, and owning
Matrix transpose remains unresolved. Slicing, row/column VectorView, arithmetic,
BLAS, numeric traits and named lifetimes remain future work.

See [NEXT_VERTICAL_24_REPORT.md](NEXT_VERTICAL_24_REPORT.md).


## NEXT-VERTICAL-25 — oriented borrowed vector views implemented

VectorView<T,Row/Column> and VectorViewMut<T,Row/Column> retain mathematical
1D identity with orientation in TypeId and dimension/element stride in the
runtime descriptor. Normal owner views borrow contiguous storage with stride 1;
borrowed transpose flips only type orientation and preserves pointer, dimension,
stride and provenance in O(1). Both descriptors are Copy/Relocatable,
non-Storable and have no drop. Writable capability does not imply uniqueness.
Checked one-based indexing and element references use the actual stride.
Owners cannot move or be replaced while derived aliases are lexically live.
Projected owners and explicit owner references are supported; stored/returned
borrows and potentially invalidating nested List effects remain conservative.
V22 consuming transpose and V24 MatrixView retain their separate contracts.
Matrix row/column projection is future work, as are slicing, arithmetic,
conjugation, methods, traits, raw descriptor construction and named lifetimes.

See [NEXT_VERTICAL_25_REPORT.md](NEXT_VERTICAL_25_REPORT.md).


## NEXT-VERTICAL-26 admission — complete mathematical axes

The isolated native compiler now connects Matrix/MatrixView with the existing
oriented VectorView abstraction through full-axis borrowed projections.
`row(x,i)` and `column(x,j)` produce Row and Column shared views; `_mut` variants
require write capability through the source Place. Mathematical orientation
MUST remain independent from physical stride, including transposed sources.
Projection is zero-copy, with fixed-axis bounds before address calculation,
closed independently verified descriptor recipes and the same underlying owner
provenance. No allocation, owning row copy or hidden element transfer is allowed.
Existing lexical/no-escape and mutable nested-List effect restrictions apply.
Slicing, submatrices, arithmetic, methods and lifetime extensions are not admitted.
See [NEXT_VERTICAL_26_REPORT.md](NEXT_VERTICAL_26_REPORT.md).

## NEXT-VERTICAL-27 admission — built-in elementwise + and -

The isolated native compiler admits its first mathematical arithmetic for
concrete built-in scalar elements: signed/unsigned 8/16/32/64-bit integers,
isize/usize, float32/float64 and their canonical aliases. Arithmetic admission
is a compiler query; Copy/Relocatable/Storable remain storage capabilities and
MUST NOT establish arithmetic on symbolic T or user-defined elements.

Any readable Vector/VectorView/VectorViewMut pair with identical element TypeId
and orientation yields a fresh owning Vector. Any readable
Matrix/MatrixView/MatrixViewMut pair with identical element TypeId yields a
fresh owning Matrix. Inputs are borrowed through expression evaluation and
remain usable. Dynamic dimension equality, or ordered row then column equality,
MUST succeed before result allocation. ShapeMismatch is distinct from bounds,
integer overflow and allocation traps. Logical strides govern every view read.

Compatible empty inputs allocate nothing. Nonempty arithmetic allocates one
backing, performs one scalar operation and initializes each result slot once.
Integer overflow is checked and aborting; floats use ordinary IEEE semantics.
MIR/SSA MUST verify ordered guards and complete initialization before owner
escape. No unwinding, behavioral generics, public operator protocol,
multiplication/division, promotion, broadcasting, BLAS or lifetime extension
is implied. See [NEXT_VERTICAL_27_REPORT.md](NEXT_VERTICAL_27_REPORT.md).


## NEXT-VERTICAL-28 — built-in scalar multiplication

The isolated native compiler admits scalar * vector-like, vector-like * scalar,
scalar * matrix-like and matrix-like * scalar. Vector/VectorView/VectorViewMut
and Matrix/MatrixView/MatrixViewMut are readable inputs; operations MUST NOT
consume existing mathematical owners. Results are fresh owners preserving
orientation and logical shape, reading explicit strides and writing contiguous
storage. Nonempty results allocate one backing; empty results allocate none.

Scalar and element MUST share their exact concrete canonical built-in integer
or float TypeId. Existing contextual literal typing is allowed, including an
integer literal contextualized to double. Typed values receive no promotion.
`supports_builtin_multiply` is an internal operation query; Copy/Storable do
not establish multiplication, including in uninstantiated generic bodies.

Source operand order, temporary borrowing protections, checked integer overflow
and IEEE floats remain mandatory. Empty scaling still evaluates its scalar.
There is no second shape and no ShapeMismatch dependency. The verified V27
initialization region extends to one descriptor and one invariant scalar.

Pairwise mathematical multiplication, dot/outer/matmul/Hadamard, division,
broadcasting, promotion, public Mul/Numeric traits, BLAS, slicing, methods and
lifetime changes remain outside this vertical.

## NEXT-VERTICAL-29 — behavioral scalar generic guarantees

The isolated compiler admits independent `Add`, `Sub`, `Mul` constraints using
the existing inline conjunction syntax. The bootstrap signatures MUST remain
homogeneous: T + T -> T, T - T -> T, T * T -> T. Compiler-provided satisfaction
is limited to existing built-in integer and float scalars, through canonical
aliases. bool, aggregates, containers and references MUST NOT acquire behavior
by structural derivation. A nominal declaration's constraint restricts its
argument and MUST NOT confer that behavior on the nominal type itself.

Structural Copy/Relocatable/Storable retain their representation and ownership
rules. The only non-reflexive implication is Copy => Relocatable. Behavioral
constraints MUST NOT change type properties or turn a symbolic parameter into
a concrete numeric type. Ordinary move/Copy rules still govern operands.

All generic bodies, including unused bodies and forwarding calls, MUST validate
against declared guarantees before instantiation. Unsatisfied arguments MUST
fail before InstanceId allocation/caching. Parametric HIR preserves the required
behavior; monomorphization selects existing checked integer or IEEE float
operations before MIR. There are no hidden capability parameters, runtime
dictionaries, indirect dispatch or new arithmetic runtime operations.

User implementations, traits/interfaces, associated types, heterogeneous
operators, generic container arithmetic, Numeric, Zero/One and dot/outer/matmul
remain deferred. See [NEXT_VERTICAL_29_REPORT.md](NEXT_VERTICAL_29_REPORT.md).


## NEXT-VERTICAL-30 — generic non-consuming mathematical kernels

Element-generic Vector/VectorView/VectorViewMut with concrete Row or Column,
and Matrix/MatrixView/MatrixViewMut, admit the existing addition, subtraction
and scalar multiplication under independent Storable + Copy + Add/Sub/Mul
requirements. Storable proves storage of the owning result's element; Copy
proves non-destructive element reads and scalar reuse. Behavioral guarantees
remain homogeneous and imply neither structural property. Containers remain
non-Copy owners and are borrowed by mathematical arithmetic.

Bodies MUST prove these obligations parametrically, even when unused; a later
concrete Copy instantiation cannot legalize a deficient body. Forwarding must
prove every callee requirement. Views remain borrowed non-Storable descriptors;
their element can independently be Storable. Existing explicit reference syntax,
shape guards, orientation, strides, evaluation order and empty semantics persist.

Behavioral kernel metadata MUST be resolved to existing checked integer or IEEE
scalar instructions before concrete HIR crosses into MIR. No runtime dispatch,
dictionaries, hidden operator arguments or behavioral layout metadata is allowed.
No user implementations, structural nominal behavior derivation, heterogeneous
operators, generic orientation, identities, dot/outer/matmul, promotion, in-place
arithmetic, BLAS or lifetime extensions are admitted by V30.


## V31 admission — native oriented Vector products and Zero

The mathematical foundation now admits Row(n)×Column(n) -> T and
Column(n)×Row(m) -> Matrix<T> of exact shape n×m. Orientation denotes 1×n or
n×1, even at dimension zero, and stays semantic TypeId identity. Both products
accept readable owners and strided shared/mutable views. Same-orientation
products remain rejected. There is no implicit transpose or Hadamard meaning.

Zero is a closed algebraic value capability for built-in integers and floats,
independent of structural and binary behavioral guarantees. Inner reduction
requires Copy+Add+Mul+Zero, starts at canonical positive zero, and runs in exact
logical order using separate checked/IEEE multiplication and addition. It needs
no allocation. Outer needs Storable+Copy+Mul, preserves zero axes and initializes
one nonempty Matrix backing with n*m multiplications/stores. Generic contracts
are checked parametrically, then operations/Zero concretize before MIR.

Matrix products remain later verticals. dot(Vector,Vector), Array/List dot,
outer()/matmul() functions, One, user implementations, widened accumulators,
generic orientation, BLAS and SIMD/reassociation remain unimplemented. A future
dot may concern Array/List sequences; advanced decompositions belong to future
STD LinearAlgebra. No lifetime, slicing or legacy behavior changes are admitted.
See [NEXT_VERTICAL_31_REPORT.md](NEXT_VERTICAL_31_REPORT.md).

## V32 admission — Matrix×Column and Row×Matrix

The native algebraic `*` table now admits Matrix<T>(m,n)×Column<T>(n)->Column<T>(m)
and Row<T>(m)×Matrix<T>(m,n)->Row<T>(n), in addition to V31 products and scalar
scaling in either order. Exact canonical element T and contraction equality are
mandatory. Any readable owner/view/mutable-view combination works using logical
Matrix and Vector strides, including transpose_view and simultaneous striding.
Inputs remain borrowed; the result is a fresh owning oriented Vector.

Storable+Copy+Add+Mul+Zero are independent generic requirements, checked even
for unused bodies and forwarding. Every output reduces from Zero in increasing
logical contraction order with checked integer Mul/Add or strict separate
floating Mul/Add. Positive output extent allocates once; zero output extent
allocates nothing. A zero contraction with positive output extent yields a
nonempty vector of Zero, with no Mul/Add and one store per output.

At the V32 boundary Matrix×Matrix was deferred (admitted by V33 below).
Matrix×Row, Column×Matrix and same-orientation Vector products remain rejected. No runtime capability dispatch, matmul/dot/Hadamard intrinsic,
BLAS, widening, user impl or lifetime change. Advanced decompositions belong to
future LinearAlgebra STD. See [NEXT_VERTICAL_32_REPORT.md](NEXT_VERTICAL_32_REPORT.md).


## V33 admission — native Matrix×Matrix

Native `*` completes basic algebraic multiplication with
Matrix<T>(m,k)×Matrix<T>(k,n)->owning Matrix<T>(m,n). Both operands independently
accept Matrix/MatrixView/MatrixViewMut and require exact canonical T. Inputs
are borrowed, may alias, and use independent logical strides, including both
transposed. Matrix(1,k)×Matrix(k,1) remains Matrix(1,1), never scalar.

Three independent extents define output rows, output columns and contraction.
Shape equality lhs.columns=rhs.rows is checked before empty bypass, allocation,
loads or operations. Empty output axes preserve both dimensions without backing
allocation. Zero contraction with positive output axes creates m*n Zero cells,
one allocation and m*n stores, with no source loads, multiplication or addition.

Generic T independently requires Storable+Copy+Add+Mul+Zero. Each cell starts
at exact typed Zero, traverses logical contraction in increasing order, and
performs checked integer Mul then Add or strict floating fmul then fadd. Output
traversal is rows then columns. There is no FMA, reassociation, BLAS, SIMD,
widening, helper surface or runtime capability dispatch. General exact cost is
m*k*n Mul/Add each, 2*m*k*n loads, m*n stores and one nonempty result allocation.

V31/V32 results retain their distinct scalar, Matrix and oriented Vector types;
scaling and +/− remain unchanged. Row×Row, Column×Column, Matrix×Row and
Column×Matrix remain rejected. Advanced decompositions belong to future STD
LinearAlgebra. See [NEXT_VERTICAL_33_REPORT.md](NEXT_VERTICAL_33_REPORT.md)
and the complete table in [compiler-next/README.md](../../compiler-next/README.md).


## LANGUAGE-PARITY-1 — explicit program entry and source comments

A program MUST have exactly one selected, non-generic `int main()` with zero
parameters in its entry module. Canonical type identity remains authoritative:
`int`, `int64` and transparent aliases of that type are equivalent spellings.
Only this resolved function receives implicit `return 0;` on normal fallthrough.
Explicit zero and nonzero returns remain valid and preserve the existing process
exit-status path. Other non-void functions, including imported helpers named
`main`, MUST retain missing-return rejection. No script mode, top-level
executable statements, global executable initialization or synthetic main exists.

Source comments are whitespace: `//` ends at the line ending or EOF, and
`/* ... */` ends at the first `*/`, without nesting. Unterminated block comments
MUST receive structured lexer diagnostic E0002 at the opening delimiter.
Original source byte spans, source identities, diagnostic line numbers and
character columns MUST be preserved, including LF and CRLF within comments.
Comments MUST NOT become semantic IR nodes. The generated main return is
explicit in HIR before ownership cleanup and ordinary MIR/SSA/LLVM lowering.
See [LANGUAGE_PARITY_1_REPORT.md](LANGUAGE_PARITY_1_REPORT.md).
