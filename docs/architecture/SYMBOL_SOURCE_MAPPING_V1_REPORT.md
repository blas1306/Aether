# SYMBOL-SOURCE-MAPPING-V1 — reporte de implementación y qualification

Estado: **CLOSED**, 2026-11-26.

Arquitectura de origen:
[EDITOR_SYMBOL_SERVICES_ARCH_1](EDITOR_SYMBOL_SERVICES_ARCH_1.md).

## 1. Alcance cerrado

Este milestone agrega provenance exacta y hechos semánticos snapshot-locales para el primer
subconjunto de declaraciones source-facing: funciones top-level, structs y enums. No agrega
handlers, capabilities LSP, consultas de Document Symbols, resolución alternativa, recovery,
índices persistentes ni estabilidad general entre snapshots.

El frontend Rust continúa siendo la única autoridad. `aether-analysis` valida y posee los
hechos junto con el HIR, el catálogo de sources y el stamp que los produjo. No se modificaron
Python, `compiler-rs`, LSP, driver, middle, backend, manifests ni locks.

## 2. Preflight, separación y preservación

- Branch inicial: `main`.
- HEAD y `origin/main` iniciales: `961427e6fb71ac5aad94c4e4a8658a0c248d93bd`, sin
  divergencia observada.
- Los documentos pendientes de `EDITOR-SYMBOL-SERVICES-ARCH-1` estaban untracked y se
  separaron como dependencia documental anterior.
- La implementación del milestone quedó limitada a `aether-frontend`, `aether-analysis`, su
  test de integración y este reporte.
- Se preservaron sin staging ni edición los cambios personales tracked de
  `examples/ProbandoNR/probandoNR2.ae` y `probandoNR3.ae`.
- También se excluyeron `examples/ProbandoNR`, `scrap/`, `.vscode/`, locks de examples,
  binarios, targets, caches, reproducers y temporales personales observados en el status.
- No se ejecutaron push, reset, clean ni stash.

## 3. Emisión autoritativa

El parser conserva ahora el token exacto del nombre en:

- `Parser::function_decl` / `function_tail` para `AstFunction::name_span`;
- `Parser::struct_decl` para `AstStruct::name_span`;
- `Parser::enum_decl` para `AstEnum::name_span`.

Funciones generadas por el compilador (`init`, wrappers y el sentinel de análisis de
librería) usan `name_span: None`; nunca reciben una ubicación fuente ficticia.

`collect_program_signatures_for_kind` llama a `collect_declaration_facts` sólo después de
completar y validar el namespace, tipos declarados, signatures, overloads, entry point y
metadata OOP. La función recorre las identidades ya aceptadas por el frontend:

- `FunctionSignature` produce `CompilerEntityId::Function`, owner módulo y
  `LogicalDeclarationKey::PackageMember(signature.symbol_key(...))`;
- `StructInfo` produce `CompilerEntityId::Struct`, owner módulo y sin clave lógica
  inventada;
- `EnumInfo` produce `CompilerEntityId::Enum`, owner módulo y sin clave lógica inventada.

Cada fact toma el `SourceId` de `ModuleInfo.source`, el full span de la metadata oficial y
el name span del AST correspondiente. Se ordenan determinísticamente por módulo, full span
y entidad. Funciones sintéticas (`$...` o sin `name_span`) quedan fuera.

Si collection rechaza una declaración, retorna antes de construir `DeclaredProgram`; si
typing o `verify_hir` fallan, `CanonicalAnalyzer` retorna `Partial + Invalid` con
`semantic: None`. La regresión con dos overloads idénticos comprueba `E0211`, stage
`Declarations` y ausencia total de `SemanticFacts` publicables.

## 4. Validación de spans e identidades

`aether-analysis::symbols::validate_declaration_facts` es la frontera fail-closed previa a
crear un `SemanticSnapshot`. Para cada fact comprueba:

