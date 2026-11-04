# Aether — OWNING-CLOSURES-READ-V1 — ABI Scope Review Report

## Qualification final — CLOSED (3 de noviembre de 2026)

La auditoría completa de `testDotConsumer()` confirmó que el único gate
restante era la expectativa `32.0` para
`dot(Array{1,2,3}, List{1,2,3})`. El cálculo independiente es
`1*1 + 2*2 + 3*3 = 14`; se corrigió únicamente esa constante a `14.0`. Las
expectativas corregidas previamente para `listA{7,8,9}` con
`arrayB/columnB{4,5,6}` permanecen en `122.0`, resultado de
`7*4 + 8*5 + 9*6`. No se modificó la implementación de `dot`, sus overloads,
la indexación, QR, APIs públicas ni contratos de Closure/Function/ABI.

La auditoría cubrió los diez casos de la función: 32, 50, 14, 122, 32, 32,
14, 32, 122 y 32, respectivamente. Todos usan dimensión 3; Array/List son
0-based, Vector es 1-based y los overloads mixtos adaptan con `i + 1`. Cada
overload valida igualdad dimensional mediante `shapeGuard`. No hay expectativas
de error o excepción dentro de `testDotConsumer()` y ninguna entrada es
incompatible. La tabla detallada de operandos y cálculos se conserva en
`CLOSURE_LLVM_RUNTIME_V1_REPORT.md`.

Qualification progresiva:

- consumer real O0: código 0;
- consumer real O2: código 0;
- ambos recorrieron QR y los tests posteriores, demostrado por su salida
  `Q`/`R`, Cholesky, SVD y eigen;
- registry aislado: código 0, 1/1, O0/O2, 1083,20 s;
- workspace serial: código 0, registry 5/5 en 1094,48 s, doc-tests completos;
- `cargo fmt --all --check`: código 0;
- `cargo clippy --workspace --all-targets -j 1`: código 0 con warnings
  preexistentes;
- `git diff --check`: código 0.

El intento inicial con `$HOME/tmp` terminó antes del consumer con código 1 y
`E0700` porque el sandbox presentó ese directorio como read-only. La
qualification válida se repitió con el directorio escribible dedicado
`/tmp/aether-linear-algebra-qualification`; no se clasifica el incidente como
fallo del producto.

La qualification focal de Closure, separada del workspace global, quedó:

- `owning_closures_read_v1`: 25/25 PASS, incluidos O0/O2, corrupción
  HIR/MIR/SSA, cross-source-module, lifecycle, ARC/alloc/free y ASan;
- `anonymous_functions_v1`: 5/5 PASS;
- `function_values_v1`: 8/8 PASS;
- Exceptions V1–V4: 6/6, 8/8, 8/8 y 7/7 PASS.

Con la implementación productiva, la qualification focal y el gate completo
del workspace en verde, **OWNING-CLOSURES-READ-V1 queda CLOSED** y
**CLOSURE-LLVM-RUNTIME-V1 queda CLOSED**. Las secciones PARTIAL siguientes se
mantienen como historial de las expectativas incorrectas, el exit 88 y su
aislamiento. No se inició otro milestone.

Archivos modificados para el cierre:

- `linearAlgebra/tests/consumer/src/main.ae`;
- `docs/architecture/CLOSURE_LLVM_RUNTIME_V1_REPORT.md`;
- `docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`.

El reproducer histórico `linear_algebra_dot_exit_88` permanece intacto.

## Qualification final tras el fix acotado — PARTIAL (3 de noviembre de 2026)

Se corrigieron exclusivamente las dos expectativas autorizadas del consumer
de `linearAlgebra`: `54.0 -> 122.0` para `dot(listA,arrayB)` y
`74.0 -> 122.0` para `dot(listA,columnB)`. Los operandos son, en el mismo
orden, `{7,8,9}` y `{4,5,6}`; la diferencia entre los dos casos es sólo la
representación `Array` 0-based / `Vector<Column>` 1-based. No se cambió el
algoritmo, la indexación, los overloads ni ningún otro test.

