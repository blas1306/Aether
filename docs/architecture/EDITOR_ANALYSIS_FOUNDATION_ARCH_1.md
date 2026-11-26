# EDITOR-ANALYSIS-FOUNDATION-ARCH-1 — servicios editoriales nativos

Estado: **CLOSED; ARQUITECTURA ACEPTADA; IMPLEMENTACIÓN NO INICIADA**,
2026-11-25.

Reporte de evidencia:
[EDITOR_ANALYSIS_FOUNDATION_ARCH_1_REPORT](EDITOR_ANALYSIS_FOUNDATION_ARCH_1_REPORT.md).

Este documento define el contrato interno de análisis editorial sobre
`compiler-next`. No implementa un servidor LSP, no cambia la semántica del
lenguaje y no convierte un resultado parcial en una compilación exitosa.

La autoridad es [COMPILER_AUTHORITY](COMPILER_AUTHORITY.md): `compiler-next` y
los contratos CLOSED vigentes son normativos. El frontend Python,
`compiler-rs` y el LSP Python son solamente evidencia histórica. En particular,
ningún componente definido aquí puede importar, ejecutar o comparar su
resultado con esas implementaciones para decidir aceptación semántica.

## 1. Alcance y decisiones cerradas

La arquitectura cierra estas decisiones:

1. Habrá un crate interno `aether-analysis`, sin ABI ni protocolo público.
   Contendrá el workspace editorial, documentos, snapshots, source mapping y
   la orquestación frontend. El catálogo/sesión canónicos hoy privados del
   driver se reubicarán allí; `aether-driver` los consumirá y podrá reexportar
   temporalmente los nombres existentes.
2. Batch y editor usarán una sola construcción de catálogo, imports,
   `ParsedProgram` e identidades. Un `SourceProvider` hará inyectable el
   contenido, pero no decidirá semántica de imports.
3. Un snapshot posee texto inmutable de todos sus inputs. El overlay gana al
   disco dentro de ese snapshot, incluso para módulos importados.
4. `DocumentVersion`, revisión del workspace, versión de package y los IDs
   densos del compilador son dominios diferentes y no intercambiables.
5. La primera implementación recalculará el grafo semántico completo afectado.
   No requiere parsing incremental ni una base de queries.
6. Los offsets de `Span` continúan siendo bytes UTF-8. La capa editorial los
   convierte con un índice explícito a líneas y unidades UTF-16.
7. El frontend existente conserva autoridad sobre diagnostics, tipos,
   ownership y HIR. La capa editorial agrega envelope, severidad, relaciones y
   estado de cobertura; no reescribe diagnostics ni fabrica HIR.
8. La cancelación V1 ocurre sólo en fronteras seguras. El trabajo batch ya
   iniciado puede terminar y luego descartarse. Supresión por obsolescencia no
   se denomina cancelación.
9. El primer recorrido termina después de análisis frontend. No baja a MIR,
   SSA, LLVM ni toolchain.

El estado CLOSED significa que existe un diseño implementable y acotado. No
afirma que el servicio, crate o LSP ya existan.

## 2. Autoridad e invariantes heredadas

Esta arquitectura preserva:

- [MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md): `PackageKey` y `SourceUnitKey` son
  identidades lógicas; `PackageId`, `ModuleId` y `SourceId` son densos de
  sesión; aliases son bindings locales y no identidades alternativas.
- [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md) y sus verticales de
  identidad/lock: una instancia resuelta tiene identidad exacta, cada owner
  resuelve sus edges y un build/check no selecciona versiones silenciosamente.
- Los contratos CLOSED de ownership, tipos, closures, excepciones y
  verificadores HIR. Un modo editorial no los relaja.
- `SourceId` identifica provenance dentro de una sesión. Un path absoluto, una
  URI o el orden de discovery no se convierten en identidad semántica pública.
- La colección de declaraciones globales precede al análisis de bodies. Un
  archivo abierto no gana precedencia sobre otro; sólo aporta contenido más
  reciente al mismo source unit lógico.
- La raíz `std` pertenece a toolchain y no puede ser suplantada por un overlay.

Invariantes nuevos:

- Cada `AnalysisSnapshot` observa una sola revisión coherente de overlays,
  proyecto y configuración.
- Cada `SourceId` de un resultado se resuelve en la tabla de sources del mismo
  snapshot; nunca mediante búsqueda por `source_name` solamente.
- Un resultado sólo puede publicarse contra las versiones para las que fue
  calculado.
- `Complete` describe cobertura, no éxito. `Valid` describe validez. Son ejes
  separados.
