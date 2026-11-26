# DOCUMENT-SYMBOLS-V1 — reporte de implementación y qualification

Estado: **CLOSED**, 2026-11-26.

Arquitectura de origen:
[EDITOR_SYMBOL_SERVICES_ARCH_1](EDITOR_SYMBOL_SERVICES_ARCH_1.md).
Instrumentación de origen:
[SYMBOL_SOURCE_MAPPING_V1_REPORT](SYMBOL_SOURCE_MAPPING_V1_REPORT.md).

## 1. API implementada

`aether-analysis` exporta una consulta interna, independiente del protocolo:

```rust
impl SemanticSnapshot {
    pub fn document_symbols(&self, source: SourceId) -> DocumentSymbolResult;
}
```

`AnalysisResult::document_symbols` aplica primero el gate `Complete + Valid` y comprueba que
el snapshot semántico corresponda al mismo `SnapshotStamp`. La variante equivalente sobre
`RequestCompletion` aplica además el estado terminal de publicación, por lo que un resultado
`Stale`, `Cancelled`, `TargetClosed`, `SourceChanged` o `InternalFailure` nunca expone hechos
viejos ni se convierte en una lista vacía.

No se agregó handler `textDocument/documentSymbol`, capability LSP ni mapping a tipos del
protocolo.

## 2. Modelo de resultados

`DocumentSymbolResult` separa:

- `Available(Vec<DocumentSymbol>)`, donde `Available([])` significa que un source válido no
  tiene declaraciones instrumentadas;
- `Unavailable(DocumentSymbolsUnavailable)`, con razones explícitas para análisis parcial o
  inválido, snapshot stale, cancelación, target cerrado, cambio externo, fallo interno,
  `SourceId` inexistente y source no editable.

Cada `DocumentSymbol` conserva:

- `CompilerEntityId` autoritativo y `SnapshotStamp` que limita su significado;
- nombre exacto y categoría interna `Function`, `Struct` o `Enum`;
- módulo propietario y `LogicalDeclarationKey` oficial cuando existe;
- `SourceIdentity`, `SourceUnitKey`, `DocumentVersion`, editabilidad, full/selection spans y
  sus rangos UTF-16 derivados;
- `children`, vacío en V1 pero apto para ownership instrumentado posterior.

No se asignaron IDs persistentes ni IDs editoriales alternativos. Las funciones sobrecargadas
mantienen sus entidades oficiales distintas; el nombre no se usa como clave.

## 3. Cobertura exacta

La consulta incluye exclusivamente hechos `DeclarationFact` validados de:

- funciones top-level source-facing;
- structs top-level;
- enums top-level.

No incluye imports, aliases, fields, variants, type parameters, parámetros, locals, clases,
interfaces, métodos ni lambdas/sentinels/wrappers sintéticos. Estas categorías requieren
instrumentación frontend oficial posterior. No se inventan `children` para ellas.

## 4. Estructura de jerarquía

Las tres categorías V1 se devuelven en la raíz y con `children: []`. El modelo conserva la
identidad del módulo owner y admite agregar relaciones owner/child sin cambiar la ubicación,
identidad ni categoría de las declaraciones actuales.

No se acopló el modelo a `DocumentSymbolKind` ni a otra representación LSP.

## 5. Política de snapshots

Los IDs densos permanecen snapshot-locales. Cada resultado lleva el stamp exacto y se
materializa sólo desde el `SemanticFacts`, `SourceTable` y `TypedHir` que ya fueron unidos por
`SemanticSnapshot`.

Una edición de overlay produce un stamp y una versión nuevos; la consulta devuelve las
posiciones del contenido nuevo. `RequestCompletion` rechaza explícitamente resultados stale,
cancelados o no publicables. No existe fallback a un snapshot anterior.

## 6. Estados `Unavailable`

La consulta semántica sólo se habilita para `AnalysisCoverage::Complete` más
`AnalysisValidity::Valid`. Parse, declarations, typing o verificación fallidos retornan
`AnalysisUnavailable` con su `AnalysisState` exacto. Los estados de lifecycle se preservan
como razones distintas.

Un `SourceId` ausente retorna `SourceNotFound`. Un source compiler-owned/toolchain retorna
`SourceNotEditable` en este milestone. Una inconsistencia imposible después del validador de
facts falla cerrada como `InternalFailure`.

