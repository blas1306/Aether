# Aether — LLVM Runtime Declaration Consistency V1 — Qualification Report

Fecha: 2026-11-15.

## Estado

**LLVM-RUNTIME-DECLARATION-CONSISTENCY-V1: PARTIAL (implementación corregida;
gate global ajeno pendiente).**

El defecto reproducible de `@aether_io_read_line` fue corregido en el backend
LLVM. El consumer candidato de Plots con Function, Closure y SVG ahora genera
LLVM válido, enlaza y ejecuta en O0/O2. Esta tarea no publica la firma candidata
de `plotFunction`, no cambia Plots y no modifica el estado PARTIAL del reporte
`PLOTS-INVOCABLE-INTEGRATION-V1`.

## Reproducer mínimo y fase exacta

El reproducer estable está en
`compiler-next/crates/aether-driver/tests/plots_invocable_integration_v1.rs`.
Carga la firma genérica candidata sólo en un proyecto temporal, importa
`plots.svg`, materializa una Closure y renderiza la figura.

Antes de la corrección, tanto O0 como O2 producían:

```llvm
define { i32, ptr } @...readLine...() {
  %raw = call { i32, ptr } @aether_io_read_line()
```

sin `define` ni `declare` de `@aether_io_read_line`. Clang rechazaba el `.ll`
con exit 1 y el driver lo presentaba como `E0601`; el build de package terminaba
con exit 2:

```text
error: use of undefined value '@aether_io_read_line'
```

El fallo ocurre al parsear/compilar el módulo LLVM, antes de producir el objeto.
No es un error del linker convencional.

Comando focal usado para confirmar el baseline:

```bash
TMPDIR=/tmp CARGO_INCREMENTAL=0 cargo test -p aether-driver \
  --test plots_invocable_integration_v1 \
  candidate_with_svg_reproduces_missing_io_declaration_o0_o2 -j 1 -- --nocapture
```

El test histórico pasaba porque afirmaba expresamente el diagnóstico O0/O2.
Después de la corrección se convirtió en una regresión positiva que exige link
y ejecución exitosos.

## Matriz de aislamiento

| Caso | Resultado después de la corrección |
|---|---|
| llamada directa a `std.IO.readLine` con Closure presente | wrapper y helper se emiten una sola vez; LLVM enlaza O0/O2 |
| módulos SVG importados sin usar IO | no se emiten `readLine`, `readText` ni `writeText` |
| SVG productivo con Function concreta | suites de sampling/SVG pasan O0/O2 |
| `Invocable` genérico con Function y SVG | link, render y ejecución pasan O0/O2 |
| `Invocable` genérico con Closure y SVG | link, render y ejecución pasan O0/O2 |
| Closure `Invocable` sin SVG | ejecución y ownership pasan O0/O2 |
| Graphics/SVG sin `plotFunction` | suites Graphics/SVG pasan; sólo conservan cuerpos alcanzables |

En el caso sin uso de IO no queda ninguna call a los helpers ni declaración o
definición innecesaria. En el caso alcanzable de `readLine`, el LLVM contiene
exactamente una call desde el wrapper y exactamente una definición privada del
helper. Clang valida ambos módulos en O0/O2.

## Causa raíz demostrada

Había dos criterios incompatibles dentro de `emit_llvm`:

1. La selección de runtime IO calculaba `reachable_io` desde el grafo cerrado
   de llamadas directas.
2. La emisión de funciones desactivaba todo dead stripping cuando existía al
   menos un layout de Closure (`closure_layouts.is_empty()`).

Por ello, cualquier Closure hacía emitir funciones importadas inalcanzables.
`graphics.svg` importa `std.File` y `std.IO`; eso incorporaba el wrapper fuente
de `std.IO.readLine`, aunque el programa nunca lo llamaba. El wrapper emitía la
call a `@aether_io_read_line`, pero la selección canónica del runtime no emitía
el helper porque `readLine` no era alcanzable.

Al activar el filtro estricto apareció la segunda parte del defecto: los
targets de Closure se invocan mediante thunks y no tienen un `SsaOp::Call`
ordinario desde `main`. El grafo tampoco recorría las calls realizadas dentro
de esos targets. El reproducer de unwind lo demostró con `failAtZero`.