- Ningún cache devuelve objetos con `SourceId`, `ModuleId`, `FunctionId` o
  `TypeId` de otra sesión salvo que toda la sesión propietaria sea la entrada
  cacheada.

## 3. Inventario técnico actual

### 3.1 APIs reutilizables

| Área | API actual | Visibilidad/contrato | Uso editorial |
|---|---|---|---|
| Source | `SourceFile`, `SourceId`, `Span` | pública en `aether-frontend` | reutilización directa dentro de cada sesión; mapping externo adicional |
| Lexing | `lex(&SourceFile)` | pública; conserva tokens/spans y acumula varios errores | directa |
| Parsing | `parse`, `parse_source` | públicas; `ParsedAst` público con construcción restringida | directa, inicialmente fail-fast |
| Declaraciones | `collect_signatures`, `collect_program_signatures`, variante library | públicas | directa sobre el `ParsedProgram` canónico |
| Semántica | `analyze`, `analyze_bodies`, `analyze_bodies_for_target` | públicas | directa; target explícito; sin lowering posterior |
| Verificación | `verify_hir` | pública | permanece obligatoria en resultados HIR válidos |
| Diagnóstico | `Diagnostic`, `DiagnosticCategory`, `Phase`, `FixIt` | públicas y estructuradas | se preservan y adaptan, no se renderizan a texto antes de tiempo |
| Módulos | `PackageKey`, `SourceUnitKey`, `ModuleInfo`, `ResolvedImport`, `ParsedModule`, `ParsedProgram` | públicos en frontend | identidades y programa canónicos |
| Símbolos | `SymbolKey`, `FunctionId`, `FunctionSignature::symbol_key` y IDs nominales | públicos; IDs densos son session-local | claves canónicas sí; IDs densos sólo dentro del snapshot |
| Sesión | `CompilationSession::discover`, `modules`, `entry`, `source_root` | pública en driver; construcción y AST internos | lógica a reubicar/adaptar; no sirve directamente para overlays |
| Check | `check_path` | pública en driver | no usar: baja hasta MIR/SSA y depende de capas no editoriales |
| Proyecto | `ProjectPlan`, `ResolvedGraph`, `ResolvedPackage`, `PackageInstanceKey` | públicas | validar frontera de proyecto y conservar identidad exacta |
| Package/lock | `resolve`, `sync`, `update` | públicas; `sync` puede escribir lock y usar registry | no llamar automáticamente desde análisis; falta lectura read-only |

### 3.2 Mecanismos internos, no contratos reutilizables todavía

`discover_catalog_with_plan`, `CatalogUnit`, `SourceCandidate`,
`collect_source_paths`, la inyección de sources de toolchain y
`CompilationSession::into_parsed_program` son privados de `aether-driver`.
Actualmente mezclan enumeración, `fs::read_to_string`, parsing, resolución de
packages, mediciones y creación de IDs. Son la implementación oficial actual,
pero su forma privada no es una API editorial estable.

En modo standalone discovery lee el entry, sigue imports de packages del
proyecto y agrega sources alcanzables. Con `ProjectPlan` enumera y parsea los
sources de todas las instancias resueltas. En ambos casos lee filesystem
directamente y se detiene ante el primer source que no puede parsear.

El frontend no ofrece hoy:

- source provider inyectable;
- análisis incremental o cache pública;
- token de cancelación;
- parser con recovery/syntax tree parcial;
- colección general de errores semánticos;
- índice persistente de símbolos/referencias;
- identidad estable de símbolo entre sesiones para todos los declarations;
- coordenadas UTF-16;
- severidad o notas relacionadas dentro de `Diagnostic`.

Estas ausencias son requisitos de adaptación o trabajo futuro, no permiso para
duplicar semántica en `aether-analysis`.

## 4. Capas y dependencias

La dirección decidida es:

```text
aether-package
      ↓
aether-frontend
      ↓
aether-analysis   (catálogo canónico + frontend orchestration + editor state)
      ↓
aether-driver     (MIR/SSA/backend/toolchain para batch)

futuro aether-lsp → aether-analysis
```

`aether-analysis` depende de `aether-frontend` y, cuando necesite tipos que el
frontend no reexporta, de `aether-package`. No depende de `aether-middle`,
`aether-backend-llvm`, `aether-driver`, clang, Python ni `compiler-rs`.

Se reubican, sin bifurcar, `CompilationSession`, `SessionModule`, `ProjectPlan`,
`StandaloneFile` y la construcción de catálogo que corresponda a esta frontera.
El driver pasa a depender de la nueva capa y conserva su pipeline posterior.
Durante la migración puede hacer `pub use aether_analysis::CompilationSession`;
no se promete estabilidad pública porque todo `compiler-next` sigue siendo una
frontera interna del producto.

