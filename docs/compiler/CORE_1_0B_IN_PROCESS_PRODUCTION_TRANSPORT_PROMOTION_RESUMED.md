# CORE-1.0B — In-process production transport promotion resumed

Fecha de continuación: 2026-08-29

Decisión local: `CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_PENDING_CI`

Este documento es evidencia nueva de la continuación. El primer intento y su
decisión `CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED` permanecen sin
modificaciones en
`CORE_1_0B_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION.md`.

## Promoción retomada después de CORE-PKG-1

La sección anterior conserva el primer intento y su decisión
`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED`. Ese intento no fue
incorrecto ni se reinterpreta: su único STOP blocker era la ausencia de una
distribución productiva del binding. CORE-PKG-1 lo resolvió formalmente con
`aether-compiler-core==1.0.0rc4` (run `33216160463`, revisión
`77417e7751482fc5a88a7d4207e99d67692da043`). No apareció otro bloqueo durante
la reauditoría del punto productivo.

Cada lane registra esta resolución como evidencia machine-readable mediante
`"previous_blocker": "resolved_by_CORE_PKG_1"`; el aggregate la exige y falla
cerrado si falta o cambia. Además, el aggregate vuelve a ejecutar el checker
oficial de CORE-PKG-1 y exige exactamente decisión
`CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED`, run `33216160463`, revisión
`77417e7751482fc5a88a7d4207e99d67692da043`, el pin `1.0.0rc4 == 1.0.0rc4` y
las cuatro superficies productivas (wrapper, binding, companion y manifest).
El job CI separado `blocker-resolution` hace la misma comprobación antes de
aceptar el aggregate; una etiqueta de lane por sí sola no resuelve el blocker.

La promoción retomada agrega el eje ortogonal
`AETHER_RUST_CORE_TRANSPORT`. La ausencia de la variable y el valor
`in_process` seleccionan PyO3; `companion` selecciona protocol-v1. Cualquier
otro valor falla cerrado. La selección queda fija en cada cliente productivo,
ambos clientes se reutilizan durante el proceso y ninguna excepción intenta el
otro transporte.

La ruta PyO3 entra por `aether_compiler_core.binding()` y la ruta rollback por
`aether_compiler_core.companion_path()`. Por lo tanto ambas ejecutan el mismo
build productivo versionado y verificado por CORE-PKG-1, sin depender de CWD,
PATH, checkout, `target/release` ni de `aether-core-qualification`.

`ProductionRustSSALoweringClient.provenance` expone de forma machine-readable
`requested_transport` y `observed_transport`. El core PyO3 se crea lazy una vez
por transporte y se reutiliza; cada request conserva una sesión Rust-owned
independiente. El contador y el último error estructurado son seguros para
concurrencia (este último es local al thread). El companion conserva startup
lazy, reuse persistente, recovery y cierre por `atexit`.

La observación no se copia del selector: cada adaptador declara su identidad de
transporte y el wrapper productivo la valida contra el valor solicitado antes
del primer request. Una conexión accidental entre una rama y el adaptador
opuesto se cierra sin ejecutar el request y falla cerrada.

No cambió `SSAPipeline.build`: los tres modos de authority que necesitan Rust
siguen recibiendo el mismo protocolo lógico de cliente y pueden ejecutar ambos
transportes. `python_ssa_only` no consulta la política de transporte. Tampoco
cambiaron Initial IR, schema-v1/v2, lifecycle, SSA, import, verifier,
refinement, canonical comparison, optimizer, backend ni protocol-v1.

La calificación executable queda definida por:

- `tests/aether/test_core_1_0b_in_process_transport.py`: política, provenance,
  no-fallback, sesiones/concurrencia, default guard y ortogonalidad;
- `scripts/qualify_core_1_0b_in_process_transport.py`: pipeline `.ae`, corpus
  histórico, CFG profundo, seis rechazos Initial IR/binding representativos con
  paridad estructurada, differential, rollback y performance por ambos
  transportes productivos. La caracterización usa warmup y cinco muestras para
  workload ordinario, histórico 116, CFG profundo 1000 y `expense_tracker`, sin
  umbral de corrección; registra mediana y dispersión separadas para conversión
  de entrada, core Rust, IPC/protocol y conversión de resultado;
- `scripts/check_core_1_0b_in_process_transport.py`: aggregate fail-closed con
  revisión exacta, matrices completas, evidencia obligatoria del consumer
  empaquetado y ausencia de evidencia tratada como bloqueo;
- `scripts/core_1_0b_packaged_consumer_probe.py`: verifica sólo los wheels
  productivos instalados en un venv fuera del checkout, sin Cargo/rustc en
  `PATH`; registra `requested_transport`/`observed_transport`, prueba failure y
  recovery sobre el mismo cliente y bloquea si el rollback companion invoca el
  binding PyO3;
- `.github/workflows/core-in-process-promotion.yml`: Linux/Windows/macOS,
  x86_64/arm64 y CPython 3.11–3.14. Cada lane de plataforma y Python construye
  wheels, ejecuta consumers aislados con ambos transportes y oculta Cargo/rustc;
  un job separado repite el development install oficial. Los workflows
  históricos no se modifican.

CLI, VS Code/LSP e IntelliJ no poseen un selector de companion separado: todos
terminan en el paquete/CLI Python y `SSAPipeline`; por eso la promoción no exige
rediseño IDE. El workflow agrega smoke del pipeline compartido y clean-wheel
consumer para ambos transportes.

La decisión previa al CI oficial es
`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_PENDING_CI`. Sólo el aggregate
con evidencia oficial completa puede emitir
`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTED`; cualquier lane ausente o
fallida emite `CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED`.

