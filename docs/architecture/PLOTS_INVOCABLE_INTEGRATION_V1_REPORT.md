# Aether — PLOTS-INVOCABLE-INTEGRATION-V1 — Qualification Report

Fecha: 2026-11-15.

## Estado

**PLOTS-INVOCABLE-INTEGRATION-V1: PARTIAL.**

La integración no se publicó en `plots/src/lib.ae`. La firma candidata supera
frontend, especialización, MIR, SSA y ejecución nativa O0/O2 con Function y
Closure cuando se carga el módulo `plots` aislado, pero el consumer productivo
que también carga `plots.svg` produce LLVM inválido para la instancia Closure.
Corregir ese defecto requiere una modificación transversal del backend o de la
selección de runtime helpers, fuera del scope autorizado.

La API productiva anterior se restauró byte por byte para no dejar una
regresión parcial. No se modificaron compiler, runtime, Graphics, SVG,
`examples/svd.ae` ni otras bibliotecas numéricas.

## Preflight

El worktree inicial contenía un único cambio ajeno en `examples/svd.ae`; se
preservó. Se inspeccionaron los reportes CLOSED de
`INVOCABLE-CAPABILITY-V1`, `BORROWED-INVOCABLE-PARAM-V1`, el contrato CLOSED de
sampling, `plots/src/lib.ae`, consumers, goldens y resolución generic entre
módulos.

Los únicos usos productivos/versionados de `plotFunction` eran calls en:

- `plots/tests/function_consumer`;
- `plots/tests/golden_generator`;
- qualification de `PLOTS-FUNCTION-SAMPLING-V1`.

No se encontró ningún uso de `plotFunction` como valor `Function`.

## Firma anterior y candidata

La firma productiva permanece:

```aether
public Figure2D plotFunction(
    Function<(float64), float64> target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options)
```

La candidata evaluada fue exactamente:

```aether
public Figure2D plotFunction<C: Invocable<(float64), float64>>(
    ref C target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options)
```

No se cambió el cuerpo. El loop, grid, validaciones, non-finite handling,
`FigureOptions`, excepciones y delegación final a `line(&points, options)` son
la misma fuente.

## Estrategia de compatibilidad

La sustitución directa es la única alternativa pequeña que conserva las calls
Function existentes y habilita Closure sin duplicar el algoritmo. La
inferencia de `ref C` funciona desde otro módulo fuente y genera instancias
concretas Function/Closure.

Preservar simultáneamente la entrada concreta y agregar la genérica con el
mismo nombre no es viable: un Function lvalue satisface ambos candidatos y el
resolver emite `E0461 ambiguous overload`. El reproducer está automatizado en
`plots_invocable_integration_v1.rs`. No se agregó ni modificó overload
resolution.

La sustitución directa cambia la identidad/mangling de la declaración y deja
de ofrecer una función concreta susceptible de address-taking sin
especialización. No hay consumer actual que tome ese valor. Calls source
Function existentes sí compilan y ejecutan con la candidata.

## Resultado funcional sin SVG

El test dedicado sustituye la firma sólo dentro de un proyecto temporal; la
fuente productiva permanece intacta. Con `plots` sin los submódulos SVG, O0 y
O2 pasan para:

- Function lvalue/top-level;
- Closure capturante lvalue;
- sampling repetido dentro del loop;
- reutilización del owner después de `plotFunction`;
- throw durante sampling, catch exterior, cleanup y reutilización posterior;
- rechazo de aridad, parámetros y resultado incompatibles.

HIR se especializa, MIR contiene `ClosureCall` y `EndClosureBorrow`, y
MIR/SSA/LLVM no conservan `CapabilityInvoke`, `BorrowedCapabilityInvoke` ni
símbolo de adapter.

## Ownership y coste

Para una Closure lvalue capturante, los contadores al terminar `main` son los
mismos en O0 y O2:

| Retain | Release | Destroy |
|---:|---:|---:|
| 0 | 1 | 1 |

El release/destroy corresponde al owner original. La frontera borrowed agrega
cero retain/release y no crea un owner adaptador. El LLVM no contiene thunk de
adaptación. El owner se invoca correctamente después del sampling normal y
después de unwind capturado.

La matriz CLOSED de Borrowed Invocable, reejecutada en esta qualification,
cubre además Function fresh/lambda sin captura, Closure fresh y captures
Copy/Alias/Move, temporaries, FF/FC/CF/CC, imports, forwarding y ausencia de
allocation de adaptación. El fixture dedicado
`plots/tests/invocable_consumer` materializa Function, top-level, lambda y
Closure lvalue/fresh con Copy/Alias/Move para el consumer productivo.

## Bloqueo productivo SVG

Al agregar `plots.svg` y `graphics.svg`, el frontend y middle-end aceptan la
instancia Closure y generan el cuerpo especializado correcto. Sin embargo, el
LLVM contiene:

