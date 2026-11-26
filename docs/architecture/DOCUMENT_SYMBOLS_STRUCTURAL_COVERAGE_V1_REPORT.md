# DOCUMENT-SYMBOLS-STRUCTURAL-COVERAGE-V1 — reporte de implementación y qualification

Estado: **CLOSED**, 2026-11-26.

Arquitectura de origen:
[EDITOR_SYMBOL_SERVICES_ARCH_1](EDITOR_SYMBOL_SERVICES_ARCH_1.md).
Milestones de origen:
[SYMBOL_SOURCE_MAPPING_V1_REPORT](SYMBOL_SOURCE_MAPPING_V1_REPORT.md) y
[DOCUMENT_SYMBOLS_V1_REPORT](DOCUMENT_SYMBOLS_V1_REPORT.md).

## 1. Alcance cerrado

La consulta interna `SemanticSnapshot::document_symbols` conserva las raíces V1 y agrega la
jerarquía source-facing completa que posee identidad oficial en el frontend actual:

- `Struct -> Field`;
- `Enum -> Variant`;
- `Class -> Field, Method, Initializer`;
- `Interface -> Requirement`.

Funciones top-level, structs y enums permanecen sin cambio de identidad. Clases e interfaces son
nuevas raíces. No se agregó handler `textDocument/documentSymbol`, capability LSP ni otra consulta
editorial.

## 2. Identidades oficiales

`CompilerEntityId` representa directamente las arenas existentes:

| Categoría | Identidad frontend snapshot-local |
| --- | --- |
| función top-level | `FunctionId` |
| struct | `StructId` |
| campo de struct o clase | `FieldId` |
| enum | `EnumId` |
| variante | `VariantId { enum_id, index }` |
| clase | `ClassId` |
| método / inicializador explícito | `FunctionId` |
| interface | `InterfaceId` |
| requisito | `RequirementId { interface, index }` |

Los métodos e inicializadores conservan además el `SymbolKey` ya producido por su
`FunctionSignature`. No se fabricaron claves lógicas para las demás categorías. `VirtualSlotId`,
`WitnessId`, witness slots, wrappers, lambdas, el `Exception` core-owned y los inicializadores
implícitos sin token fuente quedan excluidos.

## 3. Spans y emisión frontend

El parser retiene ahora el token exacto del identificador en campos, variantes, clases,
interfaces y requisitos. Los métodos e inicializadores reutilizan el `name_span` de
`AstFunction`. El full span de cada requisito fue corregido para abarcar la declaración completa
hasta `;`, sin alterar parsing ni semántica.

`collect_declaration_facts` emite sólo después de que collection haya aceptado y tipado las
identidades. Cada hecho contiene entidad, clase, nombre, source, módulo, full/name spans, owner y
clave lógica cuando existe. La asociación usa IDs, índices y spans preservados por AST/HIR; no
usa indentación ni reconstruye owners por spelling. Los facts se ordenan por módulo, posición e
identidad.

## 4. Ownership y jerarquía

Las raíces tienen owner `ModuleId`. Los miembros apuntan a la entidad nominal exacta:

- campos de struct a `StructId`;
- variantes a `EnumId`;
- campos, métodos e inicializadores a `ClassId`;
- requisitos a `InterfaceId`.

`document_symbols` materializa primero ubicaciones del source solicitado y después agrupa por
esa relación autoritativa. Raíces y children se ordenan por posición fuente e identidad. Un owner
ausente, de otra clase o no materializable causa `InternalFailure`; nunca produce una jerarquía
aproximada. No se exige containment entre el full span del owner y sus miembros.

## 5. Validación fail-closed

La frontera de `SemanticFacts` conserva los checks V1 de source, módulo, texto exacto, boundaries
UTF-8, conversión UTF-16, full/name containment y metadata HIR. Además valida por arena:

- clase exacta de `DeclarationKind` y `CompilerEntityId`;
- existencia de cada ID y correspondencia de nombre/full span;
- owner nominal, source y módulo exactos;
- índice y owner embebidos en `VariantId` y `RequirementId`;
- pertenencia de `FieldId` a exactamente una arena de campos de struct o clase;
- pertenencia del `FunctionId` de método/inicializador a la clase y categoría correcta;
- clave lógica exacta de cada callable;
- unicidad global de cada `CompilerEntityId` dentro del snapshot.

Los discriminantes de `CompilerEntityId` separan las arenas nominales. Una duplicación o
corrupción de identidad/owner rechaza el snapshot antes de publicarlo.

## 6. Snapshots, overlays y errores

