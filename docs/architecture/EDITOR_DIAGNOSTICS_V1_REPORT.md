# EDITOR-DIAGNOSTICS-V1 — reporte

Estado: **CLOSED; IMPLEMENTADO Y RECALIFICADO**, 2026-11-25.

Este milestone agrega el primer servicio de diagnósticos editoriales nativo de
`compiler-next`. No agrega LSP, MIR, SSA, backend ni ejecución de toolchain.

## 1. Implementación y fronteras

- `SourceTable` conserva el mapeo snapshot-local de `SourceId` a
  `SourceIdentity`, `DocumentVersion` cuando corresponde, `SourceUnitKey`,
  texto exacto, fingerprint e índice de líneas.
- `CompilationSession` conserva provenance y fingerprint de los bytes
  efectivamente parseados. Los imports con overlay mantienen el `DocumentId`
  del documento importado; toolchain y disco conservan sus identidades propias.
- `LineIndex` convierte offsets UTF-8 y posiciones UTF-16 en ambos sentidos,
  valida boundaries, surrogate pairs, EOF, LF, CRLF y rangos half-open sin
  normalizar el texto.
- `EditorDiagnostic` preserva código, severidad explícita, fase, categoría,
  mensaje, source display, related information y fix-its. Un fix inválido se
  omite individualmente y queda registrado como `AdaptationFailure`; un
  `SourceId` primario desconocido es un fallo interno.
- `CanonicalAnalyzer` acepta targets documento, proyecto o path, usa el
  `OverlaySourceProvider` del snapshot y el loader compartido, ejecuta
  declarations, `analyze_bodies_for_target` y `verify_hir`.
- `AnalysisState` separa cobertura y validez. Sólo frontend completo con HIR
  verificado produce `Complete + Valid` y `SemanticSnapshot`; los errores que
  detienen lexing, parsing, declarations o semántica producen
  `Partial + Invalid`.

El recorrido conserva el lexer oficial y el parser fail-fast. No fabrica AST
parcial, no analiza bodies después de un fallo requerido, no relaja ownership
y no omite `verify_hir`. `aether-analysis` depende sólo de `aether-frontend`,
`aether-package`, `sha2` y las dependencias transitivas de hashing; no depende
de driver, middle, backend, LLVM ni código legacy.

## 2. Preflight y preservación

- Branch `main`; `HEAD` y `origin/main` coincidían en
  `eec746d53520a161bdec27497f6789a632eb73f9`.
- Se inspeccionaron status, diffs staged/unstaged y untracked antes de actuar.
  El worktree ya contenía la implementación del milestone, reportes y archivos
  personales bajo `examples/ProbandoNR`, locks locales, binarios y reproducers.
- No se ejecutó reset, clean, stash, commit ni push. No se modificó ni eliminó
  ningún archivo personal.
- `EDITOR_DOCUMENT_OVERLAY_V1_REPORT.md` conserva su estado
  `CLOSED; IMPLEMENTADO Y RECALIFICADO` y su evidencia histórica 96/96.
- La única modificación de código de esta qualification agrega tests dentro de
  `aether-analysis`; no cambia funcionalidad productiva.

## 3. Evidencia histórica conservada

La primera qualification había obtenido `cargo check --workspace`, 22/22 de
`aether-analysis`, clippy, fmt, `git diff --check` y la frontera de dependencias
en PASS. Su `cargo test --workspace -j 1` avanzó correctamente hasta
`registry::linear_algebra_oal_publishes_and_runs_real_qr_consumer`, imprimió la
salida del consumidor y fue interrumpido varios minutos después. Por ello esa
ejecución original sigue registrada como **incompleta**, no como PASS. Tampoco
había evidencia entonces de una ejecución oficial del diferencial de 96 casos.

## 4. Matriz requisito → test → resultado