1. `full_span.source == name_span.source == fact.source`;
2. rangos half-open ordenados y name span contenido en full span;
3. source presente en el `SourceTable` del análisis;
4. ambos spans convertibles por el `LineIndex` del mismo texto, incluidos boundaries UTF-8;
5. slice exacto del texto igual al nombre declarado;
6. `ModuleId` existente, source concordante y `SourceUnitKey` igual al catálogo;
7. owner top-level igual a `CompilerEntityId::Module(fact.module)`;
8. variante de kind/entity correcta e ID denso presente en la arena correspondiente;
9. módulo, nombre y full span iguales a la metadata HIR oficial;
10. `SymbolKey` oficial exacto para funciones y ausencia de clave lógica fabricada para
    structs/enums.

Una discrepancia produce `AnalysisFailure::Internal`; no se entrega un snapshot semántico
parcial. La qualification corrompe un name span fuera del source y confirma el rechazo.
El caso Unicode/CRLF convierte `main` después de acentos, combining mark y emoji al rango
UTF-16 exacto mediante el `LineIndex` existente.

## 5. Ownership por snapshot

`SemanticSnapshot` posee en una sola unidad inmutable:

- `SnapshotStamp`;
- `Arc<SourceTable>`;
- `Arc<SemanticFacts>` ya validado;
- el `TypedHir` exacto contra el que se validó.

Los campos son privados y sólo se construyen en el camino `Complete + Valid`. `stamp()`,
`facts()` y `hir()` permiten al consumidor mantener la frontera explícita. Los IDs densos no
incorporan identidad temporal ni se comparan aisladamente entre ejecuciones.

La regresión cross-snapshot edita sólo el body de `main`: ambos snapshots contienen el
mismo valor numérico `FunctionId(0)`, pero tienen stamps distintos y objetos semánticos
distintos. Por tanto la igualdad del ID no afirma identidad entre snapshots. Una clave
lógica oficial puede compararse según su contrato propio, nunca como sustituto del stamp.

## 6. Cobertura real

| Categoría | Estado V1 |
| --- | --- |
| funciones top-level source | instrumentada; full/name span, módulo, owner, ID y `SymbolKey` |
| structs top-level | instrumentada; full/name span, módulo, owner e ID snapshot-local |
| enums top-level | instrumentada; full/name span, módulo, owner e ID snapshot-local |
| sintéticos/sentinel/lambdas lowering | excluidos explícitamente |
| imports y aliases | no instrumentados |
| parámetros, locals y type parameters | no instrumentados |
| struct fields y enum variants | no instrumentados |
| classes, interfaces, methods, constructors y requirements | no instrumentados |
| referencias, scopes, targets, overrides y witnesses | no instrumentados |
| recovery y declaraciones rechazadas | no publican facts |

Los tests cubren determinismo, exclusión de lambdas sintéticas, funciones/structs/enums,
genéricos en declaraciones, exactitud de slices, Unicode/combining/emoji/CRLF, source mapping
UTF-16, corrupción, imports con overlays, módulos con nombres iguales, rechazo de
declarations e IDs repetidos entre snapshots. Esto no equivale a cobertura de todos los
servicios de símbolos previstos por la arquitectura.

## 7. Extensión sin cambiar contratos

Las categorías pendientes se agregan en los puntos autoritativos que ya eligen identidad:

- parser/AST conservará name spans de imports, aliases, fields, variants, parámetros,
  locals, clases, interfaces y methods;
- collection agregará nuevas variantes de `CompilerEntityId` y `DeclarationKind` sólo
  cuando exista un ID/owner oficial, sin ampliar unilateralmente `SymbolKey`;
- typing emitirá facts de referencia y scope al resolver cada name/member/call, sin recorrer
  texto ni volver a resolver por spelling;
- `aether-analysis::symbols` validará esos facts contra las arenas y owners del mismo HIR y
  derivará índices inmutables;
- `SourceTable`, `LineIndex`, `SnapshotStamp`, `AnalysisState` y los publication gates
  actuales permanecen como contratos únicos.

La extensión será aditiva: `SemanticFacts` gana colecciones tipadas y validadores; no cambia
la resolución existente ni convierte IDs densos en persistentes. `DOCUMENT-SYMBOLS-V1` no
se inicia con este cierre.

## 8. Resolución, diagnósticos y HIR observables

