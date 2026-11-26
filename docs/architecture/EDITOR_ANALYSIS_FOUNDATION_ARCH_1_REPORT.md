# EDITOR-ANALYSIS-FOUNDATION-ARCH-1 — reporte de cierre

Estado: **CLOSED; ARQUITECTURA ACEPTADA; IMPLEMENTACIÓN NO INICIADA**,
2026-11-25.

Documento normativo:
[EDITOR_ANALYSIS_FOUNDATION_ARCH_1](EDITOR_ANALYSIS_FOUNDATION_ARCH_1.md).

Checkout auditado: `main` @ `eec746d53520` con cambios personales preexistentes
preservados.

## 1. Resultado

Se cerró una arquitectura de servicios editoriales nativos sobre
`compiler-next` sin implementar código productivo ni un servidor LSP.

La decisión principal es crear en un milestone posterior un crate interno
`aether-analysis` situado entre frontend/package y driver. La construcción de
`CompilationSession`/catálogo hoy alojada en el driver se reubicará allí y será
consumida tanto por batch como por editor. Un `SourceProvider` inyectable
seleccionará overlay, toolchain o disco; no resolverá imports ni asignará
identidades. Así no aparece un segundo loader semántico.

El contrato incluye:

- documentos con identidad estable, versión propia, overlay y relación con
  disco/proyecto;
- snapshots owned e inmutables de todos los documentos abiertos;
- overlays transitivos y coherentes para módulos importados;
- packages/locks exactos en modo read-only, sin red o escrituras implícitas;
- diagnostics estructurados que preservan los records del frontend;
- conversión validada de byte offsets UTF-8 a coordenadas UTF-16;
- cobertura y validez separadas para impedir falsos éxitos;
- recovery mínimo compatible con el frontend fail-fast actual;
- cancelación por checkpoints y stale suppression como conceptos distintos;
- un recorrido vertical sin MIR, SSA, LLVM, clang, Python ni `compiler-rs`.

## 2. Fuentes auditadas

Se revisaron:

- `COMPILER_AUTHORITY.md`;
- `LEGACY_TOOLS_FUTURE_AUDIT_V1.md` y su reporte;
- `MODULE_STD_ARCH_1.md` y reportes de package identity/lock;
- contratos CLOSED de lenguaje, ownership, closures, exceptions y
  diagnostics aplicables;
- manifests y fuentes de `aether-frontend`, `aether-driver` y
  `aether-package`;
- `SourceFile`, `SourceId`, `Span`, `Diagnostic`, `FixIt` y `Phase`;
- lexer, parser, colección de declarations, HIR/typechecking y verifier;
- `CompilationSession`, discovery, `ProjectPlan`, `ResolvedGraph` y locks;
- tests actuales de lexer/parser, módulos, packages, diagnostics, ownership y
  determinismo.

El frontend Python se examinó únicamente a través de la auditoría legacy para
entender el producto anterior. No se usó como autoridad ni como oracle.

## 3. Hallazgos de implementación

| Área | Hallazgo comprobado | Consecuencia de diseño |
|---|---|---|
| lexing | `lex` es público, conserva byte spans y acumula varios errors | reutilización directa; resultado parcial si falla |
| parsing | `parse`/`parse_source` son públicos pero retornan al primer error | un diagnostic sintáctico, sin AST inventado |
| semantic | `collect_*_signatures` y `analyze_bodies_for_target` son públicos; muchos caminos son fail-fast | no prometer colección completa; HIR sólo en éxito completo |
| verification | `verify_hir` forma parte del éxito de `analyze_bodies_for_target` | ningún modo editorial lo omite |
| diagnostics | code, phase, category, message, span, source name y fix-its ya son estructurados | envelope editorial, no parsing del render textual |
| severity/notes | no están en `Diagnostic`; los diagnostics retornados representan errors | mapping explícito a Error; related vacío hasta que exista fuente autoritativa |
| source mapping | spans son bytes; `line_column` cuenta Unicode scalars y es one-based | índice separado UTF-16 obligatorio |
| discovery | el driver enumera/lee filesystem y parsea dentro de una función privada | reubicar y parametrizar; no envolver sólo el entry |
| imports | `ParsedProgram`, `ResolvedImport`, `PackageKey` y `SourceUnitKey` ya expresan el modelo oficial | conservar estas identidades bajo aliases/overlays |
| packages | package graph exacto es reusable, pero `sync` puede crear lock y consultar registry | falta una carga/validación read-only oficial |
| symbols | existen keys canónicas parciales e IDs densos session-local | no prometer todavía índice estable cross-session |
| caching | no existe cache frontend pública | full reanalysis correcto en V1 |
| cancellation | no hay polling/token en componentes batch | checkpoints entre fases y descarte posterior |

También se comprobó que `check_path` no es la frontera editorial correcta:
después del frontend construye/verifica MIR y SSA. El servicio nuevo termina en
HIR y por estructura de crates no arrastra backend/toolchain.

## 4. Decisiones de identidad y ownership

- `DocumentId` es estable durante la vida del workspace y sobrevive
  close/reopen del mismo locator.
- `DocumentVersion` es monotónica y no se confunde con SemVer de packages.
- `SourceId`, `ModuleId`, `PackageId`, `FunctionId` y `TypeId` permanecen
  session-local.
- URI/path son locators y provenance, no identidad pública de package/symbol.
- `PackageKey`, `SourceUnitKey`, `PackageInstanceKey` y `SymbolKey` conservan
  su significado actual.
