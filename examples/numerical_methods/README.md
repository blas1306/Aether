# Numerical methods dogfood example

This small multi-module program exercises Aether with reusable root-finding and
quadrature algorithms:

- bisection, Newton-Raphson, and secant methods;
- trapezoid and Simpson integration;
- `RootResult` as a structured convergence result;
- tolerance and iteration limits;
- invalid brackets, near-zero derivatives/denominators, and invalid Simpson
  subdivisions;
- interfaces, structs by value, methods, imports, loops, exceptions, and
  scalar mathematics.

Run it from the repository root:

```bash
aether --backend=ast examples/numerical_methods/main.ae
```

Every printed validation must end in `true`.

## Why `ScalarFunction` is an interface

Aether currently has expression functions and ordinary typed functions, but it
does not have a general function type that can be used for variables,
parameters, or return values. Function references are only exposed through a
special AST-interpreter path used by `Plots`. The example therefore models a
callable scalar function with the existing `ScalarFunction.evaluate(double)`
interface. This keeps the numerical algorithms reusable without adding a new
language feature or hard-coding one equation into them.

## Backend boundary

The example is intentionally still an AST-backend dogfood program. File
imports and the consolidated real scalar-math builtins now lower through IR,
SSA, and LLVM/native. The remaining blockers reported for this program are
interfaces/interface dispatch, exceptions, and general string comparison.
The numerical loops themselves use ordinary existing Aether syntax, but a
complete native version must wait for those features (or for a first-class
function design that replaces the interface). This is a known v1 blocker, not
hidden by a second artificial implementation.