La revisión del diff confirmó que los cambios del frontend son captura aditiva de tokens de
nombre, metadata owned y copia de los facts al `TypedHir`. No se cambió lookup, scope,
selección de overload, inferencia, typing, ownership, lowering de expresiones, códigos/rangos
de diagnósticos ni construcción de funciones HIR.

Los paths sintéticos sólo recibieron `name_span: None`; el sentinel conserva exactamente su
función anterior. La suite completa del frontend, la suite de analysis y el diferencial
oficial conservan sus resultados. El único HIR observable nuevo es la metadata intencional
accesible mediante `TypedHir::semantic_facts`; no cambian nodos, targets ni semántica
preexistentes.

## 9. Qualification ejecutada en este cierre

Resultados ejecutados en esta sesión, 2026-11-26:

- `cargo test -p aether-frontend`: PASS — 98 unit, 2 integration, 0 failures; doc-tests 0.
- `cargo test -p aether-analysis`: PASS — 40 unit, 0 failures; doc-tests 0.
- Focales previos al run completo: PASS — 2 tests de integración frontend y los tests de
  Unicode/corrupción, overlay importado, aislamiento cross-snapshot y declarations
  rechazadas de analysis. Se registran como ejecuciones separadas aunque luego quedaron
  subsumidas por las suites completas.
- `cargo check --workspace`: PASS.
- `cargo clippy --workspace --all-targets -j 1`: PASS con warnings existentes del workspace
  (`large_enum_variant` en frontend y warnings no relacionados en middle/CLI/driver).
- Ejecución adicional `cargo clippy ... -- -D warnings`: FAIL por convertir el warning
  existente `large_enum_variant` de `HirStmtKind` en error. No es el gate prescrito ni un
  warning introducido por este milestone; se conserva el resultado y no se presenta como
  PASS.
- `cargo fmt --all --check`: PASS.
- `cargo tree -p aether-analysis --edges normal` y `cargo tree -p aether-frontend --edges
  normal`: PASS de frontera; sólo frontend/package y dependencias de infraestructura, sin
  driver, middle, backend, Python ni `compiler-rs`.
- `bash tests/test-differential-harness.sh`: PASS.
- `bash tests/run-differential.sh`: PASS — `mode=official checked=96 failures=0`.
- `git diff --check`: PASS antes de crear este reporte; se repite en el gate Git final.

Los archivos ignored `collect_*.txt` inspeccionados pertenecen a evidencia personal antigua
y ajena a este milestone; no se usan ni se presentan como qualification reejecutada. Los
resultados documentales históricos de `EDITOR-SYMBOL-SERVICES-ARCH-1` se conservan en su
reporte y tampoco se reinterpretan como tests de implementación.

## 10. Archivos del milestone

- `compiler-next/crates/aether-frontend/src/ast.rs`
- `compiler-next/crates/aether-frontend/src/parser.rs`
- `compiler-next/crates/aether-frontend/src/hir.rs`
- `compiler-next/crates/aether-frontend/src/hir/classes.rs`
- `compiler-next/crates/aether-frontend/src/lib.rs`
- `compiler-next/crates/aether-frontend/tests/symbol_source_mapping.rs`
- `compiler-next/crates/aether-analysis/src/lib.rs`
- `compiler-next/crates/aether-analysis/src/diagnostics.rs`
- `compiler-next/crates/aether-analysis/src/symbols.rs`
- `docs/architecture/SYMBOL_SOURCE_MAPPING_V1_REPORT.md`

## 11. Cierre

La emisión ocurre después de aceptar declarations, la validación une cada fact al HIR y al
texto exactos, el snapshot conserva el stamp que da alcance a los IDs densos, los errores no
exponen facts semánticos y la qualification mantiene resolución, diagnósticos y comportamiento
oficial. Las categorías no instrumentadas quedan explícitas y tienen una ruta aditiva sin
cambiar los contratos actuales.

Por ello `SYMBOL-SOURCE-MAPPING-V1` queda **CLOSED**. No se inicia
`DOCUMENT-SYMBOLS-V1`.