No se elige una API dentro de `aether-frontend`: documentos, filesystem,
packages resueltos, snapshots y scheduling son orquestación, no semántica del
lenguaje. Tampoco se deja dentro de `aether-driver`, porque eso obligaría al
servicio editorial a depender de backend y middle.

## 5. Documentos y workspace

### 5.1 Identidades

```rust
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct WorkspaceId(u64);

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ProjectId(u64);

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct DocumentId(u64);

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct DocumentVersion(u64);

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum DocumentLocator {
    File {
        logical_path: PathBuf,
        canonical_path: Option<PathBuf>,
    },
    Virtual { uri: Arc<str> },
}
```

`DocumentId` se asigna una vez por locator y no se reutiliza durante la vida del
workspace. Un close no cambia esa identidad. La URI es locator/provenance, no
`PackageKey`, `SourceUnitKey` ni `SymbolKey`.

Para un archivo existente, `canonical_path` evita que aliases de symlink creen
dos documentos. Para un archivo nuevo todavía inexistente, `logical_path` es
absoluto y normalizado léxicamente dentro del workspace y `canonical_path` es
`None`; al aparecer en disco se completa la relación sin cambiar `DocumentId`.

`DocumentVersion` es monotónica por documento y pertenece al store. Puede
retener la versión del cliente como metadata, pero la corrección interna usa la
versión propia. No se compara con `PackageVersion`, SemVer o lock version.

### 5.2 Registro

```rust
pub struct DocumentRecord {
    pub id: DocumentId,
    pub locator: DocumentLocator,
    pub version: DocumentVersion,
    pub client_version: Option<i64>,
    pub state: DocumentState,
    pub project: Option<ProjectId>,
}

pub enum DocumentState {
    Open {
        text: Arc<str>,
        disk_base: DiskBase,
        dirty: bool,
    },
    Closed {
        disk_base: DiskBase,
    },
}

pub enum DiskBase {
    Present { fingerprint: ContentFingerprint },
    Missing,
    NotApplicable,
}
```

El texto abierto es siempre completo en V1. Los edits incrementales LSP podrán
aplicarse antes de llegar al store, pero el snapshot guarda `Arc<str>` completo.
El estado de análisis no vive mutable dentro del record; se conserva como
`LastAnalysis` separado y siempre etiquetado con su `SnapshotStamp`.

### 5.3 Transiciones

| Operación | Efecto |
|---|---|
| open | crea o reutiliza `DocumentId`, incrementa versión, instala overlay y asocia proyecto si puede resolverse inequívocamente |
| change | exige documento abierto, reemplaza texto, incrementa versión y marca dirty; un client version regresivo se rechaza |
| save | no presupone que el cliente haya escrito correctamente: refresca fingerprint de disco si existe, conserva el overlay abierto como autoridad y actualiza dirty por igualdad |
| close | retira el overlay; siguientes snapshots leen disco. Se conserva locator→`DocumentId` y metadata mínima |
| delete en disco, documento abierto | el overlay continúa analizable con `DiskBase::Missing`; imports pueden resolverlo mientras el snapshot lo incluya |
| delete en disco, documento cerrado | el provider informa missing; se invalida catálogo y los importadores reciben diagnóstico canónico |

Si una URI virtual no tiene `SourceUnitKey` asignable por configuración, puede
analizarse como source standalone aislado, pero no satisfacer imports. No se
infieren packages desde el texto de un documento `untitled` para insertarlo en
un proyecto real.

## 6. Providers, overlays y módulos

### 6.1 Frontera canónica

```rust
pub trait SourceProvider: Send + Sync {
    fn enumerate(&self, scope: &SourceScope)
        -> Result<Vec<SourceDescriptor>, SourceProviderError>;
    fn read(&self, locator: &SourceLocator)
        -> Result<SourceContent, SourceProviderError>;
}

pub struct SourceContent {
    pub text: Arc<str>,
    pub fingerprint: ContentFingerprint,
    pub provenance: SourceProvenance,
}

pub enum SourceProvenance {
    Overlay { document: DocumentId, version: DocumentVersion },
    Disk { canonical_path: PathBuf, fingerprint: ContentFingerprint },
    Toolchain { logical_name: Arc<str>, fingerprint: ContentFingerprint },
}
```

`DiskSourceProvider` reemplaza los accesos directos del loader actual.
`OverlaySourceProvider<DiskSourceProvider>` sólo resuelve contenido y
enumeración: para un locator mapeado a documento abierto devuelve el overlay;
en otro caso delega al disco. La construcción del catálogo, validación de
package declarations, imports, aliases, toolchain sources e identidades ocurre
una sola vez en el código canónico compartido.

