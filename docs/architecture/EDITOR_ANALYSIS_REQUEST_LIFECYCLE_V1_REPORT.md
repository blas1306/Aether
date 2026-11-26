# EDITOR-ANALYSIS-REQUEST-LIFECYCLE-V1 — reporte

Estado: **CLOSED; IMPLEMENTADO Y QUALIFIED**, 2026-11-26.

## 1. Implementación

`aether-analysis` incorpora un lifecycle explícito para solicitudes editoriales
sin agregar LSP, JSON-RPC ni otra autoridad semántica. `AnalysisRequest` posee
un `RequestId`, `AnalysisTarget`, `AnalysisSnapshot` inmutable y
`CancellationToken`. `AnalysisScheduler` mantiene un worker serial por
`EditorWorkspace`; cada ejecución continúa usando `CanonicalAnalyzer`, el
loader compartido y el frontend oficial.

Los IDs son monotónicos dentro del scheduler y no se comparan ni reutilizan
como versiones documentales. El estado mutable del frontend continúa siendo
local a cada invocación.

## 2. Estados y transiciones

Las transiciones válidas son:

```text
Queued -> Running -> Published | Stale | Cancelled | TargetClosed
                  | SourceChanged | InternalFailure
Queued -> Cancelled | InternalFailure
```

`RequestState::transition` rechaza saltos, repeticiones y transiciones desde un
estado terminal. `RequestCompletion` entrega una sola terminalización y sólo
incluye `AnalysisResult` cuando la publicación fue admitida.

## 3. CancellationToken

El token usa `Arc` y atomics, y distingue cancelación solicitada de cancelación
observada. Registra además el tiempo entre ambas. Los checkpoints se ejecutan
antes de analizar, después de capturar el snapshot, alrededor de discovery y
de cada operación del provider, antes/después de declarations y bodies, antes
de adaptación/verificación y antes de publicación.

No se hace polling dentro del lexer, parser o typechecker. Si la cancelación
llega durante una fase batch, la fase termina y su resultado se descarta en el
checkpoint posterior.

## 4. Scheduler

El scheduler usa `std::thread`, `Mutex`, `Condvar` y una `VecDeque`; no incorpora
Tokio ni un pool general. El worker toma snapshots owned y nunca conserva el
lock del store durante el frontend. Una solicitud nueva cancela la ejecución
anterior del mismo target y elimina solicitudes queued obsoletas de ese target,
por lo que no acumula versiones antiguas ilimitadamente. Targets diferentes se
ejecutan FIFO.

El cierre cancela la cola, solicita cancelación de la ejecución activa, espera
al worker y rechaza trabajo nuevo. Un fallo o panic recuperable no termina el
worker.

## 5. Condiciones de publicación

La decisión central `may_publish_analysis` requiere:

1. request vigente para el target;
2. documento target todavía abierto cuando corresponde;
3. workspace y revisión iguales al snapshot;
4. cancelación no solicitada/observada;
5. fingerprints externos todavía iguales.

La lectura del estado y la verificación de inputs externos mantienen el read
lock del workspace, de modo que una mutación del store no puede intercalarse en
la decisión. Los resultados se clasifican como `Published`, `Stale`,
`Cancelled`, `TargetClosed`, `SourceChanged` o `InternalFailure`. Un resultado
`Partial + Invalid` vigente conserva y publica sus diagnósticos; un fallo
interno no se convierte en diagnóstico de usuario.

## 6. Recuperación de fallos

Cada ejecución se envuelve en `catch_unwind` cuando el perfil admite unwind.
El panic se transforma en `AnalysisFailure::Internal`, se descarta todo el
estado de esa sesión y el siguiente elemento continúa. No se promete
recuperación con `panic=abort` ni frente a terminaciones fatales del proceso.

Errores de target, adaptación y provider permanecen explícitos. Un
`SourceId` inválido continúa siendo un fallo interno. La publicación vuelve a
validar cada source externa y distingue cambio de contenido de imposibilidad
de verificar el provider.

## 7. Tests de concurrencia

Las pruebas focales usan canales y puntos de sincronización controlados, nunca
`sleep`. Cubren IDs únicos, transiciones inválidas, cancelación queued antes de
iniciar, cancelación de una ejecución activa, cancelación después de trabajo
batch no preemptible, FIFO entre targets, coalescing del mismo target, edición
y cierre durante análisis, cambio externo, stale suppression, publicación
`Partial + Invalid`, recuperación después de panic y cierre ordenado.

Las pruebas existentes siguen cubriendo captura coherente de varios overlays,
versiones documentales, restauración al cerrar, fingerprints y source mapping.

## 8. Rendimiento inicial

`AnalysisMeasurements` registra tiempo en cola, análisis total, observación de
cancelación y las fases frontend existentes. `SchedulerMeasurements` registra
trabajo descartado por stale/cancelación, máximo de pendientes, requests
completadas y bytes de overlays retenidos por snapshots queued.

No se fijaron presupuestos de latencia. Al retirar o ejecutar un queued item se
libera su snapshot; sólo queda una versión pending por target.

## 9. Qualification

Resultados confirmados:

- `cargo test -p aether-analysis`: PASS, 36/36 más doc-tests.
- `cargo check --workspace`: PASS.
- `cargo test --workspace -j 1`: PASS completo sobre el código final; el test
  QR del registry terminó normalmente en 711,28 s y luego finalizaron todos
  los doc-tests.
- `cargo fmt --all --check`: PASS.
- `cargo clippy --workspace --all-targets -j 1`: PASS; conserva warnings
  preexistentes fuera de `aether-analysis` y el crate no agrega warnings.
- `bash compiler-next/tests/test-differential-harness.sh`: PASS.
- `bash compiler-next/tests/run-differential.sh`: PASS,
  `mode=official checked=96 failures=0`.
- `cargo tree -p aether-analysis --depth 3`: sólo frontend, package, `sha2` y
  dependencias transitivas; sin driver, middle, backend, LLVM, Python ni
  legacy.
- `git diff --check`: PASS.

## 10. Limitaciones

- La cancelación continúa siendo cooperativa; no preempta una función batch.
- La atomicidad del filesystem externo queda limitada por el contrato del
  provider; el workspace sí queda protegido durante la decisión.
- No se implementan LSP, features de navegación, parsing incremental ni
  semántica nueva.
- No se recuperan aborts ni fallos fatales del proceso.

## 11. Archivos modificados

- `compiler-next/crates/aether-analysis/src/lifecycle.rs`
- `compiler-next/crates/aether-analysis/src/diagnostics.rs`
- `compiler-next/crates/aether-analysis/src/editor.rs`
- `compiler-next/crates/aether-analysis/src/lib.rs`
- `docs/architecture/EDITOR_ANALYSIS_REQUEST_LIFECYCLE_V1_REPORT.md`

## 12. Mensaje de commit sugerido

`feat(analysis): add cancellable editor request lifecycle`
