# EDITOR-DOCUMENT-OVERLAY-V1 — reporte

Estado: **CLOSED; IMPLEMENTADO Y RECALIFICADO**, 2026-11-25.

Este milestone agrega el store documental, snapshots y overlays editoriales a
`aether-analysis`. No agrega LSP, scheduling, diagnostics editoriales ni una
segunda implementación de discovery.

## 1. Implementación

- `EditorWorkspace` conserva `WorkspaceId`, `DocumentId` estables, versiones
  monotónicas, asociaciones de proyecto y una revisión global.
- `open`, `change`, `saved`, `close` y `filesystem_changed` implementan las
  transiciones CLOSED. `saved` vuelve a leer el disco y nunca escribe el
  documento.
- `AnalysisSnapshot` captura bajo un lock corto las versiones, overlays,
  generaciones de proyectos, planes validados y configuración. Parsing y
  discovery ocurren después de liberar el lock.
- `OverlaySourceProvider<DiskSourceProvider>` combina todos los overlays del
  snapshot. El provider sólo selecciona bytes/provenance; el loader canónico
  continúa asignando packages, módulos, imports e IDs.
- `SnapshotDiscovery` une inequívocamente sesión, `SnapshotStamp` e inventario
  de fingerprints efectivamente leídos.
- `may_publish` distingue resultado vigente, stale, target cerrado, source de
  disco cambiado y error del provider.

## 2. Comportamiento de documentos y filesystem

- Un archivo inexistente puede permanecer abierto y ser analizado desde su
  overlay si el directorio raíz existe. Cerrarlo retira el overlay; una lectura
  posterior informa missing por la ruta canónica.
- Si un archivo se elimina mientras está abierto, el texto capturado sigue
  siendo autoridad y `DiskBase` pasa a `Missing`. Si ya estaba cerrado, no se
  inventa contenido y discovery falla explícitamente.
- Locators existentes se canonicalizan. Dos spellings de symlink comparten
  `DocumentId`; la enumeración canónica conserva su política fail-closed ante
  symlinks dentro del árbol de sources.
- Un documento virtual tiene `DiskBase::NotApplicable`. Se conserva en el
  store/snapshot, pero sin mapping explícito no se enumera como módulo ni
  satisface imports.
- La asociación `ProjectId` es metadata editorial. La identidad semántica
  continúa siendo `ProjectPlan`/`PackageKey`/`SourceUnitKey` del loader.
- Cambios notificados en manifest, lock o cualquier path del workspace
  incrementan la revisión y vuelven stale los resultados anteriores. No se
  ejecutan `sync`, `update`, `add`, `remove`, `publish`, red ni escrituras.
- Las lecturas de disco no prometen atomicidad transaccional entre archivos.
  `DiskSourceProvider` detecta cambios observables durante una lectura; el
  resultado guarda además el fingerprint exacto de cada lectura externa.

## 3. Integración canónica

`AnalysisSnapshot::discover` llama directamente a
`discover_catalog_with_provider`. Los tests cubren entry modificado, módulos de
disco, overlay importado directo y transitivo, dos overlays simultáneos,
imports agregados/eliminados, alias, cambio de declaración `package` y cierre
con restauración de disco.

El único ajuste al loader permite que un entry ausente en disco sea aceptado
cuando el provider sí puede leerlo. Para `DiskSourceProvider` se conserva el
diagnóstico batch anterior de entry inexistente.

## 4. Límites

La carga/validación read-only de locks sigue siendo responsabilidad del
frontend de packages que construye el `ProjectPlan`; no se duplicó parser ni
resolver en analysis. Este milestone tampoco implementa LSP/JSON-RPC,
cancelación, UTF-16, diagnostics editoriales, completion, hover, rename ni
índice de símbolos.

## 5. Qualification

Las pruebas focales viven junto a `aether-analysis` y no dependen de sleeps.
Cubren identidad, versionado, transiciones válidas e inválidas, versiones de
cliente regresivas, save verificado, prioridad de overlay, transitividad,
topología, virtuales, toolchain inmutable, borrado, snapshots inmutables,
stale/source-changed, symlinks, orden determinista y ausencia de escrituras.

Resultados:

- `cargo check --workspace`: PASS.
- `cargo test --workspace -j 1`: PASS, incluidas suites canónicas de
  módulos/packages, driver batch y doc-tests.
- `cargo fmt --all --check`: PASS.
- `cargo clippy --workspace --all-targets -j 1`: PASS; conserva únicamente
  warnings preexistentes fuera de `aether-analysis`.
- `git diff --check`: PASS.
- `compiler-next/tests/run-differential.sh`: PASS, 96/96 casos.
- `cargo tree -p aether-analysis --depth 2`: sólo `aether-frontend`,
  `aether-package`, `sha2` y dependencias transitivas de hashing; no driver,
  middle, backend, LLVM ni legacy.

## 6. Reconciliación de cierre

`EDITOR-DIAGNOSTICS-V1` volvió a comprobar las condiciones de este milestone
antes de consumirlo. El store, el snapshot, la prioridad de overlays
transitivos, el loader compartido, la supresión stale y la frontera de
dependencias siguen cubiertos por las pruebas focales. No fue necesario ampliar
ni corregir la implementación de overlays para declarar este cierre.
