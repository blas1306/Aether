# Aether — ANONYMOUS-FUNCTIONS-V1 — Implementation & Qualification Report

## Estado

`ANONYMOUS-FUNCTIONS-V1 CLOSED`.

Este vertical implementa exclusivamente arrow lambdas sin captura. No se
introdujeron `Closure`, environment heap, ARC, helpers de runtime ni cambios al
ABI de `Function`. `OWNING-CLOSURES-READ-V1` permanece fuera de alcance.

## Implementación

La sintaxis pública admitida es `(T x, U y) => expression`, incluidos cero, uno
o varios parámetros tipados. El parser conserva un nodo `AstExprKind::Lambda`,
su span completo y un `LambdaId` reproducible derivado del offset source dentro
del módulo. Cada nodo referencia una declaración sintética privada cuyo nombre
no puede escribirse en source.

Las declaraciones sintéticas se agregan al módulo en postorden, de modo que
una lambda anidada sin captura obtiene su firma antes que la lambda exterior.
El frontend infiere el resultado con el mismo chequeo usado por `var`, fija la
firma estructural exacta `Function<(P...), R>` y vuelve a analizar el body con
esa firma. Una expresión `void` se conserva como effect statement y recibe
`Function<(P...), void>`.

La expresión source baja directamente a:

- `HirExprKind::FunctionRef` con el `FunctionId` sintético y `TypeId` exactos;
- `Rvalue::FunctionRef` / `Rvalue::IndirectCall` existentes;
- `SsaOp::FunctionRef` / `SsaOp::IndirectCall` existentes;
- el function pointer y prototype LLVM vigentes.

Por ello reachability, monomorfización, unwind y mangling usan el spine de
Function Values V1 sin una representación paralela. La identidad lógica del
símbolo combina package, módulo y el nombre source-stable basado en `LambdaId`.

El body sintético posee únicamente el scope de sus parámetros y los nombres
globales/importados ordinarios. Un uso que dependería de un local o parámetro
exterior falla con `E0359`; no se fabrica un capture ni se reclasifica como
closure. El shadowing por parámetros propios se conserva.

## Qualification dedicada

Se agregó `compiler-next/crates/aether-driver/tests/anonymous_functions_v1.rs`.
La suite ejecuta en O0 y O2:

- lambdas de cero, uno y múltiples parámetros;
- inferencia local mediante `var` y expected `Function`;
- resultados numéricos, booleanos y `void`;
- invocación repetida y paso como argumento;
- llamadas top-level e importadas desde el body;
- shadowing y lambdas anidadas sin captura;
- rechazo de captura exterior, firma incompatible y aridad incorrecta;
- propagación de excepciones por `IndirectCall`;
- presencia de target sintético, `FunctionRef` e `IndirectCall` en HIR/MIR/SSA;
- ausencia de `Closure` y de allocation/runtime específico.

Se agregó además un corruption test HIR que altera de forma independiente el
target ausente, el `TypeId` de Function y la identidad target incompatible. Los
verificadores MIR/SSA existentes vuelven a comprobar target, firma, callee,
resultado y aridad del mismo spine utilizado por las lambdas.

El consumer real se agregó a la qualification de Plots y llama directamente:

```aether
p.plotFunction((float64 x) => x*x, -2.0, 2.0, usize(5), &options)
```

No se modificó el código de Plots, Graphics, SVG ni las bibliotecas numéricas.

## Resultados de gates

Ejecutados el 1 de noviembre de 2026:

- `cargo test -p aether-driver --test anonymous_functions_v1 -j 1`: 5/5.
- consumer `plots.plotFunction` O0/O2: 1/1 dedicado; suite Plots global 8/8.
- Function Values V1: 8/8.
- frontend y corruption HIR: 77/77.
- `CARGO_INCREMENTAL=0 cargo test --workspace -j 1`: PASS completo, incluidos
  parser, imports, genéricos, exceptions, HIR/MIR/SSA, LLVM y doc tests.
- `cargo fmt --all --check`: PASS.
- `git diff --check`: PASS.
- `cargo clippy --workspace --all-targets -j 1`: completa sin errores; conserva
  warnings preexistentes del workspace (`assert_is_empty`,
  `needless_borrows_for_generic_args`, `too_many_lines` y equivalentes). Una
  ejecución estricta con `-D warnings` se detiene en esos warnings
  preexistentes; los warnings introducidos por este vertical fueron corregidos.

Los binarios nativos y dumps dedicados fueron comprobados en O0 y O2. No hubo
diferencias semánticas entre niveles de optimización.

## Archivos del vertical

- `compiler-next/crates/aether-frontend/src/ast.rs`
- `compiler-next/crates/aether-frontend/src/lib.rs`
- `compiler-next/crates/aether-frontend/src/parser.rs`
- `compiler-next/crates/aether-frontend/src/hir.rs`
- `compiler-next/crates/aether-driver/tests/anonymous_functions_v1.rs`
- `compiler-next/crates/aether-driver/tests/plots_function_sampling_v1.rs`
- `compiler-next/tests/modules/anonymous_functions_v1/helper.ae`
- `compiler-next/tests/modules/anonymous_functions_v1/main.ae`
- `docs/architecture/ANONYMOUS_FUNCTIONS_V1_REPORT.md`

