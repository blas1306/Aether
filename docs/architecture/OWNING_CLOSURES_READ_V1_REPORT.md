# Aether — OWNING-CLOSURES-READ-V1 — ABI Scope Review Report

## Actualización CLOSURE-OWNERSHIP-IR-V1 — CLOSED (2 de noviembre de 2026)

El subvertical de ownership IR quedó implementado y calificado. Las closures
capturantes llegan ahora a `VerifiedSsa` mediante operaciones explícitas
`ClosureCreate`, `ClosureAlias`, `ClosureBorrow`, `ClosureCall` y
`EndClosureBorrow`, conservando environment, firma, `BindingId`, tipo, modo,
orden, recipes, owner transfers y edges normal/unwind. HIR, MIR y SSA poseen
verificadores independientes y corruption tests propios.

`E0376` se trasladó a la frontera posterior a `VerifiedSsa`: el backend sigue
fail-closed y no emite boxes, payloads, thunks ni calls parciales. Ver
`CLOSURE_OWNERSHIP_IR_V1_REPORT.md` para contratos y qualification.

Evidencia focal: `owning_closures_read_v1` 21/21,
`anonymous_functions_v1` 5/5, `function_values_v1` 8/8, frontend 78/78 y
middle 29/29 PASS. El workspace serial completo finalizó PASS con código 0,
incluida la prueba larga de registry (5/5, 951,74 s) y todos los doc-tests. Fmt
y `git diff --check` finalizaron PASS, y Clippy terminó con código 0 y warnings
preexistentes.

`OWNING-CLOSURES-READ-V1` permanece **PARTIAL**: faltan allocation/publicación
LLVM de `ClosureBox`, layout productivo, invoke/destroy thunks, codegen de
`ClosureCall` y ejecución real O0/O2 de closures capturantes.

## Actualización CLOSURE-CAPTURE-ANALYSIS-V1 — CLOSED (2 de noviembre de 2026)

El subvertical semántico dedicado quedó implementado y calificado. La fase de
declaraciones conserva ahora el scope creador, resuelve variables libres por
identidad estable, clasifica Copy/Alias/Move, valida cláusulas parciales y
publica metadata tipada `ClosureEnvironmentInfo`. Incluye shadowing, bindings
homónimos, lambdas anidadas, capturas transitivas, orden canónico y warning
estructurado para capturas explícitas no usadas.

Los reproducers ya no fallan con `E0359`: ambos alcanzan `E0376`, la frontera
explícita que indica que el análisis de Closure tuvo éxito pero su lowering
productivo todavía no existe. Las lambdas sin captura conservan la ruta
`FunctionRef` original.

Evidencia focal: `owning_closures_read_v1` 13/13,
`anonymous_functions_v1` 5/5 y `function_values_v1` 8/8 PASS. Ver
`CLOSURE_CAPTURE_ANALYSIS_V1_REPORT.md` para metadata, política y qualification.
El workspace serial completo, fmt, Clippy (código 0 con warnings preexistentes)
y `git diff --check` también finalizaron correctamente.

`OWNING-CLOSURES-READ-V1` permanece **PARTIAL**: siguen pendientes
`ClosureCreate/ClosureAlias/ClosureCall`, lowering HIR/MIR/SSA, boxes/thunks,
runtime productivo, ownership/unwind y qualification O0/O2 de closures reales.

## Actualización de implementación — PARTIAL (1–2 de noviembre de 2026)

La implementación fue retomada bajo la autoridad de
`FIRST_CLASS_CLOSURES_ARCH_1_ABI_SCOPE_AMENDMENT.md`. El bloqueo de ABI entre
compilaciones independientes permanece retirado y no fue reclasificado como
bloqueo.

Estado actual: **PARTIAL; FRONTEND FOUNDATION IMPLEMENTED; PRODUCTIVE CLOSURE
VERTICAL NOT YET QUALIFIED**.

Se implementó y verificó:

- `TypeData::Closure` canónico, distinto de `Function`, con firma estructural;
- propiedades no-Copy, relocatable, storable y needs-Drop;
- layout de carrier owning de un pointer en el target vigente;
- parsing de `Closure<(P...), R>` sin conversión a `Function`;
- parsing y conservación source de `capture(copy x, alias y, move z)`;
- cláusula opcional/parcial y rechazo fail-closed de modo inválido, trailing
  entry y captura explícita duplicada;