## Revalidación local del segundo intento

El 29 de agosto de 2026, sobre Linux x86_64 y CPython 3.14, la qualification
completa observó 116/116 inputs por ambos transportes, pipeline productivo
116/116, CFG 993/1000/5000/10000, seis rechazos estructurados equivalentes,
differential positivo y divergencia/corrupción fail-closed en ambos
transportes. El aggregate local recomputó CORE-PKG-1 y emitió
`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_PENDING_CI` sin errores.

El procedimiento de development install reconstruyó el binding y companion
productivos desde el árbol actual. Un venv separado, instalado sólo desde los
wheels resultantes y ejecutado fuera del checkout sin Cargo/rustc en `PATH`,
observó `in_process` por default (cero procesos) y `companion` por rollback
explícito (un proceso persistente); ambos recuperaron el mismo cliente después
de un rechazo manejado.

La suite Python amplia obtuvo 5110 PASS y 4 SKIP. Sus 24 fallos pertenecieron
exclusivamente a `test_native_exceptions.py`: LeakSanitizer informó que no puede
ejecutarse bajo ptrace en este entorno. El archivo completo pasó 54/54 al
repetirse con `LSAN_OPTIONS=detect_leaks=0`; esto valida comportamiento pero no
reemplaza el gate de leaks de CI. `cargo check --workspace --locked`,
`cargo test --workspace --locked` y `cargo fmt --all --check` pasaron. No se
infieren resultados locales para Windows ni macOS.

## Incidente del primer run oficial CORE-1.0B

El run `33264243543` permanece inmutable con conclusión `FAILED`. Demostró dos
defectos del harness, no una nueva decisión de promoción: el cierre histórico
de CORE-PKG-1 intentaba leer la revisión `77417e77` desde el object store del
checkout actual (ausente en el clon shallow de Actions), y PowerShell entregaba
literalmente `native-dist/*.whl` a pip.

El consumidor del cierre ahora verifica los hashes fijados en la evidencia
histórica sin exigir que el checkout posterior contenga ese objeto Git ni sea
byte-identical. La comprobación explícita del source actual permanece separada
y falla si diverge. La instalación de CORE-1.0B selecciona mediante Python
exactamente un wheel compatible `aether-compiler-core==1.0.0rc4` y exactamente
un wheel `aether-language==1.0.0rc4`; cero candidatos, identidad incorrecta o
múltiples candidatos compatibles bloquean antes de invocar pip. Pip recibe
únicamente paths concretos.

Este arreglo no convierte retrospectivamente el run `33264243543` en PASS ni
cambia el estado histórico `SUCCESS` del run CORE-PKG-1 `33216160463`. Requiere
un nuevo run oficial para decidir CORE-1.0B; Windows no se afirma PASS a partir
de la regresión portable ejecutada localmente.

## Incidente del run oficial 33265815894

El run `33265815894` también permanece inmutable con conclusión `FAILED` y
decisión válida `CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED`. La
qualification demostró exactamente dos gaps adicionales del harness:

1. `packaged-clean-consumer` instalaba los dos wheels Aether con `--no-deps`
   sin preparar las dependencias runtime declaradas por `aether-language`; el
   probe se detenía con `ModuleNotFoundError: numpy` antes de observar un
   transporte.
2. El aggregate aceptaba indistintamente todos los records
   `core_1_0b_packaged_consumer`. Por eso la evidencia redundante de las
   matrices de plataforma/Python podía sustituir el artifact obligatorio del
   job `packaged-clean-consumer` y producir incorrectamente `PROMOTED`.

El artifact aggregate que emitió `PROMOTED` en ese run es internamente
inconsistente e inválido para closure; no se reinterpreta como promoción.

El instalador ahora lee `Requires-Dist` del METADATA del wheel exacto, exige el
pin `aether-compiler-core==1.0.0rc4`, instala por separado los pins runtime
activos y sólo entonces instala los dos paths de wheel seleccionados con
`--no-deps`. Pip nunca recibe un requirement de Aether resoluble desde un
índice. Un manifiesto registra paths y SHA-256 de ambos wheels, requirements e
inventario instalado y el ejecutable/versión de Python.

El consumer dedicado usa un kind distinto,
`core_1_0b_packaged_clean_consumer`, y referencia ese manifiesto exacto. Ejecuta
una compilación Aether representativa por default `in_process` y otra con el
rollback explícito `companion`; registra el mismo hash SSA para ambas, orígenes
importados, companion instalado, ausencia de checkout en `sys.path` y ausencia
de Cargo/rustc.

El checker mantiene una lista nominal de todos los artifacts requeridos:
blocker resolution, functional, development install, matrices de plataforma y
Python con sus consumers, manifiesto de instalación y ambos records del
consumer dedicado. Exige archivo, JSON object, kind/role, revisión, run, PASS y
subgate esperado. Los records de matrices ya no pueden sustituir al artifact
dedicado. Ausencia, corrupción, FAIL, mismatch o transporte no observado
bloquean y hacen fallar closure.

La corrección local en Linux x86_64/CPython 3.14 construyó ambos wheels, instaló
desde METADATA `matplotlib==3.10.8`, `numpy==2.4.2`, `scipy==1.17.1` y
`sympy==1.14.0` en un venv temporal, y pasó ambos probes sin toolchain ni
checkout importable. Las regresiones adversariales cubren evidencia válida,
consumer dedicado ausente/fallido/corrupto/con revisión distinta, observación
default incorrecta, rollback companion ausente, otro prerequisite ausente y
evidencia redundante que intenta sustituir el artifact obligatorio.

La decisión después de esta corrección local es
`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_PENDING_CI`. Sólo un nuevo run
oficial completo puede emitir una promoción formal.
