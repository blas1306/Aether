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