- sustitución generic, formatting, mangling y clasificación física de
  `Closure` separadas de `Function`;
- helpers non-atomic `aether_closure_retain_v1` y
  `aether_closure_release_v1`, con overflow/underflow fail-closed, carga del
  destroy thunk en `2W` y wiring conservador de Drop (todavía no alcanzables
  desde un productor porque `ClosureCreate` no está implementado).

Evidencia ejecutada:

- `cargo test -p aether-driver --test owning_closures_read_v1`: **4/4 PASS**;
- `cargo test -p aether-driver --test anonymous_functions_v1`: **5/5 PASS**;
- `cargo test -p aether-driver --test function_values_v1`: **8/8 PASS**;
- `CARGO_INCREMENTAL=0 cargo test --workspace -j 1`: todos los grupos
  observados finalizaron PASS; la sesión de herramienta se perdió después de
  iniciar el último test largo de registry, que se reejecutó aisladamente;
- `cargo test -p aether-registry --test registry
  linear_algebra_oal_publishes_and_runs_real_qr_consumer`: **1/1 PASS** en
  O0/O2 (1047.50 s);
- `cargo clippy --workspace --all-targets -j 1`: **código 0**, con warnings
  preexistentes; los warnings nuevos atribuibles fueron corregidos;
- `cargo fmt --all --check`: **PASS**;
- `git diff --check`: **PASS**.

En esa actualización previa, los dos reproducers todavía fallaban con `E0359`
porque la declaración sintética se analizaba fuera del scope creador. Ese
resultado histórico fue sustituido por la actualización
`CLOSURE-CAPTURE-ANALYSIS-V1` al comienzo de este documento.

No están implementados ni se declaran PASS:

- lowering productivo a partir del análisis de variables libres ya implementado;
- `ClosureCreate`, `ClosureAlias`, `ClosureCall` y metadata de captures en
  HIR/MIR/SSA;
- boxes, payload, invoke/destroy thunks, publicación y rollback;
- integración de helpers ARC con productores, contadores de qualification,
  replacement, return y keepalive;
- cleanup normal/unwind y conservación de `ExceptionEvent` para closures;
- qualification funcional O0/O2, módulos/packages fuente y corruption tests;
- qualification productiva del runtime Closure; el runtime general sí pasó su
  regresión de workspace y Clippy.

En consecuencia los gates esenciales del vertical siguen abiertos. Esta
actualización no sustituye el historial de revisión y desbloqueo conservado a
continuación, ni presenta interoperabilidad source como interoperabilidad
binaria.

Archivos modificados en esta actualización:

- `compiler-next/crates/aether-frontend/src/ast.rs`;
- `compiler-next/crates/aether-frontend/src/lib.rs`;
- `compiler-next/crates/aether-frontend/src/parser.rs`;
- `compiler-next/crates/aether-frontend/src/types.rs`;
- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-backend-llvm/src/lib.rs`;
- `compiler-next/crates/aether-driver/tests/owning_closures_read_v1.rs`;
- `reproducers/owning_closures_read_v1/README.md`;
- `docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`.

## Estado histórico previo a esta actualización

`ABI SCOPE REVIEW COMPLETE; PREVIOUS BLOCKER REMOVED; IMPLEMENTATION NOT
STARTED; NOT QUALIFIED` (1 de noviembre de 2026).

Documento normativo de la revisión:
[FIRST-CLASS-CLOSURES-ARCH-1 — ABI Scope Amendment](FIRST_CLASS_CLOSURES_ARCH_1_ABI_SCOPE_AMENDMENT.md).

No se modificaron producción, runtime ni los contratos cerrados de `Function`.
No se implementaron closures ni compilación separada.

## Resultado ejecutivo

El bloqueo anterior no era una dependencia técnica de
`OWNING-CLOSURES-READ-V1`. Confundía:

1. corrección del ABI interno de Closure en un programa compilado
   conjuntamente;
2. compatibilidad binaria entre compilaciones independientes;
3. distribución/versionado de libraries Aether precompiladas.

La infraestructura actual sólo implementa el primer dominio. Una
`CompilationSession` descubre todas las fuentes transitivas, incluidas las de
packages fuente; el driver construye un único HIR/MIR/SSA verificado, selecciona
un único target y llama una vez al backend para emitir un único módulo LLVM.
No existe una ruta que importe un box Closure producido por otra compilación.

Por tanto, `ClosureABI-v1` puede implementarse y calificarse íntegramente en el
modelo vigente sin introducir primero artefactos binarios Aether. La metadata
target/data-layout/epoch y el rechazo productor/consumidor independientes se
difieren a `COMPILED-ARTIFACT-ABI`.

Esto deja el vertical arquitectónicamente desbloqueado, pero no lo declara
implementado, PASS ni CLOSED.

## Evidencia del modelo de compilación

- `CompilationSession::discover` lee y parsea la entrada y todos sus imports
  transitivos.
- Con un project plan, el catálogo agrega las fuentes materializadas de cada
  package resuelto; no consume interfaces u objetos Aether precompilados.
- El driver reúne los módulos en un programa, analiza firmas/bodies para un
  único `TargetDescriptor`, baja a MIR y construye/verifica un único SSA.
- `LlvmTextBackend.emit(&ssa, &target)` recibe ese programa completo y produce
  un único string de módulo LLVM.
- El target bootstrap actual es único y explícito. El backend identifica su ABI
  y mangling como internos, no como ABI pública de libraries.
- `PackageMetadata` contiene nombre, versión y compatibilidad opcional de
  lenguaje; no hay metadata binaria de Closure ABI, layout o compiler epoch.
- No hay loader/importer de interfaces/objetos Aether ni una etapa donde puedan
  mezclarse dos representaciones de Closure compiladas independientemente.

Los mismos hechos que impiden calificar compilación separada demuestran que no
existe esa frontera en el alcance V1: productor y consumidor son generados por
la misma instancia del pipeline.

## Dependencia real de `ClosureABI-v1`

### Header y payload

El header normativo permanece en offsets `0`, `W` y `2W`; layout y alignment se
calculan una vez con el target de la sesión. Código consumidor en cualquier
función, módulo fuente o package fuente carga sólo el header común. El payload
privado se conoce exclusivamente en invoke/destroy thunks del productor.

No hace falta metadata persistida para impedir que un consumidor interno
interprete otro layout: HIR/MIR/SSA deben conservar un tipo `Closure` distinto
de `Function`, el backend usa un contrato único y no existe un artefacto externo
que aporte otra representación.

### Identidad y reachability

Package, module, `LambdaId`, generic instance y versión ABI bastan para formar
una identidad compiler-internal determinista dentro del programa. El mangling
debe evitar colisiones y reflejar firma/captures. Invoke thunk, destroy thunk y
body sintético deben quedar alcanzables cuando sus direcciones se almacenan en
un box, incluso si no existe otra referencia directa.

Estabilidad pública del símbolo, COMDAT entre objetos independientes y
compatibilidad de mangling entre versiones de compiler no son observables en
el modelo actual y quedan diferidas.

### ARC, llamadas, paso y retorno

Los helpers `aether_closure_retain_v1` y `aether_closure_release_v1` continúan
siendo obligatorios y versionados. V1 debe hacerlos accesibles coherentemente
desde todo el módulo emitido. La llamada carga `invoke_thunk`, deriva el
prototype de la firma Closure verificada y pasa el box como argumento oculto.

Paso y retorno entre módulos/packages fuente no cruzan una frontera binaria:
el carrier conserva su box y pointers a thunks presentes en el módulo LLVM
final. Sí requieren qualification real de Alias/Transfer/Move/Drop, keepalive,
reachability y cleanup normal/unwind.

### Exceptions y verificación

No se relaja ningún gate. HIR, MIR y SSA deben reconstruir y verificar de forma
independiente capture set/order/mode/source, identidad, recipes, owner tokens,
borrow/`EndBorrow`, firma de call y edges normal/unwind. `ExceptionEvent` debe
conservar identidad y el destroy thunk debe ser `nounwind`. O0/O2 deben observar
el mismo lifecycle y resultado.

## Qualification revisada

| Capacidad | Milestone | Estado actual |
|---|---|---|
| closures locales y cross-function | `OWNING-CLOSURES-READ-V1` | NOT IMPLEMENTED |
| paso/retorno entre módulos fuente | `OWNING-CLOSURES-READ-V1` | NOT IMPLEMENTED |
| imports de packages fuente en una sesión | `OWNING-CLOSURES-READ-V1` | NOT IMPLEMENTED |
| header/layout/thunks/helpers internos | `OWNING-CLOSURES-READ-V1` | NOT IMPLEMENTED |
| ownership, unwind y HIR/MIR/SSA | `OWNING-CLOSURES-READ-V1` | NOT IMPLEMENTED |
| paridad O0/O2 y ausencia de UAF/leaks | `OWNING-CLOSURES-READ-V1` | NOT RUN |
| productor/consumidor compilados separados | `COMPILED-ARTIFACT-ABI` | OUT OF SCOPE |
| metadata target/layout/epoch persistida | `COMPILED-ARTIFACT-ABI` | OUT OF SCOPE |
| rechazo fail-closed antes de link/load | `COMPILED-ARTIFACT-ABI` | OUT OF SCOPE |
| libraries Aether precompiladas | `COMPILED-ARTIFACT-ABI` | OUT OF SCOPE |

Un test con dos módulos o packages fuente sólo puede acreditar las primeras
filas. No puede registrarse como PASS de interoperabilidad de artefactos.

## Gates diferidos y justificación

Se difieren exclusivamente:

- formato compiler-owned de interface/object metadata;
- importación y enlace de artefactos Aether independientes;
- target triple y data-layout fingerprint persistidos;
- Aether/Closure ABI version y compiler ABI epoch persistidos;
- reglas públicas de mangling, linkage, visibility y symbol export;
- rechazo pre-link/load de productor/consumidor incompatibles;
- qualification entre versiones de compiler y distribución de libraries.

Todos dependen de una frontera de artefactos que Aether todavía no posee. No
protegen ninguna ruta adicional del programa compilado conjuntamente y, por
eso, no son condición técnica para el ABI interno.

## Trabajo real restante registrado por la revisión histórica

La lista siguiente describe el corte anterior y se conserva como trazabilidad;
la actualización al comienzo del documento sustituye sus afirmaciones sobre
parser, tipos y resolución de capturas.

Los reproducers existentes siguen siendo evidencia útil del estado source:

- `automatic_copy_capture.ae` falla con `E0359` porque la declaración sintética
  capture-free no dispone del scope exterior para analizar variables libres;
- `explicit_capture_clause.ae` falla en parsing porque la gramática exige `=>`
  inmediatamente después de parámetros.

Además faltan `TypeData::Closure`, operaciones y verificadores HIR/MIR/SSA,
ownership ledgers, ARC helpers, boxes/thunks, reachability, lowering LLVM,
cleanup normal/unwind y todas las pruebas funcionales/corrupción/O0/O2. Son
trabajo propio del vertical, no un prerrequisito general oculto.

## Baseline histórico preservado

El preflight que originó este reporte ejecutó, antes de esta enmienda,
`anonymous_functions_v1` (5/5), `function_values_v1` (8/8),
`CARGO_INCREMENTAL=0 cargo test --workspace -j 1` y `cargo fmt --all --check`
con resultado PASS. `cargo clippy --workspace --all-targets -j 1` terminó con
código cero y warnings preexistentes. Esos resultados son baseline histórico,
no qualification de closures y no se presentan como rerun de esta revisión
documental.

## Alcance de esta revisión

Se agregó la enmienda ABI y se actualizaron la arquitectura, su reporte y este
reporte. No se modificaron compiler, runtime, tests, packages, Plots, Graphics,
métodos numéricos, reproducers ni ejemplos personales. No se inició
`OWNING-CLOSURES-READ-V1`, no se creó metadata paralela y no se hizo commit ni
push.

Clasificación final: **ARCHITECTURALLY UNBLOCKED; IMPLEMENTATION NOT STARTED;
NOT QUALIFIED**.