```llvm
%raw = call { i32, ptr } @aether_io_read_line()
```

sin contener su declaración correspondiente:

```llvm
declare { i32, ptr } @aether_io_read_line()
```

`ClangToolchain::link_executable` falla en O0 y O2 con:

```text
error[E0601] (toolchain): clang rejected generated LLVM
error: use of undefined value '@aether_io_read_line'
```

El mismo fallo se reprodujo con el build real del package
`plots/tests/invocable_consumer` cuando la firma productiva se cambió
temporalmente a la candidata. `aether check .` finalizó correctamente y
`aether build . -O0` falló en link con `E0601`. El test dedicado conserva un
reproducer autocontenido O0/O2 sin modificar producción.

La ruta Function vigente y el golden SVG existente no presentan este fallo.
No se calificó un SVG Closure: no se consideró suficiente generar un archivo
ni se ocultó el fallo de link. El golden Function permanece XML válido,
determinista y byte-identical O0/O2 mediante la suite original.

## Sampling y contratos observables

La suite `plots_function_sampling_v1` pasó 8/8 tras restaurar la firma
productiva. Verifica cardinalidad, orden de validaciones, grid, familias
matemáticas, valores no finitos, excepciones, cleanup, equivalencia con Array
manual y golden SVG byte por byte O0/O2. Por tanto esta investigación no
introduce cambios observables en Plots.

La candidata sin SVG ejecuta el mismo cuerpo y produce Figures válidas, pero no
se eleva esa evidencia a qualification productiva completa porque el consumer
con SVG no enlaza.

## Qualification ejecutada

Entorno focal: `CARGO_INCREMENTAL=0`, `TMPDIR=/tmp`, Cargo serial `-j 1`.

| Comando/gate | Exit | Resultado |
|---|---:|---|
| `cargo test -p aether-driver --test borrowed_invocable_param_m3 -j 1` | 0 | 6 passed |
| `cargo test -p aether-driver --test plots_function_sampling_v1 -j 1` | 0 | 8 passed |
| `cargo test -p aether-driver --test plots_invocable_integration_v1 -j 1` | 0 | 5 passed; incluye reproducer esperado O0/O2 |
| consumer candidato core sin SVG O0/O2 | 0 | Function + Closure PASS |
| consumer candidato con SVG O0/O2 | N/A | LLVM generado; link falla `E0601` como reproduce el test |
| `aether check .` sobre fixture con firma candidata | 0 | PASS |
| `aether build . -O0` sobre fixture con firma candidata | 2 | `@aether_io_read_line` indefinido |
| consumer Function productivo `aether run . -O0/-O2` | 0/0 | PASS |
| `cargo fmt --all --check` | 0 | PASS |
| Clippy focal, warnings permitidos | 0 | PASS; sólo categorías preexistentes |
| Clippy focal con `-D warnings` | 101 | falla por 11 warnings preexistentes de `aether-frontend` |

No se ejecutó `cargo test --workspace`: la instrucción lo condiciona a que la
migración productiva esté completa, y el gate SVG la deja PARTIAL. No se
inició ni canceló el test de registry. Se ejecutaron los gates no globales
`cargo fmt --all --check`, Clippy focal y `git diff --check`.

## Archivos de esta investigación

- `compiler-next/crates/aether-driver/tests/plots_invocable_integration_v1.rs`:
  candidate qualification y reproducer estable;
- `plots/tests/invocable_consumer/aether.toml`;
- `plots/tests/invocable_consumer/aether.lock`;
- `plots/tests/invocable_consumer/src/main.ae`;
- `plots/tests/invocable_consumer/src/functions.ae`;
- `docs/architecture/PLOTS_INVOCABLE_INTEGRATION_V1_REPORT.md`.

`plots/src/lib.ae` no tiene diff final. No se hizo commit ni push.

## Regresiones y limitaciones

No hay regresión productiva porque la firma y el cuerpo vigentes no cambiaron.
El objetivo Closure permanece sin publicar. Quedan sin qualification
productiva, y por ello impiden CLOSED:

- build/link O0/O2 del consumer Closure con el package completo;
- SVG Closure estructural y byte-equivalent;
- exports/mangling finales de la API genérica productiva;
- consumers existentes y nuevos reunidos bajo la misma firma publicada.

Resolver `@aether_io_read_line` exige investigar bootstrap/runtime declaration
selection o reachability del backend. Eso es un cambio transversal y no se
implementó unilateralmente. Tampoco se agregaron Callable owning, CallableRef,
capabilities, ABI, runtime helpers, generic lambdas ni migraciones adicionales.

**Clasificación final: PLOTS-INVOCABLE-INTEGRATION-V1 PARTIAL.**