| Requisito | Evidencia y assertions comprobadas | Resultado |
| --- | --- | --- |
| UTF-8/UTF-16, astrales y CRLF | `line_index_round_trips_unicode_and_crlf`: round-trip sólo en boundaries UTF-8, emoji de dos code units, combining mark, CJK, CRLF y comienzo de segunda línea | PASS |
| Posiciones inválidas | `line_index_rejects_invalid_bytes_and_positions`: mid-codepoint, offset fuera de rango, mid-surrogate y línea inexistente | PASS |
| `SourceId` desconocido | `diagnostic_adaptation_rejects_unknown_primary_source_and_omits_invalid_fix`: exige `AnalysisFailure::Internal` y el ID 99 en el mensaje | PASS |
| `FixIt` inválido | mismo test: el fix fuera de rango no se publica y produce exactamente `AdaptationFailure::InvalidFix` para `E9999` | PASS |
| Import diagnostics con overlays | `imported_overlay_diagnostic_keeps_imported_document_identity`: exige que el diagnóstico semántico apunte al `DocumentId` del import no guardado | PASS |
| Error léxico | `analyzer_distinguishes_lexical_and_semantic_ownership_failures`: string sin terminar, fase `Lex`, `Partial(FrontendStopped) + Invalid`, sin semantic snapshot | PASS |
| Error sintáctico | `analyzer_returns_structured_parse_error_for_unsaved_overlay`: overlay inválido, severidad Error, identidad/rango editoriales, estado parcial inválido y sin semantic snapshot | PASS |
| Error semántico y ownership | `analyzer_distinguishes_lexical_and_semantic_ownership_failures`: use-after-move `E0291`, fase `Semantic`, `Partial(FrontendStopped) + Invalid`; `vertical11_aggregate_ownership_diagnostics_fail_closed` cubre la matriz canónica de rechazos | PASS |
| HIR verificado | `analyzer_qualifies_only_verified_frontend_as_complete_valid` sólo obtiene semantic snapshot después del camino que llama `verify_hir`; las suites de frontend y driver vuelven a probar corrupciones HIR fail-closed | PASS |
| `Complete + Valid` | `analyzer_qualifies_only_verified_frontend_as_complete_valid`: igualdad exacta de cobertura/validez, semantic snapshot y source identity | PASS |
| `Partial + Invalid` | tests léxico, parse y ownership anteriores verifican las rutas y ausencia de semantic snapshot | PASS |
| Stale results | `snapshots_are_immutable_and_stale_results_are_deterministic`: el snapshot conserva texto anterior y `may_publish` retorna exactamente `Stale` | PASS |
| Error interno de adaptación | el caso de `SourceId(99)` exige error interno y nunca lo presenta como diagnóstico válido | PASS |
| Módulos/packages/diagnostics | `module_std_v1`, `package_ergonomics_v1`, `multi_file_diagnostics_are_structured_and_keep_source_provenance` y suites de package dentro de driver/workspace | PASS |

La auditoría encontró cuatro rutas sin assertion directa en los 22 tests
originales: source primario desconocido, fix inválido, parada léxica y rechazo
ownership con estado exacto. Se agregaron dos tests focales que cubren esas
rutas sin ampliar la implementación; `aether-analysis` queda en 24/24.

## 5. Investigación del test QR

El nombre corresponde al integration test
`aether-registry/tests/registry.rs::linear_algebra_oal_publishes_and_runs_real_qr_consumer`.
Se ejecutó con filtro `--exact`, `-j 1`, `--nocapture` y timeout diagnóstico de
900 segundos. No se modificaron OAL, registry, expectativas ni cobertura.

Resultados reproducidos:

- aislamiento inicial: PASS, 1/1, 701,84 s;
- ejecución dentro del workspace: PASS, suite registry 5/5, test QR 699,32 s;
- repetición instrumentada para telemetría: PASS, 1/1, 699,35 s.

La prueba publica `linearAlgebra`, materializa el consumer real y ejecuta O0 y
O2. O0 emitió la salida completa aproximadamente a los 4:30; O2 emitió la misma
salida al final. Durante muestras periódicas el proceso de test mantuvo
99,4–99,7% de CPU, RSS aproximado entre 182 y 236 MiB, tres descriptores
abiertos y actividad continua. `cargo` permaneció esperando al hijo normal; no
se observaron hijos bloqueados, acumulación de pipes/handles ni espera ociosa.
El target tenía 113 GiB libres y `/tmp` 7,5 GiB libres (1% usado) durante toda
la ejecución. El comportamiento es un test CPU-bound de unos 11:40, no un
bloqueo; la interrupción histórica ocurrió antes de su duración normal.

## 6. Qualification focal y oficial

- `cargo test -p aether-analysis`: PASS, 24/24 más doc-tests.
- `cargo test -p aether-driver`: PASS de toda la suite; incluye `vertical`
  220/220, módulos, packages, diagnostics, ownership y verificadores.
- `bash compiler-next/tests/test-differential-harness.sh`: PASS. Comprueba que
  el gate oficial no invoca Python/legacy y funciona sin árbol `compiler-rs`.
- `bash compiler-next/tests/run-differential.sh`: PASS,
  `mode=official checked=96 failures=0`.
- No se modificó el manifest, ninguna expectativa ni la cobertura diferencial.

## 7. Workspace y otros gates

- `cargo test --workspace -j 1`: PASS completo, sin filtros, incluidas todas las
  suites de integración, registry QR y doc-tests. El timeout diagnóstico global
  de 2400 s no se alcanzó.
- `cargo check --workspace`: PASS.
- `cargo fmt --all --check`: PASS.
- `cargo clippy --workspace --all-targets -j 1`: PASS con warnings
  preexistentes fuera de `aether-analysis`; el crate no agrega warnings.
- `git diff --check`: PASS.
- `cargo tree -p aether-analysis --depth 2`: sólo `aether-frontend`,
  `aether-package`, `sha2` y hashing transitivo; sin dependencias legacy.

## 8. Cierre

La implementación conserva sus contratos, la cobertura crítica está
calificada, los gates focales y globales pasan, el diferencial oficial termina
96/96, y no quedan limitaciones abiertas para este milestone. Por lo tanto
`EDITOR-DIAGNOSTICS-V1` queda **CLOSED**. Este cierre no inicia cancelación ni
LSP.