No cambió el gate `Complete + Valid`, el `SnapshotStamp`, el catálogo `SourceTable` ni el lifecycle
de publicación. Overlays no guardados producen facts, rangos y versión del snapshot nuevo; stale,
cancelación, target cerrado, cambio externo, source desconocido o toolchain conservan sus razones
`Unavailable`. Errores sintácticos o semánticos no publican jerarquías parciales ni facts viejos.

## 7. Tests

Las regresiones focales cubren:

- varios campos, variantes y orden fuente;
- clases con campos, métodos e inicializadores explícitos;
- herencia, override e implementación de interfaces;
- interfaces y requisitos;
- miembros con el mismo nombre bajo owners distintos;
- genéricos, imports, módulos distintos y entidades homónimas;
- Unicode, combining marks, emoji, CRLF y rangos UTF-16;
- overlays, stamps, versiones, lifecycle stale y análisis inválido;
- determinismo de roots/children;
- exclusión de lambdas, core class, inicializadores implícitos y nombres `$...`;
- corrupción de owner e identidad duplicada;
- preservación de funciones top-level, structs y enums.

Los tests existentes de frontend, analysis, lifecycle y workspace cubren además corrupción HIR,
semántica de herencia/interfaces y ausencia de regresiones observables.

## 8. Qualification

Ejecutada el 2026-11-26:

- focales `aether-analysis::symbols`: PASS — 9/9;
- `cargo test -p aether-frontend`: PASS — 98 unit + 2 integration;
- `cargo test -p aether-analysis`: PASS — 49/49;
- `cargo test -p aether-lsp`: PASS — 4 unit + 5 integration;
- `cargo check --workspace`: PASS;
- `cargo test --workspace -j 1`: PASS, incluidas todas las suites y doc-tests;
- `cargo fmt --all --check`: PASS;
- `cargo clippy --workspace --all-targets -j 1`: PASS con warnings preexistentes en frontend,
  middle, CLI y tests de driver;
- focal `cargo clippy -p aether-analysis --all-targets`: PASS sin warnings nuevos de analysis;
- `cargo tree -p aether-analysis --edges normal`: PASS; sin dependencias nuevas;
- `bash tests/test-differential-harness.sh`: PASS;
- `bash tests/run-differential.sh`: PASS — `mode=official checked=96 failures=0`;
- `git diff --check`: PASS.

## 9. Limitaciones explícitas

Sólo se publican inicializadores escritos con token `init`. El inicializador vacío sintetizado
para una clase sin `init` no es source-facing y se excluye. El `Exception` inyectado por core se
excluye por no tener `name_span`. No existen otros constructores source-facing distintos de
`init` en el frontend actual.

No se instrumentaron aliases, imports, type parameters, parámetros, locals, scopes ni referencias.
No se modificaron selección de métodos, herencia, dispatch, override, genéricos, witnesses,
diagnósticos, ABI, HIR observable fuera de metadata source-facing ni recovery.

## 10. Archivos modificados

- `compiler-next/crates/aether-frontend/src/ast.rs`
- `compiler-next/crates/aether-frontend/src/interfaces.rs`
- `compiler-next/crates/aether-frontend/src/oop.rs`
- `compiler-next/crates/aether-frontend/src/parser.rs`
- `compiler-next/crates/aether-frontend/src/hir.rs`
- `compiler-next/crates/aether-frontend/src/hir/classes.rs`
- `compiler-next/crates/aether-frontend/tests/symbol_source_mapping.rs`
- `compiler-next/crates/aether-analysis/src/symbols.rs`
- `docs/architecture/DOCUMENT_SYMBOLS_STRUCTURAL_COVERAGE_V1_REPORT.md`

No se modificaron Python legacy, `compiler-rs`, LSP, manifests, locks, IDEs ni defaults. No se
realizó reset, clean, stash, commit ni push. El cambio personal concurrente observado al cierre en
`examples/ProbandoNR/probandoNR4.ae` se preservó sin editar, revertir ni incluir en este milestone.

## 11. Commit sugerido

`feat(analysis): add structural document symbol hierarchy`

## 12. Cierre

Todas las categorías implementadas usan identidades oficiales, cada miembro conserva su owner
real, los spans y rangos son exactos, roots y children son deterministas, y los gates de snapshots
y overlays permanecen fail-closed. No aparecen símbolos sintéticos ni capacidades/handlers nuevos.
La qualification completa y el diferencial oficial pasan.

Por ello `DOCUMENT-SYMBOLS-STRUCTURAL-COVERAGE-V1` queda **CLOSED**. No se inicia el milestone
siguiente.
