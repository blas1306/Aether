# Compiler Feature Matrix

> Classification: **Current reference**. Last reconciled: 2026-08-02.
> Capability states and typed subset rules are normative in
> [Aether Native Profile v1](../aether/AETHER_NATIVE_PROFILE_V1.md), profile
> 24. This matrix summarizes implementation stages; it does not create
> language features.

Legend: **C** complete for the typed profile subset, **P** partial/gated subset,
**N** absent. “Optimizer C” means every instruction participates in structural
operand traversal and effect-aware preservation; it does not mean a
feature-specific strength optimization exists.

| Feature family | Parser/typechecker | AST | IR/SSA | Optimizers | LLVM/native | Capability |
| --- | --- | --- | --- | --- | --- | --- |
| `int`, `double`, `boolean`, `void` | C | C | C | C | C | mixed granular C/P |
| `float`, `complex` | C experimental | C | P nominal | C preservation | N/gated | P under primitive/numeric families |
| string transport/lifecycle/equality/concat/byteLength/parse/trim/split | C | C | C | C | C | granular C; broad `strings` P |
| `null` and `T?` | C | C | C tagged | C | C `{i1,T}` | `primitive-types` P |
| enums without payload | C | C | C | C | C `i32` | `enums` C |
| structs, constructors, methods, value semantics | C | C | C | C | C for representable layouts | granular P |
| classes, fields, constructors, methods, identity/ARC | C | C | C | C | C | granular C |
| interfaces with class carrier or struct box | C | C | C witness-based | C | C | `interfaces` C |
| Array/List core, slicing, lifecycle, Eq/search | C | C | C | C | C typed subset | granular C/P |
| Vector/Matrix core | C | C | C | C | C shaped subset | P |
| top-level function values | C | C | C indirect call | C conservative | C exact signature | P |
| functions, recursion, return, `if`/`while`/`for`, break/continue | C | C | C CFG/phi | C | C typed subset | granular C/P |
| modules/imports/visibility | C | C | C combined module | C | P: no imported storage/init | P |
| process arguments and UTF-8 text files | C | C | C | C effects | C Linux subset | granular C/P |
| input | C | C | N | N/A | N/gated | unsupported |
| exceptions | C | C | C explicit event/lifecycle CFG | C conservative preservation | C private event-out path | `error-handling` C |
| user generics, closures/lambdas, class/interface inheritance, reflection | N or experiment | N/P | N | N/A | N | unsupported/outside profile |
| optimization profiles | C CLI | N/A | C | P: `-O2` aliases `-O1` | C emission | P |

## Object and interface boundary

- `T?` is always tagged; `ptr null` is not a nullable representation.
- A class value is a non-null one-word handle to an ARC object. Concrete method
  dispatch is static.
- An interface value is `{carrier,witness}`. A class carrier preserves object
  identity; a struct carrier is an owned box whose copy operation clones the
  value payload.
- Interface calls are indirect and conservatively effectful. Interface
  inheritance, default methods, downcasts, reflection, user destructors, weak
  references, unwind, and cycle collection are not implemented.

## Optimizer coverage

IR and SSA value uses are derived from dataclass instruction fields, excluding
the conventional `result` definition. Nested tuples cover calls and phi
incoming pairs. Dead-phi elimination, trivial-phi replacement, algebraic
replacement, DCE, SCCP use tracking, and copy-like propagation consume this
structural traversal. A hierarchy validation test rejects an instruction model
that cannot participate, and sentinel rewrite tests cover class/interface
operands that previously regressed.

Feature-specific folding remains intentionally limited to operations with
proved semantics. Unknown calls, interface calls, allocation, lifecycle,
memory access, traps, and mutation retain their declared effects.

Exception IR is implemented through the private event-out architecture.
`ERROR_HANDLING` is `COMPLETE` in profile 24 on Linux x86_64. ERQ-001 through
ERQ-007 and the integrated public corpus provide cross-stage differential,
ownership, diagnostic, documentation, catalog and packaging evidence. LLVM EH
remains comparison/test-only and the runtime ABI remains private. See
[ERQ-006 release evidence](exceptions/EXCEPTION_PROMOTION_EVIDENCE.md).

## Authorities

- Current language contract:
  [AETHER_LANGUAGE_SPEC_V1.md](../aether/AETHER_LANGUAGE_SPEC_V1.md)
- Current executable capability contract:
  [AETHER_NATIVE_PROFILE_V1.md](../aether/AETHER_NATIVE_PROFILE_V1.md)
- Current object representation:
  [NATIVE_OBJECT_MODEL_DESIGN.md](NATIVE_OBJECT_MODEL_DESIGN.md)
- Provisional internal ABI:
  [AETHER_NATIVE_ABI.md](AETHER_NATIVE_ABI.md)
- Dated parity evidence:
  [docs/aether/BACKEND_FEATURE_PARITY.md](../aether/BACKEND_FEATURE_PARITY.md)