El primer punto inconsistente era, por tanto, la construcción/consumo del grafo
de reachability del backend, no la firma ABI de IO, imports, monomorfización ni
el runtime POSIX.

## Corrección implementada

- `classes::reachable_functions` trata cada target de un environment Closure
  materializado como raíz indirecta y sigue transitivamente sus calls.
- La emisión de cuerpos aplica siempre el mismo filtro de reachability, incluso
  cuando existen closures.
- Los targets indirectos siguen admitidos explícitamente; no se cambió su ABI,
  thunk, ownership ni mangling.
- La selección de helpers IO permanece en su mecanismo canónico. No se añadió
  un segundo registro de símbolos ni declaraciones reparadoras posteriores.

El invariante resultante es que un wrapper runtime sólo puede emitirse si está
en el mismo cierre que habilita su helper. Las dependencias reales dentro de
closures forman parte de ese cierre. Esto corrige por la misma vía `readLine`,
`readText`, `writeText`, `writeTextAtomic` y `eprint/eprintln`; no se insertan
helpers no usados.

## Regresiones agregadas

El test de integración ahora comprueba:

- Function y Closure genéricas con SVG en O0/O2;
- ausencia completa de helpers IO inalcanzables;
- link y ejecución, no sólo búsqueda de texto diagnóstico;
- `readLine` realmente alcanzable junto a una Closure, con una definición y
  una call exactas y link válido O0/O2;
- llamadas transitivas desde un target Closure mediante el caso de unwind ya
  existente.

Clang continúa siendo el verificador final del módulo generado. No se agregó un
scanner textual general de símbolos: sería un segundo parser LLVM incompleto y
no resolvería la causa. La regresión positiva más el grafo único prueban el
contrato en la capa propietaria.

## Qualification

Entorno: `TMPDIR=/tmp`, `CARGO_INCREMENTAL=0`, Cargo serial `-j 1`.

Suites focales ejecutadas con exit 0:

- `plots_invocable_integration_v1`: 6 passed;
- `plots_function_sampling_v1`: 8 passed;
- `plots_2d_line_v1`: 5 passed;
- `graphics_foundation_v1`: 8 passed;
- `graphics_svg_backend_v1`: 11 passed;
- `io_v1`: 12 passed;
- `invocable_capability_m4`: 7 passed;
- `borrowed_invocable_param_m3`: 6 passed;
- `generic_inference_ref_argument_v1`: 5 passed.

Gates globales:

| Comando | Exit | Resultado |
|---|---:|---|
| `cargo check --workspace` | 0 | PASS |
| `cargo test --workspace -j 1` | 0 | PASS completo, incluidos doc-tests |
| `cargo fmt --all --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets -j 1` | 0 | PASS; sólo warnings preexistentes |
| `git diff --check` desde la raíz | 2 | falla sólo por whitespace preexistente en `examples/svd.ae:62` |
| `git diff --check` acotado a los archivos de esta tarea | 0 | PASS |

El consumer real largo
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó normalmente en
1028.64 s y pasó O0/O2. No se canceló ni se clasificó antes de completar.

## Archivos modificados

- `compiler-next/crates/aether-backend-llvm/src/classes.rs`;
- `compiler-next/crates/aether-backend-llvm/src/lib.rs`;
- `compiler-next/crates/aether-driver/tests/plots_invocable_integration_v1.rs`;
- `docs/architecture/LLVM_RUNTIME_DECLARATION_CONSISTENCY_V1_REPORT.md`.

Se preservó el cambio ajeno en `examples/svd.ae`. No se modificaron runtime,
ABI público, Plots, Graphics/SVG ni ejemplos. No se hizo commit ni push.

## Limitaciones

Esta qualification cierra el defecto del backend. No publica la migración de
Plots y no reemplaza su qualification productiva. El fixture de Plots continúa
probando la firma candidata temporalmente hasta que esa tarea se reabra.

La clasificación formal permanece PARTIAL porque el gate literal
`git diff --check` no retorna 0 sobre todo el worktree. La única incidencia es
el whitespace del cambio personal preexistente en `examples/svd.ae`, que esta
tarea debía preservar. No hay whitespace defectuoso en los archivos creados o
modificados por esta corrección.

