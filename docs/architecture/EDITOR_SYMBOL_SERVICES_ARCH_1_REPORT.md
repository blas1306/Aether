# EDITOR-SYMBOL-SERVICES-ARCH-1 — reporte de arquitectura

Estado: **ARCH CLOSED; IMPLEMENTACIÓN NO INICIADA**, 2026-11-26.

Documento normativo:
[EDITOR_SYMBOL_SERVICES_ARCH_1](EDITOR_SYMBOL_SERVICES_ARCH_1.md).

## 1. Preflight y preservación

- Branch: `main`.
- HEAD: `961427e6fb71ac5aad94c4e4a8658a0c248d93bd`.
- `origin/main`: `961427e6fb71ac5aad94c4e4a8658a0c248d93bd`; sin divergencia al inspeccionar.
- El status inicial contenía cambios tracked personales en
  `examples/ProbandoNR/probandoNR2.ae` y `probandoNR3.ae`.
- También contenía locks, binarios y reproducers untracked bajo `examples/ProbandoNR`,
  `examples/assessment`, `probandoNR3C` y `tmp_lambda_test.ae`, además de ignored bajo
  `scrap/`, targets, IDEs, caches y temporales.
- No había cambios staged. La configuración local sólo contenía los datos normales del repo,
  remote/branch y merge base de VS Code.
- No se ejecutaron reset, clean, stash, commit ni push. Ningún archivo personal fue editado,
  movido o eliminado.

## 2. Evidencia inspeccionada

Se leyeron:

- `COMPILER_AUTHORITY.md` y `EDITOR_ANALYSIS_FOUNDATION_ARCH_1.md`;
- reportes CLOSED de canonical loader, document overlay, editor diagnostics y request
  lifecycle;
- `AETHER_LSP_RUST_DIAGNOSTICS_V1_REPORT.md` y
  `AETHER_LSP_RUST_INTEGRATION_HARDENING_V1_REPORT.md`;
- contratos y reportes actuales de modules/std, package identity/manager/ergonomics,
  function values, generic local inference, borrow ergonomics y OOP;
- manifests y fuentes de `aether-frontend`, `aether-analysis` y la frontera LSP existente.

La auditoría de código cubrió especialmente:

- `ast.rs`, `parser.rs`, `lexer.rs`, `diagnostic.rs`;
- `hir.rs`, `types.rs`, `oop.rs`, `interfaces.rs`, `core.rs`;
- `aether-analysis::{lib,editor,diagnostics,lifecycle}.rs`;
- APIs de `SemanticSnapshot`, `SourceTable`, `LineIndex`, snapshots, overlays y publicación.

## 3. APIs existentes confirmadas

- El lexer conserva tokens y spans exactos, pero `ParsedAst` no retiene la lista de tokens.
- El parser es fail-fast y sólo entrega AST completo; no entrega syntax tree parcial.
- `ParsedProgram` conserva `ModuleInfo`, `SourceUnitKey`, source e imports resueltos.
- `FunctionSignature::symbol_key` construye el `SymbolKey` oficial y contempla
  `overload_disambiguator`.
- `TypedHir` expone modules, aliases, structs, enums, signatures, generic/concrete
  functions, instances, closure environments y `TypeArena`.
- HIR conserva targets semánticos importantes: `LocalId`, `HirCallTarget`, `FieldId`,
  `VariantId`, nominal IDs, class method targets y interface requirements.
- `BindingId` identifica bindings source dentro de una función y es usado por captures.
- `SourceTable` une cada `SourceId` con `SourceIdentity`, `DocumentVersion`,
  `SourceUnitKey`, texto, fingerprint y `LineIndex` del mismo snapshot.
- `AnalysisResult.semantic` sólo existe en `Complete + Valid`; errores de frontend actuales
  producen `Partial + Invalid` sin semantic snapshot.
- El scheduler y el LSP ya descartan cancelado, stale, target cerrado y source cambiado.

## 4. Información faltante confirmada

La mayor parte de las declaraciones AST/HIR conserva sólo el span completo. No hay
`name_span` uniforme para funciones, parámetros, locales, aliases, imports, structs, enums,
variants, classes, interfaces y methods. `AstExprKind::Field` sí es una excepción útil con
`name_span`; match bindings también conservan spans individuales.

Las expresiones `Name` suelen tener un span preciso, pero calls y nombres calificados
conservan strings y el span de la expresión completa, no spans uniformes para callee,
qualifier y member. En HIR, un place/call contiene la identidad resuelta, pero projections y
targets no conservan siempre el fragmento source que los originó.

Los scopes y tablas de lookup existen durante collection/typing, pero no sobreviven como
artefacto consultable. Tampoco existe una tabla general de `reference span -> resolved
identity`, un reverse reference index, doc comments oficiales ni una API para validar
conflictos de rename.