El provider entrega listas ordenables; la sesión las normaliza y ordena por
`SourceUnitKey`. Un provider no asigna `ModuleId`/`SourceId`, no interpreta un
`AstImport` y no crea `ResolvedImport`.

### 6.2 Prioridad y snapshot

Para cada locator la precedencia es:

1. source toolchain inmutable si el locator pertenece a toolchain; el store
   rechaza asociarle un documento editable;
2. overlay abierto capturado por el snapshot para sources de proyecto;
3. contenido de disco capturado por lectura del mismo snapshot;
4. error missing.

No se mezclan dos versiones del mismo documento en un análisis. El snapshot
captura el mapa completo de overlays bajo un lock corto, lo libera y realiza
IO/análisis usando estructuras inmutables. Un cambio simultáneo crea una
revisión posterior, no muta el snapshot en curso.

Archivos no abiertos se leen del provider de disco. Overlays de módulos
importados tienen la misma prioridad que el entry. Varios overlays no guardados
participan juntos si pertenecen a la revisión capturada.

### 6.3 Imports y cambios de topología

- Un import nuevo obliga a reconstruir discovery/resolution. Si el target está
  en otro overlay se usa ese texto; si no, se consulta disco/toolchain.
- Eliminar un import reconstruye grants y dependencies. El módulo puede seguir
  en el catálogo de un proyecto eager, pero deja de ser visible/dependencia si
  la semántica canónica así lo determina.
- Modificar alias no cambia la identidad target. `ResolvedImport.target` y
  `SymbolKey` permanecen canónicos.
- Cambiar `package` puede cambiar `SourceUnitKey`, provocar colisiones o dejar
  imports sin target; se trata como cambio de topología, no como simple body
  edit.
- Dependencias transitivas se resuelven desde el mismo provider/snapshot. No se
  permite que una lectura tardía vea un overlay posterior.
- Dos locators que reclamen la misma unidad lógica, o una unidad bajo dos
  aliases, no crean dos módulos; se conserva la validación fail-closed.

### 6.4 Packages y locks

`ProjectSnapshot` contiene un `ProjectPlan`/grafo exacto ya validado y una
`ProjectGeneration`. La carga editorial será read-only:

- lock válido: usar exactamente sus instancias/materializaciones;
- lock ausente, inválido o desactualizado: producir error de proyecto con una
  acción sugerida, sin ejecutar `sync`/`update` ni escribir archivos;
- packages registry no materializados: error de proyecto; el análisis no hace
  red implícita;
- cambio de manifest/lock: nueva generación e invalidación del catálogo.

Hace falta adaptar `aether-package` con una operación read-only de validación de
lock o separar la parte pura hoy interna de `sync`. No se implementará un lector
TOML/lock paralelo en `aether-analysis`.

## 7. Snapshot, request y ownership

```rust
pub struct EditorWorkspace {
    id: WorkspaceId,
    state: RwLock<WorkspaceState>,
    next_request: AtomicU64,
}

#[derive(Clone)]
pub struct AnalysisSnapshot {
    pub stamp: SnapshotStamp,
    overlays: Arc<OverlayMap>,
    projects: Arc<ProjectMap>,
    config: Arc<AnalysisConfig>,
    caches: Arc<AnalysisCaches>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotStamp {
    pub workspace: WorkspaceId,
    pub revision: u64,
    pub document_versions: Arc<[(DocumentId, DocumentVersion)]>,
    pub project_generations: Arc<[(ProjectId, u64)]>,
}

pub struct AnalysisRequest {
    pub id: RequestId,
    pub target: AnalysisTarget,
    pub snapshot: AnalysisSnapshot,
    pub cancellation: CancellationToken,
}

pub enum AnalysisTarget {
    Document(DocumentId),
    Entry(SourceUnitKey),
    Project(ProjectId),
}
```

El workspace posee estado mutable pequeño. Snapshot, textos, proyecto y
resultados son owned mediante `Arc`; no exponen referencias ligadas al lock del
workspace ni lifetimes de buffers del protocolo. La sesión frontend creada por
una request posee `SourceFile`, AST, arena de tipos y HIR hasta terminar o
transferir el resultado.

`SourceId` se asigna determinísticamente al construir la sesión y se acompaña
de:

```rust
pub struct SourceTable {
    by_id: Vec<SnapshotSource>,
}

pub struct SnapshotSource {
    pub source_id: SourceId,
    pub identity: SourceIdentity,
    pub unit: Option<SourceUnitKey>,
    pub text: Arc<str>,
    pub line_index: Arc<LineIndex>,
}
```