## 7. Source mapping

No se recorta texto ni se busca el nombre. Full span y selection span vienen directamente del
fact oficial. La consulta filtra por `fact.source == requested_source`, verifica containment y
source y usa exclusivamente `SnapshotSource::line_index.span_to_range` para UTF-8/UTF-16.

La ubicación conserva `SourceIdentity`, unidad lógica y versión documental del mismo registro
de `SourceTable`. Declaraciones importadas sólo aparecen al consultar su source propietario.

## 8. Orden y tests

El orden es determinista por `(SourceId, full_span.start, selection_span.start,
CompilerEntityId)`. No depende de hash maps y no deduplica por nombre.

Los siete tests focales agregados cubren conjuntamente los 22 casos solicitados:

- una y varias funciones, overloads, genéricos y exclusión de sintéticos;
- structs, enums, identidad y claves oficiales;
- mismo nombre en módulos distintos, imports y múltiples archivos;
- source válido sin declaraciones, diferenciado de `Unavailable`;
- overlay no guardado, cambio de posiciones, stamps y versiones;
- Unicode, UTF-16, LF/CRLF, full/selection ranges y containment;
- orden repetible;
- `SourceId` inválido y source toolchain no editable;
- error sintáctico y error semántico sin hechos viejos;
- stale, cancelación, target cerrado, source cambiado y fallo interno.

El caso “documento sin declaraciones” usa una unidad importada válida con sólo su declaración
`package`: un entry point standalone vacío no puede producir `Complete + Valid` porque el
contrato del lenguaje exige `main`. Los estados terminales se prueban directamente sobre
`RequestCompletion`; los tests existentes de lifecycle ejercitan además su producción real
durante edición, cancelación, cambios externos y pánico recuperado.

## 9. Qualification

Ejecutada el 2026-11-26:

- focales `aether-analysis::symbols`: PASS — 7/7;
- `cargo test -p aether-frontend`: PASS — 98 unit + 2 integration;
- `cargo test -p aether-analysis`: PASS — 47/47;
- `cargo test -p aether-lsp`: PASS — 4 unit + 5 integration;
- `cargo check --workspace`: PASS;
- `cargo test --workspace -j 1`: PASS;
- `cargo fmt --all --check`: PASS;
- `cargo clippy --workspace --all-targets -j 1`: PASS con warnings preexistentes del
  workspace; los dos warnings inicialmente detectados en tests nuevos se corrigieron y el
  focal final de clippy no reporta warnings nuevos;
- `cargo tree -p aether-analysis --edges normal`: PASS; sin dependencia nueva ni legacy;
- `bash tests/test-differential-harness.sh`: PASS;
- `bash tests/run-differential.sh`: PASS — `mode=official checked=96 failures=0`;
- `git diff --check`: PASS en el gate final.

## 10. Limitaciones

La vista syntax-only de AST actual permanece pendiente porque el snapshot no retiene todavía
un AST completo publicable para análisis inválido. No se implementó recovery ni parsing
adicional. Miembros y categorías futuras sólo podrán aparecer cuando el frontend emita su
identidad, ownership y spans oficiales.

No se agregaron firmas textuales, resolución de nombres, reference facts, navegación, hover,
completion, rename ni indexado de scopes.

## 11. Archivos modificados

- `compiler-next/crates/aether-analysis/src/symbols.rs`
- `compiler-next/crates/aether-analysis/src/lib.rs`
- `docs/architecture/DOCUMENT_SYMBOLS_V1_REPORT.md`

Los cambios personales preexistentes en `examples/ProbandoNR`, locks, binarios y temporales se
preservaron sin edición, staging ni limpieza.

## 12. Commit sugerido

`feat(analysis): add snapshot-local document symbols query`

No se realizó commit ni push.

## 13. Cierre

La consulta consume sólo hechos oficiales, filtra por source propietario, conserva identidad y
rangos exactos, ordena determinísticamente y falla cerrada para snapshots o análisis no
publicables. Los overlays usan el snapshot actual y no se inventan miembros ni identidades.
No se modificaron capabilities ni handlers LSP y el diferencial oficial permanece 96/96.

Por ello `DOCUMENT-SYMBOLS-V1` queda **CLOSED**. No se inicia el milestone siguiente.