El consumer real siguió terminando 88, sin stdout, en O0 y O2. La revisión
encontró una tercera condición anterior a ambas correcciones:
`dot(Array{1,2,3}, List{1,2,3}) != 32.0`. El resultado correcto es 14. Esta
aserción no se modificó porque el alcance ordenaba corregir exclusivamente las
expectativas 54 y 74. El registry aislado terminó con código 101, 0/1, al
observar O0 `Some(88)` después de 398,47 s; no alcanzó O2.

La qualification focal terminó con código 0:

- `owning_closures_read_v1`: 25/25 PASS, incluidos O0/O2, corrupción
  HIR/MIR/SSA, cross-source-module, lifecycle, ARC/alloc/free y ASan;
- `anonymous_functions_v1`: 5/5 PASS;
- `function_values_v1`: 8/8 PASS;
- Exceptions V1–V4: 6/6, 8/8, 8/8 y 7/7 PASS.

El workspace serial completo terminó con código 101. Todos los grupos previos
pasaron, incluidos `vertical` 220/220, frontend 78/78 y middle 29/29; registry
quedó 4/5 cuando el consumer salió O0 `Some(88)` después de 408,34 s. Cargo no
alcanzó doc-tests. `cargo fmt --all --check`,
`cargo clippy --workspace --all-targets -j 1` y `git diff --check` terminaron
con código 0; Clippy conservó warnings preexistentes.

El diagnóstico histórico de exit 88 se conserva y sigue clasificado como
defecto del consumer, no como regresión de Closure Runtime. Las dos
expectativas documentadas quedaron resueltas, pero apareció este gate
adicional fuera del fix autorizado. Por tanto **CLOSURE-LLVM-RUNTIME-V1** y
**OWNING-CLOSURES-READ-V1** permanecen **PARTIAL**; no corresponde declarar
CLOSED ni iniciar otro milestone.

## Aislamiento final y qualification — PARTIAL (3 de noviembre de 2026)

La investigación final descartó una regresión de Closure LLVM Runtime para el
fallo concreto del workspace, pero no habilita CLOSED porque el workspace
actual sigue rojo.

El consumer de `linearAlgebra` retorna `600` si `testDotConsumer()` falla;
POSIX lo expone como `88`. La primera condición fallida calcula
`dot(List{7,8,9}, Array{4,5,6})`, espera `54` y observa el resultado correcto
`122`. Una condición posterior con el mismo vector espera `74` y también
debería esperar `122`. Longitudes, indexación List/Array 0-based, adaptación a
Vector 1-based, tipos, acumulador y ownership `ref` son correctos. El defecto
está en las dos constantes esperadas del consumer; no se modificaron.

Se añadió el reproducer mínimo
`reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88`, que imprime
`122` y conserva el retorno `600`; sale 88 en O0 y O2.

La comparación usó fuentes byte-idénticas contra:

- actual: `b7a2c4df64f04531a1bb5afa0382b3485b170fac`;
- baseline anterior al runtime productivo: `93a437e2`.

Los dos compiladores terminaron 88 en O0 y O2 con el mismo consumer y la misma
biblioteca. SHA-256 relevantes:

```text
76756aeaae6c89dc21c2c4f91fc8f8630be839c94b532885399985d9d7e7ccf5  linearAlgebra/src/lib.ae
244ff06e913e5d3d59a9a2f954334d14eae62796b95224d4303eb31c5c8d7a4a  linearAlgebra/tests/consumer/src/main.ae
c16ebdd2055103a83099d0d92f419ac8787847794965d9a7e685408bd1f97ff8  linearAlgebra/aether.toml
e701376fc796da20dd598a9daf203bc5688803c51af25d9bb69c838e74a1705c  linearAlgebra/tests/consumer/aether.toml
```