`SourceIdentity` distingue documento, disk externo y toolchain. Es estable para
presentación dentro del workspace; no reemplaza las identidades semánticas.

## 8. Resultado y diagnostics

### 8.1 Estado explícito

```rust
pub struct AnalysisResult {
    pub request: RequestId,
    pub stamp: SnapshotStamp,
    pub state: AnalysisState,
    pub diagnostics: Vec<EditorDiagnostic>,
    pub semantic: Option<Arc<SemanticSnapshot>>,
    pub measurements: AnalysisMeasurements,
}

pub struct AnalysisState {
    pub coverage: AnalysisCoverage,
    pub validity: AnalysisValidity,
}

pub enum AnalysisCoverage {
    Complete,
    Partial { reached: AnalysisStage, reason: PartialReason },
}

pub enum AnalysisValidity { Valid, Invalid, Unknown }
pub enum AnalysisStage { Input, Lex, Parse, Declarations, Semantic }
pub enum PartialReason { FrontendStopped, Cancelled, MissingInput, InternalFailure }
```

Sólo `Complete + Valid` admite `semantic: Some`. `Complete + Invalid` se
reservará para una futura fase que garantice haber recorrido toda su unidad aun
en presencia de errores. Con el frontend actual, cualquier error de parser,
declarations o body es conservadoramente `Partial + Invalid`. Cancelación e ICE
son `Partial + Unknown` y no se publican como diagnostics normales de source.

`Complete + Valid` significa únicamente “frontend editorial solicitado
completo y HIR verificado”. `AnalysisResult` no tiene un estado
`CompilationSuccess`: al no ejecutar MIR, SSA, backend o toolchain, nunca
afirma que una compilación nativa completa haya terminado exitosamente.

Un último resultado válido puede conservarse para features tolerantes, pero se
marca `HistoricalSemantic { based_on: old_stamp }`; nunca se mezcla con los
diagnostics actuales ni se presenta como análisis de la versión nueva.

### 8.2 Envelope editorial

```rust
pub struct EditorDiagnostic {
    pub source: Option<SourceIdentity>,
    pub range: Option<EditorRange>,
    pub code: Arc<str>,
    pub severity: DiagnosticSeverity,
    pub phase: Phase,
    pub category: DiagnosticCategory,
    pub message: Arc<str>,
    pub related: Vec<RelatedInformation>,
    pub fixes: Vec<EditorFix>,
}

pub enum DiagnosticSeverity { Error, Warning, Information, Hint }
```

La adaptación conserva `Diagnostic::{code, phase, category, message, span,
source_name, fixits}`. Hoy los `Diagnostic` devueltos por el frontend son
errores; se mapean a `Error`. No se infiere warning desde el texto. Tipos como
`ClosureCaptureWarning` necesitarán una conversión explícita cuando formen
parte del resultado oficial.

`source_name` es display/fallback. Un `Span` se resuelve primero por `SourceId`
en `SourceTable`. Un diagnostic sin span puede ser de proyecto/workspace. Si el
ID no pertenece a la tabla, la request falla internamente; no se atribuye el
error al documento target.

El frontend no tiene notas relacionadas generales. `related` estará vacío salvo
que una API autoritativa entregue spans secundarios. No se extraen notas desde
strings. Cada `FixIt` se convierte contra el texto exacto del snapshot; si su
span está fuera de rango o no cae en boundaries UTF-8 válidos, se omite el fix y
se registra un fallo interno de adaptación, sin desplazarlo heurísticamente.

### 8.3 UTF-8 y UTF-16

`Span::{start,end}` es un rango half-open en bytes UTF-8. `SourceFile::line_column`
devuelve línea/columna one-based en Unicode scalars y sirve para rendering batch;
no es una posición LSP.

`LineIndex` guarda starts de líneas en bytes y checkpoints por línea. La
conversión byte→editor:

1. valida `offset <= text.len()` y boundary UTF-8;
2. encuentra la línea por binary search del último start no posterior;
3. cuenta `char::len_utf16()` desde el start/checkpoint;
4. devuelve línea zero-based y character zero-based en code units UTF-16.

La conversión inversa rechaza una posición dentro del segundo code unit de un
surrogate pair, una línea inexistente o una columna posterior al fin lógico de
línea. CRLF cuenta como un único corte de línea; ninguna posición editable se
normaliza cambiando bytes. Un range se convierte sólo si ambos extremos son
válidos y pertenecen al mismo source.

## 9. Recovery seguro

La auditoría del frontend actual da este límite:

| Fase | Conducta actual | Estado editorial V1 |
|---|---|---|
| lex | recorre el source y puede acumular varios `Diagnostic`; algunos errores terminales detienen el resto | publicar todos los obtenidos; no parsear porque `lex` devuelve `Err` sin tokens admitidos |
| parse | recursive descent; casi todos los errores retornan inmediatamente y `parse` devuelve un solo diagnostic | publicar ese error; no construir AST parcial |
| discovery | parsea source por source con `?`/`map_err`; un source inválido aborta la sesión | resultado parcial; no resolver semántica con grafo incompleto |
| declarations | varias validaciones son fail-fast aunque algunas subrutinas acumulan | preservar exactamente los diagnostics devueltos; sin HIR |
| bodies | analiza funciones secuencialmente y retorna ante el primer fallo de una función/fase | parcial e inválido; no conservar prefijo HIR como programa válido |
| verifier | un rechazo es fallo semántico/interno según su origen | nunca relajar ni saltar verifier |

Recovery mínimo del primer vertical:

- múltiples errores léxicos ya soportados;
- un error sintáctico autoritativo por intento;
- análisis semántico sólo cuando todas las unidades requeridas tienen AST
  completo y la colección de declarations tuvo éxito;
- ningún placeholder AST/HIR, tipo `Unknown`, symbol inventado o verifier
  deshabilitado;
- errors de otros sources pueden agregarse únicamente si cada source fue
  lexed/parsed de forma independiente por las APIs oficiales y la sesión se
  marca parcial. Esto es opcional para el primer recorrido, no un gate.

Recovery de múltiples errores sintácticos requiere un milestone del parser con
puntos de sincronización probados. No pertenece a esta arquitectura ni se
simula saltando tokens en el servicio editorial.

## 10. Cache e invalidación

El primer vertical puede usar sólo:

- `LineIndex` por `(SourceIdentity, ContentFingerprint)`;
- texto/fingerprint por snapshot;
- opcionalmente tokens/AST completos por `(SourceUnitKey, fingerprint,
  frontend_epoch)` si el AST conserva su source mapping propietario.

El resultado semántico V1 se cachea, si se hace, como sesión completa por una
clave que incluya grafo de packages, ordered source keys+fingerprints, target y
compiler epoch. No se injertan AST/HIR entre sesiones cambiando IDs.

Para corrección inicial, cualquier cambio de texto invalida discovery y el
análisis semántico del target completo. Es deliberadamente conservador y cubre
imports/package declarations nuevos o eliminados. Más adelante, un resultado
completo puede aportar reverse dependencies mediante
`ModuleInfo::semantic_dependencies`, pero éstas describen el grafo anterior y
no bastan para decidir que un texto modificado no agregó un edge. Antes de
parsear el cambio siempre se invalida su topología.

No hay cache persistente en este milestone. Determinismo y corrección preceden
a granularidad de invalidación.

## 11. Cancelación, concurrencia y publicación

```rust
#[derive(Clone)]
pub struct CancellationToken(Arc<AtomicBool>);

impl CancellationToken {
    pub fn cancel(&self);
    pub fn is_cancelled(&self) -> bool;
    pub fn checkpoint(&self) -> Result<(), Cancelled>;
}
```

Checkpoints seguros V1:

- antes de crear/enqueue la request;
- después de capturar el snapshot;
- antes/después de enumerar catálogo;
- entre lecturas de sources;
- antes/después de lex/parse de cada unidad;
- entre discovery, declarations y bodies;
- inmediatamente después de una llamada batch no cancelable;
- antes de construir/publicar el resultado.

No se inserta polling dentro de lexer/parser/typechecker en el primer
milestone. Si la cancelación llega durante `analyze_bodies_for_target`, esa
llamada puede terminar; su resultado se descarta en el siguiente checkpoint.
Esto es cancelación cooperativa de request, no preemption del cómputo interno.

La primera implementación usa un worker de análisis serial por workspace. Las
ediciones continúan capturándose mientras trabaja porque la request sólo usa su
snapshot. Se permiten varias requests en cola; una nueva puede cancelar tokens
anteriores. Paralelizar sesiones es una optimización posterior porque cada
sesión ya posee sus arenas y sources, pero no es gate del recorrido inicial.

Publicación exige atómicamente:

1. que la request sea la última solicitada para ese target;
2. que el target siga abierto/aplicable;
3. que `SnapshotStamp` coincida con la revisión publicable actual.

V1 puede exigir igualdad de revisión completa, aun si cambió un archivo no
relacionado. Es conservador. Un resultado que falla este gate es `Stale` y se
descarta; no se muta ni se publica como cancelado. Cancelled, stale, invalid e
internal failure son estados distintos.