Clases e interfaces poseen metadata nominal rica. Sin embargo, algunos methods se conectan
mediante `FunctionId` y metadata sin un span propio completo; su ubicación debe seguir la
firma y requiere una relación source-facing explícita. Slots virtuales y witnesses son
metadata de dispatch, no símbolos de usuario.

## 5. Decisiones tomadas

1. Los hechos se capturan en el frontend oficial durante la resolución; no se infieren por
   regex, spelling o un segundo resolver.
2. El servicio reside en `aether-analysis::symbols`; no se crea un crate ni framework de
   queries nuevo.
3. `SymbolId` y `ReferenceId` son snapshot-local. Los IDs densos del compilador quedan
   encapsulados en el mismo snapshot.
4. Sólo se declara identidad lógica donde `PackageKey`, `SourceUnitKey` o `SymbolKey`
   oficiales la demuestran. Locales/members sin clave oficial no reciben una falsa.
5. `SourceTable` y `LineIndex` son la única ruta de source mapping y UTF-16.
6. Se separan facts semánticos de Markdown/LSP presentation.
7. Document Symbols es el primer servicio, después de un milestone de spans/facts.
8. Completion sobre source inválido queda bloqueado por recovery/context detection oficial.
9. References declara cobertura; Rename queda prohibido hasta cobertura exhaustiva y
   validación de colisiones.

## 6. Alternativas rechazadas

- Indexar nombres desde AST o texto: no respeta shadowing, imports, overloads ni dispatch.
- Recorrer HIR y buscar el spelling dentro de spans amplios: pierde la relación exacta y es
  ambiguo con comentarios, Unicode o nombres repetidos.
- Convertir `FunctionId`, `TypeId`, `LocalId` o `FieldId` en IDs persistentes: son arenas
  densas de sesión.
- Usar URI/path como identidad de símbolo: contradice packages/source units y aliases.
- Extender `SymbolKey` unilateralmente para cada local/member: rompería el contrato oficial.
- Mantener un índice semántico independiente: duplicaría resolución y podría divergir.
- Servir HIR histórico como actual durante errores: viola versiones/snapshots.
- Implementar todos los servicios y handlers en un único milestone: impediría calificar
  spans, identidad, recovery y cobertura por separado.
- Agregar Salsa/Tower/Tokio u otra dependencia: no hay necesidad demostrada.

## 7. Plan y primer milestone

La secuencia cerrada es:

1. SYMBOL-SOURCE-MAPPING-V1;
2. DOCUMENT-SYMBOLS-V1;
3. SYMBOL-RESOLUTION-QUERIES-V1;
4. GO-TO-DEFINITION-V1;
5. HOVER-V1;
6. COMPLETION-CONTEXT-RECOVERY-V1;
7. COMPLETION-V1;
8. REFERENCES-V1;
9. RENAME-VALIDATION-V1;
10. RENAME-V1.

El primer milestone recomendado agrega spans exactos y `SemanticFacts` en el frontend,
validación source/owner e integración owned con el snapshot. No anuncia capabilities ni
implementa handlers.

## 8. Qualification de esta arquitectura

No se ejecutaron suites Rust ni diferencial porque este milestone prohíbe modificar código
productivo y los entregables son exclusivamente documentos. Sí se ejecutaron inspecciones
read-only de Git y del código. Los gates documentales (`git diff --no-index --check` para
cada archivo nuevo, revisión final de status y comprobación de archivos) terminaron en PASS.

Los tests propuestos por milestone están definidos en §15 del documento normativo y separan
frontend, API editorial y protocolo. Incluyen identidad, spans, scopes/shadowing, imports,
aliases, packages, locals/parámetros, fields/methods, structs/classes/interfaces, enums,
generics, closures, cross-file, UTF-16, overlays, stale, partial, determinismo y frontera de
dependencias legacy.

## 9. Riesgos y limitaciones

- La instrumentación toca puntos sensibles del typechecker; debe probar equivalencia de HIR
  y no alterar elección semántica.
- Retener facts y AST aumenta memoria del snapshot; debe medirse antes de optimizar.
- El parser fail-fast impide Document Symbols sobre syntax inválida y completion contextual
  general.
- No existe estabilidad cross-snapshot general ni documentación source oficial.
- References no puede prometer workspace total fuera del grafo exacto analizado.
- Rename no está autorizado por este cierre.

## 10. Archivos creados

- `docs/architecture/EDITOR_SYMBOL_SERVICES_ARCH_1.md`
- `docs/architecture/EDITOR_SYMBOL_SERVICES_ARCH_1_REPORT.md`

No se modificó código productivo, manifests, tests, LSP, Python, `compiler-rs`, IDEs ni
packaging.

## 11. Cierre

La arquitectura define identidades sin persistencia ficticia, conserva la autoridad del
frontend, reutiliza source mapping/lifecycle, hace explícitos los gaps de spans/references y
recovery, y propone APIs implementables con un primer milestone acotado. Por ello se declara
**ARCH CLOSED**. Este reporte no inicia implementación.
