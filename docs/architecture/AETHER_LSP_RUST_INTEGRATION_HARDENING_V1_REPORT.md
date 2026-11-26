# AETHER-LSP-RUST-INTEGRATION-HARDENING-V1 — reporte

Estado: **CLOSED — con limitación documentada de qualification IntelliJ**, 2026-11-26.

Durante la implementación original no se hizo commit ni push. Este cierre Git consolida el
milestone en un único commit y no hace push. No se ejecutaron `reset`, `clean`, `stash`,
descargas, `sync` ni `update` de packages.

## 1. Preflight

- Branch: `main`.
- HEAD y `origin/main`: `a31d63c52d7a5795a540c2dd5e2b587f1a4424b2`;
  no había commits publicados o no publicados divergentes.
- Se preservaron sin modificación intencional los cambios personales ya presentes en
  `examples/ProbandoNR`, sus locks/binarios, los locks de `examples/assessment`,
  `probandoNR3C`, `tmp_lambda_test.ae`, `scrap/` y todos los ignored/temporales.
- `.vscode/settings.json` está ignored por `.gitignore`, selecciona localmente
  `compiler-next/target/debug/aether-lsp` y no fue modificado.
- Se revisaron los reportes CLOSED de editor analysis, document overlay, canonical loader,
  request lifecycle y `AETHER_LSP_RUST_DIAGNOSTICS_V1`, además de
  `COMPILER_AUTHORITY.md`, los contratos de identidad/package y los tests protocolarios.
- `compiler-next` continúa siendo la única autoridad. No se modificaron Python legacy ni
  `compiler-rs`.

## 2. Riesgos investigados

Se auditó la ruta `AnalysisScheduler -> RequestCompletion -> publication mutex -> channel
FIFO -> writer único -> stdout`, el descubrimiento ascendente de `aether.toml`,
`ProjectPlan::load_read_only`, la asociación documento/proyecto y la unión de
contribuciones por target y URI.

Los escenarios de package se contrastaron con la frontera read-only y con los tests de
`aether-package`: lock correcto, ausente, malformado, divergente del manifest, package
materializado ausente, arista transitiva ausente y source standalone. Ninguno causa red o
escrituras implícitas.

Se revisaron `initialize`, `initialized`, `shutdown`, `exit`, `didOpen`, `didChange`,
`didSave`, `didClose`, `publishDiagnostics`, `$/cancelRequest`, framing, UTF-16, full sync,
versiones regresivas, métodos desconocidos y recuperación después de JSON malformado. Las
capabilities siguen anunciando sólo UTF-16 y text sync Full/open-close/save.

## 3. Defectos confirmados

1. Un archivo debajo de un manifest cuyo lock no cargaba devolvía `None` desde
   `project_for` y era analizado silenciosamente como standalone.
2. Un módulo secundario abierto dentro de un proyecto validado podía disparar otro análisis
   con ese módulo como entry, fuera de las reglas del entry oficial.
3. La unión multi-target concatenaba diagnósticos idénticos y no tenía una identidad
   explícita de deduplicación.
4. Un plan validado quedaba cacheado sin revalidar el lock antes de nuevas rondas de
   análisis; una desaparición o invalidación posterior podía continuar usando el plan viejo.
5. La limpieza por close reconstruía la unión sin aplicar la misma deduplicación que una
   publicación normal.

## 4. Causas raíz

El tipo de retorno `Option<ProjectId>` colapsaba cuatro estados distintos: proyecto listo,
proyecto no disponible, standalone y fallo interno. La asociación sólo comparaba el archivo
con el entry y no conservaba el rol del documento. Por separado, las contribuciones se
guardaban correctamente por target/URI, pero su unión era un `flatten` sin identidad.

## 5. Correcciones implementadas

- La selección de contexto distingue `Ready`, `Unavailable`, `Standalone` e
  `InternalFailure`.
- Un proyecto no disponible publica un diagnóstico `aether.project-unavailable` con source
  `aether-project`; no ejecuta semántica standalone ni inventa errores semánticos.