Una request se ejecuta dentro de un boundary que convierte panics recuperables
en `AnalysisFailure::Internal`, siempre que el perfil permita unwind. No se
reutiliza estado mutable de la sesión fallida. El workspace y los siguientes
snapshots permanecen utilizables. No se expone backtrace o datos sensibles al
diagnóstico de source.

## 12. Operaciones internas propuestas

```rust
impl EditorWorkspace {
    pub fn open(&self, input: OpenDocument) -> Result<DocumentId, StoreError>;
    pub fn change(&self, input: ChangeDocument) -> Result<DocumentVersion, StoreError>;
    pub fn saved(&self, input: SavedDocument) -> Result<DocumentVersion, StoreError>;
    pub fn close(&self, document: DocumentId) -> Result<(), StoreError>;
    pub fn filesystem_changed(&self, change: FileChange) -> Result<(), StoreError>;
    pub fn snapshot(&self) -> AnalysisSnapshot;
    pub fn request(&self, target: AnalysisTarget) -> AnalysisRequest;
    pub fn may_publish(&self, result: &AnalysisResult) -> PublishDecision;
}

pub trait Analyzer {
    fn analyze(&self, request: AnalysisRequest)
        -> Result<AnalysisResult, AnalysisFailure>;
}

pub struct CanonicalAnalyzer;
```

`CanonicalAnalyzer` construye la sesión por el loader compartido, llama a
`lex`/`parse_source`, `collect_*_signatures`,
`analyze_bodies_for_target` y conserva `verify_hir`. La operación no acepta
flags para omitir ownership/type checks, no emite LLVM y no ejecuta toolchain.

`SemanticSnapshot` es un tipo interno owned que puede contener `TypedHir`,
`SourceTable` y tablas de lookup derivadas. Esta arquitectura no congela una
API de completion/hover/references y no expone el HIR como ABI.

## 13. Primer recorrido vertical posterior

`EDITOR-ANALYSIS-FOUNDATION-V1` será una implementación pequeña:

1. crear `aether-analysis` con document store, snapshot, source provider e
   índice UTF-16;
2. reubicar/adaptar la sesión y catálogo canónicos desde `aether-driver` y
   hacer que el driver batch los consuma;
3. analizar un documento standalone abierto cuyo overlay difiere del disco;
4. resolver un módulo importado desde disco;
5. sustituir ese módulo por su overlay no guardado dentro del mismo snapshot;
6. devolver diagnostics estructurados de lex/parse/semantic con rangos y
   fix-its convertidos;
7. etiquetar cobertura/validez y descartar un resultado stale;
8. probar checkpoints de cancelación antes/entre fases;
9. compilar/probar el crate sin dependencias de middle/backend, LLVM, clang,
   Python o `compiler-rs`.

No incluye LSP/JSON-RPC, completion, hover, rename, formatting, semantic
tokens, index persistente, parsing incremental, REPL, JIT ni cambio de lenguaje.

## 14. Qualification y gates

### 14.1 Tests nuevos

| Suite propuesta | Gates |
|---|---|
| `document_store.rs` | ID estable tras close/reopen; versión monotónica; client version regresiva; save/dirty; delete abierto/cerrado; SemVer no afecta DocumentVersion |
| `overlay_provider.rs` | overlay gana a disco; unopened usa disco; varios overlays coherentes; virtual sin mapping no satisface import |
| `module_overlay.rs` | import directo/transitivo; overlay en importado; import agregado/eliminado; alias conserva target; package declaration cambiada invalida topología |
| `source_mapping.rs` | ASCII, acentos, combining marks, CJK, astral/emoji, CRLF, EOF; ida/vuelta UTF-8↔UTF-16; rechazo de mid-codepoint y mid-surrogate |
| `editor_diagnostics.rs` | source identity, code, phase, category, severity, primary range, source-less project diagnostic, related vacías, fix-it exacto y fix-it corrupto rechazado |
| `recovery.rs` | múltiples lex errors; parser fail-fast etiquetado partial; no semantic/HIR con syntax error; semantic failure partial; verifier nunca omitido |
| `snapshot_consistency.rs` | dos documentos cambian alrededor de capture; ningún snapshot mezcla versiones; stale result no se publica |
| `cancellation.rs` | cancel antes de iniciar, entre sources y entre fases; cancel durante fase batch termina en descarte; siguiente request funciona |
| `internal_failure.rs` | provider error, SourceId inválido y panic boundary no contaminan workspace ni aparecen como éxito |
| `determinism.rs` | mismo mapa de inputs en distinto orden produce IDs, diagnostics y fingerprints iguales |
| `semantic_preservation.rs` | disk-only editor result acepta/rechaza igual que frontend/driver canónico para corpus seleccionado; sin oracle legacy |
| `dependency_boundary.rs` | `cargo tree`/metadata confirma ausencia de middle/backend/LLVM; ejecución con `PATH` sin clang y entorno sin Python/compiler-rs |

