# Numerical methods dogfood example

This multi-module program exercises reusable root-finding and quadrature
algorithms written entirely in Aether:

- bisection, Newton-Raphson, and secant methods;
- trapezoid and Simpson integration;
- `RootResult` as a structured convergence result with nominal `RootStatus`;
- `IntegrationResult` as a structured quadrature result with nominal
  `IntegrationStatus`;
- tolerance and iteration limits;
- invalid brackets, near-zero derivatives/denominators, and invalid Simpson
  subdivisions, including distinct non-positive and odd-count cases;
- reversed integration limits, preserving `integral(a, b) = -integral(b, a)`;
- typed top-level callables, structs by value, imports, loops, and real scalar
  mathematics.

Run either backend from the repository root:

```bash
aether --backend=ast examples/numerical_methods/main.ae
aether --backend=llvm examples/numerical_methods/main.ae
```

Every printed validation must end in `true`, and both backends must produce the
same eighteen lines.

La caracterización de Fase 0 de Array/List se ejecuta también como guardia de
regresión indirecta para este programa. No cambia sus contratos numéricos, sus
callables ni sus resultados; el RC futuro de colecciones permanece pendiente.

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

## Root status API

`Results.ae` declares the payload-free enum `RootStatus` with `Converged`,
`MaxIterations`, `InvalidInterval`, and `ZeroDerivative`. `RootResult.status`
uses that type directly, so callers compare qualified members instead of
interpreting a boolean or integer error code. Bisection reports invalid input
and invalid brackets as `InvalidInterval`; Newton and secant report a near-zero
derivative/denominator as `ZeroDerivative`; exhausted loops report
`MaxIterations`.

## Integration status API

`trapezoid` and `simpson` return `IntegrationResult`, whose `value` is only a
numerical answer when `status == IntegrationStatus.Success`. A non-positive
subinterval count reports `NonPositiveSubintervalCount`; a positive odd count
passed to Simpson reports `SimpsonRequiresEvenSubintervals`. This removes the
ambiguous `0.0` sentinel: zero is a valid integral and is no longer also the
error contract.

The functions deliberately accept reversed limits. Their signed step preserves
the standard identity `integral(a, b) = -integral(b, a)` in both backends.

## Remaining error-model boundary

Native `throw`/`try-catch` is still unsupported. To keep one honest program
executable by both backends, expected numerical failures use nominal status
enums in `RootResult` and `IntegrationResult`; no exception or sentinel is
required.