Esto demuestra que el cambio de Closure Runtime no es necesario para
reproducir el fallo observado, sin afirmar que toda interacción posible quede
descartada. La evidencia detallada, comandos y diagnóstico están en
`CLOSURE_LLVM_RUNTIME_V1_REPORT.md`.

Qualification final ejecutada:

- `owning_closures_read_v1`: 25/25 PASS, incluidos O0/O2, corrupción
  HIR/MIR/SSA, módulos fuente, ARC/alloc/free y ASan;
- `anonymous_functions_v1`: 5/5 PASS;
- `function_values_v1`: 8/8 PASS;
- Exceptions V1–V4: 6/6, 8/8, 8/8 y 7/7 PASS;
- `cargo fmt --all --check`: código 0;
- `cargo clippy --workspace --all-targets -j 1`: código 0 con warnings
  preexistentes;
- `git diff --check`: código 0.

`TMPDIR=/tmp/aether-owning-closures-read-v1 CARGO_INCREMENTAL=0 cargo test
--workspace -j 1` terminó con código 101. Todos los grupos anteriores pasaron,
incluidos `vertical` 220/220, frontend 78/78 y middle 29/29. Registry terminó
4/5: el último test falló en O0 con `Some(88)` después de 418,93 s. O2 no fue
alcanzado por ese test, pero la ejecución directa separada confirmó O2=88.

Veredicto final: **OWNING-CLOSURES-READ-V1 PARTIAL**. La implementación y
qualification productiva de Closure están completas y no queda una regresión
observada atribuible a Closure Runtime. Falta un snapshot de aceptación con el
workspace completo PASS; por tanto sólo corresponde aceptación condicionada,
no CLOSED. No se inició otro milestone.

Los únicos cambios del trabajo son los dos reportes y los cinco archivos del
reproducer (README, manifest, lockfile, lock de paquete vacío y `src/main.ae`).

## Actualización CLOSURE-LLVM-RUNTIME-V1 — PARTIAL (3 de noviembre de 2026)

El backend/runtime productivo quedó implementado y calificado. `ClosureCreate`,
`ClosureAlias`, `ClosureBorrow`, `ClosureCall`, `EndClosureBorrow`, Move y Drop
se emiten desde `VerifiedSsa` mediante `ClosureABI-v1`: header 0/W/2W, payload
alineado desde `align_up(3W, payload_alignment)`, invoke/destroy thunks privados,
ARC versionado y reachability de bodies sintéticos. Se retiró `E0376`.

La suite focal ejecuta consumers reales O0/O2, comprueba resultado observable,
contadores alloc/free/retain/release/destroy, captures Copy/Alias/Move,
replacement/return/nesting, exception cleanup, fuentes distintas y ASan. El
resultado focal final es 25/25 PASS. Anonymous Functions (5/5), Function Values
(8/8) y Exceptions V1–V4 (6/6, 8/8, 8/8, 7/7) también finalizaron PASS.

La evidencia, decisiones de layout y lista exacta de archivos están en
`CLOSURE_LLVM_RUNTIME_V1_REPORT.md`. La compatibilidad entre artefactos
independientes permanece OUT OF SCOPE bajo la enmienda ABI; no se presenta la
compilación conjunta como prueba de esa capacidad.

Fmt, Clippy y `git diff --check` terminaron con código 0. El workspace serial
completo llegó al último test de registry, pero éste falló: el consumer de
`linearAlgebra` modificado concurrentemente salió 88 en O0. Todos los grupos
anteriores finalizaron PASS, incluido `vertical` 220/220; el resultado global
no se presenta como PASS y no se revirtieron los cambios ajenos.

Clasificación conservadora: **CLOSURE-LLVM-RUNTIME-V1 PARTIAL** y
**OWNING-CLOSURES-READ-V1 PARTIAL** hasta obtener un rerun verde del workspace.
La implementación productiva y la qualification focal de Closure están
completas; el único gate abierto registrado es la regresión externa anterior.

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