### 14.2 Tests existentes reutilizables

- unit tests de lexer: byte spans, comentarios, Unicode y ubicación exacta;
- parser `malformed_syntax_is_structured` y negativos de firmas;
- `module_std_v1.rs`: packages parciales, aliases, grants, identidad lógica y
  raíz `std`;
- `package_ergonomics_v1.rs`: anonymous/named, imports, spelling de path e
  identidad independiente del checkout;
- `aether-package/tests/resolution.rs`: resolución determinista, multiversión,
  lock fail-closed y topología;
- suites de diagnostics/ownership en `aether-driver/tests`, ejecutadas por la
  ruta batch compartida para detectar divergencia después de reubicar loader.

Los tests editoriales no invocan el LSP Python ni usan el frontend Python como
golden.

### 14.3 Medición inicial

Sin fijar budgets antes de observar datos, el vertical registrará por lo menos
p50/p95 y máximo de:

- captura de snapshot;
- enumeración/lectura;
- lex+parse;
- declarations;
- semantic bodies;
- mapping de diagnostics;
- tiempo total y tiempo desperdiciado por stale/cancel.

Medirá bytes de texto retenido, `LineIndex`, AST/sesión/cache y peak RSS cuando
sea reproducible. Habrá un corpus pequeño de un source y otro multiarchivo con
imports transitivos y overlays. Se documentarán máquina, build profile, número
de runs, warm/cold cache y tamaño del corpus. Los resultados son baseline, no
PASS/FAIL arbitrario.

## 15. Riesgos y contenciones

| Riesgo | Contención |
|---|---|
| duplicar loader/semántica | reubicar la implementación canónica y hacer que batch dependa de ella |
| atribuir diagnostics al texto equivocado | `SourceTable` snapshot-local; nunca lookup primario por nombre/path |
| publicar información parcial como válida | ejes `coverage`/`validity`, semantic sólo en Complete+Valid |
| stale HIR o IDs cruzados | ownership de sesión y cache de sesión completa |
| imports nuevos evaden invalidación | todo cambio de source invalida topología V1 |
| lock/network modifica proyecto al editar | carga read-only; error y acción sugerida |
| Unicode desplaza rangos | índice byte↔UTF-16 probado, sin cast de offsets |
| cancelación aparente | distinguir checkpoints, trabajo no preemptible y stale suppression |
| ICE corrompe requests futuras | sesión local, boundary y descarte completo |
| dependencia accidental de LLVM/legacy | DAG de crates y gate de dependencias |

## 16. Alternativas descartadas

- **Reusar el LSP/frontend Python:** no normativo y produciría una segunda
  semántica.
- **Escribir un loader editorial separado:** divergirían packages, aliases,
  toolchain, locks e identidades.
- **Parchar archivos temporales en disco y llamar `check_path`:** rompe
  snapshots, watchers, identidad y seguridad; además baja a MIR/SSA.
- **Colocar overlays dentro de `SourceFile::new` para el entry solamente:** no
  cubre imports transitivos ni múltiples documentos abiertos.
- **Depender de `aether-driver` desde analysis:** arrastra middle/backend y crea
  la capa en dirección incorrecta.
- **Usar path/URI como `ModuleId` o symbol identity:** contradice los contratos
  de packages/source units y falla con aliases/materializaciones.
- **Tratar byte column como UTF-16:** incorrecto para Unicode no ASCII.
- **Continuar typechecking después de parse errors con nodos inventados:**
  debilita invariantes y falsea ownership/tipos.
- **Cancelar threads a la fuerza:** puede interrumpir invariantes internas; V1
  usa checkpoints y descarte.
- **Introducir Salsa/Tower/Tokio o un crate LSP ahora:** dependencias y
  complejidad no justificadas por el recorrido fundacional.

## 17. Dependencias futuras explícitas

Después de V1, y sólo mediante milestones separados:

- recovery sintáctico autoritativo y colección semántica multi-error;
- invalidación incremental basada en queries/fingerprints;
- identidades completas de declarations y reference index;
- APIs de symbols, definition, references, completion y hover;
- scheduler paralelo y cancelación interna cooperativa;
- protocolo LSP Rust y negociación de capabilities;
- code actions sobre fix-its, semantic tokens y workspace index persistente.

Ninguna de estas dependencias bloquea el recorrido vertical cerrado en §13.