- Los módulos secundarios se mantienen como overlays del snapshot, pero se diagnostican a
  través del entry canónico. Al abrirse solos reciben una publicación coherente, no un
  análisis standalone.
- Antes de cada ronda se vuelve a ejecutar exclusivamente `ProjectPlan::load_read_only`.
  Cambios de plan, pérdida y recuperación avanzan la generación; el documento se asocia o
  desasocia atómicamente mediante `EditorWorkspace::set_document_project`.
- La unión deduplica valores protocolarios completos y usa la misma operación en análisis y
  close.
- Se agregó cobertura del writer desconectado; el writer termina sin panic ni reintento
  desordenado.

## 6. Invariantes de publicación

El punto de linearización es la adquisición del mutex de publicación en la segunda compuerta:
allí se valida época/open, se reemplaza la contribución y se encolan todas las URI afectadas.
El writer único consume el channel FIFO y realiza IO sin conservar locks de análisis o de
publicación.

Una edición incrementa la revisión del workspace y posteriormente la época del target. Un
resultado anterior que aún no entró a la compuerta se descarta; si ya fue encolado, la
publicación posterior queda encolada detrás y determina el estado final observable. Una
notificación ya entregada al channel no se describe como retirable. Close invalida la época,
retira sólo la contribución del target cerrado, limpia su URI y recompone las restantes.

## 7. Contrato de proyectos

- **ProjectReady:** lock y grafo oficiales cargados read-only; sólo el entry es target y los
  demás documentos del proyecto son overlays/módulos.
- **ProjectUnavailable:** existe frontera de proyecto, pero lock/grafo/materialización no
  puede validarse; se publica diagnóstico de proyecto y no hay fallback semántico.
- **Standalone:** no se encontró manifest hasta el workspace root; se permite análisis
  standalone explícito.
- **InternalFailure:** no se pudo representar la propia frontera (por ejemplo, root no
  canonicalizable); se publica un diagnóstico interno separado.

Cada ronda revalida sin red, descargas o mutaciones. La recuperación reinstala el plan y la
asociación documental; la pérdida lo desasocia antes de publicar.

## 8. Contrato multiarchivo

Las contribuciones permanecen indexadas por `DocumentId` target y URI. Reemplazar un target
afecta la unión de las URI previas y nuevas, de modo que imports agregados, eliminados,
renombrados o corregidos reciben actualización o limpieza. Cerrar un overlay permite que un
target vigente vuelva a diagnosticar el archivo de disco, sin borrar contribuciones de otros
targets.

La identidad de deduplicación contiene el JSON completo del diagnóstico: range, severity,
code, source, message y related information. Dos contribuciones idénticas colapsan; dos
diagnósticos con igual code/range pero distinto mensaje o related information se conservan.
El orden de la publicación es determinista por esa identidad.

## 9. Tests nuevos

Los tests del binario real por stdio agregan:

- proyecto con lock válido;
- lock ausente y lock malformado con fail-closed explícito;
- transición lock válido -> ausente -> restaurado sin reabrir el documento;
- prueba negativa de que no aparece el diagnóstico standalone `E0202` durante fallback;
- dos targets que diagnostican el mismo módulo y deduplicación a una sola entrada.

Los unit tests agregan preservación de diagnósticos distintos con el mismo code/range y
terminación segura del writer ante `BrokenPipe`. La suite existente conserva cobertura de
overlays importados, UTF-16, ediciones rápidas, stale suppression, close, shutdown y
recuperación protocolaria.

## 10. Qualification

Resultados observados sobre el árbol final:

- `cargo test -p aether-lsp`: PASS (4 unitarios, 5 stdio, doc-tests).
- `cargo test -p aether-analysis -j 1`: PASS (36 + doc-tests).
- `cargo test -p aether-package -j 1`: PASS.
- `cargo check --workspace`: PASS.
- `cargo test --workspace -j 1`: PASS; QR finalizó en **710,77 s**.
- `cargo fmt --all --check`: PASS.
- `cargo clippy --workspace --all-targets -j 1`: PASS con warnings preexistentes fuera del
  cambio; `aether-lsp` no agrega warnings.
