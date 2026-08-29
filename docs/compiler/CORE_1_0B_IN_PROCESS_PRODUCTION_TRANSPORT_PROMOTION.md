# CORE-1.0B — In-process production transport promotion

Fecha de auditoría: 2026-08-28

Revisión base: `68bb482594dfb372eee2f55f9c5b725dba84e7cd`

## Decisión local

`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED`

La promoción se detuvo antes de modificar el selector productivo. La condición
de parada de CORE-1.0B se cumple: el binding calificado no forma parte de la
distribución principal de Aether y promoverlo exige una decisión significativa
de packaging/distribución.

Actualmente:

- `aether-language` usa `setuptools.build_meta`, declara un paquete Python
  `py3-none-any` y no depende de un runtime nativo;
- el binding se construye por separado con Maturin como
  `aether-core-qualification`;
- el módulo `_aether_core` publica `QUALIFICATION_ONLY=True`;
- el adaptador `InProcessRustSSALoweringClient` rechaza cualquier extensión que
  no declare exactamente ese estado de qualification;
- CORE-1.0A sólo calificó clean install del wheel separado. Su cierre limita
  explícitamente la afirmación a esos wheels calificados y dice que no es una
  promoción productiva;
- el rollback companion requiere además el binario y manifest instalados en
  `<sys.prefix>/libexec/aether/ssa-shadow`; el wheel principal no los contiene.

Cambiar el selector ahora haría que una instalación oficialmente documentada
del wheel principal falle siempre al importar `_aether_core`, o exigiría un
fallback silencioso al companion, expresamente prohibido por CORE-1.0B. No se
eligió ninguna de esas dos conductas.

## Auditoría del flujo productivo actual

### Entradas reales

Los consumidores nativos del CLI (`--emit-ssa`, `--emit-llvm` y ejecución
nativa) pasan por `aether.pipeline.lower_to_verified_ssa`, que crea
`SSAPipeline(builder="general")`. El punto único de selección está en
`src/aether/pipeline.py::SSAPipeline.build`.

La autoridad default de RUST-4.5 se resuelve en
`src/aether/ssa/shadow.py::resolve_ssa_lowering_authority_mode` como
`rust_ssa_authority_refinement_verified`. La rama correspondiente obtiene
`default_rust_ssa_lowering_client()` y ejecuta
`lower_with_shadow_independent_rust_authority()`.

### Transporte productivo antes de CORE-1.0B

`default_rust_ssa_lowering_client()` devuelve el singleton
`ProductionRustSSALoweringClient`. En su primer request éste descubre solamente
el companion instalado en el prefijo canónico, construye un
`PersistentRustSSALoweringClient` y lo reutiliza durante el proceso Python. Un
lock protege la creación del cliente y otro serializa los requests del proceso
persistente. `atexit` cierra el companion.

El protocolo-v1 observado es:

1. Python verifica Initial IR, ejecuta `expand_lifecycle`, materializa
   `schema-v1` y lo serializa una sola vez como JSON compacto.
2. Python envía `u32` big-endian de longitud seguido por el payload.
3. El companion deserializa `IRModuleDTO` y llama
   `CompilerCore.lower_verified_ssa(initial)`.
4. Rust conserva la semántica compartida: lifecycle policy-v1, lowering SSA y
   verificación owned SSA; después materializa schema-v2.
5. El companion responde otro frame JSON con `{"ok":true,"ssa":...}` o
   `{"ok":false,"error":...}`.
6. Python importa schema-v2 estrictamente, ejecuta `SSAVerifier`, comprueba
   integridad same-input, ejecuta refinement obligatorio, vuelve a comprobar
   integridad y ejecuta la verificación genérica final.

No hay fallback de PATH, checkout o `target/`: la ausencia o incompatibilidad
del companion instalado falla cerrada. La variable interna
`AETHER_INTERNAL_RUST_SSA_QUALIFICATION_EXECUTABLE` puede seleccionar un path
absoluto únicamente para el harness de qualification.

### Semántica compartida y boundary PyO3 calificado

No existen dos cores semánticos. El companion en
`compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs` y PyO3 en
`compiler-rs/crates/aether-python/src/lib.rs` delegan al mismo
`aether_verifier::CompilerCore` definido en `compiler_core.rs`.

PyO3 crea un `CompilerCore`, acepta bytes schema-v1 en una
`CompilationSession` Rust-owned, ejecuta `lower_ssa()` y exporta schema-v2. La
sesión usa `Mutex<CompilationSession>` y libera el GIL durante trabajo Rust. El
adaptador Python crea un core por cliente, sesiones por compilación y mantiene
el core durante el lifetime del cliente; no tiene registry global de handles ni
fallback al companion.

