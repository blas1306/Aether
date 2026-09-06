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
Future `Vector<T, Orientation>` and `Matrix<T>` are mathematical types using
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
