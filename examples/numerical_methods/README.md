# Numerical methods dogfood example

This multi-module program exercises reusable root-finding and quadrature
algorithms written entirely in Aether:

- bisection, Newton-Raphson, and secant methods;
- trapezoid and Simpson integration;
- `RootResult` as a structured convergence result;
- tolerance and iteration limits;
- invalid brackets, near-zero derivatives/denominators, and invalid Simpson
  subdivisions;
- typed top-level callables, structs by value, imports, loops, and real scalar
  mathematics.

Run either backend from the repository root:

```bash
aether --backend=ast examples/numerical_methods/main.ae
aether --backend=llvm examples/numerical_methods/main.ae
```

Every printed validation must end in `true`, and both backends must produce the
same twelve lines.

## Callable API

`Functions.ae` declares the structural alias:

```aether
public alias ScalarCallable = double(double);
```

The root solvers and integrators receive a `ScalarCallable` and invoke it
directly. `main.ae` passes selectively imported functions from `Problems.ae`,
so this example covers both callable aliases and cross-module symbol mangling.
The old `ScalarFunction.evaluate(double)` interface workaround is no longer
needed.

Typed callables deliberately cover only capture-free user-defined top-level
functions. A value such as `double(double)` is represented natively by an LLVM
function pointer and has exact signature compatibility. Closures, lambdas,
bound methods, builtin references, and returning callable values remain out of
scope. A top-level wrapper can expose a builtin when needed.

## Remaining error-model boundary

Native `throw`/`try-catch` is still unsupported. To keep one honest program
executable by both backends, invalid numerical inputs return the existing
failure representation: root solvers return `RootResult(..., false)`, while an
invalid integration interval count returns `0.0`. The last choice is only a
dogfood sentinel; it is not proposed as the final numerical-library error API.