- Snapshots, textos, line indices y resultados usan ownership/`Arc`; una
  request no retiene guards ni referencias al store mutable.
- Un cache nunca separa valores densos de la sesión que los posee.

## 5. Decisiones de overlays

La prioridad cerrada es toolchain inmutable para sus locators, overlay abierto
para sources editables, disco y finalmente missing. La selección ocurre en el
provider; resolución de imports y validación de packages continúan en el loader
canónico. El store rechaza overlays que intenten suplantar un source toolchain.

Un overlay nuevo o modificado invalida topología completa en V1. Esto cubre
imports agregados/eliminados, aliases, cambios de package y módulos importados
no guardados. Los archivos cerrados se leen de disco. Un archivo abierto que
fue borrado sigue existiendo como overlay hasta close. Un virtual sin mapping
de proyecto no puede aparecer mágicamente como import target.

El snapshot captura todos los overlays antes de hacer IO/análisis y nunca
mezcla versiones. La publicación compara stamps; un resultado obsoleto se
descarta aun si terminó correctamente.

## 6. Decisiones de diagnostics y recovery

El envelope editorial agrega source identity, rango editor, severidad, related
information, fixes y estado de análisis sin alterar el `Diagnostic` original.
La tabla `SourceId → SnapshotSource` es la autoridad para resolver spans.
`source_name` queda como display/fallback y no puede atribuir por sí solo un
diagnostic a un documento.

Coverage y validity son independientes:

- sólo `Complete + Valid` entrega semantic snapshot actual;
- errors léxicos/sintácticos/semánticos del frontend actual son
  conservadoramente `Partial + Invalid`;
- cancellation/ICE son `Partial + Unknown`;
- semantic data histórico, si se retiene, lleva el stamp anterior y no se
  presenta como resultado actual.

Incluso `Complete + Valid` sólo afirma éxito del frontend editorial y HIR
verificado. El resultado no se denomina compilación exitosa porque no ejecuta
MIR, SSA, backend ni toolchain.

Recovery V1 no agrega nodos. Reutiliza múltiples diagnostics léxicos, acepta el
parser fail-fast y sólo ejecuta semántica si todos los AST requeridos son
completos. No relaja ownership, tipos, monomorphization ni verificación HIR.

## 7. Cancelación y concurrencia

La primera implementación tendrá un worker serial por workspace y snapshots
inmutables. Los checkpoints ocurren antes/después de discovery, cada source y
cada fase frontend. Una cancelación recibida dentro de una fase batch no la
preempta; el resultado se descarta al volver.

Se distinguen explícitamente:

- cancelación solicitada/observada;
- resultado stale por revisión posterior;
- programa inválido;
- source/provider error;
- internal failure.

Un failure no reutiliza la sesión local. Una request posterior puede analizar
normalmente el workspace.

## 8. Qualification cerrada

El documento normativo define suites para identidad/versionado, overlays,
imports transitivos, source mapping UTF-8/UTF-16, diagnostics/fix-its, recovery,
stale results, cancelación, ICE/provider errors, determinismo y preservación
semántica.

Se reutilizarán especialmente:

- tests unitarios del lexer/parser;
- `module_std_v1.rs`;
- `package_ergonomics_v1.rs`;
- `aether-package/tests/resolution.rs`;
- suites de diagnostics y ownership del driver.

El gate de dependencias verificará que `aether-analysis` no dependa de middle,
backend o LLVM y que sus pruebas funcionen sin clang, Python ni compiler-rs.
La comparación de aceptación usa exclusivamente la ruta canónica Rust.

Se medirán latencia por fase, total, trabajo descartado y memoria para un corpus
pequeño y otro multiarchivo. Este cierre no inventa thresholds antes de medir.

## 9. Riesgos abiertos, no bloqueantes

- La reubicación del loader toca una frontera pública interna del driver y debe
  preservar todos sus tests batch.
- Hace falta extraer del package manager una validación read-only del lock; no
  se autoriza duplicarla.
- El parser y body analysis actuales limitan la cantidad de diagnostics útiles
  por edición.
- Full graph reanalysis puede resultar costoso; la baseline decidirá el
  milestone incremental posterior.
- Las identidades de symbols todavía no cubren un reference index persistente.
- Panic recovery depende del panic profile; abort sigue siendo terminación de
  proceso, no un error recuperable.

Estos puntos tienen extensiones claras y no impiden implementar el recorrido
V1 delimitado.

## 10. Alternativas rechazadas

Se rechazaron el frontend/LSP Python, un loader editorial paralelo, archivos
temporales + `check_path`, overlays sólo para el entry, dependencia de analysis
hacia driver, paths como IDs semánticos, casts byte→UTF-16, HIR parcial
fabricado, cancelación forzada de threads y una dependencia prematura de un
framework LSP/query/async.

## 11. Validación de este milestone

- Se crearon únicamente los dos documentos solicitados.
- No se modificó código productivo, tests, manifests, locks, Python,
  `compiler-rs`, IDEs ni packaging.
- No se agregaron dependencias ni se eliminó ningún archivo.
- No se inició el crate, el recorrido V1 ni el servidor LSP.
- Se preservaron todos los cambios personales ya presentes en el worktree.
- No se hizo commit ni push.

Por estas razones se declara **ARCH CLOSED** y no implementación completada.
