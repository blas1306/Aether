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

Run it with `compiler-next` from the repository root:

```bash
aether examples/numerical_methods/main.ae --compiler next
aether examples/numerical_methods/main.ae --compiler next -O2
```

The first command uses O0. Every printed validation must end in `true`, and O0
and O2 must produce the same eighteen lines.

La caracterización de Fase 0 de Array/List se ejecuta también como guardia de
regresión indirecta para este programa. No cambia sus contratos numéricos, sus
callables ni sus resultados; el RC futuro de colecciones permanece pendiente.

## Callable API

`Functions.ae` declares the structural alias:

```aether
alias ScalarCallable = Function<(double), double>;
```

The root solvers and integrators receive a `ScalarCallable` and invoke it
directly. `main.ae` imports packages and passes qualified functions from
`Problems.ae`, so this example covers both callable aliases and cross-package
symbol mangling. The old `ScalarFunction.evaluate(double)` interface workaround
is no longer needed.

Typed callables deliberately cover only capture-free user-defined top-level
functions. A value such as `Function<(double), double>` is represented natively by an LLVM
function pointer and has exact signature compatibility. Closures, lambdas,
bound methods, builtin references, and returning callable values remain out of
scope. A top-level wrapper can expose a builtin when needed.

## Root status API

`Results.ae` declares the payload-free enum `RootStatus` with `Converged`,
`MaxIterations`, `InvalidInterval`, and `ZeroDerivative`. `RootResult.status`
uses that type directly. Exhaustive predicates in `Results.ae` inspect the enum
without converting it to a boolean or integer error code. Bisection reports
invalid input and invalid brackets as `InvalidInterval`; Newton and secant
report a near-zero derivative/denominator as `ZeroDerivative`; exhausted loops
report `MaxIterations`.

## Integration status API

`trapezoid` and `simpson` return `IntegrationResult`, whose `value` is only a
numerical answer when `status == IntegrationStatus.Success`. A non-positive
subinterval count reports `NonPositiveSubintervalCount`; a positive odd count
passed to Simpson reports `SimpsonRequiresEvenSubintervals`. This removes the
ambiguous `0.0` sentinel: zero is a valid integral and is no longer also the
error contract.

The functions deliberately accept reversed limits. Their signed step preserves
the standard identity `integral(a, b) = -integral(b, a)` at both optimization
levels.

## Error-model boundary

Expected numerical outcomes use nominal status enums in `RootResult` and
`IntegrationResult`; no exception or sentinel is required.
