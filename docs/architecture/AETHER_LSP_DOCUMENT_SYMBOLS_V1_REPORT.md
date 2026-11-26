# AETHER-LSP-DOCUMENT-SYMBOLS-V1 — reporte de implementación y qualification

Estado: **CLOSED**, 2026-11-26.

Arquitectura y milestones de origen:
[EDITOR_SYMBOL_SERVICES_ARCH_1](EDITOR_SYMBOL_SERVICES_ARCH_1.md),
[SYMBOL_SOURCE_MAPPING_V1_REPORT](SYMBOL_SOURCE_MAPPING_V1_REPORT.md),
[DOCUMENT_SYMBOLS_V1_REPORT](DOCUMENT_SYMBOLS_V1_REPORT.md),
[DOCUMENT_SYMBOLS_STRUCTURAL_COVERAGE_V1_REPORT](DOCUMENT_SYMBOLS_STRUCTURAL_COVERAGE_V1_REPORT.md)
y
[AETHER_LSP_RUST_INTEGRATION_HARDENING_V1_REPORT](AETHER_LSP_RUST_INTEGRATION_HARDENING_V1_REPORT.md).

## 1. Handler implementado

`aether-lsp` implementa `textDocument/documentSymbol` como request JSON-RPC con ID. El reader
valida y agenda la operación, pero no espera el análisis: un hilo de finalización espera el
`RequestHandle` y entrega exactamente una respuesta por el writer único.

El handler no parsea, no resuelve nombres y no construye un índice paralelo. Ejecuta el análisis
canónico sobre el snapshot capturado por `AnalysisScheduler`, resuelve el `SourceId` solicitado en
el `SourceTable` de ese mismo resultado y adapta exclusivamente
`RequestCompletion::document_symbols` / `SemanticSnapshot::document_symbols`.

## 2. Capability

`initialize` anuncia `"documentSymbolProvider": true`. Las capabilities previas de UTF-16 y full
text sync permanecen iguales. No se anuncian hover, completion, definition, references, rename,
semantic tokens ni workspace symbols.

## 3. Adaptación de `SymbolKind`

| Categoría interna | `SymbolKind` LSP |
| --- | --- |
| `Function` | `Function` (12) |
| `Struct` | `Struct` (23) |
| `Enum` | `Enum` (10) |
| `Field` de struct o class | `Field` (8) |
| `Variant` | `EnumMember` (22) |
| `Class` | `Class` (5) |
| `Method` | `Method` (6) |
| `Initializer` | `Constructor` (9) |
| `Interface` | `Interface` (11) |
| `Requirement` | `Method` (6) |

No se agregan `detail`, firmas, tipos, documentación, tags ni metadatos inexistentes.

## 4. Jerarquías y rangos

La respuesta usa `DocumentSymbol[]`, no `SymbolInformation[]`. Cada valor conserva nombre exacto,
kind, `range`, `selectionRange` y `children`. El orden de roots y children es el orden fuente ya
validado por analysis.

Los rangos provienen de los `full_range` y `selection_range` materializados por el `LineIndex` del
snapshot. Por tanto conservan spans half-open y posiciones UTF-16 exactas para Unicode, combining
marks, emoji y CRLF. El adaptador LSP nunca busca el spelling dentro del texto.

Inicializadores implícitos, wrappers, lambdas, witnesses, virtual slots, Core sin ubicación y
nombres sintéticos `$...` siguen excluidos por los facts oficiales.

## 5. Resolución documental

- Un documento abierto se identifica por `SourceIdentity::Document(DocumentId)`; su overlay y su
  `DocumentVersion` pertenecen al snapshot analizado.
- Un documento cerrado existente se analiza desde disco y se identifica por el path canónico de
  `SourceIdentity::Disk`.
- En un proyecto válido se analiza el entry canónico con el `ProjectId` y plan oficiales; un
  miembro sólo puede resolverse si aparece realmente en el catálogo de ese análisis.
- Un URI no `file:` recibe `InvalidParams` (`-32602`).
- Un path fuera del workspace, inexistente, no alcanzable desde el proyecto o sin source en el
  snapshot recibe `RequestFailed` (`-32803`).
- Un lock/proyecto no disponible recibe `RequestFailed`; no cae a análisis standalone.

No se convierte el URI directamente a `SourceId`, no se reutiliza un source histórico y no se
reconstruyen imports desde texto.

## 6. Lifecycle y cancelación

Las requests pendientes se indexan por su ID JSON-RPC y conservan el `CancellationToken` del
scheduler. `$/cancelRequest` cancela ese token; el resultado protocolario es `RequestCancelled`
(`-32800`). Una edición, close, cambio de generación o source externo que invalida el snapshot
produce `ContentModified` (`-32801`) y nunca símbolos viejos.

El gate de publicación del scheduler valida revision, versiones, generación de proyecto,
fingerprints de disco, target vigente y cancelación antes de entregar un resultado. Shutdown
cancela todos los tokens pendientes, detiene ordenadamente el scheduler y responde las requests
canceladas; el reader no queda bloqueado por análisis prolongado.

Panic/fallo interno, resultado ausente o corrupción de adaptación producen `InternalError`
(`-32603`). IDs duplicados o IDs de tipo inválido se rechazan como `InvalidRequest` (`-32600`).

## 7. Política de análisis no disponible

