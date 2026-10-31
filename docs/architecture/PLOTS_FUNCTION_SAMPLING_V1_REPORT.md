# PLOTS-FUNCTION-SAMPLING-V1 — reporte de implementación y qualification

Estado: **CLOSED**, 2026-10-31.

Documento normativo:
[PLOTS_FUNCTION_SAMPLING_ARCH_1](PLOTS_FUNCTION_SAMPLING_ARCH_1.md).

## Resultado

El package `plots` expone la API normativa `plotFunction` y las excepciones
nominales `InvalidSampleCountException` e
`InvalidSampleIntervalException`, ambas derivadas de `PlotException`.

La implementación valida count, endpoints y span antes de asignar o evaluar,
construye un `Array<DataPoint>` temporal exacto, evalúa el function value una
vez por índice en orden ascendente y delega exclusivamente en
`line(&points, options)`. No se modificaron compiler, runtime, Core/std,
Graphics, SVG, `line()`, Plots legacy ni ejemplos personales.

## Grid, evaluación y errores

Los endpoints se asignan explícitamente como `a` y `b`. Cada punto interior
usa, sin acumulación, `t = float64(i) / float64(N - 1)` y
`x = a + span * t`, donde `span = b - a` se calcula una sola vez. Cada X se
valida antes de la llamada indirecta. No se deduplican coordenadas repetidas
por redondeo.

La clasificación y el orden observados son:

| Condición | Resultado |
|---|---|
| `N < 2` | `InvalidSampleCountException`, cero evaluaciones |
| endpoint no finito o intervalo no creciente | `InvalidSampleIntervalException`, cero evaluaciones |
| span no representable | `PlotRangeException`, cero evaluaciones |
| X generado no finito | `PlotRangeException` antes de evaluar ese índice |
| función lanza | excepción original y sólo el prefijo de calls |
| todos los Y no finitos | `NoFiniteDataException` después de N calls |
| options inválidas | error vigente de `line()` después de N calls |

NaN e infinities retornados por la función se conservan y `line()` mantiene
su semántica de gaps. La qualification separa un polo exactamente muestreado,
un polo entre muestras y un salto finito; no atribuye detección universal de
discontinuidades al sampler.

## Ownership y composición

`plotFunction` posee el Array temporal y `line()` copia sus puntos al Buffer
owning de la Figure. La suite instrumenta los contadores de heap y confirma
balance tanto en retorno normal como cuando la función hace unwind. La Figure
no retiene callback, Array ni referencias del caller. El consumer muta
`FigureOptions` después de construir la Figure y obtiene SVG idéntico.

No existe ruta geométrica, backend, estado global, caché, evaluación diferida
ni optimización de storage nueva. La equivalencia central construye a mano el
mismo grid y verifica SVG idéntico byte por byte contra `plotFunction`.

## Qualification dedicada

`compiler-next/crates/aether-driver/tests/plots_function_sampling_v1.rs`
contiene siete gates y pasa 7/7:

1. function values top-level locales e importados mediante consumer real;
2. orden de validación, cardinalidad, efectos, throw y options tardías;
3. polinomio, seno, exponencial, logaritmo, constante, N mínimo y N=100001;
4. intervalos negativos/cruzando cero, extremos, span overflow y X repetidos;
5. discontinuidad muestreada, polo no muestreado y salto finito;
6. equivalencia con Array manual, golden SVG completo y O0/O2 byte a byte;
7. cleanup normal/unwind e inspección HIR/MIR/SSA/LLVM.

HIR, MIR y SSA contienen `FunctionRef`, `IndirectCall` y el Array ordinario;
LLVM conserva la call indirecta con unwind. Source e IR no incorporan Python,
NumPy, Matplotlib, registry, intrinsic ni una ruta especial de Graphics.

El consumer versionado está en `plots/tests/function_consumer`; su función
`sin` vive en un módulo importado. El golden matemático completo es
`plots/tests/goldens/function_sine.svg` y el generador reproducible quedó
extendido en `plots/tests/golden_generator`.

## Gates finales

Ejecutados con `.venv` activado, `CARGO_INCREMENTAL=0`,
`TMPDIR=/home/blasm/tmp` y Cargo serial `-j 1`:

| Gate | Resultado |
|---|---|
| package y consumer real `check`; consumer `run -O0/-O2` | PASS |
| qualification dedicada O0/O2 | PASS — 7/7 |
| `plots_2d_line_v1` | PASS — 5/5 |
| `function_values_v1` | PASS — 8/8 |
| golden XML y bytes O0/O2 | PASS |
| `cargo test --workspace -j 1` | PASS completo, incluidos 220/220 verticales y doc-tests |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS con warnings preexistentes |
| `git diff --check` | PASS |

Clippy conserva warnings preexistentes en código ajeno. Los warnings
`needless_raw_string_hashes` inicialmente observados en la qualification nueva
se corrigieron antes del cierre.

No se hizo commit ni push y no se inició otro milestone.

**Estado final: PLOTS-FUNCTION-SAMPLING-V1 CLOSED.**