CORE-1.0A calificó formalmente este boundary en Linux x86_64, Windows x86_64,
macOS x86_64, macOS arm64 y CPython 3.11–3.14. También calificó histórico
116/116, failures, deep CFG 993/1000/5000/10000, sesiones, concurrencia y
performance. Esa evidencia califica el boundary, no decide cómo distribuirlo
como requisito del producto.

### Contrato de error

Los errores del `CompilerCore` tienen `kind`, `category`, `phase`, `code`,
`function`, `block`, `source_location` y `message`. PyO3 los convierte en
subclases de `AetherCoreError` con esos atributos. El companion ordinario
mantiene el contrato protocol-v1 histórico de texto; el modo exclusivo
`--qualification-structured-errors` expone el diagnóstico estructurado usado
para parity. En producción, las capas Python convierten fallos de transporte,
respuesta, import, verifier y refinement en clasificaciones fail-closed.

No se modificaron formatting, schema-v1, schema-v2, lifecycle, refinement ni
la asignación de errores.

### Authority, rollback y differential

La selección de autoridad está separada conceptualmente del transporte y se
controla sólo mediante `AETHER_SSA_AUTHORITY_MODE`:

- `rust_ssa_authority_refinement_verified` (default RUST-4.5);
- `rust_ssa_authority_python_shadow` (differential fail-closed);
- `python_ssa_authority_rust_shadow` (rollback de autoridad);
- `python_ssa_only` (no invoca Rust).

Hoy las tres ramas que invocan Rust reciben el mismo cliente companion por
default. La rama Python-only no selecciona transporte. CORE-1.0B deberá cambiar
solamente la fábrica del cliente y preservar estas ramas sin cambios
semánticos.

## Superficies separadas

| Superficie | Implementación actual | Estado CORE-1.0B |
|---|---|---|
| Transporte | `ProductionRustSSALoweringClient` → protocol-v1 companion | Candidato a promoción, no modificado |
| Semántica | `CompilerCore`, lifecycle/lowering/verifiers/refinement existentes | Fuera de alcance, no modificada |
| Qualification | `InProcessRustSSALoweringClient` y workflow CORE-1.0A | Evidencia reutilizable |
| Rollback | Companion persistente explícitamente instalable | Debe conservarse; packaging por decidir |
| Differential Python-shadow | `GeneralSSABuilder` + comparación canónica | Debe conservarse con ambos transportes |

## Decisión de distribución requerida

Antes de continuar debe aprobarse uno de estos contratos de entrega:

1. **Runtime nativo separado (recomendado).** Promover el wheel calificado a una
   distribución productiva versionada, por ejemplo `aether-compiler-core`, que
   incluya `_aether_core` y el companion/manifest de rollback. Hacer que
   `aether-language` dependa de su misma versión exacta. Esto conserva el wheel
   Python principal y aprovecha la matriz Maturin ya calificada, pero obliga a
   coordinar publicación, versiones y disponibilidad de wheels nativos.
2. **Wheel principal nativo unificado.** Migrar el build principal a un proyecto
   Maturin mixto (o integrar `setuptools-rust`) y empaquetar extensión y
   companion juntos. Simplifica la instalación a una distribución, pero cambia
   el backend, los tags y el flujo editable/release de todo `aether-language`.
3. **Instalación explícita de dos distribuciones sin dependencia.** Mantener el
   wheel nativo separado y documentarlo como prerrequisito manual. No se
   recomienda: una instalación normal de `aether-language` quedaría incompleta
   aunque el transporte default fuese in-process.

La opción recomendada también debe fijar:

- nombre y versión de la distribución nativa;
- si adopta la versión de Aether o un ABI/versionado independiente;
- ubicación wheel del companion y manifest para que el rollback sea realmente
  de primera clase;
- política de sdist cuando no exista wheel compatible;
- comportamiento de editable/source checkout;
- publicación atómica de las cuatro plataformas y CPython soportados;
- cómo CLI, VS Code/LSP e IntelliJ obtienen el mismo entorno instalado.

## Trabajo deliberadamente no ejecutado

Por la condición de parada no se agregaron aún
`AETHER_RUST_CORE_TRANSPORT`, selector/provenance, tests CORE-1.0B, qualifier,
checker ni workflow. Implementarlos antes de resolver packaging produciría
evidencia sobre un entorno ensamblado a mano, no sobre una instalación
productiva real.

Tampoco se ejecutaron los gates de promoción: no existe una promoción válida
que calificar. La evidencia CORE-1.0A permanece intacta y no se modificó su
workflow histórico.

## Confirmaciones de alcance

- CORE-1.1 no fue implementado.
- Las responsabilidades semánticas no cambiaron.
- El companion no fue eliminado ni modificado.
- No se agregó fallback automático.
- No se cambió ningún authority mode.
- No se cambió schema-v1/schema-v2.
- No se creó commit.

---

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