Sólo `Complete + Valid` con `SemanticSnapshot` y stamp concordante puede producir símbolos. Un
documento válido sin declaraciones responde éxito con `[]`. Parse, declarations o semantic
incompletos/inválidos responden `RequestFailed` (`-32803`); nunca se confunden con éxito vacío ni
se sustituyen por el snapshot válido anterior.

## 8. Overlays

El análisis se agenda sobre un `AnalysisSnapshot` del workspace. Los overlays abiertos ganan sobre
disco sin archivos temporales; ediciones sucesivas avanzan revision/version y actualizan nombres,
rangos y children. Close invalida el overlay y cualquier request anterior; una request posterior
puede analizar el contenido real de disco. La identidad de un import abierto continúa siendo su
`DocumentId` dentro del `SourceTable` oficial.

## 9. Tests protocolarios

Los tests contra el binario Rust real por stdio comprueban:

- capability y correlación del ID JSON-RPC;
- funciones, structs/campos, enums/variantes, classes/campos/métodos/initializer e
  interfaces/requirements;
- herencia y override sin símbolos sintéticos;
- estructura exacta de name/kind/range/selectionRange/children;
- UTF-16, Unicode y CRLF;
- orden fuente determinista;
- overlay no guardado, cambio de posiciones y contenido de disco después de close;
- análisis inválido distinto de vacío;
- cambios rápidos, stale, cancelación explícita y shutdown con request pendiente;
- proyecto con lock inválido y métodos desconocidos.

Las suites de `aether-analysis` conservan además cobertura de imports abiertos, owners exactos,
miembros homónimos, stamps, source inexistente/no editable, facts corruptos y lifecycle completo.

## 10. Qualification

Ejecutada el 2026-11-26 sobre el árbol final:

- `cargo test -p aether-frontend`: PASS — 98 unit + 2 integration;
- `cargo test -p aether-analysis`: PASS — 49/49;
- `cargo test -p aether-lsp`: PASS — 4 unit + 8 stdio;
- `cargo check --workspace`: PASS;
- `cargo test --workspace -j 1`: PASS, incluidas suites y doc-tests; el test registry/OAL más
  largo terminó en 718,64 s;
- `cargo fmt --all --check`: PASS;
- `cargo clippy --workspace --all-targets -j 1`: PASS con warnings preexistentes en frontend,
  middle, CLI y tests ajenos; el cambio LSP quedó sin warnings propios tras el focal;
- `cargo clippy -p aether-lsp --all-targets -j 1`: PASS, sólo el warning preexistente de la
  dependencia frontend;
- `bash tests/test-differential-harness.sh`: PASS;
- `bash tests/run-differential.sh`: PASS — `mode=official checked=96 failures=0`;
- VS Code `npm test`: PASS — 4/4;
- IntelliJ `./gradlew -p tools/intellij-aether test`: PASS — build successful, task test;
- `git diff --check`: PASS.

No se realizó smoke GUI manual; se mantiene separado de las pruebas automatizadas anteriores.

## 11. Limitaciones

- Sólo se aceptan URI `file:` dentro del workspace.
- El frontend sigue siendo fail-closed: no hay Document Symbols parciales después de errores.
- Un archivo de proyecto cerrado debe pertenecer al catálogo alcanzable desde el entry canónico.
- El servidor conserva full text sync y no implementa watched files; cambios de manifest/lock se
  revalidan en la siguiente operación documental/request que refresca el proyecto.
- No se agregaron parser recovery, workspace symbol search ni otros servicios editoriales.

## 12. Procedimiento manual de VS Code

1. Desde `compiler-next`, ejecutar `cargo build -p aether-lsp`.
2. Configurar temporalmente `aether.lsp.executable` con
   `compiler-next/target/debug/aether-lsp` y abrir un archivo/proyecto Aether.
3. Abrir Outline o usar “Go to Symbol in Editor”; verificar roots y members anidados.
4. Agregar/quitar campos, variantes o métodos sin guardar y verificar actualización de nombres y
   posiciones.
5. Introducir un error sintáctico: la request debe fallar, no mostrar el outline anterior como
   vigente. Corregirlo y verificar la jerarquía nueva.
6. Probar un archivo con emoji/acentos antes de declaraciones y comprobar selección exacta.
7. Cerrar/reabrir el archivo para comprobar la transición overlay/disco.
8. Restaurar la preferencia temporal; no se cambió ningún default del repositorio.

## 13. Archivos modificados

Cambios propios de este milestone:

- `compiler-next/crates/aether-lsp/src/lib.rs`;
- `compiler-next/crates/aether-lsp/tests/protocol.rs`;
- `docs/architecture/AETHER_LSP_DOCUMENT_SYMBOLS_V1_REPORT.md`.

Se preservaron sin revertir, incluir ni reinterpretar todos los cambios personales preexistentes en
frontend, analysis, ejemplos y archivos untracked. No se ejecutaron reset, clean, stash, commit ni
push.

## 14. Commit sugerido

`feat(lsp): add hierarchical document symbols`

## 15. Cierre

Document Symbols usa exclusivamente facts semánticos y source mapping oficiales, devuelve una
jerarquía LSP con rangos UTF-16 exactos, conserva owners/identidades del snapshot y observa overlays,
stale, cancelación, errores y shutdown sin publicar resultados obsoletos. Toda la qualification
solicitada pasó.

Por ello `AETHER-LSP-DOCUMENT-SYMBOLS-V1` queda **CLOSED**.