- `bash compiler-next/tests/test-differential-harness.sh`: PASS.
- `bash compiler-next/tests/run-differential.sh`: PASS,
  `mode=official checked=96 failures=0`.
- VS Code `npm test`: PASS, 4/4.
- IntelliJ: **NO EJECUTADO / PENDIENTE DE RECALIFICACIÓN**. El checkout no contiene
  `gradlew` y el `gradle` del sistema queda bloqueado antes de cargar el proyecto porque no
  puede inicializar `libnative-platform.so`. No se presenta como PASS.
- `git diff --check`: PASS.

`cargo tree -p aether-lsp --depth 3` conserva
`aether-lsp -> aether-analysis -> aether-frontend/aether-package`, `sha2` y `serde_json`.
No aparecen driver, middle, backend LLVM, Python ni `compiler-rs`.

## 11. Limitaciones

- No se realizó un nuevo smoke GUI. Se conserva como evidencia histórica el smoke manual de
  VS Code del reporte anterior.
- El protocolo continúa limitado a documentos `file:` y full text sync.
- No existe `workspace/didChangeWatchedFiles`; por ello la revalidación de manifest/lock se
  observa en la siguiente notificación documental que provoca una ronda.
- El channel estándar no permite informar al reader que stdout falló; la garantía es terminar
  el writer sin panic y no reordenar/reintentar mensajes.
- No se agregaron completion, hover, navegación, formatting ni otra capability.

## 12. Estado de integración IDE

Los defaults de VS Code e IntelliJ no cambiaron y el LSP Python sigue disponible como
alternativa. VS Code quedó cubierto por sus tests automatizados. IntelliJ conserva su
integración, pero queda **NO EJECUTADO / PENDIENTE DE RECALIFICACIÓN** en esta máquina por
el bloqueo de bootstrap de Gradle; esta qualification no se presenta como PASS.

Procedimiento manual reproducible para ambos IDE:

1. Compilar `compiler-next/target/debug/aether-lsp` con
   `cargo build -p aether-lsp` desde `compiler-next`.
2. Configurar temporalmente ese path en `aether.lsp.executable` (VS Code) o en “Aether
   language server executable” (IntelliJ); ambos launchers agregan `--stdio`.
3. Abrir un proyecto con `aether.toml`, lock válido, entry e import `Alpha`.
4. Introducir sin guardar un error sintáctico en `Alpha`; verificar diagnóstico en la URI de
   `Alpha`, corregirlo y verificar limpieza.
5. Quitar temporalmente el lock, editar el entry y verificar
   `aether.project-unavailable`; restaurar el lock, editar otra vez y verificar recuperación.
6. Cerrar/reabrir `Alpha`, renombrar/eliminar el import y comprobar las limpiezas.
7. Restaurar la preferencia temporal; no cambiar defaults del repositorio.

## 13. Archivos modificados

- `compiler-next/crates/aether-analysis/src/editor.rs`
- `compiler-next/crates/aether-lsp/src/lib.rs`
- `compiler-next/crates/aether-lsp/tests/protocol.rs`
- `docs/architecture/AETHER_LSP_RUST_INTEGRATION_HARDENING_V1_REPORT.md`

Los demás cambios y untracked mostrados por `git status` son trabajo personal preexistente y
no forman parte del entregable.

## 14. Commit de cierre

`fix(lsp): harden project fallback and multi-target publication`

## 15. Decisión de cierre

Las cinco correcciones, los tests de publicación, la qualification Rust completa y el
diferencial oficial 96/96 satisfacen las condiciones técnicas del milestone. Se declara
**CLOSED — con limitación documentada de qualification IntelliJ**. IntelliJ permanece
**NO EJECUTADO / PENDIENTE DE RECALIFICACIÓN** por el bloqueo de Gradle descrito arriba;
la ausencia de `workspace/didChangeWatchedFiles` permanece como limitación protocolaria y
obliga a esperar la siguiente notificación documental para observar cambios externos de
manifest o lock.
