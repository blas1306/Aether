# Aether frontend experiments outside 1.0

> Classification: **Experimental / Non-normative**. This annex describes
> implementation experiments recognized by parts of the current frontend or
> AST interpreter. None of them belongs to Aether 1.0.

The normative contract is the
[Aether 1.0 Language Specification](AETHER_LANGUAGE_SPEC_V1.md). Parser,
type-checker, tooling, or AST acceptance of an item below does not establish a
language guarantee, portability promise, compatibility commitment, or future
acceptance into Aether.

## Recognized experimental surfaces

Current implementation experiments include some of the following:

- inferred declarations by assignment and destructuring;
- stored ranges and additional iteration shapes;
- nested functions;
- imported global storage and module initialization;
- `float`, `complex`, imaginary literals, tuples, `null`, and nullable types;
- classes, interfaces, constructors, methods, and dispatch;
- nested/unregistered collection layouts;
- advanced Vector/Matrix operations and host linear algebra;
- string interpolation, input, plotting, and general formatting;
- `throw`, `try`, and `catch`.

The frontend's current experimental interpolation spelling is `$expression$`,
not `${expression}`. Native profile 22 rejects the resulting interpolated
string with `AE-BACKEND-STRINGS`; stable Aether source uses concatenation and
explicit supported formatting helpers instead.

Some listed constructs are incomplete, may be mutually inconsistent, or may
change without migration support. The AST interpreter is the REPL backend and
differential reference for stable programs, but its additional behavior does
not form an “AST profile” of Aether 1.0.

The checked-in demonstrations are the entries classified
`AST_ONLY_EXPERIMENTAL` in the
[examples manifest](../../examples/v1_examples_manifest.json). Every such entry
declares its concrete `outside_v1_features`; native must reject those features
at the capability gate rather than reaching LLVM lowering. Interactive,
plotting, module-only, and frontend-demonstration entries may declare
`run: false`, while still being required to parse, typecheck, and match their
native exclusion.

## Re-entry rule

An experimental surface can enter a later language version only through an
explicit RFC, normative semantics, a native capability gate, verified
IR/SSA/LLVM lowering, differential evidence, documentation, tooling, and an
updated profile audit. Removing a rejection merely because one layer happens
to accept the syntax is not sufficient.
