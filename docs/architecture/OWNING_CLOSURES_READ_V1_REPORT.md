# Aether — OWNING-CLOSURES-READ-V1 — ABI Scope Review Report

## Estado

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

## Trabajo real restante de V1

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
